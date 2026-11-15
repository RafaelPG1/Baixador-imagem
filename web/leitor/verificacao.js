/* Leitura da BIBLIOTECA (administrador): confere o resultado da tradução.
   Só o servidor do notebook entrega este arquivo, e o leitor só o carrega quando /api/leitura vem com admin: true.
   O leitor do usuário (celular, app, exportação) nunca recebe este código nem estes dados. */
(function () {
  'use strict';
  var L = window.LEITOR; if (!L || !L.dados || !L.dados.admin) return;
  var d = L.dados, NS = 'http://www.w3.org/2000/svg';
  function el(tag, props) { var n = document.createElement(tag); Object.keys(props || {}).forEach(function (k) { n[k] = props[k]; }); return n; }
  function sv(tag, attrs) { var n = document.createElementNS(NS, tag); Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); }); return n; }
  var ROTULO = { ok: 'ok', revisar: 'revisar', erro: 'erro' };
  var MODOS = { balao: 'escrita no balão', narracao: 'escrita na narração', texto: 'texto solto reescrito', tooltip: 'não reescrita (só conferência)', nenhum: 'copiada (sem letras)' };
  var MOTIVOS = { erro: 'sem tradução', 'fora-de-balao': 'fora de balão', emenda: 'balão cortado sem par', 'sem-balao': 'balão não achado', 'sem-tinta': 'sem texto para apagar' };

  /* ---------- camada sobre cada imagem: balões e regiões lidas pelo OCR ---------- */
  var formas = {};                                                    // id da fala → forma na imagem (para destacar)
  var dica = el('div', { id: 'v-dica', hidden: true }); document.body.appendChild(dica);
  function escreverDica(f) {
    dica.textContent = '';
    var t1 = el('div', { className: 'v-d-orig' }); t1.append(el('b', { textContent: 'Original: ' }), document.createTextNode(f.original || '—'));
    var t2 = el('div', { className: 'v-d-trad' }); t2.append(el('b', { textContent: 'Tradução: ' }), document.createTextNode(f.texto || (f.erro ? '(sem tradução)' : '—')));
    var t3 = el('div', { className: 'v-d-info', textContent: info(f) });
    dica.append(t1, t2, t3);
  }
  function info(f) {
    var p = [f.id, 'estado: ' + (ROTULO[f.estado] || f.estado), 'tradução: ' + f.status];
    if (f.ocr) p.push('OCR: ' + (f.ocr.motor || '?') + ' ' + f.ocr.confianca + '% (' + f.ocr.status + ')');
    p.push(MODOS[f.modo] || f.modo);
    if (f.motivo) p.push(MOTIVOS[f.motivo] || f.motivo);
    if (f.erro) p.push('erro: ' + f.erro);
    return p.join(' · ');
  }
  function posicionar(forma) {
    var r = forma.getBoundingClientRect(), t = dica.getBoundingClientRect(), m = 8;
    var topo = r.bottom + m; if (topo + t.height > innerHeight - m) topo = Math.max(m, r.top - t.height - m);
    dica.style.top = topo + 'px';
    dica.style.left = Math.min(Math.max(m, r.left + r.width / 2 - t.width / 2), innerWidth - t.width - m) + 'px';
  }
  function camada(fig, im) {
    if (!im.medidas) return;
    var svg = sv('svg', { viewBox: '0 0 ' + im.medidas[0] + ' ' + im.medidas[1], 'class': 'v-camada', 'aria-hidden': 'true' });
    (im.baloes || []).forEach(function (b) {
      svg.appendChild(sv('polygon', { 'class': 'v-balao v-' + b.tipo, points: b.poligono.map(function (q) { return q.join(','); }).join(' ') }));
    });
    (im.conferencia || []).forEach(function (f) {
      if (!f.regiao) return;
      var r = sv('rect', { 'class': 'v-regiao v-e-' + f.estado, x: f.regiao[0], y: f.regiao[1], width: f.regiao[2], height: f.regiao[3], tabindex: 0 });
      r.dataset.id = f.id; formas[f.id] = r;
      function mostrar() { escreverDica(f); dica.hidden = false; posicionar(r); }
      r.addEventListener('pointerenter', mostrar); r.addEventListener('focus', mostrar);
      r.addEventListener('pointerleave', function () { dica.hidden = true; }); r.addEventListener('blur', function () { dica.hidden = true; });
      r.addEventListener('click', function () { escolher(f.id, false); });
      svg.appendChild(r);
    });
    fig.appendChild(svg);
  }
  d.imagens.forEach(function (im, k) { camada(L.figuras[k], im); });

  /* ---------- painel: resumo do processamento e lista das falas ---------- */
  var botao = el('button', { id: 'v-botao', type: 'button', textContent: 'Verificação', title: 'Conferir a tradução (só nesta leitura da biblioteca)' });
  var painel = el('aside', { id: 'v-painel', hidden: true });
  var cab = el('header'); var fechar = el('button', { type: 'button', textContent: '✕', title: 'Fechar' });
  cab.append(el('strong', { textContent: 'Verificação da tradução' }), fechar);
  var v = d.verificacao || {}, c = v.contagens || {};
  var resumo = el('p', { className: 'v-resumo' });
  resumo.textContent = d.traduzido
    ? (v.provedor || v.motor || 'motor desconhecido') + ' · gerado em ' + (v.gerado || '?').replace('T', ' ').slice(0, 16) + ' · ' +
      Object.keys(c).map(function (k) { return c[k] + ' ' + k; }).join(' · ')
    : 'Este capítulo ainda não foi traduzido: só as imagens aparecem.';
  var avisos = el('ul', { className: 'v-avisos' }); (v.avisos || []).forEach(function (a) { avisos.appendChild(el('li', { textContent: a })); });
  function opcao(id, rotulo, classe, ligado) {
    var l = el('label'), i = el('input', { type: 'checkbox', id: id, checked: ligado });
    i.addEventListener('change', function () { document.body.classList.toggle(classe, !i.checked); });
    l.append(i, document.createTextNode(' ' + rotulo)); if (!ligado) document.body.classList.add(classe); return l;
  }
  var marcadas = el('input', { type: 'checkbox', id: 'v-so-marcadas' });
  var opcoes = el('div', { className: 'v-opcoes' });
  opcoes.append(
    opcao('v-baloes', 'Balões detectados', 'v-sem-baloes', true),
    opcao('v-regioes', 'Regiões lidas pelo OCR', 'v-sem-regioes', true),
    (function () { var l = el('label'); l.append(marcadas, document.createTextNode(' Só falas a revisar ou com erro')); return l; })()
  );
  var lista = el('ol', { className: 'v-lista' });
  var itens = {};
  d.imagens.forEach(function (im) {
    (im.conferencia || []).forEach(function (f) {
      var li = el('li', { className: 'v-' + f.estado }); li.dataset.id = f.id; li.dataset.n = im.n; itens[f.id] = li;
      var linha = el('div', { className: 'v-l-cab' });
      linha.append(el('b', { textContent: 'p.' + im.n + ' · ' + f.id }), el('span', { className: 'v-selo v-e-' + f.estado, textContent: ROTULO[f.estado] || f.estado }));
      var o = el('div', { className: 'v-l-orig', textContent: f.original || '—' });
      var t = el('div', { className: 'v-l-trad', textContent: f.texto || (f.erro ? '(sem tradução)' : '—') });
      li.append(linha, o, t, el('small', { textContent: info(f).split(' · ').slice(1).join(' · ') }));
      li.addEventListener('click', function () { escolher(f.id, true); });
      lista.appendChild(li);
    });
  });
  if (!lista.children.length) lista.appendChild(el('li', { className: 'v-vazio', textContent: 'Nenhuma fala detectada.' }));
  marcadas.addEventListener('change', function () { painel.classList.toggle('v-filtrada', marcadas.checked); });
  painel.append(cab, resumo, avisos, opcoes, lista);
  document.body.append(botao, painel);

  function abrir(sim) { painel.hidden = !sim; botao.setAttribute('aria-expanded', String(sim)); document.body.classList.toggle('v-aberto', sim); }
  botao.addEventListener('click', function () { abrir(painel.hidden); });
  fechar.addEventListener('click', function () { abrir(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !painel.hidden) abrir(false); });

  var escolhida = null;
  function escolher(id, rolar) {
    if (escolhida && formas[escolhida]) formas[escolhida].classList.remove('v-sel');
    if (escolhida && itens[escolhida]) itens[escolhida].classList.remove('v-sel');
    escolhida = id;
    if (formas[id]) { formas[id].classList.add('v-sel'); if (rolar) formas[id].scrollIntoView({ block: 'center', behavior: 'smooth' }); }
    if (itens[id]) { itens[id].classList.add('v-sel'); if (!rolar) { abrir(true); itens[id].scrollIntoView({ block: 'nearest' }); } }
  }
  addEventListener('scroll', function () { dica.hidden = true; }, { passive: true });
})();
