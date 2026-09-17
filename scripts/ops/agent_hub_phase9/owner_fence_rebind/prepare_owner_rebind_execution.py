"""Local-only package check; timing/preflight require a later Owner consent."""
from __future__ import annotations
import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from owner_fence_representation import canonical_docker_mounts, semantic_topology_digest

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
PACKAGE = ROOT
PRIOR = ROOT.parents[0] / "ah-p9-gate-d-execution-20260917-attempt-eab3a5b8"
SOURCE = WORKSPACE / "work/ah-p9-creation-runtime-fence-source"
SEALED = json.loads((ROOT / "STATIC_PACKAGE_MANIFEST.json").read_bytes())
GATE_SHA = SEALED["gate_sha256"]
APPROVAL_SHA = SEALED["approval_sha256"]
ATTEMPT = SEALED["attempt_id"]
TARGET = "d61f0994a0c84d0ab4687211f0c15b077fb360a6241f7493b94b59f36341b344"
PROTECTED = "6e0167343174e4cb719b3799015dc5d438b8cdcc545774dc72d53f61cf2c648e"

def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()

def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()

def load_capture(name: str, expected_payload_sha256: str) -> dict:
    prefix = ROOT / f"FRESH_{name}"
    plan = json.loads(prefix.with_suffix(".plan.json").read_bytes())
    capture = json.loads(prefix.with_suffix(".capture.json").read_bytes())
    out = prefix.with_suffix(".stdout.bin").read_bytes()
    err = prefix.with_suffix(".stderr.bin").read_bytes()
    assert capture["exit_code"] == 0 and not err and not capture["transport_error"]
    assert plan["UUID"] == capture["UUID"] and plan["payload_sha256"] == expected_payload_sha256
    assert capture["raw_stdout_sha256"] == sha(out)
    return json.loads(out)

def static() -> None:
    gate_raw = (PACKAGE / "GATE_OWNER_FENCE_REBIND.json").read_bytes()
    approval = (PACKAGE / "EXACT_OWNER_REBIND_APPROVAL_DRAFT.txt").read_bytes()
    gate = json.loads(gate_raw)
    assert sha(gate_raw) == GATE_SHA and sha(approval) == APPROVAL_SHA
    assert gate["attempt_id"] == ATTEMPT and gate["status"] == "PREPARED_NOT_GRANTED_NOT_EXECUTED"
    assert gate["owner_approval"] == "NOT_GRANTED" and gate["task"] == "AH-P9-GATE-C-OWNER-FENCE-REBIND"
    assert ATTEMPT.encode() in approval and GATE_SHA.encode() in approval
    assert sha((PACKAGE / "EMAIL_PATH_PROOF.json").read_bytes()) == gate["email_path_proof_sha256"]
    assert sha((ROOT / "package_binding_contract.py").read_bytes()) == gate["package_binding_contract_sha256"]
    assert sha((ROOT / "owner_fence_representation.py").read_bytes()) == gate["representation_contract_sha256"]
    assert (ROOT / "owner_fence_representation.py").read_bytes() == (SOURCE / "scripts/ops/agent_hub_phase9/owner_fence_representation.py").read_bytes()
    for field, filename in (("mount_rca_sha256", "MOUNT_RCA.json"),
                            ("representation_registry_sha256", "REPRESENTATION_REGISTRY.json"),
                            ("cross_representation_audit_sha256", "CROSS_REPRESENTATION_AUDIT.json")):
        assert sha((ROOT / filename).read_bytes()) == gate[field]
    assert sha((ROOT / "owner_rebind_begin.template.py").read_bytes()) == gate["begin_template_sha256"]
    assert sha((ROOT / "owner_rebind_execute.template.py").read_bytes()) == gate["execute_template_sha256"]
    assert sha((ROOT / "prepare_owner_rebind_execution.py").read_bytes()) == gate["package_producer_sha256"]
    for name in ("creation_runtime_readonly.py", "host_topology_attempt_readonly.py",
                 "strict_protected_readonly.py", "owner_rebind_begin.template.py",
                 "owner_rebind_execute.template.py", "package_binding_contract.py",
                 "prepare_owner_rebind_execution.py", "validate_fresh_baseline.py",
                 "render_readonly_payloads.py"):
        assert (ROOT / name).read_bytes() == (SOURCE / "scripts/ops/agent_hub_phase9/owner_fence_rebind" / name).read_bytes()
    for name, digest in gate["preflight_payload_sha256"].items():
        assert sha((ROOT / name).read_bytes()) == digest
    shared = (ROOT / "owner_fence_representation.py").read_text(encoding="utf-8")
    for template in ("host_topology_attempt_readonly.py", "strict_protected_readonly.py"):
        original = (ROOT / template).read_text(encoding="utf-8")
        assert original.count("# __SHARED_REPRESENTATION_SOURCE__") == 1
        rendered = original.replace("# __SHARED_REPRESENTATION_SOURCE__", shared)
        assert (ROOT / template.replace(".py", ".payload.py")).read_text(encoding="utf-8") == rendered
    transport = ROOT.parents[0] / "ah-p9-gate-d-fresh-semantic-prestop-20260915/invoke_remote_capture.py"
    assert sha(transport.read_bytes()) == gate["capture_transport_sha256"]
    assert sha((ROOT.parents[0] / "ah-p9-gate-d-timing-window-correction-20260917" /
                "GATE_D_SEMANTIC_PRESTOP_CONTRACT.json").read_bytes()) == gate["inherited_semantic_prestop_contract_sha256"]
    assert sha((PRIOR / "HANDOFF_RECEIPT.json").read_bytes()) == gate["gate_d_pass_handoff_sha256"]
    override = (ROOT / "OWNER_FENCE_OVERRIDE_CANDIDATE.json").read_bytes()
    assert sha(override) == gate["compose"]["new_public_override_local_sha256"]
    assert json.loads(override) == {"services": {"agent-hub": {"environment": {
        "AGENT_PHASE9_CREATION_OWNER_ID": "6a4dd6d5c8ee64bed"}}}}
    old = json.loads((PRIOR / "EXECUTION_CONTEXT.json").read_bytes())
    assert old["candidate_head"] == "538c30bd72fd7ef763bc3e235e50d6c0d8b86bbf"
    assert old["semantic_prestop_baseline"] == json.loads((ROOT.parents[0] /
        "ah-p9-gate-d-timing-window-correction-20260917/SEMANTIC_BASELINE.json").read_bytes())["projection"]
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=SOURCE, text=True).strip()
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=SOURCE, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=SOURCE, text=True).strip()
    assert head == gate["tooling_source_head"] and branch == "feat/agent-hub-p9-owner-fence-canonical-contract" and not dirty
    assert subprocess.run(["git", "merge-base", "--is-ancestor", "538c30bd72fd7ef763bc3e235e50d6c0d8b86bbf", head], cwd=SOURCE).returncode == 0
    assert all(sha((SOURCE / "services/agent_hub" / path.removeprefix("services/agent_hub/")).read_bytes()) == digest
               for path, digest in old["source_sha256"].items())
    for path in (ROOT / "owner_rebind_begin.template.py", ROOT / "owner_rebind_execute.template.py"):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")
    receipt = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.static-preparation.v2",
               "attempt_id": ATTEMPT, "gate_sha256": GATE_SHA, "approval_sha256": APPROVAL_SHA,
               "candidate_head": head, "source_count": len(old["source_sha256"]),
               "override_sha256": sha(override), "package_binding_contract_sha256": sha((ROOT / "package_binding_contract.py").read_bytes()),
               "begin_template_sha256": sha((ROOT / "owner_rebind_begin.template.py").read_bytes()),
               "execute_template_sha256": sha((ROOT / "owner_rebind_execute.template.py").read_bytes()),
               "consent_provenance": "NOT_GRANTED", "status": "PASS_STATIC_PACKAGE", "production_writes": 0}
    (ROOT / "STATIC_PREPARATION_RECEIPT.json").write_bytes(canonical(receipt))
    print(json.dumps(receipt, sort_keys=True))

def timing(owner_grant_observed_utc: str) -> None:
    static()
    assert json.loads((ROOT / "STATIC_PREPARATION_RECEIPT.json").read_bytes())["status"] == "PASS_STATIC_PACKAGE"
    issued = datetime.now(timezone.utc)
    grant = datetime.fromisoformat(owner_grant_observed_utc.replace("Z", "+00:00"))
    assert grant.tzinfo is not None and issued >= grant
    receipt = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.timing.v1",
               "attempt_id": ATTEMPT, "gate_d_sha256": GATE_SHA, "approval_sha256": APPROVAL_SHA,
               "owner_grant_observed_utc": owner_grant_observed_utc,
               "issued_utc": issued.isoformat().replace("+00:00", "Z")}
    for name, seconds in (("entry_deadline_utc", 600), ("stop_completion_deadline_utc", 660),
                          ("candidate_decision_deadline_utc", 870),
                          ("candidate_verification_deadline_utc", 1080),
                          ("recovery_completion_deadline_utc", 1500)):
        receipt[name] = (issued + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")
    raw = canonical(receipt)
    path = ROOT / "TIMING_RECEIPT.json"
    assert not path.exists()
    with path.open("xb") as file:
        file.write(raw)
    print(json.dumps({"status": "PASS_FRESH_TIMING", "sha256": sha(raw), "issued_utc": receipt["issued_utc"],
                      "entry_deadline_utc": receipt["entry_deadline_utc"]}, sort_keys=True))

def preflight() -> None:
    static()
    gate = json.loads((PACKAGE / "GATE_OWNER_FENCE_REBIND.json").read_bytes())
    old = json.loads((PRIOR / "EXECUTION_CONTEXT.json").read_bytes())
    timing_raw = (ROOT / "TIMING_RECEIPT.json").read_bytes()
    timing_data = json.loads(timing_raw)
    payloads = gate["preflight_payload_sha256"]
    payload_name = {"runtime": "creation_runtime_readonly.py",
                    "hub": "hub_state_readonly.py",
                    "custody": "custody_protected_readonly.py",
                    "strict_protected": "strict_protected_readonly.payload.py",
                    "native": "native_mail_conditions_readonly.py",
                    "render": "owner_fence_compose_render_readonly.py",
                    "semantic": "semantic_current_sealed_readonly.py",
                    "host": "host_topology_attempt_readonly.payload.py",
                    "lead": "native_lead_readonly.py"}
    results = {name: load_capture(name, payloads[payload_name[name]]) for name in payload_name}
    issued = datetime.fromisoformat(timing_data["issued_utc"].replace("Z", "+00:00"))
    for name in results:
        captured = json.loads((ROOT / f"FRESH_{name}.capture.json").read_bytes())
        captured_utc = datetime.fromisoformat(captured["UTC"].replace("Z", "+00:00"))
        assert issued <= captured_utc <= datetime.now(timezone.utc), "STALE_PRECONSENT_CAPTURE_DENIED"
    runtime = results["runtime"]
    assert runtime["status"] == "PASS_CREATION_RUNTIME_READONLY"
    assert runtime["container_id"] == TARGET and runtime["image_id"] == gate["target"]["image_id"]
    assert runtime["running"] is True and runtime["health_status"] == "healthy" and runtime["restart_count"] == 0
    assert runtime["health_readback"] == {"/health": 200, "/readyz": 200}
    assert runtime["full_environment_sha256"] == gate["target"]["environment_sha256"]
    assert runtime["environment_count"] == gate["target"]["environment_count"]
    assert runtime["creation_settings"] == gate["target"]["settings_before"]
    assert canonical_docker_mounts(runtime["mounts_full"], target=True) == gate["target"]["mounts_full"]
    assert runtime["networks"] == gate["target"]["networks"]
    assert runtime["command_sha256"] == gate["target"]["command_sha256"]
    assert runtime["entrypoint_sha256"] == gate["target"]["entrypoint_sha256"]
    assert runtime["ports"] == gate["target"]["ports"]
    assert runtime["compose_files"] == gate["compose"]["existing_files"]
    assert results["hub"]["status"] == "PASS_HUB_STATE_READONLY"
    assert results["hub"]["state"] == {"namespace_count": 10698, "audit_type": "none",
                                           "audit_count": 0, "campaign_exists": False}
    assert results["custody"]["status"] == "PASS_PROTECTED_AND_TERMINAL_CUSTODY_READONLY"
    assert results["custody"]["protected_sha256"] == PROTECTED
    assert results["custody"]["protected_unchanged"] is True and results["custody"]["terminal_custody_unchanged"] is True
    assert results["strict_protected"]["status"] == "PASS_STRICT_PROTECTED_READONLY"
    assert results["strict_protected"]["protected_count"] == 18
    assert results["strict_protected"]["strict_protected_sha256"] == gate["strict_protected_sha256"]
    assert results["native"]["status"] == "PASS_NATIVE_MAIL_CONDITIONS_READONLY"
    assert results["native"]["config_sha256"] == gate["current_native_config_sha256"]
    assert results["native"]["users"]["creator"]["id"] == "6aab5af0215b97ba2"
    assert results["native"]["users"]["owner"]["id"] == "6a4dd6d5c8ee64bed"
    assert results["render"]["status"] == "PASS_OWNER_FENCE_COMPOSE_RENDER_READONLY"
    assert results["render"]["only_agent_hub_owner_env_delta"] is True
    assert results["semantic"]["status"] == "PASS_RUNNER_LIVE_SEMANTIC_VALIDATOR_READONLY"
    assert results["semantic"]["proof"]["status"] == "PASS_PRESTOP_SEMANTIC_TRANSITION"
    assert results["semantic"]["proof"]["immutable_key_count"] == 692
    assert results["host"]["status"] == "PASS_HOST_TOPOLOGY_ATTEMPT_READONLY"
    assert results["host"]["topology_sha256"] == old["current_topology_sha256"]
    assert results["host"]["attempt_control_absent"] is True
    assert results["lead"]["status"] == "PASS_NATIVE_LEAD_GET_ONLY"
    assert results["lead"]["latest_before_gate_d_grant"] is True
    assert all(result.get("production_writes", result.get("writes")) == 0 for result in results.values())
    now = datetime.now(timezone.utc)
    entry = datetime.fromisoformat(timing_data["entry_deadline_utc"].replace("Z", "+00:00"))
    assert (entry - now).total_seconds() >= 120
    baseline_digest = sha(canonical(old["semantic_prestop_baseline"]))
    assert baseline_digest == gate["semantic_baseline_projection_sha256"]
    pre = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.preflight.v1",
           "attempt_id": ATTEMPT, "approval_sha256": APPROVAL_SHA, "gate_d_sha256": GATE_SHA,
           "semantic_baseline_projection_sha256": baseline_digest,
           "sealed_utc": now.isoformat().replace("+00:00", "Z"),
           "full_environment_fingerprint_sha256": runtime["full_environment_sha256"],
           "status": "PASS_FRESH_READONLY_PREFLIGHT", "capture_sha256": {
               name: sha((ROOT / f"FRESH_{name}.stdout.bin").read_bytes()) for name in results},
           "production_writes": 0}
    context = dict(old)
    # The inherited archive digest was never read by either remote entrypoint.
    # Keep image identity in the sealed gate; omit this non-authority context key.
    context.pop("candidate_archive_sha256")
    context.update({"attempt_id": ATTEMPT,
                    "control_directory": gate["compose"]["new_public_override_remote_path"].rsplit("/", 1)[0],
                    "current_container_id": TARGET,
                    "current_override": gate["compose"]["existing_files"][2]["path"],
                    "current_override_sha256": gate["compose"]["existing_files"][2]["sha256"],
                    "candidate_override_sha256": gate["compose"]["new_public_override_local_sha256"],
                    "override_b64": base64.b64encode((ROOT / "OWNER_FENCE_OVERRIDE_CANDIDATE.json").read_bytes()).decode(),
                    "rollback_image_config": gate["target"]["image_id"],
                    "candidate_image_config": gate["target"]["image_id"],
                    "protected18_sha256": gate["strict_protected_sha256"],
                    "creation_settings": gate["target"]["settings_after"],
                    "settings_preimage": {name: {"present": True, "value": value}
                                           for name, value in gate["target"]["settings_before"].items()},
                    "current_topology_sha256": results["host"]["topology_sha256"],
                    "sealed_mounts": gate["target"]["mounts_full"],
                    "sealed_command_sha256": gate["target"]["command_sha256"],
                    "sealed_entrypoint_sha256": gate["target"]["entrypoint_sha256"],
                    "representation_contract_sha256": gate["representation_contract_sha256"],
                    "semantic_baseline_projection_sha256": baseline_digest,
                    "gate_d_sha256": GATE_SHA, "approval_sha256": APPROVAL_SHA,
                    "approval_b64": base64.b64encode((PACKAGE / "EXACT_OWNER_REBIND_APPROVAL_DRAFT.txt").read_bytes()).decode(),
                    "current_native_config_sha256": gate["current_native_config_sha256"],
                    "native_probe_b64": base64.b64encode((ROOT / "native_mail_conditions_readonly.py").read_bytes()).decode(),
                    "native_probe_sha256": sha((ROOT / "native_mail_conditions_readonly.py").read_bytes()),
                    "native_lead_probe_b64": base64.b64encode((ROOT / "native_lead_readonly.py").read_bytes()).decode(),
                    "native_lead_probe_sha256": sha((ROOT / "native_lead_readonly.py").read_bytes()),
                    "timing": timing_data, "timing_receipt_sha256": sha(timing_raw),
                    "preflight": pre, "preflight_evidence_sha256": sha(canonical(pre))})
    context["old_authority_denylist"] = list(old["old_authority_denylist"]) + [
        "729fe46f-b7d0-479f-8986-8540b8ed9514",
        "8920f6f746c3faa9f40f4382dcf392ae1d3911bf4af76db953bab1d9229d229d",
        "eb1a452ff736948b822516e1526802538d287fd5e85cc2553f7fee7439bf64c8",
        "6ef2e981e43895af382ab7c7d7c5e172437a3a9dc6a9eeb183a5b892fc17f977",
        "2f0ba7f6-4ec7-47c0-a3f6-6d9c4e4530af",
        "e6f5063bc26aec6114bf1f0a5b8c9dd4b51b891478cf863edbf7ac1aa695b1de",
        "81cfac90d1c8437aa0add644fc79bbe231d0ebf5ceb8dcbef8474e944d0a3a3f",
        "8fe342ddea054db1b7b7e7b529ac7ad74c3900083c1493499ea849bbd43df65c",
    ]
    assert context["candidate_head"] == "538c30bd72fd7ef763bc3e235e50d6c0d8b86bbf"
    assert context["semantic_prestop_baseline"] == old["semantic_prestop_baseline"]
    assert context["attempt_id"] not in context["old_authority_denylist"]
    from package_binding_contract import verify_package_contract
    verify_package_contract(context)
    begin = (ROOT / "owner_rebind_begin.template.py").read_text(encoding="utf-8")
    execute = (ROOT / "owner_rebind_execute.template.py").read_text(encoding="utf-8")
    encoded = base64.b64encode(canonical(context)).decode()
    representation = (ROOT / "owner_fence_representation.py").read_text(encoding="utf-8")
    binding_contract = (ROOT / "package_binding_contract.py").read_text(encoding="utf-8")
    for name, source in (("BEGIN", begin), ("EXECUTE", execute)):
        assert source.count("# __SHARED_REPRESENTATION_SOURCE__") == 1
        assert source.count("# __SHARED_PACKAGE_BINDING_CONTRACT__") == 1
        source = source.replace("# __SHARED_REPRESENTATION_SOURCE__", representation)
        source = source.replace("# __SHARED_PACKAGE_BINDING_CONTRACT__", binding_contract)
        source = source.replace("__EXECUTION_CONTEXT_B64__", encoded)
        source = source.replace("__EXPECTED_APPROVAL_SHA256__", APPROVAL_SHA)
        source = source.replace("__EXPECTED_GATE_D_SHA256__", GATE_SHA)
        source = source.replace("__EXPECTED_REPRESENTATION_SHA256__", gate["representation_contract_sha256"])
        assert "__EXECUTION_CONTEXT_B64__" not in source and "__EXPECTED_APPROVAL_SHA256__" not in source
        compile(source, name, "exec")
        (ROOT / f"{name}_REMOTE.py").write_text(source, encoding="utf-8", newline="\n")
    (ROOT / "FRESH_PREFLIGHT_EVIDENCE.json").write_bytes(canonical(pre))
    (ROOT / "EXECUTION_CONTEXT.json").write_bytes(canonical(context))
    manifest = {"schema": "npd.agent-hub.phase9.owner-fence-rebind.execution-package-manifest.v2",
                "attempt_id": ATTEMPT, "gate_sha256": GATE_SHA,
                "approval_sha256": APPROVAL_SHA,
                "semantic_baseline_projection_sha256": baseline_digest,
                "preflight_evidence_sha256": sha(canonical(pre)),
                "execution_context_sha256": sha(canonical(context)),
                "begin_sha256": sha((ROOT / "BEGIN_REMOTE.py").read_bytes()),
                "execute_sha256": sha((ROOT / "EXECUTE_REMOTE.py").read_bytes())}
    (ROOT / "EXECUTION_PACKAGE_MANIFEST.json").write_bytes(canonical(manifest))
    print(json.dumps({"status": "PASS_FRESH_PREFLIGHT_SEALED",
                      "sealed_utc": pre["sealed_utc"], "entry_reserve_seconds": (entry-now).total_seconds(),
                      "context_sha256": sha(canonical(context)), "preflight_sha256": sha(canonical(pre)),
                      "begin_sha256": sha((ROOT / "BEGIN_REMOTE.py").read_bytes()),
                      "execute_sha256": sha((ROOT / "EXECUTE_REMOTE.py").read_bytes())}, sort_keys=True))

if __name__ == "__main__":
    command = sys.argv[1]
    if command == "static": static()
    elif command == "timing": timing(sys.argv[2])
    elif command == "preflight": preflight()
    else: raise SystemExit(2)
