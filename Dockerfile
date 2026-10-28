FROM python:3.11-slim

WORKDIR /app

# ffmpeg converts recordings made in the browser (webm, mp4) into a format the
# transcriber accepts. WhatsApp's own voice notes are already ogg and skip it.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg     && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# --proxy-headers/--forwarded-allow-ips: Railway/Render terminate TLS and proxy
# plain HTTP internally. Twilio signs its webhook against the https:// URL, so
# without trusting X-Forwarded-Proto every signature check would fail.
CMD uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'
