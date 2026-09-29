FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 WORKFORCE_BILLING=plan WORKFORCE_ROOT=/app
WORKDIR /app
COPY pyproject.toml ./
COPY workforce ./workforce
RUN pip install --no-cache-dir . && useradd -m agent
COPY config ./config
COPY schemas ./schemas
COPY scripts ./scripts
COPY .claude ./.claude
RUN mkdir -p var && chown -R agent /app/var
USER agent
EXPOSE 8000
# Config is validated at boot: a broken design file stops the service instead of running unenforced.
CMD ["sh", "-c", "python scripts/validate_config.py && uvicorn workforce.app:app --host 0.0.0.0 --port 8000"]
