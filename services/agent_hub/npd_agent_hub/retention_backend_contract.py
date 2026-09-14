"""Static S3 requirements and readback validation. No client or activation API.

Object Lock protects versions, not a key name. Conditional creation and a pinned
VersionId are therefore required in addition to retention. All supplied proof
in this source task is synthetic; actual backend acceptance remains NOT_RUN.
"""
from dataclasses import dataclass
from datetime import timedelta
from .retention_custody import CustodyBlocked, PROPOSED_PERIODS, PROTECTED, aware, digest


@dataclass(frozen=True)
class S3Requirements:
    account_id: str | None = None
    region: str | None = None
    bucket: str | None = None
    prefix: str | None = None
    encryption_key_identity: str | None = None
    versioning: bool = False
    object_lock: bool = False
    retention_mode: str | None = None
    deny_unconditional_put: bool = False
    deny_delete_markers: bool = False
    independent_reader: bool = False
    lifecycle_deletion_disabled: bool = False
    governance_bypass_denied: bool = False

    def validate(self):
        values=(self.account_id,self.region,self.bucket,self.prefix,self.encryption_key_identity)
        if not all(isinstance(v,str) and v.strip() and v!='UNBOUND' for v in values):
            raise CustodyBlocked('BACKEND_CONFIGURATION_UNBOUND')
        if not (self.versioning and self.object_lock and self.deny_unconditional_put
                and self.deny_delete_markers and self.independent_reader
                and self.lifecycle_deletion_disabled and self.governance_bypass_denied):
            raise CustodyBlocked('BACKEND_SAFETY_REQUIREMENTS_MISSING')
        if self.retention_mode not in ('GOVERNANCE','COMPLIANCE'):
            raise CustodyBlocked('RETENTION_MODE_REVIEW_REQUIRED')


def static_put_plan(record,category,policy,requirements,verified_utc):
    """A plan only; it is not an authenticated request or execution authority."""
    policy.validate_authorities();requirements.validate()
    if category in PROTECTED or category not in dict(policy.category_periods):
        raise CustodyBlocked('PROTECTED_OR_UNKNOWN_MUST_NOT_EVICT')
    minimum=aware(verified_utc)+timedelta(days=dict(policy.category_periods)[category])
    return {'source_integration_only':True,'execution_authorized':False,
        'backend_acceptance':'NOT_RUN','category_mapping_status':'PROPOSAL_REQUIRES_OWNER_REVIEW',
        'operation':'PutObject','IfNoneMatch':'*','Bucket':requirements.bucket,
        'Key':requirements.prefix.rstrip('/')+'/'+record.identity+'/raw.bin',
        'ObjectLockMode':requirements.retention_mode,'ObjectLockRetainUntilDate':minimum.isoformat(),
        'raw_sha256':digest(record.raw),'linked_raw_sha256':[(k,digest(v)) for k,v in record.links],
        'required_readback':['exact_raw_bytes','exact_linked_bytes','VersionId','retention','policy_identity'],
        'automatic_deletion':False,'hold_release_authority':'UNBOUND_NO_RELEASE_IMPLEMENTED'}


def verify_static_readback(record,plan,proof):
    if not proof.get('synthetic_local_only'):
        raise CustodyBlocked('ACTUAL_BACKEND_ACCEPTANCE_NOT_IMPLEMENTED')
    if (proof.get('raw_bytes')!=record.raw or proof.get('linked_bytes')!=record.links
            or proof.get('raw_sha256')!=digest(record.raw) or not proof.get('VersionId')
            or proof.get('VersionId')=='null' or not proof.get('independent_reader')
            or proof.get('Key')!=plan['Key'] or proof.get('retention_mode')!=plan['ObjectLockMode']
            or aware(proof['retain_until_utc'])<aware(plan['ObjectLockRetainUntilDate'])):
        raise CustodyBlocked('STATIC_READBACK_PROOF_INVALID')
    return {'status':'PASS_SYNTHETIC_ONLY','actual_backend_acceptance':'NOT_RUN','execution_authorized':False}


def release_hold(*args,**kwargs):
    # Period expiry is not a hold release, deletion or trim authority.
    raise CustodyBlocked('HOLD_RELEASE_NOT_AUTHORIZED_OR_IMPLEMENTED')
