const CACHE = 'sona-play-v3';
const SHELL = ['./', './index.html', './config.js', './manifest.json', './icons/icon-192.png', './icons/icon-512.png'];
self.addEventListener('install', e => { e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {})); self.skipWaiting(); });
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(x => x !== CACHE).map(x => caches.delete(x)))));
  self.clients.claim();
});
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;
  if (e.request.mode === 'navigate') {            // network first, cached shell when offline
    e.respondWith(fetch(e.request).then(r => { const c = r.clone(); caches.open(CACHE).then(x => x.put('./index.html', c)); return r; })
      .catch(() => caches.match('./index.html')));
    return;
  }
  e.respondWith(caches.match(e.request).then(c => c || fetch(e.request)));
});
self.addEventListener('push', e => {
  let d = {}; try { d = e.data.json(); } catch (_) {}
  const bc = d.kind === 'broadcast';
  e.waitUntil(self.registration.showNotification(bc ? (d.title || 'Sona Play') : 'New from ' + (d.artist || 'an artist'), {
    body: bc ? (d.body || '') : (d.title || ''), icon: d.thumbnail || 'icons/icon-192.png', badge: 'icons/icon-192.png', data: { id: d.video_id } }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const id = e.notification.data && e.notification.data.id;
  const url = '/?play=' + encodeURIComponent(id || '');
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(l => {
    for (const c of l) if ('focus' in c) { c.postMessage({ play: id }); return c.focus(); }
    return clients.openWindow(url);
  }));
});
