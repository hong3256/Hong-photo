/* 진홍's 포토 갤러리 — 서비스 워커
   · 화면(index.html)은 network-first: 열 때마다 새 판을 먼저 받고, 인터넷이 없을 때만 캐시.
   · 아이콘·매니페스트는 stale-while-revalidate.
   · 구글 드라이브(Apps Script) 응답은 캐시하지 않음 — 항상 최신 사진 목록을 쓴다.
*/
var CACHE = 'hong-photo-v5';
var SHELL = new URL('./index.html', self.location.href).href;
var CORE = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png',
  './favicon.ico'
];

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE).then(function (cache) {
      return cache.addAll(CORE).catch(function () {
        return Promise.all(CORE.map(function (url) {
          return cache.add(url).catch(function () {});
        }));
      });
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== CACHE; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function (event) {
  var req = event.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);

  // 다른 출처(구글 드라이브·Apps Script)는 서비스 워커가 손대지 않는다.
  if (url.origin !== self.location.origin) return;

  var isDoc = req.mode === 'navigate' || (req.headers.get('accept') || '').indexOf('text/html') >= 0;
  if (isDoc) {
    event.respondWith(
      fetch(req).then(function (res) {
        var copy = res.clone();
        caches.open(CACHE).then(function (c) { c.put(SHELL, copy); });
        return res;
      }).catch(function () {
        return caches.match(SHELL).then(function (hit) { return hit || caches.match('./'); });
      })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then(function (hit) {
      var net = fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return hit; });
      return hit || net;
    })
  );
});
