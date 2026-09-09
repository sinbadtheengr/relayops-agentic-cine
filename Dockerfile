# ReelRelay on Cloud Run.
#
# Serves the ADK dev UI so a judge can drive the five-stage pipeline from a
# browser -- chat, event traces, and the session-state inspector -- without
# cloning the repo or holding any keys of their own.

FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# The agent package, plus the sample profiles the UI is demoed against.
# Everything else -- .env, .venv, tests, validation reports -- is excluded by
# .dockerignore. The image must never carry a key.
COPY reelrelay/ ./reelrelay/
COPY samples/ ./samples/

# Cloud Run injects $PORT and routes to it. adk web binds 127.0.0.1 by default,
# which is right for local dev and fatal in a container: the health check
# arrives on the external interface and finds nothing listening.
ENV PORT=8080
CMD exec python -m google.adk.cli web --host 0.0.0.0 --port ${PORT} /app
