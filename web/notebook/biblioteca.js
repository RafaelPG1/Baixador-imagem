/* Aba "Biblioteca": obras como linhas, capítulos como estações; ler, traduzir e organizar (só no notebook). */
let bib = {obras: [], versao: ''}, obraAberta = new URLSearchParams(location.search).get('obra'), escolhido = null, tradLog = 0, tradRodando = false, prontosVistos = 0;
const urlLeitor = (rel) => `/leitor?c=${encodeURIComponent(rel)}&t=${encodeURIComponent(T)}`;
const corDe = (o) => String(o.cor);
const urlCapa = (o) => rota('/api/capa', `&p=${encodeURIComponent(o.pasta)}&v=${o.capa_v}`);
function urlDaObra(nome) { const p = new URLSearchParams(location.search); if (nome) p.set('obra', nome); else p.delete('obra'); return `${location.pathname}?${p}#biblioteca`; }
let modoSel = null;                                  // seleção de capítulos para retraduzir/reajustar: {tipo, sel:Set}
function abrirObra(nome) { obraAberta = nome; escolhido = null; modoSel = null; history.pushState(null, '', urlDaObra(nome)); desenhar(); window.scrollTo(0, 0); }
window.addEventListener('popstate', () => { obraAberta = new URLSearchParams(location.search).get('obra'); escolhido = null; modoSel = null; desenhar(); });

function el(tag, classe, texto) { const e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
function botao(texto, classe, aoClicar) { const b = el('button', 'btn ' + (classe || ''), texto); b.type = 'button'; b.addEventListener('click', aoClicar); return b; }
function achar(rel) {
  for (const o of bib.obras) for (const c of o.capitulos) if (c.rel === rel) return {obra: o, cap: c};
  return null;
}
async function acao(caminho, corpo, ok) {
  try { const r = await chamar(caminho, corpo); if (ok) aviso(ok(r)); return r; }
  catch (e) { aviso(e.message); return null; }
}

function lerCapitulo(c) { window.open(urlLeitor(c.rel), '_blank', 'noopener'); }
function lerObra(o) {
  // 1º) o capítulo que você selecionou nesta obra; 2º) o último já liberado (traduzido); 3º) o último baixado.
  const sel = escolhido && o.capitulos.find((c) => c.rel === escolhido);
  const liberados = o.capitulos.filter((c) => c.traduzido);
  lerCapitulo(sel || (liberados.length ? liberados : o.capitulos).slice(-1)[0]);
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
function ligarMenu(btn, painel) {
  btn.setAttribute('aria-expanded', 'false');
  btn.addEventListener('click', (ev) => {
    ev.stopPropagation();
    const abrir = painel.hidden;
    fecharMenu(false);
    if (abrir) { painel.hidden = false; btn.setAttribute('aria-expanded', 'true'); menuAberto = {btn, painel}; const f = painel.querySelector('select, button:not(:disabled), input'); if (f && ev.detail === 0) f.focus(); }
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
let filtro = '', maisNovoPrimeiro = true, fila = {}, ultimoPainel = '';
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
const REFINO_ROT = {fila: 'aguardando refino', refinando: 'refinando', pronto: 'refinado'};
function estadoDoCapitulo(c) {
  const f = fila[c.rel];
  if (f) {
    if (f.estado === 'traduzindo') return {classe: 'ativo', t: `Traduzindo${f.total ? ' ' + Math.floor((f.feitas || 0) / f.total * 100) + '%' : '…'}`, linha: 'andando'};
    if (f.estado === 'fila') return {classe: 'ativo', t: 'Na fila', linha: 'fila'};
    if (f.refino === 'refinando') return {classe: 'ativo', t: `Refinando${f.rtotal ? ' ' + Math.floor((f.rfeitas || 0) / f.rtotal * 100) + '%' : '…'}`, linha: 'andando'};
    if (f.refino === 'fila') return {classe: 'ok', t: 'Traduzido · refino na fila', linha: 'pronto'};
    if (f.estado === 'falhou') return {classe: 'erro', t: 'Falhou', linha: 'pend'};
  }
  if (c.traduzido && c.incompleta) return {classe: 'aviso', t: `Incompleto · ${c.incompleta} página${c.incompleta === 1 ? '' : 's'} sem tradução`, linha: 'pronto'};
  return c.traduzido ? {classe: 'ok', t: 'Traduzido', linha: 'pronto'} : {classe: '', t: 'Sem tradução', linha: 'pend'};
}
function escolherCapitulo(c) { escolhido = c.rel; ultimoPainel = ''; desenhar(); focarPainel(); }
function fecharDetalhe() {
  const rel = escolhido; escolhido = null; ultimoPainel = ''; desenhar();
  const b = rel && document.querySelector(`.cap-item[data-rel="${CSS.escape(rel)}"]`); if (b) b.focus();
}
function focarPainel() { const h = $('bib-detalhe').querySelector('h3'); if (h) h.focus({preventScroll: true}); }

function elegivelSel(c) { return modoSel && (modoSel.tipo === 'exportar' || c.traduzido); }       // exportar vale para qualquer capítulo
function baixarExportacao(params) {
  const a = document.createElement('a'); a.href = rota('/api/exportar', params); a.download = ''; document.body.append(a); a.click(); a.remove();
  aviso('Preparando o arquivo do app… o download começa em instantes (pode demorar com muitas imagens).');
}
function desenharBarraSelecao(o, elegiveis) {
  const re = modoSel.tipo === 'retraduzir', ex = modoSel.tipo === 'exportar';
  const barra = el('div', 'bib-selecao');
  const n = modoSel.sel.size;
  barra.append(el('span', 'nota num', `${n} de ${elegiveis.length} selecionado${n === 1 ? '' : 's'}`));
  const todos = botao(n === elegiveis.length ? 'Limpar' : 'Selecionar todos', 'pequeno', () => { modoSel.sel = n === elegiveis.length ? new Set() : new Set(elegiveis.map((c) => c.rel)); desenhar(); });
  const ok = botao(`${re ? 'Retraduzir' : ex ? 'Exportar' : 'Reajustar'} ${n || ''}`.trim(), 'principal pequeno', async () => {
    if (!n) return;
    const rels = [...modoSel.sel];
    if (ex) { modoSel = null; baixarExportacao(rels.map((r) => '&rel=' + encodeURIComponent(r)).join('')); desenhar(); return; }
    if (re && !confirm(`Retraduzir ${n} capítulo(s) de “${o.nome}”?\n\nCada tradução atual só é substituída quando a nova terminar; se a nova falhar ou for cancelada, a atual é restaurada.`)) return;
    modoSel = null;
    if (re) { await traduzir({rels}); desenhar(); return; }
    const r = await acao('/api/traducao/reajustar', {rels}, (x) => `Reajustado: ${x.trechos} trecho(s) em ${x.imagens} imagem(ns), ${x.conjuntos} capítulo(s).`);
    if (r) carregar(); else desenhar();
  });
  ok.disabled = !n;
  const cancela = botao('Cancelar', 'pequeno', () => { modoSel = null; desenhar(); });
  barra.append(todos, ok, cancela);
  return barra;
}

function desenharLista(o) {
  const sec = el('section', 'bib-lista'); sec.dataset.cor = corDe(o);
  const cab = el('div', 'bib-lista-cab'); cab.append(el('h3', '', 'Capítulos'));
  const ordem = botao(maisNovoPrimeiro ? 'Mais novos primeiro' : 'Mais antigos primeiro', 'bib-ordem', () => { maisNovoPrimeiro = !maisNovoPrimeiro; desenhar(); });
  ordem.classList.remove('btn'); cab.append(ordem);
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
    li.classList.add('t-' + est.linha); if (escolhido === c.rel) li.classList.add('sel');
    const b = el('button', 'cap-item' + (escolhido === c.rel ? ' atual' : '')); b.type = 'button'; b.dataset.rel = c.rel;
    b.setAttribute('aria-pressed', String(escolhido === c.rel));
    const l1 = el('span', 'cap-l1'); l1.append(el('span', 'cap-num', temNum ? 'Cap. ' + c.numero : c.rotulo));
    if (c.titulo && temNum) l1.append(el('span', 'cap-sep', '·'), el('span', 'cap-titulo', c.titulo));
    const l2 = el('span', 'cap-l2'); const estado = el('span', 'cap-estado ' + est.classe, est.t);
    l2.append(`${c.imagens} ${c.imagens === 1 ? 'imagem' : 'imagens'} · `, estado);
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
  sec.append(cab); if (barraSel) sec.append(barraSel); sec.append(ul);
  return sec;
}

function desenharDetalhe() {
  const box = $('bib-detalhe');
  const achado = escolhido && achar(escolhido);
  $('pg-biblioteca').classList.toggle('com-painel', !!achado);
  if (!achado) { box.hidden = true; box.replaceChildren(); ultimoPainel = ''; return; }
  const {obra, cap} = achado;
  const chave = [cap.rel, cap.traduzido, cap.incompleta, cap.imagens, cap.numero, cap.titulo, obra.nome].join('|');
  if (chave === ultimoPainel && !box.hidden) return;                       // nada mudou: não refaz (não perde o que está sendo digitado)
  ultimoPainel = chave;
  box.hidden = false; box.dataset.cor = corDe(obra);
  const cab = el('div', 'detalhe-cab');
  const t = el('div');
  const h = el('h3', '', `${obra.nome} — ${cap.rotulo}`); h.tabIndex = -1;
  t.append(h, el('p', 'nota num', `${cap.imagens} imagem(ns) · ${cap.traduzido ? (cap.incompleta ? `incompleto (${cap.incompleta} página${cap.incompleta === 1 ? '' : 's'} sem tradução)` : 'traduzido') : 'sem tradução'}${cap.antigo ? ' · formato antigo (salve para organizar)' : ''}`));
  const fechar = botao('', 'pequeno bib-icone', fecharDetalhe); fechar.innerHTML = ic('x'); fechar.setAttribute('aria-label', 'Fechar painel do capítulo'); fechar.title = 'Fechar (Esc)';
  cab.append(t, fechar);

  const principais = el('div', 'bib-linha-acoes');
  const lerB = comIcone('ler', 'Ler', 'principal'); lerB.addEventListener('click', () => lerCapitulo(cap)); principais.append(lerB);
  const trad = comIcone('traduzir', cap.traduzido ? 'Traduzir de novo' : 'Traduzir', '');
  trad.addEventListener('click', () => {
    if (cap.traduzido && !confirm(`Traduzir de novo “${cap.rotulo}”? A tradução atual só é substituída quando a nova terminar; se a nova falhar ou for cancelada, a atual é restaurada. Suas correções salvas (glossário e memória) serão reaproveitadas.`)) return;
    traduzir({rel: cap.rel});
  });
  principais.append(trad);
  if (cap.traduzido && cap.incompleta) {
    const comp = comIcone('traduzir', `Completar ${cap.incompleta} página${cap.incompleta === 1 ? '' : 's'} sem tradução`, '');
    comp.title = 'Traduz só as páginas que ficaram sem tradução, sem mexer nas que já estão prontas';
    comp.addEventListener('click', () => traduzir({rel: cap.rel, completar: true}));
    principais.append(comp);
  }

  const gTrad = el('div', 'bib-grupo'); gTrad.append(el('h4', '', 'Tradução'));
  const linhaT = el('div', 'bib-linha-acoes');
  if (cap.traduzido) {
    const aj = comIcone('ajuste', 'Reajustar caixas e cores', ''); aj.classList.add('largo');
    aj.addEventListener('click', async () => {
      const r = await acao('/api/traducao/reajustar', {rel: cap.rel}, (x) => `Reajustado: ${x.trechos} trecho(s) em ${x.imagens} imagem(ns).`);
      if (r) carregar();
    });
    const ex = comIcone('lixo', 'Excluir tradução', 'perigo'); ex.classList.add('largo');
    ex.addEventListener('click', async () => {
      if (!confirm(`Excluir a tradução de “${cap.rotulo}”?\n\nSó o texto traduzido é apagado; as imagens originais ficam. Suas correções salvas (glossário e memória) continuam guardadas. Isto não pode ser desfeito.`)) return;
      const r = await acao('/api/traducao/excluir', {rel: cap.rel}, () => 'Tradução excluída.');
      if (r) carregar();
    });
    linhaT.append(aj, ex);
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
  gArq.append(pasta);

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
  acoes.append(comIcone('ler', 'Ler', 'principal'));
  acoes.firstChild.addEventListener('click', () => lerObra(o));
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
    pn.append(itemMenu('ajuste', 'Reajustar capítulos…', '', () => iniciarSel('reajustar')));
    pn.append(el('hr'));
  }
  if (o.capitulos.length) pn.append(itemMenu('baixar', 'Exportar para o app…', '', () => { escolhido = null; modoSel = {tipo: 'exportar', sel: new Set()}; desenhar(); }));
  if (feitas) pn.append(itemMenu('lixo', `Excluir ${feitas === 1 ? 'a tradução' : feitas + ' traduções'}`, 'perigo', async () => {
    if (!confirm(`Excluir ${feitas === 1 ? 'a tradução' : 'as ' + feitas + ' traduções'} de “${o.nome}”?\n\nAs imagens originais ficam. Isto não pode ser desfeito.`)) return;
    const r = await acao('/api/traducao/excluir', {obra: o.nome}, (x) => `${x.traducoes} tradução(ões) excluída(s).`);
    if (r) carregar();
  }));
  if (o.pasta) {
    pn.append(el('hr'));
    pn.append(itemMenu('lixo', 'Excluir obra', 'perigo', async () => {
      if (!confirm(`Excluir a obra “${o.nome}” do disco?\n\nOs ${o.capitulos.length} capítulo(s), as traduções e a capa serão apagados. Outras obras não são afetadas. Isto não pode ser desfeito.`)) return;
      const r = await acao('/api/biblioteca/obra/excluir', {obra: o.nome}, (x) => `Obra excluída (${x.capitulos} capítulo(s)).`);
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
  meta.append(nome, el('span', 'capa-sub', `${n} capítulo${n === 1 ? '' : 's'}${feitas ? ' · ' + feitas + ' traduzido' + (feitas === 1 ? '' : 's') : ''}`), tr);
  b.append(meta);
  return b;
}

function desenhar() {
  const obra = obraAberta && bib.obras.find((o) => o.nome === obraAberta);
  const caixa = $('bib-linhas');
  const focoRel = document.activeElement && document.activeElement.dataset && document.activeElement.dataset.rel;
  $('bib-conta').textContent = bib.obras.length ? (obra ? '' : `${bib.obras.length} obra${bib.obras.length === 1 ? '' : 's'}`) : '';
  $('bib-filtro').closest('.bib-busca').hidden = !!obra || !bib.obras.length;
  if (!bib.obras.length) {
    const v = el('div', 'vazio'); v.append(el('strong', '', 'A biblioteca está vazia'), el('span', '', 'Baixe um capítulo na aba “Baixar imagens”: a obra aparece aqui com a capa e o nome.'));
    v.append(botao('Ir para Baixar imagens', '', () => irPara('baixar')));
    caixa.className = 'linhas'; caixa.replaceChildren(v);
  } else if (obra) {
    caixa.className = 'linhas'; caixa.replaceChildren(desenharObra(obra));
  } else {
    const visiveis = bib.obras.filter((o) => !filtro || norm(o.nome).includes(norm(filtro)));
    caixa.className = visiveis.length ? 'capas' : 'linhas';
    caixa.replaceChildren(...(visiveis.length ? visiveis.map(cartaoObra) : [el('p', 'bib-vazio-filtro', `Nenhuma obra com “${filtro}”.`)]));
  }
  desenharDetalhe();
  if (focoRel) { const b = document.querySelector(`.cap-item[data-rel="${CSS.escape(focoRel)}"]`); if (b) b.focus({preventScroll: true}); }
}
$('bib-filtro').addEventListener('input', () => { filtro = $('bib-filtro').value.trim(); desenhar(); });

async function carregar() {
  try {
    bib = await ler('/api/biblioteca');
    if (obraAberta && !bib.obras.some((o) => o.nome === obraAberta)) obraAberta = null;
    if (escolhido && !achar(escolhido)) escolhido = null;
    desenhar(); carregarObras();
    if (typeof atualizarRefinarBib === 'function' && !tradRodando) atualizarRefinarBib(false);
  } catch (_) {}
}

/* ---- tradução */
async function cancelarCapitulo(rel) {
  await acao('/api/traducao/cancelar-item', {rel}, (x) => (x.onde === 'fila' ? 'Capítulo tirado da fila.' : 'Cancelando este capítulo…'));
  if (typeof sondarTraducao === 'function') sondarTraducao();
}
async function traduzir(alvo) {
  tradLog = 0; $('log-traducao').textContent = '';
  const r = await acao('/api/traduzir', {de: $('trad-de').value, para: $('trad-para').value, ...alvo}, (x) => x.conjuntos ? `Traduzindo ${x.conjuntos} capítulo(s)…` : 'Tradução iniciada.');
  if (r) { sondarTraducao(); document.dispatchEvent(new CustomEvent('traducao-iniciada')); }
}
let andamentoDispensado = '', filaAnterior = '';
async function sondarTraducao() {
  let e;
  try { e = await ler('/api/traducao/estado', '&log=' + tradLog); } catch (_) { return; }
  const dep = e.dependencias || {};
  $('trad-aviso').hidden = !!(dep.ocr && dep.traducao);
  if (e.log && e.log.length) {
    $('log-traducao').textContent += (tradLog ? '\n' : '') + e.log.join('\n');
    $('log-traducao').scrollTop = $('log-traducao').scrollHeight;
    tradLog = e.log_total;
  }
  const rodando = e.estado === 'executando';
  $('trad-pendentes').disabled = rodando;
  if (rodando !== tradRodando || refinarPend < 0) atualizarRefinarBib(rodando);

  // faixa de andamento: só existe enquanto há o que mostrar
  const refinando = rodando && e.fase === 'refino';
  const aviso_ = (e.avisos || []).join(' ');
  const base = rodando
    ? (refinando ? `Refinando com o Hy-MT2… ${e.refino_feitas}/${e.refino_total} capítulo(s)` : `Traduzindo… ${e.feitas}/${e.total || '?'}`) + (e.capitulos > 1 ? ` · ${e.prontos}/${e.capitulos} capítulos prontos para ler` : '')
    : e.estado === 'concluido' ? `Pronto: ${e.resumo.blocos} trecho(s) em ${e.resumo.com_texto} imagem(ns).`
    : e.estado === 'erro' ? (e.erro || 'Erro.') : '';
  const texto = [base, aviso_].filter(Boolean).join(' ');
  const chave = `${e.estado}|${e.inicio}|${e.fim}`;
  const faixa = $('bib-andamento');
  const visivel = !!texto && (rodando || andamentoDispensado !== chave);
  faixa.hidden = !visivel;
  faixa.classList.toggle('erro', !rodando && e.estado === 'erro'); faixa.classList.toggle('ok', !rodando && e.estado === 'concluido');
  $('trad-estado').textContent = texto;
  const chip = $('bib-and-chip');
  chip.className = 'chip ' + (rodando ? 'ativo' : e.estado === 'erro' ? 'erro' : 'ok');
  chip.textContent = rodando ? (e.cancelando ? 'Cancelando…' : refinando ? 'Refinando' : 'Traduzindo') : e.estado === 'erro' ? 'Erro' : 'Concluído';
  const emRefino = (e.itens || []).find((i) => i.refino === 'refinando');
  const frac = refinando ? (e.refino_total ? ((e.refino_feitas || 0) + (emRefino && emRefino.rtotal ? (emRefino.rfeitas || 0) / emRefino.rtotal : 0)) / e.refino_total : 0) : (e.total ? e.feitas / e.total : 0);
  $('bib-and-fill').style.width = Math.round((e.estado === 'concluido' ? 1 : Math.min(1, frac)) * 100) + '%';
  $('trad-cancelar').hidden = !rodando; $('trad-cancelar').disabled = !!e.cancelando;
  $('trad-cancelar').textContent = e.cancelando ? 'Cancelando…' : refinando ? 'Cancelar refinamento' : 'Cancelar tradução';
  $('bib-and-fechar').hidden = rodando; $('bib-and-fechar').dataset.chave = chave;
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
$('bib-and-fechar').addEventListener('click', () => { andamentoDispensado = $('bib-and-fechar').dataset.chave; $('bib-andamento').hidden = true; });
$('bib-log-btn').addEventListener('click', () => {
  const pre = $('log-traducao'); pre.hidden = !pre.hidden; $('bib-log-btn').setAttribute('aria-expanded', String(!pre.hidden));
  if (!pre.hidden) pre.scrollTop = pre.scrollHeight;
});
$('trad-pendentes').addEventListener('click', () => traduzir({lote: 'pendentes'}));

/* ---- motor de tradução e refinamento (mesmos da aba Traduções) */
function desenharMotorBib(cfg) {
  const sel = $('bib-motor');
  if (!sel.options.length) Object.entries(cfg.motores || {}).forEach(([v, r]) => sel.append(new Option(r, v)));
  sel.value = cfg.motor;
  $('bib-tr-resumo').textContent = ({hibrido: 'Híbrido', argos: 'Argos', hy: 'Hy-MT2 A', hy_pagina: 'Hy-MT2 B', gemini: 'Gemini', openrouter: 'OpenRouter'})[cfg.motor] || '';
}
document.addEventListener('motor-mudou', (ev) => desenharMotorBib(ev.detail));
$('bib-motor').addEventListener('change', async () => {
  const v = $('bib-motor').value, st = $('bib-motor-status');
  await Motor.escolher(v);
  st.textContent = v === 'argos' ? '' : 'Verificando…';
  if (v !== 'argos') { const h = await Motor.verificar(v); st.textContent = (h.pronto ? '✔ ' : '✖ ') + h.mensagem; }
});
let refinarPend = -1;
async function atualizarRefinarBib(rodando) {
  const b = $('bib-refinar');
  try { refinarPend = (await ler('/api/refinar/pendentes')).capitulos; } catch (_) {}
  b.disabled = rodando || refinarPend <= 0;
  b.textContent = refinarPend > 0 ? `Refinar ${refinarPend} capítulo${refinarPend > 1 ? 's' : ''} já traduzido${refinarPend > 1 ? 's' : ''}` : 'Refinar capítulos já traduzidos';
}
$('bib-refinar').addEventListener('click', async () => {
  const r = await acao('/api/refinar', {}, (x) => `Refinando ${x.capitulos} capítulo(s) com o Hy-MT2…`);
  if (r) { sondarTraducao(); document.dispatchEvent(new CustomEvent('traducao-iniciada')); }
});
Motor.carregar(); atualizarRefinarBib(false);
$('trad-cancelar').addEventListener('click', () => acao('/api/traducao/cancelar'));
$('excluir-tudo').addEventListener('click', async () => {
  const n = bib.obras.length;
  if (!n) { aviso('A biblioteca já está vazia.'); return; }
  if (!confirm(`ATENÇÃO: isto apaga TODA a biblioteca.\n\nAs ${n} obra(s), todos os capítulos, traduções e capas serão excluídos do disco. Isto não pode ser desfeito.\n\nContinuar?`)) return;
  if ((prompt('Para confirmar, digite APAGAR TUDO (em maiúsculas):') || '').trim() !== 'APAGAR TUDO') { aviso('Nada foi apagado.'); return; }
  const r = await acao('/api/biblioteca/excluir-tudo', {confirmacao: 'APAGAR TUDO'}, (x) => `Biblioteca apagada: ${x.obras} obra(s), ${x.capitulos} capítulo(s).`);
  if (r) { obraAberta = null; escolhido = null; history.replaceState(null, '', urlDaObra(null)); carregar(); }
});
$('abrir-saida').addEventListener('click', () => acao('/api/biblioteca/abrir-pasta', {}));

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
carregar(); vigiar();
irPara(location.hash.slice(1));
