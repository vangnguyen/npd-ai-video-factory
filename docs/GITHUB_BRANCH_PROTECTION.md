# GitHub main-branch protection

## Audit result

The read-only GitHub API audit on 2026-08-22 initially returned
`404 Branch not protected` for `main`. The stabilization run then applied the policy below
through the GitHub API. The verification response confirmed `strict=true`, the six
required contexts, required PRs, admin enforcement, conversation resolution, and force
push/deletion disabled. The review count remains zero until an independent reviewer is
available, preventing a single-maintainer lockout while still blocking direct/failed-CI
merges.

This stabilization change makes all three required workflows run for every pull request
targeting `main`. A stacked pull request may remain based on its dependency while under
development, but before merge it must be rebased/retargeted to current `main`; that event
is the mandatory full-CI gate.

## Required rule values

Configure a classic branch-protection rule or ruleset for the exact branch `main`:

| Setting | Required value |
|---|---|
| Require a pull request before merging | enabled |
| Required approving reviews | 0 for the current single-maintainer repository; use 1 only after a non-author reviewer is available |
| Dismiss stale approvals on new commits | enabled when review count is 1 |
| Require review from Code Owners | disabled until a reviewed `CODEOWNERS` file exists |
| Require approval of the most recent push | disabled for one maintainer; enable with an independent reviewer |
| Require conversation resolution | enabled |
| Require status checks | enabled |
| Require branches to be up to date | enabled (`strict=true`) |
| Allow force pushes | disabled |
| Allow deletions | disabled |
| Include administrators / bypass actors | enabled/no bypass for normal operation |
| Allow failed-CI merge | disabled |

Classic branch protection stores the check-run job name as its context. Select the rows
shown with these workflow/job pairs in the UI; the exact REST `contexts` values are the
job names after the arrow:

- Agent Hub CI / `test` -> `test`
- Phase 5 Deployment Bundle CI / `validate` -> `validate`
- Sprint 1 CI / `test-api` -> `test-api`
- Sprint 1 CI / `test-worker` -> `test-worker`
- Sprint 1 CI / `test-renderer` -> `test-renderer`
- Sprint 1 CI / `e2e-vertical-slice` -> `e2e-vertical-slice`

When the Phase 8.8 n8n validation job reaches `main`, also require:

- Agent Hub CI / `validate-n8n-workflows` -> `validate-n8n-workflows`

Do not require the optional external TTS smoke because it is intentionally skipped when
no approved production credential is present. Human listening remains a separate owner
acceptance gate.

## Exact REST payload

An owner may apply the rule with GitHub's branch-protection API after confirming the
check-context spelling in the repository UI. Do not paste a token into this command:

```json
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "test",
      "validate",
      "test-api",
      "test-worker",
      "test-renderer",
      "e2e-vertical-slice"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": false,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_linear_history": false,
  "lock_branch": false,
  "allow_fork_syncing": true
}
```

The zero-review setting still requires a PR and every CI gate, while avoiding a permanent
lockout because GitHub does not let a PR author approve their own change. Once a second
maintainer is available, change the review count to one, enable stale-dismissal and require
approval of the most recent push. Record the API/UI result instead of claiming protection
was enabled.

## Verification checklist

1. A direct push to `main` is rejected.
2. A draft PR cannot merge.
3. A PR missing any required job cannot merge.
4. A failed API, worker, renderer or Docker Compose E2E job blocks merge.
5. After an independent reviewer is configured, a new commit dismisses a stale approval.
6. A force-push and branch deletion are rejected.
7. Retargeting a stacked PR to `main` starts all three workflows.
8. The protection rule does not merge or deploy anything by itself.
