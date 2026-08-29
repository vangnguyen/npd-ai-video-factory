#!/usr/bin/env sh
set -eu

# This script is intended to run inside the existing Redis container and writes
# a sensitive, lossless logical DB0 export to stdout. The caller must pipe
# stdout directly to an approved encrypted off-production destination.

ACK_REQUIRED="STREAM_SENSITIVE_DB0_TO_APPROVED_ENCRYPTED_DESTINATION"
if [ "${V1_BACKUP_ENCRYPTED_PIPE_ACK:-}" != "$ACK_REQUIRED" ]; then
  printf '%s\n' "export refused: set V1_BACKUP_ENCRYPTED_PIPE_ACK=$ACK_REQUIRED" >&2
  exit 2
fi

if [ "${V1_REDIS_DB:-0}" != "0" ]; then
  printf '%s\n' 'export refused: only V1 Redis DB0 is permitted' >&2
  exit 2
fi

redis_cli="${REDIS_CLI:-redis-cli}"
keys="$($redis_cli -n 0 --scan | LC_ALL=C sort)"
db_size="$($redis_cli -n 0 --raw DBSIZE)"
scan_count="$(printf '%s\n' "$keys" | awk 'NF {count++} END {print count+0}')"

if [ "$db_size" != "$scan_count" ]; then
  printf 'export refused: DB0 changed during preflight (dbsize=%s scan=%s)\n' \
    "$db_size" "$scan_count" >&2
  exit 3
fi

# Fail before emitting any payload if an unexpected key, type, or expired key
# appears. V1 DB0 currently owns only job strings, optional idempotency strings,
# and queue/processing lists.
printf '%s\n' "$keys" | while IFS= read -r key; do
  [ -n "$key" ] || continue
  case "$key" in
    *[!A-Za-z0-9._:-]*)
      printf 'export refused: DB0 key contains unsupported characters\n' >&2
      exit 4
      ;;
  esac
  case "$key" in
    npd:video-job:*) expected_type=string ;;
    npd:video-idempotency:*) expected_type=string ;;
    npd:video-jobs:queue|npd:video-jobs:processing) expected_type=list ;;
    *) printf 'export refused: unexpected DB0 key identity\n' >&2; exit 4 ;;
  esac
  actual_type="$($redis_cli -n 0 --raw TYPE "$key")"
  if [ "$actual_type" != "$expected_type" ]; then
    printf 'export refused: unexpected type for key (expected=%s actual=%s)\n' \
      "$expected_type" "$actual_type" >&2
    exit 4
  fi
  pttl="$($redis_cli -n 0 --raw PTTL "$key")"
  if [ "$pttl" -lt -1 ]; then
    printf 'export refused: key expired during preflight\n' >&2
    exit 4
  fi
done

captured_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
queue_len="$($redis_cli -n 0 --raw LLEN npd:video-jobs:queue)"
processing_len="$($redis_cli -n 0 --raw LLEN npd:video-jobs:processing)"

items=''
capture_fingerprint=''
old_ifs=$IFS
IFS='
'
for key in $keys; do
  key_type="$($redis_cli -n 0 --raw TYPE "$key")"
  pttl="$($redis_cli -n 0 --raw PTTL "$key")"
  if [ "$pttl" -lt -1 ]; then
    printf 'export failed: key expired during capture\n' >&2
    exit 5
  fi
  key_base64="$(printf '%s' "$key" | base64 -w0)"
  dump_base64="$($redis_cli -n 0 -D '' --raw DUMP "$key" | base64 -w0)"
  if [ -z "$dump_base64" ]; then
    printf 'export failed: empty serialized dump\n' >&2
    exit 5
  fi
  dump_sha256="$(printf '%s' "$dump_base64" | base64 -d | sha256sum | awk '{print $1}')"
  item="$(printf '{"key_base64":"%s","type":"%s","pttl_ms":%s,' \
    "$key_base64" "$key_type" "$pttl")"
  item="$item$(printf '"dump_base64":"%s","dump_sha256":"%s"}' \
    "$dump_base64" "$dump_sha256")"
  if [ -n "$items" ]; then items="$items,$item"; else items=$item; fi
  fingerprint_line="$key_base64:$key_type:$dump_sha256"
  if [ -n "$capture_fingerprint" ]; then
    capture_fingerprint="$capture_fingerprint
$fingerprint_line"
  else
    capture_fingerprint=$fingerprint_line
  fi
done
IFS=$old_ifs

# Refuse the capture if any key identity or serialized value changed while the
# logical snapshot was assembled. This emits no payload before the check passes.
post_keys="$($redis_cli -n 0 --scan | LC_ALL=C sort)"
post_db_size="$($redis_cli -n 0 --raw DBSIZE)"
post_scan_count="$(printf '%s\n' "$post_keys" | awk 'NF {count++} END {print count+0}')"
if [ "$post_db_size" != "$post_scan_count" ] || [ "$post_keys" != "$keys" ]; then
  printf 'export refused: DB0 key set changed during capture\n' >&2
  exit 6
fi

post_fingerprint=''
IFS='
'
for key in $post_keys; do
  key_type="$($redis_cli -n 0 --raw TYPE "$key")"
  dump_base64="$($redis_cli -n 0 -D '' --raw DUMP "$key" | base64 -w0)"
  if [ -z "$dump_base64" ]; then
    printf 'export refused: DB0 value changed or expired during capture\n' >&2
    exit 6
  fi
  key_base64="$(printf '%s' "$key" | base64 -w0)"
  dump_sha256="$(printf '%s' "$dump_base64" | base64 -d | sha256sum | awk '{print $1}')"
  fingerprint_line="$key_base64:$key_type:$dump_sha256"
  if [ -n "$post_fingerprint" ]; then
    post_fingerprint="$post_fingerprint
$fingerprint_line"
  else
    post_fingerprint=$fingerprint_line
  fi
done
IFS=$old_ifs

if [ "$post_fingerprint" != "$capture_fingerprint" ]; then
  printf 'export refused: DB0 value changed during capture\n' >&2
  exit 6
fi

printf '{"schema_version":"1.0","database":0,"captured_at":"%s",' "$captured_at"
printf '"key_count":%s,"queue_length":%s,"processing_length":%s,"items":[%s]}\n' \
  "$scan_count" "$queue_len" "$processing_len" "$items"
