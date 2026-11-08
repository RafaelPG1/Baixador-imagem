(function () {
  var $ = function (id) { return document.getElementById(id); };
  var meta = document.querySelector('meta[name=baixador-token]');
  var botao = $('editar'), ed = $('editor'), msg = $('ed-msg');
  if (!botao) return;                                 // o leitor atual não tem botão de edição: módulo inativo
  if (!meta) {                                        // aberto direto do arquivo: a edição precisa do programa
    botao.addEventListener('click', function () {
      ed.hidden = !ed.hidden;
      $('ed-campos').hidden = true; document.querySelectorAll('#editor .geral button').forEach(function (b) { b.hidden = b.id !== 'ed-fechar'; });
      $('ed-titulo').textContent = 'Editar tradução'; msg.className = '';
      msg.textContent = 'Para corrigir ou refazer trechos, abra este capítulo pelo programa (botão “Biblioteca de imagens” ou “Ler as imagens salvas”). Abrindo o arquivo direto da pasta só é possível ler.';
    });
    $('ed-fechar').addEventListener('click', function () { ed.hidden = true; });
    return;
  }
  var T = meta.content, base = window.BAIXADOR_BASE || '';        // base = /ler/<id>/<Obra>/<Capítulo>/, definida pelo leitor
  var ocupado = false, sel = null, caixa = null, arrasto = null, ultimo = null, COR = /^#[0-9a-fA-F]{6}$/;
  var orig = $('ed-orig'), trad = $('ed-trad'), fundo = $('ed-fundo'), cor = $('ed-cor'), fonte = $('ed-fonte');
  var B = { retrad: $('ed-retrad'), aplicar: $('ed-aplicar'), remover: $('ed-remover'), area: $('ed-area'), criar: $('ed-criar'),
    img: $('ed-img'), tudo: $('ed-tudo') };

  function aviso(t, erro) { msg.textContent = t || ''; msg.className = erro ? 'erro' : ''; }
  function ocupar(v) { ocupado = v; Object.keys(B).forEach(function (k) { B[k].disabled = v; }); }
  function hex(rgb) {
    var m = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(rgb || ''); if (!m) return '#ffffff';
    return '#' + [1, 2, 3].map(function (i) { return ('0' + Number(m[i]).toString(16)).slice(-2); }).join('');
  }
  function post(acao, corpo) {
    ocupar(true); aviso('Trabalhando… (na primeira vez os modelos são carregados; pode levar alguns segundos)');
    corpo.base = base;
    return fetch('/api/bloco/' + acao + '?t=' + encodeURIComponent(T), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corpo) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.erro || ('Erro ' + r.status)); return j; }); })
      .then(function (j) { ocupar(false); return j; }, function (e) { ocupar(false); aviso(e.message, true); throw e; });
  }

  /* ---------- desenho dos trechos ---------- */
  function desenhar(fig, info) {
    fig.querySelectorAll('.tr').forEach(function (e) { e.remove(); });
    info.blocos.forEach(function (b, i) {
      if (!(b.w > 0 && b.h > 0) || !String(b.traduzido || '').trim()) return;
      var d = document.createElement('div'); d.className = 'tr'; d.dataset.i = i; d.title = b.original || '';
      d.style.left = (b.x / info.w * 100) + '%'; d.style.top = (b.y / info.h * 100) + '%';
      d.style.width = (b.w / info.w * 100) + '%'; d.style.height = (b.h / info.h * 100) + '%';
      d.style.background = COR.test(b.fundo) ? b.fundo : '#ffffff'; d.style.color = COR.test(b.cor) ? b.cor : '#111111';
      if (b.fonte > 0) d.dataset.f = b.fonte;
      if (b.refer > 0) d.dataset.r = b.refer;
      if (b.livre && !b.manual) d.dataset.lv = JSON.stringify([b.livre[0] / info.w * 100, b.livre[1] / info.h * 100, b.livre[2] / info.w * 100, b.livre[3] / info.h * 100]);
      if (b.alertas && b.alertas.length) d.dataset.a = b.alertas.join('; ');
      d.textContent = b.traduzido; fig.appendChild(d);
    });
    fig.dataset.w = info.w; fig.dataset.h = info.h;
    fig.classList.add('com-medidas'); fig.style.aspectRatio = info.w + '/' + info.h;
    if (window.ajustarTudo) window.ajustarTudo();
  }
  function tamanhoImagem(fig) {
    var img = fig.querySelector('img');
    return [Number(fig.dataset.w) || img.naturalWidth || 1, Number(fig.dataset.h) || img.naturalHeight || 1];
  }

  /* ---------- caixa de seleção com alças (frações da figura: 0..1) ---------- */
  function removerCaixa() { if (caixa) { caixa.el.remove(); caixa = null; } }
  function criarCaixa(fig, a, tipo, alvo) {
    removerCaixa();
    var el = document.createElement('div'); el.className = 'caixa';
    ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'].forEach(function (p) { var h = document.createElement('div'); h.className = 'al'; h.dataset.p = p; el.appendChild(h); });
    fig.appendChild(el);
    caixa = { fig: fig, el: el, a: a, tipo: tipo, alvo: alvo };
    pintarCaixa();
  }
  function pintarCaixa() {
    if (!caixa) return; var a = caixa.a, s = caixa.el.style;
    s.left = (a[0] * 100) + '%'; s.top = (a[1] * 100) + '%'; s.width = ((a[2] - a[0]) * 100) + '%'; s.height = ((a[3] - a[1]) * 100) + '%';
    if (caixa.tipo === 'bloco' && caixa.alvo) {
      var t = caixa.alvo.style; t.left = s.left; t.top = s.top; t.width = s.width; t.height = s.height;
      if (window.ajustarTudo) window.ajustarTudo();
    }
  }
  function pontoNaFigura(fig, e) {
    var r = fig.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  }
  function iniciarArrasto(e, modo) {      // modo: 'move' | 'novo' | nome da alça
    var fig = caixa.fig;
    arrasto = { modo: modo, ini: pontoNaFigura(fig, e), a0: caixa.a.slice() };
    ultimo = e; try { fig.setPointerCapture(e.pointerId); } catch (x) {}
    e.preventDefault(); e.stopPropagation(); rolagemAuto();
  }
  function mover(e) {
    if (!arrasto || !caixa) return;
    ultimo = e;
    var p = pontoNaFigura(caixa.fig, e), dx = p[0] - arrasto.ini[0], dy = p[1] - arrasto.ini[1], a = arrasto.a0.slice(), m = arrasto.modo;
    if (m === 'move') {
      var w = a[2] - a[0], h = a[3] - a[1];
      a[0] = Math.min(Math.max(a[0] + dx, 0), 1 - w); a[1] = Math.min(Math.max(a[1] + dy, 0), 1 - h); a[2] = a[0] + w; a[3] = a[1] + h;
    } else if (m === 'novo') {
      a = [arrasto.ini[0], arrasto.ini[1], p[0], p[1]];
    } else {
      if (m.indexOf('w') >= 0) a[0] = a[0] + dx; if (m.indexOf('e') >= 0) a[2] = a[2] + dx;
      if (m.indexOf('n') >= 0) a[1] = a[1] + dy; if (m.indexOf('s') >= 0) a[3] = a[3] + dy;
    }
    if (m !== 'move') {                    // normaliza (permite arrastar "para trás") e limita à imagem
      a = [Math.min(a[0], a[2]), Math.min(a[1], a[3]), Math.max(a[0], a[2]), Math.max(a[1], a[3])].map(function (v) { return Math.min(Math.max(v, 0), 1); });
    }
    caixa.a = a; pintarCaixa();
  }
  function baseVisivel() {                 // janela maior que a tela: a parte de baixo fica fora de alcance do mouse
    var h = window.innerHeight;
    try { var topo = window.screenY + (window.outerHeight - window.innerHeight); var vis = screen.availHeight - topo; if (vis > 200) h = Math.min(h, vis); } catch (e) {}
    return h;
  }
  window.addEventListener('scroll', function () { if (arrasto && ultimo) mover(ultimo); }, { passive: true });
  function rolarAteBorda(borda) {         // mantém à vista a borda que está sendo ajustada
    if (!caixa) return; var r = caixa.fig.getBoundingClientRect(), a = caixa.a, fim = baseVisivel();
    var y = r.top + (borda === 't' ? a[1] : a[3]) * r.height;
    if (borda === 't' || borda === 'b') { if (y < 90) window.scrollBy(0, y - 90); else if (y > fim - 90) window.scrollBy(0, y - (fim - 90)); }
  }
  function ajustarBorda(borda, dir, passo) {
    if (!caixa || ocupado) return; var d = tamanhoImagem(caixa.fig), a = caixa.a;
    var dx = passo / d[0], dy = passo / d[1], c = function (v) { return Math.min(Math.max(v, 0), 1); };
    if (borda === 't') a[1] = c(Math.min(a[1] + dir * dy, a[3] - 4 / d[1]));
    if (borda === 'b') a[3] = c(Math.max(a[3] + dir * dy, a[1] + 4 / d[1]));
    if (borda === 'l') a[0] = c(Math.min(a[0] + dir * dx, a[2] - 4 / d[0]));
    if (borda === 'r') a[2] = c(Math.max(a[2] + dir * dx, a[0] + 4 / d[0]));
    pintarCaixa(); rolarAteBorda(borda);
  }
  function mover_tudo(dx, dy) {
    if (!caixa) return; var d = tamanhoImagem(caixa.fig), a = caixa.a, w = a[2] - a[0], h = a[3] - a[1];
    a[0] = Math.min(Math.max(a[0] + dx / d[0], 0), 1 - w); a[1] = Math.min(Math.max(a[1] + dy / d[1], 0), 1 - h); a[2] = a[0] + w; a[3] = a[1] + h;
    pintarCaixa(); rolarAteBorda(dy > 0 ? 'b' : 't');
  }
  function rolagemAuto() {                 // arrastando perto da borda da janela, a página rola sozinha
    if (!arrasto) return;
    if (ultimo) {
      var fim = baseVisivel();
      if (ultimo.clientY < 80) window.scrollBy(0, -Math.min(40, (80 - ultimo.clientY) / 3 + 6));
      else if (ultimo.clientY > fim - 80) window.scrollBy(0, Math.min(40, (ultimo.clientY - (fim - 80)) / 3 + 6));
      mover(ultimo);
    }
    requestAnimationFrame(rolagemAuto);
  }
  function terminar() {
    if (!arrasto) return; var tipoArr = arrasto.modo; arrasto = null;
    if (!caixa) return;
    var d = tamanhoImagem(caixa.fig), a = caixa.a;
    if (caixa.tipo === 'area' && ((a[2] - a[0]) * d[0] < 8 || (a[3] - a[1]) * d[1] < 8)) { limpar(); return; }
    if (caixa.tipo === 'area') mostrarArea();
  }
  document.addEventListener('pointermove', mover);
  document.addEventListener('pointerup', terminar);
  document.addEventListener('pointercancel', terminar);

  document.querySelectorAll('#ed-ajuste [data-b]').forEach(function (bt) {
    bt.addEventListener('click', function () { ajustarBorda(bt.dataset.b, Number(bt.dataset.d), 20); });
  });
  $('ed-larg').addEventListener('click', function () { if (caixa) { caixa.a[0] = 0; caixa.a[2] = 1; pintarCaixa(); } });
  $('ed-titulo').addEventListener('click', function () { ed.classList.toggle('min'); });
  document.addEventListener('keydown', function (e) {
    if (!caixa || !document.body.classList.contains('edicao')) return;
    var t = e.target && e.target.tagName; if (t === 'TEXTAREA' || t === 'INPUT') return;
    var k = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] }[e.key]; if (!k) return;
    e.preventDefault();
    if (e.shiftKey) { if (k[1]) ajustarBorda('b', k[1], 10); else ajustarBorda('r', k[0], 10); }
    else if (e.ctrlKey) { if (k[1]) ajustarBorda('t', k[1], 10); else ajustarBorda('l', k[0], 10); }
    else mover_tudo(k[0] * 5, k[1] * 5);
  });

  /* ---------- painel ---------- */
  function painel(tipo) {                  // 'nada' | 'bloco' | 'area'
    ed.hidden = false;
    $('ed-campos').hidden = tipo === 'nada';
    $('ed-ajuste').hidden = tipo === 'nada';
    $('ed-estilo').hidden = tipo !== 'bloco';
    B.retrad.hidden = B.aplicar.hidden = B.remover.hidden = tipo !== 'bloco';
    B.area.hidden = B.criar.hidden = tipo !== 'area';
    $('ed-titulo').textContent = tipo === 'bloco' ? 'Trecho selecionado' : tipo === 'area' ? 'Área selecionada' : 'Edição';
    $('ed-rot-orig').firstChild.textContent = tipo === 'bloco' ? 'Texto original (corrija o que a leitura errou) ' : 'Texto original (deixe vazio para ler da imagem) ';
  }
  function limpar() {
    document.querySelectorAll('.tr.sel').forEach(function (e) { e.classList.remove('sel'); });
    removerCaixa(); sel = null; painel('nada');
  }
  function dica() { aviso('Clique num texto para editá-lo (mova e redimensione a caixa laranja), ou arraste sobre a imagem para marcar uma área. Perto da borda da janela a página rola sozinha.'); }
  botao.addEventListener('click', function () {
    var on = document.body.classList.toggle('edicao'); botao.textContent = on ? 'Sair da edição' : 'Editar tradução';
    if (window.ajustarTudo) window.ajustarTudo();                // a edição mostra a caixa original; a leitura pode usar o espaço livre
    if (!on) { limpar(); ed.hidden = true; } else { painel('nada'); dica(); var n = document.querySelectorAll('.tr[data-a]').length; if (n) aviso(n + ' trecho(s) com alerta (contorno vermelho pontilhado). Use “Próximo alerta”.'); }
  });
  $('ed-fechar').addEventListener('click', function () { limpar(); dica(); });

  function selecionarBloco(el) {
    document.querySelectorAll('.tr.sel').forEach(function (e) { e.classList.remove('sel'); });
    var fig = el.closest('figure'); el.classList.add('sel');
    var l = parseFloat(el.style.left) / 100, t = parseFloat(el.style.top) / 100, w = parseFloat(el.style.width) / 100, h = parseFloat(el.style.height) / 100;
    criarCaixa(fig, [l, t, l + w, t + h], 'bloco', el);
    sel = { fig: fig, i: Number(el.dataset.i), el: el };
    painel('bloco'); orig.value = el.title || ''; trad.value = el.textContent.replace(/\u00a0/g, ' ');
    fundo.value = hex(el.style.background); cor.value = hex(el.style.color); fonte.value = el.dataset.f || '';
    aviso(el.dataset.a ? '⚠ Revisar: ' + el.dataset.a + '. Arraste a caixa laranja para mover/redimensionar e clique em “Aplicar alterações”.' : 'Arraste a caixa laranja para mover, ou as alças para redimensionar. Depois clique em “Aplicar alterações”.');
  }
  function mostrarArea() {
    sel = { fig: caixa.fig, i: null };
    painel('area'); orig.value = ''; trad.value = '';
    aviso('Ajuste a caixa se precisar. “Ler e traduzir a área” usa a leitura da imagem (ou o texto original digitado); “Criar com a tradução digitada” usa o que você escreveu.');
  }
  function retangulo() {
    var d = tamanhoImagem(caixa.fig), a = caixa.a;
    return { x: a[0] * d[0], y: a[1] * d[1], w: (a[2] - a[0]) * d[0], h: (a[3] - a[1]) * d[1] };
  }

  /* pré-visualização ao vivo das cores e do tamanho da letra */
  fundo.addEventListener('input', function () { if (sel && sel.el) sel.el.style.background = fundo.value; });
  cor.addEventListener('input', function () { if (sel && sel.el) sel.el.style.color = cor.value; });
  fonte.addEventListener('input', function () {
    if (!sel || !sel.el) return;
    if (Number(fonte.value) > 0) sel.el.dataset.f = fonte.value; else delete sel.el.dataset.f;
    if (window.ajustarTudo) window.ajustarTudo();
  });
  trad.addEventListener('input', function () { if (sel && sel.el) { sel.el.textContent = trad.value; if (window.ajustarTudo) window.ajustarTudo(); } });

  B.retrad.addEventListener('click', function () {
    if (!sel || sel.i == null || ocupado) return; var s = sel;
    post('retraduzir', { imagem: s.fig.dataset.arq, indice: s.i, original: orig.value }).then(function (j) { desenhar(s.fig, j); var el = s.fig.querySelector('.tr[data-i="' + s.i + '"]'); if (el) selecionarBloco(el); aviso('Pronto.'); }, function () {});
  });
  B.aplicar.addEventListener('click', function () {
    if (!sel || sel.i == null || !caixa || ocupado) return; var s = sel, r = retangulo();
    var c = { imagem: s.fig.dataset.arq, indice: s.i, x: r.x, y: r.y, w: r.w, h: r.h, fundo: fundo.value, cor: cor.value, fonte: Number(fonte.value) || 0, traduzido: trad.value };
    post('geometria', c).then(function (j) { desenhar(s.fig, j); var el = s.fig.querySelector('.tr[data-i="' + s.i + '"]'); if (el) selecionarBloco(el); aviso('Alterações aplicadas.'); }, function () {});
  });
  B.remover.addEventListener('click', function () {
    if (!sel || sel.i == null || ocupado) return; var s = sel;
    post('remover', { imagem: s.fig.dataset.arq, indice: s.i }).then(function (j) { desenhar(s.fig, j); limpar(); aviso('Trecho removido.'); }, function () {});
  });
  B.area.addEventListener('click', function () {
    if (!sel || !caixa || sel.i != null || ocupado) return; var s = sel, r = retangulo();
    var c = { imagem: s.fig.dataset.arq, x: r.x, y: r.y, w: r.w, h: r.h };
    if (orig.value.trim()) c.texto = orig.value;
    post('area', c).then(function (j) { desenhar(s.fig, j); limpar(); aviso('Área traduzida. Clique no texto novo para ajustar, se precisar.'); }, function () {});
  });
  B.criar.addEventListener('click', function () {
    if (!sel || !caixa || sel.i != null || ocupado) return;
    if (!trad.value.trim()) { aviso('Digite a tradução no campo “Tradução”.', true); return; }
    var s = sel, r = retangulo();
    post('area', { imagem: s.fig.dataset.arq, x: r.x, y: r.y, w: r.w, h: r.h, texto: orig.value, traduzido: trad.value })
      .then(function (j) { desenhar(s.fig, j); limpar(); aviso('Trecho criado.'); }, function () {});
  });
  $('ed-alerta').addEventListener('click', function () {
    var todos = [].slice.call(document.querySelectorAll('.tr[data-a]'));
    if (!todos.length) { aviso('Nenhum trecho com alerta.'); return; }
    var atual = sel && sel.el ? todos.indexOf(sel.el) : -1, prox = todos[(atual + 1) % todos.length];
    prox.scrollIntoView({ block: 'center' }); selecionarBloco(prox);
  });
  B.img.addEventListener('click', function () {
    if (ocupado) return;
    var fig = (sel && sel.fig) || (function () {         // sem seleção: a imagem que está no meio da tela
      var meio = window.innerHeight / 2, achada = null;
      document.querySelectorAll('figure').forEach(function (f) { var r = f.getBoundingClientRect(); if (r.top <= meio && r.bottom >= meio) achada = f; });
      return achada; })();
    if (!fig) { aviso('Role até a imagem desejada.', true); return; }
    if (!confirm('Refazer a leitura e a tradução da imagem ' + fig.dataset.n + '? As edições feitas nela serão perdidas.')) return;
    post('imagem', { imagem: fig.dataset.arq }).then(function (j) { desenhar(fig, j); limpar(); aviso('Imagem ' + fig.dataset.n + ' refeita.'); }, function () {});
  });
  B.tudo.addEventListener('click', function () {
    if (ocupado) return;
    if (!confirm('Refazer a tradução do capítulo INTEIRO? Todas as edições feitas à mão serão perdidas e pode levar vários minutos.')) return;
    ocupar(true); aviso('Iniciando…');
    fetch('/api/bloco/capitulo?t=' + encodeURIComponent(T), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base: base }) })
      .then(function (r) { return r.json().then(function (j) { if (!r.ok) throw new Error(j.erro || ('Erro ' + r.status)); return j; }); })
      .then(function () {
        var t = setInterval(function () {
          fetch('/api/traducao/estado?t=' + encodeURIComponent(T) + '&log=999999', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (e) {
            if (e.estado === 'executando') aviso('Traduzindo… ' + e.feitas + '/' + (e.total || '?'));
            else if (e.estado === 'concluido') { clearInterval(t); aviso('Pronto. Recarregando…'); location.reload(); }
            else if (e.estado === 'erro') { clearInterval(t); ocupar(false); aviso(e.erro || 'Erro na tradução.', true); }
          }, function () {});
        }, 1500);
      }, function (e) { ocupar(false); aviso(e.message, true); });
  });

  /* ---------- interação com a página ---------- */
  $('paginas').addEventListener('pointerdown', function (e) {
    if (!document.body.classList.contains('edicao') || e.button !== 0 || ocupado) return;
    var al = e.target.closest('.al'), cx = e.target.closest('.caixa');
    if (caixa && al) { iniciarArrasto(e, al.dataset.p); return; }
    if (caixa && cx) { iniciarArrasto(e, 'move'); return; }
    var fig = e.target.closest('figure'); if (!fig) return;
    var tr = e.target.closest('.tr');
    if (tr) { selecionarBloco(tr); e.preventDefault(); return; }
    limpar();
    var p = pontoNaFigura(fig, e);
    criarCaixa(fig, [p[0], p[1], p[0], p[1]], 'area', null);
    iniciarArrasto(e, 'novo');
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && document.body.classList.contains('edicao')) { limpar(); dica(); }
  });
})();
