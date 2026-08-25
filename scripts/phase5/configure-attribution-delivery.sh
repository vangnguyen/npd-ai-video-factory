#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${AGENT_HUB_ENV_FILE:-/etc/npd-ai/agent-hub.env}"
BACKUP_DIR="${AGENT_HUB_CONFIG_BACKUP_DIR:-/var/backups/npd-agent-hub/config}"
APPLY=0
ROTATE=0
NEW_KEY_ID=""

usage() {
  printf 'Usage: %s --apply [--rotate --new-key-id KEY_ID] [--env-file PATH] [--backup-dir PATH]\n' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply) APPLY=1 ;;
    --rotate) ROTATE=1 ;;
    --new-key-id) shift; NEW_KEY_ID="${1:?--new-key-id requires a value}" ;;
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
if [[ "$ROTATE" == "1" && -z "$NEW_KEY_ID" ]]; then
  printf 'configure error: --rotate requires --new-key-id\n' >&2
  exit 2
fi
if [[ "$ROTATE" == "0" && -n "$NEW_KEY_ID" ]]; then
  printf 'configure error: --new-key-id is only valid with --rotate\n' >&2
  exit 2
fi
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

python3 - "$ENV_FILE" "$ROTATE" "$NEW_KEY_ID" "$BACKUP_DIR" "$timestamp" <<'PY'
import json
import os
import re
import secrets
import shutil
import stat
import sys
import tempfile

path, rotate_raw, new_key_id, backup_dir, timestamp = sys.argv[1:]
rotate = rotate_raw == "1"
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

active_key = (
    values.get("AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY")
    or values.get("AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY")
    or ""
)
active_key_id = (
    values.get("AGENT_ATTRIBUTION_ACTIVE_KEY_ID")
    or values.get("AGENT_ATTRIBUTION_RECEIPT_KEY_ID")
    or "npd-attribution-v1"
)
host_keyring_path = (
    values.get("AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE")
    or "/etc/npd-ai/agent-attribution-verification-keys.json"
)
container_keyring_path = (
    values.get("AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE")
    or "/run/secrets/agent-attribution-verification-keys.json"
)

key_id_pattern = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,79}$")
if not key_id_pattern.fullmatch(active_key_id):
    raise SystemExit("active attribution key_id is invalid")
if active_key and len(active_key) < 32:
    raise SystemExit("active attribution signing key must be at least 32 characters")

historical: dict[str, str] = {}
if os.path.exists(host_keyring_path):
    with open(host_keyring_path, encoding="utf-8") as handle:
        historical = json.load(handle)
    if not isinstance(historical, dict):
        raise SystemExit("historical verification key file must contain a JSON object")
    backup_keyring = os.path.join(
        backup_dir, f"agent-attribution-verification-keys-{timestamp}.json"
    )
    shutil.copy2(host_keyring_path, backup_keyring)
    os.chmod(backup_keyring, 0o600)

for key_id, key in historical.items():
    if not isinstance(key_id, str) or not key_id_pattern.fullmatch(key_id):
        raise SystemExit("historical verification key_id is invalid")
    if not isinstance(key, str) or len(key) < 32:
        raise SystemExit("historical verification key is invalid")

if rotate:
    if len(active_key) < 32:
        raise SystemExit("cannot rotate before an active key is configured")
    if not key_id_pattern.fullmatch(new_key_id):
        raise SystemExit("new attribution key_id is invalid")
    if new_key_id == active_key_id or new_key_id in historical:
        raise SystemExit("new attribution key_id must be unused")
    if active_key_id in historical:
        raise SystemExit("active key_id must not already be historical")
    historical[active_key_id] = active_key
    active_key_id = new_key_id
    active_key = secrets.token_hex(32)
elif len(active_key) < 32:
    active_key = secrets.token_hex(32)

if active_key == values.get("AGENT_SESSION_SIGNING_KEY", ""):
    raise SystemExit("attribution receipt key must differ from session signing key")
if active_key_id in historical:
    raise SystemExit("active key_id must not appear in the historical keyring")

updates = {
    "AGENT_ATTRIBUTION_ACTIVE_SIGNING_KEY": active_key,
    "AGENT_ATTRIBUTION_ACTIVE_KEY_ID": active_key_id,
    "AGENT_ATTRIBUTION_VERIFICATION_KEYS_HOST_FILE": host_keyring_path,
    "AGENT_ATTRIBUTION_VERIFICATION_KEYS_FILE": container_keyring_path,
    # Keep legacy aliases synchronized for a rollback to the pre-keyring image.
    "AGENT_ATTRIBUTION_RECEIPT_SIGNING_KEY": active_key,
    "AGENT_ATTRIBUTION_RECEIPT_KEY_ID": active_key_id,
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


def atomic_write(target: str, content: str, mode: int) -> None:
    directory = os.path.dirname(os.path.abspath(target))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".npd-attribution.", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


env_mode = stat.S_IMODE(os.stat(path).st_mode)
atomic_write(path, "\n".join(lines) + "\n", env_mode)
atomic_write(
    host_keyring_path,
    json.dumps(historical, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    0o600,
)
PY

printf 'attribution delivery config ready: env=%s backup=%s rotated=%s active_key_id=%s\n' \
  "$ENV_FILE" "$backup_path" "$ROTATE" "${NEW_KEY_ID:-preserved}"
printf 'secret material was generated locally and was not printed\n'
