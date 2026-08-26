# Phase 8.9 — Alert Routing Preview

## Outcome

Phase 8.9 centralizes provider-alert severity routing, dedupe windows, cooldown and
escalation rules. It only produces a deterministic preview in Command Center. It does
not configure or contact email, PWA, Zalo or ticket providers and does not mutate a
source system.

The implementation was originally developed as a stacked branch after Phase 8.8. Its
current authoritative state supersedes that historical note: PR #20 is merged into
`main` at `400899ba82501beeea469f4a33dc169a9a09bb8e` and is live as Agent Hub
`0.13.0`. The external-delivery behavior remains preview-only.

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
- whether escalation would apply after suppression; acknowledged, resolved and
  cooldown alerts always report `escalation_would_apply=false` even when the raw
  time/occurrence threshold has been met;
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
8. The fixed 24-hour production window from `2026-08-25T05:11:00Z` through
   `2026-08-26T05:11:00Z` passed with 288/288 heartbeats, zero gaps above 330 seconds,
   zero lease skips, zero overlapping incidents, five healthy providers and no safety
   violation.

## Intentional limits

No external provider adapter, credential onboarding, notification queue, subscription,
send retry, incident ticket or auto-remediation is included. Production deployment of
the internal preview does not enable external notification delivery: candidate providers
remain `not_configured`, `would_send=false`, external notifications remain disabled and
production write remains disabled. A separate owner-approved phase is required before
proposing any least-privilege external notification provider.
