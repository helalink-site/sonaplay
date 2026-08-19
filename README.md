# Sona Play — Full Project & Setup Guide

## What's in this zip

```
sona-play/
├── index.html          <- the app itself (frontend, open in a browser)
└── backend/
    ├── app.py           <- Flask API (search, stream, download)
    ├── requirements.txt
    ├── Dockerfile        <- for deploying on Render
    └── .dockerignore
```

How it works: `index.html` is a single-page app that calls the API in
`backend/app.py` to search for songs (SoundCloud first, YouTube fallback),
stream them, and download them. First play of any song downloads it once
into a server-side cache; every play after that (by anyone) is instant.

---

## PART 1 — Run it on your phone (Termux) to test

You need **3 Termux sessions running at the same time**. Open a new one by
swiping from the left edge of the screen, or tap the hamburger menu → New
session.

### Session 1 — install + start the backend

```bash
cd backend
pip install -r requirements.txt --break-system-packages
pkg install ffmpeg -y
python app.py
```

Leave this running. It's now serving on `localhost:5000`.

### Session 2 — expose it to the internet

```bash
npm install -g localtunnel
npx localtunnel --port 5000 --subdomain xavitech-sona
```

Leave this running too. This is what makes `https://xavitech-sona.loca.lt`
work — the URL already hardcoded into `index.html`.

**If that subdomain is ever taken by someone else on a given day**,
localtunnel gives you a different random one instead — check the terminal
output for the actual URL it gives you, and if it's not `xavitech-sona`,
update line 743 of `index.html` to match.

### Session 3 — serve the HTML file

```bash
cd /path/to/sona-play      # wherever you put this unzipped folder
python -m http.server 8080
```

### Open the app

On your phone, open **Chrome** and go to:
```
http://localhost:8080/index.html
```

### Before assuming anything's broken — test the backend directly first

```bash
curl https://xavitech-sona.loca.lt/api/health
curl "https://xavitech-sona.loca.lt/api/search?q=Burna+Boy&limit=5"
```

If both return real JSON (not an error), the backend's working and any
remaining issue is in the frontend/browser, not the API.

---

## PART 2 — Deploy for real (Render, so it doesn't depend on your phone)

1. Push the `backend/` folder to your GitHub repo (`helalink-site/sonaplay`)
2. Render dashboard → **New → Web Service** → connect the repo
3. Set **Environment: Docker** (not Python) — this picks up `Dockerfile`,
   which installs ffmpeg. Without this, downloads silently fail.
4. Add a **persistent disk** (Render dashboard → your service → Disks →
   Add Disk), mount it at `/var/data`
5. Add environment variable: `CACHE_DIR=/var/data/cache`
   — without this, the song cache wipes on every redeploy
6. (Optional, recommended) Add your `cookies.txt` as a **Secret File** at
   `/etc/secrets/cookies.txt`, then add env var:
   `COOKIE_FILE=/etc/secrets/cookies.txt`
7. Deploy. Wait for the build to finish.
8. Copy your Render URL (e.g. `https://sonaplay.onrender.com`)
9. In `index.html`, update line 743:
   ```js
   const API='https://sonaplay.onrender.com/api';
   ```
10. Re-host `index.html` wherever you're serving the frontend from
    (GitHub Pages, Render static site, etc.)

### Known behavior on Render's free tier
The service sleeps after 15 minutes of no traffic. The first request after
that takes 20-50 seconds to wake up — this is Render's free-tier behavior,
not a bug. Upgrade to a paid instance if this matters for real users.

---

## Things to know going in (not bugs, just how this is built)

- **First play of any song** takes a few seconds (server downloads it once)
- **SoundCloud catalog gaps**: big commercial hits often aren't there —
  YouTube fills in automatically when that happens
- **Cache grows over time** with no automatic cleanup yet — worth adding
  before real users pile up storage
- **Cookies expire** — if search/stream suddenly stop working after
  working fine, re-export a fresh `cookies.txt` before assuming the code
  broke
