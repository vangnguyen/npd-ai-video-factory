from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path

# __SHARED_REPRESENTATION_SOURCE__


CONTEXT = json.loads(base64.b64decode("__EXECUTION_CONTEXT_B64__"))
CONTROL = Path(CONTEXT["control_directory"])
PARENT = CONTROL.parent
WORKDIR = Path(CONTEXT["workdir"])
BASE = Path(CONTEXT["base_compose"])
RECOVERY = Path(CONTEXT["recovery_override"])
CURRENT = Path(CONTEXT["current_override"])
EXPECTED_CONTAINER = CONTEXT["current_container_id"]
EXPECTED_IMAGE = CONTEXT["rollback_image_config"]
PROJECT = "npd-agent-hub-prod"
SERVICE = "agent-hub"
HOST_SOURCES = {
    "GA4_SERVICE_ACCOUNT_HOST_FILE": ("/etc/npd-ai/ga4-agent-hub-readonly.json", "36519be007706e8d0245c6cfef1ed2cf37ef992c2fc2dacdc4290d2fe6c895a7"),
    "AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE": ("/etc/npd-ai/agent-attribution-verification-keys.json", "ea6346727e1237e078e45efd5e055b747aa506b01b0e38d9c0b6164afc157922"),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise RuntimeError(reason)


def run(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, timeout=timeout, shell=False)


def file_sha(path: Path) -> str:
    require(path.is_file() and not path.is_symlink(), f"UNSAFE_FILE:{path}")
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_host_sources() -> None:
    for name, (source, expected_sha) in HOST_SOURCES.items():
        path = Path(source)
        require(path.is_file() and not path.is_symlink(), f"HOST_SOURCE_MISSING:{name}")
        require(stat.S_IMODE(path.stat().st_mode) == 0o600, f"HOST_SOURCE_MODE_DRIFT:{name}")
        require(file_sha(path) == expected_sha, f"HOST_SOURCE_DIGEST_DRIFT:{name}")


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
    require(path.is_file() and not path.is_symlink() and file_sha(path) == sha(raw), f"CONTROL_WRITE_VERIFY_FAILED:{path.name}")
    return sha(raw)


def current_target() -> dict[str, object]:
    ps = run([
        "docker", "ps", "-aq", "--no-trunc",
        "--filter", f"label=com.docker.compose.project={PROJECT}",
        "--filter", f"label=com.docker.compose.service={SERVICE}",
    ])
    require(ps.returncode == 0 and not ps.stderr, "DOCKER_PS_FAILED")
    ids = [x.strip() for x in ps.stdout.decode("ascii").splitlines() if x.strip()]
    require(ids == [EXPECTED_CONTAINER], "OWNED_RUNTIME_IDENTITY_DRIFT")
    inspected = run(["docker", "inspect", EXPECTED_CONTAINER])
    require(inspected.returncode == 0 and not inspected.stderr, "DOCKER_INSPECT_FAILED")
    return json.loads(inspected.stdout)[0]


# __SHARED_PACKAGE_BINDING_CONTRACT__


def main() -> int:
    verify_package_contract(CONTEXT)
    require(CONTEXT["representation_contract_sha256"] == "__EXPECTED_REPRESENTATION_SHA256__", "REPRESENTATION_CONTRACT_HASH_INVALID")
    require(sha(base64.b64decode(CONTEXT["approval_b64"])) == CONTEXT["approval_sha256"], "APPROVAL_BYTES_INVALID")
    require(CONTEXT["approval_sha256"] == "__EXPECTED_APPROVAL_SHA256__", "APPROVAL_HASH_INVALID")
    require(CONTEXT["gate_d_sha256"] == "__EXPECTED_GATE_D_SHA256__", "GATE_D_HASH_INVALID")
    require(CONTEXT["candidate_head"] == "538c30bd72fd7ef763bc3e235e50d6c0d8b86bbf", "HEAD_INVALID")
    require(file_sha(BASE) == CONTEXT["base_compose_sha256"], "BASE_COMPOSE_DRIFT")
    require(file_sha(RECOVERY) == CONTEXT["recovery_override_sha256"], "RECOVERY_OVERRIDE_DRIFT")
    require(file_sha(CURRENT) == CONTEXT["current_override_sha256"], "CURRENT_OVERRIDE_DRIFT")
    verify_host_sources()
    require(not os.path.lexists(CONTROL), "APPROVAL_ALREADY_CONSUMED_OR_CONTROL_EXISTS")
    issued = parse_time(CONTEXT["timing"]["issued_utc"])
    grant = parse_time(CONTEXT["timing"]["owner_grant_observed_utc"])
    require(issued >= grant and (now() - issued).total_seconds() >= 0, "TIMING_ISSUANCE_INVALID")
    require(CONTEXT["timing"]["attempt_id"] == CONTEXT["attempt_id"], "TIMING_ATTEMPT_MISMATCH")
    require(CONTEXT["timing"]["gate_d_sha256"] == CONTEXT["gate_d_sha256"], "TIMING_GATE_MISMATCH")
    require(CONTEXT["timing"]["approval_sha256"] == CONTEXT["approval_sha256"], "TIMING_APPROVAL_MISMATCH")
    exact_offsets = {
        "entry_deadline_utc": 600,
        "stop_completion_deadline_utc": 660,
        "candidate_decision_deadline_utc": 870,
        "candidate_verification_deadline_utc": 1080,
        "recovery_completion_deadline_utc": 1500,
    }
    for key, seconds in exact_offsets.items():
        require((parse_time(CONTEXT["timing"][key]) - issued).total_seconds() == seconds, "TIMING_BOUND_INVALID")
    require((parse_time(CONTEXT["timing"]["entry_deadline_utc"]) - now()).total_seconds() >= 60, "BEGIN_RESERVE_BELOW_60")
    timing_raw = canonical(CONTEXT["timing"])
    require(sha(timing_raw) == CONTEXT["timing_receipt_sha256"], "TIMING_RECEIPT_HASH_INVALID")
    preflight = CONTEXT["preflight"]
    require(preflight["attempt_id"] == CONTEXT["attempt_id"], "STALE_PREFLIGHT_ATTEMPT_DENIED")
    require(preflight["approval_sha256"] == CONTEXT["approval_sha256"], "STALE_PREFLIGHT_APPROVAL_DENIED")
    require(preflight["gate_d_sha256"] == CONTEXT["gate_d_sha256"], "STALE_PREFLIGHT_GATE_DENIED")
    require(preflight["semantic_baseline_projection_sha256"] == CONTEXT["semantic_baseline_projection_sha256"], "STALE_PREFLIGHT_BASELINE_DENIED")
    sealed = parse_time(preflight["sealed_utc"])
    require(sealed.tzinfo is not None and sealed.utcoffset() is not None, "PREFLIGHT_TIME_NOT_AWARE")
    require(issued <= sealed < parse_time(CONTEXT["timing"]["entry_deadline_utc"]), "STALE_PREFLIGHT_TIME_DENIED")
    require((parse_time(CONTEXT["timing"]["entry_deadline_utc"]) - sealed).total_seconds() >= 120, "PREFLIGHT_RESERVE_BELOW_120")
    require(sha(canonical(preflight)) == CONTEXT["preflight_evidence_sha256"], "PREFLIGHT_BYTES_MISMATCH")
    item = current_target()
    state = item.get("State") or {}
    require(item.get("Image") == EXPECTED_IMAGE, "CURRENT_IMAGE_DRIFT")
    require(canonical_docker_mounts(item.get("Mounts") or [], target=True) == CONTEXT["sealed_mounts"], "CURRENT_MOUNTS_DRIFT")
    require(semantic_topology_digest(item) == CONTEXT["current_topology_sha256"], "CURRENT_TOPOLOGY_DRIFT")
    config = item.get("Config") or {}
    require(sha(json.dumps(config.get("Cmd"), sort_keys=True).encode()) == CONTEXT["sealed_command_sha256"], "CURRENT_COMMAND_DRIFT")
    require(sha(json.dumps(config.get("Entrypoint"), sort_keys=True).encode()) == CONTEXT["sealed_entrypoint_sha256"], "CURRENT_ENTRYPOINT_DRIFT")
    require(state.get("Running") is True and (state.get("Health") or {}).get("Status") == "healthy", "CURRENT_RUNTIME_NOT_HEALTHY")
    labels = item.get("Config", {}).get("Labels") or {}
    require(labels.get("com.docker.compose.project.working_dir") == str(WORKDIR), "WORKDIR_DRIFT")
    require(labels.get("com.docker.compose.project.config_files") == f"{BASE},{RECOVERY},{CURRENT}", "COMPOSE_CONTEXT_DRIFT")
    env = {}
    for row in item.get("Config", {}).get("Env") or []:
        key, sep, value = row.partition("=")
        require(bool(sep) and key not in env, "ENV_INVALID")
        env[key] = value
    require(sha(json.dumps(env, sort_keys=True, separators=(",", ":")).encode()) == CONTEXT["preflight"]["full_environment_fingerprint_sha256"], "CURRENT_ENV_DRIFT")
    require({name: {"present": name in env, "value": env.get(name)} for name in CONTEXT["creation_settings"]} == CONTEXT["settings_preimage"], "SETTINGS_PREIMAGE_DRIFT")

    root = Path("/var/lib/npd-ai/agent-hub-deployments")
    require(root.is_dir() and not root.is_symlink(), "DEPLOYMENT_ROOT_UNSAFE")
    gate_parent = PARENT.parent
    if not gate_parent.exists():
        os.mkdir(gate_parent, mode=0o700)
    require(gate_parent.is_dir() and not gate_parent.is_symlink(), "GATE_PARENT_UNSAFE")
    if not PARENT.exists():
        os.mkdir(PARENT, mode=0o700)
    require(PARENT.is_dir() and not PARENT.is_symlink(), "CONTROL_PARENT_UNSAFE")
    os.mkdir(CONTROL, mode=0o700)
    timing_sha = atomic_create(CONTROL / "timing-receipt.json", timing_raw)
    override_raw = base64.b64decode(CONTEXT["override_b64"])
    require(sha(override_raw) == CONTEXT["candidate_override_sha256"], "OVERRIDE_BYTES_INVALID")
    override_sha = atomic_create(CONTROL / "owner-only-override.json", override_raw)
    preflight_raw = canonical(CONTEXT["preflight"])
    preflight_sha = atomic_create(CONTROL / "preflight-evidence.json", preflight_raw)
    consumed = {
        "schema": "npd.agent-hub.phase9.owner-fence-rebind.approval-consumption.v1",
        "status": "GRANTED_EXACT_AND_CONSUMED",
        "attempt_id": CONTEXT["attempt_id"],
        "consumed_utc": now().isoformat(),
        "approval_sha256": CONTEXT["approval_sha256"],
        "gate_d_sha256": CONTEXT["gate_d_sha256"],
        "timing_receipt_sha256": timing_sha,
        "preflight_evidence_sha256": preflight_sha,
        "candidate_override_sha256": override_sha,
        "candidate_image_expected_config": CONTEXT["candidate_image_config"],
        "candidate_image_semantic_sha256": CONTEXT["candidate_image_semantic_sha256"],
        "candidate_head": CONTEXT["candidate_head"],
        "scope": "AGENT_HUB_OWNER_FENCE_REBIND_ONLY",
        "gate_c": "NOT_GRANTED_NOT_EXECUTED",
        "retry": False,
    }
    consumed_raw = canonical(consumed)
    consumed_sha = atomic_create(CONTROL / "approval-consumed.json", consumed_raw)
    directory_fd = os.open(CONTROL, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    print(json.dumps({
        "status": "PASS_OWNER_FENCE_APPROVAL_CONSUMED_CONTROL_INITIALIZED",
        "attempt_id": CONTEXT["attempt_id"],
        "control_directory": str(CONTROL),
        "approval_consumed_sha256": consumed_sha,
        "timing_receipt_sha256": timing_sha,
        "preflight_evidence_sha256": preflight_sha,
        "override_sha256": override_sha,
        "entry_deadline_utc": CONTEXT["timing"]["entry_deadline_utc"],
        "stop_completion_deadline_utc": CONTEXT["timing"]["stop_completion_deadline_utc"],
        "candidate_decision_deadline_utc": CONTEXT["timing"]["candidate_decision_deadline_utc"],
        "candidate_verification_deadline_utc": CONTEXT["timing"]["candidate_verification_deadline_utc"],
        "recovery_completion_deadline_utc": CONTEXT["timing"]["recovery_completion_deadline_utc"],
        "production_business_writes": 0,
        "gate_c": "NOT_GRANTED_NOT_EXECUTED",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED_OWNER_FENCE_BEGIN", "error": str(exc), "production_business_writes": 0}, sort_keys=True))
        raise SystemExit(2)
