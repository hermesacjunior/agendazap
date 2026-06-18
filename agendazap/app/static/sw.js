/* AgendaZap service worker — shell offline conservador.
   Servido em "/sw.js" (escopo raiz) via rota FastAPI para poder controlar "/".
   Estrategia:
     - Apenas requisicoes GET sao cacheadas.
     - Assets estaticos sob /static/  -> stale-while-revalidate.
     - Navegacoes (HTML)              -> network-first, com pagina offline minima.
       NUNCA cacheamos HTML autenticado/admin/auth/api, para nao servir
       conteudo desatualizado ou de outra sessao.
     - Todo o resto (POST, JSON de API, cross-origin) -> direto para a rede.
*/
const VERSION = 'v4';
const STATIC_CACHE = 'az-static-' + VERSION;
const PRECACHE = [
  '/static/css/main.css?v=4',
  '/static/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/icon.svg',
];

const OFFLINE_HTML =
  '<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">' +
  '<meta name="viewport" content="width=device-width, initial-scale=1">' +
  '<title>Sem conexao — AgendaZap</title>' +
  '<link rel="stylesheet" href="/static/css/main.css"></head>' +
  '<body><div class="auth-page"><div class="auth-card" style="text-align:center">' +
  '<div class="auth-logo" style="justify-content:center"><div class="logo-icon">AZ</div><span>AgendaZap</span></div>' +
  '<h2 style="margin-bottom:8px">Voce esta offline</h2>' +
  '<p class="text-muted" style="margin-bottom:20px">Conecte-se a internet para continuar.</p>' +
  '<button class="btn btn-primary btn-full" onclick="location.reload()">Tentar novamente</button>' +
  '</div></div></body></html>';

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== STATIC_CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return url.origin === self.location.origin && url.pathname.startsWith('/static/');
}

self.addEventListener('fetch', (event) => {
  const req = event.request;

  // Apenas GET; o resto (POST etc.) vai direto para a rede.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Nunca toca em requisicoes cross-origin.
  if (url.origin !== self.location.origin) return;

  // Assets estaticos: network-first (online sempre pega a versao atual;
  // offline cai no cache). Evita servir CSS/JS desatualizado apos deploy.
  if (isStaticAsset(url)) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Navegacoes (carregamento de pagina): network-first, sem cachear a resposta
  // (evita conteudo autenticado/desatualizado). So mostra o shell offline
  // quando a rede esta indisponivel.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(
        () => new Response(OFFLINE_HTML, { headers: { 'Content-Type': 'text/html; charset=utf-8' } })
      )
    );
    return;
  }

  // Default: passa direto para a rede.
});
