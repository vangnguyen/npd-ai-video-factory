#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

mkdir -p e2e-artifacts storage/assets/vinhomes-green-paradise storage/jobs
cp .env.example .env

python - <<'PY'
import base64
from pathlib import Path

# Valid 1x1 PNG. Multiple named fixtures exercise deterministic local asset resolution
# while keeping the CI render lightweight and copyright-safe.
png = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
folder = Path("storage/assets/vinhomes-green-paradise")
folder.mkdir(parents=True, exist_ok=True)
for index in range(1, 6):
    (folder / f"fixture-{index:02d}.png").write_bytes(png)
PY

cleanup() {
  docker compose logs --no-color > e2e-artifacts/compose.log 2>&1 || true
  docker compose down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[e2e] building and starting stack"
docker compose up -d --build

echo "[e2e] waiting for API readiness"
ready=0
for _ in $(seq 1 90); do
  if curl --fail --silent http://localhost:8000/readyz >/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != "1" ]]; then
  echo "API did not become ready" >&2
  exit 1
fi

if ! curl --fail --silent http://localhost:3001/healthz >/dev/null; then
  echo "Renderer health check failed" >&2
  exit 1
fi

expected_duration="$(python -c 'import json; print(json.load(open("examples/vinhomes-green-paradise.request.json", encoding="utf-8"))["video"]["duration_seconds"])')"
echo "[e2e] creating ${expected_duration}-second video job"
create_response="$(
  curl --fail --silent --show-error \
    -X POST http://localhost:8000/api/v1/video-jobs \
    -H 'Content-Type: application/json' \
    -H 'Idempotency-Key: github-actions-sprint-1-e2e' \
    --data-binary @examples/vinhomes-green-paradise.request.json
)"
printf '%s\n' "$create_response" > e2e-artifacts/create-response.json
job_id="$(printf '%s' "$create_response" | python -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "[e2e] job_id=$job_id"

terminal=0
for attempt in $(seq 1 120); do
  status_json="$(curl --fail --silent --show-error "http://localhost:8000/api/v1/video-jobs/$job_id")"
  printf '%s\n' "$status_json" > e2e-artifacts/job-status.json
  read -r job_status job_stage progress < <(
    printf '%s' "$status_json" | python -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d["stage"], d["progress"])'
  )
  echo "[e2e] poll=$attempt status=$job_status stage=$job_stage progress=$progress"
  if [[ "$job_status" == "awaiting_review" ]]; then
    terminal=1
    break
  fi
  if [[ "$job_status" == "failed" ]]; then
    echo "Video job failed" >&2
    printf '%s\n' "$status_json" >&2
    exit 1
  fi
  sleep 5
done

if [[ "$terminal" != "1" ]]; then
  echo "Video job did not reach awaiting_review before timeout" >&2
  exit 1
fi

job_dir="storage/jobs/$job_id"
for required in script.json storyboard.json narration.wav subtitles.srt video-manifest.json final.mp4 qc.json; do
  if [[ ! -f "$job_dir/$required" ]]; then
    echo "Missing required artifact: $required" >&2
    exit 1
  fi
done

cp "$job_dir/final.mp4" e2e-artifacts/final.mp4
cp "$job_dir/qc.json" e2e-artifacts/qc.json
cp "$job_dir/video-manifest.json" e2e-artifacts/video-manifest.json

python - <<'PY'
import json
from pathlib import Path

qc = json.loads(Path("e2e-artifacts/qc.json").read_text(encoding="utf-8"))
request = json.loads(
    Path("examples/vinhomes-green-paradise.request.json").read_text(encoding="utf-8")
)
expected_duration = float(request["video"]["duration_seconds"])
assert qc["width"] == 1080, qc
assert qc["height"] == 1920, qc
assert qc["video_codec"] == "h264", qc
assert qc["audio_codec"], qc
assert abs(float(qc["duration_seconds"]) - expected_duration) <= 3.0, qc
assert int(qc["size_bytes"]) > 100_000, qc
print("[e2e] QC verified", json.dumps(qc, ensure_ascii=False))
PY

echo "[e2e] Sprint 1 vertical slice passed"
