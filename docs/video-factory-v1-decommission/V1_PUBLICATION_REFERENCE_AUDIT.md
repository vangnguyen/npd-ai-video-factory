# V1 publication and artifact reference audit

Status: **resolved conservatively; owner acceptance pending**

AH-01C refreshed the repository/local evidence and queried the accepted production topology using
read-only operations. No post, workflow, job, Redis key, file, route or configuration was changed.
No credential, raw business payload or private media was retained in evidence.

## Search boundary and findings

The exact 12 retained V1 job IDs plus the public port, job API, renderer media and `final.mp4`
fragments were checked across:

| Source | Coverage | Matches |
|---|---:|---:|
| V1 Redis DB0 | 12 job records; queue and processing both empty | 12 canonical job records; zero publication fields |
| V1 public read routes | 12 status routes; one-byte range probe only for media | 12 status routes and seven final videos still live |
| Public WordPress REST | 16 discovered bases; 10 public collections; 4,320 objects including 3,919 media items | 0 |
| Primary Facebook Page `1148837305263525` | 96 published posts, 96 feed objects and 35 videos since 13/08/2026 | 0 |
| Production n8n | 11 workflows, seven history versions and 1,373 executions since 13/08/2026 | 0 |
| Agent Hub Redis DB1 | 6,483 namespace keys and all supported values | 0 |
| Content publisher durable state | 2,320 string values | 0 |
| Repository, storage manifest and V3 owner-review lineage | 194 storage files plus owner-review sources | One known V3 lineage to `vid_1786695599261_60dbfd66ed` |

The detailed safe aggregates are in
[`v1-publication-reference-evidence.json`](v1-publication-reference-evidence.json). The public
WordPress scan is reproducible with
[`audit_wordpress_public.py`](../../scripts/ops/v1_publication_audit/audit_wordpress_public.py).

## Resolution policy

Point-in-time absence cannot prove that an operator never copied a link into a private message or
an undeclared system. AH-01C therefore does not classify any job as deletable by absence:

- the V3 source job is `ACTIVE_REFERENCE`;
- the other 11 jobs are `ARCHIVE_REQUIRED`, including five failed/partial jobs;
- live status, artifact and renderer-media route families are `REDIRECT_REQUIRED`; and
- the inactive n8n Sprint 1 fixture is `SAFE_TO_RETIRE` only under a future n8n-owner gate.

Any late-discovered reference automatically becomes `ARCHIVE_REQUIRED`; any live legacy URL becomes
`REDIRECT_REQUIRED`. The machine-readable
[`v1-publication-reference-catalog.json`](v1-publication-reference-catalog.json) therefore has zero
`UNKNOWN` without granting deletion or shutdown authority.

## Limitations and gate

Anonymous WordPress REST cannot enumerate private drafts/design templates, and only the primary
Facebook Page in the accepted topology was queried. Those limitations are absorbed by the
archive/redirect fallback instead of being treated as proof of absence.

The owner must accept the catalog, and it must be refreshed immediately before AH-03. Until the
compatibility redirects, backup custody, Redis migration, telemetry observation and final snapshot
gates pass, all V1 artifact routes and stored media remain protected from removal.
