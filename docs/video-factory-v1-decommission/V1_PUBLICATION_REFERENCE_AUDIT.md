# V1 publication and artifact reference audit

Status: **partial; external catalog coverage unresolved**

This audit searched available repository, local owner-review and production n8n evidence without
publishing, authenticating to an external social/CMS account, reading a secret, or changing a
workflow.

## Results

| Scope | Result |
|---|---|
| Repository source/docs/tests | V1 API/artifact routes exist as implementation, fixtures and legacy documentation; these are not publication records. |
| Local V3 owner-review workspace | V1 job `vid_1786695599261_60dbfd66ed` is referenced as the source job in the V3 generation manifest and assembly tooling. |
| Renderer owner-review call | `vid_1787989200000_a1b2c3d4e5` is an ad hoc render ID for the V3 package, not a DB0 V1 publication record. |
| Production n8n workflows | One route reference: inactive `NPD AI Video Factory - Sprint 1 Smoke Test`; zero concrete `vid_17866*` IDs and zero public `:8000`/`:3001` URL references in workflow definitions. |
| Production n8n executions | AH-01 found zero retained executions for the inactive V1 workflow. |
| V1 schema/Redis | No publication destination, post ID, public URL or analytics fields. |
| Authorized CMS/social catalog | Not available within AH-01B scope; absence was not assumed. |

The known V3 lineage means job `vid_1786695599261_60dbfd66ed` and its retained artifacts must stay
through the V3 owner-review and V1 archive windows. It is not evidence that the video was published.

## Remaining acceptance work

The business owner must authorize and identify the canonical inventories to search, including any
WordPress media/posts, social posts, Drive/shared links, CRM attachments and operator handoff
catalogs. For each retained V1 job ID and artifact URL/path, record the external object, owner,
visibility, last access/use, retention requirement and redirect/archive decision.

No V1 artifact route or stored media may be removed until the external catalog result is accepted.
`v1-publication-reference-catalog` therefore remains `UNKNOWN`.
