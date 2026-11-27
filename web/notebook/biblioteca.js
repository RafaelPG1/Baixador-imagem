/* Aba "Biblioteca": obras como linhas, capítulos como estações; ler, traduzir e organizar (só no notebook). */
let hist = {posicoes: {}, estados: {}, ultima: null}, tamanhos = {}, bib = {obras: [], versao: ''}, obraAberta = new URLSearchParams(location.search).get('obra'), escolhido = null, tradLog = 0, tradRodando = false, prontosVistos = 0;
const urlLeitor = (rel) => `/leitor?c=${encodeURIComponent(rel)}&t=${encodeURIComponent(T)}`;
const corDe = (o) => String(o.cor);
const urlCapa = (o) => rota('/api/capa', `&p=${encodeURIComponent(o.pasta)}&v=${o.capa_v}`);
function urlDaObra(nome) { const p = new URLSearchParams(location.search); if (nome) p.set('obra', nome); else p.delete('obra'); return `${location.pathname}?${p}#biblioteca`; }
let modoSel = null;                                  // seleção de capítulos para retraduzir/exportar: {tipo, sel:Set}
function abrirObra(nome) { obraAberta = nome; escolhido = null; modoSel = null; filtroCap = ''; history.pushState(null, '', urlDaObra(nome)); desenhar(); window.scrollTo(0, 0); }
window.addEventListener('popstate', () => { obraAberta = new URLSearchParams(location.search).get('obra'); escolhido = null; modoSel = null; filtroCap = ''; desenhar(); });

function el(tag, classe, texto) { const e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
function botao(texto, classe, aoClicar) { const b = el('button', 'btn ' + (classe || ''), texto); b.type = 'button'; b.addEventListener('click', aoClicar); return b; }
function achar(rel) {
  for (const o of bib.obras) for (const c of o.capitulos) if (c.rel === rel) return {obra: o, cap: c};
  return null;
}
function tamanhoLegivel(b) { return b >= 1073741824 ? (b / 1073741824).toFixed(1) + ' GB' : b >= 1048576 ? Math.round(b / 1048576) + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB'; }
async function acao(caminho, corpo, ok) {
  try { const r = await chamar(caminho, corpo); if (ok) aviso(ok(r)); return r; }
  catch (e) { aviso(e.message); return null; }
}

function lerCapitulo(c) { window.open(urlLeitor(c.rel), '_blank', 'noopener'); }
const ESTADO_OBRA = {'': 'Sem estado', quero: 'Quero ler', lendo: 'Lendo', concluida: 'Concluída'};      // da OBRA; "lido" é do capítulo e é outra coisa
const estadoDaObra = (o) => (hist.estados[o.nome] || {}).e || '';
async function definirEstado(o, e) { try { await chamar('/api/historico/estado', {obra: o.nome, estado: e, t: Date.now()}); hist.estados[o.nome] = {e, t: Date.now()}; desenhar(); } catch (x) { aviso(x.message); } }
function carregarHistorico() { return ler('/api/historico').then((h) => { if (JSON.stringify([h.estados, h.ultima]) !== JSON.stringify([hist.estados, hist.ultima])) { hist = h; desenhar(); } else hist = h; }).catch(() => {}); }
function blocoContinuar() {
  const u = hist.ultima; if (!u) return null;
  const o = bib.obras.find((x) => x.capitulos.some((c) => c.rel === u.rel)); const c = o && o.capitulos.find((x) => x.rel === u.rel);
  if (!c) return null;
  const b = el('div', 'bib-continuar'); b.append(el('span', '', `Continuar lendo: ${o.nome} — ${c.rotulo || nomeCap(c)} (página ${u.p} de ${u.n})`));
  b.append(botao('Continuar', 'principal pequeno', () => lerCapitulo(c)));
  return b;
}
function lerObra(o) {
  // 1º) o capítulo que você selecionou nesta obra; 2º) o primeiro liberado (traduzido) ainda não lido; 3º) o último liberado; 4º) o último baixado.
  const sel = escolhido && o.capitulos.find((c) => c.rel === escolhido);
  const liberados = o.capitulos.filter((c) => c.traduzido);
  const proximo = liberados.find((c) => !c.lido);                               // 2º) o primeiro liberado que você ainda não leu
  lerCapitulo(sel || proximo || (liberados.length ? liberados : o.capitulos).slice(-1)[0]);
}

/* ---------- ícones (um só traço) e menus ---------- */
const ICO = {
  ler: '<path d="M4 5a2 2 0 0 1 2-2h12v16H6a2 2 0 0 0-2 2z"/><path d="M4 19V5"/>',
  traduzir: '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
  mais: '<circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/>',
  seta: '<path d="m6 9 6 6 6-6"/>', x: '<path d="M6 6l12 12M18 6 6 18"/>',
  atualizar: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  imagem: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-4-4-9 9"/>',
  nome: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  pasta: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  lixo: '<path d="M4 7h16"/><path d="M10 11v6M14 11v6"/><path d="M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12"/><path d="M9 7V4h6v3"/>',
  ajuste: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3"/><path d="M1 14h6M9 8h6M17 16h6"/>',
  voltar: '<path d="m15 18-6-6 6-6"/>',
  baixar: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M4 21h16"/>',
};
const ic = (nome) => `<svg class="ic" viewBox="0 0 24 24" aria-hidden="true">${ICO[nome]}</svg>`;
function comIcone(nome, texto, classe) { const b = botao('', classe); b.innerHTML = ic(nome); b.append(el('span', '', texto)); return b; }
function itemMenu(nome, texto, classe, aoClicar) { const b = el('button', 'bib-item ' + (classe || '')); b.type = 'button'; b.innerHTML = ic(nome); b.append(el('span', '', texto)); b.addEventListener('click', aoClicar); return b; }

/* menus suspensos (botão + painel): fecham com Esc, clique fora ou ao escolher; um por vez */
let menuAberto = null;
function fecharMenu(voltarFoco) {
  if (!menuAberto) return;
  const {btn, painel} = menuAberto; painel.hidden = true; btn.setAttribute('aria-expanded', 'false');
  if (voltarFoco) btn.focus();
  menuAberto = null;
}
/* se o painel não cabe embaixo do botão: abre para cima (quando há espaço) ou rola a página só o necessário para ele aparecer inteiro */
function posicionarPainel(btn, painel) {
  painel.classList.remove('acima');
  const r = painel.getBoundingClientRect(); if (r.bottom <= window.innerHeight - 8) return;
  const topo = document.querySelector('.topo'), limite = topo ? topo.getBoundingClientRect().bottom : 0;
  if (btn.getBoundingClientRect().top - 8 - r.height >= limite + 8) { painel.classList.add('acima'); return; }
  painel.scrollIntoView({block: 'nearest', behavior: 'smooth'});
}
function ligarMenu(btn, painel) {
  btn.setAttribute('aria-expanded', 'false');
  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const abrir = painel.hidden;
    fecharMenu(false);
    if (abrir) { painel.hidden = false; btn.setAttribute('aria-expanded', 'true'); menuAberto = {btn, painel}; posicionarPainel(btn, painel); const f = painel.querySelector('select, button:not(:disabled), input'); if (f && ev.detail === 0) f.focus(); }
  });
  painel.addEventListener('click', (ev) => { if (ev.target.closest('.bib-item') || ev.target.closest('.bib-pop-acoes button')) fecharMenu(false); });
}
document.addEventListener('click', (ev) => { if (menuAberto && !menuAberto.painel.contains(ev.target)) fecharMenu(false); });
document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape' || $('pg-biblioteca').hidden) return;
  if (menuAberto) { fecharMenu(true); return; }
  if (escolhido) fecharDetalhe();
});
ligarMenu($('bib-tr-btn'), $('bib-tr-painel'));
ligarMenu($('bib-mais-btn'), $('bib-mais-painel'));

/* ---------- capítulo: lista (trilho de estações) e painel lateral ---------- */
let filtro = '', filtroCap = '', maisNovoPrimeiro = true, fila = {}, ultimoPainel = '';
const norm = (t) => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
const numCap = (c) => { const n = parseFloat(c.numero); return Number.isFinite(n) && String(c.numero).trim() !== '' ? n : null; };
function agrupar(nums) {
  const r = []; let ini = null, fim = null;
  (nums || []).slice().sort((x, y) => x - y).forEach((n) => {
    if (ini !== null && n === fim + 1) fim = n; else { if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim); ini = fim = n; }
  });
  if (ini !== null) r.push(ini === fim ? String(ini) : ini + '–' + fim);
  return r;
}
function estadoDoCapitulo(c) {
  const f = fila[c.rel];
  if (f) {
    if (f.estado === 'traduzindo') return {classe: 'ativo', t: `Traduzindo${f.total ? ' ' + Math.floor((f.feitas || 0) / f.total * 100) + '%' : '…'}`, linha: 'andando'};
    if (f.estado === 'fila') return {classe: 'ativo', t: 'Na fila', linha: 'fila'};
    if (f.estado === 'falhou') return {classe: 'erro', t: 'Falhou', linha: 'pend'};
  }
  if (c.baixa_incompleta) return {classe: 'erro', t: 'Download incompleto · apague e baixe de novo', linha: 'pend'};
  if (c.traduzido && c.incompleta) return {classe: 'aviso', t: `Incompleto · ${c.incompleta} fala${c.incompleta === 1 ? '' : 's'} sem tradução`, linha: 'pronto'};
  if (c.traduzido && c.revisar) return {classe: 'ok', t: `Traduzido · ${c.revisar} a revisar`, linha: 'pronto'};
  return c.traduzido ? {classe: 'ok', t: 'Traduzido', linha: 'pronto'} : {classe: '', t: 'Sem tradução', linha: 'pend'};
}
function escolherCapitulo(c) { escolhido = c.rel; ultimoPainel = ''; desenhar(); focarPainel(); }
function fecharDetalhe() {
  const rel = escolhido; escolhido = null; ultimoPainel = ''; desenhar();
  const b = rel && document.querySelector(`.cap-item[data-rel="${CSS.escape(rel)}"]`); if (b) b.focus();
}
function focarPainel() { const h = $('bib-detalhe').querySelector('h3'); if (h) h.focus({preventScroll: true}); }

function elegivelSel(c) { return modoSel && (modoSel.tipo === 'exportar' || modoSel.tipo === 'excluir' || c.traduzido); }       // exportar vale para qualquer capítulo
function baixarExportacao(params) {
  const a = document.createElement('a'); a.href = rota('/api/exportar', params); a.download = ''; document.body.append(a); a.click(); a.remove();
  aviso('Preparando o arquivo do app… o download começa em instantes (pode demorar com muitas imagens).');
}
function nomeCap(c) { return c.numero != null && c.numero !== '' ? 'Cap. ' + c.numero : c.rotulo; }
async function excluirCapitulos(o, caps) {
  const lista = caps.map(nomeCap), mostra = lista.length > 40 ? lista.slice(0, 40).join(', ') + ` … e mais ${lista.length - 40}` : lista.join(', ');
  const trad = caps.filter((c) => c.traduzido).length;
  if (!confirm(`Excluir ${caps.length === 1 ? 'este capítulo' : caps.length + ' capítulos'} de “${o.nome}”?\n\n${mostra}\n\nEles vão para a Lixeira (Mais ações → Lixeira), com imagens${trad ? ' e traduções' : ''}, e podem ser restaurados por 14 dias. Os outros capítulos e a obra ficam.`)) return;
  const r = await acao('/api/biblioteca/capitulos/excluir', {obra: o.nome, rels: caps.map((c) => c.rel)}, (x) => `${x.apagados.length} capítulo(s) movido(s) para a Lixeira.` + (x.erros.length ? ` Falhou: ${x.erros.join('; ')}` : ''));
  if (r) { modoSel = null; escolhido = null; ultimoPainel = ''; carregar(); }
}

function desenharBarraSelecao(o, elegiveis) {
  const re = modoSel.tipo === 'retraduzir', ex = modoSel.tipo === 'exportar', del = modoSel.tipo === 'excluir';
  const barra = el('div', 'bib-selecao');
  const n = modoSel.sel.size;
  barra.append(el('span', 'nota num', `${n} de ${elegiveis.length} selecionado${n === 1 ? '' : 's'}`));
  const todos = botao(n === elegiveis.length ? 'Limpar' : 'Selecionar todos', 'pequeno', () => { modoSel.sel = n === elegiveis.length ? new Set() : new Set(elegiveis.map((c) => c.rel)); desenhar(); });
  const ok = botao(`${del ? 'Excluir' : re ? 'Retraduzir' : 'Exportar'} ${n || ''}`.trim(), 'principal pequeno', async () => {
    if (!n) return;
    const rels = [...modoSel.sel];
    if (del) { await excluirCapitulos(o, o.capitulos.filter((c) => modoSel.sel.has(c.rel))); return; }
    if (ex) { modoSel = null; baixarExportacao(rels.map((r) => '&rel=' + encodeURIComponent(r)).join('')); desenhar(); return; }
    if (!confirm(`Retraduzir ${n} capítulo(s) de “${o.nome}”?\n\nCada tradução atual só é substituída quando a nova terminar; se a nova falhar ou for cancelada, a atual continua valendo.`)) return;
    modoSel = null;
    await traduzir({rels}); desenhar();
  });
  ok.disabled = !n;
  const cancela = botao('Cancelar', 'pequeno', () => { modoSel = null; desenhar(); });
  barra.append(todos, ok, cancela);
  if (del) {                                                       // marca um intervalo pelo número do capítulo (existentes entre os dois; sem número ficam de fora)
    const campo = (id, rot, chave) => { const i = el('input'); i.type = 'text'; i.id = id; i.inputMode = 'decimal'; i.maxLength = 7; i.value = modoSel[chave] || ''; i.setAttribute('aria-label', rot); i.placeholder = rot;
      i.addEventListener('input', () => { modoSel[chave] = i.value; }); i.addEventListener('keydown', (e) => { if (e.key === 'Enter') marcar(); }); return i; };
    const marcar = () => {
      const v = (t) => parseFloat(String(t || '').replace(',', '.'));
      const de = v(modoSel.de), ate = modoSel.ate ? v(modoSel.ate) : de;                    // só o inicial = um capítulo
      if (!Number.isFinite(de) || !Number.isFinite(ate)) { aviso('Informe o número inicial (e o final, se for um intervalo).'); return; }
      if (de > ate) { aviso('O número inicial é maior que o final.'); return; }
      const achados = o.capitulos.filter((c) => { const x = numCap(c); return x !== null && x >= de && x <= ate; });
      if (!achados.length) { aviso(`Nenhum capítulo entre ${de} e ${ate}.`); return; }
      achados.forEach((c) => modoSel.sel.add(c.rel)); desenhar();
    };
    const faixa = el('div', 'bib-intervalo');
    faixa.append(el('span', 'nota', 'Intervalo: do cap.'), campo('bib-sel-de', 'inicial', 'de'), el('span', 'nota', 'ao'), campo('bib-sel-ate', 'final (opcional)', 'ate'), botao('Marcar', 'pequeno', marcar));
    barra.append(faixa);
  }
  return barra;
}

function desenharLista(o) {
  const sec = el('section', 'bib-lista'); sec.dataset.cor = corDe(o);
  const cab = el('div', 'bib-lista-cab'); cab.append(el('h3', '', 'Capítulos'));
  const ordem = botao(maisNovoPrimeiro ? 'Mais novos primeiro' : 'Mais antigos primeiro', 'bib-ordem', () => { maisNovoPrimeiro = !maisNovoPrimeiro; desenhar(); });
  ordem.classList.remove('btn');
  let ulRef = null;
  cab.append(Diagrama.campoBusca(filtroCap, (v) => { filtroCap = v; if (ulRef) Diagrama.filtrar(ulRef, v); }), ordem);
  const elegiveis = o.capitulos.filter((c) => elegivelSel(c));
  const barraSel = modoSel ? desenharBarraSelecao(o, elegiveis) : null;
  const itens = o.capitulos.map((c, i) => ({tipo: 'cap', c, i, n: numCap(c)}));
  agrupar(o.faltando).forEach((g) => itens.push({tipo: 'falta', g, n: parseFloat(g)}));
  itens.sort((x, y) => (((y.n !== null && x.n !== null) ? y.n - x.n : 0) || ((y.i || 0) - (x.i || 0))) * (maisNovoPrimeiro ? 1 : -1));
  const ul = el('ul', 'bib-trilho');
  itens.forEach((it) => {
    const li = el('li', 'bib-est');
    if (it.tipo === 'falta') { li.classList.add('falta'); li.textContent = 'Faltam na biblioteca: ' + it.g; ul.append(li); return; }
    const c = it.c, est = estadoDoCapitulo(c), temNum = c.numero != null && c.numero !== '';
    li._cap = c; li.classList.add('t-' + est.linha); if (c.lido) li.classList.add('lido'); if (escolhido === c.rel) li.classList.add('sel');
    const b = el('button', 'cap-item' + (escolhido === c.rel ? ' atual' : '')); b.type = 'button'; b.dataset.rel = c.rel;
    b.setAttribute('aria-pressed', String(escolhido === c.rel));
    const l1 = el('span', 'cap-l1'); l1.append(el('span', 'cap-num', temNum ? 'Cap. ' + c.numero : c.rotulo));
    if (c.titulo && temNum) l1.append(el('span', 'cap-sep', '·'), el('span', 'cap-titulo', c.titulo));
    const l2 = el('span', 'cap-l2'); const estado = el('span', 'cap-estado ' + est.classe, est.t);
    l2.append(`${c.imagens} ${c.imagens === 1 ? 'imagem' : 'imagens'} · `, estado);
    if (c.lido) l2.append(' · ', el('span', 'cap-estado lido', 'Lido'));
    if (modoSel) {
      const marcado = modoSel.sel.has(c.rel);
      l1.prepend(el('span', 'cap-check', elegivelSel(c) ? (marcado ? '☑' : '☐') : '—'));
      b.setAttribute('aria-pressed', String(marcado)); b.disabled = !elegivelSel(c); if (marcado) li.classList.add('sel');
      b.addEventListener('click', () => { if (modoSel.sel.has(c.rel)) modoSel.sel.delete(c.rel); else modoSel.sel.add(c.rel); desenhar(); });
    }
    b.append(l1, l2); if (!modoSel) b.addEventListener('click', () => (escolhido === c.rel ? fecharDetalhe() : escolherCapitulo(c)));
    const acoes = el('div', 'cap-acoes');
    const f = fila[c.rel];
    if (f && (f.estado === 'fila' || (f.estado === 'traduzindo' && Object.keys(fila).length > 1))) {          // cancelar só este capítulo
      const x = comIcone('x', 'Cancelar', 'pequeno'); x.title = f.estado === 'fila' ? 'Tirar da fila' : 'Cancelar só este capítulo (a fila continua)';
      x.addEventListener('click', () => cancelarCapitulo(c.rel)); acoes.append(x); acoes.classList.add('fixo');
    }
    if (!modoSel) { const ler = comIcone('ler', 'Ler', 'pequeno'); ler.title = `Ler ${c.rotulo}`; ler.addEventListener('click', () => lerCapitulo(c)); acoes.append(ler); }
    li.append(b, acoes); ul.append(li);
  });
  ulRef = ul; if (filtroCap.trim()) Diagrama.filtrar(ul, filtroCap);
  sec.append(cab); if (barraSel) sec.append(barraSel); sec.append(ul);
  return sec;
}

function desenharDetalhe() {
  const box = $('bib-detalhe');
  const achado = escolhido && achar(escolhido);
  $('pg-biblioteca').classList.toggle('com-painel', !!achado);
  if (!achado) { box.hidden = true; box.replaceChildren(); ultimoPainel = ''; return; }
  const {obra, cap} = achado;
  const chave = [cap.rel, cap.lido, cap.traduzido, cap.incompleta, cap.baixa_incompleta, cap.revisar, cap.imagens, cap.numero, cap.titulo, obra.nome].join('|');
  if (chave === ultimoPainel && !box.hidden) return;                       // nada mudou: não refaz (não perde o que está sendo digitado)
  ultimoPainel = chave;
  box.hidden = false; box.dataset.cor = corDe(obra);
  const cab = el('div', 'detalhe-cab');
  const t = el('div');
  const h = el('h3', '', `${obra.nome} — ${cap.rotulo}`); h.tabIndex = -1;
  t.append(h, el('p', 'nota num', `${cap.imagens} imagem(ns) · ${cap.traduzido ? (cap.incompleta ? `incompleto (${cap.incompleta} fala${cap.incompleta === 1 ? '' : 's'} sem tradução)` : cap.revisar ? `traduzido (${cap.revisar} a revisar)` : 'traduzido') : 'sem tradução'}${cap.antigo ? ' · formato antigo (salve para organizar)' : ''}`));
  const fechar = botao('', 'pequeno bib-icone', fecharDetalhe); fechar.innerHTML = ic('x'); fechar.setAttribute('aria-label', 'Fechar painel do capítulo'); fechar.title = 'Fechar (Esc)';
  cab.append(t, fechar);

  const principais = el('div', 'bib-linha-acoes');
  const lerB = comIcone('ler', 'Ler', 'principal'); lerB.addEventListener('click', () => lerCapitulo(cap)); principais.append(lerB);
  const trad = comIcone('traduzir', cap.traduzido ? 'Traduzir de novo' : 'Traduzir', '');
  trad.addEventListener('click', () => {
    if (cap.traduzido && !confirm(`Traduzir de novo “${cap.rotulo}”? A tradução atual só é substituída quando a nova terminar; se a nova falhar ou for cancelada, a atual continua valendo.`)) return;
    traduzir({rel: cap.rel});
  });
  principais.append(trad);
  const lidoB = botao(cap.lido ? 'Marcar como não lido' : 'Marcar como lido', 'largo', async () => { if (await acao('/api/lidos', {rel: cap.rel, lido: !cap.lido})) carregar(); });
  principais.append(lidoB);

  const gTrad = el('div', 'bib-grupo'); gTrad.append(el('h4', '', 'Tradução'));
  const linhaT = el('div', 'bib-linha-acoes');
  if (cap.traduzido) {
    const ex = comIcone('lixo', 'Excluir tradução', 'perigo'); ex.classList.add('largo');
    ex.addEventListener('click', async () => {
      if (!confirm(`Excluir a tradução de “${cap.rotulo}”?\n\nSó a tradução é apagada; as imagens originais ficam. Isto não pode ser desfeito.`)) return;
      const r = await acao('/api/traducao/excluir', {rel: cap.rel}, () => 'Tradução excluída.');
      if (r) carregar();
    });
    linhaT.append(ex);
  } else linhaT.append(el('p', 'nota largo', 'Ainda sem tradução. Use “Traduzir” acima.'));
  const exp = comIcone('baixar', 'Exportar para o app do celular', ''); exp.classList.add('largo');
  exp.title = 'Baixa um ZIP deste capítulo (imagens + tradução) para importar no app do celular e ler sem internet';
  exp.addEventListener('click', () => baixarExportacao('&rel=' + encodeURIComponent(cap.rel)));
  linhaT.append(exp);
  gTrad.append(linhaT, el('p', 'nota', 'Para corrigir o texto traduzido, abra “Ler” e use “Editar tradução” no leitor.'));

  const gOrg = el('div', 'bib-grupo'); gOrg.append(el('h4', '', 'Organização'));
  const form = el('div', 'grade-2');
  const campo = (rot, valor, id, extra) => {
    const l = el('label', 'campo', rot); const i = el('input'); i.type = 'text'; i.id = id; i.value = valor == null ? '' : valor; i.spellcheck = false;
    if (extra) Object.assign(i, extra); l.append(i); form.append(l); return i;
  };
  const iObra = campo('Obra', obra.nome, 'bd-obra', {maxLength: 80});
  const iNum = campo('Capítulo nº', cap.numero, 'bd-num', {maxLength: 7});
  const iTit = campo('Nome do capítulo', cap.titulo, 'bd-tit', {maxLength: 80});
  const salvar = botao('Salvar organização', 'principal', async () => {
    const r = await acao('/api/biblioteca/capitulo', {rel: cap.rel, obra: iObra.value, numero: iNum.value, titulo: iTit.value}, () => 'Capítulo reorganizado.');
    if (r) { escolhido = r.rel; ultimoPainel = ''; carregar(); }
  });
  const renomear = botao('Renomear a obra inteira', '', async () => {
    const novo = iObra.value.trim();
    if (!novo || novo === obra.nome) { aviso('Escreva o novo nome no campo “Obra”.'); return; }
    if (!confirm(`Renomear a obra “${obra.nome}” para “${novo}”? Todos os ${obra.capitulos.length} capítulos serão movidos (se “${novo}” já existir, as duas se juntam).`)) return;
    const r = await acao('/api/biblioteca/obra', {obra: obra.nome, novo}, (x) => `${x.capitulos} capítulo(s) movido(s).`);
    if (r) { escolhido = null; obraAberta = novo; history.replaceState(null, '', urlDaObra(novo)); carregar(); }
  });
  const linhaO = el('div', 'bib-linha-acoes'); linhaO.append(salvar, renomear);
  gOrg.append(form, linhaO);

  const gArq = el('div', 'bib-grupo'); gArq.append(el('h4', '', 'Arquivos'));
  const pasta = comIcone('pasta', 'Abrir pasta do capítulo', ''); pasta.addEventListener('click', () => acao('/api/biblioteca/abrir-pasta', {rel: cap.rel}));
  const exCap = comIcone('lixo', 'Excluir este capítulo', 'perigo'); exCap.addEventListener('click', () => excluirCapitulos(obra, [cap]));
  gArq.append(pasta, exCap);

  box.replaceChildren(cab, principais, gTrad, gOrg, gArq);
  box.scrollTop = 0;
}

/* ---------- obra aberta: ficha à esquerda, capítulos à direita ---------- */
function desenharObra(o) {
  const raiz = el('div', 'bib-obra obra-pagina');
  const ficha = el('aside', 'bib-ficha'); ficha.dataset.cor = corDe(o);
  const volta = el('button', 'obra-volta'); volta.type = 'button'; volta.innerHTML = ic('voltar') + '<span>Biblioteca</span>'; volta.setAttribute('aria-label', 'Voltar para a biblioteca');
  volta.addEventListener('click', () => abrirObra(null));
  const hero = el('header', 'obra-hero');
  const capa = el('div', 'obra-hero-capa');
  const inicial = () => capa.append(el('span', 'capa-inicial', (o.nome.trim()[0] || '?').toUpperCase()));
  if (o.capa) { const f = el('img'); f.alt = ''; f.decoding = 'async'; f.src = urlCapa(o); f.addEventListener('error', () => { f.remove(); inicial(); }); capa.append(f); } else inicial();
  const pend = o.capitulos.filter((c) => !c.traduzido).length;
  const feitas = o.capitulos.length - pend;
  const prog = el('div', 'bib-progresso'); const tr = el('div', 'capa-trilho'); const barra = el('i'); barra.style.width = (o.capitulos.length ? Math.round(feitas / o.capitulos.length * 100) : 0) + '%'; tr.append(barra);
  prog.append(tr);
  const acoes = el('div', 'obra-hero-acoes');
  const selE = el('select', 'bib-estado'); selE.setAttribute('aria-label', 'Estado da obra'); Object.entries(ESTADO_OBRA).forEach(([v, t]) => { const op = el('option', '', v ? t : 'Estado: —'); op.value = v; selE.append(op); }); selE.value = estadoDaObra(o); selE.addEventListener('change', () => definirEstado(o, selE.value));
  acoes.append(comIcone('ler', 'Ler', 'principal'));
  acoes.firstChild.addEventListener('click', () => lerObra(o));
  acoes.append(selE);
  if (pend) { const b = comIcone('traduzir', `Traduzir ${pend} pendente${pend === 1 ? '' : 's'}`, ''); b.addEventListener('click', () => traduzir({lote: 'pendentes', obra: o.nome})); acoes.append(b); }
  if (o.pasta) {
    const atual = comIcone('atualizar', 'Atualizar', '');
    atual.title = 'Baixar os capítulos mais novos desta obra';
    atual.addEventListener('click', async () => {
      if (!o.ultima_url) { aviso('Nenhum capítulo desta obra guarda o endereço (capitulo.json). Baixe um capítulo pelo programa para poder atualizar.'); return; }
      const r = await Baixar.atualizarObra(o.ultima_url, o.nome);
      if (r) irPara('baixar');
    });
    acoes.append(atual);
  }
  // mais ações da obra
  const menu = el('div', 'bib-menu'); const mb = comIcone('mais', 'Mais ações', ''); mb.setAttribute('aria-controls', 'bib-obra-mais'); mb.insertAdjacentHTML('beforeend', ic('seta'));
  const pn = el('div', 'bib-popover'); pn.id = 'bib-obra-mais'; pn.hidden = true;
  if (o.pasta) {
    const temCapa = !!o.capa;
    pn.append(itemMenu('imagem', temCapa ? 'Atualizar capa' : 'Baixar capa', '', async () => {
      if (temCapa && !confirm(`Trocar a capa de “${o.nome}” pela que está na página da obra?`)) return;
      const r = await acao('/api/capa/baixar', {pasta: o.pasta, substituir: temCapa, ...Baixar.configuracaoNavegador()}, (x) => x.mensagem);
      if (r) carregar();
    }));
    pn.append(itemMenu('nome', 'Renomear obra', '', async () => {
      const novo = (prompt(`Novo nome para “${o.nome}”.\nSe já existir uma obra com esse nome, as duas serão juntadas.`, o.nome) || '').trim();
      if (!novo || novo === o.nome) return;
      const r = await acao('/api/biblioteca/obra', {obra: o.nome, novo}, (x) => `Obra renomeada (${x.capitulos} capítulo(s) atualizados).`);
      if (r) { escolhido = null; obraAberta = novo; history.replaceState(null, '', urlDaObra(novo)); carregar(); }
    }));
  }
  if (feitas) {
    const iniciarSel = (tipo) => { escolhido = null; modoSel = {tipo, sel: new Set()}; desenhar(); };
    pn.append(itemMenu('traduzir', 'Retraduzir capítulos…', '', () => iniciarSel('retraduzir')));
    pn.append(el('hr'));
  }
  if (o.capitulos.length) pn.append(itemMenu('traduzir', 'Tradução com IA na web…', '', () => WebIA.abrir(o)));
  if (o.capitulos.length) pn.append(itemMenu('baixar', 'Exportar para o app…', '', () => { escolhido = null; modoSel = {tipo: 'exportar', sel: new Set()}; desenhar(); }));
  if (feitas) pn.append(itemMenu('lixo', `Excluir ${feitas === 1 ? 'a tradução' : feitas + ' traduções'}`, 'perigo', async () => {
    if (!confirm(`Excluir ${feitas === 1 ? 'a tradução' : 'as ' + feitas + ' traduções'} de “${o.nome}”?\n\nAs imagens originais ficam. Isto não pode ser desfeito.`)) return;
    const r = await acao('/api/traducao/excluir', {obra: o.nome}, (x) => `${x.traducoes} tradução(ões) excluída(s).`);
    if (r) carregar();
  }));
  if (o.capitulos.length) pn.append(itemMenu('lixo', 'Excluir capítulos…', 'perigo', () => { escolhido = null; modoSel = {tipo: 'excluir', sel: new Set(), de: '', ate: ''}; desenhar(); }));
  if (o.pasta) {
    pn.append(el('hr'));
    pn.append(itemMenu('lixo', 'Excluir obra', 'perigo', async () => {
      if (!confirm(`Excluir a obra “${o.nome}”?\n\nOs ${o.capitulos.length} capítulo(s), as traduções e a capa vão para a Lixeira e podem ser restaurados por 14 dias. Outras obras não são afetadas.`)) return;
      const r = await acao('/api/biblioteca/obra/excluir', {obra: o.nome}, (x) => `Obra movida para a Lixeira (${x.capitulos} capítulo(s)).`);
      if (r) { obraAberta = null; escolhido = null; history.replaceState(null, '', urlDaObra(null)); carregar(); }
    }));
  }
  menu.append(mb, pn); ligarMenu(mb, pn); acoes.append(menu);
  hero.append(capa, el('h2', 'obra-hero-nome', o.nome), el('p', 'obra-hero-resumo', Diagrama.resumo(o)), prog, acoes);
  ficha.append(volta, hero);
  raiz.append(ficha, desenharLista(o));
  return raiz;
}

/* ---------- lista de obras ---------- */
function cartaoObra(o) {
  const b = Diagrama.cartao(o, urlCapa, (x) => abrirObra(x.nome));
  const n = o.capitulos.length, feitas = o.capitulos.filter((c) => c.traduzido).length;
  const meta = el('span', 'capa-meta');
  const nome = b.querySelector('.capa-nome'); nome.remove(); b.title = o.nome;
  const tr = el('span', 'capa-trilho'); const barra = el('i'); barra.style.width = (n ? Math.round(feitas / n * 100) : 0) + '%'; tr.append(barra);
  const est = estadoDaObra(o); if (est) b.title = `${o.nome} — ${ESTADO_OBRA[est]}`;
  meta.append(nome, ...(est ? [el('span', 'capa-estado', ESTADO_OBRA[est])] : []), el('span', 'capa-sub', `${n} capítulo${n === 1 ? '' : 's'}${feitas ? ' · ' + feitas + ' traduzido' + (feitas === 1 ? '' : 's') : ''}${tamanhos[o.nome] ? ' · ' + tamanhoLegivel(tamanhos[o.nome]) : ''}`), tr);
  b.append(meta);
  return b;
}

/* o redesenho recria o DOM: guarda e devolve a rolagem da ficha e da lista de capítulos */
function rolagens() { return ['.bib-ficha', '.bib-trilho'].map((q) => { const e = document.querySelector(q); return e ? e.scrollTop : 0; }); }
function devolverRolagens(r) { ['.bib-ficha', '.bib-trilho'].forEach((q, i) => { const e = document.querySelector(q); if (e && r[i]) e.scrollTop = r[i]; }); }

function desenhar() {
  const obra = obraAberta && bib.obras.find((o) => o.nome === obraAberta);
  const caixa = $('bib-linhas');
  const focoRel = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.rel;
  const rol = rolagens();
  const focoId = document.activeElement && /^bib-(busca-cap|sel-)/.test(document.activeElement.id) ? document.activeElement.id : '';
  $('bib-conta').textContent = bib.obras.length ? (obra ? '' : `${bib.obras.length} obra${bib.obras.length === 1 ? '' : 's'}`) : '';
  $('bib-filtro').closest('.bib-busca').hidden = !!obra || !bib.obras.length;
  $('bib-estado').hidden = !!obra || !bib.obras.length;
  if (!bib.obras.length) {
    const v = el('div', 'vazio'); v.append(el('strong', '', 'A biblioteca está vazia'), el('span', '', 'Baixe um capítulo na aba “Baixar imagens”: a obra aparece aqui com a capa e o nome.'));
    v.append(botao('Ir para Baixar imagens', '', () => irPara('baixar')));
    caixa.className = 'linhas'; caixa.replaceChildren(v);
  } else if (obra) {
    caixa.className = 'linhas'; caixa.replaceChildren(desenharObra(obra));
  } else {
    const sel = $('bib-estado').value, visiveis = bib.obras.filter((o) => (!filtro || norm(o.nome).includes(norm(filtro))) && (!sel || (sel === 'sem' ? !estadoDaObra(o) : estadoDaObra(o) === sel)));
    caixa.className = visiveis.length ? 'capas' : 'linhas';
    const continuar = !filtro && !sel && blocoContinuar();
    caixa.replaceChildren(...(continuar ? [continuar] : []), ...(visiveis.length ? visiveis.map(cartaoObra) : [el('p', 'bib-vazio-filtro', filtro ? `Nenhuma obra com “${filtro}”.` : 'Nenhuma obra neste estado.')]));
  }
  devolverRolagens(rol);
  if (focoId) { const i = $(focoId); if (i) { i.focus({preventScroll: true}); i.setSelectionRange(i.value.length, i.value.length); } }
  desenharDetalhe();
  if (focoRel) { const b = document.querySelector(`.cap-item[data-rel="${CSS.escape(focoRel)}"]`); if (b) b.focus({preventScroll: true}); }
}
$('bib-estado').addEventListener('change', desenhar);
$('bib-filtro').addEventListener('input', () => { filtro = $('bib-filtro').value.trim(); desenhar(); });

async function carregar() {
  try {
    bib = await ler('/api/biblioteca');
    if (obraAberta && !bib.obras.some((o) => o.nome === obraAberta)) obraAberta = null;
    if (escolhido && !achar(escolhido)) escolhido = null;
    desenhar(); carregarObras(); carregarHistorico();
    ler('/api/armazenamento/tamanhos').then((t) => { if (JSON.stringify(t.obras) !== JSON.stringify(tamanhos)) { tamanhos = t.obras; desenhar(); } }).catch(() => {});   // o servidor guarda em cache até a biblioteca mudar
  } catch (_) {}
}

/* ---- tradução */
async function cancelarCapitulo(rel) {
  await acao('/api/traducao/cancelar-item', {rel}, (x) => (x.onde === 'fila' ? 'Capítulo tirado da fila.' : 'Cancelando este capítulo…'));
  if (typeof sondarTraducao === 'function') sondarTraducao();
}
async function traduzir(alvo) {
  tradLog = 0;
  const r = await acao('/api/traduzir', {...alvo}, (x) => x.conjuntos ? `Traduzindo ${x.conjuntos} capítulo(s)…` : 'Tradução iniciada.');
  if (r) { sondarTraducao(); document.dispatchEvent(new CustomEvent('traducao-iniciada')); }
}
let filaAnterior = '';
async function sondarTraducao() {
  let e;
  try { e = await ler('/api/traducao/estado', '&log=999999999'); } catch (_) { return; }
  const dep = e.dependencias || {pronto: true};
  $('trad-aviso').hidden = !!dep.pronto; $('trad-aviso').textContent = dep.mensagem || '';
  const rodando = e.estado === 'executando';
  $('trad-pendentes').disabled = rodando;

  $('bib-tr-btn').classList.toggle('ativo', rodando);

  // estado de cada capítulo na lista (trilho)
  const nova = {}; (e.itens || []).forEach((i) => { if (i.rel) nova[i.rel] = i; });
  fila = rodando ? nova : {};
  const assinatura = JSON.stringify(fila);
  if (assinatura !== filaAnterior) { filaAnterior = assinatura; if (obraAberta) desenhar(); }

  if ((tradRodando && !rodando) || (rodando && e.prontos !== prontosVistos)) carregar();
  prontosVistos = e.prontos;
  tradRodando = rodando;
}
$('trad-pendentes').addEventListener('click', () => traduzir({lote: 'pendentes'}));

/* ---- motor de tradução (o mesmo da aba Traduções; a escolha é sempre explícita) */
function desenharMotorBib(cfg) {
  const sel = $('bib-motor');
  if (!sel.options.length) Object.entries(cfg.motores || {}).forEach(([v, r]) => sel.append(new Option(r, v)));
  sel.value = cfg.motor;
  $('bib-tr-resumo').textContent = ({local: 'TranslateGemma', mymemory: 'MyMemory', web: 'IA na web'})[cfg.motor] || '';
}
document.addEventListener('motor-mudou', (ev) => desenharMotorBib(ev.detail));
$('bib-motor').addEventListener('change', async () => {
  const v = $('bib-motor').value, st = $('bib-motor-status');
  await Motor.escolher(v);
  st.textContent = 'Verificando…';
  const h = await Motor.verificar(v); st.textContent = (h.pronto ? '✔ ' : '✖ ') + h.mensagem;
});
Motor.carregar();
$('excluir-tudo').addEventListener('click', async () => {
  const n = bib.obras.length;
  if (!n) { aviso('A biblioteca já está vazia.'); return; }
  if (!confirm(`ATENÇÃO: isto apaga TODA a biblioteca.\n\nAs ${n} obra(s), todos os capítulos, traduções e capas vão para a Lixeira e podem ser restaurados por 14 dias.\n\nContinuar?`)) return;
  if ((prompt('Para confirmar, digite APAGAR TUDO (em maiúsculas):') || '').trim() !== 'APAGAR TUDO') { aviso('Nada foi apagado.'); return; }
  const r = await acao('/api/biblioteca/excluir-tudo', {confirmacao: 'APAGAR TUDO'}, (x) => `${x.obras} obra(s) e ${x.capitulos} capítulo(s) movidos para a Lixeira.`);
  if (r) { obraAberta = null; escolhido = null; history.replaceState(null, '', urlDaObra(null)); carregar(); }
});
$('abrir-saida').addEventListener('click', () => acao('/api/biblioteca/abrir-pasta', {}));

/* o leitor abre em outra aba e marca "lido" no servidor (isso não muda a "versão" da biblioteca): ao voltar para esta aba, recarrega */
document.addEventListener('visibilitychange', () => { if (!document.hidden && !$('pg-biblioteca').hidden) carregar(); });

/* ---- sincronização: a cada 3 s confere a "versão" da biblioteca; só recarrega se mudou */
async function vigiar() {
  if (!$('pg-biblioteca').hidden && !document.hidden) {
    try {
      const v = (await ler('/api/versao')).versao;
      if (v !== bib.versao) await carregar();
      sondarTraducao();
    } catch (_) {}
  }
  setTimeout(vigiar, 3000);
}
document.addEventListener('pagina', (ev) => { if (ev.detail === 'biblioteca') carregar(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden && !$('pg-biblioteca').hidden) carregarHistorico(); });
carregar(); vigiar();
irPara(location.hash.slice(1));