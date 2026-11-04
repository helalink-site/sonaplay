/* Sona Play app shell cache: opens fast on repeat visits. Audio and API calls are never cached here. */
var V='sona-shell-v10';
var SHELL=['./','index.html','config.js','manifest.json','icons/icon-192.png','icons/icon-512.png'];
self.addEventListener('install',function(e){e.waitUntil(caches.open(V).then(function(c){return c.addAll(SHELL)}).then(function(){return self.skipWaiting()}).catch(function(){}))});
self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(k){return Promise.all(k.filter(function(x){return x!==V}).map(function(x){return caches.delete(x)}))}).then(function(){return self.clients.claim()}))});
self.addEventListener('fetch',function(e){var r=e.request,u=new URL(r.url);
if(r.method!=='GET'||r.headers.has('range'))return;
var same=u.origin===location.origin,fonts=/fonts\.(googleapis|gstatic)\.com$/.test(u.hostname)||u.hostname==='cdn.jsdelivr.net';
if(!same&&!fonts)return;
if(same&&/^\/(api|admin)/.test(u.pathname))return;
e.respondWith(caches.open(V).then(function(c){return c.match(r).then(function(hit){
var net=fetch(r).then(function(res){if(res&&res.ok)c.put(r,res.clone());return res}).catch(function(){return hit});
return hit||net})}))});
