#!/usr/bin/env python3
"""Audit public WordPress REST collections for legacy Video Factory references."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "npd-ah01c-readonly-audit/1.0"
MAX_PAGES_PER_COLLECTION = 500


class AuditError(RuntimeError):
    pass


def fetch_json(url: str) -> tuple[Any, dict[str, str]]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode("utf-8")), {key.lower(): value for key, value in response.headers.items()}


def safe_record(item: Any, *, rest_base: str, needles: list[str], raw: str) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"rest_base": rest_base, "id": None, "matched_needles": needles}
    guid = item.get("guid")
    guid_link = guid.get("rendered") if isinstance(guid, dict) else None
    link = item.get("link") or item.get("source_url") or guid_link
    return {
        "rest_base": rest_base,
        "id": item.get("id"),
        "status": item.get("status"),
        "modified": item.get("modified_gmt") or item.get("modified"),
        "public_reference": link if isinstance(link, str) else None,
        "matched_needles": sorted(needle for needle in needles if needle.casefold() in raw.casefold()),
    }


def audit_collection(api_root: str, rest_base: str, needles: list[str]) -> dict[str, Any]:
    item_count = 0
    matches: list[dict[str, Any]] = []
    page = 1
    total_pages: int | None = None
    while page <= MAX_PAGES_PER_COLLECTION:
        query = urlencode({"context": "view", "per_page": 100, "page": page})
        url = urljoin(api_root, f"{rest_base}?{query}")
        try:
            payload, headers = fetch_json(url)
        except HTTPError as exc:
            if page == 1:
                return {
                    "rest_base": rest_base,
                    "access": "UNAVAILABLE_PUBLICLY",
                    "http_status": exc.code,
                    "item_count": 0,
                    "matches": [],
                }
            if exc.code == 400:
                break
            raise
        if not isinstance(payload, list):
            return {
                "rest_base": rest_base,
                "access": "NON_COLLECTION_RESPONSE",
                "http_status": 200,
                "item_count": item_count,
                "matches": matches,
            }
        if total_pages is None:
            total_pages = int(headers.get("x-wp-totalpages", "1"))
        for item in payload:
            raw = json.dumps(item, ensure_ascii=False, sort_keys=True)
            matched = [needle for needle in needles if needle.casefold() in raw.casefold()]
            if matched:
                matches.append(safe_record(item, rest_base=rest_base, needles=matched, raw=raw))
        item_count += len(payload)
        if page >= total_pages or not payload:
            break
        page += 1
    if page > MAX_PAGES_PER_COLLECTION:
        raise AuditError(f"collection page cap exceeded: {rest_base}")
    return {
        "rest_base": rest_base,
        "access": "PUBLIC_READ",
        "http_status": 200,
        "item_count": item_count,
        "page_count": page,
        "matches": matches,
    }


def audit(base_url: str, needles: list[str]) -> dict[str, Any]:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise AuditError("base URL must be an absolute HTTPS URL")
    canonical_base = f"{parsed.scheme}://{parsed.netloc}/"
    api_root = urljoin(canonical_base, "wp-json/wp/v2/")
    types, _ = fetch_json(urljoin(api_root, "types?context=view"))
    if not isinstance(types, dict):
        raise AuditError("WordPress types endpoint did not return an object")

    rest_bases: dict[str, list[str]] = {}
    skipped_templates: list[str] = []
    for type_name, descriptor in types.items():
        rest_base = descriptor.get("rest_base") if isinstance(descriptor, dict) else None
        if not isinstance(rest_base, str) or not rest_base:
            continue
        if "(?P<" in rest_base:
            skipped_templates.append(rest_base)
            continue
        rest_bases.setdefault(rest_base, []).append(str(type_name))

    collections: list[dict[str, Any]] = []
    for rest_base in sorted(rest_bases):
        result = audit_collection(api_root, rest_base, needles)
        result["wordpress_types"] = sorted(rest_bases[rest_base])
        collections.append(result)

    accessible = [item for item in collections if item["access"] == "PUBLIC_READ"]
    matches = [match for item in accessible for match in item["matches"]]
    video_media = next((item for item in collections if item["rest_base"] == "media"), None)
    return {
        "schema_version": "1.0",
        "scope": "public_wordpress_reference_audit",
        "status": "PASS",
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base_url": canonical_base,
        "api_root": api_root,
        "authentication_used": False,
        "write_performed": False,
        "needles": needles,
        "summary": {
            "discovered_rest_bases": len(rest_bases),
            "public_collections": len(accessible),
            "non_public_collections": len(collections) - len(accessible),
            "public_items_scanned": sum(item["item_count"] for item in accessible),
            "matched_objects": len(matches),
            "media_items_scanned": video_media["item_count"] if video_media else 0,
        },
        "collections": collections,
        "matches": matches,
        "templated_routes_not_collection_scanned": sorted(skipped_templates),
        "limitations": [
            "Only data exposed by anonymous WordPress REST context=view was read.",
            "Private drafts, private attachments and non-WordPress systems require separate inventory evidence.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--needle", action="append", required=True)
    args = parser.parse_args()
    try:
        report = audit(args.base_url, args.needle)
    except (AuditError, HTTPError, URLError, json.JSONDecodeError, OSError, ValueError) as exc:
        sys.stderr.write(f"WordPress audit failed: {exc}\n")
        return 2
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
