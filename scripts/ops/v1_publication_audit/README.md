# V1 publication reference audit tooling

`audit_wordpress_public.py` enumerates every anonymously readable WordPress REST collection and
searches its public JSON representation for exact legacy job IDs and route fragments. It sends no
credentials and performs no write. Its report contains only counts, matching object identifiers,
public links and the matched search terms; it does not retain page bodies.

This is one evidence source, not a universal proof of absence. Private CMS objects, social
platforms, Agent Hub, n8n, repository/local manifests and any owner-maintained publication ledger
must be covered separately. When absence cannot be proven, the safe disposition is
`ARCHIVE_REQUIRED` or `REDIRECT_REQUIRED`, never deletion by assumption.
