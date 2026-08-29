#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
BASE_COMPOSE="${PHASE5_COMPOSE_FILE:-$ROOT_DIR/deploy/phase5/docker-compose.agent-hub.prod.yml}"
V1_COMPOSE="${V1_COMPOSE_FILE:-$ROOT_DIR/docker-compose.yml}"
V1_NETWORK="${NPD_DOCKER_NETWORK:-npd-ai-video-factory_default}"
EXPECTED_COMMIT=""
RECIPIENT_FILE=""
OUTPUT_FILE=""
CONFIRM=""

usage() {
  printf 'Usage: bash scripts/ops/agent_hub_redis/ah_r01_export_encrypted.sh --expected-commit <sha> --recipient-file <age-recipients> --output <absolute.age> --confirm EXPORT_AH_R01_DB1_ENCRYPTED\n' >&2
  exit 2
}

while (($#)); do
  case "$1" in
    --expected-commit) EXPECTED_COMMIT="${2:-}"; shift 2 ;;
    --recipient-file) RECIPIENT_FILE="${2:-}"; shift 2 ;;
    --output) OUTPUT_FILE="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ "$CONFIRM" == "EXPORT_AH_R01_DB1_ENCRYPTED" ]] || usage
[[ "$EXPECTED_COMMIT" =~ ^[0-9a-f]{40}$ ]] || usage
[[ "$(git -C "$ROOT_DIR" rev-parse HEAD)" == "$EXPECTED_COMMIT" ]] \
  || { printf 'AH-R01 export error: repository commit mismatch\n' >&2; exit 2; }
git -C "$ROOT_DIR" diff --quiet \
  || { printf 'AH-R01 export error: tracked tree is dirty\n' >&2; exit 2; }
git -C "$ROOT_DIR" diff --cached --quiet \
  || { printf 'AH-R01 export error: staged tree is dirty\n' >&2; exit 2; }
command -v age >/dev/null 2>&1 \
  || { printf 'AH-R01 export error: age is unavailable\n' >&2; exit 2; }
[[ "$RECIPIENT_FILE" == /* && -f "$RECIPIENT_FILE" ]] \
  || { printf 'AH-R01 export error: recipient file must be absolute\n' >&2; exit 2; }
[[ "$OUTPUT_FILE" == /* && "$OUTPUT_FILE" == *.age ]] \
  || { printf 'AH-R01 export error: output must be an absolute .age path\n' >&2; exit 2; }
[[ "$(basename "$OUTPUT_FILE")" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{2,180}\.age$ ]] \
  || { printf 'AH-R01 export error: output filename is invalid\n' >&2; exit 2; }
resolved_recipient="$(realpath "$RECIPIENT_FILE")"
resolved_output_dir="$(realpath "$(dirname "$OUTPUT_FILE")")"
case "$resolved_recipient" in "$ROOT_DIR"|"$ROOT_DIR"/*) printf 'AH-R01 export error: recipient custody must be outside Git\n' >&2; exit 2 ;; esac
case "$resolved_output_dir" in "$ROOT_DIR"|"$ROOT_DIR"/*) printf 'AH-R01 export error: encrypted backup must be outside Git\n' >&2; exit 2 ;; esac
for candidate in \
  "$OUTPUT_FILE" \
  "$OUTPUT_FILE.sha256" \
  "$OUTPUT_FILE.source-before.json" \
  "$OUTPUT_FILE.source-after.json" \
  "$OUTPUT_FILE.receipt.json"; do
  [[ ! -e "$candidate" ]] \
    || { printf 'AH-R01 export error: an output evidence file already exists\n' >&2; exit 2; }
done
age --encrypt --recipients-file "$resolved_recipient" /dev/null >/dev/null \
  || { printf 'AH-R01 export error: age recipient file is invalid\n' >&2; exit 2; }

v1_redis_before="$(docker compose -f "$V1_COMPOSE" ps -q redis)"
agent_hub_before="$(docker compose -f "$BASE_COMPOSE" ps -q agent-hub)"
[[ -n "$v1_redis_before" && -n "$agent_hub_before" ]] \
  || { printf 'AH-R01 export error: source services are not running\n' >&2; exit 2; }
current_url="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$agent_hub_before" \
  | sed -n 's/^AGENT_REDIS_URL=//p' | tail -n 1)"
[[ "$current_url" == "redis://redis:6379/1" ]] \
  || { printf 'AH-R01 export error: Agent Hub source is not V1 Redis DB1\n' >&2; exit 2; }

maintenance_image="npd-agent-hub:ah-r01-maintenance-${EXPECTED_COMMIT:0:12}"
docker build --tag "$maintenance_image" \
  --file "$ROOT_DIR/services/agent_hub/Dockerfile" "$ROOT_DIR" >/dev/null
maintenance_image_id="$(docker image inspect "$maintenance_image" --format '{{.Id}}')"

source_snapshot() {
  docker run --rm --read-only --tmpfs /tmp:mode=0700 --cap-drop ALL \
    --network "$V1_NETWORK" \
    --env AGENT_STORE_BACKEND=redis \
    --env AGENT_REDIS_URL=redis://redis:6379/1 \
    --env AGENT_STORE_NAMESPACE=npd:agent-hub:v1 \
    "$maintenance_image" \
    python -m npd_agent_hub.redis_source_snapshot --require-exclusive-namespace
}
source_before_json="$(source_snapshot)"

partial_file="$resolved_output_dir/.ah-r01-$(basename "$OUTPUT_FILE").partial-$$"
cleanup_partial() { rm -f -- "$partial_file"; }
trap cleanup_partial EXIT

docker run --rm --read-only --tmpfs /tmp:mode=0700 --cap-drop ALL \
  --network "$V1_NETWORK" \
  --env AGENT_STORE_BACKEND=redis \
  --env AGENT_REDIS_URL=redis://redis:6379/1 \
  --env AGENT_STORE_NAMESPACE=npd:agent-hub:v1 \
  "$maintenance_image" \
  python -m npd_agent_hub.maintenance backup --output - \
  | age --encrypt --recipients-file "$resolved_recipient" --output "$partial_file"
[[ -s "$partial_file" ]] \
  || { printf 'AH-R01 export error: encrypted output is empty\n' >&2; exit 3; }
source_after_json="$(source_snapshot)"
chmod 600 "$partial_file"
mv -- "$partial_file" "$OUTPUT_FILE"
sha256sum "$OUTPUT_FILE" > "$OUTPUT_FILE.sha256"
printf '%s\n' "$source_before_json" > "$OUTPUT_FILE.source-before.json"
printf '%s\n' "$source_after_json" > "$OUTPUT_FILE.source-after.json"
chmod 600 "$OUTPUT_FILE" "$OUTPUT_FILE.sha256" \
  "$OUTPUT_FILE.source-before.json" "$OUTPUT_FILE.source-after.json"

v1_redis_after="$(docker compose -f "$V1_COMPOSE" ps -q redis)"
agent_hub_after="$(docker compose -f "$BASE_COMPOSE" ps -q agent-hub)"
[[ "$v1_redis_after" == "$v1_redis_before" && "$agent_hub_after" == "$agent_hub_before" ]] \
  || { printf 'AH-R01 export error: source service identity changed\n' >&2; exit 3; }

cipher_sha256="$(sha256sum "$OUTPUT_FILE" | awk '{print $1}')"
cipher_bytes="$(stat -c '%s' "$OUTPUT_FILE")"
receipt_file="$OUTPUT_FILE.receipt.json"
created_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
python3 - \
  "$receipt_file" \
  "$OUTPUT_FILE.source-before.json" \
  "$OUTPUT_FILE.source-after.json" <<PY
import json
from pathlib import Path
import sys

source_before = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
source_after = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))

payload = {
    "schema_version": "1.0",
    "status": "PASS",
    "change_id": "AH-R01-M2-EXPORT",
    "created_at": "$created_at",
    "git_commit": "$EXPECTED_COMMIT",
    "maintenance_image_id": "$maintenance_image_id",
    "source": "v1-redis-db1-agent-hub-namespace-only",
    "source_redis_container_id": "$v1_redis_before",
    "agent_hub_container_id": "$agent_hub_before",
    "source_before": source_before,
    "source_after": source_after,
    "cipher_sha256": "$cipher_sha256",
    "cipher_bytes": int("$cipher_bytes"),
    "plaintext_written_to_disk": False,
    "production_read_performed": True,
    "production_write_performed": False,
    "agent_hub_container_unchanged": True,
    "v1_redis_container_unchanged": True,
    "restore_rehearsal_performed": False,
    "cutover_performed": False,
    "ah03_authorized": False,
}
Path(sys.argv[1]).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
chmod 600 "$receipt_file"
trap - EXIT
printf 'AH-R01 encrypted export PASS: cipher_bytes=%s plaintext_on_disk=false production_write=false restore_rehearsal=false cutover=false\n' \
  "$cipher_bytes"
