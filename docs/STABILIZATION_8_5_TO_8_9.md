# Stabilization gate for Phase 8.5–8.9

Feature development is frozen. Allowed changes are bug fixes, tests, observability,
documentation and security/reliability fixes.

The Phase 8.8 production observation baseline is
`phase88-acceptance-baseline-20260822T143413Z.json`, starting at
2026-08-22 21:34 Asia/Ho_Chi_Minh. A final report generated before
2026-08-24 21:34 Asia/Ho_Chi_Minh is invalid.

If the final report passes heartbeat continuity, scheduler/lease/error SLOs, incident
recovery, provider health, restart/persistence and zero-side-effect gates, merge only in
this order after owner approval:

```text
#16 -> latest main
#17 -> latest main
#18 -> latest main
#19 -> latest main
```

Each final head must run Agent Hub CI, Phase 5 Deployment Bundle CI, Sprint 1 API/worker/
renderer/Docker E2E, business eval 20/20, compile/syntax, diff checks and n8n import
validation when applicable. Production must not be redeployed when the reviewed `main`
commit is code-equivalent to the live commit.

PR #20 remains draft/preview-only and cannot deploy until the observation gate passes,
dependencies are merged, full CI passes and the owner approves. The HMAC keyring and every
god-file extraction remain separate draft PRs.
