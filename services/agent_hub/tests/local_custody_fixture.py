"""Explicit synthetic-only test policy/archive; never Owner/production authority."""
from npd_agent_hub.retention_custody import CustodyCoordinator,CustodyPolicy,LocalFixtureArchive

def fixture_retention():
    policy=CustodyPolicy('SYNTHETIC_LOCAL_TEST_POLICY_NOT_OWNER_DISPOSITION',
        category_mapping_owner_adopted=True,named_owner='synthetic-requester',
        named_verifier='synthetic-verifier',named_custodian='synthetic-custodian')
    def classify(row):
        if 'provider-health' in row.source or row.source=='provider_health_snapshots':
            return 'routine_provider_health_nonincident_nonpilot'
        if 'delivery' in row.source or 'heartbeat' in row.source:
            return 'ordinary_nonpilot_signed_delivery_and_deadletter'
        return 'ordinary_nonpilot_audit_and_linked_snapshot'
    # Explicit fixture oracle: these sanitized rows have no linked production
    # evidence. A production resolver cannot assume the same empty relation.
    return CustodyCoordinator(policy=policy,archive=LocalFixtureArchive(),classify=classify,
        resolve_links=lambda row,session: row.links,local_only=True)
