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
