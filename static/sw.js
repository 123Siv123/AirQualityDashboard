/* AQ Monitor — minimal offline shell for PWA install */
const CACHE_NAME = "aq-monitor-v1";
const PRECACHE = [
  "/dashboard",
  "/static/manifest.webmanifest",
  "/static/css/theme.css",
  "/static/css/mobile-pwa.css",
  "/static/js/pwa-install.js",
  "/static/js/air-alerts.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function (cache) {
      return cache.addAll(PRECACHE).catch(function () {
        /* partial precache ok */
      });
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys
          .filter(function (k) {
            return k !== CACHE_NAME;
          })
          .map(function (k) {
            return caches.delete(k);
          })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener("fetch", function (event) {
  const url = new URL(event.request.url);

  if (url.pathname.startsWith("/api/")) {
    return;
  }

  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    fetch(event.request)
      .then(function (response) {
        if (response && response.status === 200 && url.origin === self.location.origin) {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(function (cache) {
            cache.put(event.request, copy);
          });
        }
        return response;
      })
      .catch(function () {
        return caches.match(event.request).then(function (cached) {
          if (cached) {
            return cached;
          }
          if (event.request.mode === "navigate") {
            return caches.match("/dashboard");
          }
        });
      })
  );
});
