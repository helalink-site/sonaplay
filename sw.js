/* Clears the old Sona Play caches and takes over from the earlier service worker. No caching, no fetch handling. */
self.addEventListener('install',function(){self.skipWaiting()});
self.addEventListener('activate',function(e){e.waitUntil(caches.keys().then(function(k){return Promise.all(k.map(function(x){return caches.delete(x)}))}).then(function(){return self.clients.claim()}))});
