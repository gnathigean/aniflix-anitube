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
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request);
    })
  );
});
