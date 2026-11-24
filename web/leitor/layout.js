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

  // ---------------------------------------------------------------------------------------------------------------
  // Encaixe pelo FORMATO do balão. `perfil` = faixas [y, x0, x1] do miolo do balão (sem contorno), de cima para baixo. Cada linha do texto
  // usa a largura que o balão realmente tem naquela altura (balão redondo é estreito em cima e embaixo), centrada na caixa.
  // Ordem de prioridade: (1) maior fonte que cabe de verdade no balão; (2) fonte menor, até o piso de leitura; (3) só então o texto vaza.
  function largurasDoPerfil(perfil, cx, y0, y1) {                     // largura livre, centrada em cx, entre as alturas y0 e y1
    var w = Infinity, achou = false;
    for (var i = 0; i < perfil.length; i++) {
      var f = perfil[i];
      if (f[0] < y0 - 1 || f[0] > y1 + 1) continue;
      achou = true;
      w = Math.min(w, 2 * Math.min(cx - f[1], f[2] - cx));
    }
    if (!achou) return 0;                                              // fora do balão (acima/abaixo): sem espaço
    return Math.max(0, w);
  }
  function quebrar(measure, words, size, larguras) {                   // guloso, com uma largura por linha; null se passar de larguras.length linhas
    var lines = [], line = '', k = 0;
    for (var i = 0; i < words.length; i++) {
      var w = words[i], prox = line ? line + ' ' + w : w;
      if (k >= larguras.length) return null;
      if (!line && measure(w, size) > larguras[k]) return null;       // palavra sozinha não cabe nesta linha
      if (line && measure(prox, size) > larguras[k]) { lines.push(line); k++; line = w; if (k >= larguras.length || measure(w, size) > larguras[k]) return null; }
      else line = prox;
    }
    if (line) lines.push(line);
    return lines;
  }
  function fitShape(measure, text, caixa, perfil, o) {
    var words = text.trim().split(/\s+/).filter(Boolean);
    var lineHeight = o.lineHeight == null ? 1.12 : o.lineHeight;
    if (!words.length || !perfil || perfil.length < 2) return null;
    var cx = caixa[0] + caixa[2] / 2, cy = caixa[1] + caixa[3] / 2;
    var piso = o.piso;
    // a caixa só limita para dentro do balão: o perfil já é o limite real; usa o maior entre os dois em altura
    var yTop = perfil[0][0], yBot = perfil[perfil.length - 1][0];
    for (var size = Math.floor(o.fontMax); size >= piso; size--) {
      var lh = size * lineHeight;
      for (var n = 1; n <= 14; n++) {
        var bloco = n * lh;
        var topo = cy - bloco / 2;
        if (topo < yTop - 1 || topo + bloco > yBot + 1) { if (topo + bloco / 2 > yBot) break; continue; }
        var larg = [];
        for (var i = 0; i < n; i++) larg.push(largurasDoPerfil(perfil, cx, topo + i * lh, topo + (i + 1) * lh));
        if (larg.some(function (x) { return x < size * 0.8; })) continue;
        var lines = quebrar(measure, words, size, larg);
        if (lines && lines.length <= n) {
          // linhas que sobram viram nada: recentra o bloco no que foi usado
          return { size: size, lines: lines, lineHeight: lineHeight, overflow: false, caixa: [cx - caixa[2] / 2, cy - lines.length * lh / 2, caixa[2], lines.length * lh], forma: true };
        }
      }
    }
    return null;
  }

  // Encaixa uma fala: forma do balão → piso de leitura → vazamento mínimo. opcoes: { fontMax, fontMin, perfil, limites }.
  function fitBalao(measure, text, caixa, opcoes) {
    var o = opcoes || {};
    var fontMax = o.fontMax == null ? 40 : o.fontMax;
    var fontMin = o.fontMin == null ? 10 : o.fontMin;
    var piso = Math.max(fontMin, Math.round(fontMax * 0.55));         // piso confortável; abaixo disso o texto vaza em vez de encolher
    var base = { fontMax: fontMax, lineHeight: o.lineHeight };
    var r = fitShape(measure, text, caixa, o.perfil, { fontMax: fontMax, lineHeight: o.lineHeight, piso: piso });
    if (r) return r;
    if (o.perfil && o.perfil.length >= 2) {                           // ainda dentro do balão, mas até o piso absoluto
      r = fitShape(measure, text, caixa, o.perfil, { fontMax: Math.min(fontMax, piso), lineHeight: o.lineHeight, piso: fontMin });
      if (r) return r;
    }
    // vaza: a caixa cresce aos poucos (nunca mais que 2x) mantendo a fonte no piso confortável
    var opts = { fontMax: fontMax, fontMin: piso, lineHeight: o.lineHeight, alvo: 1 };
    var fatores = [1, 1.1, 1.2, 1.35, 1.5, 1.75, 2], melhor = null;
    for (var i = 0; i < fatores.length; i++) {
      var k = fatores[i], c = [caixa[0] - caixa[2] * (k - 1) / 2, caixa[1] - caixa[3] * (k - 1) / 2, caixa[2] * k, caixa[3] * k];
      var f = fitText(measure, text, c, opts);
      f.caixa = c;
      if (!f.overflow) return f;
      melhor = f;
    }
    melhor.size = Math.max(fontMin, melhor.size);                      // última saída: piso absoluto, aceitando pequeno excesso
    melhor.lines = wrap(measure, text.trim().split(/\s+/).filter(Boolean), melhor.size, melhor.caixa[2]);
    return melhor;
  }

  // ---------------------------------------------------------------------------------------------------------------
  // Colisão entre falas da mesma imagem: cada fala ocupa os retângulos das suas linhas; se dois retângulos de falas diferentes se
  // tocam, as falas se afastam (pelo eixo de menor penetração) e, se ainda não der, a fonte diminui até o piso.
  function retangulos(measure, f, margem) {
    var lh = f.size * f.lineHeight, cx = f.caixa[0] + f.caixa[2] / 2, topo = f.caixa[1] + f.caixa[3] / 2 - lh * f.lines.length / 2;
    return f.lines.map(function (l, i) {
      var w = measure(l, f.size) + f.size * 0.2 + margem * 2;
      return [cx - w / 2, topo + i * lh - margem, w, lh + margem * 2];
    });
  }
  function penetracao(a, b) {                                          // [px, py] = quanto uma entra na outra; null se não se tocam
    var px = Math.min(a[0] + a[2], b[0] + b[2]) - Math.max(a[0], b[0]);
    var py = Math.min(a[1] + a[3], b[1] + b[3]) - Math.max(a[1], b[1]);
    return px > 0 && py > 0 ? [px, py] : null;
  }
  function colisoes(rs) {                                              // todos os pares (i<j) com retângulos que se tocam
    var out = [];
    for (var i = 0; i < rs.length; i++) for (var j = i + 1; j < rs.length; j++) {
      var pior = null;
      for (var a = 0; a < rs[i].length; a++) for (var b = 0; b < rs[j].length; b++) {
        var p = penetracao(rs[i][a], rs[j][b]);
        if (p && (!pior || p[0] * p[1] > pior[0] * pior[1])) pior = p;
      }
      if (pior) out.push({ i: i, j: j, p: pior });
    }
    return out;
  }
  function fitPagina(measure, falas, limites, opcoes) {
    var o = opcoes || {};
    var res = falas.map(function (f) {
      var r = fitBalao(measure, f.texto, f.caixa, { fontMax: f.fonteMax, fontMin: o.fontMin, perfil: f.perfil, lineHeight: o.lineHeight });
      r.fonteMax = f.fonteMax == null ? 40 : f.fonteMax;
      return r;
    });
    var W = limites ? limites[0] : Infinity, H = limites ? limites[1] : Infinity;
    function dentro(r) {                                                // mantém o bloco de texto dentro da imagem
      var c = r.caixa, h = r.lines.length * r.size * r.lineHeight;
      var x = Math.min(Math.max(c[0], Math.min(0, c[0])), Math.max(W - c[2], c[0]));
      var cy = Math.min(Math.max(c[1] + c[3] / 2, h / 2), Math.max(H - h / 2, h / 2));
      r.caixa = [x, cy - c[3] / 2, c[2], c[3]];
    }
    for (var volta = 0; volta < 12; volta++) {
      for (var it = 0; it < 24; it++) {
        var rs = res.map(function (r) { return retangulos(measure, r, 1); });
        var cols = colisoes(rs);
        if (!cols.length) return res;
        cols.forEach(function (c) {
          var A = res[c.i], B = res[c.j];
          var ca = A.caixa, cb = B.caixa;
          var dx = (ca[0] + ca[2] / 2) - (cb[0] + cb[2] / 2), dy = (ca[1] + ca[3] / 2) - (cb[1] + cb[3] / 2);
          if (c.p[1] <= c.p[0] * 1.5) {                                 // separa na vertical (texto empilhado é o caso comum)
            var d = (c.p[1] + 2) / 2, s = dy >= 0 ? 1 : -1;
            A.caixa = [ca[0], ca[1] + s * d, ca[2], ca[3]]; B.caixa = [cb[0], cb[1] - s * d, cb[2], cb[3]];
          } else {
            var e = (c.p[0] + 2) / 2, t = dx >= 0 ? 1 : -1;
            A.caixa = [ca[0] + t * e, ca[1], ca[2], ca[3]]; B.caixa = [cb[0] - t * e, cb[1], cb[2], cb[3]];
          }
          dentro(A); dentro(B);
        });
      }
      // empurrar não bastou (sem espaço): diminui a fonte das falas envolvidas e tenta de novo
      var envolvidas = {};
      colisoes(res.map(function (r) { return retangulos(measure, r, 1); })).forEach(function (c) { envolvidas[c.i] = envolvidas[c.j] = true; });
      var mudou = false;
      Object.keys(envolvidas).forEach(function (k) {
        var r = res[k], novo = Math.floor(r.size * 0.92);
        if (novo < (o.fontMin == null ? 10 : o.fontMin)) return;
        var words = falas[k].texto.trim().split(/\s+/).filter(Boolean), larg = r.caixa[2];
        r.size = novo; r.lines = wrap(measure, words, novo, Math.max(larg, r.lines.reduce(function (m, l) { return Math.max(m, measure(l, novo)); }, 0)));
        r.caixa = [r.caixa[0], r.caixa[1] + r.caixa[3] / 2 - r.lines.length * novo * r.lineHeight / 2, r.caixa[2], r.lines.length * novo * r.lineHeight];
        mudou = true;
      });
      if (!mudou) break;
    }
    return res;
  }

  var api = { wrap: wrap, fitText: fitText, fitFlexible: fitFlexible, fitBalao: fitBalao, fitPagina: fitPagina, colisoes: colisoes, retangulos: retangulos };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else raiz.LeitorLayout = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);
