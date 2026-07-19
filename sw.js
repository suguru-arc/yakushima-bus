// 屋久島バス乗換 / Yakushima Bus - Service Worker
//
// 単一HTMLアプリなので、キャッシュ対象はこのファイル自身とmanifest.jsonのみ。
// 屋久島は山間部で電波が入らない場所が多いため、一度開けばオフラインでも
// そのまま使えることを最優先にしている。
//
// 更新運用: 時刻表・運賃データを更新してyakushima-bus.htmlを差し替えたときは、
// 必ず CACHE_NAME のバージョン番号を上げること。上げないと、既にオフライン
// 利用者の端末にキャッシュされた古いデータがいつまでも使われ続けてしまう。
const CACHE_NAME = "yakushima-bus-v1";
const PRECACHE_URLS = ["./", "./yakushima-bus.html", "./manifest.json"];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS))
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

// stale-while-revalidate: まずキャッシュがあれば即座に返してオフラインでも
// 確実に開けるようにしつつ、裏で最新版を取得してキャッシュを更新しておく。
self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
