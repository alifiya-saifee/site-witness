/* The home-screen app's service worker. It keeps only the app's frame (the page and its icons) so the app opens
   fast and shows "can't reach the Mac" when offline. It NEVER keeps files, replies, results or anything under
   /api/ or /helper/: those always go straight to the Mac. */
const FRAME = 'diwan-frame-v1';
const KEEP = ['/', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/icon-maskable.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(FRAME).then(c => c.addAll(KEEP)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== FRAME).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/helper/')) return;  // never cached
  if (!KEEP.includes(url.pathname)) return;
  // the page: the newest from the Mac when it answers, the kept frame when it doesn't
  e.respondWith(fetch(e.request).then(r => {
    if (r.ok) { const copy = r.clone(); caches.open(FRAME).then(c => c.put(url.pathname, copy)); }
    return r;
  }).catch(() => caches.match(url.pathname)));
});
