#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
BACKUP_DIR="${AGENT_HUB_CONFIG_BACKUP_DIR:-/var/backups/npd-agent-hub/config}"
APPLY=0
ROTATE=0

usage() {
  printf 'Usage: %s --apply [--rotate] [--env-file PATH] [--backup-dir PATH]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --rotate) ROTATE=1 ;;
    --env-file) shift; ENV_FILE="${1:?--env-file requires a path}" ;;
    --backup-dir) shift; BACKUP_DIR="${1:?--backup-dir requires a path}" ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'configure error: unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ "$APPLY" == "1" ]] || {
  printf 'configure error: --apply is required; no changes were made\n' >&2
  exit 2
}
[[ -f "$ENV_FILE" ]] || {
  printf 'configure error: env file not found: %s\n' "$ENV_FILE" >&2
  exit 2
}
command -v python3 >/dev/null 2>&1 || {
  printf 'configure error: python3 is required\n' >&2
  exit 2
}

umask 077
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$BACKUP_DIR"
backup_path="$BACKUP_DIR/agent-hub.env-$timestamp"
cp --preserve=mode,ownership,timestamps "$ENV_FILE" "$backup_path"

python3 - "$ENV_FILE" "$ROTATE" <<'PY'
import os
import re
import secrets
import stat
import sys
import tempfile

path = sys.argv[1]
rotate = sys.argv[2] == "1"
with open(path, encoding="utf-8") as handle:
    original = handle.read()

lines = original.splitlines()
positions: dict[str, int] = {}
values: dict[str, str] = {}
for index, line in enumerate(lines):
    match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
    if not match:
        continue
    key, value = match.groups()
    if key in positions:
        raise SystemExit(f"duplicate environment key: {key}")
    positions[key] = index
    values[key] = value.strip().strip("'\"")

receipt_key_name = "AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY"
receipt_key = values.get(receipt_key_name, "")
if rotate or len(receipt_key) < 32:
    receipt_key = secrets.token_hex(32)
if receipt_key == values.get("AGENT_SESSION_SIGNING_KEY", ""):
    raise SystemExit("attribution receipt key must differ from session signing key")

updates = {
    receipt_key_name: receipt_key,
    "AGENT_ATTRIBUTION_RECEIPT_KEY_ID": (
        values.get("AGENT_ATTRIBUTION_RECEIPT_KEY_ID") or "npd-attribution-v1"
    ),
    "AGENT_ATTRIBUTION_DELIVERY_MAX_ATTEMPTS": (
        values.get("AGENT_ATTRIBUTION_DELIVERY_MAX_ATTEMPTS") or "4"
    ),
    "AGENT_ATTRIBUTION_FRESHNESS_SLOS_JSON": (
        values.get("AGENT_ATTRIBUTION_FRESHNESS_SLOS_JSON")
        or '{"n8n_lead_intake":15,"meta_ads":1440,"ga4":1440,"espocrm":1440,"utm":60}'
    ),
}

for key, value in updates.items():
    rendered = (
        f"{key}='{value}'"
        if key == "AGENT_ATTRIBUTION_FRESHNESS_SLOS_JSON"
        else f"{key}={value}"
    )
    if key in positions:
        lines[positions[key]] = rendered
    else:
        lines.append(rendered)

mode = stat.S_IMODE(os.stat(path).st_mode)
directory = os.path.dirname(os.path.abspath(path))
fd, temporary = tempfile.mkstemp(prefix=".agent-hub.env.", dir=directory, text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY

printf 'attribution delivery config ready: env=%s backup=%s rotated=%s\n' \
  "$ENV_FILE" "$backup_path" "$ROTATE"
printf 'secret material was generated locally and was not printed\n'
