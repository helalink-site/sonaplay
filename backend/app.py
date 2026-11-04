"""
Sona Play backend — Flask API matching the endpoint contract baked into
index.html (const API = '.../api').

ARCHITECTURE (cache-once, serve-many):
Instead of live-relaying a signed googlevideo URL on every play (fragile:
URLs expire, need custom Range-forwarding, IP-locked), each song is fully
downloaded ONCE into a local cache folder the first time anyone plays or
downloads it. After that, both streaming and downloading serve the same
cached file straight off disk via Flask's send_file, which handles
Range/seek requests correctly with zero custom code.

SOURCE: YouTube Music search (ytmsearch) — built for songs/albums, so it
naturally excludes podcasts/tutorials/reactions far better than plain
YouTube search. A duration/live-stream safety check runs at DOWNLOAD time
(not search time), since YT Music's quick search results don't reliably
include duration - checking too early was wiping out real results.

Endpoints:
  GET  /api/search?q=&limit=&order=
  GET  /api/artist?name=&limit=
  GET  /api/mixes?limit=
  GET  /api/stream/<vid>          -> warms the cache, returns a proxy URL
  GET  /api/proxy/<vid>           -> serves cached audio (streaming, seekable)
  GET  /api/download/<vid>?title=&artist=  -> serves cached audio as attachment
  GET  /api/relay?url=            -> kept for backward compatibility only

Run locally:
  pip install -r requirements.txt
  python app.py

Deploy (Render): gunicorn app:app  (see Dockerfile - needs ffmpeg)
"""

import os
import re
import random
import time
import io
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

import requests
import yt_dlp
from flask import Flask, request, jsonify, Response, stream_with_context, send_file
from flask_cors import CORS
import hmac
from security import init_security, ALLOWED_ORIGINS
try:
    from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1, APIC
    from mutagen.mp4 import MP4, MP4Cover
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

app = Flask(__name__)
CORS(app, origins=ALLOWED_ORIGINS)
init_security(app)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

COOKIE_FILE = os.environ.get("COOKIE_FILE", "")

# Mobile browsers/textareas often silently convert the tab characters in a
# Netscape cookies.txt file into spaces when pasted, corrupting the format
# without any visible sign. Base64 has no whitespace to mangle, so if a
# COOKIE_FILE_B64 env var is present, decode it to a real file at startup
# and use that instead - this is the reliable path when pasting via a
# phone's Render/hosting dashboard UI.
COOKIE_FILE_B64 = os.environ.get("COOKIE_FILE_B64", "")
if COOKIE_FILE_B64 and not (COOKIE_FILE and os.path.exists(COOKIE_FILE)):
    import base64 as _b64
    _decoded_path = "/tmp/cookies.txt"
    with open(_decoded_path, "wb") as _f:
        _f.write(_b64.b64decode(COOKIE_FILE_B64))
    COOKIE_FILE = _decoded_path
PROXY_URL = os.environ.get("PROXY_URL", "")

# Needed only for Delete Account. Get this from Supabase dashboard ->
# Settings -> API -> service_role key. NEVER put this in the frontend -
# it has full admin access to every user's data.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# Where downloaded audio lives. On Render, point this at a persistent disk
# mount (e.g. "/var/data/cache") or the cache is wiped on every redeploy.
CACHE_DIR = os.environ.get("CACHE_DIR", os.path.join(os.path.dirname(__file__), "cache"))
os.makedirs(CACHE_DIR, exist_ok=True)

# Maps a videoId (e.g. "sc_1234567") to the real source URL yt-dlp needs to
# fetch it. Populated whenever /api/search, /api/artist, or /api/mixes runs,
# since a track always gets searched before it gets played. In-memory is
# fine for a single-instance deploy; swap for a small sqlite/Redis table if
# you ever run multiple backend instances.
_track_url_cache = {}
# Video IDs the person reached through the DJ Mixes tab - these are allowed
# to be long, unlike everywhere else where a long result means an
# accidental live stream/mix that snuck past search filtering.
_known_mix_ids = set()

# Short-lived cache for resolved mix URLs - resolving a URL requires a full
# yt-dlp webpage fetch + JS challenge solve, which takes several real
# seconds every time. Caching it briefly means replaying the same mix
# (even by a different person) skips that wait entirely. Short TTL because
# googlevideo URLs themselves expire after a while.
_mix_url_cache = {}
MIX_URL_CACHE_TTL = 60 * 4

MIX_SEEDS = [
    "afrobeats hits", "bongo flava hits", "gengetone hits",
    "amapiano mix", "kenyan gospel hits", "hip hop hits 2025",
    "dancehall hits", "r&b hits",
]

YT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{11}$")

YDL_BASE_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "geo_bypass": True,
    "socket_timeout": 20,
    "retries": 3,
    # Without these two, YouTube's signature/n-challenge can't be solved and
    # every download fails with "Requested format is not available" - this
    # was the root cause behind everything we chased today.
    "js_runtimes": {"node": {}},
    "remote_components": ["ejs:github", "ejs:npm"],
    "extractor_args": {"youtube": {"player_client": ["tv", "web", "mweb"]}},
}
if COOKIE_FILE and os.path.exists(COOKIE_FILE):
    YDL_BASE_OPTS["cookiefile"] = COOKIE_FILE
if PROXY_URL:
    YDL_BASE_OPTS["proxy"] = PROXY_URL

REQUESTS_PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else None


def ydl_opts(**overrides):
    o = dict(YDL_BASE_OPTS)
    o.update(overrides)
    return o


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def fmt_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def split_artist_title(raw_title, uploader):
    title = raw_title or "Unknown"
    artist = uploader or "Unknown Artist"
    m = re.match(r"^\s*([^-]{2,40})\s*-\s*(.+)$", title)
    if m:
        artist, title = m.group(1).strip(), m.group(2).strip()
    title = re.sub(r"\s*[\(\[](official|lyrics?|audio|video|mv|hd|4k)[^\)\]]*[\)\]]", "", title, flags=re.I).strip()
    return artist, title


MAX_TRACK_SECONDS = 15 * 60  # reject mixes/live streams - a real song is a few minutes

# Titles containing these are almost never the actual studio track someone
# searched for - filtering them out cuts down a lot of the wrong-result noise.
JUNK_TITLE_PATTERNS = re.compile(
    r"\b(cover|reaction|tutorial|lesson|karaoke|type\s*beat|podcast|interview|"
    r"react(s|ing)?|full\s*album|behind\s*the\s*scenes|bts|unboxing|review|"
    r"live\s*performance|\(live\)|\blive\b|\bfm\b|radio|performance|concert|"
    r"responds?\s*to|guide\s*to|how\s*to|episode\s*\d+|vlog|explains?|breaks?\s*down)\b|🔴",
    re.I,
)

# Multi-track compilations/mix videos - these belong ONLY on the dedicated
# DJ Mixes tab (/api/mixes), never in normal song search, artist pages, or
# the home feed. A single search result titled "1H30 Gospel Mix" is not the
# song someone is looking for, it's an hour of many songs mashed together.
MIX_TITLE_PATTERNS = re.compile(
    r"\bmix(es|tape)?\b|\bcompilation\b|\bplaylist\b|\d+\s*h(ou)?rs?\b|"
    r"\bnonstop\b|\bmedley\b|\bmegamix\b|\bvolume\s*\d+|\bvol\.?\s*\d+|"
    r"\bskiza\b|\bpraise\s*(and|&)\s*worship\b|\bworship\s*(mix|songs)\b",
    re.I,
)


def is_junk_result(title, duration):
    if not title:
        return True
    if JUNK_TITLE_PATTERNS.search(title):
        return True
    return False


def extract_artist(e):
    """YouTube Music search results carry artist info differently than
    plain YouTube did - checking several possible fields since 'uploader'
    alone (what worked before) often comes back empty here."""
    artists = e.get("artists") or e.get("artist")
    if isinstance(artists, list) and artists:
        first = artists[0]
        if isinstance(first, dict):
            name = first.get("name")
        else:
            name = first
        if name:
            return name
    if isinstance(artists, str) and artists:
        return artists
    for key in ("uploader", "channel", "creator", "album_artist"):
        val = e.get(key)
        if val:
            return val
    return None


def yt_entry_to_track(e, allow_mixes=False):
    vid = e.get("id")
    if not vid:
        return None
    # NOTE: ytmsearch's flat/quick results often don't include duration at
    # all, so we can't safely reject on "missing duration" here without
    # wiping out every real result. The mix/livestream safety check now
    # happens at actual download time instead (see ensure_cached), where
    # yt-dlp knows the real duration for certain before downloading bytes.
    duration = e.get("duration")
    title = e.get("title")
    if e.get("is_live"):
        return None
    if is_junk_result(title, duration):
        return None
    if not allow_mixes and title and MIX_TITLE_PATTERNS.search(title):
        return None
    if allow_mixes:
        _known_mix_ids.add(vid)  # whitelist so download-time filter allows the full length
    raw_artist = extract_artist(e)
    artist, clean_title = split_artist_title(title, raw_artist)
    thumbs = e.get("thumbnails") or []
    thumb = thumbs[-1]["url"] if thumbs else e.get("thumbnail", "")
    return {
        "videoId": vid,
        "title": clean_title,
        "artist": artist,
        "thumbnail": thumb,
        "duration": fmt_duration(duration),
        "source": "youtube",
    }


def yt_search(query, limit=20, order="relevance", allow_mixes=False):
    """Plain YouTube search only - "ytsearchdate:" turned out to also be
    unsupported in this yt-dlp version (same category of bug as the earlier
    ytmsearch one), which is exactly why New Releases kept coming back
    empty. Regular "ytsearch" is the one prefix we've confirmed actually
    works, so we use it for every order now. Freshness for "New Releases"
    still comes through fine since the frontend already appends
    "new release"/year keywords to those specific queries.

    Over-fetches 2x the raw results since mix/junk filtering throws a good
    chunk away - without this, a request for 20 songs could come back with
    only 4-6 after filtering, which is exactly the "handful of songs"
    problem being reported."""
    query = query.strip()
    if not query:
        return []
    search_query = f"{query} official audio"
    raw_limit = limit * 2
    try:
        with yt_dlp.YoutubeDL(ydl_opts(extract_flat="in_playlist")) as ydl:
            info = ydl.extract_info(f"ytsearch{raw_limit}:{search_query}", download=False)
        entries = info.get("entries") or []
        tracks = [t for t in (yt_entry_to_track(e, allow_mixes=allow_mixes) for e in entries) if t]
        tracks = tracks[:limit]
        print(f">>> yt_search query={query!r} order={order} allow_mixes={allow_mixes}: {len(entries)} raw entries -> {len(tracks)} after filtering")
        return tracks
    except Exception as e:
        import traceback
        print(f"!!! yt_search FAILED for query={query!r} order={order}: {e}")
        traceback.print_exc()
        return []


# ---------------------------------------------------------------------------
# Cache: download-once, serve-many
# ---------------------------------------------------------------------------

def cache_path(vid, ext="m4a"):
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", vid)
    return os.path.join(CACHE_DIR, f"{safe}.{ext}")


def find_cached_native(vid):
    """Native-format cache (no transcoding) used for streaming - much
    faster than the mp3 path since there's no ffmpeg re-encode pass."""
    safe = re.sub(r"[^a-zA-Z0-9_-]", "", vid)
    for f in os.listdir(CACHE_DIR):
        if f.startswith(safe + ".") and not f.endswith(".mp3"):
            return os.path.join(CACHE_DIR, f)
    return None


def resolve_source_url(vid):
    """Figure out the real URL yt-dlp should download from, given a videoId."""
    if vid in _track_url_cache:
        return _track_url_cache[vid]
    if YT_ID_RE.match(vid):
        return f"https://www.youtube.com/watch?v={vid}"
    return None


def _reject_long_or_live(info_dict, *, incomplete=False):
    """yt-dlp match_filter: runs after full video info is fetched but
    BEFORE any bytes are downloaded, so a 3-hour mix gets rejected
    instantly instead of hanging for hours mid-download.

    Still blocks genuinely LIVE (currently airing) streams always - those
    never finish downloading regardless of source. But a long *recorded*
    video that the person reached via the DJ Mixes tab is allowed through,
    since a 1-2 hour mix is exactly what that tab is supposed to play."""
    if info_dict.get("is_live"):
        return "skipping - currently live, can't be fully downloaded"
    vid = info_dict.get("id")
    if vid in _known_mix_ids:
        return None  # explicitly allowed - this came from the DJ Mixes tab
    if info_dict.get("was_live"):
        return "skipping - this is a live stream, not a song"
    duration = info_dict.get("duration")
    if duration and duration > MAX_TRACK_SECONDS:
        return f"skipping - {duration}s is too long to be a single song"
    return None  # allow the download


def ensure_cached(vid):
    """Streaming path: download the native best-audio format with NO
    transcoding. This is what makes playback start quickly - ffmpeg
    re-encoding the whole track was the slow part before."""
    existing = find_cached_native(vid)
    if existing and os.path.getsize(existing) > 1000:
        return existing

    source_url = resolve_source_url(vid)
    if not source_url:
        return None

    safe = re.sub(r"[^a-zA-Z0-9_-]", "", vid)
    tmp_template = os.path.join(CACHE_DIR, f"{safe}.%(ext)s")

    # Some videos don't have a clean "bestaudio" stream available - retry
    # with progressively looser format selectors instead of giving up on
    # the first "Requested format is not available" error.
    format_attempts = ["bestaudio/best", "best", "worst"]
    for fmt in format_attempts:
        dl_opts = ydl_opts(format=fmt, outtmpl=tmp_template, match_filter=_reject_long_or_live)
        try:
            with yt_dlp.YoutubeDL(dl_opts) as ydl:
                ydl.download([source_url])
            result = find_cached_native(vid)
            if result:
                return result
        except Exception as e:
            print(f"!!! download attempt failed for {vid} with format={fmt!r}: {e}")
            continue

    return None


def ensure_mp3(vid):
    """Download path only: transcode the already-cached native file to mp3
    on demand, locally - fast, since it's not re-downloading anything."""
    mp3_path = cache_path(vid, "mp3")
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 1000:
        return mp3_path

    native_path = ensure_cached(vid)
    if not native_path:
        return None

    import subprocess
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", native_path, "-vn", "-ab", "192k", mp3_path],
            check=True, capture_output=True, timeout=120,
        )
    except Exception:
        return None
    return mp3_path if os.path.exists(mp3_path) else None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/search")
def search():
    q = request.args.get("q", "")
    limit = int(request.args.get("limit", 20))
    order = request.args.get("order", "relevance")
    return jsonify({"tracks": yt_search(q, limit=limit, order=order)})


def normalize_name(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def uploaded_by_artist(track, requested_name):
    """For artist pages specifically: only keep results actually uploaded
    by that artist's own channel, not videos that just mention their name
    in the title (news coverage, comedy skits, reaction/commentary
    channels). Checks the parsed artist field, which usually reflects the
    channel/uploader for non 'Artist - Title' formatted videos."""
    candidate = normalize_name(track.get("artist"))
    query = normalize_name(requested_name)
    if not candidate or not query:
        return False
    return query in candidate or candidate in query


POPULAR_ARTISTS = ['Rayvanny', 'Diamond Platnumz', 'Burna Boy', 'Wizkid', 'Davido', 'Sauti Sol', 'Khaligraph Jones', 'Mejja', 'Bien', 'Nyashinski', 'Harmonize', 'Nandy', 'Zuchu', 'Bahati', 'Otile Brown', 'Alikiba', 'Marioo', 'Jux', 'Mbosso', 'Whozu', 'Tems', 'Asake', 'Rema', 'Ayra Starr', 'Kizz Daniel', 'Focalistic', 'Tyla', 'Willy Paul']


@app.get("/api/suggest")
def suggest():
    """Typo-tolerant artist suggestions (edit distance via difflib), fast and local."""
    import difflib
    q = request.args.get("q", "").strip()[:60]
    nq = normalize_name(q)
    if len(nq) < 2:
        return jsonify({"suggestions": [], "corrected": None})
    scored = []
    for name in POPULAR_ARTISTS:
        nn = normalize_name(name)
        first = normalize_name(name.split()[0])
        if nn.startswith(nq) or first.startswith(nq):
            score = 1.0
        else:
            score = max(difflib.SequenceMatcher(None, nq, nn).ratio(), difflib.SequenceMatcher(None, nq, first).ratio())
        if score >= 0.72:
            scored.append((score, name))
    scored.sort(key=lambda x: -x[0])
    out = [n for _, n in scored[:6]]
    exact = any(normalize_name(n) == nq or normalize_name(n).startswith(nq) for n in out)
    corrected = out[0] if out and not exact else None
    return jsonify({"suggestions": [{"name": n, "type": "artist"} for n in out], "corrected": corrected})



@app.get("/api/artist")
def artist():
    name = request.args.get("name", "")
    # Bumped from 30 - artist pages were showing "a handful of old songs"
    # because the previous limit + filtering losses left too little.
    limit = int(request.args.get("limit", 50))
    # Over-fetch since the channel-match filter below throws more away.
    raw_tracks = yt_search(f"{name} official", limit=limit * 2)
    tracks = [t for t in raw_tracks if uploaded_by_artist(t, name)][:limit]
    print(f">>> /api/artist name={name!r}: {len(raw_tracks)} raw -> {len(tracks)} actually from that channel")
    return jsonify({"tracks": tracks})


@app.get("/api/mixes")
def mixes():
    """The ONE place mix/compilation content is allowed - this is the
    dedicated DJ Mixes tab, so allow_mixes=True here is intentional and
    correct, unlike everywhere else in the app.

    Personalizes to the person's own selected genre/followed artist when
    provided (from Settings), so someone who follows Bongo/Rumba artists
    sees mixes for that, not a random genre every time. Falls back to a
    random seed only when they haven't set any preference yet."""
    limit = int(request.args.get("limit", 20))
    genre = request.args.get("genre", "").strip()
    artist_pref = request.args.get("artist", "").strip()
    if artist_pref:
        seed = f"{artist_pref} mix latest"
        title = f"{artist_pref} Mixes"
    elif genre:
        seed = f"{genre} mix latest 2026"
        title = f"Latest {genre} Mixes"
    else:
        seed = random.choice(MIX_SEEDS)
        title = seed.title()
    # Over-fetch since we're about to filter more strictly than yt_search
    # does on its own - allow_mixes=True only stops REJECTING mix-titled
    # results, it doesn't REQUIRE them, so regular single-song videos that
    # happen to match the search were leaking into this tab. Requiring an
    # actual mix/compilation-style title fixes that.
    raw = yt_search(seed, limit=limit * 3, allow_mixes=True)
    tracks = [t for t in raw if MIX_TITLE_PATTERNS.search(t.get("title", ""))][:limit]

    # A single artist rarely has actual "DJ mix" style content about
    # themselves - real mixes are almost always multi-artist compilations.
    # Rather than leaving the person stuck on an empty tab, fall back to
    # their genre preference, then a random mix seed, so DJ Mixes always
    # has something to show.
    if not tracks and artist_pref:
        if genre:
            seed = f"{genre} mix latest 2026"
            title = f"Latest {genre} Mixes"
        else:
            seed = random.choice(MIX_SEEDS)
            title = seed.title()
        raw = yt_search(seed, limit=limit * 3, allow_mixes=True)
        tracks = [t for t in raw if MIX_TITLE_PATTERNS.search(t.get("title", ""))][:limit]

    return jsonify({"tracks": tracks, "title": title})


def resolve_live_url(vid, allow_long=False):
    """Get the direct playable URL WITHOUT downloading the file to disk
    first, so playback can start immediately. Cached briefly since
    resolving costs several real seconds (webpage fetch + JS challenge).
    Returns (url, ext) so callers know what file extension to cache as."""
    now = time.time()
    cached = _mix_url_cache.get(vid)
    if cached and cached[1] > now:
        return cached[0]

    source_url = resolve_source_url(vid)
    if not source_url:
        return None
    try:
        with yt_dlp.YoutubeDL(ydl_opts(format="bestaudio/best")) as ydl:
            info = ydl.extract_info(source_url, download=False)
        if not allow_long:
            if info.get("is_live") or info.get("was_live"):
                print(f"!!! resolve_live_url rejected {vid}: live stream")
                return None
            duration = info.get("duration")
            if duration and duration > MAX_TRACK_SECONDS:
                print(f"!!! resolve_live_url rejected {vid}: {duration}s too long")
                return None
        url = info.get("url")
        ext = info.get("ext", "m4a")
        if url:
            _mix_url_cache[vid] = ((url, ext), now + MIX_URL_CACHE_TTL)
        return (url, ext) if url else None
    except Exception as e:
        print(f"!!! resolve_live_url failed for {vid}: {e}")
        return None


@app.get("/api/stream/<vid>")
def stream(vid):
    """Cache hit (song played before, by anyone): instant, serves the
    already-downloaded file via /api/proxy.

    Cache miss on a SONG: returns /api/relay-and-cache - streams live to
    the listener immediately AND writes the same bytes to disk in the
    background, so playback starts fast now while still being fully
    cached for the next person by the time it finishes.

    Mixes: always live-relay only, deliberately never cached to disk -
    a 90-minute file isn't worth the storage for what's usually a
    one-time listen (kept simple on purpose, decided earlier).

    ?mix=1 marks a request as a mix even without prior registration in
    _known_mix_ids - this is what lets DJ-uploaded mixes (from the
    Supabase dj_mixes table, not the old search-based discovery) get the
    same long-duration allowance and live-relay treatment."""
    is_mix = vid in _known_mix_ids or request.args.get("mix") == "1"
    if is_mix:
        resolved = resolve_live_url(vid, allow_long=True)
        if not resolved:
            return jsonify({"error": "could not resolve this mix"}), 404
        direct_url, _ = resolved
        return jsonify({"url": direct_url, "videoId": vid, "live": True})

    existing = find_cached_native(vid)
    if existing and os.path.getsize(existing) > 1000:
        base = request.url_root.rstrip("/")
        return jsonify({"url": f"{base}/api/proxy/{vid}", "videoId": vid})

    base = request.url_root.rstrip("/")
    return jsonify({"url": f"{base}/api/relay-and-cache/{vid}", "videoId": vid, "live": True})


@app.get("/api/relay-and-cache/<vid>")
def relay_and_cache(vid):
    """The hybrid: streams bytes to the listener as they arrive AND writes
    those same bytes to the cache file at the same time. First listener
    gets fast start; the file is fully cached the moment it finishes, so
    every play after that (even before this one ends, if it races) is
    instant via the normal /api/proxy path."""
    existing = find_cached_native(vid)
    if existing and os.path.getsize(existing) > 1000:
        # someone else's request already finished caching this in the time
        # it took to get here - just serve the real cached file instead
        ext = os.path.splitext(existing)[1].lstrip(".")
        mimetype = {"m4a": "audio/mp4", "webm": "audio/webm", "opus": "audio/opus"}.get(ext, "audio/mpeg")
        return send_file(existing, mimetype=mimetype, conditional=True)

    resolved = resolve_live_url(vid, allow_long=False)
    if not resolved:
        return jsonify({"error": "could not resolve this track"}), 404
    direct_url, ext = resolved

    final_path = cache_path(vid, ext)
    tmp_path = final_path + ".part"

    try:
        upstream = requests.get(direct_url, stream=True, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0"}, proxies=REQUESTS_PROXIES)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    content_type = upstream.headers.get("Content-Type") or \
        {"m4a": "audio/mp4", "webm": "audio/webm", "opus": "audio/opus"}.get(ext, "audio/mpeg")

    def generate():
        wrote_ok = False
        try:
            with open(tmp_path, "wb") as f:
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        yield chunk
            wrote_ok = True
        finally:
            if wrote_ok:
                try:
                    os.replace(tmp_path, final_path)  # now cached for next time
                except Exception as e:
                    print(f"!!! could not finalize cache for {vid}: {e}")
            else:
                try:
                    os.remove(tmp_path)  # partial/failed download - don't leave junk
                except Exception:
                    pass

    # NOTE: deliberately NOT claiming "Accept-Ranges: bytes" here - this
    # endpoint always streams from byte 0 and doesn't actually support
    # arbitrary range requests (that would mean seeking mid-write into a
    # file that's still being cached, real complexity we skipped). Claiming
    # range support we don't honor was causing the browser to expect
    # proper 206 partial responses it never got - audio would "play" per
    # the UI state but produce no actual sound. Being honest that this
    # stream is sequential-only fixes that.
    resp_headers = {}
    if "Content-Length" in upstream.headers:
        resp_headers["Content-Length"] = upstream.headers["Content-Length"]
    return Response(stream_with_context(generate()), status=200,
                     content_type=content_type, headers=resp_headers)


@app.get("/api/proxy/<vid>")
def proxy(vid):
    path = ensure_cached(vid)
    if not path:
        return jsonify({"error": "track unavailable"}), 404
    ext = os.path.splitext(path)[1].lstrip(".")
    mimetype = {"m4a": "audio/mp4", "webm": "audio/webm", "opus": "audio/opus"}.get(ext, "audio/mpeg")
    # conditional=True makes Flask handle Range headers automatically, so
    # scrubbing the progress bar just works - no custom relay code needed.
    return send_file(path, mimetype=mimetype, conditional=True)


@app.get("/api/download/<vid>")
def download(vid):
    title = request.args.get("title", vid)
    artist = request.args.get("artist", "")
    thumbnail = request.args.get("thumb", "")
    path = ensure_mp3(vid)
    if not path:
        return jsonify({"error": "track unavailable"}), 404
    tag_audio_file(path, title, artist, thumbnail)
    safe_name = re.sub(r'[\\/*?:"<>|]', "", f"{artist} - {title}".strip(" -")) or vid
    return send_file(path, as_attachment=True, download_name=f"{safe_name}.mp3")


_app_icon_bytes = None
def get_app_icon_bytes():
    """The bundled Sona Play logo, used as fallback cover art when a
    track has no thumbnail of its own - so every download at least looks
    branded instead of showing a blank/generic file icon."""
    global _app_icon_bytes
    if _app_icon_bytes is not None:
        return _app_icon_bytes
    for path in (
        os.path.join(os.path.dirname(__file__), "..", "icons", "icon-512.png"),
        os.path.join(os.path.dirname(__file__), "icons", "icon-512.png"),
    ):
        try:
            with open(path, "rb") as f:
                _app_icon_bytes = f.read()
                return _app_icon_bytes
        except Exception:
            continue
    _app_icon_bytes = b""
    return _app_icon_bytes


def tag_audio_file(path, title, artist, thumbnail_url):
    """Embeds title/artist tags and cover art into the downloaded file -
    the track's own thumbnail when available, otherwise the Sona Play logo,
    so downloads look like a real song file in any music player instead of
    a bare, unlabeled mp3."""
    if not MUTAGEN_OK:
        return
    cover_bytes = None
    if thumbnail_url:
        try:
            r = requests.get(thumbnail_url, timeout=8)
            if r.ok:
                cover_bytes = r.content
        except Exception:
            pass
    if not cover_bytes:
        cover_bytes = get_app_icon_bytes()

    try:
        if path.lower().endswith(".mp3"):
            try:
                tags = ID3(path)
            except ID3NoHeaderError:
                tags = ID3()
            tags["TIT2"] = TIT2(encoding=3, text=title or "Unknown")
            tags["TPE1"] = TPE1(encoding=3, text=artist or "Unknown Artist")
            if cover_bytes:
                tags["APIC"] = APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover_bytes)
            tags.save(path)
        elif path.lower().endswith(".m4a"):
            tags = MP4(path)
            tags["\xa9nam"] = [title or "Unknown"]
            tags["\xa9ART"] = [artist or "Unknown Artist"]
            if cover_bytes:
                tags["covr"] = [MP4Cover(cover_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
            tags.save(path)
    except Exception as e:
        print(f"!!! tagging failed for {path}: {e}")


@app.get("/api/relay")
def relay():
    """Live-relays audio bytes for DJ mixes, forwarding Range requests both
    ways so the browser can seek and - critically - so it gets a valid
    Content-Range header back. Without that header, a 206 response is
    technically invalid: the browser can't determine the audio's total
    duration or which bytes it received, and silently refuses to play it
    even though the data arrived fine. That was the exact cause of mixes
    showing "0:00" duration with no sound."""
    target = request.args.get("url", "")
    if not target:
        return jsonify({"error": "missing url"}), 400
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        if request.headers.get("Range"):
            headers["Range"] = request.headers["Range"]
        upstream = requests.get(target, stream=True, timeout=30, headers=headers, proxies=REQUESTS_PROXIES)

        def generate():
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk

        resp_headers = {}
        for h in ("Content-Range", "Content-Length", "Accept-Ranges"):
            if h in upstream.headers:
                resp_headers[h] = upstream.headers[h]
        resp_headers.setdefault("Accept-Ranges", "bytes")

        status = upstream.status_code if upstream.status_code in (200, 206) else 200
        return Response(stream_with_context(generate()), status=status,
                         content_type=upstream.headers.get("Content-Type", "audio/webm"),
                         headers=resp_headers)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.post("/api/account/delete")
def delete_account():
    """Deletes the requesting person's own account permanently. Verifies
    their access token first (so nobody can delete someone else's account),
    then uses the service role key to actually perform the deletion via
    Supabase's admin API."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "missing auth token"}), 401
    access_token = auth_header[len("Bearer "):]

    # Step 1: verify the token and find out who's making this request
    try:
        verify_resp = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"Authorization": f"Bearer {access_token}", "apikey": SUPABASE_ANON_KEY},
            timeout=10,
        )
        if verify_resp.status_code != 200:
            return jsonify({"error": "invalid or expired session"}), 401
        user_id = verify_resp.json().get("id")
        if not user_id:
            return jsonify({"error": "could not identify user"}), 401
    except Exception as e:
        return jsonify({"error": f"could not verify session: {e}"}), 502

    if not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({
            "error": "Account deletion isn't configured yet. Set SUPABASE_SERVICE_ROLE_KEY "
                     "on the server (Supabase dashboard -> Settings -> API -> service_role key)."
        }), 501

    # Step 2: actually delete, using the admin-only service role key
    try:
        del_resp = requests.delete(
            f"{SUPABASE_URL}/auth/v1/admin/users/{user_id}",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
            },
            timeout=10,
        )
        if del_resp.status_code not in (200, 204):
            return jsonify({"error": f"deletion failed: {del_resp.text}"}), 502
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"error": f"deletion failed: {e}"}), 502


ADMIN_KEY = os.environ.get("ADMIN_KEY", "")


def _require_admin_key(req):
    key = req.headers.get("X-Admin-Key", "")
    return bool(ADMIN_KEY) and hmac.compare_digest(str(key or ""), ADMIN_KEY)


def _list_all_users():
    if not SUPABASE_SERVICE_ROLE_KEY:
        return None
    users, page = [], 1
    while True:
        r = requests.get(
            f"{SUPABASE_URL}/auth/v1/admin/users",
            headers={
                "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": SUPABASE_SERVICE_ROLE_KEY,
            },
            params={"page": page, "per_page": 200},
            timeout=15,
        )
        if r.status_code != 200:
            break
        batch = r.json().get("users", [])
        users.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return users


@app.get("/api/admin/stats")
def admin_stats():
    if not _require_admin_key(request):
        return jsonify({"error": "unauthorized"}), 401
    users = _list_all_users()
    if users is None:
        return jsonify({"error": "SUPABASE_SERVICE_ROLE_KEY not configured"}), 500
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_ago = now - timedelta(days=30)

    def _parse(u):
        try:
            return datetime.fromisoformat(u["created_at"].replace("Z", "+00:00"))
        except Exception:
            return None

    new_today = sum(1 for u in users if (_parse(u) or now) >= today_start)
    new_month = sum(1 for u in users if (_parse(u) or now) >= month_ago)
    return jsonify({"total": len(users), "new_today": new_today, "new_last_30d": new_month})


@app.get("/api/admin/users")
def admin_users():
    if not _require_admin_key(request):
        return jsonify({"error": "unauthorized"}), 401
    users = _list_all_users()
    if users is None:
        return jsonify({"error": "SUPABASE_SERVICE_ROLE_KEY not configured"}), 500
    users_sorted = sorted(users, key=lambda u: u.get("created_at", ""), reverse=True)
    out = [
        {
            "id": u.get("id"),
            "email": u.get("email"),
            "created_at": u.get("created_at"),
            "last_sign_in_at": u.get("last_sign_in_at"),
        }
        for u in users_sorted[:200]
    ]
    return jsonify({"users": out})


@app.get("/api/admin/health")
def admin_health():
    if not _require_admin_key(request):
        return jsonify({"error": "unauthorized"}), 401
    try:
        ver = yt_dlp.version.__version__
        ytdlp_ok = True
    except Exception:
        ver = "unknown"
        ytdlp_ok = False
    return jsonify({
        "status": "ok",
        "ytdlp_ok": ytdlp_ok,
        "ytdlp_version": ver,
        "cached_tracks": len(os.listdir(CACHE_DIR)) if os.path.exists(CACHE_DIR) else 0,
    })


@app.get("/api/admin/config")
def admin_get_config():
    if not _require_admin_key(request):
        return jsonify({"error": "unauthorized"}), 401
    key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/app_config?select=*&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=10,
    )
    rows = r.json() if r.status_code == 200 else []
    return jsonify(rows[0] if rows else {})


@app.post("/api/admin/config")
def admin_set_config():
    if not _require_admin_key(request):
        return jsonify({"error": "unauthorized"}), 401
    if not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({"error": "SUPABASE_SERVICE_ROLE_KEY not configured"}), 500
    body = request.get_json(force=True, silent=True) or {}
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/app_config?id=eq.1",
        headers={
            "apikey": SUPABASE_SERVICE_ROLE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        },
        json=body,
        timeout=10,
    )
    ok = r.status_code in (200, 201)
    return jsonify(r.json() if ok else {"error": r.text}), (200 if ok else 502)


@app.get("/api/health")
def health():
    cookie_active = bool(YDL_BASE_OPTS.get("cookiefile"))
    cookie_path = YDL_BASE_OPTS.get("cookiefile", "")
    cookie_size = 0
    if cookie_active and os.path.exists(cookie_path):
        cookie_size = os.path.getsize(cookie_path)
    return jsonify({
        "status": "ok",
        "cached_tracks": len(os.listdir(CACHE_DIR)),
        "cookie_active": cookie_active,
        "cookie_path": cookie_path,
        "cookie_size_bytes": cookie_size,
        "cookie_file_b64_env_set": bool(os.environ.get("COOKIE_FILE_B64", "")),
        "cookie_file_env_set": bool(os.environ.get("COOKIE_FILE", "")),
    })



# ---------------------------------------------------------------------------
# Scheduled job: new releases from followed artists + pending admin broadcasts.
# Call every ~30 min from an external scheduler (free Render instances sleep):
#   POST /api/jobs/check-releases   header X-Cron-Secret: <CRON_SECRET>
# ---------------------------------------------------------------------------
CRON_SECRET = os.environ.get("CRON_SECRET", "")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "admin@example.com")


def _sb(method, path, **kw):
    key = SUPABASE_SERVICE_ROLE_KEY
    h = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    h.update(kw.pop("headers", {}))
    return requests.request(method, f"{SUPABASE_URL}/rest/v1/{path}", headers=h, timeout=20, **kw)


def _push(user_ids, payload):
    if not VAPID_PRIVATE_KEY or not user_ids:
        return 0
    try:
        import json as _json
        from pywebpush import webpush, WebPushException
    except ImportError:
        return 0
    subs = _sb("GET", f"push_subscriptions?user_id=in.({','.join(user_ids)})&select=id,endpoint,p256dh,auth").json()
    sent = 0
    for s in subs:
        try:
            webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}},
                    data=_json.dumps(payload), vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": "mailto:" + VAPID_EMAIL})
            sent += 1
        except WebPushException as e:
            if getattr(e.response, "status_code", 0) in (404, 410):
                _sb("DELETE", f"push_subscriptions?id=eq.{s['id']}")
        except Exception:
            pass
    return sent


def _push_pending_broadcasts():
    """Send phone notifications for admin broadcasts not pushed yet. Returns how many rows were handled."""
    pend = _sb("GET", "notifications?kind=eq.broadcast&pushed=eq.false&select=id,user_id,title,body&limit=2000").json()
    if not isinstance(pend, list):
        return 0
    groups = {}
    for n in pend:
        groups.setdefault((n["title"], n["body"]), []).append(n)
    for (title, body), items in groups.items():
        _push([i["user_id"] for i in items], {"kind": "broadcast", "title": title, "body": body})
        _sb("PATCH", f"notifications?id=in.({','.join(i['id'] for i in items)})", json={"pushed": True})
    return len(pend)


def _admin_user(req):
    """The Supabase user if the bearer token belongs to an admin (the database's is_admin() decides)."""
    auth = req.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or not SUPABASE_URL:
        return None
    try:
        h = {"Authorization": auth, "apikey": SUPABASE_ANON_KEY}
        u = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers=h, timeout=8)
        if u.status_code != 200:
            return None
        r = requests.post(f"{SUPABASE_URL}/rest/v1/rpc/is_admin", headers={**h, "Content-Type": "application/json"}, json={}, timeout=8)
        return u.json() if r.status_code == 200 and r.json() is True else None
    except Exception:
        return None


def _auth_admin(method, path, **kw):
    key = SUPABASE_SERVICE_ROLE_KEY
    h = {"apikey": key, "Authorization": "Bearer " + key, "Content-Type": "application/json"}
    return requests.request(method, f"{SUPABASE_URL}/auth/v1/admin/{path}", headers=h, timeout=20, **kw)


@app.post("/api/admin/test-alert")
def admin_test_alert():
    me = _admin_user(request)
    if not me:
        return jsonify({"error": "unauthorized"}), 401
    uid = me.get("id")
    title, body = "Test alert", "If you can read this, alerts work."
    saved = False
    try:
        r = _sb("POST", "notifications", json=[{"user_id": uid, "kind": "broadcast", "title": title, "body": body, "pushed": True}])
        saved = r.status_code in (200, 201, 204)
    except Exception:
        pass
    devices = 0
    try:
        d = _sb("GET", f"push_subscriptions?user_id=eq.{uid}&select=id").json()
        devices = len(d) if isinstance(d, list) else 0
    except Exception:
        pass
    sent = _push([uid], {"kind": "broadcast", "title": title, "body": body})
    return jsonify({"saved": saved, "push_ready": bool(VAPID_PRIVATE_KEY), "devices": devices, "push_sent": sent})


@app.post("/api/admin/push-now")
def admin_push_now():
    if not _admin_user(request):
        return jsonify({"error": "unauthorized"}), 401
    return jsonify({"pushed_rows": _push_pending_broadcasts()})


@app.post("/api/admin/user-create")
def admin_user_create():
    if not _admin_user(request):
        return jsonify({"error": "unauthorized"}), 401
    if not SUPABASE_SERVICE_ROLE_KEY:
        return jsonify({"error": "SUPABASE_SERVICE_ROLE_KEY not configured"}), 500
    b = request.get_json(silent=True) or {}
    email = str(b.get("email", "")).strip().lower()
    password = str(b.get("password", ""))
    name = str(b.get("display_name", "")).strip()[:60] or email.split("@")[0]
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"error": "Enter a valid email"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    r = _auth_admin("POST", "users", json={"email": email, "password": password, "email_confirm": True,
                                           "user_metadata": {"display_name": name}})
    if r.status_code not in (200, 201):
        try:
            msg = r.json().get("msg") or r.json().get("message") or r.text
        except Exception:
            msg = r.text
        return jsonify({"error": str(msg)[:200]}), 400
    return jsonify({"ok": True, "id": r.json().get("id")})


@app.post("/api/admin/user-delete")
def admin_user_delete():
    me = _admin_user(request)
    if not me:
        return jsonify({"error": "unauthorized"}), 401
    uid = str((request.get_json(silent=True) or {}).get("id", ""))
    if not re.match(r"^[0-9a-fA-F-]{36}$", uid):
        return jsonify({"error": "bad id"}), 400
    if uid == me.get("id"):
        return jsonify({"error": "You cannot delete your own admin account here"}), 400
    adm = _sb("GET", f"admins?user_id=eq.{uid}&select=user_id").json()
    if isinstance(adm, list) and adm:
        return jsonify({"error": "That user is an admin. Remove their admin rights first."}), 400
    r = _auth_admin("DELETE", f"users/{uid}")
    if r.status_code not in (200, 204):
        return jsonify({"error": f"delete failed: {r.text[:160]}"}), 502
    return jsonify({"ok": True})


@app.post("/api/jobs/check-releases")
def job_check_releases():
    if not CRON_SECRET or not hmac.compare_digest(request.headers.get("X-Cron-Secret", ""), CRON_SECRET):
        return jsonify({"error": "forbidden"}), 403
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        return jsonify({"error": "not configured"}), 500
    import datetime as _dt
    follows = _sb("GET", "follows?select=user_id,artist_name&kind=eq.artist&limit=5000").json()
    muted = {r["user_id"] for r in _sb("GET", "user_prefs?select=user_id&notify_new_songs=eq.false").json()}
    state = {r["artist_name"]: r for r in _sb("GET", "artist_state?select=artist_name,last_seen_video_id,checked_at").json()}
    by = {}
    for f in follows:
        by.setdefault(f["artist_name"], []).append(f["user_id"])
    new_songs = 0
    for artist in sorted(by, key=lambda a: (state.get(a) or {}).get("checked_at") or "")[:40]:
        try:
            tracks = [t for t in yt_search(f"{artist} official audio", limit=5, order="date") if uploaded_by_artist(t, artist)]
        except Exception:
            continue
        if not tracks:
            continue
        t = tracks[0]
        vid = t["videoId"]
        last = (state.get(artist) or {}).get("last_seen_video_id")
        _sb("POST", "artist_state?on_conflict=artist_name", headers={"Prefer": "resolution=merge-duplicates"},
            json={"artist_name": artist, "last_seen_video_id": vid, "checked_at": _dt.datetime.utcnow().isoformat() + "Z"})
        if not last or last == vid:      # first sighting only records the song, no alert
            continue
        users = [u for u in by[artist] if u not in muted]
        if users:
            _sb("POST", "notifications", json=[{"user_id": u, "artist": artist, "video_id": vid, "title": t.get("title"),
                "thumbnail": t.get("thumbnail"), "kind": "release", "pushed": True} for u in users])
            _push(users, {"artist": artist, "title": t.get("title"), "video_id": vid, "thumbnail": t.get("thumbnail")})
            new_songs += 1
    pend = _push_pending_broadcasts()
    return jsonify({"artists_checked": min(len(by), 40), "new_songs": new_songs, "broadcasts_pushed": pend})



import threading as _th, queue as _q
_warm_q = _q.Queue()
_warming = set()
def _warm_one(vid):
    ex = find_cached_native(vid)
    if ex and os.path.getsize(ex) > 1000:
        return
    resolved = resolve_live_url(vid, allow_long=False)
    if not resolved:
        return
    url, ext = resolved
    final = cache_path(vid, ext)
    tmp = final + ".part"
    r = requests.get(url, stream=True, timeout=30, headers={"User-Agent": "Mozilla/5.0"}, proxies=REQUESTS_PROXIES)
    with open(tmp, "wb") as f:
        for c in r.iter_content(chunk_size=64 * 1024):
            if c:
                f.write(c)
    os.replace(tmp, final)
def _warm_loop():
    while True:
        v = _warm_q.get()
        try:
            _warm_one(v)
        except Exception as e:
            print(f"warm failed {v}: {e}")
        finally:
            _warming.discard(v)
_th.Thread(target=_warm_loop, daemon=True).start()
@app.post("/api/warm")
def warm_songs():
    ids = (request.get_json(silent=True) or {}).get("ids", [])
    n = 0
    for v in ids[:6]:
        if isinstance(v, str) and re.fullmatch(r"[\w-]{11}", v) and v not in _warming and _warm_q.qsize() < 16:
            _warming.add(v)
            _warm_q.put(v)
            n += 1
    return jsonify({"queued": n})
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1", threaded=True)
