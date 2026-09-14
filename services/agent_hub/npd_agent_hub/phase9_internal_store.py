"""No-trim commits for the existing Campaign audit list, without Redis retries."""
from __future__ import annotations

import json

from redis.exceptions import WatchError

from .campaign_models import Campaign
from .attribution_models import CampaignIdentityMapping
from .phase9_internal_audit import (
    INTERNAL_AUDIT_BUDGET, INTERNAL_AUDIT_CAP, Phase9AuditDenied, content_sha256,
)


def deny(reason):
    raise Phase9AuditDenied(f"PHASE9_INTERNAL_AUDIT:{reason}")


def create_internal_campaign(store, campaign, audit):
    campaign = Campaign.model_validate(campaign.model_dump())
    if (campaign.internal_cohort is None or audit.campaign_id != campaign.campaign_id
            or audit.event_type != "campaign_created" or audit.to_status != campaign.status):
        deny("CAMPAIGN_BINDING_INVALID")
    required = 1 + INTERNAL_AUDIT_BUDGET  # Creation audit plus room for mandatory ingest audits.
    cid = campaign.campaign_id
    lead = campaign.internal_cohort.subject_ref.removeprefix("lead:")
    if hasattr(store, "_phase9_lock"):
        with store._phase9_lock:
            bucket = store.campaign_audit.get(cid, [])
            if cid in store.campaigns or any(e.lead_id == lead for e in store.touchpoints.values()):
                deny("REPLAY_OR_SUBJECT_NOT_EMPTY")
            if len(bucket) + required > INTERNAL_AUDIT_CAP:
                deny("CAPACITY_INSUFFICIENT")
            model = campaign.model_copy(deep=True)
            record = audit.model_copy(deep=True)
            store.campaigns[cid] = model
            store.campaign_updated_at[cid] = model.updated_at
            store.campaign_audit[cid] = [*bucket, record]
        return
    campaign_key = store._key("campaign-os", "campaign", cid)
    audit_key = store._key("campaign-os", "audit", cid)
    index = store._key("campaign-os", "campaigns")
    lead_index = store._key("attribution-os", "lead", lead, "touchpoints")
    with store.redis.pipeline() as pipe:
        try:
            pipe.watch(campaign_key, audit_key, index, lead_index)
            for target, expected in ((campaign_key,"string"),(audit_key,"list"),
                                     (index,"zset"),(lead_index,"zset")):
                if pipe.type(target) not in ("none",expected):
                    deny("STORE_TYPE_INVALID")
            if pipe.exists(campaign_key) or pipe.zcard(lead_index):
                deny("REPLAY_OR_SUBJECT_NOT_EMPTY")
            if pipe.llen(audit_key) + required > INTERNAL_AUDIT_CAP:
                deny("CAPACITY_INSUFFICIENT")
            pipe.multi()
            pipe.set(campaign_key, campaign.model_dump_json(), nx=True)
            pipe.zadd(index, {cid:campaign.updated_at.timestamp()})
            pipe.rpush(audit_key, audit.model_dump_json())
            pipe.execute()
        except WatchError as exc:
            raise Phase9AuditDenied("PHASE9_INTERNAL_AUDIT:CONCURRENT_CHANGE") from exc


def memory_commit(store, bundle):
    bundle.validate()
    with store._phase9_lock:
        cid = bundle.campaign.campaign_id
        current = store.campaigns.get(cid)
        bucket = store.campaign_audit.get(cid, [])
        if current is None or current != bundle.campaign:
            deny("CAMPAIGN_CHANGED")
        if sorted(content_sha256(m) for m in store.identity_mappings.values()) != sorted(
            content_sha256(m) for m in bundle.identity_mappings
        ):
            deny("IDENTITY_MAPPING_CHANGED")
        if len(bucket) + INTERNAL_AUDIT_BUDGET > INTERNAL_AUDIT_CAP:
            deny("CAPACITY_INSUFFICIENT")
        if (bundle.touchpoint.event_id in store.touchpoints
                or bundle.snapshot.snapshot_id in store.attribution_quality_snapshots
                or bundle.receipt.receipt_id in store.attribution_delivery_receipts
                or any(event.lead_id == bundle.touchpoint.lead_id for event in store.touchpoints.values())
                or any(a.event_id in {b.event_id for b in bucket} for a in bundle.audits)):
            deny("REPLAY_OR_SUBJECT_NOT_EMPTY")
        # All validation precedes the first mutation, under the same writer lock.
        touchpoint = bundle.touchpoint.model_copy(deep=True)
        snapshot = bundle.snapshot.model_copy(deep=True)
        receipt = bundle.receipt.model_copy(deep=True)
        audits = [audit.model_copy(deep=True) for audit in bundle.audits]
        store.touchpoints[touchpoint.event_id] = touchpoint
        store.attribution_quality_snapshots[snapshot.snapshot_id] = snapshot
        store.attribution_delivery_receipts[receipt.receipt_id] = receipt
        store.campaign_audit[cid] = [*bucket, *audits]


def redis_commit(store, bundle):
    bundle.validate()
    event, snapshot, receipt = bundle.touchpoint, bundle.snapshot, bundle.receipt
    key = store._key
    campaign_key = key("campaign-os", "campaign", bundle.campaign.campaign_id)
    audit_key = key("campaign-os", "audit", bundle.campaign.campaign_id)
    event_key = key("attribution-os", "touchpoint", event.event_id)
    snapshot_key = key("attribution-os", "data-quality", snapshot.snapshot_id)
    receipt_key = key("attribution-os", "delivery-receipt", receipt.receipt_id)
    lead_index = key("attribution-os", "lead", event.lead_id, "touchpoints")
    indexes = (
        key("attribution-os", "touchpoints"),
        key("attribution-os", "campaign", event.campaign_id, "touchpoints"),
        lead_index, key("attribution-os", "data-quality-snapshots"),
        key("attribution-os", "delivery-receipts"),
    )
    expected_types = {campaign_key: "string", audit_key: "list", event_key: "string",
                      snapshot_key: "string", receipt_key: "string",
                      **{index: "zset" for index in indexes}}
    mapping_index = key("attribution-os", "identity-mappings")
    mapping_keys = {key("attribution-os", "identity-mapping", m.mapping_id): m
                    for m in bundle.identity_mappings}
    expected_types.update({mapping_index: "zset", **{k: "string" for k in mapping_keys}})
    with store.redis.pipeline() as pipe:
        try:
            pipe.watch(*expected_types)
            # Prevent EXEC runtime type errors (Redis transactions do not undo
            # commands after such errors). WATCH also fences subsequent changes.
            for target, expected in expected_types.items():
                actual = pipe.type(target)
                if actual not in ("none", expected):
                    deny("STORE_TYPE_INVALID")
            if set(pipe.zrange(mapping_index, 0, -1)) != {m.mapping_id for m in bundle.identity_mappings}:
                deny("IDENTITY_MAPPING_CHANGED")
            for target, mapping in mapping_keys.items():
                raw = pipe.get(target)
                if raw is None or CampaignIdentityMapping.model_validate_json(raw) != mapping:
                    deny("IDENTITY_MAPPING_CHANGED")
            raw = pipe.get(campaign_key)
            if raw is None or content_sha256(Campaign.model_validate_json(raw)) != content_sha256(bundle.campaign):
                deny("CAMPAIGN_CHANGED")
            count = pipe.llen(audit_key)
            if count + INTERNAL_AUDIT_BUDGET > INTERNAL_AUDIT_CAP:
                deny("CAPACITY_INSUFFICIENT")
            if (any(pipe.exists(target) for target in (event_key, snapshot_key, receipt_key))
                    or pipe.zcard(lead_index)):
                deny("REPLAY_OR_SUBJECT_NOT_EMPTY")
            # Existing audit IDs are create-only too; no list item is overwritten.
            ids = {json.loads(raw)["event_id"] for raw in pipe.lrange(audit_key, 0, -1)}
            if any(a.event_id in ids for a in bundle.audits):
                deny("AUDIT_REPLAY")
            pipe.multi()
            pipe.set(event_key, event.model_dump_json(), nx=True)
            for index in indexes[:3]:
                pipe.zadd(index, {event.event_id: event.occurred_at.timestamp()})
            pipe.set(snapshot_key, snapshot.model_dump_json(), nx=True)
            pipe.zadd(indexes[3], {snapshot.snapshot_id: snapshot.created_at.timestamp()})
            pipe.set(receipt_key, receipt.model_dump_json(), nx=True)
            pipe.zadd(indexes[4], {receipt.receipt_id: receipt.received_at.timestamp()})
            pipe.rpush(audit_key, *(audit.model_dump_json() for audit in bundle.audits))
            pipe.execute()  # Exactly one attempt. No LTRIM/DEL and no automatic retry.
        except WatchError as exc:
            raise Phase9AuditDenied("PHASE9_INTERNAL_AUDIT:CONCURRENT_CHANGE") from exc


def redis_append_campaign_audit(store, event, campaign):
    """Other existing Campaign audit helpers may not trim internal custody either."""
    audit_key = store._key("campaign-os", "audit", event.campaign_id)
    campaign_key = store._key("campaign-os", "campaign", event.campaign_id)
    with store.redis.pipeline() as pipe:
        try:
            pipe.watch(audit_key, campaign_key)
            if pipe.type(audit_key) not in ("none", "list"):
                deny("STORE_TYPE_INVALID")
            raw = pipe.get(campaign_key)
            if raw is None or content_sha256(Campaign.model_validate_json(raw)) != content_sha256(campaign):
                deny("CAMPAIGN_CHANGED")
            if pipe.llen(audit_key) + 1 > INTERNAL_AUDIT_CAP:
                deny("CAPACITY_INSUFFICIENT")
            if any(json.loads(row)["event_id"] == event.event_id
                   for row in pipe.lrange(audit_key, 0, -1)):
                deny("AUDIT_REPLAY")
            pipe.multi()
            pipe.rpush(audit_key, event.model_dump_json())
            pipe.execute()
        except WatchError as exc:
            raise Phase9AuditDenied("PHASE9_INTERNAL_AUDIT:CONCURRENT_CHANGE") from exc
