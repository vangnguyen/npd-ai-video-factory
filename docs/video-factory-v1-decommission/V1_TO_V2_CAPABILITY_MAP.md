# Video Factory V1 to V2/V3 capability map

## Contract source and rule

This map uses only the documented external boundary in the independent V2/V3 repository at commit
[`8fa9640`](https://github.com/vangnguyen/npd-video-factory-v2/commit/8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee):

- [Agent Hub Bridge v1](https://github.com/vangnguyen/npd-video-factory-v2/blob/8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee/docs/AGENT_HUB_BRIDGE.md)
- [V2-11 API](https://github.com/vangnguyen/npd-video-factory-v2/blob/8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee/docs/API.md)
- [V2-11 security](https://github.com/vangnguyen/npd-video-factory-v2/blob/8fa96409b0db6ec6d4dc3c04f6e3aaab2f3201ee/docs/SECURITY.md)

The V2/V3 repository and runtime were not modified. Non-bridge V2 endpoints are documented below
only to identify ownership; they are **not** authorized Agent Hub integration endpoints.

## Architectural decision

Agent Hub retains:

- business intent, campaign context, orchestration, human-approval surfaces and audit;
- a narrow `VideoFactoryClient` that signs versioned service requests;
- webhook verification, replay protection, idempotent event persistence and correlation IDs;
- normalized project/cost/publication/analytics summaries for business reporting.

Video Factory V2/V3 retains:

- script/media intelligence, uploads, providers, TTS, subtitles, timeline editing and preview;
- Remotion/FFmpeg/ComfyUI/Vision/image/video generation implementations;
- review/final rendering, media QC, artifact storage, publication receipts and media cost ledger;
- its own PostgreSQL, Redis, object storage, secrets, provider gates and acceptance gates.

There will be no internal package import, shared database, direct Redis coupling, shared process
memory, or undocumented API call.

## Current bridge truth

The documented V2-11 bridge exposes:

| Method | Path | Current capability |
|---|---|---|
| `GET` | `/api/v1/bridge/contract` | Version, actions, events, roles and isolation truth |
| `POST` | `/api/v1/bridge/project-requests` | Idempotent `project.create_draft` only |
| `GET` | `/api/v1/bridge/project-requests/{request_id}` | Durable request state |
| `GET` | `/api/v1/bridge/projects/{project_id}/summary` | Read-only project/cost/publication/analytics counts |
| `GET` | `/api/v1/bridge/events` | Secret-free outbound event history |
| `GET` | `/api/v1/bridge/webhook-deliveries` | Delivery state and signed receipt metadata |

Every bridge endpoint requires the `agent-hub-bridge.v1` version header and a dedicated `service`
identity. Requests bind method, exact path, exact query, timestamp, nonce and body SHA-256 into an
HMAC-SHA256 signature. POST also requires `Idempotency-Key`.

The only current inbound action creates a draft project and immutable initial version. It fixes:

- `execution_mode=draft_only`;
- `start_pipeline=false`;
- `publish_requested=false`;
- `external_action_requested=false`.

The complete event vocabulary is reserved, but V2-11 currently emits only
`video.project.created`. A declared event must not be treated as live until its durable emitter is
documented and accepted.

## Capability map

| V1 capability | Current V1 implementation | Documented V2/V3 owner/capability | Bridge coverage now | Agent Hub action | Decision |
|---|---|---|---|---|---|
| Business video brief | `VideoProducerAgent`, `video.brief.create` | Bridge draft project request | Full for draft intake once client is implemented | Keep planning; map typed brief to signed request | `KEEP` |
| Create/enqueue video job | `POST /api/v1/video-jobs` | V2 has project-bound jobs internally | **Not equivalent:** bridge can create draft only and cannot start pipeline | Build compatibility only after a versioned bridge action is accepted | `REPLACE_WITH_V2_API` |
| Get job status | `GET /api/v1/video-jobs/{id}` | V2 request state, project summary, internal job/event APIs | Partial: bridge request state and summary only | Map new projects to bridge state; keep legacy read adapter for old IDs | `REPLACE_WITH_V2_API` |
| Artifact download | V1 recorded-name file route | V2 project-scoped checksummed object/artifact delivery | No bridge artifact route | Agent Hub should surface links/status only; archive V1 reads separately | `MIGRATE` |
| Script/storyboard | Deterministic provider in V1 worker | V2 content intelligence/project versions | Not exposed as Agent Hub execution detail | Remove implementation from Agent Hub boundary | `DEPRECATE` |
| Local asset selection | Filesystem asset folder | V2 project assets/object storage with rights/provenance | Draft request may carry business context, not raw filesystem coupling | Do not send local paths; use explicit project/asset contracts later | `MIGRATE` |
| TTS | eSpeak/OpenAI adapter in V1 worker | V2 audio/provider registry and cost controls | No bridge TTS action | Remove provider execution and secrets from V1/Agent Hub | `DEPRECATE` |
| Subtitle generation/edit | Worker SRT plus manifest cues | V2 versioned subtitles and production package | No bridge edit action | Agent Hub may request business outcome only after contract expansion | `DEPRECATE` |
| Manifest/timeline | V1 manifest v1.0 | V2 immutable project/timeline/subtitle/audio versions | Summary only | Retain V1 schema for archive; never import V2 schema packages | `KEEP` for history |
| Proxy preview | V1 has no separate preview resource | V2 preview resource | No bridge preview action/event currently live | Future signed request + `video.preview.ready` event required | `REPLACE_WITH_V2_API` when available |
| Render | Public V1 `/render` | V2 review/final render and QC | No bridge render action | Never call renderer directly; wait for versioned bridge support | `DEPRECATE` |
| Render status/QC | V1 job progress, `qc.json` | V2 render records, QC and evidence | Summary counts only | Consume normalized status/event, not renderer internals | `REPLACE_WITH_V2_API` when available |
| Human approval | V1 terminal `awaiting_review`; human process outside API | V2 explicit approval resource bound to version tuple | No bridge approval command/event emitter currently live | Agent Hub may surface request and submit decision only via future signed contract | `MIGRATE` |
| Publish | Not implemented by V1 job API | V2 publishing validation/receipts; current success is dry-run only | Summary count only; no bridge publish action | Do not add publishing to Agent Hub or V1; preserve owner gates | `DEPRECATE` |
| Publication status | Not represented in V1 | V2 publication resources | Project summary count only | Future normalized events/read contract | `REPLACE_WITH_V2_API` when available |
| Analytics | Not represented in V1 | V2 analytics sync/snapshots/assessments/insights | Project summary count only | Consume business summaries/events; do not duplicate provider ledger | `REPLACE_WITH_V2_API` when available |
| Media cost detail | Not durable in V1 | V2 VND cost ledger | Project summary includes cost counts, not detailed ledger | Aggregate approved summaries into campaign cost/ROI | `MIGRATE` |
| n8n media orchestration | Inactive manual V1 smoke | V2 owns media workflow; n8n remains integration automation | Bridge calls can be made by Agent Hub client, not duplicated in n8n | Archive V1 workflow; keep n8n out of media engine | `DEPRECATE` |

## Proposed `VideoFactoryClient` contract status

AH-01 does not implement this client. The table prevents conceptual methods from being wired to
undocumented or non-bridge endpoints.

| Client method | Allowed bridge mapping at V2-11 | Status for AH-02 |
|---|---|---|
| `get_contract()` | `GET /api/v1/bridge/contract` | Ready for mock/contract implementation |
| `create_project()` | `POST /api/v1/bridge/project-requests` | Ready, draft-only |
| `get_project_request()` | `GET /api/v1/bridge/project-requests/{request_id}` | Ready |
| `get_project()` | `GET /api/v1/bridge/projects/{project_id}/summary` | Partial business summary |
| `list_events()` | `GET /api/v1/bridge/events` | Ready for declared/live distinction |
| `list_webhook_deliveries()` | `GET /api/v1/bridge/webhook-deliveries` | Ready for operations/audit |
| `request_generation()` | None | Blocked; do not call `/api/v1/video-jobs` directly |
| `request_analysis()` | None | Blocked |
| `request_preview()` | None | Blocked |
| `request_render()` | None | Blocked |
| `submit_approval()` | None | Blocked |
| `request_publish()` | None | Blocked; V2 live publish is not accepted |
| `get_publications()` | Summary count only | Partial; detailed bridge read needed if business requires it |
| `get_analytics()` | Summary count only | Partial; normalized bridge read/event needed |

## Webhook map

Target events from the master architecture must be handled only after each emitter is live:

| Event | Contract vocabulary | V2-11 emitter status | Agent Hub handler status |
|---|---|---|---|
| `trend.opportunity.detected` | Reserved | Not claimed live | Do not enable |
| `idea.shortlist.ready` | Reserved | Not claimed live | Do not enable |
| `video.project.created` | Reserved | Live in V2-11 | AH-02 may implement mocked verifier/persistence |
| `video.analysis.completed` | Reserved | Not claimed live | Do not enable |
| `video.preview.ready` | Reserved | Not claimed live | Do not enable |
| `video.approval.required` | Reserved | Not claimed live | Do not enable |
| `video.approved` | Reserved | Not claimed live | Do not enable |
| `video.render.completed` | Reserved | Not claimed live | Do not enable |
| `video.render.failed` | Reserved | Not claimed live | Do not enable |
| `video.publish.completed` | Reserved | Not claimed live | Do not enable |
| `video.publish.failed` | Reserved | Not claimed live | Do not enable |
| `video.analytics.updated` | Reserved | Not claimed live | Do not enable |
| `video.winner.detected` | Reserved | Not claimed live | Do not enable |

Future Agent Hub webhook handling must validate HMAC, timestamp, body hash, contract version and
historical key ID; reject replayed event IDs/nonces; persist the event before processing; remain
retry-safe; and write an audit trail. V2's secret files and Redis queues remain V2-owned.

## Correlation and observability

The future bridge must persist a mapping without shared storage:

```text
campaign_id
  -> agent_task_id / action_id
  -> bridge request_id / idempotency hash
  -> video_factory_project_id
  -> webhook event_id / delivery receipt
  -> publication and analytics summary IDs when available
```

Agent Hub must not persist raw V2 secrets, provider payloads, internal Redis keys, local filesystem
paths, or database identifiers that are not part of the external contract.

## Blocking gaps before V1 write deprecation

1. Current bridge draft creation does not replace V1 job execution.
2. Generation, analysis, preview, render, approval, detailed publication and detailed analytics are
   not bridge actions/reads at V2-11.
3. Only `video.project.created` is currently emitted.
4. The Agent Hub client, HMAC signer, nonce/idempotency store, webhook verifier and contract tests
   do not yet exist.
5. Production bridge deployment and Caddy exposure are separate owner/acceptance gates.
6. The V1 renderer still has an unknown direct caller.

Until these gaps are resolved through reviewed versioned contracts, V1 create cannot be safely
proxied and V1 runtime cannot be disabled.
