const CACHE_NAME = 'aniflix-cache-v2';
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/screenshot-mobile.png',
  '/icons/screenshot-desktop.png',
  'https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap'
];

// Instalação: Cacheia ativos estáticos iniciais
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[ServiceWorker] Caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Ativação: Limpa caches antigos
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keyList) => {
      return Promise.all(keyList.map((key) => {
        if (key !== CACHE_NAME) {
          console.log('[ServiceWorker] Removing old cache', key);
          return caches.delete(key);
        }
      }));
    })
  );
  return self.clients.claim();
});

// Fetch: Estratégia de Cache-First para assets, Network-First para o resto
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // Ignora requisições de API, Streaming de vídeo e extensões de dev
  if (url.pathname.includes('/stream') || url.pathname.includes('/api/') || url.hostname.includes('localhost')) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((response) => {
      // Retorna do cache se encontrar
      if (response) return response;

      // Caso contrário, busca na rede e salva no cache dinâmico
      return fetch(event.request).then((networkResponse) => {
        if (!networkResponse || networkResponse.status !== 200 || networkResponse.type !== 'basic') {
          return networkResponse;
        }

        const responseToCache = networkResponse.clone();
        caches.open(CACHE_NAME).then((cache) => {
          // Só cacheia arquivos estáticos (CSS, JS, Imagens de UI)
          if (url.pathname.match(/\.(js|css|png|jpg|jpeg|svg|woff2)$/)) {
            cache.put(event.request, responseToCache);
          }
        });

        return networkResponse;
      }).catch(() => {
        // Fallback offline para navegação principal
        if (event.request.mode === 'navigate') {
          return caches.match('/');
        }
      });
    })
  );
});
