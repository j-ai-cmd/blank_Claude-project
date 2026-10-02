# Self-hosted runtime (videos, voices, code tests). Builds on ARM (Oracle Ampere) and x86.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium HYPERFRAMES_SKIP_SKILLS=1 DO_NOT_TRACK=1 \
    HF_HOME=/models
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg espeak-ng chromium fonts-dejavu-core curl ca-certificates git \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y --no-install-recommends nodejs \
 && npm i -g hyperframes@0.8.91 && rm -rf /var/lib/apt/lists/* /root/.npm
# CPU PyTorch (no GPU on the free tier), then the Kokoro voice engine
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir "fastapi[standard]" uvicorn pytest "kokoro>=0.9.4" soundfile numpy
RUN useradd -m runner && mkdir -p /models && chown runner /models
COPY deploy/runtime_server.py /srv/runtime_server.py
USER runner
WORKDIR /srv
EXPOSE 8080
CMD ["uvicorn", "runtime_server:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
