FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WORKFORCE_BILLING=plan WORKFORCE_ROOT=/app
# ffprobe: the video_spec check reads rendered MP4s here. Building and rendering happen on the Modal runtime.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY workforce ./workforce
RUN pip install --no-cache-dir . && useradd -m agent
COPY config ./config
COPY schemas ./schemas
COPY scripts ./scripts
COPY context ./context
COPY core ./core
COPY shows ./shows
COPY .claude ./.claude
RUN mkdir -p var uploads outbox proposals && chown -R agent /app/var /app/uploads /app/outbox /app/proposals /app/config /app/context /app/.claude
USER agent
EXPOSE 8000
# Config is validated at boot: a broken design file stops the service instead of running unenforced.
CMD ["sh", "-c", "python scripts/validate_config.py && uvicorn workforce.app:app --host 0.0.0.0 --port 8000 --workers 1"]
