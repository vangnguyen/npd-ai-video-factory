# GitHub main-branch protection

## Audit result

The read-only GitHub API audit on 2026-08-22 returned `404 Branch not protected` for
`main`. The repository therefore had no server-side rule preventing a direct push,
force-push, branch deletion or merge with failed checks.

This stabilization change makes all three required workflows run for every pull request
targeting `main`. A stacked pull request may remain based on its dependency while under
development, but before merge it must be rebased/retargeted to current `main`; that event
is the mandatory full-CI gate.

## Required rule values

Configure a classic branch-protection rule or ruleset for the exact branch `main`:

| Setting | Required value |
|---|---|
| Require a pull request before merging | enabled |
| Required approving reviews | 1 |
| Dismiss stale approvals on new commits | enabled |
| Require review from Code Owners | disabled until a reviewed `CODEOWNERS` file exists |
| Require approval of the most recent push | enabled if the plan supports it |
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
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": true
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

If the GitHub plan or API rejects `require_last_push_approval`, remove only that property;
keep the one-review, stale-dismissal and full-CI gates. Record the API/UI result in this
document instead of claiming protection was enabled.

## Verification checklist

1. A direct push to `main` is rejected.
2. A draft PR cannot merge.
3. A PR missing any required job cannot merge.
4. A failed API, worker, renderer or Docker Compose E2E job blocks merge.
5. A new commit dismisses a stale approval.
6. A force-push and branch deletion are rejected.
7. Retargeting a stacked PR to `main` starts all three workflows.
8. The protection rule does not merge or deploy anything by itself.
