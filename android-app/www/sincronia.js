/* Histórico de leitura do aparelho (celular/app) e sincronia com o notebook. Fica em localStorage ('baixador.hist'):
   { posicoes: {rel: {p,n,f,t}}, lidos: {rel: {v,t}}, estados: {obra: {e,t}} }  (t = ms). Na mesclagem o item mais NOVO vence,
   então dados velhos de um lado nunca apagam o que foi feito depois do outro. O capítulo lido também continua em 'lido:<rel>' (usado pela lista). */
(function (raiz) {
  'use strict';
  var HIST = 'baixador.hist', ESTADOS = ['', 'quero', 'lendo', 'concluida'];
  function criar(st) {
    function ler() { try { var h = JSON.parse(st.getItem(HIST)) || {}; return { posicoes: h.posicoes || {}, lidos: h.lidos || {}, estados: h.estados || {} }; } catch (_) { return { posicoes: {}, lidos: {}, estados: {} }; } }
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
      gravar(h); return h;
    }
    var ultimaSync = 0, emAndamento = null;
    function sincronizar(enviar, forcar) {                          // enviar(corpo) → Promise<json do notebook>; no máx. 1 por 8 s, nunca duas ao mesmo tempo
      if (emAndamento) return emAndamento;
      if (!forcar && Date.now() - ultimaSync < 8000) return Promise.resolve(null);
      ultimaSync = Date.now();
      emAndamento = Promise.resolve().then(function () { return enviar(payload()); }).then(function (r) { mesclar(r); return r; }).then(function (r) { emAndamento = null; return r; }, function (e) { emAndamento = null; throw e; });
      return emAndamento;
    }
    return { ler: ler, gravar: gravar, estadoDaObra: estadoDaObra, definirEstado: definirEstado, marcarLido: marcarLido, ultima: ultima, payload: payload, mesclar: mesclar, sincronizar: sincronizar, ESTADOS: ESTADOS };
  }
  var api = { criar: criar, ROTULOS: { '': 'Sem estado', quero: 'Quero ler', lendo: 'Lendo', concluida: 'Concluída' } };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else raiz.Sincronia = api;
})(typeof window !== 'undefined' ? window : globalThis);
