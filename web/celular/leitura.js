/* Leitura pelo celular: somente leitura. Lista as obras (linhas) e abre o capítulo; sincroniza sozinha. */
let dados = {obras: [], versao: ''}, obraAberta = new URLSearchParams(location.search).get('obra');
const $ = (id) => document.getElementById(id);
const urlCap = (rel) => '/leitor?c=' + encodeURIComponent(rel);
function guardar(chave, valor) { try { localStorage.setItem(chave, valor); } catch (_) {} }
function lido(chave) { try { return localStorage.getItem(chave); } catch (_) { return null; } }
function el(tag, classe, texto) { const e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
let _t = null;
function aviso(t) { const x = $('toast'); x.textContent = t; x.hidden = false; clearTimeout(_t); _t = setTimeout(() => { x.hidden = true; }, 3000); }

const urlCapa = (o) => `/api/capa?p=${encodeURIComponent(o.pasta)}&v=${o.capa_v}`;
function urlDaObra(nome) { return nome ? '/?obra=' + encodeURIComponent(nome) : '/'; }
function abrirObra(nome) { obraAberta = nome; history.pushState(null, '', urlDaObra(nome)); desenhar(); window.scrollTo(0, 0); }
window.addEventListener('popstate', () => { obraAberta = new URLSearchParams(location.search).get('obra'); desenhar(); });
function abrir(o, c) { guardar('ultimo:' + o.nome, c.rel); location.href = urlCap(c.rel); }
function continuar(o) {
  const rel = lido('ultimo:' + o.nome);
  const atual = o.capitulos.find((c) => c.rel === rel);
  if (!atual) return o.capitulos[0];
  const i = o.capitulos.indexOf(atual);
  return o.capitulos[i];
}

const ICO = {ler: '<path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/>', voltar: '<path d="m15 18-6-6 6-6"/>'};
const ic = (n) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${ICO[n]}</svg>`;
const norm = (t) => (t || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const corDe = (o) => String(o.cor == null ? 0 : o.cor);
let filtro = '', maisNovoPrimeiro = lido('ordem') !== 'antigos';
function numCap(c) { const n = parseFloat(c.numero); return Number.isFinite(n) && String(c.numero).trim() !== '' ? n : null; }
function agrupar(faltando) {
  const r = []; let ini = null, fim = null;
  (faltando || []).slice().sort((x, y) => x - y).forEach((n) => {
    if (ini !== null && n === fim + 1) fim = n; else { if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim); ini = fim = n; }
  });
  if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim);
  return r;
}

function cartaoObra(o) {
  const b = Diagrama.cartao(o, urlCapa, (x) => abrirObra(x.nome));
  const n = o.capitulos.length, feitas = o.capitulos.filter((c) => c.traduzido).length;
  const meta = el('span', 'capa-meta');
  const nome = b.querySelector('.capa-nome'); nome.remove();
  const tr = el('span', 'capa-trilho'); const barra = el('i'); barra.style.width = (n ? Math.round(feitas / n * 100) : 0) + '%'; tr.append(barra);
  meta.append(nome, el('span', 'capa-sub', `${n} capítulo${n === 1 ? '' : 's'}${feitas ? ' · ' + feitas + ' traduzido' + (feitas === 1 ? '' : 's') : ''}`), tr);
  b.append(meta);
  return b;
}

function desenharObra(o) {
  const ultimo = lido('ultimo:' + o.nome);
  const raiz = el('div', 'bib-obra obra-pagina');
  const ficha = el('aside', 'bib-ficha'); ficha.dataset.cor = corDe(o);
  const volta = el('button', 'obra-volta'); volta.type = 'button'; volta.innerHTML = ic('voltar') + '<span>Biblioteca</span>'; volta.setAttribute('aria-label', 'Voltar para a biblioteca');
  volta.addEventListener('click', () => abrirObra(null));
  const hero = el('header', 'obra-hero');
  const capa = el('div', 'obra-hero-capa');
  const inicial = () => capa.append(el('span', 'capa-inicial', (o.nome.trim()[0] || '?').toUpperCase()));
  if (o.capa) { const f = el('img'); f.alt = ''; f.decoding = 'async'; f.src = urlCapa(o); f.addEventListener('error', () => { f.remove(); inicial(); }); capa.append(f); } else inicial();
  const nome = el('h2', 'obra-hero-nome', o.nome); const res = el('p', 'obra-hero-resumo', Diagrama.resumo(o));
  const feitas = o.capitulos.filter((c) => c.traduzido).length;
  const prog = el('div', 'bib-progresso'); const tr = el('div', 'capa-trilho'); const barra = el('i'); barra.style.width = (o.capitulos.length ? Math.round(feitas / o.capitulos.length * 100) : 0) + '%'; tr.append(barra); prog.append(tr);
  const ler = el('button', 'btn principal'); ler.type = 'button'; ler.innerHTML = ic('ler');
  ler.append(el('span', '', ultimo && o.capitulos.some((c) => c.rel === ultimo) ? 'Continuar' : 'Ler'));
  ler.addEventListener('click', () => abrir(o, continuar(o)));
  const acoes = el('div', 'obra-hero-acoes'); acoes.append(ler);
  hero.append(capa, nome, res, prog, acoes);
  ficha.append(volta, hero);

  const lista = el('section', 'bib-lista'); lista.dataset.cor = corDe(o);
  const cab = el('div', 'bib-lista-cab'); cab.append(el('h3', '', 'Capítulos'));
  const ordem = el('button', 'bib-ordem', maisNovoPrimeiro ? 'Mais novos primeiro' : 'Mais antigos primeiro'); ordem.type = 'button';
  ordem.addEventListener('click', () => { maisNovoPrimeiro = !maisNovoPrimeiro; guardar('ordem', maisNovoPrimeiro ? 'novos' : 'antigos'); desenhar(); });
  cab.append(ordem);
  const itens = o.capitulos.map((c, i) => ({tipo: 'cap', c, i, n: numCap(c)}));
  agrupar(o.faltando).forEach((g) => itens.push({tipo: 'falta', g, n: parseFloat(g)}));
  itens.sort((x, y) => (((y.n !== null && x.n !== null) ? y.n - x.n : 0) || ((y.i || 0) - (x.i || 0))) * (maisNovoPrimeiro ? 1 : -1));
  const ul = el('ul', 'bib-trilho');
  itens.forEach((it) => {
    const li = el('li', 'bib-est');
    if (it.tipo === 'falta') { li.classList.add('falta'); li.textContent = 'Faltam na biblioteca: ' + it.g; ul.append(li); return; }
    const c = it.c, temNum = c.numero != null && c.numero !== '';
    li.classList.add(c.traduzido ? 't-pronto' : 't-pend'); if (ultimo === c.rel) li.classList.add('sel');
    const b = el('button', 'cap-item'); b.type = 'button'; b.dataset.rel = c.rel;
    const l1 = el('span', 'cap-l1'); l1.append(el('span', 'cap-num', temNum ? 'Cap. ' + c.numero : c.rotulo));
    if (c.titulo && temNum) l1.append(el('span', 'cap-sep', '·'), el('span', 'cap-titulo', c.titulo));
    const l2 = el('span', 'cap-l2'); l2.append(`${c.imagens} imagem${c.imagens === 1 ? '' : 's'} · `, el('span', 'cap-estado ' + (c.traduzido ? (c.incompleta ? 'aviso' : 'ok') : ''), c.traduzido ? (c.incompleta ? `Incompleto · ${c.incompleta} sem tradução` : 'Traduzido') : 'Sem tradução'));
    if (ultimo === c.rel) l2.append(' · ', el('span', 'cap-estado ativo', 'Parou aqui'));
    b.append(l1, l2); b.addEventListener('click', () => abrir(o, c));
    li.append(b); ul.append(li);
  });
  lista.append(cab, ul);
  raiz.append(ficha, lista);
  return raiz;
}

function desenhar() {
  const obra = obraAberta && dados.obras.find((o) => o.nome === obraAberta);
  const caixa = $('linhas');
  $('bib-conta').textContent = dados.obras.length && !obra ? `${dados.obras.length} obra${dados.obras.length === 1 ? '' : 's'}` : '';
  $('bib-barra').hidden = !!obra || !dados.obras.length;
  if (!dados.obras.length) {
    const v = el('div', 'vazio'); v.append(el('strong', '', 'Nada para ler ainda'), el('span', '', 'Quando o notebook baixar um capítulo, ele aparece aqui sozinho.'));
    caixa.className = 'linhas'; caixa.replaceChildren(v);
  } else if (obra) {
    caixa.className = 'linhas'; caixa.replaceChildren(desenharObra(obra));
  } else {
    const visiveis = dados.obras.filter((o) => !filtro || norm(o.nome).includes(norm(filtro)));
    caixa.className = visiveis.length ? 'capas' : 'linhas';
    caixa.replaceChildren(...(visiveis.length ? visiveis.map(cartaoObra) : [el('p', 'bib-vazio-filtro', `Nenhuma obra com “${filtro}”.`)]));
  }
}
$('bib-filtro').addEventListener('input', () => { filtro = $('bib-filtro').value.trim(); desenhar(); });

function chip(texto, classe) { $('sync').textContent = texto; $('sync').className = 'chip ' + classe; }

async function carregar() {
  const r = await fetch('/api/biblioteca', {cache: 'no-store'});
  if (r.status === 401 || r.status === 403) { chip('Sem acesso', 'erro'); throw new Error('acesso'); }
  const novo = await r.json();
  const primeira = !dados.versao;
  const antes = dados.obras.reduce((n, o) => n + o.capitulos.length, 0);
  dados = novo;
  if (obraAberta && !dados.obras.some((o) => o.nome === obraAberta)) obraAberta = null;
  desenhar();
  const agora = dados.obras.reduce((n, o) => n + o.capitulos.length, 0);
  if (!primeira && agora > antes) aviso(agora - antes === 1 ? 'Novo capítulo disponível' : `${agora - antes} capítulos novos`);
}

async function vigiar() {
  if (!document.hidden) {
    try {
      const r = await fetch('/api/versao', {cache: 'no-store'});
      if (!r.ok) throw new Error(String(r.status));
      const v = (await r.json()).versao;
      if (v !== dados.versao) await carregar();
      chip('Atualizado', 'ok');
    } catch (e) { if (e.message !== 'acesso') chip('Sem conexão com o notebook', 'erro'); }
  }
  setTimeout(vigiar, 3000);
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) vigiar_agora(); });
function vigiar_agora() { fetch('/api/versao', {cache: 'no-store'}).then((r) => r.json()).then((j) => { if (j.versao !== dados.versao) carregar(); chip('Atualizado', 'ok'); }).catch(() => chip('Sem conexão com o notebook', 'erro')); }
window.addEventListener('pageshow', () => { desenhar(); });
carregar().catch(() => {}).finally(vigiar);
