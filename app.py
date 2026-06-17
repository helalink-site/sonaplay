import os,json,hashlib,re,logging
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
def cg(k):
 if k in _cache:
  d,e=_cache[k]
  if datetime.now()<e:return d
  del _cache[k]
def cs(k,d,m=30):_cache[k]=(d,datetime.now()+timedelta(minutes=m))
def search_archive(q,n=10):
 try:
  r=requests.get('https://archive.org/advancedsearch.php',params={'q':f'({q}) AND mediatype:audio','output':'json','rows':n,'fl':'identifier,title,creator','sort':'downloads desc'},timeout=10)
  docs=r.json().get('response',{}).get('docs',[])
  tracks=[]
  for doc in docs:
   iid=doc.get('identifier','')
   if not iid:continue
   ar=doc.get('creator','Unknown')
   if isinstance(ar,list):ar=ar[0]
   tracks.append({'videoId':iid,'title':doc.get('title','Unknown'),'artist':str(ar),'thumbnail':f'https://archive.org/services/img/{iid}','duration':'','url':f'https://archive.org/details/{iid}','source':'archive'})
  return tracks
 except Exception as e:log.error(f'archive:{e}');return[]
def get_file(iid):
 k=f'f:{iid}'
 c=cg(k)
 if c:return c
 try:
  r=requests.get(f'https://archive.org/metadata/{iid}',timeout=10)
  files=r.json().get('files',[])
  mp3=[f for f in files if f.get('name','').lower().endswith('.mp3')]
  audio=[f for f in files if any(f.get('name','').lower().endswith(x) for x in['.mp3','.ogg','.m4a','.opus'])]
  best=(mp3 or audio)
  if best:
   url=f'https://archive.org/download/{iid}/{best[0]["name"]}'
   cs(k,url,60);return url
 except Exception as e:log.error(f'getfile:{e}')
def search_yt(q,n=10):
 if not YT_KEY:return[]
 try:
  r=requests.get('https://www.googleapis.com/youtube/v3/search',params={'part':'snippet','q':q,'type':'video','videoCategoryId':'10','maxResults':n,'key':YT_KEY},timeout=10)
  tracks=[]
  for i in r.json().get('items',[]):
   vid=i.get('id',{}).get('videoId','')
   if not vid:continue
   sn=i.get('snippet',{})
   tracks.append({'videoId':vid,'title':sn.get('title','Unknown'),'artist':sn.get('channelTitle','Unknown').replace(' - Topic',''),'thumbnail':sn.get('thumbnails',{}).get('high',{}).get('url',f'https://img.youtube.com/vi/{vid}/mqdefault.jpg'),'duration':'','url':f'https://youtube.com/watch?v={vid}','source':'youtube'})
  return tracks
 except:return[]
def search_tracks(q,n=10):
 k=hashlib.md5(f'{q}:{n}'.encode()).hexdigest()
 c=cg(k)
 if c:return c
 tracks=search_archive(q,n)
 if len(tracks)<5:tracks=search_yt(q,n)+tracks
 tracks=tracks[:n]
 if tracks:cs(k,tracks)
 return tracks
def get_stream(tid):
 k=f's:{tid}'
 c=cg(k)
 if c:return c
 url=get_file(tid)
 if url:cs(k,url,60)
 return url or''
@app.route('/api/health')
def health():return jsonify({'status':'ok','source':'archive.org'})
@app.route('/api/search')
def search():
 q=request.args.get('q','').strip()
 n=min(int(request.args.get('limit',10)),20)
 if not q:return jsonify({'tracks':[],'error':'Query required'}),400
 return jsonify({'tracks':search_tracks(q,n),'count':len(search_tracks(q,n))})
@app.route('/api/proxy/<tid>')
def proxy(tid):
 url=get_stream(tid)
 if not url:return jsonify({'error':'No stream'}),404
 try:
  hdrs={'User-Agent':'Mozilla/5.0'}
  rng=request.headers.get('Range')
  if rng:hdrs['Range']=rng
  r=requests.get(url,headers=hdrs,stream=True,timeout=30)
  def gen():
   for chunk in r.iter_content(16384):
    if chunk:yield chunk
  rh={'Content-Type':r.headers.get('Content-Type','audio/mpeg'),'Accept-Ranges':'bytes','Access-Control-Allow-Origin':'*'}
  if'Content-Length'in r.headers:rh['Content-Length']=r.headers['Content-Length']
  if'Content-Range'in r.headers:rh['Content-Range']=r.headers['Content-Range']
  return Response(stream_with_context(gen()),status=r.status_code,headers=rh)
 except Exception as e:return jsonify({'error':str(e)}),500
@app.route('/api/download/<tid>')
def download(tid):
 url=get_stream(tid)
 if not url:return jsonify({'error':'Not available'}),404
 title=re.sub(r'[^\w\s-]','',request.args.get('title',tid))[:50]
 out=CACHE_DIR/f'{tid}.mp3'
 if not out.exists():
  r=requests.get(url,stream=True,timeout=60)
  with open(str(out),'wb') as f:
   for chunk in r.iter_content(8192):
    if chunk:f.write(chunk)
 if out.exists():return send_file(str(out),as_attachment=True,download_name=f'{title}.mp3',mimetype='audio/mpeg')
 return jsonify({'error':'Failed'}),500
@app.route('/api/subscribe',methods=['POST'])
def sub():return jsonify({'success':True})
@app.route('/',defaults={'path':''})
@app.route('/<path:path>')
def serve(path):
 f=Path('frontend')/path
 if path and f.exists() and f.is_file():return send_file(str(f))
 return send_file('frontend/index.html')
if __name__=='__main__':app.run(host='0.0.0.0',port=PORT,debug=False)
