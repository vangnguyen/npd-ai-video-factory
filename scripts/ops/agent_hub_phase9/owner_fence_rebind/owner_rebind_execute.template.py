from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import os
import re
import socket
import ssl
import stat
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# __SHARED_REPRESENTATION_SOURCE__


CONTEXT = json.loads(base64.b64decode("__EXECUTION_CONTEXT_B64__"))
CONTROL = Path(CONTEXT["control_directory"])
WORKDIR = Path(CONTEXT["workdir"])
BASE = Path(CONTEXT["base_compose"])
RECOVERY = Path(CONTEXT["recovery_override"])
OVERRIDE = CONTROL / "override.json"
PROJECT = "npd-agent-hub-prod"
SERVICE = "agent-hub"
EXPECTED_OLD_CONTAINER = CONTEXT["current_container_id"]
EXPECTED_OLD_IMAGE = CONTEXT["rollback_image_config"]
EXPECTED_CANDIDATE_IMAGE = CONTEXT["candidate_image_config"]
EXPECTED_TAG = CONTEXT["candidate_tag"]
EXPECTED_PROTECTED = CONTEXT["protected18_sha256"]
RELEVANT_PATTERN = re.compile("agent|redis|caddy|n8n|espo|wordpress|salehub|people|(?:^|[-_])hr(?:[-_]|$)|api|worker|renderer", re.I)
SETTING_NAMES = sorted(CONTEXT["creation_settings"])
HOST_SOURCES = {
    "GA4_SERVICE_ACCOUNT_HOST_FILE": {
        "path": "/etc/npd-ai/ga4-agent-hub-readonly.json",
        "target": "/run/secrets/ga4-service-account.json",
        "sha256": "36519be007706e8d0245c6cfef1ed2cf37ef992c2fc2dacdc4290d2fe6c895a7",
    },
    "AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE": {
        "path": "/etc/npd-ai/agent-attribution-verification-keys.json",
        "target": "/run/secrets/agent-attribution-verification-keys.json",
        "sha256": "ea6346727e1237e078e45efd5e055b747aa506b01b0e38d9c0b6164afc157922",
    },
}


class GateStop(RuntimeError):
    pass


def require(condition: object, reason: str) -> None:
    if not condition:
        raise GateStop(reason)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_digest(value: object) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or now()).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def run(argv: list[str], *, input_bytes: bytes | None = None, timeout: int = 30,
        environment: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, input=input_bytes, capture_output=True, timeout=timeout,
                          env=environment, shell=False)


def command_receipt(name: str, result: subprocess.CompletedProcess[bytes]) -> dict[str, object]:
    return {
        "component": name,
        "exit_code": result.returncode,
        "stdout_sha256": sha(result.stdout),
        "stdout_bytes": len(result.stdout),
        "stderr_sha256": sha(result.stderr),
        "stderr_bytes": len(result.stderr),
    }


def sha_file(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"UNSAFE_FILE:{path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_create(path: Path, raw: bytes, mode: int = 0o600) -> str:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)
    require(sha_file(path) == sha(raw), f"CONTROL_WRITE_VERIFY_FAILED:{path.name}")
    return sha(raw)


def env_map(values: list[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for row in values:
        key, sep, value = row.partition("=")
        require(bool(sep) and key not in output, "CONTAINER_ENV_INVALID")
        output[key] = value
    return output


def normalized(value: object) -> object:
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalized(item) for item in value]
    return value


def topology(item: dict[str, object]) -> dict[str, object]:
    return semantic_topology(item)


def topology_digest(item: dict[str, object]) -> str:
    # Preserve all topology array order except fields explicitly canonicalized by topology().
    return canonical_digest(topology(item))


def verify_recreated_topology(original: dict[str, object], recreated: dict[str, object]) -> str:
    old = topology(original)
    new = topology(recreated)
    require(old["host_config"].get("OomKillDisable") is None, "SEALED_OOM_PREIMAGE_DRIFT")
    require(new["host_config"].get("OomKillDisable") in (None, False), "RECREATED_OOM_NOT_DEFAULT_FALSE")
    require(effective_topology(old) == effective_topology(new), "SECOND_TOPOLOGY_DELTA")
    return canonical_digest(effective_topology(new))


def verify_host_sources() -> dict[str, str]:
    observed = {}
    for name, binding in HOST_SOURCES.items():
        path = Path(binding["path"])
        require(path.is_file() and not path.is_symlink(), f"HOST_SOURCE_MISSING:{name}")
        mode = path.stat().st_mode
        require(stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o600, f"HOST_SOURCE_MODE_DRIFT:{name}")
        require(sha_file(path) == binding["sha256"], f"HOST_SOURCE_DIGEST_DRIFT:{name}")
        observed[name] = binding["sha256"]
    return observed


def compose_environment() -> dict[str, str]:
    verify_host_sources()
    result = dict(os.environ)
    for name, binding in HOST_SOURCES.items():
        result[name] = binding["path"]
    return result


def verify_host_mounts(mounts: list[dict[str, object]]) -> None:
    canonical_docker_mounts(mounts, target=True)
    for binding in HOST_SOURCES.values():
        matched = [row for row in mounts if row.get("Destination") == binding["target"]]
        require(len(matched) == 1, "HOST_MOUNT_CARDINALITY_DRIFT")
        row = matched[0]
        require(row.get("Type") == "bind" and row.get("Source") == binding["path"]
                and row.get("RW") is False, "HOST_MOUNT_SOURCE_DRIFT")


def verify_rendered_host_mounts(volumes: list[dict[str, object]]) -> None:
    canonical_compose_volumes(volumes)
    for binding in HOST_SOURCES.values():
        matched = [row for row in volumes if row.get("target") == binding["target"]]
        require(len(matched) == 1, "RENDERED_HOST_MOUNT_CARDINALITY_DRIFT")
        row = matched[0]
        require(row.get("type") == "bind" and row.get("source") == binding["path"]
                and row.get("read_only") is True, "RENDERED_HOST_MOUNT_SOURCE_DRIFT")


def comparable_config(item: dict[str, object]) -> dict[str, object]:
    config = copy.deepcopy(item.get("Config") or {})
    config.pop("Hostname", None)
    config.pop("Image", None)
    env = env_map(config.get("Env") or [])
    for name in SETTING_NAMES:
        env.pop(name, None)
    config["Env"] = env
    labels = config.setdefault("Labels", {})
    config["Labels"] = {
        key: value
        for key, value in labels.items()
        if key.startswith("com.docker.compose.")
        and key not in {
            "com.docker.compose.config-hash",
            "com.docker.compose.replace",
            "com.docker.compose.project.config_files",
            "com.docker.compose.image",
        }
    }
    return normalized(config)


def sanitized_container(item: dict[str, object]) -> dict[str, object]:
    labels = item.get("Config", {}).get("Labels") or {}
    state = item.get("State") or {}
    mounts = canonical_docker_mounts(item.get("Mounts") or [])
    return {
        "name": str(item.get("Name", "")).lstrip("/"),
        "id": item.get("Id"),
        "image_id": item.get("Image"),
        "compose_project": labels.get("com.docker.compose.project"),
        "compose_service": labels.get("com.docker.compose.service"),
        "status": state.get("Status"),
        "running": state.get("Running"),
        "health": (state.get("Health") or {}).get("Status"),
        "restart_count": item.get("RestartCount"),
        "networks": sorted((item.get("NetworkSettings", {}).get("Networks") or {}).keys()),
        "ports": item.get("HostConfig", {}).get("PortBindings") or {},
        "mounts": mounts,
    }


def container_signature(item: dict[str, object]) -> dict[str, object]:
    clean = sanitized_container(item)
    return {key: normalized(clean.get(key)) for key in ("compose_project", "compose_service", "id", "image_id", "mounts", "name", "networks", "ports", "restart_count", "running", "status", "health")}


def inspect_running() -> list[dict[str, object]]:
    ps = run(["docker", "ps", "-q", "--no-trunc"])
    require(ps.returncode == 0 and not ps.stderr, "DOCKER_PS_RUNNING_FAILED")
    ids = ps.stdout.decode("ascii").split()
    require(ids and all(re.fullmatch("[0-9a-f]{64}", value) for value in ids), "DOCKER_RUNNING_IDS_INVALID")
    inspected = run(["docker", "inspect", *ids])
    require(inspected.returncode == 0 and not inspected.stderr, "DOCKER_INSPECT_RUNNING_FAILED")
    return json.loads(inspected.stdout)


def protected_digest(items: list[dict[str, object]]) -> str:
    digest, count = strict_protected_digest(items, PROJECT, SERVICE, RELEVANT_PATTERN)
    require(count == 18, "PROTECTED_SERVICE_COUNT_DRIFT")
    return digest


def target_ids() -> list[str]:
    ps = run([
        "docker", "ps", "-aq", "--no-trunc",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={SERVICE}",
    ])
    require(ps.returncode == 0 and not ps.stderr, "DOCKER_PS_TARGET_FAILED")
    return [x.strip() for x in ps.stdout.decode("ascii").splitlines() if x.strip()]


def inspect_one(identifier: str) -> dict[str, object]:
    result = run(["docker", "inspect", identifier])
    require(result.returncode == 0 and not result.stderr, "DOCKER_INSPECT_TARGET_FAILED")
    rows = json.loads(result.stdout)
    require(len(rows) == 1, "DOCKER_INSPECT_TARGET_CARDINALITY")
    return rows[0]


def verify_custody() -> None:
    expected = CONTEXT["recovery_custody"]
    root = Path("/var/lib/npd-ai/agent-hub-deployments/phase9-limited-pilot")
    op = expected["operation_id"]
    directory = root / "attempts" / op
    require(directory.is_dir() and not directory.is_symlink(), "OWNED_ATTEMPT_PATH_UNSAFE")
    inventory = {}
    for path in directory.iterdir():
        require(path.is_file() and not path.is_symlink(), "OWNED_ATTEMPT_INVENTORY_UNSAFE")
        inventory[path.name] = sha_file(path)
    require(inventory == expected["attempt_inventory"], "OWNED_ATTEMPT_INVENTORY_DRIFT")
    claim = root / "operations" / f"{op}.json"
    state = directory / "state.json"
    require(sha_file(claim) == expected["claim_sha256"], "OWNED_CLAIM_DRIFT")
    require(sha_file(state) == expected["state_sha256"], "OWNED_STATE_DRIFT")
    require(json.loads(state.read_bytes()).get("status") == "ROLLED_BACK_VERIFIED", "OWNED_TERMINAL_STATE_DRIFT")
    for relative, wanted in expected["terminal_history_metadata_sha256"].items():
        path = root / relative
        require(path.is_file() and not path.is_symlink() and sha_file(path) == wanted, "TERMINAL_HISTORY_DRIFT")


class RespClient:
    def __init__(self, redis_url: str, password_file_value: str | None, target_item: dict[str, object]) -> None:
        parsed = urllib.parse.urlsplit(redis_url)
        require(parsed.scheme in {"redis", "rediss"}, "REDIS_SCHEME_UNSUPPORTED")
        host = parsed.hostname or ""
        port = parsed.port or 6379
        address = self._resolve_container_address(host, target_item)
        sock = socket.create_connection((address, port), timeout=5)
        if parsed.scheme == "rediss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=host)
        self.sock = sock
        self.file = sock.makefile("rb")
        username = urllib.parse.unquote(parsed.username) if parsed.username else None
        password = urllib.parse.unquote(parsed.password) if parsed.password else None
        if password_file_value:
            require(password is None, "REDIS_PASSWORD_SOURCE_AMBIGUOUS")
            password = password_file_value
        if password is not None:
            if username:
                require(self.command("AUTH", username, password) == b"OK", "REDIS_AUTH_FAILED")
            else:
                require(self.command("AUTH", password) == b"OK", "REDIS_AUTH_FAILED")
        path = parsed.path.strip("/")
        database = int(path or "0")
        require(database == 1, "REDIS_DB_DRIFT")
        require(self.command("SELECT", str(database)) == b"OK", "REDIS_SELECT_FAILED")
        require(self.command("PING") == b"PONG", "REDIS_PING_FAILED")

    @staticmethod
    def _resolve_container_address(host: str, target_item: dict[str, object]) -> str:
        try:
            socket.inet_aton(host)
            return host
        except OSError:
            pass
        if host in {"127.0.0.1", "localhost"}:
            return host
        running = inspect_running()
        target_networks = set((target_item.get("NetworkSettings", {}).get("Networks") or {}).keys())
        matches: list[str] = []
        for item in running:
            for network_name, network in (item.get("NetworkSettings", {}).get("Networks") or {}).items():
                aliases = set(network.get("Aliases") or [])
                if network_name in target_networks and host in aliases and network.get("IPAddress"):
                    matches.append(str(network["IPAddress"]))
        require(len(set(matches)) == 1, "REDIS_NETWORK_TARGET_UNRESOLVED")
        return matches[0]

    @staticmethod
    def _encode(args: tuple[object, ...]) -> bytes:
        chunks = [f"*{len(args)}\r\n".encode()]
        for arg in args:
            raw = arg if isinstance(arg, bytes) else str(arg).encode("utf-8")
            chunks.append(f"${len(raw)}\r\n".encode())
            chunks.append(raw)
            chunks.append(b"\r\n")
        return b"".join(chunks)

    def _line(self) -> bytes:
        line = self.file.readline()
        require(line.endswith(b"\r\n"), "REDIS_PROTOCOL_TRUNCATED")
        return line[:-2]

    def _read(self) -> object:
        prefix = self.file.read(1)
        require(prefix, "REDIS_PROTOCOL_EOF")
        if prefix == b"+":
            return self._line()
        if prefix == b"-":
            raise GateStop("REDIS_COMMAND_DENIED")
        if prefix == b":":
            return int(self._line())
        if prefix == b"$":
            size = int(self._line())
            if size == -1:
                return None
            raw = self.file.read(size)
            require(len(raw) == size and self.file.read(2) == b"\r\n", "REDIS_BULK_TRUNCATED")
            return raw
        if prefix == b"*":
            count = int(self._line())
            if count == -1:
                return None
            return [self._read() for _ in range(count)]
        raise GateStop("REDIS_PROTOCOL_INVALID")

    def command(self, *args: object) -> object:
        self.sock.sendall(self._encode(args))
        return self._read()

    def pipeline(self, commands: list[tuple[object, ...]]) -> list[object]:
        self.sock.sendall(b"".join(self._encode(command) for command in commands))
        return [self._read() for _ in commands]

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            self.sock.close()


def redis_connection_inputs(item: dict[str, object]) -> tuple[str, str | None]:
    values = env_map(item.get("Config", {}).get("Env") or [])
    redis_url = values.get("AGENT_REDIS_URL")
    require(bool(redis_url), "REDIS_URL_MISSING")
    password_file = values.get("AGENT_REDIS_PASSWORD_FILE", "")
    password_value = None
    if password_file:
        mounts = item.get("Mounts") or []
        match = [row for row in mounts if row.get("Destination") == password_file]
        require(len(match) == 1 and match[0].get("RW") is False, "REDIS_PASSWORD_MOUNT_UNBOUND")
        host_path = Path(str(match[0].get("Source")))
        require(host_path.is_file() and not host_path.is_symlink(), "REDIS_PASSWORD_FILE_UNSAFE")
        password_value = host_path.read_text(encoding="utf-8").rstrip("\r\n")
        require(bool(password_value), "REDIS_PASSWORD_EMPTY")
    return str(redis_url), password_value


def framed(parts: list[bytes]) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(struct.pack(">Q", len(part)))
        h.update(part)
    return h.hexdigest()



def redis_snapshot(item: dict[str, object]) -> dict[str, object]:
    redis_url, password = redis_connection_inputs(item)
    client = RespClient(redis_url, password, item)
    namespace = "npd:agent-hub:v1"
    heartbeat_prefix = namespace + ":attribution-os:heartbeat-receipt:"
    heartbeat_index_key = namespace + ":attribution-os:heartbeat-receipts"
    audit_key = namespace + ":attribution-os:audit"
    snapshot_prefix = namespace + ":provider-health:snapshot:"
    snapshot_index_key = namespace + ":provider-health:snapshots"
    alert_prefix = namespace + ":provider-health:alert:"
    alert_index_key = namespace + ":provider-health:alerts"
    status_key = namespace + ":provider-health:scheduler:status"
    lease_key = namespace + ":provider-health:scheduler:lease"
    campaign_id = "CMP-AHINTERNAL-P9SLACOHORT-202609-01"
    heartbeat_key_re = re.compile(r"^" + re.escape(heartbeat_prefix) + r"ahr_[0-9a-f]{24}$")
    snapshot_key_re = re.compile(r"^" + re.escape(snapshot_prefix) + r"phs_[0-9a-f]{24}$")
    alert_key_re = re.compile(r"^" + re.escape(alert_prefix) + r"pha_[0-9a-f]{24}$")

    def as_bytes(value: object) -> bytes:
        return value.encode("utf-8") if isinstance(value, str) else value

    def utc_text(value: str) -> str:
        parsed = parse_time(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "MUTABLE_TIMESTAMP_NOT_AWARE")
        return parsed.astimezone(timezone.utc).isoformat()

    def classify(name: str) -> str:
        if heartbeat_key_re.fullmatch(name):
            return "heartbeat_item"
        if name == heartbeat_index_key:
            return "heartbeat_index"
        if snapshot_key_re.fullmatch(name):
            return "snapshot_item"
        if name == snapshot_index_key:
            return "snapshot_index"
        if alert_key_re.fullmatch(name):
            return "alert_item"
        if name == alert_index_key:
            return "alert_index"
        if name == status_key:
            return "scheduler_status"
        if name == lease_key:
            return "scheduler_lease"
        if name == audit_key:
            return "attribution_audit"
        return "immutable"

    def zrange_withscores(key: str) -> list[tuple[str, float]]:
        raw = client.command("ZRANGE", key, "0", "-1", "WITHSCORES")
        require(isinstance(raw, list) and len(raw) % 2 == 0, "ZSET_READ_INVALID")
        rows: list[tuple[str, float]] = []
        for index in range(0, len(raw), 2):
            member, score = raw[index], raw[index + 1]
            require(isinstance(member, bytes) and isinstance(score, bytes), "ZSET_ROW_INVALID")
            rows.append((member.decode("utf-8"), float(score.decode("ascii"))))
        return rows

    env = env_map(item.get("Config", {}).get("Env") or [])
    active_id = env.get("AGENT_ATTRIBUTION_ACTIVE_KEY_ID") or env.get("AGENT_ATTRIBUTION_RECEIPT_KEY_ID") or "npd-attribution-v1"
    active_key = env.get("AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY") or env.get("AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY") or ""
    require(bool(active_id) and len(active_key) >= 32, "ACTIVE_HEARTBEAT_VERIFICATION_KEY_UNAVAILABLE")
    verification_keys = {active_id: active_key}
    historical_path = env.get("AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE", "")
    if historical_path:
        matching = [row for row in item.get("Mounts") or [] if row.get("Destination") == historical_path]
        require(len(matching) == 1 and matching[0].get("RW") is False, "HISTORICAL_KEYRING_MOUNT_UNBOUND")
        host_path = Path(str(matching[0].get("Source")))
        require(host_path.is_file() and not host_path.is_symlink(), "HISTORICAL_KEYRING_UNSAFE")
        historical = json.loads(host_path.read_bytes())
        require(isinstance(historical, dict) and active_id not in historical, "HISTORICAL_KEYRING_INVALID")
        verification_keys.update(historical)

    def heartbeat_signature_valid(payload: dict[str, object]) -> bool:
        key_id = payload.get("key_id")
        key = verification_keys.get(key_id)
        if not key:
            return False
        unsigned = dict(payload)
        signature = unsigned.pop("signature", None)
        expected = "hmac-sha256:" + hmac.new(
            key.encode("utf-8"),
            json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return isinstance(signature, str) and hmac.compare_digest(signature, expected)

    try:
        cursor = b"0"
        keys: set[bytes] = set()
        while True:
            response = client.command("SCAN", cursor, "MATCH", namespace + ":*", "COUNT", "1000")
            require(isinstance(response, list) and len(response) == 2, "REDIS_SCAN_INVALID")
            cursor_raw, batch = response
            require(isinstance(cursor_raw, bytes) and isinstance(batch, list), "REDIS_SCAN_INVALID")
            cursor = cursor_raw
            for key in batch:
                require(isinstance(key, bytes), "REDIS_KEY_INVALID")
                keys.add(key)
            if cursor == b"0":
                break
        ordered = sorted(keys)
        names = [key.decode("utf-8") for key in ordered]
        classes = {name: classify(name) for name in names}
        commands: list[tuple[object, ...]] = []
        for key in ordered:
            commands.extend([("TYPE", key), ("DUMP", key)])
        responses: list[object] = []
        for start in range(0, len(commands), 1000):
            responses.extend(client.pipeline(commands[start:start + 1000]))
        complete_parts: list[bytes] = []
        immutable_parts: list[bytes] = []
        immutable_keys: list[bytes] = []
        for index, key in enumerate(ordered):
            kind = responses[index * 2]
            dumped = responses[index * 2 + 1]
            require(isinstance(kind, bytes) and isinstance(dumped, bytes), "REDIS_KEY_CHANGED_DURING_CAPTURE")
            complete_parts.extend([key, kind, dumped])
            if classes[names[index]] == "immutable":
                immutable_keys.append(key)
                immutable_parts.extend([key, kind, dumped])

        heartbeat_index: list[dict[str, object]] = []
        heartbeat_ids: list[str] = []
        for receipt_id, score in zrange_withscores(heartbeat_index_key):
            require(re.fullmatch(r"ahr_[0-9a-f]{24}", receipt_id), "HEARTBEAT_INDEX_ID_INVALID")
            raw = client.command("GET", heartbeat_prefix + receipt_id)
            require(isinstance(raw, bytes), "HEARTBEAT_PAYLOAD_MISSING")
            payload = json.loads(raw)
            require(isinstance(payload, dict), "HEARTBEAT_PAYLOAD_INVALID")
            required_fields = {"receipt_id", "heartbeat_id", "producer", "emitted_at", "sequence", "payload_digest", "received_at", "key_id", "signature", "read_only", "external_writes_enabled"}
            require(set(payload) == required_fields, "HEARTBEAT_PAYLOAD_SCHEMA_DRIFT")
            require(payload["receipt_id"] == receipt_id, "HEARTBEAT_ID_KEY_MISMATCH")
            expected_id = "ahr_" + hashlib.sha256(str(payload["heartbeat_id"]).encode("utf-8")).hexdigest()[:24]
            require(expected_id == receipt_id, "HEARTBEAT_DERIVATION_MISMATCH")
            require(payload["producer"] == EXPECTED_PRODUCER, "HEARTBEAT_PRODUCER_INVALID")
            require(payload["read_only"] is True and payload["external_writes_enabled"] is False, "HEARTBEAT_WRITE_FLAG_INVALID")
            require(re.fullmatch(r"[0-9a-f]{64}", str(payload["payload_digest"])), "HEARTBEAT_PAYLOAD_DIGEST_INVALID")
            require(abs(score - parse_time(str(payload["received_at"])).timestamp()) < 0.001, "HEARTBEAT_INDEX_SCORE_MISMATCH")
            signature_valid = heartbeat_signature_valid(payload)
            require(signature_valid, "HEARTBEAT_SIGNATURE_INVALID")
            heartbeat_ids.append(receipt_id)
            heartbeat_index.append({
                "receipt_id": receipt_id,
                "heartbeat_id": payload["heartbeat_id"],
                "producer": payload["producer"],
                "emitted_at_utc": utc_text(str(payload["emitted_at"])),
                "received_at_utc": utc_text(str(payload["received_at"])),
                "sequence": int(payload["sequence"]),
                "payload_digest": payload["payload_digest"],
                "key_id": payload["key_id"],
                "signature_valid": True,
                "score": score,
                "raw_sha256": sha(raw),
            })
        heartbeat_key_ids = sorted(name[len(heartbeat_prefix):] for name, family in classes.items() if family == "heartbeat_item")
        require(heartbeat_key_ids == sorted(heartbeat_ids), "HEARTBEAT_INDEX_PAYLOAD_SET_MISMATCH")
        require(len(heartbeat_index) == HEARTBEAT_CAP, "HEARTBEAT_RETENTION_COUNT_DRIFT")

        snapshot_index: list[dict[str, object]] = []
        snapshot_ids: list[str] = []
        for snapshot_id, score in zrange_withscores(snapshot_index_key):
            require(re.fullmatch(r"phs_[0-9a-f]{24}", snapshot_id), "SNAPSHOT_INDEX_ID_INVALID")
            raw = client.command("GET", snapshot_prefix + snapshot_id)
            require(isinstance(raw, bytes), "SNAPSHOT_PAYLOAD_MISSING")
            payload = json.loads(raw)
            require(isinstance(payload, dict) and payload.get("snapshot_id") == snapshot_id, "SNAPSHOT_PAYLOAD_INVALID")
            require(payload.get("production_write_enabled") is False, "SNAPSHOT_PRODUCTION_WRITE_ENABLED")
            require(payload.get("external_notifications_enabled") is False, "SNAPSHOT_EXTERNAL_NOTIFICATION_ENABLED")
            require(abs(score - parse_time(str(payload["observed_at"])).timestamp()) < 0.001, "SNAPSHOT_INDEX_SCORE_MISMATCH")
            snapshot_ids.append(snapshot_id)
            snapshot_index.append({
                "snapshot_id": snapshot_id,
                "observed_at_utc": utc_text(str(payload["observed_at"])),
                "score": score,
                "production_write_enabled": False,
                "external_notifications_enabled": False,
                "raw_sha256": sha(raw),
            })
        snapshot_key_ids = sorted(name[len(snapshot_prefix):] for name, family in classes.items() if family == "snapshot_item")
        require(snapshot_key_ids == sorted(snapshot_ids), "SNAPSHOT_INDEX_PAYLOAD_SET_MISMATCH")
        require(len(snapshot_index) == SNAPSHOT_CAP, "SNAPSHOT_RETENTION_COUNT_DRIFT")

        alerts: list[dict[str, object]] = []
        alert_ids: list[str] = []
        for alert_id, score in zrange_withscores(alert_index_key):
            require(re.fullmatch(r"pha_[0-9a-f]{24}", alert_id), "ALERT_INDEX_ID_INVALID")
            raw = client.command("GET", alert_prefix + alert_id)
            require(isinstance(raw, bytes), "ALERT_PAYLOAD_MISSING")
            payload = json.loads(raw)
            require(isinstance(payload, dict) and payload.get("alert_id") == alert_id, "ALERT_PAYLOAD_INVALID")
            require(payload.get("routing_targets") == ["command_center", "audit"], "ALERT_ROUTING_DRIFT")
            require(payload.get("external_notifications_enabled") is False and payload.get("external_writes_enabled") is False, "ALERT_EXTERNAL_EFFECT_ENABLED")
            require(abs(score - parse_time(str(payload["last_detected_at"])).timestamp()) < 0.001, "ALERT_INDEX_SCORE_MISMATCH")
            alert_ids.append(alert_id)
            alerts.append({
                "alert_id": alert_id,
                "status": payload["status"],
                "last_detected_at_utc": utc_text(str(payload["last_detected_at"])),
                "score": score,
                "routing_targets": payload["routing_targets"],
                "external_notifications_enabled": False,
                "external_writes_enabled": False,
                "raw_sha256": sha(raw),
            })
        alert_key_ids = sorted(name[len(alert_prefix):] for name, family in classes.items() if family == "alert_item")
        require(alert_key_ids == sorted(alert_ids), "ALERT_INDEX_PAYLOAD_SET_MISMATCH")

        audit_raw = client.command("LRANGE", audit_key, "0", "-1")
        require(isinstance(audit_raw, list), "AUDIT_LIST_INVALID")
        audit_rows: list[dict[str, object]] = []
        for position, raw in enumerate(audit_raw):
            require(isinstance(raw, bytes), "AUDIT_ROW_INVALID")
            payload = json.loads(raw)
            require(isinstance(payload, dict) and isinstance(payload.get("metadata"), dict), "AUDIT_SCHEMA_INVALID")
            metadata = payload["metadata"]
            actor = payload.get("actor")
            event_type = payload.get("event_type")
            kind = "other"
            authenticated = False
            if event_type == "producer_heartbeat_received":
                kind = "heartbeat"
                authenticated = (
                    actor == EXPECTED_HEARTBEAT_ACTOR
                    and metadata.get("producer") == EXPECTED_PRODUCER
                    and re.fullmatch(r"ahr_[0-9a-f]{24}", str(metadata.get("receipt_id", ""))) is not None
                    and metadata.get("external_side_effect") is False
                    and set(metadata) == {"heartbeat_id", "receipt_id", "producer", "sequence", "external_side_effect"}
                )
            elif actor == SCHEDULER_ACTOR and event_type in SCHEDULER_EVENTS:
                kind = "scheduler"
            audit_rows.append({
                "position": position,
                "event_id": payload.get("event_id"),
                "event_type": event_type,
                "actor_class": EXPECTED_HEARTBEAT_ACTOR if actor == EXPECTED_HEARTBEAT_ACTOR else SCHEDULER_ACTOR if actor == SCHEDULER_ACTOR else "other",
                "created_at_utc": utc_text(str(payload.get("created_at"))),
                "kind": kind,
                "heartbeat_authenticated_route": authenticated,
                "receipt_id": metadata.get("receipt_id"),
                "heartbeat_id": metadata.get("heartbeat_id"),
                "producer": metadata.get("producer"),
                "sequence": metadata.get("sequence"),
                "snapshot_id": metadata.get("snapshot_id"),
                "alert_id": metadata.get("alert_id"),
                "routing_targets": metadata.get("routing_targets"),
                "external_notification": metadata.get("external_notification"),
                "external_side_effect": metadata.get("external_side_effect"),
                "raw_sha256": sha(raw),
            })
        require(len(audit_rows) == AUDIT_CAP, "ATTRIBUTION_AUDIT_COUNT_DRIFT")

        raw_status = client.command("GET", status_key)
        require(isinstance(raw_status, bytes), "SCHEDULER_STATUS_MISSING")
        status = json.loads(raw_status)
        lease = client.command("GET", lease_key)
        lease_ttl = client.command("PTTL", lease_key)
        require(isinstance(lease_ttl, int), "SCHEDULER_LEASE_TTL_INVALID")
        selected: dict[str, object] = {}
        for label, key in {
            "global_attribution": audit_key,
            "global_task_audit": namespace + ":audit:global",
            "campaign_audit": namespace + ":campaign-os:audit:" + campaign_id,
            "campaign_record": namespace + ":campaign-os:campaign:" + campaign_id,
        }.items():
            kind_raw = client.command("TYPE", key)
            require(isinstance(kind_raw, bytes), "REDIS_TYPE_INVALID")
            kind = kind_raw.decode("ascii")
            if kind == "list":
                count = client.command("LLEN", key)
            elif kind == "zset":
                count = client.command("ZCARD", key)
            elif kind == "none":
                count = 0
            else:
                count = 1
            dumped = client.command("DUMP", key)
            selected[label] = {
                "type": kind,
                "count": int(count),
                "dump_sha256": sha(dumped) if isinstance(dumped, bytes) else None,
            }

        second_keys: set[bytes] = set()
        cursor = b"0"
        while True:
            response = client.command("SCAN", cursor, "MATCH", namespace + ":*", "COUNT", "1000")
            require(isinstance(response, list) and len(response) == 2, "REDIS_SECOND_SCAN_INVALID")
            cursor, batch = response
            require(isinstance(cursor, bytes) and isinstance(batch, list), "REDIS_SECOND_SCAN_INVALID")
            second_keys.update(batch)
            if cursor == b"0":
                break
        require(second_keys == keys, "REDIS_KEYS_CHANGED_DURING_SNAPSHOT")
        return {
            "observed_utc": iso(),
            "namespace_key_count": len(ordered),
            "namespace_keyset_sha256": framed(ordered),
            "namespace_fingerprint_sha256": framed(complete_parts),
            "business_store_fingerprint_sha256": framed(immutable_parts),
            "immutable_key_count": len(immutable_keys),
            "immutable_keyset_sha256": framed(immutable_keys),
            "immutable_fingerprint_sha256": framed(immutable_parts),
            "heartbeat_index": heartbeat_index,
            "heartbeat_index_sha256": canonical_digest(heartbeat_index),
            "heartbeat_count": len(heartbeat_index),
            "snapshot_index": snapshot_index,
            "snapshot_index_sha256": canonical_digest(snapshot_index),
            "snapshot_count": len(snapshot_index),
            "alerts": alerts,
            "alerts_sha256": canonical_digest(alerts),
            "alert_count": len(alerts),
            "audit_rows": audit_rows,
            "audit_rows_sha256": canonical_digest(audit_rows),
            "audit_count": len(audit_rows),
            "scheduler_status": status,
            "scheduler_status_raw_sha256": sha(raw_status),
            "scheduler_state": status.get("state"),
            "scheduler_next_run_at": status.get("next_run_at"),
            "scheduler_internal_only": {
                "evaluates_cached_state_only": status.get("evaluates_cached_state_only"),
                "external_provider_probes_enabled": status.get("external_provider_probes_enabled"),
                "external_notifications_enabled": status.get("external_notifications_enabled"),
                "production_write_enabled": status.get("production_write_enabled"),
            },
            "scheduler_lease_present": lease is not None,
            "scheduler_lease_ttl_ms": lease_ttl,
            "lease_present": lease is not None,
            "lease_ttl_ms": lease_ttl,
            "selected": selected,
        }
    finally:
        client.close()


def verify_control_preimage() -> dict[str, str]:
    expected_files = {
        "approval-consumed.json",
        "override.json",
        "preflight-evidence.json",
        "timing-receipt.json",
    }
    require(CONTROL.is_dir() and not CONTROL.is_symlink(), "CONTROL_DIRECTORY_UNSAFE")
    actual = {path.name for path in CONTROL.iterdir()}
    require(actual == expected_files, "CONTROL_INVENTORY_DRIFT")
    for path in CONTROL.iterdir():
        require(path.is_file() and not path.is_symlink(), "CONTROL_FILE_UNSAFE")
    hashes = {name: sha_file(CONTROL / name) for name in sorted(expected_files)}
    require(hashes["override.json"] == CONTEXT["candidate_override_sha256"], "CANDIDATE_OVERRIDE_DRIFT")
    require(hashes["timing-receipt.json"] == CONTEXT["timing_receipt_sha256"], "TIMING_RECEIPT_DRIFT")
    require(hashes["preflight-evidence.json"] == CONTEXT["preflight_evidence_sha256"], "PREFLIGHT_EVIDENCE_DRIFT")
    consumed = json.loads((CONTROL / "approval-consumed.json").read_bytes())
    require(consumed.get("status") == "GRANTED_EXACT_AND_CONSUMED", "APPROVAL_NOT_CONSUMED")
    require(consumed.get("attempt_id") == CONTEXT["attempt_id"], "ATTEMPT_ID_DRIFT")
    require(consumed.get("approval_sha256") == CONTEXT["approval_sha256"], "APPROVAL_CONSUMPTION_DRIFT")
    require(consumed.get("gate_c") == "NOT_GRANTED_NOT_EXECUTED" and consumed.get("retry") is False, "AUTHORITY_SCOPE_DRIFT")
    return hashes



def verify_timing(*, entry: bool = False, stop: bool = False, decision: bool = False, verification: bool = False, rollback: bool = False) -> None:
    timing = CONTEXT["timing"]
    current = now()
    if entry:
        require(current < parse_time(timing["entry_deadline_utc"]), "ENTRY_DEADLINE_EXPIRED")
    if stop:
        require(current < parse_time(timing["stop_completion_deadline_utc"]), "STOP_DEADLINE_EXPIRED")
    if decision:
        require(current < parse_time(timing["candidate_decision_deadline_utc"]), "CANDIDATE_DECISION_DEADLINE_EXPIRED")
    if verification:
        require(current < parse_time(timing["candidate_verification_deadline_utc"]), "CANDIDATE_VERIFICATION_DEADLINE_EXPIRED")
    if rollback:
        require(current < parse_time(timing["recovery_completion_deadline_utc"]), "RECOVERY_DEADLINE_EXPIRED")


def elapsed_bound(stopped_at: datetime, maximum_seconds: int, reason: str) -> None:
    require((now() - stopped_at).total_seconds() < maximum_seconds, reason)


def verify_files() -> None:
    require(sha_file(BASE) == CONTEXT["base_compose_sha256"], "BASE_COMPOSE_DRIFT")
    require(sha_file(RECOVERY) == CONTEXT["recovery_override_sha256"], "RECOVERY_OVERRIDE_DRIFT")
    require(sha_file(OVERRIDE) == CONTEXT["candidate_override_sha256"], "CANDIDATE_OVERRIDE_DRIFT")
    verify_host_sources()


def verify_old_target() -> dict[str, object]:
    require(target_ids() == [EXPECTED_OLD_CONTAINER], "OLD_TARGET_CARDINALITY_DRIFT")
    item = inspect_one(EXPECTED_OLD_CONTAINER)
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_OLD_IMAGE, "OLD_IMAGE_DRIFT")
    require(state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy", "OLD_RUNTIME_NOT_HEALTHY")
    require(item.get("RestartCount") == 0, "OLD_RUNTIME_RESTART_DRIFT")
    require(topology_digest(item) == CONTEXT["current_topology_sha256"], "OLD_TOPOLOGY_DRIFT")
    require(canonical_docker_mounts(item.get("Mounts") or [], target=True) == CONTEXT["sealed_mounts"], "OLD_MOUNTS_DRIFT")
    config = item.get("Config") or {}
    require(sha(json.dumps(config.get("Cmd"), sort_keys=True).encode()) == CONTEXT["sealed_command_sha256"], "OLD_COMMAND_DRIFT")
    require(sha(json.dumps(config.get("Entrypoint"), sort_keys=True).encode()) == CONTEXT["sealed_entrypoint_sha256"], "OLD_ENTRYPOINT_DRIFT")
    verify_host_mounts(item.get("Mounts") or [])
    env = env_map(item.get("Config", {}).get("Env") or [])
    require(canonical_digest(env) == CONTEXT["preflight"]["full_environment_fingerprint_sha256"], "OLD_ENV_DRIFT")
    setting_state = {name: {"present": name in env, "value": env.get(name)} for name in SETTING_NAMES}
    require(setting_state == CONTEXT["settings_preimage"], "OLD_SETTINGS_DRIFT")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.working_dir") == str(WORKDIR), "OLD_WORKDIR_DRIFT")
    require(labels.get("com.docker.compose.project.config_files") == f"{BASE},{RECOVERY}", "OLD_COMPOSE_CONTEXT_DRIFT")
    return item


def verify_protected_and_custody() -> None:
    require(protected_digest(inspect_running()) == EXPECTED_PROTECTED, "PROTECTED_SERVICE_DRIFT")
    verify_custody()



HEARTBEAT_CAP = 5000
SNAPSHOT_CAP = 5000
AUDIT_CAP = 5000
EXPECTED_PRODUCER = "n8n_lead_intake"
EXPECTED_HEARTBEAT_ACTOR = "operator"
SCHEDULER_ACTOR = "provider_health_scheduler"
SCHEDULER_EVENTS = {
    "provider_health_scheduled_evaluation",
    "provider_alert_opened",
    "provider_alert_reopened",
    "provider_alert_resolved",
}

def _capped_transition(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    *,
    id_field: str,
    cap: int,
    family: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    require(len(before) == cap and len(after) == cap, f"{family}_CAP_DRIFT")
    before_ids = [row[id_field] for row in before]
    after_ids = [row[id_field] for row in after]
    require(len(before_ids) == len(set(before_ids)), f"{family}_BASE_DUPLICATE")
    require(len(after_ids) == len(set(after_ids)), f"{family}_LIVE_DUPLICATE")
    before_set = set(before_ids)
    after_set = set(after_ids)
    removed = [row for row in before if row[id_field] not in after_set]
    added = [row for row in after if row[id_field] not in before_set]
    require(len(removed) == len(added), f"{family}_REPLACEMENT_COUNT_MISMATCH")
    count = len(added)
    require(before[:count] == removed, f"{family}_REMOVAL_NOT_OLDEST")
    require(after[-count:] == added if count else True, f"{family}_ADDITION_NOT_NEWEST")
    overlap_before = before[count:]
    overlap_after = after[: cap - count] if count else after
    require(overlap_before == overlap_after, f"{family}_OVERLAP_CHANGED")
    return removed, added, overlap_after


def _audit_transition(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    require(len(before) == AUDIT_CAP and len(after) == AUDIT_CAP, "AUDIT_CAP_DRIFT")
    before_hashes = [row["raw_sha256"] for row in before]
    after_hashes = [row["raw_sha256"] for row in after]
    require(len(before_hashes) == len(set(before_hashes)), "AUDIT_BASE_DUPLICATE")
    require(len(after_hashes) == len(set(after_hashes)), "AUDIT_LIVE_DUPLICATE")
    added_count = len(set(after_hashes) - set(before_hashes))
    removed_count = len(set(before_hashes) - set(after_hashes))
    require(added_count == removed_count, "AUDIT_REPLACEMENT_COUNT_MISMATCH")
    require(
        before_hashes[added_count:] == after_hashes[: AUDIT_CAP - added_count],
        "AUDIT_NOT_RPUSH_LTRIM_TRANSITION",
    )
    return after[-added_count:] if added_count else []


def _validate_scheduler_event(row: dict[str, Any]) -> None:
    require(row.get("kind") == "scheduler", "UNAPPROVED_AUDIT_KIND")
    require(row.get("actor_class") == SCHEDULER_ACTOR, "SCHEDULER_ACTOR_DRIFT")
    require(row.get("event_type") in SCHEDULER_EVENTS, "SCHEDULER_EVENT_TYPE_DENIED")
    require(row.get("external_notification") is False, "SCHEDULER_EXTERNAL_NOTIFICATION")
    require(row.get("external_side_effect") is False, "SCHEDULER_EXTERNAL_SIDE_EFFECT")
    require(row.get("routing_targets") == ["command_center", "audit"], "SCHEDULER_ROUTING_DRIFT")


def _validate_heartbeat_event(row: dict[str, Any]) -> None:
    require(row.get("kind") == "heartbeat", "UNAPPROVED_AUDIT_KIND")
    require(row.get("event_type") == "producer_heartbeat_received", "HEARTBEAT_AUDIT_TYPE_DRIFT")
    require(row.get("actor_class") == EXPECTED_HEARTBEAT_ACTOR, "HEARTBEAT_ACTOR_DRIFT")
    require(row.get("heartbeat_authenticated_route") is True, "HEARTBEAT_ROUTE_NOT_AUTHENTICATED")
    require(row.get("producer") == EXPECTED_PRODUCER, "HEARTBEAT_AUDIT_PRODUCER_DRIFT")
    require(row.get("external_side_effect") is False, "HEARTBEAT_EXTERNAL_SIDE_EFFECT")


def validate_semantic_transition(
    baseline: dict[str, Any], current: dict[str, Any]
) -> dict[str, Any]:
    require(current["immutable_key_count"] == baseline["immutable_key_count"], "IMMUTABLE_KEY_COUNT_DRIFT")
    require(current["immutable_keyset_sha256"] == baseline["immutable_keyset_sha256"], "IMMUTABLE_KEYSET_DRIFT")
    require(current["immutable_fingerprint_sha256"] == baseline["immutable_fingerprint_sha256"], "IMMUTABLE_CONTENT_DRIFT")
    require(current["selected"]["global_attribution"]["count"] == AUDIT_CAP, "GLOBAL_ATTRIBUTION_COUNT_DRIFT")
    require(current["selected"]["campaign_audit"]["count"] == 0, "PHASE9_CAMPAIGN_AUDIT_EXISTS")
    require(current["selected"]["campaign_record"]["count"] == 0, "PHASE9_CAMPAIGN_EXISTS")
    # Alert refresh can be silent in the current scheduler implementation. It is
    # outside this approved mutable family, so pin the entire alert projection.
    require(current["alerts_sha256"] == baseline["alerts_sha256"], "SCHEDULER_ALERT_DRIFT")

    _, heartbeat_added, _ = _capped_transition(
        baseline["heartbeat_index"],
        current["heartbeat_index"],
        id_field="receipt_id",
        cap=HEARTBEAT_CAP,
        family="HEARTBEAT",
    )
    _, snapshot_added, _ = _capped_transition(
        baseline["snapshot_index"],
        current["snapshot_index"],
        id_field="snapshot_id",
        cap=SNAPSHOT_CAP,
        family="SNAPSHOT",
    )
    audit_added = _audit_transition(baseline["audit_rows"], current["audit_rows"])

    heartbeat_by_id = {row["receipt_id"]: row for row in heartbeat_added}
    last_sequence = int(baseline["heartbeat_index"][-1]["sequence"])
    for row in heartbeat_added:
        require(row.get("producer") == EXPECTED_PRODUCER, "HEARTBEAT_PRODUCER_DRIFT")
        require(row.get("signature_valid") is True, "HEARTBEAT_SIGNATURE_INVALID")
        sequence = int(row.get("sequence", 0))
        require(sequence > last_sequence, "HEARTBEAT_SEQUENCE_NOT_INCREASING")
        require(row.get("heartbeat_id") == f"heartbeat:n8n-lead-intake:{sequence}", "HEARTBEAT_SOURCE_ID_CONTRACT_DRIFT")
        emitted_ms = round(datetime.fromisoformat(str(row["emitted_at_utc"])).timestamp() * 1000)
        require(sequence == emitted_ms, "HEARTBEAT_SEQUENCE_TIMESTAMP_MISMATCH")
        last_sequence = sequence
        require(row.get("raw_sha256"), "HEARTBEAT_RAW_DIGEST_MISSING")

    snapshot_by_id = {row["snapshot_id"]: row for row in snapshot_added}
    for row in snapshot_added:
        expected = "phs_" + hashlib.sha256(
            f"{row['observed_at_utc']}:provider_health_scheduled_evaluation".encode("utf-8")
        ).hexdigest()[:24]
        require(row["snapshot_id"] == expected, "SNAPSHOT_NOT_SCHEDULED_EVALUATION")
        require(row.get("production_write_enabled") is False, "SNAPSHOT_PRODUCTION_WRITE_ENABLED")
        require(row.get("external_notifications_enabled") is False, "SNAPSHOT_EXTERNAL_NOTIFICATION_ENABLED")

    heartbeat_audits: dict[str, dict[str, Any]] = {}
    snapshot_audits: dict[str, dict[str, Any]] = {}
    alert_audits: dict[str, list[dict[str, Any]]] = {}
    for row in audit_added:
        if row.get("kind") == "heartbeat":
            _validate_heartbeat_event(row)
            receipt_id = str(row.get("receipt_id"))
            require(receipt_id not in heartbeat_audits, "HEARTBEAT_AUDIT_DUPLICATE")
            heartbeat_audits[receipt_id] = row
        elif row.get("kind") == "scheduler":
            _validate_scheduler_event(row)
            if row.get("event_type") == "provider_health_scheduled_evaluation":
                snapshot_id = str(row.get("snapshot_id"))
                require(snapshot_id not in snapshot_audits, "SNAPSHOT_AUDIT_DUPLICATE")
                snapshot_audits[snapshot_id] = row
            else:
                alert_id = str(row.get("alert_id"))
                alert_audits.setdefault(alert_id, []).append(row)
        else:
            raise GateStop("UNEXPLAINED_ATTRIBUTION_TRANSITION")

    require(set(heartbeat_by_id) == set(heartbeat_audits), "HEARTBEAT_AUDIT_CORRELATION_MISMATCH")
    for receipt_id, receipt in heartbeat_by_id.items():
        audit = heartbeat_audits[receipt_id]
        require(audit.get("heartbeat_id") == receipt.get("heartbeat_id"), "HEARTBEAT_AUDIT_ID_MISMATCH")
        require(audit.get("producer") == receipt.get("producer"), "HEARTBEAT_AUDIT_PRODUCER_MISMATCH")
        require(audit.get("sequence") == receipt.get("sequence"), "HEARTBEAT_AUDIT_SEQUENCE_MISMATCH")
    require(set(snapshot_by_id) == set(snapshot_audits), "SNAPSHOT_AUDIT_CORRELATION_MISMATCH")

    baseline_alerts = {row["alert_id"]: row for row in baseline["alerts"]}
    current_alerts = {row["alert_id"]: row for row in current["alerts"]}
    require(set(baseline_alerts) <= set(current_alerts), "SCHEDULER_ALERT_REMOVED")
    changed_alerts = {
        alert_id
        for alert_id, row in current_alerts.items()
        if alert_id not in baseline_alerts or row != baseline_alerts[alert_id]
    }
    require(changed_alerts == set(alert_audits), "SCHEDULER_ALERT_AUDIT_CORRELATION_MISMATCH")
    for alert_id in changed_alerts:
        row = current_alerts[alert_id]
        require(row.get("routing_targets") == ["command_center", "audit"], "ALERT_ROUTING_DRIFT")
        require(row.get("external_notifications_enabled") is False, "ALERT_EXTERNAL_NOTIFICATION")
        require(row.get("external_writes_enabled") is False, "ALERT_EXTERNAL_WRITE")

    status = current.get("scheduler_status") or {}
    require(status.get("state") in {"idle", "running", "succeeded"}, "SCHEDULER_STATE_INVALID")
    require(status.get("evaluates_cached_state_only") is True, "SCHEDULER_CACHED_ONLY_DRIFT")
    require(status.get("external_provider_probes_enabled") is False, "SCHEDULER_PROVIDER_PROBE_DRIFT")
    require(status.get("external_notifications_enabled") is False, "SCHEDULER_NOTIFICATION_DRIFT")
    require(status.get("production_write_enabled") is False, "SCHEDULER_PRODUCTION_WRITE_DRIFT")
    if current.get("scheduler_lease_present"):
        require(0 < int(current.get("scheduler_lease_ttl_ms", -1)) <= 600000, "SCHEDULER_LEASE_INVALID")

    return {
        "status": "PASS_PRESTOP_SEMANTIC_TRANSITION",
        "immutable_key_count": current["immutable_key_count"],
        "heartbeat_added": len(heartbeat_added),
        "snapshot_added": len(snapshot_added),
        "alert_changed": len(changed_alerts),
        "audit_added": len(audit_added),
        "current_full_keyset_observation": current["namespace_keyset_sha256"],
        "proof_sha256": canonical_digest(
            {
                "immutable": current["immutable_fingerprint_sha256"],
                "heartbeat_added": heartbeat_added,
                "snapshot_added": snapshot_added,
                "alerts": [current_alerts[key] for key in sorted(changed_alerts)],
                "audit_added": audit_added,
            }
        ),
    }


POST_STOP_EXACT_FIELDS = (
    "namespace_key_count",
    "namespace_keyset_sha256",
    "namespace_fingerprint_sha256",
    "immutable_key_count",
    "immutable_keyset_sha256",
    "immutable_fingerprint_sha256",
    "heartbeat_index_sha256",
    "snapshot_index_sha256",
    "alerts_sha256",
    "audit_rows_sha256",
    "scheduler_status_raw_sha256",
    "selected",
)


def validate_post_stop_pair(
    baseline: dict[str, Any], first: dict[str, Any], second: dict[str, Any]
) -> dict[str, Any]:
    validate_semantic_transition(baseline, first)
    validate_semantic_transition(baseline, second)
    for row in (first, second):
        require(row.get("scheduler_lease_present") is False, "POSTSTOP_LEASE_PRESENT")
        require(row.get("scheduler_lease_ttl_ms") == -2, "POSTSTOP_LEASE_TTL_DRIFT")
        require((row.get("scheduler_status") or {}).get("state") in {"idle", "succeeded"}, "POSTSTOP_SCHEDULER_NOT_TERMINAL")
    require(
        {field: first[field] for field in POST_STOP_EXACT_FIELDS}
        == {field: second[field] for field in POST_STOP_EXACT_FIELDS},
        "POSTSTOP_A_B_DRIFT",
    )
    return {
        "status": "PASS_POSTSTOP_EXACT_A_B",
        "required_wait_seconds": 5,
        "projection_sha256": digest({field: second[field] for field in POST_STOP_EXACT_FIELDS}),
    }


def verify_pre_stop_store(snapshot: dict[str, object]) -> None:
    proof = validate_semantic_transition(CONTEXT["semantic_prestop_baseline"], snapshot)
    snapshot["semantic_transition"] = proof


def stable_store_projection(snapshot: dict[str, object]) -> dict[str, object]:
    return {key: snapshot[key] for key in (
        "namespace_key_count",
        "namespace_keyset_sha256",
        "namespace_fingerprint_sha256",
        "business_store_fingerprint_sha256",
        "immutable_key_count",
        "immutable_keyset_sha256",
        "immutable_fingerprint_sha256",
        "heartbeat_index_sha256",
        "snapshot_index_sha256",
        "alerts_sha256",
        "audit_rows_sha256",
        "scheduler_status_raw_sha256",
        "scheduler_state",
        "scheduler_next_run_at",
        "lease_present",
        "lease_ttl_ms",
        "selected",
        "target_stopped_state",
        "target_finished_at",
        "target_exit_code",
        "target_oom_killed",
        "target_error",
        "topology_sha256",
    )}


def verify_post_stop_store(snapshot: dict[str, object]) -> None:
    proof = validate_semantic_transition(CONTEXT["semantic_prestop_baseline"], snapshot)
    snapshot["semantic_transition"] = proof
    require(snapshot["namespace_key_count"] == CONTEXT["semantic_prestop_baseline"]["namespace_key_count"], "POSTSTOP_NAMESPACE_COUNT_DRIFT")
    require(snapshot["selected"]["global_attribution"]["count"] == 5000, "POSTSTOP_GLOBAL_ATTRIBUTION_COUNT_DRIFT")
    require(snapshot["selected"]["campaign_audit"]["count"] == 0, "POSTSTOP_CAMPAIGN_AUDIT_EXISTS")
    require(snapshot["selected"]["campaign_record"]["count"] == 0, "POSTSTOP_CAMPAIGN_EXISTS")
    require(snapshot["lease_present"] is False and snapshot["lease_ttl_ms"] == -2, "POSTSTOP_SCHEDULER_LEASE_PRESENT")
    require(snapshot["scheduler_state"] in {"idle", "succeeded"}, "POSTSTOP_SCHEDULER_NOT_TERMINAL")
    require(snapshot["target_stopped_state"] == "exited", "POSTSTOP_TARGET_STATE_INVALID")
    require(snapshot["target_exit_code"] == 0, "POSTSTOP_TARGET_EXIT_INVALID")
    require(snapshot["target_oom_killed"] is False and snapshot["target_error"] == "", "POSTSTOP_TARGET_EXIT_AMBIGUOUS")
    require(snapshot["topology_sha256"] == CONTEXT["current_topology_sha256"], "POSTSTOP_TOPOLOGY_DRIFT")


def verify_compose_render(old_item: dict[str, object]) -> dict[str, object]:
    compose_env = compose_environment()
    rollback_result = run([
        "docker", "compose", "--project-name", PROJECT,
        "-f", str(BASE), "-f", str(RECOVERY), "config", "--format", "json",
    ], timeout=30, environment=compose_env)
    require(rollback_result.returncode == 0 and not rollback_result.stderr, "ROLLBACK_COMPOSE_RENDER_FAILED")
    rollback_service = json.loads(rollback_result.stdout).get("services", {}).get(SERVICE)
    require(isinstance(rollback_service, dict), "ROLLBACK_COMPOSE_SERVICE_MISSING")
    verify_rendered_host_mounts(rollback_service.get("volumes") or [])
    result = run([
        "docker", "compose", "--project-name", PROJECT,
        "-f", str(BASE), "-f", str(RECOVERY), "-f", str(OVERRIDE),
        "config", "--format", "json",
    ], timeout=30, environment=compose_env)
    require(result.returncode == 0 and not result.stderr, "COMPOSE_RENDER_FAILED")
    rendered = json.loads(result.stdout)
    service = rendered.get("services", {}).get(SERVICE)
    require(isinstance(service, dict), "COMPOSE_SERVICE_MISSING")
    require(service.get("image") == EXPECTED_TAG, "COMPOSE_IMAGE_DRIFT")
    verify_rendered_host_mounts(service.get("volumes") or [])
    require(
        canonical_compose_volumes(service.get("volumes") or [])
        == canonical_compose_volumes(rollback_service.get("volumes") or []),
        "CANDIDATE_ROLLBACK_MOUNT_RENDER_DRIFT",
    )
    rendered_env = service.get("environment") or {}
    old_env = env_map(old_item.get("Config", {}).get("Env") or [])
    old_image = run(["docker", "image", "inspect", EXPECTED_OLD_IMAGE])
    require(old_image.returncode == 0 and not old_image.stderr, "OLD_IMAGE_INSPECT_FAILED")
    old_defaults = env_map((json.loads(old_image.stdout)[0].get("Config") or {}).get("Env") or [])
    expected_service_env = {
        key: value for key, value in old_env.items()
        if key not in old_defaults or old_defaults.get(key) != value
    }
    expected_service_env.update(CONTEXT["creation_settings"])
    require(rendered_env == expected_service_env, "COMPOSE_ENVIRONMENT_DRIFT")
    return {
        "raw_sha256": sha(result.stdout),
        "rollback_raw_sha256": sha(rollback_result.stdout),
        "environment_fingerprint_sha256": canonical_digest(rendered_env),
        "image": service.get("image"),
    }



def candidate_image_semantic(item: dict[str, object]) -> dict[str, object]:
    config = item.get("Config") or {}
    rootfs = item.get("RootFS") or {}
    return {
        "id": item.get("Id"),
        "repo_tags": sorted(item.get("RepoTags") or []),
        "repo_digests": sorted(item.get("RepoDigests") or []),
        "architecture": item.get("Architecture"),
        "os": item.get("Os"),
        "rootfs_type": rootfs.get("Type"),
        "rootfs_layers": rootfs.get("Layers") or [],
        "config_env": config.get("Env") or [],
        "config_entrypoint": config.get("Entrypoint"),
        "config_cmd": config.get("Cmd"),
        "config_working_dir": config.get("WorkingDir"),
        "config_labels": config.get("Labels") or {},
    }


def verify_imported_image(commands: list[dict[str, object]]) -> dict[str, object]:
    # Previous transfer/import is provenance only. This fresh attempt performs
    # no image-store mutation and independently verifies the exact local image.
    inspect = run(["docker", "image", "inspect", EXPECTED_TAG])
    commands.append(command_receipt("candidate_image_readonly_inspect", inspect))
    require(inspect.returncode == 0 and not inspect.stderr, "CANDIDATE_IMAGE_MISSING")
    rows = json.loads(inspect.stdout)
    require(len(rows) == 1 and rows[0].get("Id") == EXPECTED_CANDIDATE_IMAGE, "CANDIDATE_IMAGE_CONFIG_DRIFT")
    labels = rows[0].get("Config", {}).get("Labels") or {}
    require(labels.get("org.opencontainers.image.revision") == CONTEXT["candidate_head"], "CANDIDATE_REVISION_LABEL_DRIFT")
    semantic_sha = canonical_digest(candidate_image_semantic(rows[0]))
    require(semantic_sha == CONTEXT["candidate_image_semantic_sha256"], "CANDIDATE_IMAGE_SEMANTIC_DRIFT")
    old_image = run(["docker", "image", "inspect", EXPECTED_OLD_IMAGE])
    require(old_image.returncode == 0 and not old_image.stderr, "OLD_IMAGE_INSPECT_FAILED")
    old_defaults = env_map((json.loads(old_image.stdout)[0].get("Config") or {}).get("Env") or [])
    new_defaults = env_map((rows[0].get("Config") or {}).get("Env") or [])
    require(old_defaults == new_defaults, "CANDIDATE_IMAGE_DEFAULT_ENV_DRIFT")
    return {
        "status": "PASS_IMPORTED_IMAGE_REVERIFIED_NO_IMPORT",
        "image_id": rows[0].get("Id"),
        "revision": labels.get("org.opencontainers.image.revision"),
        "semantic_sha256": semantic_sha,
        "inspect_raw_sha256": sha(inspect.stdout),
        "image_store_writes": 0,
    }



def write_before_receipts(
    old_item: dict[str, object],
    post_stop_store: dict[str, object],
    render: dict[str, object],
    post_stop_reseal_sha256: str,
) -> tuple[str, str]:
    runtime_before = {
        "schema": "npd.agent-hub.phase9.gate-d.prestop-reseal.runtime-before.v1",
        "attempt_id": CONTEXT["attempt_id"],
        "captured_utc": iso(),
        "container": sanitized_container(old_item),
        "topology_sha256": topology_digest(old_item),
        "comparable_config_sha256": canonical_digest(comparable_config(old_item)),
        "full_environment_fingerprint_sha256": canonical_digest(env_map(old_item.get("Config", {}).get("Env") or [])),
        "settings_preimage": CONTEXT["settings_preimage"],
        "base_compose_sha256": sha_file(BASE),
        "recovery_override_sha256": sha_file(RECOVERY),
        "compose_render": render,
        "post_stop_reseal_sha256": post_stop_reseal_sha256,
        "secret_values_retained": False,
    }
    business_before = {
        "schema": "npd.agent-hub.phase9.gate-d.prestop-reseal.business-store-before.v1",
        "attempt_id": CONTEXT["attempt_id"],
        "captured_utc": iso(),
        "authority_source": "POST_STOP_RESEAL_ONLY",
        "snapshot": post_stop_store,
        "post_stop_reseal_sha256": post_stop_reseal_sha256,
        "DB0_reads": 0,
        "DB1_writes": 0,
        "production_business_writes": 0,
    }
    runtime_sha = atomic_create(CONTROL / "runtime-before.json", canonical(runtime_before))
    business_sha = atomic_create(CONTROL / "business-store-before.json", canonical(business_before))
    return runtime_sha, business_sha



def running_target_ids() -> list[str]:
    ps = run([
        "docker", "ps", "-q", "--no-trunc",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={SERVICE}",
    ])
    require(ps.returncode == 0 and not ps.stderr, "DOCKER_PS_RUNNING_TARGET_FAILED")
    return [x.strip() for x in ps.stdout.decode("ascii").splitlines() if x.strip()]


def http_port_open() -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1.0)
    try:
        return sock.connect_ex(("127.0.0.1", 8010)) == 0
    finally:
        sock.close()


def verify_post_stop_writer_absence(stopped_item: dict[str, object]) -> None:
    require(target_ids() == [EXPECTED_OLD_CONTAINER], "POSTSTOP_TARGET_CARDINALITY")
    require(running_target_ids() == [], "POSTSTOP_TARGET_STILL_RUNNING")
    require(not http_port_open(), "POSTSTOP_HTTP_WRITE_PATH_AVAILABLE")
    state = stopped_item.get("State") or {}
    require(stopped_item.get("Image") == EXPECTED_OLD_IMAGE, "POSTSTOP_OLD_IMAGE_DRIFT")
    require(state.get("Running") is False and state.get("Status") == "exited", "POSTSTOP_TARGET_NOT_EXITED")
    require(state.get("ExitCode") == 0, "POSTSTOP_GRACEFUL_EXIT_FAILED")
    require(state.get("OOMKilled") is False and not state.get("Error"), "POSTSTOP_EXIT_AMBIGUOUS")
    require(topology_digest(stopped_item) == CONTEXT["current_topology_sha256"], "POSTSTOP_TOPOLOGY_DRIFT")
    require(protected_digest(inspect_running()) == EXPECTED_PROTECTED, "POSTSTOP_PROTECTED_DRIFT")
    verify_custody()


def stop_target_only(commands: list[dict[str, object]]) -> tuple[dict[str, object], datetime, dict[str, object]]:
    verify_timing(entry=True, stop=True)
    started_at = now()
    result = run(["docker", "stop", "--time", "30", EXPECTED_OLD_CONTAINER], timeout=40)
    commands.append(command_receipt("stop_exact_agent_hub_target_only", result))
    require(result.returncode == 0 and not result.stderr, "OWNED_RUNTIME_STOP_FAILED")
    stopped_at = now()
    verify_timing(stop=True)
    item = inspect_one(EXPECTED_OLD_CONTAINER)
    verify_post_stop_writer_absence(item)
    state = item.get("State") or {}
    return item, stopped_at, {
        "started_at_utc": iso(started_at),
        "stopped_at_utc": iso(stopped_at),
        "elapsed_seconds": (stopped_at - started_at).total_seconds(),
        "container_id": item.get("Id"),
        "image_id": item.get("Image"),
        "state": state.get("Status"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error") or "",
        "http_port_open": False,
        "running_target_count": 0,
        "protected18_sha256": EXPECTED_PROTECTED,
    }


def enrich_post_stop_snapshot(old_item: dict[str, object], stopped_item: dict[str, object]) -> dict[str, object]:
    snapshot = redis_snapshot(old_item)
    state = stopped_item.get("State") or {}
    snapshot.update({
        "target_stopped_state": state.get("Status"),
        "target_finished_at": state.get("FinishedAt"),
        "target_exit_code": state.get("ExitCode"),
        "target_oom_killed": state.get("OOMKilled"),
        "target_error": state.get("Error") or "",
        "topology_sha256": topology_digest(stopped_item),
    })
    verify_post_stop_store(snapshot)
    return snapshot


def post_stop_reseal(
    old_item: dict[str, object],
    stopped_item: dict[str, object],
    stopped_at: datetime,
) -> tuple[dict[str, object], str, dict[str, object]]:
    verify_post_stop_writer_absence(stopped_item)
    first = enrich_post_stop_snapshot(old_item, stopped_item)
    elapsed_bound(stopped_at, 30, "POSTSTOP_RESEAL_EXCEEDED_30_SECONDS")
    time.sleep(5)
    stopped_item_second = inspect_one(EXPECTED_OLD_CONTAINER)
    verify_post_stop_writer_absence(stopped_item_second)
    second = enrich_post_stop_snapshot(old_item, stopped_item_second)
    first_projection = stable_store_projection(first)
    second_projection = stable_store_projection(second)
    require(first_projection == second_projection, "POSTSTOP_A_B_CHANGED")
    elapsed_bound(stopped_at, 30, "POSTSTOP_RESEAL_EXCEEDED_30_SECONDS")
    receipt = {
        "schema": "npd.agent-hub.phase9.gate-d.prestop-reseal.post-stop-reseal.v1",
        "status": "PASS_POST_STOP_RESEALED_STABLE",
        "attempt_id": CONTEXT["attempt_id"],
        "captured_utc": iso(),
        "stopped_at_utc": iso(stopped_at),
        "allowed_mutable_fields": CONTEXT["post_stop_reseal_allowed_fields"],
        "snapshot_a_projection_sha256": canonical_digest(first_projection),
        "snapshot_b_projection_sha256": canonical_digest(second_projection),
        "sealed_projection": second_projection,
        "stability_observation_seconds": 5,
        "writer_absence": {
            "running_agent_hub_targets": 0,
            "direct_http_port_open": False,
            "independent_scheduler_process": False,
            "external_http_write_paths_reachable": False,
            "protected_services_unchanged": True,
        },
        "DB0_reads": 0,
        "DB1_writes": 0,
        "production_business_writes": 0,
    }
    receipt_sha = atomic_create(CONTROL / "post-stop-reseal.json", canonical(receipt))
    return second, receipt_sha, receipt


def compose_create(old_item: dict[str, object], commands: list[dict[str, object]], stopped_at: datetime) -> dict[str, object]:
    verify_timing(decision=True)
    elapsed_bound(stopped_at, 210, "CANDIDATE_DECISION_EXCEEDED_210_SECONDS")
    result = run([
        "docker", "compose", "--project-name", PROJECT,
        "-f", str(BASE), "-f", str(RECOVERY), "-f", str(OVERRIDE),
        "up", "--no-start", "--no-deps", "--no-build", "--pull", "never", SERVICE,
    ], timeout=120, environment=compose_environment())
    commands.append(command_receipt("compose_create_no_start", result))
    require(result.returncode == 0, "CANDIDATE_COMPOSE_CREATE_FAILED")
    require(target_ids() and len(target_ids()) == 1, "CANDIDATE_TARGET_CARDINALITY")
    new_id = target_ids()[0]
    require(new_id != EXPECTED_OLD_CONTAINER, "CANDIDATE_NOT_RECREATED")
    item = inspect_one(new_id)
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_CANDIDATE_IMAGE, "CANDIDATE_CONTAINER_IMAGE_DRIFT")
    require(state.get("Running") is False and state.get("Status") in {"created", "exited"}, "CANDIDATE_STARTED_PREMATURELY")
    effective_sha = verify_recreated_topology(old_item, item)
    verify_host_mounts(item.get("Mounts") or [])
    env = env_map(item.get("Config", {}).get("Env") or [])
    for name, value in CONTEXT["creation_settings"].items():
        require(env.get(name) == value, "CANDIDATE_FENCE_SETTING_DRIFT")
    old_env = env_map(old_item.get("Config", {}).get("Env") or [])
    expected_env = dict(old_env)
    expected_env.update(CONTEXT["creation_settings"])
    require(env == expected_env, "CANDIDATE_UNDECLARED_ENV_DRIFT")
    require(canonical_digest(comparable_config(item)) == canonical_digest(comparable_config(old_item)), "CANDIDATE_CONFIG_DRIFT")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.working_dir") == str(WORKDIR), "CANDIDATE_WORKDIR_DRIFT")
    expected_files = f"{BASE},{RECOVERY},{OVERRIDE}"
    require(labels.get("com.docker.compose.project.config_files") == expected_files, "CANDIDATE_COMPOSE_CONTEXT_DRIFT")
    return {
        "container_id": new_id,
        "image_id": item.get("Image"),
        "status": state.get("Status"),
        "running": state.get("Running"),
        "effective_topology_sha256": effective_sha,
        "comparable_config_sha256": canonical_digest(comparable_config(item)),
        "environment_fingerprint_sha256": canonical_digest(env),
    }


def start_once(container_id: str, commands: list[dict[str, object]], stopped_at: datetime) -> dict[str, object]:
    verify_timing(decision=True)
    elapsed_bound(stopped_at, 210, "CANDIDATE_START_DECISION_EXCEEDED_210_SECONDS")
    result = run(["docker", "start", container_id], timeout=30)
    commands.append(command_receipt("single_candidate_start", result))
    require(result.returncode == 0 and not result.stderr, "CANDIDATE_START_FAILED")
    deadline = time.monotonic() + 150
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        verify_timing(verification=True, rollback=True)
        elapsed_bound(stopped_at, 420, "CANDIDATE_VERIFICATION_EXCEEDED_420_SECONDS")
        item = inspect_one(container_id)
        state = item.get("State") or {}
        last_state = state
        if state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy":
            return {
                "healthy_at_utc": iso(),
                "running": True,
                "health": "healthy",
                "restart_count": item.get("RestartCount"),
            }
        if state.get("Running") is False:
            break
        time.sleep(2)
    raise GateStop("CANDIDATE_HEALTH_FAILED")


def http_read(path: str) -> dict[str, object]:
    request = urllib.request.Request("http://127.0.0.1:8010" + path, method="GET")
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read()
        return {"path": path, "status": response.status, "body_sha256": sha(raw), "body": json.loads(raw)}


def denial_probe(path: str, payload: object) -> dict[str, object]:
    raw_payload = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    request = urllib.request.Request(
        "http://127.0.0.1:8010" + path,
        data=raw_payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=5)
        raise GateStop("DENIAL_PROBE_UNEXPECTED_SUCCESS")
    except urllib.error.HTTPError as exc:
        body = exc.read()
        require(exc.code == 403, "DENIAL_PROBE_WRONG_STATUS")
        parsed = json.loads(body)
        require(parsed.get("detail") in {"PHASE9_CREATION_ROUTE_DENIED", "PHASE9_CREATION_REQUEST_DENIED"}, "DENIAL_PROBE_WRONG_REASON")
        return {"path": path, "status": exc.code, "reason": parsed.get("detail"), "body_sha256": sha(body)}


def verify_candidate_inside(container_id: str, commands: list[dict[str, object]]) -> dict[str, object]:
    expected_b64 = base64.b64encode(json.dumps(CONTEXT["source_sha256"], sort_keys=True).encode()).decode()
    code = r'''
import base64, hashlib, json, os
from pathlib import Path
from npd_agent_hub.config import HubSettings

expected = json.loads(base64.b64decode(os.environ['EXPECTED_SOURCE_HASHES_B64']))
s = HubSettings.from_env()
assert s.runtime_mode == 'phase9_creation'
assert s.provider_health_scheduler_enabled is False
assert s.phase9_creation_campaign_id == 'CMP-AHINTERNAL-P9SLACOHORT-202609-01'
assert s.phase9_creation_owner_id == '6a4dd6d5c8ee64bed'
actual = {}
for source_name, wanted in expected.items():
    relative = source_name.removeprefix('services/agent_hub/')
    path = Path('/app') / relative
    assert path.is_file(), 'SOURCE_FILE_MISSING'
    got = hashlib.sha256(path.read_bytes()).hexdigest()
    assert got == wanted, 'SOURCE_FILE_HASH_DRIFT'
    actual[source_name] = got
aggregate = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
print(json.dumps({
  'status':'PASS_EXACT_CANDIDATE_INSIDE',
  'source_file_count':len(actual),
  'source_hash_map_aggregate_sha256':aggregate,
  'runtime_mode':s.runtime_mode,
  'scheduler_enabled':s.provider_health_scheduler_enabled,
  'campaign_id':s.phase9_creation_campaign_id,
  'owner_id':s.phase9_creation_owner_id,
  'DB1_writes':0,
  'provider_calls':0,
}, sort_keys=True))
'''
    result = run([
        "docker", "exec", "-e", f"EXPECTED_SOURCE_HASHES_B64={expected_b64}",
        container_id, "python", "-B", "-c", code,
    ], timeout=45)
    commands.append(command_receipt("verify_candidate_inside", result))
    require(result.returncode == 0 and not result.stderr, "CANDIDATE_INSIDE_VERIFICATION_FAILED")
    parsed = json.loads(result.stdout)
    require(parsed.get("status") == "PASS_EXACT_CANDIDATE_INSIDE", "CANDIDATE_INSIDE_STATUS_INVALID")
    require(parsed.get("source_file_count") == len(CONTEXT["source_sha256"]), "CANDIDATE_SOURCE_COUNT_DRIFT")
    return parsed


def verify_post_start(
    container_id: str,
    old_item: dict[str, object],
    before_store: dict[str, object],
    commands: list[dict[str, object]],
    stopped_at: datetime,
) -> dict[str, object]:
    verify_timing(verification=True, rollback=True)
    elapsed_bound(stopped_at, 420, "CANDIDATE_VERIFICATION_EXCEEDED_420_SECONDS")
    require(target_ids() == [container_id], "POST_START_TARGET_CARDINALITY")
    item = inspect_one(container_id)
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_CANDIDATE_IMAGE, "POST_START_IMAGE_DRIFT")
    require(state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy", "POST_START_HEALTH_DRIFT")
    require(item.get("RestartCount") == 0, "POST_START_RESTART_COUNT_DRIFT")
    verify_recreated_topology(old_item, item)
    verify_host_mounts(item.get("Mounts") or [])
    require(canonical_digest(comparable_config(item)) == canonical_digest(comparable_config(old_item)), "POST_START_CONFIG_DRIFT")
    env = env_map(item.get("Config", {}).get("Env") or [])
    expected_env = env_map(old_item.get("Config", {}).get("Env") or [])
    expected_env.update(CONTEXT["creation_settings"])
    require(env == expected_env, "POST_START_ENV_DRIFT")
    require(protected_digest(inspect_running()) == EXPECTED_PROTECTED, "POST_START_PROTECTED_DRIFT")
    verify_custody()
    health = http_read("/health")
    ready = http_read("/readyz")
    require(health["status"] == 200 and health["body"].get("status") == "ok", "HEALTH_ENDPOINT_FAILED")
    require(ready["status"] == 200 and ready["body"].get("status") == "ready", "READY_ENDPOINT_FAILED")
    inside = verify_candidate_inside(container_id, commands)
    probes = [
        denial_probe("/api/v1/provider-health/evaluate", {}),
        denial_probe("/api/v1/provider-health/refresh", {}),
        denial_probe("/api/v1/attribution/deliveries/heartbeats", {}),
        denial_probe("/api/v1/attribution/deliveries", {}),
        denial_probe("/api/v1/agent-tasks", {}),
        denial_probe("/agent-hub/events/v1", {}),
        denial_probe("/api/v1/campaigns", {}),
    ]
    first_store = redis_snapshot(item)
    for key in (
        "namespace_key_count",
        "namespace_fingerprint_sha256",
        "business_store_fingerprint_sha256",
        "scheduler_status_raw_sha256",
        "selected",
    ):
        require(first_store[key] == before_store[key], "POST_START_BUSINESS_WRITE_DETECTED")
    require(first_store["lease_present"] is False, "POST_START_SCHEDULER_LEASE_CREATED")
    time.sleep(5)
    verify_timing(verification=True, rollback=True)
    elapsed_bound(stopped_at, 420, "CANDIDATE_VERIFICATION_EXCEEDED_420_SECONDS")
    second_store = redis_snapshot(item)
    for key in (
        "namespace_key_count",
        "namespace_fingerprint_sha256",
        "business_store_fingerprint_sha256",
        "scheduler_status_raw_sha256",
        "selected",
    ):
        require(second_store[key] == first_store[key], "POST_START_AUTONOMOUS_WRITE_DETECTED")
    return {
        "container_id": container_id,
        "image_id": item.get("Image"),
        "status": "OWNER_FENCE_REBOUND_VERIFIED",
        "health": "healthy",
        "ready": True,
        "runtime_mode": "phase9_creation",
        "scheduler_initialized": False,
        "scheduler_status_unchanged": True,
        "scheduler_lease_absent": True,
        "business_store_unchanged": True,
        "namespace_key_count": second_store["namespace_key_count"],
        "namespace_fingerprint_sha256": second_store["namespace_fingerprint_sha256"],
        "business_store_fingerprint_sha256": second_store["business_store_fingerprint_sha256"],
        "protected18_sha256": EXPECTED_PROTECTED,
        "health_read": health,
        "ready_read": ready,
        "denial_probes": probes,
        "inside_verification": inside,
    }


def wait_healthy(container_id: str, timeout_seconds: int = 150) -> dict[str, object]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        verify_timing(rollback=True)
        item = inspect_one(container_id)
        state = item.get("State") or {}
        if state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy":
            return item
        if state.get("Running") is False:
            break
        time.sleep(2)
    raise GateStop("RUNTIME_HEALTH_TIMEOUT")



def rollback_once(
    old_item: dict[str, object],
    post_stop_store: dict[str, object] | None,
    stopped_at: datetime | None,
    trigger: str,
    commands: list[dict[str, object]],
) -> dict[str, object]:
    verify_timing(rollback=True)
    if stopped_at is not None:
        elapsed_bound(stopped_at, 840, "RECOVERY_EXCEEDED_840_SECONDS")
    existing_ids = target_ids()
    require(len(existing_ids) == 1, "BOUNDED_ROLLBACK_PRE_TARGET_CARDINALITY")
    existing = inspect_one(existing_ids[0])
    existing_state = existing.get("State") or {}
    require(existing.get("Image") in {EXPECTED_CANDIDATE_IMAGE, EXPECTED_OLD_IMAGE},
            "BOUNDED_ROLLBACK_UNOWNED_IMAGE")
    if existing_state.get("Running") is True or existing_state.get("Restarting") is True:
        require(existing.get("Image") == EXPECTED_CANDIDATE_IMAGE, "BOUNDED_ROLLBACK_ORIGINAL_RUNNING")
        stopped_candidate = run(["docker", "stop", "--time", "30", existing_ids[0]], timeout=40)
        commands.append(command_receipt("bounded_rollback_stop_failed_candidate", stopped_candidate))
        require(stopped_candidate.returncode == 0, "BOUNDED_ROLLBACK_CANDIDATE_STOP_FAILED")
        require((inspect_one(existing_ids[0]).get("State") or {}).get("Running") is False,
                "BOUNDED_ROLLBACK_CANDIDATE_STILL_RUNNING")
    verify_timing(rollback=True)
    result = run([
        "docker", "compose", "--project-name", PROJECT,
        "-f", str(BASE), "-f", str(RECOVERY),
        "up", "--no-start", "--no-deps", "--no-build", "--pull", "never",
        "--force-recreate", SERVICE,
    ], timeout=150, environment=compose_environment())
    commands.append(command_receipt("bounded_rollback_create_original_not_started", result))
    require(result.returncode == 0, "BOUNDED_ROLLBACK_COMPOSE_FAILED")
    ids = target_ids()
    require(len(ids) == 1, "BOUNDED_ROLLBACK_TARGET_CARDINALITY")
    item = inspect_one(ids[0])
    state = item.get("State") or {}
    require(state.get("Running") is False and state.get("Status") in {"created", "exited"},
            "BOUNDED_ROLLBACK_STARTED_BEFORE_INSPECTION")
    env = env_map(item.get("Config", {}).get("Env") or [])
    old_env = env_map(old_item.get("Config", {}).get("Env") or [])
    require(item.get("Image") == EXPECTED_OLD_IMAGE, "BOUNDED_ROLLBACK_IMAGE_DRIFT")
    require(env == old_env, "BOUNDED_ROLLBACK_ENV_DRIFT")
    verify_recreated_topology(old_item, item)
    verify_host_mounts(item.get("Mounts") or [])
    require(canonical_digest(comparable_config(item)) == canonical_digest(comparable_config(old_item)), "BOUNDED_ROLLBACK_CONFIG_DRIFT")
    require(protected_digest(inspect_running()) == EXPECTED_PROTECTED, "BOUNDED_ROLLBACK_PROTECTED_DRIFT")
    verify_custody()
    verify_timing(rollback=True)
    start = run(["docker", "start", ids[0]], timeout=30)
    commands.append(command_receipt("bounded_rollback_single_original_start", start))
    require(start.returncode == 0 and not start.stderr, "BOUNDED_ROLLBACK_START_FAILED")
    item = wait_healthy(ids[0])
    health = http_read("/health")
    ready = http_read("/readyz")
    require(health["status"] == 200 and health["body"].get("status") == "ok", "ROLLBACK_HEALTH_ENDPOINT_FAILED")
    require(ready["status"] == 200 and ready["body"].get("status") == "ready", "ROLLBACK_READY_ENDPOINT_FAILED")
    store = redis_snapshot(item)
    require(store["namespace_key_count"] == 10698, "ROLLBACK_NAMESPACE_COUNT_DRIFT")
    require(store["selected"]["global_attribution"]["count"] == 5000, "ROLLBACK_GLOBAL_ATTRIBUTION_COUNT_DRIFT")
    require(store["selected"]["campaign_audit"]["count"] == 0, "ROLLBACK_CAMPAIGN_AUDIT_CREATED")
    require(store["selected"]["campaign_record"]["count"] == 0, "ROLLBACK_CAMPAIGN_CREATED")
    verify_timing(rollback=True)
    if stopped_at is not None:
        elapsed_bound(stopped_at, 840, "RECOVERY_COMPLETED_AFTER_MAX_OUTAGE")
    receipt = {
        "schema": "npd.agent-hub.phase9.gate-d.prestop-reseal.rollback-receipt.v1",
        "status": "ROLLED_BACK_VERIFIED",
        "attempt_id": CONTEXT["attempt_id"],
        "trigger": trigger,
        "completed_utc": iso(),
        "container_id": item.get("Id"),
        "image_id": item.get("Image"),
        "settings_restored": CONTEXT["settings_preimage"],
        "normal_scheduler_restored": env.get("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED") == "true" and "AGENT_RUNTIME_MODE" not in env,
        "protected18_sha256": EXPECTED_PROTECTED,
        "namespace_key_count": store["namespace_key_count"],
        "post_stop_authority_available": post_stop_store is not None,
        "normal_scheduler_bookkeeping_may_resume": True,
        "redis_restores": 0,
        "lead_writes": 0,
        "campaign_writes": 0,
        "retry": False,
    }
    receipt_sha = atomic_create(CONTROL / "rollback-receipt.json", canonical(receipt))
    receipt["receipt_sha256"] = receipt_sha
    return receipt


# This block is inserted into the previously accepted semantic-prestop runner.
# It changes only the rebind-specific bindings and Compose file stack.
CURRENT = Path(CONTEXT["current_override"])
OVERRIDE = CONTROL / "owner-only-override.json"


def verify_control_preimage() -> dict[str, str]:
    expected = {"approval-consumed.json", "owner-only-override.json",
                "preflight-evidence.json", "timing-receipt.json"}
    require(CONTROL.is_dir() and not CONTROL.is_symlink(), "CONTROL_DIRECTORY_UNSAFE")
    actual = {path.name for path in CONTROL.iterdir()}
    require(actual == expected, "CONTROL_INVENTORY_DRIFT")
    for path in CONTROL.iterdir():
        require(path.is_file() and not path.is_symlink(), "CONTROL_FILE_UNSAFE")
    hashes = {name: sha_file(CONTROL / name) for name in sorted(expected)}
    require(hashes["owner-only-override.json"] == CONTEXT["candidate_override_sha256"], "OVERRIDE_DRIFT")
    require(hashes["timing-receipt.json"] == CONTEXT["timing_receipt_sha256"], "TIMING_DRIFT")
    require(hashes["preflight-evidence.json"] == CONTEXT["preflight_evidence_sha256"], "PREFLIGHT_DRIFT")
    consumed = json.loads((CONTROL / "approval-consumed.json").read_bytes())
    require(consumed.get("status") == "GRANTED_EXACT_AND_CONSUMED", "APPROVAL_NOT_CONSUMED")
    require(consumed.get("attempt_id") == CONTEXT["attempt_id"], "ATTEMPT_DRIFT")
    require(consumed.get("approval_sha256") == CONTEXT["approval_sha256"], "APPROVAL_DRIFT")
    require(consumed.get("gate_d_sha256") == CONTEXT["gate_d_sha256"], "GATE_DRIFT")
    require(consumed.get("gate_c") == "NOT_GRANTED_NOT_EXECUTED" and consumed.get("retry") is False,
            "AUTHORITY_SCOPE_DRIFT")
    return hashes


def verify_files() -> None:
    require(sha_file(BASE) == CONTEXT["base_compose_sha256"], "BASE_COMPOSE_DRIFT")
    require(sha_file(RECOVERY) == CONTEXT["recovery_override_sha256"], "RECOVERY_OVERRIDE_DRIFT")
    require(sha_file(CURRENT) == CONTEXT["current_override_sha256"], "CURRENT_OVERRIDE_DRIFT")
    require(sha_file(OVERRIDE) == CONTEXT["candidate_override_sha256"], "OWNER_OVERRIDE_DRIFT")
    verify_host_sources()


def verify_native_preflight(commands: list[dict[str, object]]) -> None:
    for name, source_key, expected_sha in (
        ("native_no_email", "native_probe_b64", CONTEXT["native_probe_sha256"]),
        ("native_no_new_lead", "native_lead_probe_b64", CONTEXT["native_lead_probe_sha256"]),
    ):
        source = base64.b64decode(CONTEXT[source_key])
        require(sha(source) == expected_sha, "NATIVE_PROBE_SOURCE_DRIFT")
        result = run(["python3", "-B", "-"], input_bytes=source, timeout=30)
        commands.append(command_receipt(name, result))
        require(result.returncode == 0 and not result.stderr, "NATIVE_PREFLIGHT_FAILED")
        observation = json.loads(result.stdout)
        if name == "native_no_email":
            require(observation.get("status") == "PASS_NATIVE_MAIL_CONDITIONS_READONLY"
                    and observation.get("config_sha256") == CONTEXT["current_native_config_sha256"]
                    and (observation.get("users") or {}).get("owner", {}).get("id") == "6a4dd6d5c8ee64bed"
                    and (observation.get("users") or {}).get("creator", {}).get("id") == "6aab5af0215b97ba2"
                    and observation.get("writes") == 0, "NATIVE_CONFIG_OR_IDENTITY_DRIFT")
        else:
            require(observation.get("status") == "PASS_NATIVE_LEAD_GET_ONLY"
                    and observation.get("latest_before_gate_d_grant") is True
                    and observation.get("production_writes") == 0,
                    "NATIVE_LEAD_APPEARED")


def verify_old_target() -> dict[str, object]:
    require(target_ids() == [EXPECTED_OLD_CONTAINER], "TARGET_CARDINALITY_DRIFT")
    item = inspect_one(EXPECTED_OLD_CONTAINER)
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_OLD_IMAGE, "IMAGE_DRIFT")
    require(state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy",
            "RUNTIME_NOT_HEALTHY")
    require(item.get("RestartCount") == 0, "RESTART_COUNT_DRIFT")
    require(topology_digest(item) == CONTEXT["current_topology_sha256"], "TOPOLOGY_DRIFT")
    require(canonical_docker_mounts(item.get("Mounts") or [], target=True) == CONTEXT["sealed_mounts"], "MOUNTS_DRIFT")
    config = item.get("Config") or {}
    require(sha(json.dumps(config.get("Cmd"), sort_keys=True).encode()) == CONTEXT["sealed_command_sha256"], "COMMAND_DRIFT")
    require(sha(json.dumps(config.get("Entrypoint"), sort_keys=True).encode()) == CONTEXT["sealed_entrypoint_sha256"], "ENTRYPOINT_DRIFT")
    verify_host_mounts(item.get("Mounts") or [])
    env = env_map(item.get("Config", {}).get("Env") or [])
    require(canonical_digest(env) == CONTEXT["preflight"]["full_environment_fingerprint_sha256"],
            "FULL_ENV_DRIFT")
    state_of_settings = {name: {"present": name in env, "value": env.get(name)}
                         for name in CONTEXT["creation_settings"]}
    require(state_of_settings == CONTEXT["settings_preimage"], "SETTINGS_PREIMAGE_DRIFT")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.working_dir") == str(WORKDIR), "WORKDIR_DRIFT")
    require(labels.get("com.docker.compose.project.config_files") == f"{BASE},{RECOVERY},{CURRENT}",
            "COMPOSE_CONTEXT_DRIFT")
    for path, expected_status, expected_body in (("/health", 200, "ok"), ("/readyz", 200, "ready")):
        response = http_read(path)
        require(response["status"] == expected_status and response["body"].get("status") == expected_body,
                "HTTP_HEALTH_READY_DRIFT")
    return item


def verify_compose_render(old_item: dict[str, object]) -> dict[str, object]:
    common = ["docker", "compose", "--project-name", PROJECT,
              "-f", str(BASE), "-f", str(RECOVERY), "-f", str(CURRENT)]
    old_run = run(common + ["config", "--format", "json"], timeout=30,
                  environment=compose_environment())
    require(old_run.returncode == 0 and not old_run.stderr, "OLD_COMPOSE_RENDER_FAILED")
    new_run = run(common + ["-f", str(OVERRIDE), "config", "--format", "json"], timeout=30,
                  environment=compose_environment())
    require(new_run.returncode == 0 and not new_run.stderr, "NEW_COMPOSE_RENDER_FAILED")
    old = json.loads(old_run.stdout)
    new = json.loads(new_run.stdout)
    old_service = old.get("services", {}).get(SERVICE)
    new_service = new.get("services", {}).get(SERVICE)
    require(isinstance(old_service, dict) and isinstance(new_service, dict), "SERVICE_RENDER_MISSING")
    require(new_service.get("image") == EXPECTED_TAG == old_service.get("image"), "IMAGE_RENDER_DRIFT")
    verify_rendered_host_mounts(old_service.get("volumes") or [])
    verify_rendered_host_mounts(new_service.get("volumes") or [])
    old_env = old_service.get("environment") or {}
    new_env = new_service.get("environment") or {}
    require(old_env.get("AGENT_PHASE9_CREATION_OWNER_ID") == "6a658eeb6ab0c81ab",
            "OLD_OWNER_RENDER_DRIFT")
    require(new_env.get("AGENT_PHASE9_CREATION_OWNER_ID") == "6a4dd6d5c8ee64bed",
            "NEW_OWNER_RENDER_DRIFT")
    normalized_new = copy.deepcopy(new_service)
    normalized_new["environment"]["AGENT_PHASE9_CREATION_OWNER_ID"] = old_env["AGENT_PHASE9_CREATION_OWNER_ID"]
    require(normalized_new == old_service, "SECOND_AGENT_HUB_RENDER_DELTA")
    old_others = {key: value for key, value in old.get("services", {}).items() if key != SERVICE}
    new_others = {key: value for key, value in new.get("services", {}).items() if key != SERVICE}
    require(old_others == new_others, "PROTECTED_SERVICE_RENDER_DELTA")
    return {"status": "PASS_ONE_FIELD_COMPOSE_RENDER", "old_sha256": sha(old_run.stdout),
            "new_sha256": sha(new_run.stdout), "owner_before": old_env["AGENT_PHASE9_CREATION_OWNER_ID"],
            "owner_after": new_env["AGENT_PHASE9_CREATION_OWNER_ID"]}


def verify_pre_stop_store(snapshot: dict[str, object]) -> None:
    proof = validate_semantic_transition(CONTEXT["semantic_prestop_baseline"], snapshot)
    snapshot["semantic_transition"] = proof
    selected = snapshot["selected"]
    require(selected["campaign_record"]["count"] == 0, "COHORT_CAMPAIGN_ALREADY_EXISTS")
    require(selected["campaign_audit"]["count"] == 0, "COHORT_AUDIT_ALREADY_EXISTS")
    require(selected["global_attribution"]["count"] == 5000, "GLOBAL_AUDIT_COUNT_DRIFT")
    require(2000 - selected["campaign_audit"]["count"] >= 3, "INTERNAL_AUDIT_CAPACITY")


def compose_create(old_item: dict[str, object], commands: list[dict[str, object]],
                   stopped_at: datetime) -> dict[str, object]:
    verify_timing(decision=True)
    elapsed_bound(stopped_at, 210, "CANDIDATE_DECISION_EXCEEDED_210_SECONDS")
    result = run(["docker", "compose", "--project-name", PROJECT,
                  "-f", str(BASE), "-f", str(RECOVERY), "-f", str(CURRENT), "-f", str(OVERRIDE),
                  "up", "--no-start", "--no-deps", "--no-build", "--pull", "never",
                  "--force-recreate", SERVICE], timeout=120, environment=compose_environment())
    commands.append(command_receipt("owner_rebind_compose_create_no_start", result))
    require(result.returncode == 0, "OWNER_REBIND_COMPOSE_CREATE_FAILED")
    ids = target_ids()
    require(len(ids) == 1 and ids[0] != EXPECTED_OLD_CONTAINER, "RECREATED_TARGET_CARDINALITY")
    item = inspect_one(ids[0])
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_CANDIDATE_IMAGE, "RECREATED_IMAGE_DRIFT")
    require(state.get("Running") is False and state.get("Status") == "created", "STARTED_BEFORE_INSPECTION")
    effective_sha = verify_recreated_topology(old_item, item)
    verify_host_mounts(item.get("Mounts") or [])
    env = env_map(item.get("Config", {}).get("Env") or [])
    old_env = env_map(old_item.get("Config", {}).get("Env") or [])
    expected_env = dict(old_env)
    expected_env["AGENT_PHASE9_CREATION_OWNER_ID"] = "6a4dd6d5c8ee64bed"
    require(env == expected_env, "UNDECLARED_ENV_DELTA")
    for name, value in CONTEXT["creation_settings"].items():
        require(env.get(name) == value, "CREATION_FENCE_SETTING_DRIFT")
    require(canonical_digest(comparable_config(item)) == canonical_digest(comparable_config(old_item)),
            "SECOND_CONFIG_DELTA")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.working_dir") == str(WORKDIR), "WORKDIR_DRIFT")
    require(labels.get("com.docker.compose.project.config_files") == f"{BASE},{RECOVERY},{CURRENT},{OVERRIDE}",
            "NEW_COMPOSE_CONTEXT_DRIFT")
    verify_protected_and_custody()
    return {"container_id": ids[0], "image_id": item.get("Image"),
            "status": state.get("Status"), "running": False,
            "effective_topology_sha256": effective_sha,
            "comparable_config_sha256": canonical_digest(comparable_config(item)),
            "environment_fingerprint_sha256": canonical_digest(env)}


def write_before_receipts(old_item: dict[str, object], post_stop_store: dict[str, object],
                          render: dict[str, object], post_stop_reseal_sha256: str) -> tuple[str, str]:
    runtime = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.runtime-before.v1",
               "attempt_id": CONTEXT["attempt_id"], "captured_utc": iso(),
               "container": sanitized_container(old_item),
               "topology_sha256": topology_digest(old_item),
               "comparable_config_sha256": canonical_digest(comparable_config(old_item)),
               "full_environment_fingerprint_sha256": canonical_digest(
                   env_map(old_item.get("Config", {}).get("Env") or [])),
               "settings_preimage": CONTEXT["settings_preimage"],
               "compose_sha256": {"base": sha_file(BASE), "recovery": sha_file(RECOVERY),
                                  "current": sha_file(CURRENT), "owner_only": sha_file(OVERRIDE)},
               "compose_render": render, "post_stop_reseal_sha256": post_stop_reseal_sha256,
               "secret_values_retained": False}
    business = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.business-store-before.v1",
                "attempt_id": CONTEXT["attempt_id"], "captured_utc": iso(),
                "authority_source": "POST_STOP_RESEAL_ONLY", "snapshot": post_stop_store,
                "post_stop_reseal_sha256": post_stop_reseal_sha256,
                "DB1_writes": 0, "production_business_writes": 0}
    return (atomic_create(CONTROL / "runtime-before.json", canonical(runtime)),
            atomic_create(CONTROL / "business-store-before.json", canonical(business)))


def rollback_once(old_item: dict[str, object], post_stop_store: dict[str, object] | None,
                  stopped_at: datetime | None, trigger: str,
                  commands: list[dict[str, object]]) -> dict[str, object]:
    verify_timing(rollback=True)
    if stopped_at is not None:
        elapsed_bound(stopped_at, 840, "RECOVERY_EXCEEDED_840_SECONDS")
    ids = target_ids()
    require(len(ids) == 1, "ROLLBACK_TARGET_CARDINALITY")
    existing = inspect_one(ids[0])
    state = existing.get("State") or {}
    require(existing.get("Image") == EXPECTED_OLD_IMAGE == EXPECTED_CANDIDATE_IMAGE,
            "ROLLBACK_IMAGE_DRIFT")
    if state.get("Running") is True or state.get("Restarting") is True:
        stopped = run(["docker", "stop", "--time", "30", ids[0]], timeout=40)
        commands.append(command_receipt("rollback_stop_owned_target", stopped))
        require(stopped.returncode == 0, "ROLLBACK_TARGET_STOP_FAILED")
        require((inspect_one(ids[0]).get("State") or {}).get("Running") is False,
                "ROLLBACK_TARGET_STILL_RUNNING")
    created = run(["docker", "compose", "--project-name", PROJECT,
                   "-f", str(BASE), "-f", str(RECOVERY), "-f", str(CURRENT),
                   "up", "--no-start", "--no-deps", "--no-build", "--pull", "never",
                   "--force-recreate", SERVICE], timeout=150, environment=compose_environment())
    commands.append(command_receipt("rollback_recreate_original_creation_runtime", created))
    require(created.returncode == 0, "ROLLBACK_COMPOSE_FAILED")
    ids = target_ids()
    require(len(ids) == 1, "ROLLBACK_RECREATED_CARDINALITY")
    item = inspect_one(ids[0])
    state = item.get("State") or {}
    require(state.get("Running") is False and state.get("Status") == "created", "ROLLBACK_PRESTART_STATE")
    require(item.get("Image") == EXPECTED_OLD_IMAGE, "ROLLBACK_IMAGE_CHANGED")
    require(env_map(item.get("Config", {}).get("Env") or []) ==
            env_map(old_item.get("Config", {}).get("Env") or []), "ROLLBACK_ENV_CHANGED")
    verify_recreated_topology(old_item, item)
    verify_host_mounts(item.get("Mounts") or [])
    require(canonical_digest(comparable_config(item)) == canonical_digest(comparable_config(old_item)),
            "ROLLBACK_CONFIG_CHANGED")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.config_files") == f"{BASE},{RECOVERY},{CURRENT}",
            "ROLLBACK_COMPOSE_CONTEXT_DRIFT")
    verify_protected_and_custody()
    verify_timing(rollback=True)
    started = run(["docker", "start", ids[0]], timeout=30)
    commands.append(command_receipt("rollback_single_start", started))
    require(started.returncode == 0 and not started.stderr, "ROLLBACK_START_FAILED")
    item = wait_healthy(ids[0])
    health = http_read("/health")
    ready = http_read("/readyz")
    require(health["status"] == 200 and health["body"].get("status") == "ok", "ROLLBACK_HEALTH_FAILED")
    require(ready["status"] == 200 and ready["body"].get("status") == "ready", "ROLLBACK_READY_FAILED")
    env = env_map(item.get("Config", {}).get("Env") or [])
    require(env.get("AGENT_PHASE9_CREATION_OWNER_ID") == "6a658eeb6ab0c81ab" and
            env.get("AGENT_RUNTIME_MODE") == "phase9_creation" and
            env.get("AGENT_PROVIDER_HEALTH_SCHEDULER_ENABLED") == "false", "ROLLBACK_FENCE_DRIFT")
    store = redis_snapshot(item)
    if post_stop_store is not None:
        for field in ("namespace_keyset_sha256", "namespace_fingerprint_sha256",
                      "immutable_fingerprint_sha256", "audit_rows_sha256", "selected"):
            require(store[field] == post_stop_store[field], "ROLLBACK_STORE_DRIFT")
    verify_protected_and_custody()
    verify_timing(rollback=True)
    if stopped_at is not None:
        elapsed_bound(stopped_at, 840, "RECOVERY_COMPLETED_AFTER_BOUND")
    receipt = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.rollback.v1",
               "status": "ROLLED_BACK_VERIFIED", "attempt_id": CONTEXT["attempt_id"],
               "trigger": trigger, "completed_utc": iso(), "container_id": ids[0],
               "image_id": item.get("Image"), "settings_restored": CONTEXT["settings_preimage"],
               "provider_health_scheduler_enabled": False, "redis_restores": 0,
               "lead_writes": 0, "campaign_writes": 0, "retry": False}
    receipt["receipt_sha256"] = atomic_create(CONTROL / "rollback-receipt.json", canonical(receipt))
    return receipt


# __SHARED_PACKAGE_BINDING_CONTRACT__


def main() -> int:
    commands: list[dict[str, object]] = []
    stop_attempted = False
    stopped = False
    old_item: dict[str, object] | None = None
    post_stop_store: dict[str, object] | None = None
    stopped_at: datetime | None = None
    try:
        verify_package_contract(CONTEXT)
        require(CONTEXT["representation_contract_sha256"] == "__EXPECTED_REPRESENTATION_SHA256__", "REPRESENTATION_CONTRACT_HASH_INVALID")
        control_hashes = verify_control_preimage()
        verify_timing(entry=True)
        verify_files()
        require(CONTEXT["approval_sha256"] == "__EXPECTED_APPROVAL_SHA256__", "APPROVAL_HASH_INVALID")
        require(CONTEXT["gate_d_sha256"] == "__EXPECTED_GATE_D_SHA256__", "GATE_D_HASH_INVALID")
        require(CONTEXT["attempt_id"] not in CONTEXT["old_authority_denylist"], "STALE_ATTEMPT_DENIED")
        require(CONTEXT["approval_sha256"] not in CONTEXT["old_authority_denylist"], "CONSUMED_APPROVAL_DENIED")
        require(CONTEXT["timing_receipt_sha256"] not in CONTEXT["old_authority_denylist"], "STALE_TIMING_DENIED")

        old_item = verify_old_target()
        verify_protected_and_custody()
        verify_native_preflight(commands)
        image_verification = verify_imported_image(commands)
        render = verify_compose_render(old_item)
        pre_stop_store = redis_snapshot(old_item)
        verify_pre_stop_store(pre_stop_store)

        # Recheck all immutable/pre-stop bindings immediately before the only
        # runtime mutation. Mutable business digests are observed but not bound.
        verify_timing(entry=True, stop=True)
        verify_files()
        old_item = verify_old_target()
        verify_protected_and_custody()
        verify_native_preflight(commands)
        verify_imported_image(commands)
        pre_stop_store = redis_snapshot(old_item)
        verify_pre_stop_store(pre_stop_store)

        stop_attempted = True
        stopped_item, stopped_at, stop_receipt = stop_target_only(commands)
        stopped = True
        post_stop_store, post_stop_reseal_sha, reseal_receipt = post_stop_reseal(old_item, stopped_item, stopped_at)
        runtime_before_sha, business_before_sha = write_before_receipts(
            old_item, post_stop_store, render, post_stop_reseal_sha
        )

        created = compose_create(old_item, commands, stopped_at)
        started = start_once(str(created["container_id"]), commands, stopped_at)
        post = verify_post_start(
            str(created["container_id"]), old_item, post_stop_store, commands, stopped_at
        )
        verify_timing(verification=True, rollback=True)
        elapsed_bound(stopped_at, 420, "CANDIDATE_VERIFICATION_EXCEEDED_420_SECONDS")
        adoption = {
            "schema": "npd.agent-hub.phase9.owner-fence-rebind.adoption-receipt.v1",
            "status": "OWNER_FENCE_REBOUND_VERIFIED",
            "attempt_id": CONTEXT["attempt_id"],
            "completed_utc": iso(),
            "approval_sha256": CONTEXT["approval_sha256"],
            "gate_d_sha256": CONTEXT["gate_d_sha256"],
            "timing_receipt_sha256": CONTEXT["timing_receipt_sha256"],
            "control_preimage_hashes": control_hashes,
            "runtime_before_sha256": runtime_before_sha,
            "business_store_before_sha256": business_before_sha,
            "post_stop_reseal_sha256": post_stop_reseal_sha,
            "image_verification": image_verification,
            "compose_render": render,
            "target_only_stop": stop_receipt,
            "post_stop_reseal": reseal_receipt,
            "created_not_running_verification": created,
            "single_start": started,
            "post_start": post,
            "commands": commands,
            "source_head": CONTEXT["candidate_head"],
            "candidate_image_config": EXPECTED_CANDIDATE_IMAGE,
            "creation_settings": CONTEXT["creation_settings"],
            "scheduler_autonomous_writes": 0,
            "provider_calls": 0,
            "production_business_writes": 0,
            "redis_writes": 0,
            "gate_c": "PREPARED_NOT_GRANTED_NOT_EXECUTED",
            "business_uat": "NOT_RUN",
            "rollback_needed": False,
            "retry": False,
        }
        receipt_sha = atomic_create(CONTROL / "adoption-receipt.json", canonical(adoption))
        final_item = inspect_one(str(created["container_id"]))
        require(final_item.get("Image") == EXPECTED_CANDIDATE_IMAGE, "POST_RECEIPT_IMAGE_DRIFT")
        require((final_item.get("State") or {}).get("Running") is True, "POST_RECEIPT_RUNTIME_STOPPED")
        require(protected_digest(inspect_running()) == EXPECTED_PROTECTED, "POST_RECEIPT_PROTECTED_DRIFT")
        verify_custody()
        print(json.dumps({
            "status": "OWNER_FENCE_REBOUND_VERIFIED",
            "attempt_id": CONTEXT["attempt_id"],
            "adoption_receipt_sha256": receipt_sha,
            "post_stop_reseal_sha256": post_stop_reseal_sha,
            "container_id": created["container_id"],
            "image_id": EXPECTED_CANDIDATE_IMAGE,
            "runtime_mode": "phase9_creation",
            "scheduler_initialized": False,
            "autonomous_business_writes": 0,
            "provider_calls": 0,
            "production_business_writes": 0,
            "rollback_needed": False,
            "gate_c": "PREPARED_NOT_GRANTED_NOT_EXECUTED",
        }, sort_keys=True))
        return 0
    except Exception as exc:
        trigger = str(exc)
        needs_rollback = stopped
        if stop_attempted and not stopped and old_item is not None:
            try:
                current = inspect_one(EXPECTED_OLD_CONTAINER)
                state = current.get("State") or {}
                needs_rollback = not (
                    current.get("Image") == EXPECTED_OLD_IMAGE
                    and state.get("Running") is True
                    and (state.get("Health") or {}).get("Status") == "healthy"
                )
            except Exception:
                needs_rollback = True
        if needs_rollback and old_item is not None:
            try:
                rollback = rollback_once(old_item, post_stop_store, stopped_at, trigger, commands)
                print(json.dumps({
                    "status": "BLOCKED_GATE_D_ROLLED_BACK_VERIFIED",
                    "attempt_id": CONTEXT["attempt_id"],
                    "error": trigger,
                    "rollback": rollback,
                    "commands": commands,
                    "production_business_writes": 0,
                    "retry": False,
                    "gate_c": "NOT_GRANTED_NOT_EXECUTED",
                }, sort_keys=True))
                return 2
            except Exception as rollback_exc:
                print(json.dumps({
                    "status": "BLOCKED_GATE_D_ROLLBACK_AMBIGUOUS_OWNER_REVIEW",
                    "attempt_id": CONTEXT["attempt_id"],
                    "error": trigger,
                    "rollback_error": str(rollback_exc),
                    "commands": commands,
                    "production_business_writes": 0,
                    "retry": False,
                    "gate_c": "NOT_GRANTED_NOT_EXECUTED",
                }, sort_keys=True))
                return 3
        print(json.dumps({
            "status": "BLOCKED_GATE_D_BEFORE_RUNTIME_STOP",
            "attempt_id": CONTEXT.get("attempt_id"),
            "error": trigger,
            "commands": commands,
            "production_business_writes": 0,
            "retry": False,
            "gate_c": "NOT_GRANTED_NOT_EXECUTED",
        }, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
