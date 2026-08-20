# Phase 6 read-only credential onboarding

This runbook onboards three independent production identities for Agent Hub. It does not reuse the Meta lead-ingestion token, does not grant Ads management, does not grant GA4 edit access, and does not enable the n8n write executor.

## Audited targets (2026-08-20)

| Source | Target | Identifier | Credential boundary |
|---|---|---|---|
| Meta Ads | `Bat Dong San 1`, `Bat Dong San 4` | Graph account IDs `act_556651439430505`, `act_1327826684720880` | dedicated token; read performance only |
| GA4 | account `NPD`, property `Ngọc Phương Đông` | property `251054384` | dedicated service account; property-level Viewer only |
| Social | primary Facebook Page `Ngọc Phương Đông` | Page `1148837305263525` | separate token; Page aggregate read only |

Meta Business portfolio: `Bat Dong San VN` (`142792211683682`). Google Cloud project selected for the GA4 identity: `n8n-automation-499210` (`230976622228`). The Analytics Data API was disabled and the project had no service accounts at audit time.

## Names and destinations

- Meta Ads system user: `npd-agent-hub-ads-readonly`
- Meta social system user: `npd-agent-hub-social-readonly`
- Meta app: use the approved business app only to mint two separate, narrowly scoped tokens; do not reuse the lead-ingestion token.
- GA4 service account: `npd-agent-hub-ga4-readonly@n8n-automation-499210.iam.gserviceaccount.com`
- VPS environment: `/etc/npd-ai/agent-hub.env`, mode `600`
- GA4 key on VPS: `/etc/npd-ai/ga4-agent-hub-readonly.json`, mode `600`, bind-mounted read-only at `/run/secrets/ga4-service-account.json`

Never paste token/key values into chat, issues, pull requests, logs, shell history or Git.

## Required access

### Meta Ads

Assign only `Bat Dong San 1` and `Bat Dong San 4` to the Ads identity with the minimum performance-view access accepted by Meta. Generate a token containing only the read permission required by the Insights GET used by Agent Hub. Do not grant campaign management, billing, audience management, lead retrieval, Page publishing or messaging permissions.

Production variables:

```text
META_ADS_ACCOUNT_ID=556651439430505,1327826684720880
META_ADS_ACCESS_TOKEN=<dedicated secret>
META_GRAPH_VERSION=<explicit supported version>
```

### GA4

Enable `analyticsdata.googleapis.com` in `n8n-automation-499210`. Create the dedicated service account without project IAM roles, create one JSON key, and add only its email to GA4 property `251054384` as `Viewer` at property level. Do not grant account-level access, Editor, Marketer or Administrator.

Production variables/mount:

```text
GA4_PROPERTY_ID=251054384
GA4_SERVICE_ACCOUNT_FILE=/run/secrets/ga4-service-account.json
GA4_SERVICE_ACCOUNT_HOST_FILE=/etc/npd-ai/ga4-agent-hub-readonly.json
```

The application requests only `https://www.googleapis.com/auth/analytics.readonly` and calls `runReport`.

### Social

Assign only Page `Ngọc Phương Đông` to the social identity with the minimum Page insights/engagement view access accepted by Meta. The credential must be different from the Ads token and the lead-ingestion token. Agent Hub requests Page name/follower/fan counts and aggregate reaction/comment/share counts only; it does not request post text or messages.

Production variables:

```text
SOCIAL_META_PAGE_ID=1148837305263525
SOCIAL_META_ACCESS_TOKEN=<dedicated secret>
SOCIAL_META_GRAPH_VERSION=<explicit supported version>
SOCIAL_INSIGHTS_URL=
SOCIAL_INSIGHTS_TOKEN=
```

## Acceptance sequence

1. Record the pre-change Meta asset assignments, GA4 property access list, Cloud API state and Agent Hub source status without exposing secrets.
2. Create and assign each identity separately. Stop if the UI requires broader access than this runbook.
3. Transfer secrets directly to the VPS paths above, set ownership to `root:root` and mode `600`, then remove local download copies after VPS verification.
4. Run configuration validation. It must report `configured` for each complete source and `incomplete` for any partial credential set.
5. Redeploy Agent Hub only. Do not modify Caddy, n8n, Redis or the video services.
6. Run loopback and public read-only smoke. Confirm the three sources are `available`, no token appears in results/logs, and no write proposal was executed.
7. Verify the n8n executor remains blank/disabled, PR #9 remains draft/unmerged, and retain the prior Agent Hub image plus namespace backup for rollback.

If any source fails, clear only that source's production variables and redeploy. Do not widen its permissions as an automatic recovery step.

## Onboarding record (2026-08-20)

- Meta rejected creation of additional named system users in this Business portfolio. The existing Employee system user `Conversions API System User` (`61552256442538`) is therefore used only as the token issuer. Its assigned source assets are limited to `Xem hiệu quả` for Bat Dong San 1 and Bat Dong San 4, and `Thông tin chi tiết` for the Ngọc Phương Đông Page. Business Settings identifies the Ads assets as `23850639293630279` and `23853145021290221`; the Graph API resolves their canonical account IDs as `act_556651439430505` and `act_1327826684720880`, which are the IDs used by Agent Hub.
- The Ads credential is a new 60-day token from `NPD Comment` containing only `ads_read`. It is separate from the lead-ingestion token and stored at `/etc/npd-ai/agent-hub-meta-ads.token` with mode `600`.
- A temporary `Quản lý ứng dụng` assignment was tested because Meta did not expose Page permissions in the system-user token dialog. It did not resolve that limitation and was removed. The original partial app assignment (`Phát triển ứng dụng`, `Xem thông tin chi tiết`, `Thử nghiệm ứng dụng`) was restored and verified.
- The Social credential is a new Page access token derived from an OAuth grant restricted to Page `1148837305263525`. The grant contains `pages_show_list` and `pages_read_engagement`; `pages_manage_posts` is explicitly declined. The resulting Page token was verified against Page identity/follower counts and aggregate post edges, then stored at `/etc/npd-ai/agent-hub-social.token` with mode `600`.
- Service account `npd-agent-hub-ga4-readonly@n8n-automation-499210.iam.gserviceaccount.com` has no project IAM role and has property-level `Viewer` on GA4 property `251054384`. Analytics Data API is enabled. The first unrecoverable key was revoked; replacement key `d26f7b6788150813f43352d1d2486666b1fb176d` is the only active key and is stored at `/etc/npd-ai/ga4-agent-hub-readonly.json` with mode `600`. The local download was removed after remote validation.
- Graph API is pinned to `v26.0` for both Meta readers. No Ads mutation, Page publish, message, GA4 edit, CRM write or n8n executor enablement was performed.
