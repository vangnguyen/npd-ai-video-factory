#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${RUN_PRODUCTION_PILOT:-0}" != "1" ]]; then
  echo "Refusing to run a paid/production pilot." >&2
  echo "Set RUN_PRODUCTION_PILOT=1 explicitly after assets, logo, and VPS secrets are ready." >&2
  exit 2
fi

if [[ ! -f .env ]]; then
  echo "Missing .env. Create it from .env.example and configure production secrets on the VPS." >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3 is required to run the production pilot." >&2
  exit 2
fi

"$PYTHON_BIN" - <<'PY'
from pathlib import Path

values = {}
for raw in Path('.env').read_text(encoding='utf-8').splitlines():
    line = raw.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    values[key.strip()] = value.strip()

required = {
    'APP_ENV': 'production',
    'TTS_PROVIDER': 'openai',
    'PILOT_STRICT_ASSETS': '1',
}
for key, expected in required.items():
    actual = values.get(key, '')
    if actual != expected:
        raise SystemExit(f"{key} must be {expected!r}; found {actual!r}")

if not values.get('OPENAI_API_KEY'):
    raise SystemExit('OPENAI_API_KEY is missing from the VPS .env/secret environment')
if not values.get('OPENAI_TTS_MODEL'):
    raise SystemExit('OPENAI_TTS_MODEL is missing')
if not values.get('OPENAI_TTS_VOICE'):
    raise SystemExit('OPENAI_TTS_VOICE is missing')
print('[pilot] environment guard passed (secret value not printed)')
PY

mkdir -p production-pilot-artifacts storage/jobs

echo "[pilot] building worker for asset preflight"
docker compose build worker

echo "[pilot] validating licensed project assets and production logo"
docker compose run --rm worker \
  python -m npd_worker.preflight \
  --project-folder vinhomes-green-paradise \
  --minimum-clips 5

echo "[pilot] starting stack"
docker compose up -d --build

cleanup_on_error() {
  local code=$?
  if [[ $code -ne 0 ]]; then
    echo "[pilot] failed; recent service logs follow" >&2
    docker compose logs --tail=120 api worker renderer >&2 || true
  fi
  return $code
}
trap cleanup_on_error EXIT

echo "[pilot] waiting for API and renderer health"
api_ready=0
for _ in $(seq 1 90); do
  if curl --fail --silent http://localhost:8000/readyz >/dev/null; then
    api_ready=1
    break
  fi
  sleep 2
done
if [[ "$api_ready" != "1" ]]; then
  echo "API did not become ready" >&2
  exit 1
fi
curl --fail --silent http://localhost:3001/healthz >/dev/null

request_path="examples/vinhomes-green-paradise.request.json"
pilot_duration_seconds="$(
  "$PYTHON_BIN" - "$request_path" <<'PY'
import json
import sys
from pathlib import Path

request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(request['video']['duration_seconds'])
PY
)"
echo "[pilot] creating the real-media ${pilot_duration_seconds}-second job"
create_response="$(
  curl --fail --silent --show-error \
    -X POST http://localhost:8000/api/v1/video-jobs \
    -H 'Content-Type: application/json' \
    -H "Idempotency-Key: production-pilot-$(date -u +%Y%m%dT%H%M%SZ)" \
    --data-binary @"$request_path"
)"
job_id="$(printf '%s' "$create_response" | "$PYTHON_BIN" -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
evidence_dir="production-pilot-artifacts/$job_id"
mkdir -p "$evidence_dir"
printf '%s\n' "$create_response" > "$evidence_dir/create-response.json"
echo "[pilot] job_id=$job_id"

terminal=0
for attempt in $(seq 1 120); do
  status_json="$(curl --fail --silent --show-error "http://localhost:8000/api/v1/video-jobs/$job_id")"
  printf '%s\n' "$status_json" > "$evidence_dir/job-status.json"
  read -r status stage progress < <(
    printf '%s' "$status_json" | "$PYTHON_BIN" -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["stage"], d["progress"])'
  )
  echo "[pilot] poll=$attempt status=$status stage=$stage progress=$progress"
  if [[ "$status" == "awaiting_review" ]]; then
    terminal=1
    break
  fi
  if [[ "$status" == "failed" ]]; then
    echo "Production pilot failed" >&2
    printf '%s\n' "$status_json" >&2
    exit 1
  fi
  sleep 5
done

if [[ "$terminal" != "1" ]]; then
  echo "Production pilot did not reach awaiting_review before timeout" >&2
  exit 1
fi

job_dir="storage/jobs/$job_id"
for required in final.mp4 qc.json video-manifest.json script.json storyboard.json subtitles.srt; do
  if [[ ! -f "$job_dir/$required" ]]; then
    echo "Missing required production artifact: $required" >&2
    exit 1
  fi
done

cp "$job_dir/final.mp4" "$evidence_dir/final.mp4"
cp "$job_dir/qc.json" "$evidence_dir/qc.json"
cp "$job_dir/video-manifest.json" "$evidence_dir/video-manifest.json"
cp "$job_dir/script.json" "$evidence_dir/script.json"
cp "$job_dir/storyboard.json" "$evidence_dir/storyboard.json"
cp "$job_dir/subtitles.srt" "$evidence_dir/subtitles.srt"
docker compose logs --no-color api worker renderer > "$evidence_dir/compose.log" 2>&1 || true

"$PYTHON_BIN" - "$evidence_dir/qc.json" "$request_path" <<'PY'
import json
import sys
from pathlib import Path

qc = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
request = json.loads(Path(sys.argv[2]).read_text(encoding='utf-8'))
expected_duration = float(request['video']['duration_seconds'])
assert qc['width'] == 1080, qc
assert qc['height'] == 1920, qc
assert qc['video_codec'] == 'h264', qc
assert qc['audio_codec'], qc
assert abs(float(qc['duration_seconds']) - expected_duration) <= 3.0, qc
assert int(qc['size_bytes']) > 100_000, qc
print('[pilot] QC verified:', json.dumps(qc, ensure_ascii=False))
PY

echo "[pilot] COMPLETE"
echo "[pilot] Review video: $evidence_dir/final.mp4"
echo "[pilot] QC evidence: $evidence_dir/qc.json"
echo "[pilot] Do not publish automatically; complete the human review gate first."
