"""Security layer for the Sona Play API: CORS allow-list, rate limits, input checks, headers."""
import os, re, time, threading
from collections import defaultdict, deque
from flask import request, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix

_raw = os.environ.get("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in _raw.split(",") if o.strip()] or [
    "http://localhost:8888", "http://localhost:5500", "http://127.0.0.1:5500"]

VID_RE = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
# (path prefix, max requests per minute per IP) - first match wins
LIMITS = [("/api/admin", 20), ("/api/account", 5), ("/api/download", 15),
          ("/api/search", 90), ("/api/", 300)]
_hits, _lock = defaultdict(deque), threading.Lock()


def _limited(prefix, limit, ip):
    now = time.time()
    with _lock:
        if len(_hits) > 20000:
            _hits.clear()
        q = _hits[(prefix, ip)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
    return False


def init_security(app):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)
    app.config["MAX_CONTENT_LENGTH"] = 1_000_000

    @app.before_request
    def _guard():
        if request.method == "OPTIONS":
            return None
        path = request.path
        for prefix, limit in LIMITS:
            if path.startswith(prefix):
                if _limited(prefix, limit, request.remote_addr or "?"):
                    return jsonify({"error": "Too many requests, slow down"}), 429
                break
        vid = (request.view_args or {}).get("vid")
        if vid is not None and not VID_RE.match(vid):
            return jsonify({"error": "Bad video id"}), 400
        return None

    @app.after_request
    def _headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cross-Origin-Resource-Policy"] = "cross-origin"  # audio is played from another origin
        if request.path.startswith("/api/admin") or request.path.startswith("/api/account"):
            resp.headers["Cache-Control"] = "no-store"
        return resp
