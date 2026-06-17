import os, json, hashlib, re, logging
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_file, Response, stream_with_context
from flask_cors import CORS
import requests

logging.basicConfig(level=logging.INFO)
log = logging.getLogger('sona')
app = Flask(__name__)
CORS(app, origins=['*'])
CACHE_DIR = Path(os.getenv('CACHE_DIR', '/tmp/sona_cache'))
PORT = int(os.getenv('PORT', 5000))
YT_KEY = os.getenv('YOUTUBE_API_KEY', '')
CACHE_DIR.mkdir(parents=True, exist_ok=True)
_cache = {}

def cache_get(k):
    if k in _cache:
        d, e = _cache[k]
        if datetime.now() < e: return d
        del _cache[k]
    return None

def cache_set(k, d, m=30):
    _cache[k] = (d, datetime.now() + timedelta(minutes=m))

# ── INTERNET ARCHIVE SEARCH ──────────────────────────────────────────────────
def search_archive(query, limit=10):
    try:
        r = requests.get('https://archive.org/advancedsearch.php', params={
            'q': f'({query}) AND mediatype:audio',
            'mediatype': 'audio',
            'output': 'json',
            'rows': limit,
            'fl': 'identifier,title,creator,year,format',
            'sort': 'downloads desc',
        }, timeout=10)
        docs = r.json().get('response', {}).get('docs', [])
        tracks = []
        for doc in docs:
            iid = doc.get('identifier', '')
            if not iid: continue
            title = doc.get('title', 'Unknown')
            artist = doc.get('creator', 'Unknown')
            if isinstance(artist, list): artist = artist[0]
            tracks.append({
                'videoId': iid,
                'title': title,
                'artist': str(artist),
                'thumbnail': f'https://archive.org/services/img/{iid}',
                'duration': '',
                'url': f'https://archive.org/details/{iid}',
                'source': 'archive',
            })
        return tracks
    except Exception as e:
        log.error(f'Archive search: {e}')
        return []

def get_archive_files(identifier):
    """Get audio files for an Archive.org item."""
    k = f'files:{identifier}'
    c = cache_get(k)
    if c: return c
    try:
        r = requests.get(f'https://archive.org/metadata/{identifier}', timeout=10)
        data = r.json()
        files = data.get('files', [])
        audio_exts = ['.mp3', '.ogg', '.flac', '.wav', '.m4a', '.opus']
        audio_files = [f for f in files if any(f.get('name', '').lower().endswith(ext) for ext in audio_exts)]
        # Prefer mp3
        mp3 = [f for f in audio_files if f.get('name', '').lower().endswith('.mp3')]
        best = mp3[0] if mp3 else (audio_files[0] if audio_files else None)
        if best:
            url = f'https://archive.org/download/{identifier}/{best["name"]}'
            cache_set(k, url, m=60)
            return url
    except Exception as e:
        log.error(f'Archive files: {e}')
    return ''

# ── YOUTUBE API SEARCH (fallback) ─────────────────────────────────────────────
def search_youtube(query, limit=10):
    if not YT_KEY: return []
    try:
        r = requests.get('https://www.googleapis.com/youtube/v3/search', params={
            'part': 'snippet', 'q': query, 'type': 'video',
            'videoCategoryId': '10', 'maxResults': limit, 'key': YT_KEY,
        }, timeout=10)
        items = r.json().get('items', [])
        tracks = []
        for item in items:
            vid = item.get('id', {}).get('videoId', '')
            if not vid: continue
            sn = item.get('snippet', {})
            tracks.append({
                'videoId': vid,
                'title': sn.get('title', 'Unknown'),
                'artist': sn.get('channelTitle', 'Unknown').replace(' - Topic', ''),
                'thumbnail': sn.get('thumbnails', {}).get('high', {}).get('url', f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'),
                'duration': '',
                'url': f'https://youtube.com/watch?v={vid}',
                'source': 'youtube',
            })
        return tracks
    except Exception as e:
        log.error(f'YT search: {e}')
        return []

def search_tracks(query, limit=10):
    k = hashlib.md5(f'{query}:{limit}'.encode()).hexdigest()
    c = cache_get(k)
    if c: return c
    # Try Archive first, YouTube as metadata fallback
    tracks = search_archive(query, limit)
    if len(tracks) < 3:
        yt = search_youtube(query, limit)
        # Merge - use YT for metadata/thumbnails, Archive for audio
        tracks = yt + [t for t in tracks if t['videoId'] not in [x['videoId'] for x in yt]]
        tracks = tracks[:limit]
    if tracks: cache_set(k, tracks)
    return tracks

# ── STREAM ───────────────────────────────────────────────────────────────────
def get_stream_url(track_id):
    k = f'stream:{track_id}'
    c = cache_get(k)
    if c: return c
    # Check if it's an Archive identifier (not a YouTube video ID)
    if not re.match(r'^[a-zA-Z0-9_-]{11}$', track_id):
        # Internet Archive item
        url = get_archive_files(track_id)
        if url:
            cache_set(k, url, m=60)
            return url
    # YouTube - try to find same song on Archive
    return ''

# ── ROUTES ───────────────────────────────────────────────────────────────────
@app.route('/api/health')
def health():
    return jsonify({'status': 'ok', 'service': 'Sona', 'sources': ['archive.org', 'youtube_meta']})

@app.route('/api/search')
def search():
    q = request.args.get('q', '').strip()
    limit = min(int(request.args.get('limit', 10)), 20)
    if not q: return jsonify({'tracks': [], 'error': 'Query required'}), 400
    tracks = search_tracks(q, limit)
    return jsonify({'tracks': tracks, 'count': len(tracks)})

@app.route('/api/stream/<track_id>')
def stream(track_id):
    url = get_stream_url(track_id)
    if not url: return jsonify({'error': 'No stream URL'}), 404
    return jsonify({'url': url, 'trackId': track_id})

@app.route('/api/proxy/<track_id>')
def proxy(track_id):
    url = get_stream_url(track_id)
    if not url: return jsonify({'error': 'No stream URL'}), 404
    try:
        rng = request.headers.get('Range')
        hdrs = {'User-Agent': 'Mozilla/5.0'}
        if rng: hdrs['Range'] = rng
        r = requests.get(url, headers=hdrs, stream=True, timeout=30)
        ct = r.headers.get('Content-Type', 'audio/mpeg')
        def gen():
            for chunk in r.iter_content(16384):
                if chunk: yield chunk
        rh = {'Content-Type': ct, 'Accept-Ranges': 'bytes', 'Access-Control-Allow-Origin': '*'}
        if 'Content-Length' in r.headers: rh['Content-Length'] = r.headers['Content-Length']
        if 'Content-Range' in r.headers: rh['Content-Range'] = r.headers['Content-Range']
        return Response(stream_with_context(gen()), status=r.status_code, headers=rh)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<track_id>')
def download(track_id):
    url = get_stream_url(track_id)
    if not url: return jsonify({'error': 'Not available'}), 404
    title = re.sub(r'[^\w\s-]', '', request.args.get('title', track_id))[:50]
    out = CACHE_DIR / f'{track_id}.mp3'
    if not out.exists():
        try:
            r = requests.get(url, stream=True, timeout=60)
            with open(str(out), 'wb') as f:
                for chunk in r.iter_content(8192):
                    if chunk: f.write(chunk)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    if out.exists():
        return send_file(str(out), as_attachment=True, download_name=f'{title}.mp3', mimetype='audio/mpeg')
    return jsonify({'error': 'Download failed'}), 500

@app.route('/api/subscribe', methods=['POST'])
def subscribe():
    return jsonify({'success': True})

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    f = Path('frontend') / path
    if path and f.exists() and f.is_file(): return send_file(str(f))
    return send_file('frontend/index.html')

if __name__ == '__main__':
    log.info('Sona starting with Internet Archive source')
    app.run(host='0.0.0.0', port=PORT, debug=False)
