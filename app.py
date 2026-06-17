import os, json, hashlib, re, subprocess, logging
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
        d,e=_cache[k]
        if datetime.now()<e: return d
        del _cache[k]
    return None

def cache_set(k,d,m=30):
    _cache[k]=(d,datetime.now()+timedelta(minutes=m))

def search_yt_api(q,limit):
    if not YT_KEY: return []
    try:
        r=requests.get('https://www.googleapis.com/youtube/v3/search',params={
            'part':'snippet','q':q,'type':'video','videoCategoryId':'10',
            'maxResults':limit,'key':YT_KEY},timeout=10)
        items=r.json().get('items',[])
        ids=','.join([i['id']['videoId'] for i in items if i.get('id',{}).get('videoId')])
        dur={}
        if ids:
            vr=requests.get('https://www.googleapis.com/youtube/v3/videos',
                params={'part':'contentDetails','id':ids,'key':YT_KEY},timeout=10)
            for v in vr.json().get('items',[]):
                m2=re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',v.get('contentDetails',{}).get('duration',''))
                if m2:
                    h,mn,s=(int(x or 0) for x in m2.groups())
                    t=h*3600+mn*60+s; mm,ss=divmod(t,60)
                    dur[v['id']]=f'{mm}:{ss:02d}'
        tracks=[]
        for item in items:
            vid=item.get('id',{}).get('videoId','')
            if not vid: continue
            sn=item.get('snippet',{})
            tracks.append({'videoId':vid,'title':sn.get('title','Unknown'),
                'artist':sn.get('channelTitle','Unknown').replace(' - Topic',''),
                'thumbnail':sn.get('thumbnails',{}).get('high',{}).get('url',f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'),
                'duration':dur.get(vid,''),'url':f'https://youtube.com/watch?v={vid}'})
        return tracks
    except Exception as e:
        log.error(f'YT API: {e}'); return []

def search_ytdlp(q,limit):
    try:
        cmd=['yt-dlp',f'ytsearch{limit}:{q}','--flat-playlist',
             '--print','%(id)s|%(title)s|%(uploader)s|%(duration)s',
             '--no-warnings','--quiet']
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        tracks=[]
        for line in r.stdout.strip().split('\n'):
            if not line.strip(): continue
            p=line.split('|')
            if len(p)<3: continue
            vid=p[0].strip()
            try:
                d=int(p[3].strip()) if len(p)>3 else 0
                mm,ss=divmod(d,60); dur=f'{mm}:{ss:02d}'
            except: dur=''
            tracks.append({'videoId':vid,'title':p[1].strip(),
                'artist':p[2].strip().replace(' - Topic',''),
                'thumbnail':f'https://img.youtube.com/vi/{vid}/mqdefault.jpg',
                'duration':dur,'url':f'https://youtube.com/watch?v={vid}'})
        return tracks
    except Exception as e:
        log.error(f'ytdlp search: {e}'); return []

def search_tracks(q,limit=10):
    k=hashlib.md5(f'{q}:{limit}'.encode()).hexdigest()
    c=cache_get(k)
    if c: return c
    tracks=search_yt_api(q,limit) or search_ytdlp(q,limit)
    if tracks: cache_set(k,tracks)
    return tracks

def get_stream(vid):
    k=f'stream:{vid}'
    c=cache_get(k)
    if c: return c
    try:
        cmd=['yt-dlp',f'https://youtube.com/watch?v={vid}',
             '--get-url','-f','bestaudio[ext=m4a]/bestaudio/best',
             '--no-warnings','--quiet']
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        url=r.stdout.strip().split('\n')[0]
        if url and url.startswith('http'):
            cache_set(k,url,m=4); return url
    except Exception as e:
        log.error(f'stream: {e}')
    return ''

@app.route('/api/health')
def health():
    return jsonify({'status':'ok','yt_api':bool(YT_KEY)})

@app.route('/api/search')
def search():
    q=request.args.get('q','').strip()
    limit=min(int(request.args.get('limit',10)),20)
    if not q: return jsonify({'tracks':[],'error':'Query required'}),400
    return jsonify({'tracks':search_tracks(q,limit),'count':len(search_tracks(q,limit))})

@app.route('/api/proxy/<vid>')
def proxy(vid):
    try:
        url=get_stream(vid)
        if not url: return jsonify({'error':'No stream URL'}),404
        rng=request.headers.get('Range')
        hdrs={'User-Agent':'Mozilla/5.0','Referer':'https://www.youtube.com/'}
        if rng: hdrs['Range']=rng
        r=requests.get(url,headers=hdrs,stream=True,timeout=30)
        ct=r.headers.get('Content-Type','audio/mp4')
        if 'video' in ct: ct='audio/mp4'
        def gen():
            for chunk in r.iter_content(16384):
                if chunk: yield chunk
        rh={'Content-Type':ct,'Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*'}
        if 'Content-Length' in r.headers: rh['Content-Length']=r.headers['Content-Length']
        if 'Content-Range' in r.headers: rh['Content-Range']=r.headers['Content-Range']
        return Response(stream_with_context(gen()),status=r.status_code,headers=rh)
    except Exception as e:
        return jsonify({'error':str(e)}),500

@app.route('/api/download/<vid>')
def download(vid):
    title=re.sub(r'[^\w\s-]','',request.args.get('title',vid))[:50]
    out=CACHE_DIR/f'{vid}.mp3'
    if not out.exists():
        try:
            subprocess.run(['yt-dlp',f'https://youtube.com/watch?v={vid}',
                '-x','--audio-format','mp3','--audio-quality','0',
                '-o',str(CACHE_DIR/f'{vid}.%(ext)s'),
                '--no-warnings','--quiet'],timeout=120)
        except: pass
    if out.exists():
        return send_file(str(out),as_attachment=True,download_name=f'{title}.mp3',mimetype='audio/mpeg')
    return jsonify({'error':'Download failed'}),500

@app.route('/api/subscribe',methods=['POST'])
def subscribe():
    return jsonify({'success':True})

@app.route('/',defaults={'path':''})
@app.route('/<path:path>')
def serve(path):
    f=Path('frontend')/path
    if path and f.exists() and f.is_file(): return send_file(str(f))
    return send_file('frontend/index.html')

if __name__=='__main__':
    app.run(host='0.0.0.0',port=PORT,debug=False)
