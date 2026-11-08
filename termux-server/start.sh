#!/data/data/com.termux/files/usr/bin/bash
# Starts the Sona Play server on this phone + a Cloudflare tunnel, and publishes the tunnel
# address to Supabase (app_config.api_url) so the app finds it by itself.
[ -f "$HOME/sona.env" ] || { echo "Missing ~/sona.env"; exit 1; }
set -a; . "$HOME/sona.env"; set +a
termux-wake-lock 2>/dev/null
export PORT=5000
export WARM_DOWNLOAD="${WARM_DOWNLOAD:-1}"
export CACHE_MAX_MB="${CACHE_MAX_MB:-1500}"
export CACHE_DIR="${CACHE_DIR:-$HOME/sona-cache}"
mkdir -p "$CACHE_DIR"
cd "$HOME/sonaplay/backend" || exit 1

# 1) the server, restarted automatically if it ever stops
( while true; do
    gunicorn app:app --bind 127.0.0.1:$PORT --workers 1 --threads 6 --timeout 120 --access-logfile - >> "$HOME/sona-server.log" 2>&1
    sleep 3
  done ) &

# 2) the tunnel; every new address is published to Supabase
while true; do
  rm -f "$HOME/sona-tunnel.log"
  cloudflared tunnel --url http://127.0.0.1:$PORT --no-autoupdate > "$HOME/sona-tunnel.log" 2>&1 &
  CP=$!
  URL=""
  for i in $(seq 1 60); do
    URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$HOME/sona-tunnel.log" | head -1)
    [ -n "$URL" ] && break
    sleep 1
  done
  if [ -n "$URL" ]; then
    echo "$(date) tunnel: $URL"
    curl -s -X PATCH "$SUPABASE_URL/rest/v1/app_config?id=eq.1" \
      -H "apikey: $SUPABASE_SERVICE_ROLE_KEY" -H "Authorization: Bearer $SUPABASE_SERVICE_ROLE_KEY" \
      -H "Content-Type: application/json" -d "{\"api_url\":\"$URL\"}" > /dev/null
  fi
  wait $CP
  sleep 3
done
