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
# Invidious instances to try
INVIDIOUS_INSTANCES=[
    'https://invidious.snopyta.org',
    'https://inv.riverside.rocks',
    'https://invidious.kavin.rocks',
    'https://yt.artemislena.eu',
    'https://invidious.projectsegfau.lt',
]

# Piped instances as fallback
PIPED_INSTANCES=[
    'https://pipedapi.kavin.rocks',
    'https://piped-api.garudalinux.org',
    'https://api.piped.projectsegfau.lt',
]

def get_yt_stream(video_id):
    """Get audio stream via Invidious then Piped API"""
    k=f'yt:{video_id}'
    c=cg(k)
    if c: return c

    # Try Invidious first
    for instance in INVIDIOUS_INSTANCES:
        try:
            r=requests.get(f'{instance}/api/v1/videos/{video_id}',
                params={'fields':'adaptiveFormats,formatStreams'},
                headers={'User-Agent':'Mozilla/5.0'},timeout=10)
            if r.status_code!=200:
                continue
            data=r.json()
            # adaptiveFormats has audio-only streams
            formats=data.get('adaptiveFormats',[])
            audio=[f for f in formats if 'audio' in f.get('type','') and 'video' not in f.get('type','')]
            if not audio:
                # fallback to formatStreams (combined)
                audio=data.get('formatStreams',[])
            if not audio:
                continue
            best=sorted(audio,key=lambda x:int(x.get('bitrate',0)),reverse=True)
            url=best[0].get('url','')
            if url and url.startswith('http'):
                cs(k,url,50)
                log.info(f'Invidious OK: {video_id} via {instance}')
                return url
        except Exception as e:
            log.warning(f'Invidious {instance} failed: {e}')
            continue

    # Try Piped as fallback
    for instance in PIPED_INSTANCES:
        try:
            r=requests.get(f'{instance}/streams/{video_id}',
                headers={'User-Agent':'Mozilla/5.0'},timeout=10)
            if r.status_code!=200:
                continue
            data=r.json()
            audio_streams=data.get('audioStreams',[])
            if not audio_streams:
                continue
            best=sorted(audio_streams,key=lambda x:x.get('bitrate',0),reverse=True)
            url=best[0].get('url','')
            if url and url.startswith('http'):
                cs(k,url,50)
                log.info(f'Piped OK: {video_id} via {instance}')
                return url
        except Exception as e:
            log.warning(f'Piped {instance} failed: {e}')
            continue

    log.error(f'All instances failed for {video_id}')
    return ''

# --- Archive.org fallback ---
def search_archive(q,n=10):
    try:
        r=requests.get('https://archive.org/advancedsearch.php',params={
            'q':f'({q}) AND mediatype:audio AND subject:music NOT subject:radio NOT subject:podcast',
            'output':'json','rows':n*2,
            'fl':'identifier,title,creator',
            'sort':'downloads desc',
        },timeout=10)
        docs=r.json().get('response',{}).get('docs',[])
        tracks=[]
        skip=['radio','podcast','news','broadcast','lecture','speech']
        for doc in docs:
            iid=doc.get('identifier','')
            title=doc.get('title','Unknown')
            if not iid or any(w in title.lower() for w in skip): continue
            ar=doc.get('creator','Unknown')
            if isinstance(ar,list): ar=ar[0]
            tracks.append({'videoId':iid,'title':title,'artist':str(ar),
                'thumbnail':f'https://archive.org/services/img/{iid}',
                'duration':'','url':f'https://archive.org/details/{iid}','source':'archive'})
            if len(tracks)>=n: break
        return tracks
    except Exception as e:
        log.error(f'archive search: {e}'); return []

def get_archive_file(iid):
    k=f'f:{iid}'; c=cg(k)
    if c: return c
    try:
        r=requests.get(f'https://archive.org/metadata/{iid}',timeout=10)
        files=r.json().get('files',[])
        mp3=[f for f in files if f.get('name','').lower().endswith('.mp3')]
        audio=mp3 or [f for f in files if any(f.get('name','').lower().endswith(x) for x in['.ogg','.m4a','.opus','.flac'])]
        if audio:
            chosen=sorted([f for f in audio if f.get('size')],key=lambda x:int(x.get('size',0)))
            chosen=chosen[0] if chosen else audio[0]
            url=f'https://archive.org/download/{iid}/{chosen["name"]}'
            cs(k,url,60); return url
    except Exception as e:
        log.error(f'archive file: {e}')
    return ''

def search_yt(q,n=10):
    if not YT_KEY: return []
    try:
        r=requests.get('https://www.googleapis.com/youtube/v3/search',params={
            'part':'snippet','q':q,'type':'video',
            'videoCategoryId':'10','maxResults':n,'key':YT_KEY,
        },timeout=10)
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

def search_tracks(q,n=10):
    k=hashlib.md5(f'{q}:{n}'.encode()).hexdigest()
    c=cg(k)
    if c: return c
    tracks=search_yt(q,n) or search_archive(q,n)
    tracks=tracks[:n]
    if tracks: cs(k,tracks)
    return tracks

# --- Routes ---
@app.route('/api/health')
def health():
    has_cookies=COOKIES_FILE.exists()
    return jsonify({'status':'ok','cookies':has_cookies,'source':'youtube+archive'})

@app.route('/api/search')
def search():
    q=request.args.get('q','').strip()
    n=min(int(request.args.get('limit',10)),20)
    if not q: return jsonify({'tracks':[],'error':'Query required'}),400
    tracks=search_tracks(q,n)
    return jsonify({'tracks':tracks,'count':len(tracks)})

@app.route('/api/stream/<vid>')
def stream_url(vid):
    """Get streamable audio URL for a YouTube video ID"""
    is_yt=bool(re.match(r'^[a-zA-Z0-9_-]{11}$',vid))
    if is_yt:
        url=get_yt_stream(vid)
        if url:
            return jsonify({'url':url,'source':'youtube'})
        # fallback: search archive
        log.info(f'yt-dlp failed for {vid}, trying archive fallback')
        title=request.args.get('title','')
        artist=request.args.get('artist','')
        q=f'{title} {artist}'.strip() or vid
        archive=search_archive(q,3)
        if archive:
            aurl=get_archive_file(archive[0]['videoId'])
            if aurl:
                return jsonify({'url':aurl,'source':'archive','track':archive[0]})
        return jsonify({'error':'No stream available'}),404
    else:
        # Archive ID
        url=get_archive_file(vid)
        if url: return jsonify({'url':url,'source':'archive'})
        return jsonify({'error':'Not found'}),404

@app.route('/api/proxy/<tid>')
def proxy(tid):
    """Proxy audio stream to avoid CORS issues"""
    is_yt=bool(re.match(r'^[a-zA-Z0-9_-]{11}$',tid))
    if is_yt:
        url=get_yt_stream(tid)
    else:
        url=get_archive_file(tid)
    if not url:
        return jsonify({'error':'No stream available'}),404
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

@app.route('/api/archive-search')
def archive_search():
    q=request.args.get('q','').strip()
    tracks=search_archive(q,3)
    if tracks:
        url=get_archive_file(tracks[0]['videoId'])
        return jsonify({'url':url,'track':tracks[0]})
    return jsonify({'error':'Not found on archive'}),404

@app.route('/api/download/<tid>')
def download(tid):
    is_yt=bool(re.match(r'^[a-zA-Z0-9_-]{11}$',tid))
    url=get_yt_stream(tid) if is_yt else get_archive_file(tid)
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
