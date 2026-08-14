FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends espeak-ng ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY apps/api /workspace/apps/api
COPY services/worker /workspace/services/worker
RUN pip install --no-cache-dir /workspace/apps/api /workspace/services/worker

WORKDIR /workspace/services/worker
CMD ["python", "-m", "npd_worker.main"]
