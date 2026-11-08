/* Ajuste do texto traduzido dentro de cada caixa. Mesmo algoritmo do leitor do notebook (web/leitor/leitor.js):
   se mudar lá, copie para cá. */
(function () {
  'use strict';
  var NBSP = ' ';
  var BALANCEIA = !!(window.CSS && CSS.supports && CSS.supports('text-wrap', 'balance'));
  var FRACAS = /^(a|o|e|à|às|ao|aos|as|os|um|uma|uns|de|do|da|dos|das|em|no|na|nos|nas|por|pra|pro|que|se|me|te|lhe|eu|tu|ele|ela|mas|ou|já|só|há|é|nem|com|sem|até|meu|seu|teu|sua|tua|esse|essa|este|esta|isso|isto|não|sim|mais|muito)$/i;
  /* Palavras curtas ficam coladas à seguinte e a última palavra não fica sozinha na linha (espaço não separável);
     nada de hifenização: palavra nunca é cortada. O texto guardado e o do editor continuam sem NBSP. */
  function colarPalavras(texto) {
    var p = texto.replace(/ /g, ' ').trim().split(/\s+/), n = p.length, saida = '';
    if (n < 2) return p.join('');
    for (var i = 0; i < n; i++) {
      saida += p[i];
      if (i === n - 1) break;
      var limpa = p[i].replace(/[^A-Za-zÀ-ÿ0-9-]/g, ''), fim = /[.!?…,;:]$/.test(p[i]);
      var cola = !fim && (p[i] === '-' || p[i] === '—' || (limpa.length <= 2 || FRACAS.test(limpa)) && p[i].length + p[i + 1].length <= 16);
      if (i === n - 2 && n >= 3 && p[i].length + p[i + 1].length <= 14) cola = true;      // evita a "viúva" no fim
      saida += cola ? NBSP : ' ';
    }
    return saida;
  }
  function escala(fig) { return fig && Number(fig.dataset.w) > 0 ? fig.clientWidth / Number(fig.dataset.w) : 0; }
  function geometria(el, g) { el.style.left = g[0]; el.style.top = g[1]; el.style.width = g[2]; el.style.height = g[3]; }
  function cabe(el) { return el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1; }
  function melhorFonte(el, teto) {
    var lo = 5, hi = Math.max(8, Math.min(el.clientHeight, teto)), melhor = 0;
    while (lo <= hi) {
      var meio = (lo + hi) >> 1; el.style.fontSize = meio + 'px';
      if (cabe(el)) { melhor = meio; lo = meio + 1; } else { hi = meio - 1; }
    }
    return melhor;
  }
  function linhas(el) {
    var t = el.firstChild; if (!t || t.nodeType !== 3) return 0;
    var r = document.createRange(); r.selectNodeContents(t); return r.getClientRects().length;
  }
  /* Equilibra as linhas: o texto ocupa a largura mínima que mantém o mesmo número de linhas (sem recuo gigante num lado). */
  function equilibrar(el) {
    el.style.paddingLeft = el.style.paddingRight = '';
    var n = linhas(el);
    if (n < 2 || (BALANCEIA && n <= 6)) return;
    var cheio = el.clientWidth, lo = 0, hi = Math.floor(cheio / 2) - 6, melhor = 0;
    while (lo <= hi) {
      var meio = (lo + hi) >> 1; el.style.paddingLeft = el.style.paddingRight = meio + 'px';
      if (linhas(el) <= n && cabe(el)) { melhor = meio; lo = meio + 1; } else { hi = meio - 1; }
    }
    if (melhor > 0) el.style.paddingLeft = el.style.paddingRight = melhor + 'px'; else el.style.paddingLeft = el.style.paddingRight = '';
  }
  function ajustar(el) {
    var fig = el.closest('figure'), fixo = parseFloat(el.dataset.f);
    var ligado = colarPalavras(el.textContent); if (el.textContent !== ligado) el.textContent = ligado;
    if (!el.dataset.g0) el.dataset.g0 = JSON.stringify([el.style.left, el.style.top, el.style.width, el.style.height]);
    var base = JSON.parse(el.dataset.g0); geometria(el, base);          // sempre parte da caixa original (o editor lê esta)
    el.removeAttribute('data-s'); el.style.paddingLeft = el.style.paddingRight = '';
    var esc = escala(fig);
    if (fixo > 0 && esc > 0) { el.style.fontSize = (fixo * esc) + 'px'; equilibrar(el); return; }
    var ref = parseFloat(el.dataset.r), teto = 64;
    if (ref > 0 && esc > 0) teto = Math.max(9, Math.min(64, ref * esc * 0.95));       // nunca bem maior que a letra original
    var f = melhorFonte(el, teto);
    var edicao = document.body.classList.contains('edicao');
    if (el.dataset.lv && !edicao && (f === 0 || f < teto * 0.8)) {                  // aperto: usa o espaço livre do balão
      var lv = JSON.parse(el.dataset.lv), pct = function (v) { return v + '%'; };
      geometria(el, [pct(lv[0]), pct(lv[1]), pct(lv[2]), pct(lv[3])]);
      var g = melhorFonte(el, teto);
      if (g > f + 0.5) f = g; else { geometria(el, base); f = melhorFonte(el, teto); }
    }
    if (f === 0) { f = 5; el.setAttribute('data-s', '1'); }                          // nem no mínimo cabe: não corta o texto
    el.style.fontSize = f + 'px';
    equilibrar(el);
  }
  function ajustarTudo() { document.querySelectorAll('.tr').forEach(ajustar); }
  window.AjusteTexto = { ajustar: ajustar, ajustarTudo: ajustarTudo };
})();
