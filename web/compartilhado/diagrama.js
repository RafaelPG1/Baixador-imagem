/* Telas da obra (compartilhadas pelo notebook e pelo celular): cartão com capa e nome, e a página da obra com a lista de capítulos. */
(function () {

  function agrupar(faltando) {            // [138,139,140,143] → ["138–140", "143"]
    const r = []; let ini = null, fim = null;
    (faltando || []).slice().sort((x, y) => x - y).forEach((n) => {
      if (ini !== null && n === fim + 1) fim = n;
      else { if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim); ini = fim = n; }
    });
    if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim);
    return r;
  }
  function numero(c) { const n = parseFloat(c.numero); return Number.isFinite(n) && String(c.numero).trim() !== '' ? n : null; }

  const SETA = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"></polyline></svg>';

  // Página da obra: voltar, capa com nome e ações, e só a listagem de capítulos (do mais novo ao mais antigo).
  // opc: {urlCapa(obra), acoes: [nós], aoVoltar(), atual: rel destacado, aoEscolher(c, obra)}
  function paginaObra(obra, opc) {
    opc = opc || {};
    const raiz = document.createElement('section');
    raiz.className = 'obra-pagina';
    if (opc.aoVoltar) {
      const v = document.createElement('button'); v.type = 'button'; v.className = 'obra-volta';
      v.innerHTML = SETA + '<span>Biblioteca</span>'; v.setAttribute('aria-label', 'Voltar para a biblioteca');
      v.addEventListener('click', opc.aoVoltar); raiz.append(v);
    }
    const hero = document.createElement('header'); hero.className = 'obra-hero';
    const capa = document.createElement('div'); capa.className = 'obra-hero-capa';
    if (obra.capa && opc.urlCapa) {
      const f = document.createElement('img'); f.alt = ''; f.decoding = 'async'; f.src = opc.urlCapa(obra);
      f.addEventListener('error', () => { f.remove(); capa.append(inicial(obra)); });
      capa.append(f);
    } else capa.append(inicial(obra));
    const nome = document.createElement('h2'); nome.className = 'obra-hero-nome'; nome.textContent = obra.nome;
    const res = document.createElement('p'); res.className = 'obra-hero-resumo'; res.textContent = resumo(obra);
    const acoes = document.createElement('div'); acoes.className = 'obra-hero-acoes'; acoes.append(...(opc.acoes || []));
    hero.append(capa, nome, res, acoes);

    const itens = obra.capitulos.map((c, i) => ({tipo: 'cap', c, i, n: numero(c)}));
    agrupar(obra.faltando).forEach((g) => itens.push({tipo: 'falta', g, n: parseFloat(g)}));
    itens.sort((x, y) => (y.n !== null && x.n !== null ? y.n - x.n : 0) || ((y.i || 0) - (x.i || 0)));
    const sec = document.createElement('section'); sec.className = 'obra-caps';
    const tit = document.createElement('h3'); tit.className = 'obra-caps-titulo'; tit.textContent = 'Capítulos';
    const ul = document.createElement('ul'); ul.className = 'cap-lista';
    itens.forEach((it) => {
      const li = document.createElement('li');
      if (it.tipo === 'falta') {
        li.className = 'cap-falta'; li.textContent = 'Faltam na biblioteca: ' + it.g;
      } else {
        const c = it.c, temNum = c.numero != null && c.numero !== '';
        const b = document.createElement('button'); b.type = 'button'; b.dataset.rel = c.rel;
        b.className = 'cap-item' + (opc.atual === c.rel ? ' atual' : '');
        const l1 = document.createElement('span'); l1.className = 'cap-l1';
        const num = document.createElement('span'); num.className = 'cap-num'; num.textContent = temNum ? 'Cap. ' + c.numero : c.rotulo;
        l1.append(num);
        if (c.titulo && temNum) { const sep = document.createElement('span'); sep.className = 'cap-sep'; sep.textContent = '·'; const t = document.createElement('span'); t.className = 'cap-titulo'; t.textContent = c.titulo; l1.append(sep, t); }
        b.append(l1);
        if (c.traduzido) { const l2 = document.createElement('span'); l2.className = 'cap-l2'; l2.textContent = 'Traduzido'; b.append(l2); }
        b.addEventListener('click', () => opc.aoEscolher && opc.aoEscolher(c, obra));
        li.append(b);
      }
      ul.append(li);
    });
    sec.append(tit, ul);
    raiz.append(hero, sec);
    return raiz;
  }

  function inicial(obra) {
    const i = document.createElement('span'); i.className = 'capa-inicial'; i.textContent = (obra.nome.trim()[0] || '?').toUpperCase(); return i;
  }

  function resumo(obra) {
    const n = obra.capitulos.length;
    const partes = [n + (n === 1 ? ' capítulo' : ' capítulos')];
    if (obra.traduzidos) partes.push(obra.traduzidos + ' traduzido' + (obra.traduzidos === 1 ? '' : 's'));
    if (obra.faltando && obra.faltando.length) partes.push(obra.faltando.length + ' faltando');
    return partes.join(' · ');
  }

  // Cartão da obra: só a capa (ou a inicial, se ainda não há capa) e o nome. `urlCapa(obra)` monta o endereço da imagem.
  function cartao(obra, urlCapa, aoAbrir) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'capa-card'; b.dataset.cor = String(obra.cor);
    b.setAttribute('aria-label', obra.nome);
    const img = document.createElement('span'); img.className = 'capa-img';
    const semCapa = () => { img.replaceChildren(inicial(obra)); };
    if (obra.capa) {
      const f = document.createElement('img'); f.alt = ''; f.loading = 'lazy'; f.decoding = 'async'; f.src = urlCapa(obra);
      f.addEventListener('error', semCapa); img.append(f);
    } else semCapa();
    const nome = document.createElement('span'); nome.className = 'capa-nome'; nome.textContent = obra.nome;
    b.append(img, nome);
    b.addEventListener('click', () => aoAbrir(obra));
    return b;
  }

  window.Diagrama = {paginaObra, resumo, cartao};
})();
