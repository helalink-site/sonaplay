import os,json,hashlib,re,logging,subprocess,tempfile
from pathlib import Path
from datetime import datetime,timedelta
from flask import Flask,request,jsonify,send_file,Response,stream_with_context
from flask_cors import CORS
import requests

logging.basicConfig(level=logging.INFO)
log=logging.getLogger('sona')
app=Flask(__name__)
CORS(app,origins=['*'])
CACHE_DIR=Path(os.getenv('CACHE_DIR','/tmp/sona_cache'))
PORT=int(os.getenv('PORT',5000))
YT_KEY=os.getenv('YOUTUBE_API_KEY','')
CACHE_DIR.mkdir(parents=True,exist_ok=True)
_cache={}

# --- Cookies setup ---
# Cookies can be set via YOUTUBE_COOKIES_B64 env var (base64 of cookies.txt)
# or by placing cookies.txt in the project root
COOKIES_FILE=Path(os.getenv('COOKIES_PATH','/etc/secrets/cookies.txt'))

def ensure_cookies():
    """Load cookies from env var if file doesn't exist"""
    b64=os.getenv('YOUTUBE_COOKIES_B64','')
    if b64 and not COOKIES_FILE.exists():
        import base64
        try:
            COOKIES_FILE.write_bytes(base64.b64decode(b64))
            log.info('Cookies loaded from env var')
        except Exception as e:
            log.error(f'Cookie decode error: {e}')
    return COOKIES_FILE.exists()

ensure_cookies()

def cg(k):
    if k in _cache:
        d,e=_cache[k]
        if datetime.now()<e: return d
        del _cache[k]

def cs(k,d,m=30):
    _cache[k]=(d,datetime.now()+timedelta(minutes=m))

# --- yt-dlp stream extraction ---
# Working stream sources in 2026
COBALT_INSTANCES=[
    'https://cobalt.tools',
    'https://co.wuk.sh',
]

def try_ytdlp_tv_client(video_id):
    """Try yt-dlp with the 'tv' player client - yt-dlp's 2026 default for YouTube,
    designed to work without requiring a PO Token unlike android/web clients."""
    url=f'https://www.youtube.com/watch?v={video_id}'
    cmd=[
        'yt-dlp',
        '--no-playlist',
        '-f','bestaudio[ext=m4a]/bestaudio/best',
        '--get-url',
        '--no-warnings',
        '--quiet',
        '--extractor-args','youtube:player_client=tv',
    ]
    if COOKIES_FILE.exists():
        cmd+=['--cookies',str(COOKIES_FILE)]
    cmd.append(url)
    try:
        result=subprocess.run(cmd,capture_output=True,text=True,timeout=25)
        stream_url=result.stdout.strip().split('\n')[0]
        if stream_url and stream_url.startswith('http'):
            log.info(f'yt-dlp(tv) OK: {video_id}')
            return stream_url
        log.warning(f'yt-dlp(tv) no URL for {video_id}: {result.stderr[:200]}')
    except Exception as e:
        log.warning(f'yt-dlp(tv) error: {e}')
    return None

def get_yt_stream(video_id):
    """Get audio stream - try yt-dlp(tv client) first, then cobalt, then invidious"""
    k=f'yt:{video_id}'
    c=cg(k)
    if c: return c

    # Method 1: yt-dlp with tv client (our own server, our own cookies, current 2026 default)
    url=try_ytdlp_tv_client(video_id)
    if url:
        cs(k,url,50)
        return url

    yt_url=f'https://www.youtube.com/watch?v={video_id}'
    headers={
        'Accept':'application/json',
        'Content-Type':'application/json',
        'User-Agent':'Mozilla/5.0'
    }

    for base in COBALT_INSTANCES:
        try:
            r=requests.post(f'{base}/api/json',
                json={'url':yt_url,'isAudioOnly':True,'aFormat':'mp3','filenamePattern':'basic'},
                headers=headers,timeout=15)
            if r.status_code!=200:
                log.warning(f'Cobalt {base} status {r.status_code}')
                continue
            data=r.json()
            status=data.get('status','')
            url=data.get('url','')
            if status in ('stream','redirect','tunnel') and url:
                cs(k,url,50)
                log.info(f'Cobalt OK: {video_id} via {base}')
                return url
            log.warning(f'Cobalt {base} bad status: {status} data:{str(data)[:100]}')
        except Exception as e:
            log.warning(f'Cobalt {base} error: {e}')
            continue

    # Last resort: try inv.nadeko.net (currently one of few working invidious)
    try:
        r=requests.get(f'https://inv.nadeko.net/api/v1/videos/{video_id}',
            params={'fields':'adaptiveFormats'},
            headers={'User-Agent':'Mozilla/5.0'},timeout=12)
        if r.status_code==200:
            formats=r.json().get('adaptiveFormats',[])
            audio=[f for f in formats if 'audio' in f.get('type','') and 'video' not in f.get('type','')]
            if audio:
                best=sorted(audio,key=lambda x:int(x.get('bitrate',0)),reverse=True)
                url=best[0].get('url','')
                if url:
                    cs(k,url,40)
                    log.info(f'Nadeko OK: {video_id}')
                    return url
    except Exception as e:
        log.warning(f'Nadeko failed: {e}')

    log.error(f'All stream sources failed for {video_id}')
    return ''

# Archive.org removed — was returning irrelevant junk results

INV_SEARCH_INSTANCES=[
    'https://inv.nadeko.net',
    'https://inv.thepixora.com',
    'https://invidious.nerdvpn.de',
    'https://invidious.privacyredirect.com',
    'https://iv.datura.network',
]

def search_invidious(q,n=10):
    """Search via Invidious - no API key, no quota limits"""
    for base in INV_SEARCH_INSTANCES:
        try:
            r=requests.get(f'{base}/api/v1/search',params={
                'q':q,'type':'video',
            },timeout=8)
            if r.status_code!=200: continue
            items=r.json()
            tracks=[]
            for i in items:
                vid=i.get('videoId','')
                if not vid: continue
                thumbs=i.get('videoThumbnails',[])
                thumb=''
                if thumbs:
                    high=[t for t in thumbs if t.get('quality')=='high']
                    thumb=(high[0] if high else thumbs[0]).get('url','')
                if thumb and thumb.startswith('/'):
                    thumb=f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'
                dur=i.get('lengthSeconds',0)
                dur_str=f'{dur//60}:{dur%60:02d}' if dur else ''
                tracks.append({'videoId':vid,'title':i.get('title','Unknown'),
                    'artist':i.get('author','Unknown'),
                    'thumbnail':thumb or f'https://img.youtube.com/vi/{vid}/mqdefault.jpg',
                    'duration':dur_str,'url':f'https://youtube.com/watch?v={vid}','source':'youtube'})
                if len(tracks)>=n: break
            if tracks:
                log.info(f'Invidious search OK via {base}: {len(tracks)} results')
                return tracks
        except Exception as e:
            log.warning(f'Invidious search {base} failed: {e}')
            continue
    return []

def search_yt(q,n=10,order='relevance'):
    """Fallback: YouTube Data API (quota limited)"""
    if not YT_KEY: return []
    try:
        r=requests.get('https://www.googleapis.com/youtube/v3/search',params={
            'part':'snippet','q':q,'type':'video',
            'videoCategoryId':'10','maxResults':n,'key':YT_KEY,'order':order,
        },timeout=10)
        if r.status_code!=200:
            log.error(f'YT API error {r.status_code}: {r.text[:300]}')
            return []
        tracks=[]
        for i in r.json().get('items',[]):
            vid=i.get('id',{}).get('videoId','')
            if not vid: continue
            sn=i.get('snippet',{})
            tracks.append({'videoId':vid,'title':sn.get('title','Unknown'),
                'artist':sn.get('channelTitle','Unknown').replace(' - Topic',''),
                'thumbnail':sn.get('thumbnails',{}).get('high',{}).get('url',f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'),
                'duration':'','url':f'https://youtube.com/watch?v={vid}','source':'youtube'})
        return tracks
    except: return []

def search_deezer(q,n=10):
    """Deezer search - no API key needed, reliable fallback.
    Returns Deezer track data; we tag source as 'deezer' so frontend
    knows to resolve a YouTube video ID before streaming."""
    try:
        r=requests.get('https://api.deezer.com/search',params={'q':q,'limit':n},timeout=8)
        if r.status_code!=200: return []
        items=r.json().get('data',[])
        tracks=[]
        for i in items:
            title=i.get('title','Unknown')
            artist=i.get('artist',{}).get('name','Unknown')
            cover=i.get('album',{}).get('cover_big') or i.get('album',{}).get('cover_medium','')
            dur=i.get('duration',0)
            dur_str=f'{dur//60}:{dur%60:02d}' if dur else ''
            # No real videoId yet - frontend/backend will resolve via search when played
            tracks.append({
                'videoId':f'dz_{i.get("id","")}',  # marker prefix, resolved later
                'title':title,'artist':artist,
                'thumbnail':cover or '',
                'duration':dur_str,
                'url':i.get('link',''),
                'source':'deezer',
                'searchQuery':f'{title} {artist}'  # used to resolve real YT id on play
            })
        return tracks
    except Exception as e:
        log.warning(f'Deezer search failed: {e}')
        return []

def search_tracks(q,n=10,order='relevance'):
    k=hashlib.md5(f'{q}:{n}:{order}'.encode()).hexdigest()
    c=cg(k)
    if c: return c
    # YouTube API primary, Invidious 2nd, Deezer 3rd (metadata only, resolved on play)
    tracks=search_yt(q,n,order) or search_invidious(q,n) or search_deezer(q,n)
    tracks=tracks[:n]
    if tracks: cs(k,tracks,120)  # cache 2 hours to save quota
    return tracks

# --- Routes ---
@app.route('/api/health')
def health():
    has_cookies=COOKIES_FILE.exists()
    return jsonify({'status':'ok','cookies':has_cookies,'source':'youtube+invidious'})

@app.route('/api/search')
def search():
    q=request.args.get('q','').strip()
    n=min(int(request.args.get('limit',10)),20)
    order=request.args.get('order','relevance')  # 'date' for newest first
    if not q: return jsonify({'tracks':[],'error':'Query required'}),400
    tracks=search_tracks(q,n,order)
    return jsonify({'tracks':tracks,'count':len(tracks)})

@app.route('/api/stream/<vid>')
def stream_url(vid):
    """Get streamable audio URL for a YouTube video ID, or resolve Deezer marker first"""
    # Deezer track marker - need to resolve real YouTube video ID first
    if vid.startswith('dz_'):
        query=request.args.get('title','')+' '+request.args.get('artist','')
        query=query.strip()
        if not query:
            return jsonify({'error':'Cannot resolve - missing title/artist'}),400
        resolved=search_yt(query,3) or search_invidious(query,3)
        if not resolved:
            return jsonify({'error':'Could not find matching song'}),404
        real_vid=resolved[0]['videoId']
        url=get_yt_stream(real_vid)
        if url:
            return jsonify({'url':url,'source':'youtube','resolvedFrom':'deezer','videoId':real_vid})
        return jsonify({'error':'No stream available'}),404

    is_yt=bool(re.match(r'^[a-zA-Z0-9_-]{11}$',vid))
    if is_yt:
        url=get_yt_stream(vid)
        if url:
            return jsonify({'url':url,'source':'youtube'})
        return jsonify({'error':'No stream available'}),404
    else:
        return jsonify({'error':'Not found'}),404

def _relay_stream(url):
    """Shared logic: fetch a URL server-side and stream bytes to client (avoids CORS)"""
    try:
        hdrs={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        rng=request.headers.get('Range')
        if rng: hdrs['Range']=rng
        r=requests.get(url,headers=hdrs,stream=True,timeout=30)
        ct=r.headers.get('Content-Type','audio/mp4')
        def gen():
            for chunk in r.iter_content(16384):
                if chunk: yield chunk
        rh={'Content-Type':ct,'Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*'}
        if 'Content-Length' in r.headers: rh['Content-Length']=r.headers['Content-Length']
        if 'Content-Range' in r.headers: rh['Content-Range']=r.headers['Content-Range']
        return Response(stream_with_context(gen()),status=r.status_code,headers=rh)
    except Exception as e:
        return jsonify({'error':str(e)}),500

@app.route('/api/relay')
def relay():
    """Relay an already-resolved stream URL (browser found it, server just fetches bytes).
    This avoids re-discovering the stream from Render's blocked IP."""
    url=request.args.get('url','')
    if not url or not url.startswith('http'):
        return jsonify({'error':'Invalid url'}),400
    return _relay_stream(url)

@app.route('/api/proxy/<tid>')
def proxy(tid):
    """Legacy proxy - re-discovers stream server-side (may fail due to IP blocking)"""
    url=get_yt_stream(tid)
    if not url:
        return jsonify({'error':'No stream available'}),404
    return _relay_stream(url)

@app.route('/api/download/<tid>')
def download(tid):
    url=get_yt_stream(tid)
    if not url: return jsonify({'error':'Not available'}),404
    title=re.sub(r'[^\w\s-]','',request.args.get('title',tid))[:50]
    out=CACHE_DIR/f'{tid}.mp3'
    if not out.exists():
        r=requests.get(url,stream=True,timeout=60)
        with open(str(out),'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk: f.write(chunk)
    if out.exists():
        return send_file(str(out),as_attachment=True,download_name=f'{title}.mp3',mimetype='audio/mpeg')
    return jsonify({'error':'Failed'}),500

@app.route('/api/subscribe',methods=['POST'])
def sub(): return jsonify({'success':True})

@app.route('/',defaults={'path':''})
@app.route('/<path:path>')
def serve(path):
    f=Path('frontend')/path
    if path and f.exists() and f.is_file(): return send_file(str(f))
    return send_file('frontend/index.html')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=PORT,debug=False)
