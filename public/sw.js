'use strict';

/* Bump this string whenever the app shell changes to force cache refresh. */
const CACHE = 'ec-v3';
const IMG_CACHE = 'ec-images'; /* persists across CACHE version bumps */

/* Files cached on install — the minimum needed to render the app offline. */
const SHELL = [
  '/',
  '/index.html',
  '/js/app.js',
  '/css/style.css',
  '/icon.svg',
  '/icon.png',
];

/* ── Install: precache the app shell ── */
self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function (c) { return c.addAll(SHELL); })
      .then(function () { return self.skipWaiting(); })
  );
});

/* ── Activate: delete caches from old versions ── */
self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(
          keys.filter(function (k) { return k !== CACHE && k !== IMG_CACHE; })
              .map(function (k) { return caches.delete(k); })
        );
      })
      .then(function () { return self.clients.claim(); })
  );
});

/* ── Fetch ── */
self.addEventListener('fetch', function (e) {
  var url = new URL(e.request.url);

  /* Google Fonts: cache-first (font files are content-addressed and never change) */
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    e.respondWith(
      caches.match(e.request).then(function (hit) {
        return hit || fetch(e.request).then(function (res) {
          caches.open(CACHE).then(function (c) { c.put(e.request, res.clone()); });
          return res;
        });
      })
    );
    return;
  }

  /* Wikimedia images: cache-first using the persistent image cache */
  if (url.hostname === 'upload.wikimedia.org') {
    e.respondWith(
      caches.match(e.request).then(function (hit) {
        return hit || fetch(e.request).then(function (res) {
          if (res.ok) caches.open(IMG_CACHE).then(function (c) { c.put(e.request, res.clone()); });
          return res;
        });
      })
    );
    return;
  }

  /* Ignore other cross-origin requests (dictionary API, Wikipedia, etc.) */
  if (url.origin !== location.origin) return;

  /* App shell: cache-first — bump CACHE version above to force an update */
  if (SHELL.includes(url.pathname)) {
    e.respondWith(
      caches.match(e.request).then(function (hit) {
        return hit || fetch(e.request).then(function (res) {
          caches.open(CACHE).then(function (c) { c.put(e.request, res.clone()); });
          return res;
        });
      })
    );
    return;
  }

  /* catalog.json and chapter .md files: network-first, cache as fallback.
     app.js also mirrors chapters to localStorage — the SW cache is a second
     layer that covers the case where localStorage has been cleared. */
  e.respondWith(
    fetch(e.request)
      .then(function (res) {
        caches.open(CACHE).then(function (c) { c.put(e.request, res.clone()); });
        return res;
      })
      .catch(function () { return caches.match(e.request); })
  );
});
