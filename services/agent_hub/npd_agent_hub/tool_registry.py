from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class CapabilityMode(str, Enum):
    READ = "read"
    DRAFT = "draft"
    WRITE = "write"


class ExecutionState(str, Enum):
    ENABLED = "enabled"
    PLANNING_ONLY = "planning_only"
    DISABLED = "disabled"


class ToolCapability(BaseModel):
    name: str
    mode: CapabilityMode
    requires_approval: bool
    target_system: str
    execution_state: ExecutionState
    dry_run_support: bool = False
    description: str


def _tool(
    name: str,
    mode: CapabilityMode,
    target: str,
    description: str,
    *,
    approval: bool = False,
    state: ExecutionState = ExecutionState.ENABLED,
    dry_run: bool = False,
) -> ToolCapability:
    return ToolCapability(
        name=name,
        mode=mode,
        requires_approval=approval,
        target_system=target,
        execution_state=state,
        dry_run_support=dry_run,
        description=description,
    )


TOOL_REGISTRY: dict[str, ToolCapability] = {
    item.name: item
    for item in [
        _tool("analytics.read", CapabilityMode.READ, "Meta Ads/GA4/Social/EspoCRM", "Read aggregated marketing evidence."),
        _tool("crm.leads.read", CapabilityMode.READ, "EspoCRM", "Read the allowlisted Lead projection."),
        _tool("crm.audit.read", CapabilityMode.READ, "EspoCRM", "Read CRM hygiene and follow-up evidence."),
        _tool("research.search", CapabilityMode.DRAFT, "Research workspace", "Prepare a research brief; no external mutation.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("content.idea_score", CapabilityMode.DRAFT, "Content workspace", "Score ideas in the planning workspace.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("video.brief.create", CapabilityMode.DRAFT, "NPD Video Factory", "Prepare a video brief without rendering or publishing.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("video.jobs.create", CapabilityMode.WRITE, "NPD Video Factory", "Submit a bounded internal render job.", dry_run=True),
        _tool("social.package.create", CapabilityMode.DRAFT, "Social workspace", "Prepare channel-specific social drafts.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("campaign.plan.generate", CapabilityMode.DRAFT, "Campaign OS", "Generate campaign/channel plans and previews.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("ads.plan.create", CapabilityMode.DRAFT, "Meta Ads/Google Ads", "Prepare structure, audience, keyword, budget and tracking plans.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("email.sequence.draft", CapabilityMode.DRAFT, "Email marketing provider", "Prepare an email sequence without sending.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("zalo_zbs.sequence.draft", CapabilityMode.DRAFT, "Zalo OA/ZBS provider", "Prepare consent-aware ZBS/OA drafts without sending.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("landing.preview.create", CapabilityMode.DRAFT, "WordPress/Sales Hub", "Prepare staging metadata and landing-page preview.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("tracking.validate", CapabilityMode.DRAFT, "Campaign OS/downstream contracts", "Validate required tracking fields without writes.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.ledger.read", CapabilityMode.DRAFT, "Attribution OS", "Prepare an immutable Campaign/Lead/Opportunity ledger review in shadow mode.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.identity.read", CapabilityMode.READ, "Campaign OS/Attribution OS", "Read owner-verified external ID to Campaign mappings and data-quality coverage."),
        _tool("attribution.identity.register", CapabilityMode.DRAFT, "Campaign OS/Attribution OS", "Register an owner-verified ID mapping without mutating source systems.", approval=True, state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.touchpoint.ingest", CapabilityMode.DRAFT, "Attribution OS", "Normalize pseudonymous read-only source events through verified identity resolution.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.intake.issue.read", CapabilityMode.READ, "n8n Lead Intake/Attribution OS", "Review privacy-safe unknown and conflicting source identities."),
        _tool("attribution.intake.issue.replay", CapabilityMode.DRAFT, "Attribution OS", "Replay a verified Lead Intake exception into the internal shadow ledger only.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.delivery.status.read", CapabilityMode.READ, "n8n/read-only providers", "Read signed-receipt, retry, dead-letter and freshness SLO metrics."),
        _tool("attribution.delivery.receipt.verify", CapabilityMode.READ, "Attribution OS", "Verify an HMAC delivery receipt without exposing its signing key."),
        _tool("attribution.delivery.ingest", CapabilityMode.DRAFT, "Attribution OS", "Accept a pseudonymous read-only delivery and issue an immutable signed receipt.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.delivery.failure.record", CapabilityMode.DRAFT, "Attribution OS", "Record bounded producer retry/dead-letter evidence without scheduling external execution.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("provider.health.read", CapabilityMode.READ, "Read-only marketing providers/Attribution OS", "Read bounded provider probe, freshness and internal alert state."),
        _tool("provider.health.refresh", CapabilityMode.READ, "Read-only marketing providers/Attribution OS", "Refresh aggregate provider health using read-only probes; no source mutation or external notification."),
        _tool("provider.health.scheduler.read", CapabilityMode.READ, "Agent Hub internal audit", "Read scheduler state for cached internal health evaluation."),
        _tool("provider.health.evaluate", CapabilityMode.DRAFT, "Agent Hub internal audit", "Evaluate cached provider state and heartbeat freshness without provider probes or external notifications.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.heartbeat.ingest", CapabilityMode.DRAFT, "n8n/Attribution OS", "Accept a PII-free producer heartbeat and issue an immutable signed receipt.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.heartbeat.read", CapabilityMode.READ, "Attribution OS", "Read signed producer heartbeat receipts and freshness evidence."),
        _tool("provider.alert.acknowledge", CapabilityMode.DRAFT, "Agent Hub internal audit", "Acknowledge a deduplicated internal alert without contacting external systems.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("provider.alert.routing.preview", CapabilityMode.DRAFT, "Agent Hub internal audit", "Preview severity routing, dedupe, cooldown and escalation without delivering an external notification.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.reconcile.preview", CapabilityMode.DRAFT, "Attribution OS/EspoCRM", "Reconcile read-only Opportunity and revenue snapshots without source-system writes.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("revenue.report.read", CapabilityMode.DRAFT, "Attribution OS", "Prepare an owner-accepted pipeline and closed-revenue shadow report.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("attribution.quality.accept", CapabilityMode.DRAFT, "Attribution OS", "Record an owner quality-gate decision without external effects.", approval=True, state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("experiment.plan.create", CapabilityMode.DRAFT, "Experiment OS", "Create a hypothesis, variants, metrics, guardrails and stop conditions from accepted attribution evidence.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("experiment.preview.generate", CapabilityMode.DRAFT, "Experiment OS", "Generate a deterministic experiment preview without changing traffic, spend or production content.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("experiment.observation.read", CapabilityMode.READ, "GA4/Meta Ads/verified snapshots", "Attach normalized variant observations collected through read-only source access; raw PII is forbidden."),
        _tool("experiment.recommendation.evaluate", CapabilityMode.DRAFT, "Experiment OS", "Evaluate freshness, sample sufficiency, significance and guardrails to produce an advisory recommendation.", state=ExecutionState.PLANNING_ONLY, dry_run=True),
        _tool("experiment.execution.start", CapabilityMode.WRITE, "Ads/CMS/CRM providers", "Start live experiment allocation or mutate production delivery.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("ads.budget.update", CapabilityMode.WRITE, "Meta Ads", "Mutate a live advertising budget.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("ads.launch", CapabilityMode.WRITE, "Meta Ads/Google Ads", "Launch a live campaign.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("social.publish", CapabilityMode.WRITE, "Social channels", "Publish branded content.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("email.bulk_send", CapabilityMode.WRITE, "Email marketing provider", "Send a bulk marketing sequence.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("zalo_zbs.bulk_send", CapabilityMode.WRITE, "Zalo OA/ZBS provider", "Send a bulk ZBS/OA campaign.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("landing.production_publish", CapabilityMode.WRITE, "WordPress/Sales Hub", "Publish a landing page to production.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("crm.records.update", CapabilityMode.WRITE, "EspoCRM", "Update bounded CRM records.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("crm.mass_write", CapabilityMode.WRITE, "EspoCRM", "Perform a CRM mass write.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
        _tool("sales.contact.send", CapabilityMode.WRITE, "Customer contact channels", "Contact a customer.", approval=True, state=ExecutionState.DISABLED, dry_run=True),
    ]
}


AUTO_READ_TOOLS = {
    name for name, capability in TOOL_REGISTRY.items() if capability.mode == CapabilityMode.READ
}

N8N_WRITE_TOOLS = {
    "ads.budget.update",
    "social.publish",
    "sales.contact.send",
    "crm.records.update",
}


def list_tool_capabilities() -> list[ToolCapability]:
    return [TOOL_REGISTRY[name] for name in sorted(TOOL_REGISTRY)]
