/* Regra única de "capítulo traduzido" para o app: o que conta como concluído e quais capítulos entram num download.
   Concluído = tem tradução e nenhuma fala ficou sem traduzir (incompleta === 0). Parcial e só-original nunca entram. */
(function (raiz) {
  'use strict';
  function estado(c) {
    if (!c || !c.traduzido) return 'original';
    return c.incompleta > 0 ? 'incompleto' : 'concluido';
  }
  /* Cópia local já serve? Só se foi guardada com a tradução concluída (campo gravado no download; cópias antigas sem o campo baixam de novo uma vez). */
  function localServe(loc) { return !!(loc && loc.traduzido && loc.traducaoCompleta === true); }
  /* caps: capítulos da obra no notebook (do mais antigo ao mais novo); locais: { rel: capítuloLocal }.
     modo 'offline' pula o que já está no celular completo; modo 'zip' baixa tudo que é concluído (o arquivo é escolha do usuário). */
  function plano(caps, locais, modo) {
    var p = { baixar: [], jaNoCelular: [], incompletos: [], semTraducao: [] };
    caps.forEach(function (c) {
      var e = estado(c);
      if (e === 'original') p.semTraducao.push(c);
      else if (e === 'incompleto') p.incompletos.push(c);
      else if (modo === 'offline' && localServe(locais[c.rel])) p.jaNoCelular.push(c);
      else p.baixar.push(c);
    });
    return p;
  }
  var api = { estado: estado, plano: plano, localServe: localServe };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else raiz.Traduzidos = api;
})(typeof window !== 'undefined' ? window : globalThis);
