/* Leitor global: a mesma página para qualquer obra e capítulo (notebook e celular).
   O capítulo vem do endereço (?c=Obra/Capítulo[&r=id]); os dados, de /api/leitura. Nada é gerado por capítulo. */
(function () {
  'use strict';
  var params = new URLSearchParams(location.search);
  var relPedido = params.get('c') || '', raizId = params.get('r') || '';
  var metaToken = document.querySelector('meta[name=baixador-token]');
  var tok = metaToken ? metaToken.content : '';                       // só o notebook tem token; o celular usa o cookie da chave
  var qt = tok ? 't=' + encodeURIComponent(tok) : '';
  function api(caminho, extra) {
    var p = []; if (extra) p.push(extra); if (qt) p.push(qt);
    return caminho + (p.length ? '?' + p.join('&') : '');
  }
  function $(id) { return document.getElementById(id); }
  var principal = $('paginas');
  var figuras = [];

  /* ---------- tradução sobre a página: o PNG de limpeza (texto original apagado) + o texto traduzido em SVG ----------
     Tudo em pixels da imagem original (viewBox): o encaixe do texto não depende do tamanho da tela. */
  var NS = 'http://www.w3.org/2000/svg';
  var FONTE = '"Comic Neue", "Comic Sans MS", system-ui, sans-serif';
  var canvas = document.createElement('canvas').getContext('2d');
  var larguras = {};
  var textos = [];                                                    // { g, fala, medidas }: refeitos quando a fonte embutida termina de carregar
  function medir(texto, tamanho) {                                    // mede em 100 px e escala (a largura é linear no tamanho)
    var w = larguras[texto];
    if (w === undefined) { canvas.font = '700 100px ' + FONTE; w = canvas.measureText(texto).width; larguras[texto] = w; }
    return w * tamanho / 100;
  }
  function elSvg(tag, attrs) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function escrever(g, fala, medidas) {
    g.textContent = '';
    var texto = fala.maiuscula ? fala.texto.toLocaleUpperCase('pt-BR') : fala.texto;
    // o texto pode vazar do balão: se não coubesse sem encolher demais, a caixa cresce antes de a letra diminuir
    var f = window.LeitorLayout.fitFlexible(medir, texto, fala.caixa, { fontMax: fala.fonteMax, limites: medidas });
    var c = f.caixa;
    var t = elSvg('text', { 'class': 'tr', fill: fala.tinta, 'font-size': f.size, 'text-anchor': 'middle', 'dominant-baseline': 'central' });
    var halo = fala.contorno || fala.fundo;                           // contorno (letra sobre a arte) ou halo na cor do balão, que mantém legível o que passa do balão
    if (halo) {
      t.setAttribute('stroke', halo); t.setAttribute('stroke-width', f.size * (fala.contorno ? 0.2 : 0.16));
      t.setAttribute('stroke-linejoin', 'round'); t.setAttribute('paint-order', 'stroke');
    }
    var lh = f.size * f.lineHeight, topo = c[1] + c[3] / 2 - lh * (f.lines.length - 1) / 2;
    f.lines.forEach(function (linha, i) { var s = elSvg('tspan', { x: c[0] + c[2] / 2, y: topo + i * lh }); s.textContent = linha; t.appendChild(s); });
    g.appendChild(t);
  }
  function ajustarTudo() { larguras = {}; textos.forEach(function (x) { escrever(x.g, x.fala, x.medidas); }); }
  window.ajustarTudo = ajustarTudo;

  /* ---------- montagem da página a partir dos dados do capítulo ---------- */
  function montar(d) {
    principal.textContent = '';
    textos = [];
    var prefixoLimpeza = d.subLimpeza || 'traducao/limpeza/';
    d.imagens.forEach(function (im) {
      var fig = document.createElement('figure'), falas = im.falas || [];
      fig.dataset.n = im.n; fig.dataset.arq = im.arq;
      if (im.medidas) {
        fig.className = 'com-medidas'; fig.style.aspectRatio = im.medidas[0] + '/' + im.medidas[1];
        fig.dataset.w = im.medidas[0]; fig.dataset.h = im.medidas[1];
      }
      var img = document.createElement('img');
      img.src = d.base + (d.sub || '') + encodeURIComponent(im.arq); img.alt = 'Imagem ' + im.n + ': ' + im.arq; img.loading = 'lazy'; img.decoding = 'async';
      fig.appendChild(img);
      if (im.medidas && im.patch) {                                   // texto original apagado, por cima da imagem
        var limpa = document.createElement('img'); limpa.className = 'patch'; limpa.alt = ''; limpa.decoding = 'async';
        limpa.src = d.base + prefixoLimpeza + encodeURIComponent(im.patch);
        fig.appendChild(limpa);
      }
      if (im.medidas && falas.length) {
        var svg = elSvg('svg', { viewBox: '0 0 ' + im.medidas[0] + ' ' + im.medidas[1], 'class': 'tr-svg', 'aria-hidden': 'true' });
        falas.forEach(function (fala) { var g = elSvg('g', {}); svg.appendChild(g); textos.push({ g: g, fala: fala, medidas: im.medidas }); });
        fig.appendChild(svg);
      }
      principal.appendChild(fig);
    });
    figuras = [].slice.call(principal.querySelectorAll('figure'));
    var fim = document.createElement('p'); fim.className = 'fim';
    fim.textContent = 'Fim de “' + d.titulo + '” — ' + d.imagens.length + ' imagem(ns).';
    $('fim').appendChild(fim);
    document.title = d.titulo;
    window.BAIXADOR_BASE = d.base;
    ajustarTudo();
    if (document.fonts && document.fonts.load) document.fonts.load('700 20px "Comic Neue"').then(ajustarTudo, function () {});
  }

  /* ---------- progresso lateral: um quadradinho por página; clicar leva à página; mostra o número ---------- */
  var barra = $('progresso'), bolha = $('pq-num'), quadrados = [], paginaAtual = 0, ocultarBolha = null;
  function mostrarNumero(btn, ms) {
    var r = btn.getBoundingClientRect();
    bolha.textContent = btn.dataset.n + ' / ' + figuras.length;
    bolha.style.top = (r.top + r.height / 2) + 'px'; bolha.style.left = (r.right + 6) + 'px'; bolha.hidden = false;
    clearTimeout(ocultarBolha);
    if (ms) ocultarBolha = setTimeout(esconderNumero, ms);
  }
  function esconderNumero() { clearTimeout(ocultarBolha); bolha.hidden = true; }
  function montarProgresso() {
    barra.textContent = ''; quadrados = []; paginaAtual = 0;
    figuras.forEach(function (fig, k) {
      var b = document.createElement('button'); b.type = 'button'; b.dataset.n = k + 1; b.tabIndex = -1;
      b.setAttribute('aria-label', 'Ir para a página ' + (k + 1) + ' de ' + figuras.length);
      b.addEventListener('focus', function () { mostrarNumero(b); });
      b.addEventListener('blur', esconderNumero);
      barra.appendChild(b); quadrados.push(b);
    });
    atualizarProgresso();
  }
  // Toque, clique ou arrasto na barra: a página vem da altura do dedo (a barra ocupa a tela toda, então cada página é uma faixa fina).
  function paginaDaAltura(y) {
    var r = barra.getBoundingClientRect(), n = quadrados.length;
    return Math.max(0, Math.min(n - 1, Math.floor((y - r.top) / r.height * n)));
  }
  function irPara(k, ms) {
    figuras[k].scrollIntoView({ block: 'start' });
    mostrarNumero(quadrados[k]);
  }
  var arrastando = false;
  function selecionar() { barra.classList.add('aberta'); }
  function desselecionar() { barra.classList.remove('aberta'); esconderNumero(); }
  barra.addEventListener('pointerdown', function (e) {
    if (!quadrados.length) return;
    arrastando = true; selecionar();
    try { barra.setPointerCapture(e.pointerId); } catch (_) {}
    irPara(paginaDaAltura(e.clientY));
    e.preventDefault();
  });
  barra.addEventListener('pointermove', function (e) {
    if (arrastando) irPara(paginaDaAltura(e.clientY));
    else if (e.pointerType === 'mouse' && quadrados.length && !barra.classList.contains('aberta')) mostrarNumero(quadrados[paginaDaAltura(e.clientY)]);
  });
  function soltar() { arrastando = false; if (barra.classList.contains('aberta')) mostrarNumero(quadrados[paginaAtual - 1] || quadrados[0]); }
  barra.addEventListener('pointerup', soltar);
  barra.addEventListener('pointercancel', soltar);
  barra.addEventListener('pointerleave', function (e) { if (!arrastando && e.pointerType === 'mouse' && !barra.classList.contains('aberta')) esconderNumero(); });
  // selecionada fica assim até tocar em outro lugar
  document.addEventListener('pointerdown', function (e) { if (barra.classList.contains('aberta') && !barra.contains(e.target)) desselecionar(); }, true);
  // Chegar ao fim do capítulo (rolando de verdade, não só abrir uma página curta) marca como lido.
  // Notebook: no servidor (a porta muda a cada abertura, o LocalStorage seria perdido). Celular: LocalStorage (porta fixa).
  var marcado = false;
  function marcarLido() {
    if (marcado || !relCanonico) return; marcado = true;
    if (tok) fetch(api('/api/lidos'), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ rel: relCanonico, lido: true }) }).catch(function () { marcado = false; });
    else { try { localStorage.setItem('lido:' + relCanonico, '1'); } catch (_) {} }
  }
  function atualizarProgresso() {
    var total = figuras.length; if (!total) return;
    var p = 1;
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 2) p = total;   // chegou ao fim
    else { var meio = window.innerHeight * 0.4; for (var j = 0; j < total; j++) { if (figuras[j].getBoundingClientRect().top <= meio) p = j + 1; else break; } }
    if (p === total && window.scrollY > 0) marcarLido();
    if (p === paginaAtual) return;
    paginaAtual = p;
    if (barra.classList.contains('aberta') && !arrastando) mostrarNumero(quadrados[p - 1]);
    for (var m = 0; m < total; m++) quadrados[m].className = m < p - 1 ? 'lido' : (m === p - 1 ? 'atual' : '');
  }
  var agendado = false;
  function agendar() { if (agendado) return; agendado = true; requestAnimationFrame(function () { agendado = false; atualizarProgresso(); }); }
  window.addEventListener('scroll', agendar, { passive: true });
  window.addEventListener('resize', agendar);
  window.addEventListener('load', agendar);
  if ('ResizeObserver' in window) new ResizeObserver(agendar).observe(principal);

  /* ---------- botões flutuantes: aparecem/somem com dois cliques (ou dois toques) na leitura ---------- */
  var flut = $('flutuantes'), painel = $('painel-lista'), botaoLista = $('lista'), casa = $('casa'), livro = $('livro');
  casa.href = tok ? '/?' + qt + '#biblioteca' : '/';
  var ultimoToque = 0;
  function fecharLista() { painel.hidden = true; botaoLista.setAttribute('aria-expanded', 'false'); }
  function mostrarOuEsconder() {
    var agora = Date.now(); if (agora - ultimoToque < 450) return; ultimoToque = agora;   // dblclick + double-tap não contam duas vezes
    flut.hidden = !flut.hidden;
    if (flut.hidden) fecharLista();
  }
  /* Dois cliques/toques só valem com a página PARADA: nada de rolagem recente, nenhum deslocamento da página entre os dois
     toques e nenhum arrasto de dedo. Um toque que só para a rolagem (ou termina uma) é descartado e zera a sequência. */
  var PARADA_MS = 220, ultimaRolagem = 0, rolando = false, fimDaRolagem = null;
  function parada() { return !rolando && Date.now() - ultimaRolagem > PARADA_MS; }
  window.addEventListener('scroll', function () {
    ultimaRolagem = Date.now(); rolando = true;
    clearTimeout(fimDaRolagem); fimDaRolagem = setTimeout(function () { rolando = false; }, PARADA_MS);
  }, { passive: true });
  var cliques = [], bloqueioMouseAte = 0;
  principal.addEventListener('click', function (e) {
    if (e.detail === 1) cliques = [];                                 // primeiro clique da sequência
    cliques.push({ y: window.scrollY, ok: parada() });
    if (cliques.length > 2) cliques.shift();
  });
  principal.addEventListener('dblclick', function () {
    if (Date.now() < bloqueioMouseAte) return;                        // dblclick sintetizado depois de um toque descartado
    var par = cliques.slice(-2), mesmaPagina = par.length === 2 && par.every(function (c) { return c.ok && Math.abs(c.y - par[0].y) < 2; });
    cliques = [];
    if (mesmaPagina && parada()) mostrarOuEsconder();
  });
  var toque = null, atual = null;
  principal.addEventListener('touchstart', function (e) {
    var t = e.touches[0];
    atual = e.touches.length === 1 ? { x: t.clientX, y: t.clientY, quando: Date.now(), sy: window.scrollY, moveu: false, rolava: !parada() } : null;
    if (!atual || atual.rolava) { toque = null; bloqueioMouseAte = Date.now() + 700; }   // este toque só parou a rolagem
  }, { passive: true });
  principal.addEventListener('touchmove', function (e) {
    if (!atual) return; var t = e.touches[0];
    if (Math.abs(t.clientX - atual.x) > 10 || Math.abs(t.clientY - atual.y) > 10) { atual.moveu = true; toque = null; }
  }, { passive: true });
  principal.addEventListener('touchcancel', function () { atual = null; toque = null; }, { passive: true });
  principal.addEventListener('touchend', function (e) {
    var t = e.changedTouches[0], agora = Date.now(), a = atual; atual = null;
    if (!a || a.rolava || a.moveu || agora - a.quando > 350 || Math.abs(window.scrollY - a.sy) > 1 || !parada()) { toque = null; bloqueioMouseAte = agora + 700; return; }
    if (toque && agora - toque.quando < 320 && Math.abs(t.clientX - toque.x) < 30 && Math.abs(t.clientY - toque.y) < 30 && Math.abs(window.scrollY - toque.sy) < 2) { toque = null; mostrarOuEsconder(); }
    else toque = { quando: agora, x: t.clientX, y: t.clientY, sy: window.scrollY };
  }, { passive: true });
  botaoLista.addEventListener('click', function () {
    var abrir = painel.hidden; painel.hidden = !abrir; botaoLista.setAttribute('aria-expanded', abrir ? 'true' : 'false');
    if (abrir) { var atual = painel.querySelector('[aria-current=true]'); if (atual) atual.scrollIntoView({ block: 'center' }); }
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') fecharLista(); });
  document.addEventListener('click', function (e) { if (!painel.hidden && !painel.contains(e.target) && !botaoLista.contains(e.target)) fecharLista(); });
  /* ---------- original / tradução: só esconde os textos sobrepostos; a posição de leitura não muda ---------- */
  var idioma = $('idioma'), CHAVE_IDIOMA = 'baixador.original';
  function lerPreferencia() { try { return localStorage.getItem(CHAVE_IDIOMA) === '1'; } catch (_) { return false; } }
  function aplicarIdioma(original) {
    document.body.classList.toggle('original', original);
    idioma.setAttribute('aria-pressed', String(original));
    var rotulo = original ? 'Ver a tradução' : 'Ver o idioma original';
    idioma.title = rotulo; idioma.setAttribute('aria-label', rotulo);
  }
  function atualizarIdioma() {
    var tem = !!principal.querySelector('.tr-svg, .patch');
    if (tem) idioma.removeAttribute('aria-disabled'); else idioma.setAttribute('aria-disabled', 'true');
    aplicarIdioma(tem && lerPreferencia());
    if (!tem) { idioma.title = 'Este capítulo não tem tradução'; idioma.setAttribute('aria-label', idioma.title); }
  }
  idioma.addEventListener('click', function () {
    if (idioma.getAttribute('aria-disabled') === 'true') return;
    var original = !document.body.classList.contains('original'), y = window.scrollY;
    aplicarIdioma(original); window.scrollTo(0, y);
    try { localStorage.setItem(CHAVE_IDIOMA, original ? '1' : '0'); } catch (_) {}
  });
  if (document.fonts) { if (document.fonts.ready) document.fonts.ready.then(ajustarTudo); if (document.fonts.addEventListener) document.fonts.addEventListener('loadingdone', ajustarTudo); }   // a fonte embutida chega depois do 1º cálculo
  var nomeObra = '';                                                 // preenchido quando a biblioteca responde
  function urlObra(nome) { return (tok ? '/?' + qt + '&obra=' : '/?obra=') + encodeURIComponent(nome) + (tok ? '#biblioteca' : ''); }
  livro.addEventListener('click', function () { if (nomeObra) location.href = urlObra(nomeObra); });
  $('fechar-lista').addEventListener('click', fecharLista);

  /* ---------- posição real do capítulo na obra, lista de capítulos e navegação ---------- */
  var relCanonico = relPedido;
  function href(c) { return '/leitor?c=' + encodeURIComponent(c.rel) + (qt ? '&' + qt : ''); }
  function ligar(a, c) { if (c) { a.href = href(c); a.removeAttribute('aria-disabled'); } else { a.removeAttribute('href'); a.setAttribute('aria-disabled', 'true'); } }
  function numero(c) { var n = parseFloat(c.numero); return isFinite(n) && String(c.numero).trim() !== '' ? n : null; }
  function posicao(obra, i) {
    // Número real do capítulo / último número existente na obra (ex.: 172/175). Sem números, a posição na lista.
    var atual = obra.capitulos[i], ultimo = null;
    obra.capitulos.forEach(function (c) { var n = numero(c); if (n !== null && (ultimo === null || n > numero(ultimo))) ultimo = c; });
    if (numero(atual) !== null && ultimo) return { atual: String(atual.numero), total: String(ultimo.numero) };
    return { atual: String(i + 1), total: String(obra.capitulos.length) };
  }
  function desenharObra(obra, i) {
    var pos = posicao(obra, i), el = $('cap-pos'); el.textContent = '';
    var b = document.createElement('b'); b.textContent = pos.atual; var de = document.createElement('i'); de.textContent = '/' + pos.total;
    el.append(b, de); el.title = 'Capítulo ' + pos.atual + ' de ' + pos.total;
    ligar($('anterior'), obra.capitulos[i - 1]); ligar($('proximo'), obra.capitulos[i + 1]);
    var ul = $('lista-caps'); ul.textContent = '';
    for (var k = obra.capitulos.length - 1; k >= 0; k--) {            // do mais novo para o mais antigo
      var c = obra.capitulos[k], li = document.createElement('li'), a = document.createElement('a');
      var n = document.createElement('b'); n.textContent = numero(c) !== null ? 'Cap. ' + c.numero : (c.rotulo || c.rel); a.appendChild(n);
      if (numero(c) !== null && c.titulo) { var t = document.createElement('span'); t.textContent = c.titulo; a.appendChild(t); }
      if (k === i) { a.setAttribute('aria-current', 'true'); a.addEventListener('click', function (ev) { ev.preventDefault(); fecharLista(); }); a.href = '#'; }
      else a.href = href(c);
      li.appendChild(a); ul.appendChild(li);
    }
    var nav = $('navcap'); nav.textContent = '';
    var voltar = document.createElement('a'); voltar.textContent = '‹ Obra'; voltar.title = 'Voltar para a página da obra'; voltar.href = urlObra(obra.nome);
    var prox = obra.capitulos[i + 1], seguinte = document.createElement('a');
    if (prox) { seguinte.textContent = 'Próximo ›'; seguinte.className = 'principal'; seguinte.href = href(prox); seguinte.title = prox.rotulo || ''; }
    else { seguinte.textContent = 'Último capítulo'; seguinte.setAttribute('aria-disabled', 'true'); }
    nav.append(voltar, seguinte);
    nav.hidden = false;
  }
  function carregarObra() {
    if (raizId) return;                                               // pasta de fora da biblioteca: sem obra, sem navegação
    fetch(api('/api/biblioteca'), { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
      var obra = null, i = -1;
      (d.obras || []).forEach(function (o) { o.capitulos.forEach(function (c, k) { if (c.rel === relCanonico) { obra = o; i = k; } }); });
      if (obra) { nomeObra = obra.nome; livro.removeAttribute('aria-disabled'); desenharObra(obra, i); }
    }).catch(function () {});
  }

  /* ---------- leitura da biblioteca (verificação): código e dados à parte, carregados só quando o servidor marca admin ---------- */
  function carregarVerificacao(d) {
    window.LEITOR = { dados: d, figuras: figuras, api: api, principal: principal };
    var l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/estatico/verificacao.css'; document.head.appendChild(l);
    var sc = document.createElement('script'); sc.src = '/estatico/verificacao.js'; document.body.appendChild(sc);
  }

  /* ---------- início ---------- */
  var acesso = fetch(api('/api/leitura', 'c=' + encodeURIComponent(relPedido) + (raizId ? '&r=' + encodeURIComponent(raizId) : '')), { cache: 'no-store' });
  acesso.then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); }).then(function (d) {
    relCanonico = d.rel;
    montar(d); montarProgresso(); atualizarIdioma(); carregarObra();
    if (d.admin) carregarVerificacao(d);                             // leitura da BIBLIOTECA: só o notebook manda d.admin e entrega estes arquivos
    document.addEventListener('visibilitychange', function () { if (!document.hidden) carregarObra(); });
    setInterval(function () { if (!document.hidden) carregarObra(); }, 20000);   // capítulos novos: o "172/175" acompanha
  }).catch(function (erro) {
    var p = $('carregando');
    p.textContent = erro === 401 || erro === 403 ? 'Sem acesso. Abra o leitor pelo programa.' : 'Capítulo não encontrado.';
  });
})();
