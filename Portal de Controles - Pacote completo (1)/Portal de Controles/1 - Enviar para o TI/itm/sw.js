/* Service worker do Controle ITM
   Guarda a página e as bibliotecas no aparelho para o app abrir sem rede.
   Ao publicar uma versão nova do index.html, aumente o número em CACHE. */
const CACHE = "balanco-itm-v1";
const ARQUIVOS = [
  "./",
  "./index.html",
  "./manifest.json"
];

self.addEventListener("install", e => {
  e.waitUntil(
    caches.open(CACHE).then(c =>
      Promise.all(ARQUIVOS.map(u =>
        c.add(new Request(u, { mode: u.startsWith("http") ? "no-cors" : "same-origin" })).catch(() => {})
      ))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", e => {
  e.waitUntil(
    caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", e => {
  const req = e.request;
  if (req.method !== "GET") return;                       // envios ao servidor passam direto

  // Página: tenta a rede (pega versão nova) e cai para a cópia guardada quando offline
  if (req.mode === "navigate") {
    e.respondWith(
      fetch(req).then(r => { if (r.ok && r.type === "basic" && !r.redirected) { const c = r.clone(); caches.open(CACHE).then(x => x.put("./index.html", c)); } return r; })
        .catch(() => caches.match("./index.html").then(r => r || caches.match("./")))
    );
    return;
  }

  // Bibliotecas, fontes e imagens: usa a cópia guardada e atualiza em segundo plano
  if (["script", "style", "font", "image", "manifest"].includes(req.destination)) {
    e.respondWith(
      caches.match(req).then(salvo => {
        const rede = fetch(req).then(r => { if (r && (r.ok || r.type === "opaque")) { const c = r.clone(); caches.open(CACHE).then(x => x.put(req, c)); } return r; })
          .catch(() => salvo);
        return salvo || rede;
      })
    );
  }
  // Demais pedidos (ex.: API de sincronização) não são interceptados
});
