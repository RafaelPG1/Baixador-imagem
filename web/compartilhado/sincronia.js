/* Histórico de leitura do aparelho (celular/app) e sincronia com o notebook. Fica em localStorage ('baixador.hist'):
   { posicoes: {rel: {p,n,f,t}}, lidos: {rel: {v,t}}, estados: {obra: {e,t}}, obras: {id: ficha} }  (t = ms).
   `obras` (ficha da obra: último encontrado/baixado/traduzido/lido, situação…) é do notebook: o aparelho guarda a cópia mais nova e devolve o que tem; quem junta os campos é o notebook. Na mesclagem o item mais NOVO vence,
   então dados velhos de um lado nunca apagam o que foi feito depois do outro. O capítulo lido também continua em 'lido:<rel>' (usado pela lista). */
(function (raiz) {
  'use strict';
  var HIST = 'baixador.hist', ESTADOS = ['', 'quero', 'lendo', 'concluida'];
  function criar(st) {
    function ler() { try { var h = JSON.parse(st.getItem(HIST)) || {}; return { posicoes: h.posicoes || {}, lidos: h.lidos || {}, estados: h.estados || {}, obras: h.obras || {} }; } catch (_) { return { posicoes: {}, lidos: {}, estados: {}, obras: {} }; } }
    function gravar(h) { try { st.setItem(HIST, JSON.stringify(h)); } catch (_) {} }
    function estadoDaObra(obra) { var x = ler().estados[obra]; return x ? x.e : ''; }
    function definirEstado(obra, e) { if (ESTADOS.indexOf(e) < 0) return; var h = ler(); h.estados[obra] = { e: e, t: Date.now() }; gravar(h); }
    function marcarLido(rel, v) { var h = ler(); h.lidos[rel] = { v: !!v, t: Date.now() }; gravar(h); try { v ? st.setItem('lido:' + rel, '1') : st.removeItem('lido:' + rel); } catch (_) {} }
    function ultima() {
      var h = ler(), melhor = null;
      Object.keys(h.posicoes).forEach(function (rel) { var v = h.posicoes[rel]; if (v.p < v.n && (!melhor || v.t > melhor.t)) melhor = { rel: rel, p: v.p, n: v.n, f: v.f, t: v.t }; });
      return melhor;
    }
    function payload() {                                             // 'lido:' antigos (sem data) vão com t=1: perdem para qualquer decisão datada
      var h = ler();
      for (var i = 0; i < (st.length || 0); i++) { var k = st.key(i); if (k && k.indexOf('lido:') === 0 && st.getItem(k) === '1' && !h.lidos[k.slice(5)]) h.lidos[k.slice(5)] = { v: true, t: 1 }; }
      return h;
    }
    function mesclar(srv) {                                          // resposta do notebook → local (o mais novo vence, item a item)
      var h = ler(); srv = srv || {};
      Object.keys(srv.posicoes || {}).forEach(function (rel) { var v = srv.posicoes[rel]; if (v && v.t > ((h.posicoes[rel] || {}).t || 0)) h.posicoes[rel] = v; });
      Object.keys(srv.estados || {}).forEach(function (o) { var v = srv.estados[o]; if (v && v.t > ((h.estados[o] || {}).t || 0)) h.estados[o] = v; });
      Object.keys(srv.lidos || {}).forEach(function (rel) {
        var v = srv.lidos[rel]; if (!v || !v.t || v.t <= ((h.lidos[rel] || {}).t || 0)) return;
        h.lidos[rel] = { v: !!v.v, t: v.t };
        try { v.v ? st.setItem('lido:' + rel, '1') : st.removeItem('lido:' + rel); } catch (_) {}
      });
      Object.keys(srv.obras || {}).forEach(function (id) { var v = srv.obras[id], a = h.obras[id]; if (v && typeof v === 'object' && (!a || (v.t_atualizado || 0) >= (a.t_atualizado || 0))) h.obras[id] = v; });   // cópia mais nova da ficha; nada some
      gravar(h); return h;
    }
    var ultimaSync = 0, emAndamento = null, situacao = 'aguardando', ouvintes = [];
    function mudou(e) { situacao = e; ouvintes.forEach(function (f) { try { f(e); } catch (_) {} }); }
    function aoMudarEstado(f) { ouvintes.push(f); f(situacao); }          // 'sincronizado' | 'sincronizando' | 'aguardando' (sem conexão com o notebook)
    function sincronizar(enviar, forcar) {                          // enviar(corpo) → Promise<json do notebook>; no máx. 1 por 8 s, nunca duas ao mesmo tempo
      if (emAndamento) return emAndamento;
      if (!forcar && Date.now() - ultimaSync < 8000) return Promise.resolve(null);
      ultimaSync = Date.now();
      mudou('sincronizando');
      emAndamento = Promise.resolve().then(function () { return enviar(payload()); })
        .then(function (r) { if (!r || typeof r !== 'object') throw new Error('resposta inválida'); mesclar(r); return r; })   // resposta quebrada/cortada: nada é gravado
        .then(function (r) { emAndamento = null; mudou('sincronizado'); return r; }, function (e) { emAndamento = null; mudou('aguardando'); throw e; });
      return emAndamento;
    }
    function automatico(enviar, aoAtualizar) {                      // sem botão: ao abrir, ao voltar ao app, ao reconectar e de tempos em tempos
      function rodar(forcar) {
        if (typeof document !== 'undefined' && document.hidden) return;
        var antes = JSON.stringify(ler());
        sincronizar(enviar, forcar).then(function (r) { if (r && aoAtualizar && JSON.stringify(ler()) !== antes) aoAtualizar(); }, function () {});
      }
      if (typeof window !== 'undefined' && window.addEventListener) {
        window.addEventListener('online', function () { rodar(true); });
        window.addEventListener('focus', function () { rodar(false); });
        window.addEventListener('pageshow', function () { rodar(false); });
        document.addEventListener('visibilitychange', function () { if (!document.hidden) rodar(true); });
      }
      var tempo = setInterval(function () { rodar(false); }, 20000); if (tempo && tempo.unref) tempo.unref();
      rodar(true);
      return rodar;
    }
    return { ler: ler, gravar: gravar, estadoDaObra: estadoDaObra, definirEstado: definirEstado, marcarLido: marcarLido, ultima: ultima, payload: payload, mesclar: mesclar, sincronizar: sincronizar, automatico: automatico, aoMudarEstado: aoMudarEstado, ESTADOS: ESTADOS };
  }
  var api = { criar: criar, ROTULOS: { '': 'Sem estado', quero: 'Quero ler', lendo: 'Lendo', concluida: 'Concluída' }, TEXTO_ESTADO: { sincronizado: 'Sincronizado', sincronizando: 'Sincronizando…', aguardando: 'Aguardando conexão' } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else raiz.Sincronia = api;
})(typeof window !== 'undefined' ? window : globalThis);
