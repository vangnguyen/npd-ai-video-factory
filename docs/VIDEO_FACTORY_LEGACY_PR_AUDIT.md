# Video Factory legacy PR audit

## Decision

Legacy PR #8 and PR #6 have now been clean-ported in the required order and closed as
superseded **without merge**. Their divergent histories were not reintroduced.

- PR #8 was replaced by draft PR
  [#34](https://github.com/vangnguyen/npd-ai-video-factory/pull/34), based on current
  `main` and limited to the useful Sprint 1/media-QC improvements.
- PR #6 was replaced by stacked draft PR
  [#35](https://github.com/vangnguyen/npd-ai-video-factory/pull/35), based on #34 and
  limited to the useful production-pilot/TTS work.

Both replacement PRs remain unmerged and undeployed pending owner review. Closing the
legacy PRs was repository cleanup, not production authorization.

## Historical audit result

| Legacy PR | Scope files | Identical on historical main | Changed | Missing | Final disposition |
|---|---:|---:|---:|---:|---|
| #6 `codex/production-pilot` | 17 | 0 | 12 | 5 | Closed; useful work reimplemented in #35 |
| #8 `agent/complete-sprint-1-vertical-slice` | 36 | 0 | 22 | 14 | Closed; useful work reimplemented in #34 |

Ten paths overlapped between the two old branches. PR #8 was used as the later QC
baseline; the production-pilot port was then layered on top so PR #6 could not overwrite
its renderer, narration, n8n or E2E hardening.

## PR #8 replacement — PR #34

The clean port retains:

- per-scene PCM narration assembly and measured subtitle cues;
- exact narration duration and audible-sample validation;
- decoded luminance and audio-peak checks that reject black/silent false passes;
- visible deterministic E2E fixtures;
- renderer contract/engine tests and API/n8n regression coverage;
- cross-platform E2E interpreter handling.

Evidence on the clean branch:

- API: `12 passed`;
- worker: `17 passed`;
- renderer: `8 passed`, typecheck and bundle PASS;
- local Docker Compose E2E media contract PASS;
- all seven GitHub checks, including Docker Compose E2E, green.

No real production media or credential was added to Git.

## PR #6 replacement — PR #35

The clean port retains:

- OpenAI Vietnamese TTS adapter with deterministic/offline CI fallback;
- guarded, explicitly enabled one-shot production-pilot runner;
- asset and provider preflight;
- request-driven duration checks;
- bounded production-TTS speed fit connected to the active narration path;
- production-pilot operator documentation.

Evidence on the clean branch:

- API: `18 passed`;
- worker: `24 passed`;
- renderer: `8 passed`, typecheck and bundle PASS;
- Docker Compose E2E job `vid_1787741618152_a19ae99d0d` reached
  `awaiting_review` with 30.059 seconds, 1080x1920, 30 fps, H.264/AAC, 30 visual
  samples, dark-frame ratio `0` and audio peak `-3 dB`;
- all GitHub checks applicable to the stacked branch are green. Full protected-branch
  gates must run again after #35 is retargeted to updated `main`.

No publishing or production deployment was performed.

## Human voice acceptance requirement

Technical checks establish decodability, audible audio, timing, subtitle alignment and
absence of black/silent output. They do **not** establish acceptable Vietnamese voice
quality. Issue [#5](https://github.com/vangnguyen/npd-ai-video-factory/issues/5) therefore
remains open for the owner to listen and explicitly accept pronunciation, fluency,
pacing and tail silence.

Review artefacts are kept outside Git:

- `outputs/video-production-pilot-v2/production-pilot-v2-owner-review.mp4`;
- `outputs/video-production-pilot-v2/production-pilot-v2-narration-owner-review.wav`.

The MP4 SHA-256 recorded at handoff is
`8880671615269C0246767735EE3083DA9860928A01BE2DE5BE81D7EC4C3AFAD9`.

## Current production TTS status

Current `main` and the live production baseline are unchanged by this audit. The clean
production TTS adapter exists only in draft PR #35. Offline eSpeak remains deterministic
test infrastructure, not an approved production voice. No publishing capability was
enabled.

## Remaining Video Factory work

1. Owner reviews and merges #34 before #35, with protected-branch CI on each final head.
2. Owner performs the human Vietnamese voice acceptance and closes issue #5 only after
   an explicit decision.
3. Production asset rights/provenance remains an owner gate for any real campaign.
4. Any later publication design remains separately owner-gated; automatic publish is
   still disabled.

Issue [#7](https://github.com/vangnguyen/npd-ai-video-factory/issues/7) was closed as
`not planned`: a generic multi-niche AI Content Network Factory conflicts with the
accepted Ngọc Phương Đông real-estate roadmap and is not being carried into Phase 9.
