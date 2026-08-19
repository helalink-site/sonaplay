FROM python:3.11-slim

# ffmpeg is required for /api/download (mp3 conversion via yt-dlp postprocessor).
# Render's default Python buildpack does NOT include this - it's why downloads
# were failing silently before.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=5000
EXPOSE 5000

# --threads lets one worker handle multiple concurrent /api/relay or
# /api/download requests without blocking (both hold the connection open
# for the whole audio transfer). --timeout is raised because audio
# extraction + relay can take longer than gunicorn's 30s default.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 8 --timeout 120
