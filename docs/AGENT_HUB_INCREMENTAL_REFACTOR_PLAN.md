# Agent Hub incremental refactor plan

## Constraints

Refactor only after the Phase 8 dependency stack is on `main`. Use small pull requests,
preserve every public route/response, Redis key, audit event and safety flag, and require
API parity tests. No rewrite and no forced data migration.

## Sequence

1. Extract provider-health HTTP routes from `main.py` into
   `routers/provider_health.py`; keep the same singleton services, dependencies, paths,
   status codes and OpenAPI operation contracts.
2. Extract attribution/delivery routes, then campaigns, experiments, agents and auth in
   separate PRs. `main.py` becomes app lifecycle plus router registration.
3. Introduce repository modules behind the existing `HubStore` protocol. Start with
   provider health and delivery; the existing memory/Redis stores delegate without
   changing keys or serialization.
4. Split the dashboard by bounded render fragments/assets while preserving the exact
   `/command-center` shell and browser behavior.

## Mandatory parity gates per extraction

- route-method-path inventory before/after is identical;
- OpenAPI response schema and RBAC tests pass;
- Redis keys and encoded payloads are byte/field compatible;
- memory and fakeredis restart tests pass;
- business eval 20/20;
- Python compile and JavaScript syntax pass;
- Agent Hub, Phase 5 and Sprint 1 Docker E2E green;
- no write/notification/executor flag changes.

The first safe extraction is provider-health routing because its endpoints are cohesive,
read-mostly and already have Phase 8.7–8.9 contract tests. It must be a separate draft PR
based on the latest stabilized dependency, not part of the HMAC or roadmap PR.

