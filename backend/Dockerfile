FROM python:3.11-slim

# ffmpeg is required for /api/download (mp3 conversion via yt-dlp postprocessor).
# Render's default Python buildpack does NOT include this - it's why downloads
# were failing silently before.
#
# nodejs is required for yt-dlp's js_runtimes signature/n-challenge solver
# (YDL_BASE_OPTS in app.py) - without it, every stream resolve fails with
# "The page needs to be reloaded".
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
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
# Kept to 1 worker / 4 threads (not 2/8) - Render's free tier only has
# 512MB RAM, and each concurrent yt-dlp resolve can spin up a Node
# subprocess for signature-solving, which adds up fast at higher
# concurrency and was causing OOM crashes.
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
