/* Sona Play service worker: installable app, offline start, push alerts */
const CACHE = 'sona-v6';
const SHELL = ['./', './index.html', './manifest.json', './config.js', './icons/icon-192.png', './icons/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;
  const u = new URL(r.url);
  if (u.origin !== location.origin) return;            // never touch the API, audio, Supabase or CDN
  if (r.mode === 'navigate') {
    e.respondWith(fetch(r).catch(() => caches.match('./index.html')));
    return;
  }
  e.respondWith(caches.match(r).then(hit => {
    const net = fetch(r).then(x => { if (x.ok) { const cp = x.clone(); caches.open(CACHE).then(c => c.put(r, cp)); } return x; }).catch(() => hit);
    return hit || net;
  }));
});

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data.json(); } catch (_) {}
  const song = !!d.video_id;
  const icon = d.thumbnail && /^https:/.test(d.thumbnail) ? d.thumbnail : 'icons/icon-192.png';
  e.waitUntil(self.registration.showNotification(
    song ? 'New from ' + (d.artist || 'an artist') : (d.title || 'Sona Play'),
    { body: song ? (d.title || '') : (d.body || ''), icon, badge: 'icons/icon-192.png', tag: d.video_id || 'sona', data: { id: d.video_id || '' } }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const id = (e.notification.data || {}).id || '';
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs => {
    for (const c of cs) { if ('focus' in c) { c.focus(); if (id) c.postMessage({ play: id }); return; } }
    return clients.openWindow(id ? '/?play=' + id : '/');
  }));
});
