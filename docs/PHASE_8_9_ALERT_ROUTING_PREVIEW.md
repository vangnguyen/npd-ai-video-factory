# Phase 8.9 — Alert Routing Preview

## Outcome

Phase 8.9 centralizes provider-alert severity routing, dedupe windows, cooldown and
escalation rules. It only produces a deterministic preview in Command Center. It does
not configure or contact email, PWA, Zalo or ticket providers and does not mutate a
source system.

This branch is stacked on draft Phase 8.8 PR #19. It must remain a separate draft PR and
must not be deployed to production until the Phase 8.8 48-hour acceptance evidence is
reviewed by the owner.

## Policy matrix

| Severity | Dedupe | Cooldown | Candidate channels | Escalation preview |
|---|---:|---:|---|---|
| info | 60 min | 60 min | email | none |
| warning | 30 min | 30 min | email, PWA | owner review after 60 min or 3 occurrences |
| critical | 15 min | 15 min | email, PWA, Zalo, ticket | owner review after 15 min or 2 occurrences |

Candidate channels are metadata only. Their provider state is always `not_configured`,
execution state is `preview_only`, and `would_send=false`. Runtime alert execution targets
remain only `command_center` and `audit`.

## API and UI

`GET /api/v1/provider-health/alerts/{alert_id}/routing-preview` is viewer-readable and
purely computes:

- the existing stable dedupe key;
- policy windows and remaining cooldown;
- suppression state for cooldown, acknowledged or resolved incidents;
- whether escalation would apply;
- a bounded, PII-free notification title/message preview;
- candidate channels with external delivery disabled.

Command Center renders this contract beneath the internal alert queue. Preview does not
acknowledge the alert, append a delivery, create a credential or trigger a webhook.

## Acceptance gates

1. Severity maps to one centralized immutable policy.
2. Stable alert dedupe key is reused; no duplicate notification object is persisted.
3. Cooldown and acknowledged/resolved suppression are explicit.
4. Escalation is advisory and targets only `owner_review_preview`.
5. Viewer can inspect preview; no role can send externally.
6. Email/PWA/Zalo/ticket remain `not_configured`; `would_send=false`.
7. Existing Phase 1–8.8 tests, Agent Hub CI, Phase 5 bundle and Sprint 1 Docker E2E pass.

## Intentional limits

No external provider adapter, credential onboarding, notification queue, subscription,
send retry, incident ticket, auto-remediation or production deployment is included.
Owner approval after the Phase 8.8 observation window is required before proposing any
least-privilege external notification provider.
