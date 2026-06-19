import os,json,hashlib,re,logging,subprocess
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
COOKIES_FILE=Path('cookies.txt')
CACHE_DIR.mkdir(parents=True,exist_ok=True)
_cache={}

def cg(k):
    if k in _cache:
        d,e=_cache[k]
        if datetime.now()<e:return d
        del _cache[k]

def cs(k,d,m=30):
    _cache[k]=(d,datetime.now()+timedelta(minutes=m))

def search_yt_api(q,n=10):
    if not YT_KEY:return[]
    try:
        r=requests.get('https://www.googleapis.com/youtube/v3/search',params={
            'part':'snippet','q':q,'type':'video','videoCategoryId':'10',
            'maxResults':n,'key':YT_KEY},timeout=10)
        items=r.json().get('items',[])
        ids=','.join([i['id']['videoId'] for i in items if i.get('id',{}).get('videoId')])
        dur={}
        if ids:
            vr=requests.get('https://www.googleapis.com/youtube/v3/videos',
                params={'part':'contentDetails','id':ids,'key':YT_KEY},timeout=10)
            for v in vr.json().get('items',[]):
                m2=re.match(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',
                    v.get('contentDetails',{}).get('duration',''))
                if m2:
                    h,mn,s=(int(x or 0) for x in m2.groups())
                    t=h*3600+mn*60+s;mm,ss=divmod(t,60)
                    dur[v['id']]=f'{mm}:{ss:02d}'
        tracks=[]
        for item in items:
            vid=item.get('id',{}).get('videoId','')
            if not vid:continue
            sn=item.get('snippet',{})
            tracks.append({'videoId':vid,'title':sn.get('title','Unknown'),
                'artist':sn.get('channelTitle','Unknown').replace(' - Topic',''),
                'thumbnail':sn.get('thumbnails',{}).get('high',{}).get('url',
                    f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'),
                'duration':dur.get(vid,''),'url':f'https://youtube.com/watch?v={vid}'})
        return tracks
    except Exception as e:
        log.error(f'YT API:{e}');return[]

def search_ytdlp(q,n=10):
    try:
        cmd=['yt-dlp',f'ytsearch{n}:{q}','--flat-playlist',
             '--print','%(id)s|%(title)s|%(uploader)s|%(duration)s',
             '--no-warnings','--quiet']
        if COOKIES_FILE.exists():
            cmd+=['--cookies',str(COOKIES_FILE)]
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
        tracks=[]
        for line in r.stdout.strip().split('\n'):
            if not line.strip():continue
            p=line.split('|')
            if len(p)<3:continue
            vid=p[0].strip()
            try:
                d=int(p[3].strip()) if len(p)>3 else 0
                mm,ss=divmod(d,60);dur=f'{mm}:{ss:02d}'
            except:dur=''
            tracks.append({'videoId':vid,'title':p[1].strip(),
                'artist':p[2].strip().replace(' - Topic',''),
                'thumbnail':f'https://img.youtube.com/vi/{vid}/mqdefault.jpg',
                'duration':dur,'url':f'https://youtube.com/watch?v={vid}'})
        return tracks
    except Exception as e:
        log.error(f'ytdlp search:{e}');return[]

def search_tracks(q,n=10):
    k=hashlib.md5(f'{q}:{n}'.encode()).hexdigest()
    c=cg(k)
    if c:return c
    tracks=search_yt_api(q,n) or search_ytdlp(q,n)
    if tracks:cs(k,tracks)
    return tracks

def get_stream(vid):
    k=f's:{vid}'
    c=cg(k)
    if c:return c
    cmds=[
        ['yt-dlp',f'https://youtube.com/watch?v={vid}',
         '--get-url','-f','bestaudio[ext=m4a]/bestaudio/best',
         '--extractor-args','youtube:player_client=android,web',
         '--no-warnings','--quiet'],
        ['yt-dlp',f'https://youtube.com/watch?v={vid}',
         '--get-url','-f','bestaudio/best',
         '--extractor-args','youtube:player_client=ios',
         '--no-warnings','--quiet'],
    ]
    for cmd in cmds:
        if COOKIES_FILE.exists():
            cmd+=['--cookies',str(COOKIES_FILE)]
        try:
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
            url=r.stdout.strip().split('\n')[0]
            if url and url.startswith('http'):
                cs(k,url,m=4);return url
        except Exception as e:
            log.error(f'stream:{e}')
    return''

@app.route('/api/test')
def test():
    cmd=['yt-dlp','https://youtube.com/watch?v=BQ1zn3KwKS8',
         '--get-url','-f','bestaudio/best',
         '--extractor-args','youtube:player_client=android',
         '--no-warnings']
    if COOKIES_FILE.exists():
        cmd+=['--cookies',str(COOKIES_FILE)]
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
    return jsonify({
        'stdout':r.stdout[:300],
        'stderr':r.stderr[:500],
        'returncode':r.returncode,
        'cookies':COOKIES_FILE.exists()
    })

@app.route('/api/health')
def health():
    return jsonify({'status':'ok','cookies':COOKIES_FILE.exists(),'yt_api':bool(YT_KEY)})

@app.route('/api/search')
def search():
    q=request.args.get('q','').strip()
    n=min(int(request.args.get('limit',10)),20)
    if not q:return jsonify({'tracks':[],'error':'Query required'}),400
    return jsonify({'tracks':search_tracks(q,n),'count':len(search_tracks(q,n))})

@app.route('/api/proxy/<vid>')
def proxy(vid):
    url=get_stream(vid)
    if not url:return jsonify({'error':'No stream URL'}),404
    try:
        hdrs={'User-Agent':'Mozilla/5.0','Referer':'https://www.youtube.com/'}
        rng=request.headers.get('Range')
        if rng:hdrs['Range']=rng
        r=requests.get(url,headers=hdrs,stream=True,timeout=30)
        ct=r.headers.get('Content-Type','audio/mp4')
        if 'video' in ct:ct='audio/mp4'
        def gen():
            for chunk in r.iter_content(16384):
                if chunk:yield chunk
        rh={'Content-Type':ct,'Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*'}
        if 'Content-Length' in r.headers:rh['Content-Length']=r.headers['Content-Length']
        if 'Content-Range' in r.headers:rh['Content-Range']=r.headers['Content-Range']
        return Response(stream_with_context(gen()),status=r.status_code,headers=rh)
    except Exception as e:
        return jsonify({'error':str(e)}),500

@app.route('/api/download/<vid>')
def download(vid):
    title=re.sub(r'[^\w\s-]','',request.args.get('title',vid))[:50]
    out=CACHE_DIR/f'{vid}.mp3'
    if not out.exists():
        cmd=['yt-dlp',f'https://youtube.com/watch?v={vid}',
             '-x','--audio-format','mp3','--audio-quality','0',
             '-o',str(CACHE_DIR/f'{vid}.%(ext)s'),
             '--no-warnings','--quiet']
        if COOKIES_FILE.exists():cmd+=['--cookies',str(COOKIES_FILE)]
        try:subprocess.run(cmd,timeout=120)
        except:pass
    if out.exists():
        return send_file(str(out),as_attachment=True,
            download_name=f'{title}.mp3',mimetype='audio/mpeg')
    return jsonify({'error':'Download failed'}),500

@app.route('/api/subscribe',methods=['POST'])
def sub():return jsonify({'success':True})

@app.route('/',defaults={'path':''})
@app.route('/<path:path>')
def serve(path):
    f=Path('frontend')/path
    if path and f.exists() and f.is_file():return send_file(str(f))
    return send_file('frontend/index.html')

if __name__=='__main__':
    log.info(f'Sona - cookies:{"YES" if COOKIES_FILE.exists() else "NO"}')
    app.run(host='0.0.0.0',port=PORT,debug=False)
# Already complete - just need to check the debug
