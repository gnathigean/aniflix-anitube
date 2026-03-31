self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open('aniflix-v1').then((cache) => {
      return cache.addAll([
        '/',
        '/static/index.html',
        'https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap'
      ]);
    })
  );
});

self.addEventListener('fetch', (e) => {
  // Ignora requisições de API e Streamíng de video, garantindo natividade (HTTP 206)
  if (e.request.url.includes('/stream') || e.request.url.includes('/api/')) {
      return;
  }

  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request).catch(err => {
          console.error("[ServiceWorker] Fetch failed:", err);
          return new Response("", { status: 502, statusText: "Bad Gateway/Offline" });
      });
    })
  );
});
