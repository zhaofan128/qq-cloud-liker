const CACHE = 'qz-v1';
const ASSETS = ['./index.html', './app.js', './manifest.webmanifest', './icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // 数据与 API 始终走网络，避免看到过期快照
  if (url.pathname.endsWith('snapshot.json') || url.hostname === 'api.github.com') return;
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
