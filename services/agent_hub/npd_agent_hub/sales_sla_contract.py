"""Shared, dependency-free SLA enum and report/acceptance semantics.

This contract verifies evidence-dependent status truthfulness. A truthful
not_evaluable result never satisfies the overdue-missing-evidence acceptance case.
It grants no operation, approval, execution, or source-completeness authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum


SLA_SEMANTICS_VERSION = "phase-9b-sales-sla-semantics-v1"
SLA_POLICY_SOURCE = "campaign_os_sales_handoff"
SLA_CLOCK_BASES = frozenset({"lead_created", "form_submit_fallback"})


class SalesSLAStatus(str, Enum):
    MET = "met"
    LATE = "late"
    BREACHED = "breached"
    PENDING = "pending"
    OVERDUE_MISSING_EVIDENCE = "overdue_missing_evidence"
    NOT_EVALUABLE = "not_evaluable"


BROWSER_SLA_LABELS = {
    SalesSLAStatus.MET.value: "MET",
    SalesSLAStatus.LATE.value: "LATE",
    SalesSLAStatus.BREACHED.value: "BREACHED_VERIFIED",
    SalesSLAStatus.PENDING.value: "PENDING",
    SalesSLAStatus.OVERDUE_MISSING_EVIDENCE.value: "OVERDUE_MISSING_EVIDENCE_NOT_BREACHED",
    SalesSLAStatus.NOT_EVALUABLE.value: "NOT_AVAILABLE_NOT_EVALUABLE",
}

SLA_REPORT_FIELDS = (
    "sales_sla_semantics_version", "sla_evaluation_as_of",
    "first_response_sla", "first_response_sla_clock_start_at",
    "first_response_sla_clock_basis", "first_response_sla_policy_source",
    "first_response_sla_policy_available", "first_response_sla_target_minutes",
    "first_response_sla_deadline_at", "first_response_sla_observed_at",
    "first_response_sla_evidence_count", "first_response_sla_completeness_covered",
    "first_response_sla_completeness_receipt_id", "first_response_sla_reason",
)


def _reason(status: str, *, clock_missing: bool, policy_missing: bool) -> str:
    if status == SalesSLAStatus.NOT_EVALUABLE.value:
        if clock_missing and policy_missing:
            return "SLA_CLOCK_AND_POLICY_UNAVAILABLE"
        return "SLA_CLOCK_UNAVAILABLE" if clock_missing else "SLA_POLICY_UNAVAILABLE"
    return {
        "met": "QUALIFYING_ACTIVITY_WITHIN_DEADLINE",
        "late": "QUALIFYING_ACTIVITY_AFTER_DEADLINE",
        "pending": "SLA_DEADLINE_NOT_PASSED",
        "breached": "MISSING_ACTIVITY_WITH_VERIFIED_DEADLINE_COMPLETENESS",
        "overdue_missing_evidence": "OVERDUE_MISSING_EVIDENCE_NOT_CONFIRMED_BREACH",
    }[status]


def report_sla_fields(snapshot) -> dict[str, str | int | bool | None]:
    """Project the evaluated window, preserving unavailable inputs as null."""
    window = snapshot.first_response_sla
    iso = lambda value: value.isoformat() if value is not None else None
    status = window.status.value
    return dict(zip(SLA_REPORT_FIELDS, (
        SLA_SEMANTICS_VERSION, iso(snapshot.as_of), status,
        iso(window.clock_start_at), snapshot.lead_start_basis, snapshot.policy_source,
        window.target_minutes is not None, window.target_minutes,
        iso(window.deadline_at), iso(window.observed_at), len(window.evidence_refs),
        window.completeness_receipt_id is not None,
        window.completeness_receipt_id,
        _reason(status, clock_missing=window.clock_start_at is None,
                policy_missing=window.target_minutes is None),
    )))


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def validate_first_response_sla(fields: dict, *, report_as_of: object) -> dict:
    """Recompute the status from explicit window inputs; never accept a remap."""
    failures = []
    def check(condition: bool, name: str) -> None:
        if condition is not True:
            failures.append(name)

    check(set(SLA_REPORT_FIELDS) <= fields.keys(), "missing_sla_basis")
    check(fields.get("sales_sla_semantics_version") == SLA_SEMANTICS_VERSION, "wrong_sla_contract")
    status = fields.get("first_response_sla")
    check(isinstance(status, str) and status in BROWSER_SLA_LABELS, "unknown_sla_status")
    as_of = _time(fields.get("sla_evaluation_as_of"))
    check(as_of is not None and as_of == _time(report_as_of), "invalid_or_mismatched_as_of")
    clock = fields.get("first_response_sla_clock_start_at")
    start = _time(clock)
    check(clock is None or start is not None, "malformed_sla_clock")
    basis = fields.get("first_response_sla_clock_basis")
    check((clock is None and basis is None) or (start is not None and isinstance(basis, str) and basis in SLA_CLOCK_BASES), "invalid_sla_clock_basis")
    target = fields.get("first_response_sla_target_minutes")
    check(target is None or (type(target) is int and target >= 1), "invalid_sla_target")
    policy = fields.get("first_response_sla_policy_available")
    check(type(policy) is bool and policy == (target is not None), "invalid_sla_policy_availability")
    check(fields.get("first_response_sla_policy_source") == SLA_POLICY_SOURCE, "wrong_sla_policy_source")
    deadline_value = fields.get("first_response_sla_deadline_at")
    deadline = _time(deadline_value)
    check(deadline_value is None or deadline is not None, "malformed_sla_deadline")
    observed_value = fields.get("first_response_sla_observed_at")
    observed = _time(observed_value)
    check(observed_value is None or observed is not None, "malformed_sla_observation")
    count = fields.get("first_response_sla_evidence_count")
    check(type(count) is int and count >= 0, "invalid_sla_evidence_count")
    covered = fields.get("first_response_sla_completeness_covered")
    check(type(covered) is bool, "invalid_sla_completeness_coverage")
    receipt = fields.get("first_response_sla_completeness_receipt_id")
    check((covered is False and receipt is None) or
          (covered is True and isinstance(receipt, str) and bool(receipt)
           and fields.get("completeness_verified") is True), "invalid_sla_completeness_binding")
    expected = None
    if not failures:
        if start is None or target is None:
            check(deadline is None and observed is None and covered is False, "unavailable_sla_inferred_result")
            expected = SalesSLAStatus.NOT_EVALUABLE.value
        else:
            try:
                expected_deadline = start + timedelta(minutes=target)
            except OverflowError:
                check(False, "sla_deadline_overflow")
                expected_deadline = None
            check(deadline is not None and deadline == expected_deadline, "missing_or_wrong_sla_deadline")
            if observed is not None:
                check(observed >= start and count > 0 and covered is False, "invalid_qualifying_activity")
                if expected_deadline is not None:
                    expected = SalesSLAStatus.MET.value if observed <= expected_deadline else SalesSLAStatus.LATE.value
            else:
                check(count == 0, "missing_observation_for_supplied_evidence")
                if deadline is not None:
                    expected = (SalesSLAStatus.PENDING.value if as_of <= deadline else
                                SalesSLAStatus.BREACHED.value if covered else
                                SalesSLAStatus.OVERDUE_MISSING_EVIDENCE.value)
                    check(not covered or as_of > deadline, "premature_verified_breach")
        check(status == expected, "sla_status_does_not_match_inputs")
        if expected is not None:
            check(fields.get("first_response_sla_reason") == _reason(expected, clock_missing=start is None, policy_missing=target is None), "wrong_sla_reason")
    truthful = not failures
    return {
        "contract_version": SLA_SEMANTICS_VERSION,
        "reported_status": status, "expected_status": expected,
        "truthful": truthful, "failures": failures,
        "classification": fields.get("first_response_sla_reason") if truthful else "SLA_SEMANTICS_INVALID",
        "overdue_missing_evidence_covered": truthful and status == SalesSLAStatus.OVERDUE_MISSING_EVIDENCE.value,
        "required_acceptance_status": SalesSLAStatus.OVERDUE_MISSING_EVIDENCE.value,
        "execution_authorized": False,
    }
