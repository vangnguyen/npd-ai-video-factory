import asyncio

from npd_agent_hub.evals import DEFAULT_CASES, evaluate_all, load_cases


def test_phase_5_1_business_eval_catalog_has_twenty_cases():
    cases = load_cases(DEFAULT_CASES)

    assert len(cases) == 20
    assert len({case["id"] for case in cases}) == 20


def test_phase_5_1_business_eval_gate_passes_at_one_hundred_percent():
    report = asyncio.run(evaluate_all(DEFAULT_CASES))

    assert report["total"] == 20
    assert report["passed"] == 20
    assert report["pass_rate"] == 1.0
