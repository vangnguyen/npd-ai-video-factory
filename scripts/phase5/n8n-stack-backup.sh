#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

STACK_ROOT="${N8N_STACK_ROOT:-/opt/n8n}"
COMPOSE_FILE="${N8N_COMPOSE_FILE:-$STACK_ROOT/docker-compose.yml}"
COMPOSE_PROJECT="${N8N_COMPOSE_PROJECT:-n8n-marketing}"
BACKUP_ROOT="${N8N_BACKUP_ROOT:-$STACK_ROOT/backups}"
RETENTION_DAYS="${N8N_BACKUP_RETENTION_DAYS:-14}"
TIMESTAMP="${N8N_BACKUP_TIMESTAMP:-$(date +%Y-%m-%d_%H-%M-%S)}"
LOCK_FILE="${N8N_BACKUP_LOCK_FILE:-$BACKUP_ROOT/.backup.lock}"

fail() {
  printf 'n8n backup error: %s\n' "$*" >&2
  exit 2
}

for command in docker gzip tar sha256sum flock realpath find; do
  command -v "$command" >/dev/null 2>&1 || fail "$command is required"
done

[[ "$STACK_ROOT" == /* ]] || fail "N8N_STACK_ROOT must be absolute"
[[ "$BACKUP_ROOT" == /* ]] || fail "N8N_BACKUP_ROOT must be absolute"
[[ "$BACKUP_ROOT" != "/" && "$BACKUP_ROOT" != "$STACK_ROOT" ]] \
  || fail "refusing unsafe backup root: $BACKUP_ROOT"
[[ "$RETENTION_DAYS" =~ ^[0-9]+$ ]] || fail "retention days must be numeric"
[[ "$TIMESTAMP" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}-[0-9]{2}-[0-9]{2}$ ]] \
  || fail "timestamp has an unsupported format"
[[ -f "$COMPOSE_FILE" ]] || fail "Compose file not found: $COMPOSE_FILE"

mkdir -p "$BACKUP_ROOT"
backup_root_abs="$(realpath "$BACKUP_ROOT")"
stack_root_abs="$(realpath "$STACK_ROOT")"
[[ "$backup_root_abs" == "$stack_root_abs"/* ]] \
  || fail "backup root must remain below the n8n stack root"

exec 9>"$LOCK_FILE"
flock -n 9 || fail "another n8n backup is already running"

partial_dir="$backup_root_abs/.partial-$TIMESTAMP-$$"
final_dir="$backup_root_abs/$TIMESTAMP"
[[ ! -e "$partial_dir" && ! -e "$final_dir" ]] \
  || fail "backup destination already exists"
mkdir -m 700 "$partial_dir"

cleanup_partial() {
  exit_code=$?
  if [[ $exit_code -ne 0 && -d "$partial_dir" ]]; then
    rm -rf -- "$partial_dir"
  fi
  exit "$exit_code"
}
trap cleanup_partial EXIT

compose() {
  docker compose -p "$COMPOSE_PROJECT" -f "$COMPOSE_FILE" "$@"
}

running_container() {
  local service="$1"
  local container_id
  container_id="$(compose ps -q --status running "$service")"
  [[ -n "$container_id" ]] || fail "service is not running: $service"
  printf '%s\n' "$container_id"
}

volume_for_destination() {
  local container_id="$1"
  local destination="$2"
  local volume_name
  volume_name="$(docker inspect "$container_id" --format \
    "{{range .Mounts}}{{if and (eq .Type \"volume\") (eq .Destination \"$destination\")}}{{println .Name}}{{end}}{{end}}")"
  volume_name="${volume_name//$'\r'/}"
  volume_name="${volume_name//$'\n'/}"
  [[ "$volume_name" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] \
    || fail "no safe named volume found for $destination"
  printf '%s\n' "$volume_name"
}

archive_volume() {
  local volume_name="$1"
  local output_name="$2"
  docker run --rm \
    -v "$volume_name:/data:ro" \
    -v "$partial_dir:/backup" \
    alpine:3.20 \
    tar -czf "/backup/$output_name" -C /data .
}

postgres_id="$(running_container postgres)"
docker exec "$postgres_id" sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' </dev/null \
  | gzip -c > "$partial_dir/postgres.sql.gz"

n8n_id="$(running_container n8n)"
n8n_volume="$(volume_for_destination "$n8n_id" /home/node/.n8n)"
archive_volume "$n8n_volume" n8n_data.tar.gz

espocrm_db_id="$(compose ps -q --status running espocrm-db)"
if [[ -n "$espocrm_db_id" ]]; then
  docker exec "$espocrm_db_id" sh -ec \
    'export MYSQL_PWD="$MARIADB_PASSWORD"; exec mariadb-dump -u "$MARIADB_USER" --single-transaction --quick "$MARIADB_DATABASE"' \
    </dev/null | gzip -c > "$partial_dir/espocrm.sql.gz"

  espocrm_id="$(running_container espocrm)"
  archive_volume "$(volume_for_destination "$espocrm_id" /var/www/html/data)" espocrm_data.tar.gz
  archive_volume "$(volume_for_destination "$espocrm_id" /var/www/html/custom)" espocrm_custom.tar.gz
  archive_volume "$(volume_for_destination "$espocrm_id" /var/www/html/client/custom)" espocrm_custom_client.tar.gz
fi

config_inputs=()
for item in docker-compose.yml Caddyfile backup.sh .env zalo-token-data zalo-token-service.mjs; do
  [[ -e "$STACK_ROOT/$item" ]] && config_inputs+=("$item")
done
[[ ${#config_inputs[@]} -gt 0 ]] || fail "no stack configuration files found"

if [[ -f /root/espocrm-n8n-api.env ]]; then
  tar -czf "$partial_dir/config.tar.gz" \
    -C "$STACK_ROOT" "${config_inputs[@]}" \
    -C /root espocrm-n8n-api.env
else
  tar -czf "$partial_dir/config.tar.gz" -C "$STACK_ROOT" "${config_inputs[@]}"
fi

for artifact in "$partial_dir"/*.sql.gz; do
  [[ -e "$artifact" ]] || continue
  [[ -s "$artifact" ]] || fail "empty SQL backup: $artifact"
  gzip -t "$artifact"
done
for artifact in "$partial_dir"/*.tar.gz "$partial_dir/config.tar.gz"; do
  [[ -e "$artifact" ]] || continue
  [[ -s "$artifact" ]] || fail "empty archive: $artifact"
  tar -tzf "$artifact" >/dev/null
done

cat > "$partial_dir/MANIFEST.txt" <<EOF
timestamp=$TIMESTAMP
compose_project=$COMPOSE_PROJECT
compose_file=$COMPOSE_FILE
n8n_volume=$n8n_volume
postgres_container=$postgres_id
n8n_container=$n8n_id
espocrm_included=$([[ -n "$espocrm_db_id" ]] && printf true || printf false)
EOF

(
  cd "$partial_dir"
  sha256sum ./*.gz > SHA256SUMS
)
chmod 600 "$partial_dir"/*
mv "$partial_dir" "$final_dir"

find "$backup_root_abs" \
  -mindepth 1 -maxdepth 1 -type d \
  -name '20??-??-??_??-??-??' -mtime "+$RETENTION_DAYS" \
  -exec rm -rf -- {} +

trap - EXIT
printf 'Backup created: %s\n' "$final_dir"
