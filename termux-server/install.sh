#!/data/data/com.termux/files/usr/bin/bash
# Run once:  bash ~/sonaplay/termux-server/install.sh
set -e
pkg update -y
pkg install -y python nodejs ffmpeg cloudflared python-cryptography termux-api
pip install --upgrade pip
pip install flask flask-cors "yt-dlp[default]" requests gunicorn mutagen
pip install pywebpush==2.0.0 || echo "pywebpush skipped (only needed for push notifications)"
mkdir -p ~/.termux/boot ~/sona-cache
cat > ~/.termux/boot/sona.sh <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
termux-wake-lock
nohup bash ~/sonaplay/termux-server/start.sh > ~/sona-run.log 2>&1 &
BOOT
chmod +x ~/.termux/boot/sona.sh
echo "Done. Next: create ~/sona.env (see README), then: bash ~/sonaplay/termux-server/start.sh"
