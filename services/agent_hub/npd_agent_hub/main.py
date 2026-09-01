from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from .auth import (
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    Principal,
    Role,
    authorizer,
    require_operator,
    require_owner,
    require_viewer,
)
from .attribution_models import (
    AttributionAcceptanceRequest,
    AttributionAuditEvent,
    AttributionDataQualitySnapshot,
    AttributionIdentityStatus,
    AttributionIntakeIssue,
    AttributionIntakePreview,
    AttributionModel,
    AttributionReconciliation,
    AttributionReport,
    AttributionStatus,
    CampaignIdentityMapping,
    CampaignIdentityMappingCreate,
    IdentitySource,
    OpportunitySourceSnapshot,
    ReconciliationRequest,
    SourceTouchpointIngestRequest,
    TouchpointBackfillRequest,
    TouchpointEvent,
)
from .espocrm_opportunities import EspoOpportunityError, EspoOpportunityNotConfigured
from .delivery_models import (
    AttributionDeadLetter,
    AttributionDeliveryEnvelope,
    AttributionDeliveryFailure,
    AttributionDeliveryReceipt,
    AttributionDeliveryStatus,
    AttributionHeartbeatReceipt,
    AttributionHeartbeatReceiptVerificationRequest,
    AttributionProducerHeartbeat,
    AttributionReceiptVerification,
    AttributionReceiptVerificationRequest,
    DeliveryOutcome,
)
from .delivery_observability import DeliveryIntegrityConflict, DeliveryNotConfigured
from .experiment_models import (
    Experiment,
    ExperimentApprovalDecision,
    ExperimentApprovalRequest,
    ExperimentAuditEvent,
    ExperimentCreate,
    ExperimentDraftUpdate,
    ExperimentEvaluation,
    ExperimentEvaluationRequest,
    ExperimentMetaTrackingMappingUpdate,
    ExperimentObservation,
    ExperimentObservationCreate,
    ExperimentObservationQualityDecision,
    ExperimentOSStatus,
    ExperimentPreview,
    ExperimentStatus,
    ExperimentSourceReadRequest,
    ExperimentSourceReadResult,
    ExperimentTrackingValidation,
    ObservationSource,
)
from .campaign_models import (
    Campaign,
    CampaignApprovalDecision,
    CampaignApprovalRequest,
    CampaignAuditEvent,
    CampaignBriefRequest,
    CampaignCreate,
    CampaignDraftUpdate,
    CampaignStatus,
    CampaignSummary,
    CampaignTransitionRequest,
)
from .campaign_providers import ProviderContract, campaign_provider_contracts
from .dashboard import command_center_html
from .espocrm_mapping import EspoMappingReader, EspoMappingRecommendation
from .espocrm_schema import (
    EspoEntitySchema,
    EspoSchemaError,
    EspoSchemaNotConfigured,
    EspoSchemaReader,
)
from .models import (
    AgentDescriptor,
    AgentTask,
    ApprovalDecision,
    AuditEvent,
    CommandCenterReport,
    CommandCenterSnapshot,
    PlannedAction,
    ToolExecutionResult,
)
from .google_login import (
    begin_google_login,
    complete_google_login,
    login_page,
    logout_response,
)
from .orchestrator import hub
from .routers.journeys import router as journeys_router
from .routers.provider_health import router as provider_health_router
from .tool_registry import ToolCapability, list_tool_capabilities
from .video_factory.router import (
    disabled_boundary as disabled_video_factory_boundary,
    router as video_factory_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await hub.provider_health_scheduler.start()
    try:
        yield
    finally:
        await hub.provider_health_scheduler.stop()


app = FastAPI(
    title="NPD Agent Hub",
    version="0.13.0",
    description="Multi-agent control plane with PII-free producer heartbeat and scheduled internal health evaluation.",
    lifespan=lifespan,
)
app.include_router(provider_health_router)
app.include_router(journeys_router)
app.include_router(video_factory_router)
app.state.video_factory_boundary = disabled_video_factory_boundary
schema_reader = EspoSchemaReader()
mapping_reader = EspoMappingReader(schema_reader)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/") or request.url.path == "/agent-hub/events/v1":
        response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    try:
        if not hub.storage_health():
            raise RuntimeError("storage ping failed")
        auth_errors = authorizer.configuration_errors()
        if auth_errors:
            raise RuntimeError("; ".join(auth_errors))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="agent hub dependency/configuration unavailable") from exc
    return {
        "status": "ready",
        "storage": hub.store.backend_name,
        "auth": authorizer.settings.auth_mode,
    }


@app.get("/login")
def login(request: Request, error: str = Query(default="")):
    if authorizer.browser_login_enabled:
        session_cookie = request.cookies.get(SESSION_COOKIE)
        if session_cookie:
            try:
                authorizer.authenticate_session(session_cookie)
                return RedirectResponse("/command-center", status_code=303)
            except HTTPException:
                pass
    return login_page(enabled=authorizer.browser_login_enabled, error=error)


@app.get("/auth/google/login")
def google_login():
    return begin_google_login(authorizer)


@app.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str = Query(default=""),
    state: str = Query(default=""),
    error: str = Query(default=""),
):
    if error or not code or not state:
        return RedirectResponse("/login?error=Google+login+was+cancelled", status_code=303)
    state_cookie = request.cookies.get(OAUTH_STATE_COOKIE)
    if not state_cookie:
        raise HTTPException(status_code=401, detail="login state cookie is missing")
    return complete_google_login(
        authorizer,
        code=code,
        state=state,
        state_cookie=state_cookie,
    )


@app.get("/logout")
def logout():
    return logout_response()


@app.get("/command-center")
def command_center_page(request: Request):
    if authorizer.browser_login_enabled:
        session_cookie = request.cookies.get(SESSION_COOKIE)
        if not session_cookie:
            return RedirectResponse("/login", status_code=303)
        try:
            authorizer.authenticate_session(session_cookie)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
    return command_center_html(browser_login_enabled=authorizer.browser_login_enabled)


@app.get("/api/v1/whoami")
def whoami(principal: Principal = Depends(require_viewer)) -> dict[str, str]:
    return {"role": principal.role.name.lower(), "subject": principal.subject}


@app.get("/api/v1/agents", response_model=list[AgentDescriptor])
def list_agents(_principal: Principal = Depends(require_viewer)) -> list[AgentDescriptor]:
    return hub.list_agents()


@app.get("/api/v1/integrations/marketing/status", response_model=dict[str, str])
def marketing_source_status(
    _principal: Principal = Depends(require_viewer),
) -> dict[str, str]:
    return hub.executor.marketing_sources.configuration_status()


@app.get(
    "/api/v1/integrations/campaign/status",
    response_model=dict[str, ProviderContract],
)
def campaign_provider_status(
    _principal: Principal = Depends(require_viewer),
) -> dict[str, ProviderContract]:
    return campaign_provider_contracts()


@app.get("/api/v1/tools/capabilities", response_model=list[ToolCapability])
def tool_capabilities(
    _principal: Principal = Depends(require_viewer),
) -> list[ToolCapability]:
    return list_tool_capabilities()


@app.post("/api/v1/agent-tasks", response_model=CommandCenterReport)
async def create_agent_task(
    task: AgentTask,
    _principal: Principal = Depends(require_operator),
) -> CommandCenterReport:
    report = hub.run(task)
    return await hub.analyze(report.task_id)


@app.post("/api/v1/agent-tasks/{task_id}/analyze", response_model=CommandCenterReport)
async def analyze_agent_task(
    task_id: str,
    _principal: Principal = Depends(require_operator),
) -> CommandCenterReport:
    try:
        return await hub.analyze(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get("/api/v1/agent-tasks/{task_id}", response_model=CommandCenterReport)
def get_agent_task(
    task_id: str,
    _principal: Principal = Depends(require_viewer),
) -> CommandCenterReport:
    report = hub.get(task_id)
    if report is None:
        raise HTTPException(status_code=404, detail="agent task not found")
    return report


@app.post(
    "/api/v1/agent-tasks/{task_id}/actions/{action_id}/decision",
    response_model=PlannedAction,
)
def decide_action(
    task_id: str,
    action_id: str,
    decision: ApprovalDecision,
    _principal: Principal = Depends(require_owner),
) -> PlannedAction:
    try:
        return hub.decide(task_id, action_id, decision)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="planned action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/agent-tasks/{task_id}/actions/{action_id}/execute",
    response_model=ToolExecutionResult,
)
async def execute_action(
    task_id: str,
    action_id: str,
    _principal: Principal = Depends(require_operator),
) -> ToolExecutionResult:
    try:
        return await hub.execute(task_id, action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="planned action not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/agent-tasks/{task_id}/executions",
    response_model=list[ToolExecutionResult],
)
def list_task_executions(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[ToolExecutionResult]:
    try:
        return hub.list_executions(task_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get(
    "/api/v1/agent-tasks/{task_id}/audit",
    response_model=list[AuditEvent],
)
def list_task_audit(
    task_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AuditEvent]:
    try:
        return hub.list_audit(task_id, limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent task not found") from exc


@app.get("/api/v1/command-center", response_model=CommandCenterSnapshot)
def command_center(
    limit: int = Query(default=50, ge=1, le=200),
    audit_limit: int = Query(default=50, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> CommandCenterSnapshot:
    return hub.command_center(limit=limit, audit_limit=audit_limit)


@app.post("/api/v1/campaigns", response_model=Campaign, status_code=201)
def create_campaign(
    request: CampaignCreate,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    return hub.campaigns.create(request, actor=principal.subject)


@app.post("/api/v1/campaigns/from-brief", response_model=Campaign, status_code=201)
def create_campaign_from_brief(
    request: CampaignBriefRequest,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    try:
        return hub.campaigns.create_from_brief(request, actor=principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/campaigns", response_model=list[Campaign])
def list_campaigns(
    limit: int = Query(default=50, ge=1, le=1000),
    status: CampaignStatus | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> list[Campaign]:
    return hub.campaigns.list(limit=limit, status=status)


@app.get("/api/v1/campaigns/{campaign_id}", response_model=Campaign)
def get_campaign(
    campaign_id: str,
    _principal: Principal = Depends(require_viewer),
) -> Campaign:
    try:
        return hub.campaigns.get(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@app.patch("/api/v1/campaigns/{campaign_id}", response_model=Campaign)
def update_campaign(
    campaign_id: str,
    update: CampaignDraftUpdate,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    try:
        return hub.campaigns.update_draft(campaign_id, update, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/campaigns/{campaign_id}/channel-plans/refresh", response_model=Campaign)
def refresh_campaign_channel_plans(
    campaign_id: str,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    try:
        return hub.campaigns.refresh_plans(campaign_id, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/campaigns/{campaign_id}/approvals/request", response_model=Campaign)
def request_campaign_approval(
    campaign_id: str,
    request: CampaignApprovalRequest,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    try:
        return hub.campaigns.request_approval(
            campaign_id,
            scope=request.scope,
            actor=principal.subject,
            note=request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/campaigns/{campaign_id}/approvals/{scope}/decision",
    response_model=Campaign,
)
def decide_campaign_approval(
    campaign_id: str,
    scope: str,
    decision: CampaignApprovalDecision,
    principal: Principal = Depends(require_owner),
) -> Campaign:
    try:
        return hub.campaigns.decide_approval(
            campaign_id,
            scope=scope,
            decision=decision,
            actor=principal.subject,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/campaigns/{campaign_id}/transitions", response_model=Campaign)
def transition_campaign(
    campaign_id: str,
    request: CampaignTransitionRequest,
    principal: Principal = Depends(require_operator),
) -> Campaign:
    try:
        return hub.campaigns.transition(
            campaign_id,
            target=request.target_status,
            actor=principal.subject,
            owner_authorized=principal.role == Role.OWNER,
            note=request.note,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/campaigns/{campaign_id}/audit", response_model=list[CampaignAuditEvent])
def campaign_audit(
    campaign_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[CampaignAuditEvent]:
    try:
        return hub.campaigns.history(campaign_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@app.get("/api/v1/campaigns/{campaign_id}/summary", response_model=CampaignSummary)
def campaign_summary(
    campaign_id: str,
    _principal: Principal = Depends(require_viewer),
) -> CampaignSummary:
    try:
        return hub.campaigns.summary(campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc


@app.get("/api/v1/attribution/status", response_model=AttributionStatus)
def attribution_status(
    _principal: Principal = Depends(require_viewer),
) -> AttributionStatus:
    return hub.attribution.status()


@app.get(
    "/api/v1/attribution/identity/status",
    response_model=AttributionIdentityStatus,
)
def attribution_identity_status(
    _principal: Principal = Depends(require_viewer),
) -> AttributionIdentityStatus:
    return hub.attribution.identity_status()


@app.get(
    "/api/v1/attribution/identity-mappings",
    response_model=list[CampaignIdentityMapping],
)
def list_attribution_identity_mappings(
    source_system: IdentitySource | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    _principal: Principal = Depends(require_viewer),
) -> list[CampaignIdentityMapping]:
    return hub.attribution.list_identity_mappings(
        source_system=source_system, campaign_id=campaign_id, limit=limit
    )


@app.post(
    "/api/v1/attribution/identity-mappings",
    response_model=CampaignIdentityMapping,
    status_code=201,
)
def register_attribution_identity_mapping(
    request: CampaignIdentityMappingCreate,
    principal: Principal = Depends(require_owner),
) -> CampaignIdentityMapping:
    try:
        return hub.attribution.register_identity_mapping(
            request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/experiments/status", response_model=ExperimentOSStatus)
def experiment_os_status(
    _principal: Principal = Depends(require_viewer),
) -> ExperimentOSStatus:
    return hub.experiments.status()


@app.post("/api/v1/experiments", response_model=Experiment, status_code=201)
def create_experiment(
    request: ExperimentCreate,
    principal: Principal = Depends(require_operator),
) -> Experiment:
    try:
        return hub.experiments.create(request, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"{exc.args[0]} not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/experiments", response_model=list[Experiment])
def list_experiments(
    limit: int = Query(default=50, ge=1, le=1000),
    campaign_id: str | None = Query(default=None),
    status: ExperimentStatus | None = Query(default=None),
    _principal: Principal = Depends(require_viewer),
) -> list[Experiment]:
    return hub.experiments.list(limit=limit, campaign_id=campaign_id, status=status)


@app.get("/api/v1/experiments/{experiment_id}", response_model=Experiment)
def get_experiment(
    experiment_id: str,
    _principal: Principal = Depends(require_viewer),
) -> Experiment:
    try:
        return hub.experiments.get(experiment_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc


@app.patch("/api/v1/experiments/{experiment_id}", response_model=Experiment)
def update_experiment(
    experiment_id: str,
    update: ExperimentDraftUpdate,
    principal: Principal = Depends(require_operator),
) -> Experiment:
    try:
        return hub.experiments.update_draft(experiment_id, update, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/preview",
    response_model=ExperimentPreview,
)
def preview_experiment(
    experiment_id: str,
    principal: Principal = Depends(require_operator),
) -> ExperimentPreview:
    try:
        return hub.experiments.preview(experiment_id, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/approvals/request",
    response_model=Experiment,
)
def request_experiment_approval(
    experiment_id: str,
    request: ExperimentApprovalRequest,
    principal: Principal = Depends(require_operator),
) -> Experiment:
    try:
        return hub.experiments.request_approval(
            experiment_id, actor=principal.subject, note=request.note
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/approvals/decision",
    response_model=Experiment,
)
def decide_experiment_approval(
    experiment_id: str,
    decision: ExperimentApprovalDecision,
    principal: Principal = Depends(require_owner),
) -> Experiment:
    try:
        return hub.experiments.decide_approval(
            experiment_id, decision, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/experiments/{experiment_id}/audit",
    response_model=list[ExperimentAuditEvent],
)
def experiment_audit(
    experiment_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[ExperimentAuditEvent]:
    try:
        return hub.experiments.history(experiment_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/observations",
    response_model=ExperimentObservation,
    status_code=201,
)
def add_experiment_observation(
    experiment_id: str,
    request: ExperimentObservationCreate,
    principal: Principal = Depends(require_operator),
) -> ExperimentObservation:
    try:
        return hub.experiments.add_observation(
            experiment_id, request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/experiments/{experiment_id}/observations",
    response_model=list[ExperimentObservation],
)
def list_experiment_observations(
    experiment_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    _principal: Principal = Depends(require_viewer),
) -> list[ExperimentObservation]:
    try:
        return hub.experiments.observations(experiment_id, limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc


@app.get(
    "/api/v1/experiments/{experiment_id}/tracking-validation",
    response_model=ExperimentTrackingValidation,
)
def validate_experiment_tracking(
    experiment_id: str,
    source_system: ObservationSource = Query(...),
    _principal: Principal = Depends(require_viewer),
) -> ExperimentTrackingValidation:
    try:
        return hub.experiments.validate_tracking(experiment_id, source_system)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"{exc.args[0]} not found") from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/tracking-mapping",
    response_model=ExperimentTrackingValidation,
)
def apply_experiment_meta_tracking_mapping(
    experiment_id: str,
    request: ExperimentMetaTrackingMappingUpdate,
    principal: Principal = Depends(require_owner),
) -> ExperimentTrackingValidation:
    try:
        return hub.experiments.apply_meta_tracking_mapping(
            experiment_id, request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"{exc.args[0]} not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/source-read",
    response_model=ExperimentSourceReadResult,
)
async def read_experiment_source(
    experiment_id: str,
    request: ExperimentSourceReadRequest,
    principal: Principal = Depends(require_operator),
) -> ExperimentSourceReadResult:
    try:
        return await hub.experiments.read_source_observation(
            experiment_id, request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"{exc.args[0]} not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/observations/{observation_id}/quality-decision",
    response_model=ExperimentObservation,
)
def decide_experiment_observation_quality(
    experiment_id: str,
    observation_id: str,
    decision: ExperimentObservationQualityDecision,
    principal: Principal = Depends(require_owner),
) -> ExperimentObservation:
    try:
        return hub.experiments.decide_observation_quality(
            experiment_id, observation_id, decision, actor=principal.subject
        )
    except KeyError as exc:
        detail = "observation not found" if exc.args[0] == "observation" else "experiment not found"
        raise HTTPException(status_code=404, detail=detail) from exc


@app.post(
    "/api/v1/experiments/{experiment_id}/evaluations",
    response_model=ExperimentEvaluation,
)
def evaluate_experiment(
    experiment_id: str,
    request: ExperimentEvaluationRequest,
    principal: Principal = Depends(require_operator),
) -> ExperimentEvaluation:
    try:
        return hub.experiments.evaluate(
            experiment_id, request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="experiment not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/attribution/touchpoints/backfill")
def backfill_attribution_touchpoints(
    request: TouchpointBackfillRequest,
    principal: Principal = Depends(require_operator),
) -> dict[str, int | bool]:
    try:
        return hub.attribution.backfill(request, actor=principal.subject)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post(
    "/api/v1/attribution/touchpoints/ingest",
    response_model=AttributionDataQualitySnapshot,
)
def ingest_attribution_source_touchpoints(
    request: SourceTouchpointIngestRequest,
    principal: Principal = Depends(require_operator),
) -> AttributionDataQualitySnapshot:
    return hub.attribution.ingest_source_touchpoints(
        request, actor=principal.subject
    )


@app.get(
    "/api/v1/attribution/data-quality",
    response_model=list[AttributionDataQualitySnapshot],
)
def list_attribution_data_quality(
    limit: int = Query(default=50, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionDataQualitySnapshot]:
    return hub.attribution.list_data_quality_snapshots(limit=limit)


@app.get(
    "/api/v1/attribution/intake/issues",
    response_model=list[AttributionIntakeIssue],
)
def list_attribution_intake_issues(
    status: str | None = Query(default="pending"),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionIntakeIssue]:
    try:
        return hub.attribution.list_intake_issues(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/attribution/intake/issues/{issue_id}/preview",
    response_model=AttributionIntakePreview,
)
def preview_attribution_intake_issue(
    issue_id: str,
    _principal: Principal = Depends(require_viewer),
) -> AttributionIntakePreview:
    try:
        return hub.attribution.preview_intake_issue(issue_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="intake issue not found") from exc


@app.post(
    "/api/v1/attribution/intake/issues/{issue_id}/replay",
    response_model=AttributionDataQualitySnapshot,
)
def replay_attribution_intake_issue(
    issue_id: str,
    principal: Principal = Depends(require_operator),
) -> AttributionDataQualitySnapshot:
    try:
        return hub.attribution.replay_intake_issue(
            issue_id, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="intake issue not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/attribution/deliveries/status",
    response_model=AttributionDeliveryStatus,
)
def attribution_delivery_status(
    _principal: Principal = Depends(require_viewer),
) -> AttributionDeliveryStatus:
    return hub.delivery.status()


@app.get(
    "/api/v1/attribution/deliveries/receipts",
    response_model=list[AttributionDeliveryReceipt],
)
def list_attribution_delivery_receipts(
    producer: str | None = Query(default=None),
    outcome: DeliveryOutcome | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionDeliveryReceipt]:
    return hub.delivery.list_receipts(
        producer=producer, outcome=outcome, limit=limit
    )


@app.get(
    "/api/v1/attribution/deliveries/dead-letters",
    response_model=list[AttributionDeadLetter],
)
def list_attribution_dead_letters(
    producer: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionDeadLetter]:
    return hub.delivery.list_dead_letters(producer=producer, limit=limit)


@app.post(
    "/api/v1/attribution/deliveries/receipts/verify",
    response_model=AttributionReceiptVerification,
)
def verify_attribution_delivery_receipt(
    request: AttributionReceiptVerificationRequest,
    _principal: Principal = Depends(require_viewer),
) -> AttributionReceiptVerification:
    try:
        return hub.delivery.verify(request.receipt)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post(
    "/api/v1/attribution/deliveries/failures",
    response_model=AttributionDeliveryReceipt,
)
def record_attribution_delivery_failure(
    request: AttributionDeliveryFailure,
    principal: Principal = Depends(require_operator),
) -> AttributionDeliveryReceipt:
    try:
        return hub.delivery.record_failure(request, actor=principal.subject)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/attribution/deliveries",
    response_model=AttributionDeliveryReceipt,
)
def ingest_attribution_delivery(
    request: AttributionDeliveryEnvelope,
    principal: Principal = Depends(require_operator),
) -> AttributionDeliveryReceipt:
    try:
        return hub.delivery.ingest(request, actor=principal.subject)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    "/api/v1/attribution/deliveries/heartbeats",
    response_model=list[AttributionHeartbeatReceipt],
)
def list_attribution_heartbeats(
    producer: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionHeartbeatReceipt]:
    return hub.delivery.list_heartbeats(producer=producer, limit=limit)


@app.post(
    "/api/v1/attribution/deliveries/heartbeats",
    response_model=AttributionHeartbeatReceipt,
)
async def ingest_attribution_heartbeat(
    request: AttributionProducerHeartbeat,
    principal: Principal = Depends(require_operator),
) -> AttributionHeartbeatReceipt:
    try:
        receipt = hub.delivery.ingest_heartbeat(request, actor=principal.subject)
        await hub.provider_health_scheduler.run_once(force=True)
        return receipt
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except DeliveryIntegrityConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post(
    "/api/v1/attribution/deliveries/heartbeats/verify",
    response_model=AttributionReceiptVerification,
)
def verify_attribution_heartbeat_receipt(
    request: AttributionHeartbeatReceiptVerificationRequest,
    _principal: Principal = Depends(require_viewer),
) -> AttributionReceiptVerification:
    try:
        return hub.delivery.verify_heartbeat(request.receipt)
    except DeliveryNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/v1/attribution/touchpoints", response_model=list[TouchpointEvent])
def list_attribution_touchpoints(
    campaign_id: str | None = Query(default=None),
    opportunity_id: str | None = Query(default=None),
    lead_id: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    _principal: Principal = Depends(require_viewer),
) -> list[TouchpointEvent]:
    return hub.attribution.list_touchpoints(
        campaign_id=campaign_id,
        opportunity_id=opportunity_id,
        lead_id=lead_id,
        limit=limit,
    )


@app.post(
    "/api/v1/attribution/reconciliations",
    response_model=AttributionReconciliation,
    status_code=201,
)
def create_attribution_reconciliation(
    request: ReconciliationRequest,
    principal: Principal = Depends(require_operator),
) -> AttributionReconciliation:
    try:
        return hub.attribution.reconcile(request, actor=principal.subject)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/attribution/reconciliations/{reconciliation_id}",
    response_model=AttributionReconciliation,
)
def get_attribution_reconciliation(
    reconciliation_id: str,
    _principal: Principal = Depends(require_viewer),
) -> AttributionReconciliation:
    try:
        return hub.attribution.get_reconciliation(reconciliation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="reconciliation not found") from exc


@app.post(
    "/api/v1/attribution/reconciliations/{reconciliation_id}/acceptance",
    response_model=AttributionReconciliation,
)
def decide_attribution_quality_acceptance(
    reconciliation_id: str,
    request: AttributionAcceptanceRequest,
    principal: Principal = Depends(require_owner),
) -> AttributionReconciliation:
    try:
        return hub.attribution.accept_quality(
            reconciliation_id, request, actor=principal.subject
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="reconciliation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/attribution/reconciliations/{reconciliation_id}/report",
    response_model=AttributionReport,
)
def attribution_report(
    reconciliation_id: str,
    model: AttributionModel = Query(default=AttributionModel.LAST_TOUCH),
    _principal: Principal = Depends(require_viewer),
) -> AttributionReport:
    try:
        return hub.attribution.report(reconciliation_id, model=model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="reconciliation not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/attribution/audit", response_model=list[AttributionAuditEvent])
def attribution_audit(
    limit: int = Query(default=100, ge=1, le=1000),
    _principal: Principal = Depends(require_viewer),
) -> list[AttributionAuditEvent]:
    return hub.attribution.audit(limit=limit)


@app.get(
    "/api/v1/attribution/sources/espocrm/opportunities",
    response_model=OpportunitySourceSnapshot,
)
async def read_espocrm_opportunity_snapshot(
    limit: int = Query(default=200, ge=1, le=500),
    _principal: Principal = Depends(require_operator),
) -> OpportunitySourceSnapshot:
    try:
        return await hub.opportunity_reader.read(limit=limit)
    except EspoOpportunityNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoOpportunityError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post(
    "/api/v1/attribution/reconciliations/espocrm",
    response_model=AttributionReconciliation,
    status_code=201,
)
async def reconcile_espocrm_opportunities(
    limit: int = Query(default=200, ge=1, le=500),
    principal: Principal = Depends(require_operator),
) -> AttributionReconciliation:
    try:
        snapshot = await hub.opportunity_reader.read(limit=limit)
    except EspoOpportunityNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoOpportunityError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not snapshot.observations:
        raise HTTPException(
            status_code=409,
            detail="EspoCRM has no Opportunity snapshots; quality acceptance remains blocked",
        )
    try:
        return hub.attribution.reconcile(
            ReconciliationRequest(observations=snapshot.observations),
            actor=principal.subject,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get(
    "/api/v1/integrations/espocrm/schema/{entity_type}",
    response_model=EspoEntitySchema,
)
async def espocrm_schema(
    entity_type: str,
    _principal: Principal = Depends(require_viewer),
) -> EspoEntitySchema:
    try:
        return await schema_reader.read_entity(entity_type)
    except EspoSchemaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoSchemaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get(
    "/api/v1/integrations/espocrm/mapping/{entity_type}",
    response_model=EspoMappingRecommendation,
)
async def espocrm_mapping(
    entity_type: str,
    _principal: Principal = Depends(require_viewer),
) -> EspoMappingRecommendation:
    try:
        return await mapping_reader.recommend(entity_type)
    except EspoSchemaNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EspoSchemaError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
