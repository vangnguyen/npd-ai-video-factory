# Video Factory legacy PR audit

## Decision

Do not merge PR #6 or PR #8 directly, and do not close either one yet. Both are draft,
conflicting and strongly diverged from `main`, but the blob-level audit found code that is
not present on current `main`. The safe disposition is a clean port from future stabilized
`main`, not a merge or a 100-plus-commit history transplant.

The 2026-08-26 status recheck confirmed both PRs remain open and draft. Their disposition
is unchanged; Phase 9 work must not absorb or merge their divergent histories.

## Evidence summary

| PR | Scope files | Identical on main | Changed from main | Missing from main | Disposition |
|---|---:|---:|---:|---:|---|
| #6 `codex/production-pilot` | 17 | 0 | 12 | 5 | keep draft; selectively port production-provider work |
| #8 `agent/complete-sprint-1-vertical-slice` | 36 | 0 | 22 | 14 | keep draft; selectively port QC/renderer hardening |

Ten paths overlap between the PRs, including worker pipeline, renderer, E2E smoke and the
n8n Sprint 1 workflow. PR #8 is the later implementation for those overlapping paths and
should be the comparison source; PR #6 must not overwrite it.

## PR #6 disposition

Still useful and absent from `main`:

- OpenAI Vietnamese TTS adapter and provider tests;
- guarded one-shot production pilot runner with an explicit enable flag;
- asset/provider preflight;
- production TTS smoke helper;
- production-pilot runbook;
- request-driven duration check.

Superseded or unsafe to port wholesale:

- overlapping worker, renderer, n8n and E2E files predate PR #8 hardening;
- its branch omits all newer Agent Hub/Phase 5–8 architecture;
- its current merge result would delete newer production code.

Recommended action after stabilization: create a new video-provider branch from current
`main`, reimplement the OpenAI TTS adapter and guarded provider preflight with current
interfaces, run secret-free unit tests, then require owner approval and human listening.

## PR #8 disposition

Still useful and absent or materially stronger than `main`:

- per-scene PCM narration assembly and measured subtitle cues;
- exact narration master duration and audible-sample validation;
- decoded luminance and audio-peak QC that prevents black/silent false passes;
- visible E2E fixtures;
- renderer request/contract/engine tests and package lock;
- API/n8n contract regression tests;
- cross-platform E2E interpreter handling.

Current `main` already has a working FastAPI/Redis/worker/Remotion vertical slice and
offline Vietnamese eSpeak, so porting must be a focused parity patch rather than replacing
the full pipeline. The recommended clean-port order is tests/fixtures, narration timing,
decoded-media QC, then renderer contract decomposition.

## Human voice acceptance requirement

Technical CI evidence from PR #8 passed container rendering, visual sampling and audio
integrity after its blocker fixes. That does not establish acceptable Vietnamese voice
quality. Offline eSpeak is deterministic test infrastructure, not an approved production
voice. A human must listen to the final artifact and explicitly accept pronunciation,
fluency, pacing, subtitle alignment and tail silence before any production TTS merge or
publishing work.

## Current production TTS status

Current `main` defaults to `TTS_PROVIDER=espeak` and contains eSpeak plus an explicit
unconfigured provider. It does not contain PR #6's OpenAI production TTS adapter. No
production TTS credential or automatic publishing capability is enabled by this audit.

## Video Factory work still missing

- clean-port of PR #8 media-QC and measured-cue improvements;
- clean-port and security review of the production TTS adapter;
- human Vietnamese voice acceptance;
- production asset rights/provenance acceptance;
- current-main Docker Compose E2E after each port;
- owner-gated publication design; automatic publish remains disabled.

Close #6/#8 only after every retained item has a traceable clean replacement PR or the
owner explicitly decides it is no longer needed.
