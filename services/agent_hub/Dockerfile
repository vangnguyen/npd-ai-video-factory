FROM python:3.12-slim

WORKDIR /app
COPY services/agent_hub/pyproject.toml /app/pyproject.toml
RUN pip install --no-cache-dir .
COPY services/agent_hub/npd_agent_hub /app/npd_agent_hub

EXPOSE 8010
CMD ["uvicorn", "npd_agent_hub.main:app", "--host", "0.0.0.0", "--port", "8010"]
