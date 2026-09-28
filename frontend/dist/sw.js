// Service worker: caches the app shell only. API calls and media are never cached (private + large).
const CACHE = "rushline-mulj6xtm";
const SHELL = ["/", "/index.html", "/app.js", "/app.css", "/manifest.webmanifest", "/icons/icon-192.png", "/icons/apple-touch-icon.png",
  "/fonts/Poppins-Bold.ttf", "/fonts/Poppins-Medium.ttf"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // network-first so new deploys show up; cached shell when offline
  e.respondWith(
    fetch(e.request).then((r) => {
      if (r.ok && SHELL.includes(url.pathname)) { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(url.pathname, copy)); }
      return r;
    }).catch(() => caches.match(url.pathname).then((r) => r || caches.match("/index.html")))
  );
});
