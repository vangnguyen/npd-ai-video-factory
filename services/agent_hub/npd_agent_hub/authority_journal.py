"""Durable authority journal abstraction with an explicit LOCAL SQLite fixture.

No Redis/S3 driver or production activation. Existing journals are never created
on read/open. SQL writes serialize once, preserve exact snapshots and receipt
prefixes, and never retry an uncertain/conflicting commit. Checkpoints must be
independently retained before any production restore may become authoritative.
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Protocol
from uuid import UUID, uuid4

from .retention_custody import CustodyBlocked

SCHEMA = "npd.agent-hub.custody.authority-journal.local-sql.v1"
DOMAIN = b"npd.agent-hub.custody.journal-commit.v1\0"
ZERO = "0" * 64
ORDER = {"HOLD_REQUEST": 0, "ARCHIVE_WRITE": 1, "CUSTODY_VERIFY": 2, "CUSTODY_COMMIT": 3}


def sql_failure(error, committing=False):
    # Extended BUSY/LOCKED codes retain their primary code in the low byte.
    code = getattr(error, "sqlite_errorcode", None)
    conflict = isinstance(code, int) and (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
    return ("AUTHORITY_JOURNAL_COMMIT_UNCERTAIN_HOLD_NO_RETRY" if committing else
            "AUTHORITY_JOURNAL_CONCURRENCY_CONFLICT_NO_RETRY" if conflict else
            "AUTHORITY_JOURNAL_BACKEND_ERROR_HOLD")


def raw_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf8", errors="strict")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf8", errors="strict"), object_pairs_hook=unique,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        if raw_json(value) != raw:
            raise ValueError("noncanonical snapshot")
        return value
    except (ValueError, TypeError, UnicodeError) as error:
        raise CustodyBlocked("AUTHORITY_JOURNAL_CORRUPT_HOLD") from error


def empty_snapshot():
    return {"schema": SCHEMA, "receipts": [], "seen_token_ids": [], "transactions": {}}


def validate_extension(previous, current):
    if (not isinstance(current, dict) or set(current) != set(empty_snapshot())
        or current["schema"] != SCHEMA or not isinstance(current["receipts"], list)
        or not isinstance(current["transactions"], dict) or not isinstance(current["seen_token_ids"], list)):
        raise CustodyBlocked("AUTHORITY_JOURNAL_UNKNOWN_STATE_HOLD")
    if any(not isinstance(token, str) for token in current["seen_token_ids"]):
        raise CustodyBlocked("AUTHORITY_JOURNAL_UNKNOWN_TOKEN_STATE_HOLD")
    if (current["receipts"][:len(previous["receipts"])] != previous["receipts"]
        or not set(previous["seen_token_ids"]) <= set(current["seen_token_ids"])
        or len(current["seen_token_ids"]) != len(set(current["seen_token_ids"]))):
        raise CustodyBlocked("AUTHORITY_JOURNAL_PREFIX_OR_REPLAY_CORRUPT_HOLD")
    for custody_id, prior in previous["transactions"].items():
        now = current["transactions"].get(custody_id)
        if not isinstance(now, dict):
            raise CustodyBlocked("AUTHORITY_JOURNAL_TRANSACTION_REMOVED_HOLD")
        if (any(now.get(k) != prior.get(k) for k in ("input_sha256", "requester"))
            or any(prior.get(k) is not None and now.get(k) != prior[k]
                   for k in ("custodian", "verifier", "archive_sha256"))
            or type(now.get("consumed")) is not bool or (prior.get("consumed") and not now["consumed"])
            or now.get("state") not in ORDER or ORDER[now["state"]] < ORDER.get(prior.get("state"), 99)
            or type(now.get("expires_at")) is not int or now["expires_at"] > prior["expires_at"]):
            raise CustodyBlocked("AUTHORITY_JOURNAL_TRANSACTION_CHANGED_HOLD")


@dataclass(frozen=True)
class JournalCheckpoint:
    journal_id: str
    sequence: int
    commit_sha256: str
    state_sha256: str


class AuthorityJournal(Protocol):
    journal_id: str
    trust_sha256: str
    synthetic_local_only: bool
    def atomic(self): ...
    def read_snapshot(self) -> dict: ...
    def checkpoint(self) -> JournalCheckpoint: ...


@dataclass(frozen=True)
class LocalJournalScope:
    fixture_root: Path

    def path(self, name):
        root = self.fixture_root
        temp_root = Path(tempfile.gettempdir()).resolve()
        if (not isinstance(root, Path) or not root.is_absolute() or root.is_symlink()
            or not root.is_dir() or root.resolve() == temp_root
            or not root.resolve().is_relative_to(temp_root)
            or not isinstance(name, str) or Path(name).name != name or name in {"", ".", ".."}
            or ":" in name or "\\" in name or "/" in name):
            raise CustodyBlocked("LOCAL_AUTHORITY_FIXTURE_SCOPE_REQUIRED")
        path = root.resolve() / name
        if path.is_symlink():
            raise CustodyBlocked("AUTHORITY_JOURNAL_SYMLINK_DENIED")
        return path


class SQLiteFixtureAuthorityJournal:
    """Actual local disk transactions, no production/network filesystem support."""
    synthetic_local_only = True

    def __init__(self, *, scope: LocalJournalScope, name: str, journal_id: str,
                 trust_sha256: str, minimum_checkpoint: JournalCheckpoint,
                 production_mode=False):
        if production_mode:
            raise CustodyBlocked("PRODUCTION_AUTHORITY_JOURNAL_NOT_ACCEPTED_HOLD")
        try:
            if (str(UUID(journal_id)) != journal_id or len(trust_sha256) != 64
                or trust_sha256.lower() != trust_sha256 or len(bytes.fromhex(trust_sha256)) != 32
                or not isinstance(minimum_checkpoint, JournalCheckpoint)
                or minimum_checkpoint.journal_id != journal_id
                or type(minimum_checkpoint.sequence) is not int or minimum_checkpoint.sequence < 0):
                raise ValueError()
            for digest in (minimum_checkpoint.commit_sha256, minimum_checkpoint.state_sha256):
                if len(digest) != 64 or digest.lower() != digest or len(bytes.fromhex(digest)) != 32:
                    raise ValueError()
        except (ValueError, TypeError, AttributeError) as error:
            raise CustodyBlocked("AUTHORITY_JOURNAL_BINDING_INVALID") from error
        self.scope = scope
        self.name = name
        self.journal_id = journal_id
        self.trust_sha256 = trust_sha256
        self.minimum_checkpoint = minimum_checkpoint
        self.unavailable = False  # deterministic local outage fixture, never prod config.
        self.read_snapshot()  # Missing/unknown/corrupt state stops before any authority.

    @classmethod
    def create_fixture(cls, *, scope, name="authority.sqlite", trust_sha256):
        path = scope.path(name)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        journal_id = str(uuid4())
        connection = sqlite3.connect(path, isolation_level=None, timeout=0)
        try:
            if connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
                raise CustodyBlocked("AUTHORITY_JOURNAL_DURABILITY_CONFIG_DRIFT_HOLD")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("CREATE TABLE commits (sequence INTEGER PRIMARY KEY, previous_sha256 TEXT NOT NULL, state BLOB NOT NULL, state_sha256 TEXT NOT NULL, commit_sha256 TEXT NOT NULL)")
            connection.executemany("INSERT INTO metadata VALUES (?,?)", [
                ("schema", SCHEMA), ("journal_id", journal_id), ("trust_sha256", trust_sha256)])
            raw = raw_json(empty_snapshot())
            state_sha = sha(raw)
            tip = sha(DOMAIN + raw_json([journal_id, trust_sha256, 0, ZERO, state_sha]))
            connection.execute("INSERT INTO commits VALUES (?,?,?,?,?)", (0, ZERO, raw, state_sha, tip))
            connection.commit()
        finally:
            connection.close()
        checkpoint = JournalCheckpoint(journal_id, 0, tip, state_sha)
        return cls(scope=scope, name=name, journal_id=journal_id, trust_sha256=trust_sha256,
                   minimum_checkpoint=checkpoint)

    def _connect(self, write=False):
        path = self.scope.path(self.name)
        if self.unavailable:
            raise CustodyBlocked("AUTHORITY_JOURNAL_BACKEND_UNAVAILABLE_HOLD")
        if not path.is_file():
            raise CustodyBlocked("AUTHORITY_JOURNAL_MISSING_HOLD")
        # URI mode=rw/ro never creates a missing database; no memory fallback.
        connection = sqlite3.connect(path.as_uri() + ("?mode=rw" if write else "?mode=ro"),
                                     uri=True, isolation_level=None, timeout=0)
        connection.execute("PRAGMA busy_timeout=0")
        if connection.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
            connection.close()
            raise CustodyBlocked("AUTHORITY_JOURNAL_DURABILITY_CONFIG_DRIFT_HOLD")
        if write:
            connection.execute("PRAGMA synchronous=FULL")
            if connection.execute("PRAGMA synchronous").fetchone()[0] != 2:
                connection.close()
                raise CustodyBlocked("AUTHORITY_JOURNAL_DURABILITY_CONFIG_DRIFT_HOLD")
        else:
            connection.execute("PRAGMA query_only=ON")
        return connection

    def _load(self, connection):
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise CustodyBlocked("AUTHORITY_JOURNAL_CORRUPT_HOLD")
        meta = dict(connection.execute("SELECT key,value FROM metadata"))
        if meta != {"schema": SCHEMA, "journal_id": self.journal_id, "trust_sha256": self.trust_sha256}:
            raise CustodyBlocked("AUTHORITY_JOURNAL_IDENTITY_OR_TRUST_DRIFT_HOLD")
        previous = empty_snapshot()
        prior_tip = ZERO
        checkpoint = None
        count = 0
        for sequence, parent, raw, state_sha, tip in connection.execute("SELECT * FROM commits ORDER BY sequence"):
            if sequence != count or parent != prior_tip or not isinstance(raw, bytes) or sha(raw) != state_sha:
                raise CustodyBlocked("AUTHORITY_JOURNAL_CHAIN_OR_DIGEST_MISMATCH_HOLD")
            expected = sha(DOMAIN + raw_json([self.journal_id, self.trust_sha256, sequence, parent, state_sha]))
            if tip != expected:
                raise CustodyBlocked("AUTHORITY_JOURNAL_CHAIN_OR_DIGEST_MISMATCH_HOLD")
            state = strict_json(raw)
            validate_extension(previous, state)
            checkpoint = JournalCheckpoint(self.journal_id, sequence, tip, state_sha)
            if self.minimum_checkpoint and self.minimum_checkpoint.sequence == sequence:
                if self.minimum_checkpoint != checkpoint:
                    raise CustodyBlocked("AUTHORITY_JOURNAL_CHECKPOINT_MISMATCH_HOLD")
            previous = state
            prior_tip = tip
            count += 1
        if checkpoint is None or (self.minimum_checkpoint and
            (self.minimum_checkpoint.journal_id != self.journal_id or checkpoint.sequence < self.minimum_checkpoint.sequence)):
            raise CustodyBlocked("AUTHORITY_JOURNAL_ROLLBACK_OR_EMPTY_HOLD")
        return previous, checkpoint

    def _append_commit(self, connection, previous, state, checkpoint):
        validate_extension(previous, state)
        raw = raw_json(state)
        state_sha = sha(raw)
        tip = sha(DOMAIN + raw_json([self.journal_id, self.trust_sha256,
            checkpoint.sequence + 1, checkpoint.commit_sha256, state_sha]))
        connection.execute("INSERT INTO commits VALUES (?,?,?,?,?)", (
            checkpoint.sequence + 1, checkpoint.commit_sha256, raw, state_sha, tip))

    @contextmanager
    def atomic(self):
        connection = None
        committing = False
        try:
            connection = self._connect(write=True)
            connection.execute("BEGIN IMMEDIATE")
            previous, checkpoint = self._load(connection)
            state = copy.deepcopy(previous)
            yield state
            if state != previous:
                self._append_commit(connection, previous, state, checkpoint)
            committing = True
            connection.commit()
        except sqlite3.Error as error:
            raise CustodyBlocked(sql_failure(error, committing)) from error
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    def _read(self):
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN")
            return self._load(connection)
        except sqlite3.Error as error:
            raise CustodyBlocked(sql_failure(error)) from error
        finally:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()

    def read_snapshot(self):
        return self._read()[0]

    def checkpoint(self):
        return self._read()[1]
