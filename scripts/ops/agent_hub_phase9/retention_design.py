"""RCA16 local reference for archive-before-eviction and writer CAS.

This module is not imported by HubStore, an API, a runner or a dispatcher. It
implements a local test model, not Redis enforcement or a production archive.
Policy adoption, archive durability and all-writer integration require separate
Owner disposition and implementation/deployment. No execution authority exists.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
from threading import RLock


class RetentionBlocked(ValueError):
    pass


class Category(str, Enum):
    PROTECTED = "MUST_NOT_EVICT"
    ARCHIVABLE = "EVICTABLE_AFTER_DURABLE_CUSTODY"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def aware(value: str) -> str:
    time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if time.tzinfo is None or time.utcoffset() is None:
        raise RetentionBlocked("TIMESTAMP_REQUIRES_TIMEZONE")
    return time.astimezone(timezone.utc).isoformat()


def strict_object(raw: bytes) -> dict:
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise RetentionBlocked("DUPLICATE_JSON_KEY")
            value[key] = item
        return value
    value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(RetentionBlocked("NONFINITE_JSON")))
    if not isinstance(value, dict):
        raise RetentionBlocked("RECORD_MUST_BE_OBJECT")
    return value


@dataclass(frozen=True)
class LinkedBytes:
    reference: str
    raw: bytes


@dataclass(frozen=True)
class Entry:
    ledger: str
    raw: bytes
    links: tuple[LinkedBytes, ...] = ()

    @property
    def data(self):
        value = strict_object(self.raw)
        if not all(isinstance(value.get(key), str) and value[key]
                   for key in ("event_id", "event_type", "created_at")):
            raise RetentionBlocked("RECORD_ID_TYPE_TIME_MISSING")
        aware(value["created_at"])
        return value

    @property
    def identity(self):
        return self.data["event_id"]

    @property
    def references(self):
        value = self.data
        metadata = value.get("metadata", {})
        if not isinstance(metadata, dict):
            raise RetentionBlocked("RECORD_METADATA_INVALID")
        keys = ("operation_id", "attempt_id", "incident_id", "hold_id", "snapshot_id",
                "receipt_id", "source_event_id", "task_id", "review_id", "campaign_id")
        return tuple(str(source[key]) for source in (value, metadata) for key in keys if source.get(key)) + tuple(link.reference for link in self.links)

    def custody(self):
        value = self.data
        metadata = value.get("metadata", {})
        if not isinstance(metadata, dict):
            raise RetentionBlocked("RECORD_METADATA_INVALID")
        required = {str(metadata[key]) for key in ("snapshot_id", "receipt_id") if metadata.get(key)}
        links = {item.reference: item for item in self.links}
        if len(links) != len(self.links) or not required <= links.keys():
            raise RetentionBlocked("LINKED_CUSTODY_MISSING_OR_DUPLICATE")
        for reference in required:
            linked = strict_object(links[reference].raw)
            if reference not in (linked.get("snapshot_id"), linked.get("receipt_id")):
                raise RetentionBlocked("LINKED_REFERENCE_MISMATCH")
        return {"ledger": self.ledger, "event_id": self.identity, "event_type": value["event_type"],
                "occurred_at_UTC": aware(value["created_at"]),
                "raw_bytes": len(self.raw), "raw_sha256": digest(self.raw),
                "links": [{"reference": key, "raw_bytes": len(item.raw), "raw_sha256": digest(item.raw)}
                          for key, item in sorted(links.items())]}


@dataclass(frozen=True)
class Policy:
    """Synthetic fixture policy only; never an Owner approval parser."""
    version: str
    classes: tuple[tuple[str, Category], ...] = ()
    adopted_in_local_fixture: bool = False
    ledger: str = "npd:agent-hub:v1:attribution-os:audit"

    @property
    def sha256(self):
        return digest(encode({"domain": "npd.agent-hub.retention.local-reference.v1",
                              "version": self.version, "classes": sorted((key, value.value) for key, value in self.classes),
                              "ledger": self.ledger,
                              "synthetic_local_policy": self.adopted_in_local_fixture}))

    def category(self, entry: Entry):
        if not self.adopted_in_local_fixture or not self.version:
            raise RetentionBlocked("OWNER_POLICY_REQUIRED_LOCAL_MODEL")
        if entry.ledger != self.ledger:
            raise RetentionBlocked("LEDGER_SCOPE_MISMATCH")
        classes = dict(self.classes)
        if len(classes) != len(self.classes):
            raise RetentionBlocked("AMBIGUOUS_POLICY")
        category = classes.get(entry.data["event_type"])
        if category not in (Category.PROTECTED, Category.ARCHIVABLE):
            raise RetentionBlocked("UNKNOWN_CATEGORY")
        return category


@dataclass(frozen=True)
class ArchiveReceipt:
    manifest_sha256: str


class LocalArchive:
    """O_EXCL + fsync + independent re-read for temporary local fixtures.

    Production needs an Owner-selected backend/custodian with enforced no-delete,
    no-overwrite and crash/durability guarantees. This class is not WORM storage.
    """
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _path(self, kind: str, wanted: str):
        if len(wanted) != 64 or any(c not in "0123456789abcdef" for c in wanted):
            raise RetentionBlocked("ARCHIVE_IDENTIFIER_INVALID")
        path = self.root / kind / wanted
        if any(p.is_symlink() for p in (self.root, path.parent, path)):
            raise RetentionBlocked("ARCHIVE_SYMLINK_FORBIDDEN")
        return path

    def _write(self, path: Path, raw: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.read_bytes() != raw:
                raise RetentionBlocked("ARCHIVE_OVERWRITE_FORBIDDEN")
            return
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())

    def preserve(self, entry: Entry, policy: Policy, archived_at: str):
        binding = entry.custody()
        for raw in (entry.raw, *(link.raw for link in entry.links)):
            self._write(self._path("blobs", digest(raw)), raw)
        manifest = {"domain": "npd.agent-hub.audit-custody.local-reference.v1", **binding,
                    "archived_at_UTC": aware(archived_at), "policy_sha256": policy.sha256,
                    "retention_status": "SYNTHETIC_LOCAL_ONLY_NO_PRODUCTION_DISPOSITION"}
        raw = encode(manifest)
        receipt = ArchiveReceipt(digest(raw))
        self._write(self._path("manifests", receipt.manifest_sha256), raw)
        self.verify(entry, policy, receipt)
        return receipt

    def verify(self, entry: Entry, policy: Policy, receipt: ArchiveReceipt):
        try:
            raw = self._path("manifests", receipt.manifest_sha256).read_bytes()
            if digest(raw) != receipt.manifest_sha256:
                raise RetentionBlocked("ARCHIVE_MANIFEST_DIGEST_MISMATCH")
            manifest = strict_object(raw)
            if manifest.get("domain") != "npd.agent-hub.audit-custody.local-reference.v1" or manifest.get("policy_sha256") != policy.sha256:
                raise RetentionBlocked("ARCHIVE_POLICY_OR_DOMAIN_MISMATCH")
            if manifest.get("retention_status") != "SYNTHETIC_LOCAL_ONLY_NO_PRODUCTION_DISPOSITION":
                raise RetentionBlocked("ARCHIVE_RETENTION_STATUS_MISMATCH")
            if any(manifest.get(key) != value for key, value in entry.custody().items()):
                raise RetentionBlocked("ARCHIVE_ENTRY_BINDING_MISMATCH")
            aware(manifest["archived_at_UTC"])
            for wanted in (entry.raw, *(link.raw for link in entry.links)):
                actual = self._path("blobs", digest(wanted)).read_bytes()
                if actual != wanted or digest(actual) != digest(wanted):
                    raise RetentionBlocked("ARCHIVE_RAW_DIGEST_MISMATCH")
        except FileNotFoundError as error:
            raise RetentionBlocked("ARCHIVE_MISSING") from error


@dataclass(frozen=True)
class Observation:
    version: int
    ledger_sha256: str
    policy_sha256: str
    rows: tuple[Entry, ...]


class ReferenceLedger:
    """Locked CAS model for WATCH/MULTI writer enforcement, no Redis client."""
    def __init__(self, rows: tuple[Entry, ...], policy: Policy, *, cap: int = 5000):
        if cap < 1 or len(rows) > cap or len({r.identity for r in rows}) != len(rows):
            raise RetentionBlocked("LEDGER_CAP_OR_ID_DRIFT")
        self.rows = rows
        self.policy = policy
        self.cap = cap
        self.version = 0
        self.protected_ids: set[str] = set()
        self.protected_refs: set[str] = set()
        self.commits = {}
        self.lock = RLock()

    @staticmethod
    def fingerprint(rows):
        h = hashlib.sha256(b"npd.agent-hub.audit-list.exact-bytes.v1\0")
        for row in rows:
            binding = encode(row.custody())
            h.update(len(binding).to_bytes(8, "big")); h.update(binding)
            h.update(len(row.raw).to_bytes(8, "big")); h.update(row.raw)
        return h.hexdigest()

    def observe(self):
        with self.lock:
            return Observation(self.version, self.fingerprint(self.rows), self.policy.sha256, self.rows)

    def hold(self, *, event_id=None, reference=None):
        with self.lock:
            if event_id:
                self.protected_ids.add(event_id)
            if reference:
                self.protected_refs.add(reference)
            self.version += 1

    def prospective_evictions(self, observation: Observation, added: tuple[Entry, ...]):
        rows = observation.rows + added
        return rows[:max(0, len(rows) - self.cap)]

    def append(self, observation: Observation, added: tuple[Entry, ...], *, commit_id: str,
               archive: LocalArchive, receipts: dict[str, ArchiveReceipt]):
        if not added or len(added) > self.cap or not commit_id:
            raise RetentionBlocked("APPEND_BATCH_INVALID")
        payload_digest = self.fingerprint(added)
        with self.lock:
            if not self.policy.adopted_in_local_fixture:
                raise RetentionBlocked("OWNER_POLICY_REQUIRED_LOCAL_MODEL")
            if commit_id in self.commits:
                if self.commits[commit_id]["payload_sha256"] != payload_digest:
                    raise RetentionBlocked("IDEMPOTENCY_PAYLOAD_CONFLICT")
                return self.commits[commit_id]  # same prior result, zero second write
            if observation.version != self.version or observation.ledger_sha256 != self.fingerprint(self.rows) or observation.policy_sha256 != self.policy.sha256:
                raise RetentionBlocked("LEDGER_OR_POLICY_CHANGED_STOP_NO_RETRY")
            if len({row.identity for row in (*self.rows, *added)}) != len(self.rows) + len(added):
                raise RetentionBlocked("DUPLICATE_ENTRY_ID")
            for row in added:
                self.policy.category(row)
            evicted = self.prospective_evictions(observation, added)
            for row in evicted:
                if self.policy.category(row) == Category.PROTECTED or row.identity in self.protected_ids or self.protected_refs.intersection(row.references):
                    raise RetentionBlocked("PROTECTED_EVICTION_BOUNDARY")
                if row.identity not in receipts:
                    raise RetentionBlocked("ARCHIVE_MISSING")
                archive.verify(row, self.policy, receipts[row.identity])
            result = {"commit_id": commit_id, "payload_sha256": payload_digest,
                      "evicted_ids": [row.identity for row in evicted], "appended_ids": [row.identity for row in added],
                      "execution_authorized": False, "production_writes": 0}
            self.rows = (*self.rows, *added)[len(evicted):]
            self.version += 1
            self.commits[commit_id] = result
            return result
