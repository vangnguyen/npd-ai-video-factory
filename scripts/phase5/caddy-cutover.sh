#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="${PHASE5_CADDY_TEMPLATE:-$ROOT_DIR/deploy/phase5/Caddyfile.agent-hub.example}"
CADDYFILE="${N8N_CADDYFILE:-/opt/n8n/Caddyfile}"
CADDY_CONTAINER="${N8N_CADDY_CONTAINER:-n8n-marketing-caddy-1}"
BACKUP_DIR="${N8N_CADDY_BACKUP_DIR:-/opt/n8n}"
TIMESTAMP="${PHASE5_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
ACTION="apply"
BACKUP=""
SAFETY_BACKUP=""
CONFIRM=""

fail() {
  printf 'caddy cutover error: %s\n' "$*" >&2
  exit 2
}

usage() {
  cat >&2 <<'EOF'
Usage:
  AGENT_HUB_HOSTNAME=host.example.com bash scripts/phase5/caddy-cutover.sh \
    --apply --confirm APPLY_CADDY
  bash scripts/phase5/caddy-cutover.sh \
    --rollback /opt/n8n/Caddyfile.before-agent-hub-<timestamp> \
    --confirm ROLLBACK_CADDY

Both paths validate the candidate in n8n-marketing-caddy-1 before changing the
bind-mounted host file. The host file is updated in place to preserve its inode.
EOF
  exit 2
}

while (($#)); do
  case "$1" in
    --apply) ACTION="apply"; shift ;;
    --rollback) ACTION="rollback"; BACKUP="${2:-}"; shift 2 ;;
    --confirm) CONFIRM="${2:-}"; shift 2 ;;
    *) usage ;;
  esac
done

[[ -f "$CADDYFILE" ]] || fail "Caddyfile not found: $CADDYFILE"
[[ -w "$CADDYFILE" ]] || fail "Caddyfile is not writable: $CADDYFILE"
docker inspect "$CADDY_CONTAINER" >/dev/null 2>&1 || fail "Caddy container not found: $CADDY_CONTAINER"
[[ "$(docker inspect -f '{{.State.Running}}' "$CADDY_CONTAINER")" == "true" ]] \
  || fail "Caddy container is not running: $CADDY_CONTAINER"

workdir="$(mktemp -d)"
container_candidate="/tmp/npd-agent-hub-caddy-$TIMESTAMP"
cleanup() {
  docker exec "$CADDY_CONTAINER" rm -f "$container_candidate" >/dev/null 2>&1 || true
  rm -rf "$workdir"
}
trap cleanup EXIT

candidate="$workdir/Caddyfile.candidate"
if [[ "$ACTION" == "apply" ]]; then
  [[ "$CONFIRM" == "APPLY_CADDY" ]] || fail "literal confirmation APPLY_CADDY is required"
  [[ -f "$TEMPLATE" ]] || fail "Caddy template not found: $TEMPLATE"
  hostname="${AGENT_HUB_HOSTNAME:-}"
  [[ "$hostname" =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
    || fail "AGENT_HUB_HOSTNAME must be a bare DNS hostname"
  [[ "$hostname" != *example.invalid ]] || fail "placeholder hostname is not allowed"
  if grep -Fq '# BEGIN NPD AGENT HUB PHASE 5' "$CADDYFILE"; then
    fail "managed Agent Hub block already exists; review it manually instead of appending a duplicate"
  fi
  if grep -Fq "$hostname" "$CADDYFILE"; then
    fail "hostname already exists in Caddyfile: $hostname"
  fi
  cp "$CADDYFILE" "$candidate"
  printf '\n' >> "$candidate"
  sed "s/agent-hub\.example\.invalid/$hostname/g" "$TEMPLATE" >> "$candidate"
  BACKUP="$BACKUP_DIR/Caddyfile.before-agent-hub-$TIMESTAMP"
  SAFETY_BACKUP="$BACKUP"
else
  [[ "$CONFIRM" == "ROLLBACK_CADDY" ]] || fail "literal confirmation ROLLBACK_CADDY is required"
  [[ -n "$BACKUP" && -f "$BACKUP" ]] || fail "Caddy backup not found: $BACKUP"
  cp "$BACKUP" "$candidate"
  SAFETY_BACKUP="$BACKUP_DIR/Caddyfile.before-agent-hub-rollback-$TIMESTAMP"
fi

docker cp "$candidate" "$CADDY_CONTAINER:$container_candidate"
docker exec "$CADDY_CONTAINER" caddy fmt --overwrite "$container_candidate"
docker exec "$CADDY_CONTAINER" caddy validate --config "$container_candidate" --adapter caddyfile
docker cp "$CADDY_CONTAINER:$container_candidate" "$candidate"

mkdir -p "$BACKUP_DIR"
[[ ! -e "$SAFETY_BACKUP" ]] || fail "refusing to overwrite Caddy backup: $SAFETY_BACKUP"
cp -a "$CADDYFILE" "$SAFETY_BACKUP"
chmod 600 "$SAFETY_BACKUP"

cat "$candidate" > "$CADDYFILE"
if ! docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile \
  || ! docker exec "$CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile; then
  if [[ -f "$SAFETY_BACKUP" ]]; then
    printf 'Caddy %s failed; restoring %s in place\n' "$ACTION" "$SAFETY_BACKUP" >&2
    cat "$SAFETY_BACKUP" > "$CADDYFILE"
    docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile >/dev/null
    docker exec "$CADDY_CONTAINER" caddy reload --config /etc/caddy/Caddyfile >/dev/null
  fi
  fail "Caddy validate/reload failed"
fi

printf 'caddy %s ok: container=%s caddyfile=%s backup=%s\n' \
  "$ACTION" "$CADDY_CONTAINER" "$CADDYFILE" "$SAFETY_BACKUP"
