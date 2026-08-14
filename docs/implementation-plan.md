# Sprint 1 Implementation Plan

1. **Bootstrap the monorepo.** Add Python and Node toolchains, formatting, linting, tests, and developer commands.
2. **Codify shared contracts.** Implement request/status models and compile the video-manifest schema for both runtimes.
3. **Create the FastAPI skeleton.** Add settings, health endpoint, dependency boundaries, and structured logging.
4. **Implement Redis job state.** Define immutable input snapshots, state transitions, progress, attempts, and TTL policy.
5. **Implement job endpoints.** Add create, status, and artifact access with idempotency and safe validation errors.
6. **Implement the content director.** Create provider interfaces plus deterministic fake and configured LLM adapter.
7. **Implement Vietnamese TTS.** Create provider interface, deterministic test fixture, duration probing, and configured adapter.
8. **Implement the local asset resolver.** Index allowlisted files and map storyboard slots without Vision AI or stock APIs.
9. **Build and validate manifests.** Generate timed scenes/subtitles and reject contract or duration violations.
10. **Implement Remotion rendering.** Build `real-estate-short-v1`, renderer HTTP boundary, progress reporting, and H.264 output.
11. **Implement the resumable worker.** Orchestrate stages, persist artifacts atomically, retry transient failures, and record terminal errors.
12. **Complete the n8n smoke workflow.** Normalize input, create job, poll with a bounded loop, and surface the artifact URL.
13. **Prove the vertical slice.** Run contract/unit/E2E tests, inspect video metadata, document commands, and attach evidence to the PR.

Each task must leave the repository testable. Later tasks may extend earlier interfaces but must not expand the Sprint 1 exclusions.
