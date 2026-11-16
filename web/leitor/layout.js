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

  // Como fitText, mas o texto pode VAZAR da caixa: se para caber ele teria de encolher demais (menos que `alvo` do tamanho original,
  // fontMax), a caixa cresce a partir do centro (até 2x em cada lado, sem passar da imagem) antes de a fonte diminuir.
  // Devolve { size, lines, lineHeight, overflow, caixa } com a caixa efetivamente usada.
  function fitFlexible(measure, text, caixa, opcoes) {
    var o = opcoes || {};
    var fontMax = o.fontMax == null ? 40 : o.fontMax;
    var alvo = (o.alvo == null ? 0.8 : o.alvo) * fontMax;
    var limites = o.limites || null;                     // [largura, altura] da imagem
    // A caixa cresce, mas não passa da imagem; se a caixa original já passa (balão cortado: o texto atravessa a emenda), esse excesso é permitido.
    function dentro(c) {
      if (!limites) return c;
      var x0 = Math.max(Math.min(0, caixa[0]), c[0]), y0 = Math.max(Math.min(0, caixa[1]), c[1]);
      var x1 = Math.min(Math.max(limites[0], caixa[0] + caixa[2]), c[0] + c[2]);
      var y1 = Math.min(Math.max(limites[1], caixa[1] + caixa[3]), c[1] + c[3]);
      return x1 - x0 >= 1 && y1 - y0 >= 1 ? [x0, y0, x1 - x0, y1 - y0] : c;
    }
    var melhor = fitText(measure, text, caixa, o);
    melhor.caixa = caixa;
    if (!melhor.overflow && melhor.size >= alvo) return melhor;
    var fatores = [1.15, 1.3, 1.5, 1.75, 2];
    for (var i = 0; i < fatores.length; i++) {
      var k = fatores[i];
      var c = dentro([caixa[0] - caixa[2] * (k - 1) / 2, caixa[1] - caixa[3] * (k - 1) / 2, caixa[2] * k, caixa[3] * k]);
      var r = fitText(measure, text, c, o);
      r.caixa = c;
      if (melhor.overflow && !r.overflow) melhor = r;
      else if (melhor.overflow === r.overflow && r.size > melhor.size) melhor = r;
      if (!melhor.overflow && melhor.size >= alvo) break;
    }
    return melhor;
  }

  var api = { wrap: wrap, fitText: fitText, fitFlexible: fitFlexible };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else raiz.LeitorLayout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
