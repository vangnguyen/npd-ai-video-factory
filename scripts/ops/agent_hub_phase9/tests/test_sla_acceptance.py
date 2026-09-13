"""Pure local SLA acceptance, schema consistency and fail-closed coverage tests."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pilot_uat
from sla_contract_loader import contract


def window(*, missing_clock=False):
    return {
        'sales_sla_semantics_version': contract.SLA_SEMANTICS_VERSION,
        'sla_evaluation_as_of': '2026-09-01T08:30:00Z',
        'first_response_sla': 'not_evaluable' if missing_clock else 'overdue_missing_evidence',
        'first_response_sla_clock_start_at': None if missing_clock else '2026-09-01T08:00:00Z',
        'first_response_sla_clock_basis': None if missing_clock else 'lead_created',
        'first_response_sla_policy_source': contract.SLA_POLICY_SOURCE,
        'first_response_sla_policy_available': True,
        'first_response_sla_target_minutes': 15,
        'first_response_sla_deadline_at': None if missing_clock else '2026-09-01T08:15:00Z',
        'first_response_sla_observed_at': None,
        'first_response_sla_evidence_count': 0,
        'first_response_sla_completeness_covered': False,
        'first_response_sla_completeness_receipt_id': None,
        'first_response_sla_reason': 'SLA_CLOCK_UNAVAILABLE' if missing_clock else 'OVERDUE_MISSING_EVIDENCE_NOT_CONFIRMED_BREACH',
        'completeness_verified': False,
    }


def report(fields):
    return {'detail': {'report': {'metrics': {'as_of': fields['sla_evaluation_as_of']}, 'item': {
        'entity_id_sha256': 'a'*64, 'priority': 'high', 'reason_present': True, 'recommended_action_present': True,
        'details': {**fields, 'evaluation_status': 'evaluated', 'journey_state': 'negotiation',
                    'recommendation_version': 'phase-9b-nba-v2', 'completeness_proof_status': 'not_supplied',
                    'missing_inputs': 'sales_sla_completeness', 'shadow_mode': True,
                    'execution_enabled': False, 'customer_contact_enabled': False}}}}}


class SLAAcceptanceTests(unittest.TestCase):
    def setUp(self):
        # A literal local fixture, not a generated execution operation/gate/approval.
        pilot_uat.configure({'operation_id':'SYNTHETIC_NO_EXECUTION', 'subject_ref_sha256':'a'*64,
                            'role_email_sha256':{}, 'candidate_runtime_ids':[]},
                           {'window':{'decision_deadline_utc':'2026-09-01T09:00:00Z'}})

    def assess(self, fields):
        return contract.validate_first_response_sla(fields, report_as_of='2026-09-01T08:30:00Z')

    def test_missing_clock_is_truthful_but_never_overdue_acceptance(self):
        result = self.assess(window(missing_clock=True))
        self.assertTrue(result['truthful'])
        self.assertEqual(result['classification'], 'SLA_CLOCK_UNAVAILABLE')
        self.assertFalse(result['overdue_missing_evidence_covered'])

    def test_overdue_requires_available_clock_policy_deadline_and_missing_evidence(self):
        result = self.assess(window())
        self.assertTrue(result['truthful'])
        self.assertTrue(result['overdue_missing_evidence_covered'])
        self.assertFalse(result['execution_authorized'])

    def test_acceptance_keeps_independent_overdue_business_requirement(self):
        fields = window(missing_clock=True)
        result = pilot_uat.evaluate({}, {}, {}, {'observed_first_response_sla':'not_evaluable'}, report(fields))
        self.assertTrue(result['checks']['phase9_item_truthful'])
        self.assertFalse(result['checks']['sla_acceptance_overdue_missing_evidence'])
        self.assertEqual(result['status'], 'FAIL')
        self.assertIn('sla_acceptance_overdue_missing_evidence', result['failures'])

    def test_valid_overdue_report_is_accepted_only_for_the_sla_check(self):
        result = pilot_uat.evaluate({}, {}, {}, {'observed_first_response_sla':'overdue_missing_evidence'}, report(window()))
        self.assertTrue(result['checks']['phase9_item_truthful'])
        self.assertTrue(result['checks']['sla_acceptance_overdue_missing_evidence'])
        self.assertEqual(result['status'], 'FAIL')  # All ownership/browser/safety checks still required.

    def test_missing_sla_basis_old_receipt_cannot_be_upgraded_to_a_pass(self):
        fields = {'first_response_sla':'overdue_missing_evidence'}
        result = contract.validate_first_response_sla(fields, report_as_of='2026-09-01T08:30:00Z')
        self.assertFalse(result['truthful'])
        self.assertIn('missing_sla_basis', result['failures'])

    def test_status_only_remap_or_missing_deadline_is_rejected(self):
        for fields in [window(missing_clock=True), window()]:
            fields['first_response_sla'] = 'overdue_missing_evidence'
            fields['first_response_sla_deadline_at'] = None
            self.assertFalse(self.assess(fields)['truthful'])

    def test_browser_label_and_api_status_must_agree_for_each_enum(self):
        for status, label in contract.BROWSER_SLA_LABELS.items():
            browser={'observed_first_response_sla':status,'sales_sla':label,
                     'overdue_missing_evidence_not_breached':True,'lead_score_not_purchase_probability':True}
            checked=pilot_uat.validate_browser_evidence(browser, invocation_id='', task_id='', review_id='', deployment={})
            self.assertTrue(checked['truthfulness'])
        browser['sales_sla']='wrong-label'
        self.assertFalse(pilot_uat.validate_browser_evidence(browser, invocation_id='', task_id='', review_id='', deployment={})['truthfulness'])

    def test_browser_api_sla_mismatch_is_rejected(self):
        result=pilot_uat.evaluate({}, {}, {}, {'observed_first_response_sla':'not_evaluable'}, report(window()))
        self.assertFalse(result['checks']['browser_api_sla_consistency'])

    def test_each_required_report_field_is_fail_closed_if_missing(self):
        for name in contract.SLA_REPORT_FIELDS:
            with self.subTest(field=name):
                fields=window();fields.pop(name)
                self.assertFalse(self.assess(fields)['truthful'])

    def test_no_policy_clock_or_proof_can_be_invented_from_task_deadline(self):
        for name, value in [('first_response_sla_clock_basis','task_created'),
                            ('first_response_sla_policy_source','internal_review_minutes'),
                            ('first_response_sla_completeness_covered',True),
                            ('first_response_sla_evidence_count',1),
                            ('first_response_sla_deadline_at','2026-09-01T08:16:00Z')]:
            fields=window();fields[name]=value
            self.assertFalse(self.assess(fields)['truthful'])

    def test_serializer_does_not_erase_required_sla_basis(self):
        template=Path(__file__).resolve().parents[1]/'runtime_template.py'
        import ast
        source=ast.parse(template.read_text(encoding='utf-8'))
        function=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='uat_detail')
        assignment=next(n for n in function.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='allowed_details' for t in n.targets))
        allowed=ast.literal_eval(assignment.value)
        self.assertTrue(set(contract.SLA_REPORT_FIELDS)<=set(allowed))


if __name__ == '__main__':
    unittest.main()
