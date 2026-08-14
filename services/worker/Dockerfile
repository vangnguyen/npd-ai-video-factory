FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /worker
COPY pyproject.toml ./
COPY worker.py ./
RUN pip install --no-cache-dir .

CMD ["python", "worker.py"]
