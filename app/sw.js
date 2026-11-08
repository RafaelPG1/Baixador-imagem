/* Service worker do app. O cache é versionado: uma versão nova só entra quando você aperta "Atualizar" (nada de
   app pela metade). __VERSAO__ é trocado pelo código do commit na publicação (.github/workflows/pages.yml). */
const VERSAO = '__VERSAO__';
const CACHE = 'baixador-app-' + VERSAO;
const ARQUIVOS = ['./', './index.html', './app.css', './app.js', './ajuste.js', './zip.js', './manifest.webmanifest', './icons/icon-192.png', './icons/icon-512.png'];

self.addEventListener('install', (ev) => {
  ev.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQUIVOS.map((u) => new Request(u, { cache: 'reload' })))));
});
self.addEventListener('activate', (ev) => {
  ev.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k.startsWith('baixador-app-') && k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', (ev) => {
  const req = ev.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  ev.respondWith(caches.open(CACHE).then(async (c) => {
    const achado = await c.match(req, { ignoreSearch: true });
    if (achado) return achado;
    if (req.mode === 'navigate') { const base = await c.match('./index.html'); if (base) return base; }
    return fetch(req);
  }));
});
self.addEventListener('message', (ev) => {
  if (ev.data === 'PULAR_ESPERA') self.skipWaiting();
  else if (ev.data === 'VERSAO' && ev.ports[0]) ev.ports[0].postMessage(VERSAO);
});
