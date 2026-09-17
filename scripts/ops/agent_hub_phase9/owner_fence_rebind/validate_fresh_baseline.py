"""Validate the preparation-only production snapshot without issuing timing."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from owner_fence_representation import canonical_docker_mounts


ROOT = Path(__file__).resolve().parent
GATE = json.loads((ROOT / "GATE_OWNER_FENCE_REBIND.json").read_bytes())
CAPTURES = ("runtime", "hub", "custody", "strict_protected", "native", "render", "semantic", "host", "lead")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read(name):
    prefix = ROOT / ("FRESH_" + name)
    plan = json.loads(prefix.with_suffix(".plan.json").read_bytes())
    capture = json.loads(prefix.with_suffix(".capture.json").read_bytes())
    stdout = prefix.with_suffix(".stdout.bin").read_bytes()
    stderr = prefix.with_suffix(".stderr.bin").read_bytes()
    assert capture["exit_code"] == 0 and capture["transport_error"] is None and not stderr
    payload_name = {"runtime": "creation_runtime_readonly.py", "hub": "hub_state_readonly.py",
                 "custody": "custody_protected_readonly.py", "strict_protected": "strict_protected_readonly.payload.py", "native": "native_mail_conditions_readonly.py",
                    "render": "owner_fence_compose_render_readonly.py",
                    "semantic": "semantic_current_sealed_readonly.py",
                 "host": "host_topology_attempt_readonly.payload.py", "lead": "native_lead_readonly.py"}[name]
    assert plan["UUID"] == capture["UUID"]
    assert plan["payload_sha256"] == GATE["preflight_payload_sha256"][payload_name]
    assert capture["raw_stdout_sha256"] == sha(stdout)
    result = json.loads(stdout)
    assert result.get("production_writes", result.get("writes")) == 0
    return result, sha(stdout)


def main():
    results = {name: read(name) for name in CAPTURES}
    runtime, hub, custody, strict_protected, native, render, semantic, host, lead = (
        results[name][0] for name in CAPTURES
    )
    assert runtime["status"] == "PASS_CREATION_RUNTIME_READONLY"
    assert runtime["container_id"] == GATE["target"]["container_id"]
    assert runtime["image_id"] == GATE["target"]["image_id"]
    assert runtime["running"] and runtime["health_status"] == "healthy"
    assert runtime["restart_count"] == 0
    assert runtime["health_readback"] == {"/health": 200, "/readyz": 200}
    assert runtime["creation_settings"] == GATE["target"]["settings_before"]
    assert runtime["full_environment_sha256"] == GATE["target"]["environment_sha256"]
    assert canonical_docker_mounts(runtime["mounts_full"], target=True) == GATE["target"]["mounts_full"]
    assert runtime["networks"] == GATE["target"]["networks"]
    assert runtime["ports"] == GATE["target"]["ports"]
    assert hub["status"] == "PASS_HUB_STATE_READONLY"
    assert hub["state"] == {"namespace_count": 10698, "audit_type": "none",
                            "audit_count": 0, "campaign_exists": False}
    assert custody["status"] == "PASS_PROTECTED_AND_TERMINAL_CUSTODY_READONLY"
    assert custody["protected_unchanged"] and custody["terminal_custody_unchanged"]
    assert custody["protected_sha256"] == "6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e"
    assert strict_protected["status"] == "PASS_STRICT_PROTECTED_READONLY"
    assert strict_protected["protected_count"] == 18
    assert strict_protected["strict_protected_sha256"] == GATE["strict_protected_sha256"]
    assert native["status"] == "PASS_NATIVE_MAIL_CONDITIONS_READONLY"
    assert native["config_sha256"] == GATE["current_native_config_sha256"]
    assert native["matching_internal_lead_name_count"] == 0
    assert native["users"]["owner"]["id"] == "6a4dd6d5c8ee64bed"
    assert native["users"]["creator"]["id"] == "6aab5af0215b97ba2"
    assert render["status"] == "PASS_OWNER_FENCE_COMPOSE_RENDER_READONLY"
    assert render["only_agent_hub_owner_env_delta"] is True
    assert semantic["status"] == "PASS_RUNNER_LIVE_SEMANTIC_VALIDATOR_READONLY"
    assert semantic["proof"]["status"] == "PASS_PRESTOP_SEMANTIC_TRANSITION"
    assert semantic["proof"]["immutable_key_count"] == 692
    assert host["status"] == "PASS_HOST_TOPOLOGY_ATTEMPT_READONLY"
    assert host["topology_sha256"] == "24947dc3fe36b785f9d4eca3b952d84ca1a47dbe6a32c89d80323a9489d0bd5a"
    assert host["attempt_control_absent"] is True
    assert lead["status"] == "PASS_NATIVE_LEAD_GET_ONLY"
    assert lead["latest_before_gate_d_grant"] is True
    receipt = {
        "schema": "npd.agent-hub.phase9.owner-fence-rebind.preparation-baseline.v2",
        "status": "PASS_READONLY_PREPARATION_SNAPSHOT",
        "observed_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "attempt_id": GATE["attempt_id"],
        "capture_sha256": {name: results[name][1] for name in CAPTURES},
        "container_id": runtime["container_id"],
        "owner_fence": runtime["creation_settings"]["AGENT_PHASE9_CREATION_OWNER_ID"],
        "db1_namespace_count": hub["state"]["namespace_count"],
        "campaign_absent": not hub["state"]["campaign_exists"],
        "campaign_audit_count": hub["state"]["audit_count"],
        "protected_services_unchanged": "18/18",
        "terminal_custody_unchanged": True,
        "native_config_sha256": native["config_sha256"],
        "semantic_immutable_key_count": semantic["proof"]["immutable_key_count"],
        "production_writes": 0,
        "execution_preflight_reuse": "DENY_FRESH_REQUIRED_AFTER_OWNER_CONSENT",
    }
    raw = canonical(receipt)
    (ROOT / "FRESH_READONLY_BASELINE_RECEIPT.json").write_bytes(raw)
    print(json.dumps({"status": receipt["status"], "receipt_sha256": sha(raw),
                      "attempt_id": receipt["attempt_id"]}, sort_keys=True))


if __name__ == "__main__":
    main()
