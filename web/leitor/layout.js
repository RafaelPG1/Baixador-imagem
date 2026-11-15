// Encaixa um texto numa caixa: acha o maior tamanho de fonte em que as linhas cabem. Sem DOM: quem chama passa
// measure(texto, tamanho) → largura. Serve igual no navegador (canvas) e nos testes (Node).
(function (raiz) {
  function wrap(measure, words, size, width) {
    var lines = [];
    var line = '';
    words.forEach(function (w) {
      var next = line ? line + ' ' + w : w;
      if (line && measure(next, size) > width) { lines.push(line); line = w; } else line = next;
    });
    if (line) lines.push(line);
    return lines;
  }

  // Devolve { size, lines, lineHeight, overflow }. overflow = não coube nem no tamanho mínimo (usa o mínimo mesmo assim).
  function fitText(measure, text, caixa, opcoes) {
    var w = caixa[2];
    var h = caixa[3];
    var o = opcoes || {};
    var fontMax = o.fontMax == null ? 40 : o.fontMax;
    var fontMin = o.fontMin == null ? 8 : o.fontMin;
    var lineHeight = o.lineHeight == null ? 1.12 : o.lineHeight;
    var words = text.trim().split(/\s+/).filter(Boolean);
    if (!words.length) return { size: fontMin, lines: [], lineHeight: lineHeight, overflow: false };
    function cabe(size) {
      if (words.some(function (x) { return measure(x, size) > w; })) return null; // palavra sozinha não cabe na largura
      var lines = wrap(measure, words, size, w);
      return lines.length * size * lineHeight <= h ? lines : null;
    }
    var size = Math.max(fontMin, Math.floor(fontMax));
    var lines = null;
    for (; size >= fontMin; size--) { lines = cabe(size); if (lines) break; }
    if (!lines) {
      size = fontMin;
      return { size: size, lines: wrap(measure, words, size, w), lineHeight: lineHeight, overflow: true };
    }
    // equilibra: mesma quantidade de linhas, na menor largura possível (evita última linha de uma palavra só)
    var narrow = w;
    var sz = size;
    while (narrow > w * 0.5 && wrap(measure, words, sz, narrow * 0.97).length === lines.length &&
           !words.some(function (x) { return measure(x, sz) > narrow * 0.97; })) narrow *= 0.97;
    return { size: size, lines: wrap(measure, words, size, narrow), lineHeight: lineHeight, overflow: false };
  }

  var api = { wrap: wrap, fitText: fitText };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else raiz.LeitorLayout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
