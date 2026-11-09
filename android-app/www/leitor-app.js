/* Adaptador do leitor no app. O leitor (leitor.js) é a MESMA cópia da web; aqui só trocamos de onde vêm os dados:
   - capítulo baixado no celular  -> lido do banco local (funciona sem internet);
   - capítulo que só está no notebook -> lido direto dele, com a chave no cabeçalho (sem baixar a obra);
   e os links do leitor ("capítulo anterior/próximo", "Obra", "Biblioteca") passam a abrir as telas do app.
   Entra ANTES do leitor.js. Nenhuma chave de API aqui: só a chave de pareamento guardada pelo app. */
(function () {
  'use strict';
  var nativoFetch = window.fetch.bind(window);
  var CHAVE_CFG = 'baixador-conexao', PREF = '/__ler/';
  var enc = encodeURIComponent;
  function lembrar(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }
  function guardar(k, v) { try { localStorage.setItem(k, v); } catch (_) {} }
  function cfg() { try { var c = JSON.parse(lembrar(CHAVE_CFG) || 'null'); return c && c.base && c.chave ? c : null; } catch (_) { return null; } }

  /* ---------- banco local (o mesmo do app.js) ---------- */
  var _bd = null;
  function bd() {
    if (!_bd) _bd = new Promise(function (ok, err) {
      var r = indexedDB.open('baixador-leitor', 1);
      r.onupgradeneeded = function () { var d = r.result; d.createObjectStore('obras', { keyPath: 'nome' }); d.createObjectStore('caps', { keyPath: 'id' }); d.createObjectStore('imgs', { keyPath: 'chave' }); };
      r.onsuccess = function () { ok(r.result); }; r.onerror = function () { err(r.error); };
    });
    return _bd;
  }
  function pedido(r) { return new Promise(function (ok, err) { r.onsuccess = function () { ok(r.result); }; r.onerror = function () { err(r.error); }; }); }
  async function obter(loja, chave) { var d = await bd(); return pedido(d.transaction(loja).objectStore(loja).get(chave)); }
  async function todos(loja) { var d = await bd(); return pedido(d.transaction(loja).objectStore(loja).getAll()); }

  /* ---------- pedidos ao notebook ---------- */
  function resposta(status, corpo) { return new Response(typeof corpo === 'string' ? corpo : JSON.stringify(corpo), { status: status, headers: { 'Content-Type': 'application/json' } }); }
  async function doNotebook(caminho, limite) {
    var c = cfg(); if (!c) throw new Error('sem-conexao');
    var ctl = new AbortController(), fim = setTimeout(function () { ctl.abort(); }, limite || 20000);
    try { return await nativoFetch(c.base + caminho, { headers: { Authorization: 'Bearer ' + c.chave }, signal: ctl.signal, cache: 'no-store' }); }
    finally { clearTimeout(fim); }
  }
  var motivoFalha = '';
  function falhou(motivo) { motivoFalha = motivo; }

  /* ---------- /api/leitura: baixado primeiro; senão, direto do notebook ---------- */
  async function leitura(rel) {
    var cap = null; try { cap = await obter('caps', rel); } catch (_) {}
    if (cap) {
      return resposta(200, { rel: cap.id, obra: cap.obra, rotulo: cap.rotulo, titulo: cap.dados.titulo, imagens: cap.dados.imagens,
        base: PREF + 'l/' + enc(cap.id) + '/', sub: '' });
    }
    if (!cfg()) { falhou('Este capítulo não está baixado e o app não está conectado ao notebook.'); return resposta(404, { erro: 'sem-conexao' }); }
    var r;
    try { r = await doNotebook('/api/leitura?c=' + enc(rel), 25000); }
    catch (_) { falhou('Sem conexão com o notebook e este capítulo não foi baixado. Confira o Tailscale e se o notebook está ligado.'); return resposta(503, { erro: 'offline' }); }
    if (r.status === 401) falhou('O notebook recusou a chave. Conecte de novo em Ajustes.');
    else if (r.status === 403) falhou('O notebook recusou o endereço. Confira o nome .ts.net salvo no programa.');
    else if (!r.ok) falhou('O notebook não achou este capítulo.');
    if (!r.ok) return resposta(r.status === 404 ? 404 : 503, { erro: 'falha' });
    var d = await r.json();
    d.base = PREF + 'o' + d.base;                                    // /__ler/o/ler/<obra>/<capítulo>/…
    return resposta(200, d);
  }

  /* ---------- /api/biblioteca: o que o notebook tem + o que já está baixado ---------- */
  var ultimaBiblioteca = null;
  async function biblioteca() {
    var remota = null;
    if (cfg()) {
      try { var r = await doNotebook('/api/biblioteca', 8000); if (r.ok) remota = await r.json(); } catch (_) {}
    }
    var obras = remota && remota.obras ? remota.obras : [], achados = {};
    obras.forEach(function (o) { o.capitulos.forEach(function (c) { achados[c.rel] = 1; }); });
    var locais = []; try { locais = await todos('caps'); } catch (_) {}
    var porObra = {};
    obras.forEach(function (o) { porObra[o.nome] = o; });
    locais.forEach(function (c) {                                    // baixado e ausente no notebook: continua navegável
      if (achados[c.id]) return;
      var o = porObra[c.obra] || (porObra[c.obra] = { nome: c.obra, capitulos: [] }); if (obras.indexOf(o) < 0) obras.push(o);
      o.capitulos.push({ rel: c.id, numero: c.numero, titulo: c.titulo, rotulo: c.rotulo, traduzido: !!c.traduzido });
    });
    obras.forEach(function (o) {
      o.capitulos.sort(function (a, b) {
        var x = parseFloat(a.numero), y = parseFloat(b.numero);
        if (isFinite(x) && isFinite(y) && x !== y) return x - y;
        return String(a.rotulo || a.rel).localeCompare(String(b.rotulo || b.rel), 'pt', { numeric: true });
      });
    });
    ultimaBiblioteca = { remota: !!remota };
    return resposta(200, { obras: obras });
  }

  window.fetch = function (entrada, opcoes) {
    var alvo; try { alvo = new URL(typeof entrada === 'string' ? entrada : entrada.url, location.href); } catch (_) { return nativoFetch(entrada, opcoes); }
    if (alvo.origin === location.origin) {
      if (alvo.pathname === '/api/leitura') return leitura(alvo.searchParams.get('c') || '');
      if (alvo.pathname === '/api/biblioteca') return biblioteca();
    }
    return nativoFetch(entrada, opcoes);
  };

  /* ---------- imagens: carregadas só quando chegam perto da tela (lê o notebook ou o banco local) ---------- */
  var fila = [], ativos = 0, MAX = 4;
  function urlDaImagem(v) {                                          // v = /__ler/l/<rel>/<arq>  ou  /__ler/o/ler/<…>/<arq>
    if (v.indexOf(PREF + 'l/') === 0) {
      var p = v.slice((PREF + 'l/').length).split('/'), rel = decodeURIComponent(p[0]), arq = decodeURIComponent(p.slice(1).join('/'));
      return obter('imgs', rel + '|' + arq).then(function (r) { if (!r) throw new Error('imagem local ausente'); return URL.createObjectURL(r.blob); });
    }
    var caminho = v.slice((PREF + 'o').length);                      // /ler/<…> como o notebook entende
    return doNotebook(caminho, 60000).then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.blob(); }).then(function (b) { return URL.createObjectURL(b); });
  }
  function rodarFila() {
    while (ativos < MAX && fila.length) {
      var tarefa = fila.shift(); ativos++;
      tarefa().then(function () {}, function () {}).then(function () { ativos--; rodarFila(); });
    }
  }
  var desc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
  var observador = 'IntersectionObserver' in window ? new IntersectionObserver(function (itens) {
    itens.forEach(function (it) { if (it.isIntersecting) { observador.unobserve(it.target); carregar(it.target); } });
  }, { rootMargin: '1800px 0px' }) : null;
  function carregar(img, tentativa) {
    var v = img.__virtual; if (!v || img.__carregando || img.__carregada) return Promise.resolve();
    img.__carregando = true;
    var feito = new Promise(function (ok) {
      fila.push(function () {
        return urlDaImagem(v).then(function (u) { desc.set.call(img, u); img.__carregada = true; }, function () {
          if (!tentativa) { img.__carregando = false; fila.push(function () { return carregar(img, 1); }); }
          else { img.alt = (img.alt || '') + ' (não carregou)'; img.dataset.erro = '1'; }
        }).then(function () { img.__carregando = false; ok(); });
      });
      rodarFila();
    });
    return feito;
  }
  Object.defineProperty(HTMLImageElement.prototype, 'src', {
    configurable: true, enumerable: true,
    get: function () { return desc.get.call(this); },
    set: function (v) {
      if (typeof v === 'string' && v.indexOf(PREF) === 0) {
        this.__virtual = v; this.__carregada = false;
        if (observador) observador.observe(this); else carregar(this);
      } else desc.set.call(this, v);
    },
  });
  window.__carregarImagensAte = function (k) {                      // usado para voltar de onde parou
    var imgs = [].slice.call(document.querySelectorAll('#paginas figure img')).slice(0, k + 1);
    return Promise.all(imgs.map(function (i) { if (observador) observador.unobserve(i); return carregar(i); }));
  };

  /* ---------- links: o leitor monta /leitor?c=…, / e /?obra=…; no app isso são páginas do app ---------- */
  function paraApp(u) {
    if (u.pathname === '/leitor') return 'leitor.html' + u.search;
    return null;
  }
  document.addEventListener('click', function (ev) {
    if (ev.defaultPrevented || ev.button > 0 || ev.metaKey || ev.ctrlKey) return;
    var a = ev.target.closest && ev.target.closest('a[href]'); if (!a) return;
    var u; try { u = new URL(a.getAttribute('href'), location.href); } catch (_) { return; }
    if (u.origin !== location.origin) return;
    var destino = paraApp(u);
    if (destino) { ev.preventDefault(); location.href = destino; }
  }, true);

  /* ---------- erro legível quando o capítulo não abre ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    var c = document.getElementById('carregando'); if (!c || !window.MutationObserver) return;
    var mo = new MutationObserver(function () {
      if (motivoFalha && c.textContent !== motivoFalha && !document.querySelector('#paginas figure')) { c.textContent = motivoFalha; }
    });
    mo.observe(c, { childList: true, characterData: true, subtree: true });
  });

  /* ---------- volta de onde parou (por capítulo, guardado neste celular) ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    var rel = new URLSearchParams(location.search).get('c') || '', principal = document.getElementById('paginas');
    if (!rel || !principal) return;
    var chave = 'pos:' + rel, restaurado = false;
    function figuras() { return [].slice.call(principal.querySelectorAll('figure')); }
    function atual() {
      var f = figuras(), ref = window.innerHeight * 0.3, k = 0;
      for (var i = 0; i < f.length; i++) { if (f[i].getBoundingClientRect().top <= ref) k = i; else break; }
      return k;
    }
    var agendado = false;
    window.addEventListener('scroll', function () {
      if (!restaurado || agendado) return; agendado = true;
      requestAnimationFrame(function () { agendado = false; guardar(chave, String(atual())); });
    }, { passive: true });
    new MutationObserver(function (_, mo) {
      var f = figuras(); if (!f.length || restaurado) return; mo.disconnect();
      var salvo = parseInt(lembrar(chave), 10);
      if (!(salvo > 0 && salvo < f.length)) { restaurado = true; return; }
      var limite = new Promise(function (ok) { setTimeout(ok, 5000); });
      Promise.race([window.__carregarImagensAte(salvo), limite]).then(function () {
        if (window.ajustarTudo) window.ajustarTudo();
        figuras()[salvo].scrollIntoView({ block: 'start' }); restaurado = true;
      });
    }).observe(principal, { childList: true });
  });
})();
