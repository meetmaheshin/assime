// AARTH service worker. The HTML is network-first so code updates apply on the
// next load; static assets (icons/manifest) are cache-first. API calls
// (/auth, /tasks, /voice, ...) are never touched.
const CACHE = "aarth-v3";
const SHELL = [
  "/ui/", "/ui/index.html",
  "/ui/manifest.webmanifest", "/ui/icon-192.png", "/ui/icon-512.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});
self.addEventListener("fetch", (e) => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || !u.pathname.startsWith("/ui/")) return; // API passes through
  const isDoc = u.pathname === "/ui/" || u.pathname.endsWith("/index.html");
  const put = (res) => { const c = res.clone(); caches.open(CACHE).then((x) => x.put(e.request, c)).catch(() => {}); return res; };
  if (isDoc) {
    // network-first: always try to get the latest app, fall back to cache offline
    e.respondWith(fetch(e.request).then(put).catch(() => caches.match(e.request)));
  } else {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request).then(put)));
  }
});
