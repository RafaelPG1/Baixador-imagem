/* Aba "Atualizações": mostra o que a verificação achou. Só descobre: baixar é uma decisão da pessoa (leva o capítulo para a aba Baixar). */
let atDados = null, atTimer = null;
const dataHora = (t) => t ? new Date(t).toLocaleString('pt-BR', {dateStyle: 'short', timeStyle: 'short'}) : 'nunca';
const ROTULO_STATUS = {ok: 'verificada', erro: 'erro', sem_lista: 'sem lista', sem_url: 'sem endereço', adiada: 'adiada', nunca: 'ainda não verificada'};
const seguro = (u) => /^https?:\/\//i.test(u || '');

function el(tag, classe, texto) { const e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; }
function botaoPequeno(texto, aoClicar, classe = 'btn pequeno') { const b = el('button', classe, texto); b.type = 'button'; b.addEventListener('click', aoClicar); return b; }

function levarParaBaixar(obra, c) {                       // só preenche o formulário da aba Baixar: quem baixa é a pessoa
  $('url').value = c.url; $('url').dispatchEvent(new Event('input', {bubbles: true}));
  $('obra').value = obra; $('obra').dispatchEvent(new Event('input', {bubbles: true}));
  $('cap-num').value = c.numero; $('cap-num').dispatchEvent(new Event('input', {bubbles: true}));
  irPara('baixar'); $('url').focus();
}

const CLASSE_STATUS = {ok: 'ok', erro: 'erro', sem_lista: 'aviso', sem_url: 'aviso', adiada: 'aviso', nunca: ''};
const SVG_LINK = '<svg class="au-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';
// cor e capa vêm da Biblioteca (variável `bib` de biblioteca.js), para a obra ter a mesma cara nas duas abas
const obraDaBiblioteca = (nome) => (typeof bib !== 'undefined' && bib.obras.find((x) => x.nome === nome)) || null;
function corDaObra(nome) {
  const b = obraDaBiblioteca(nome); if (b) return String(b.cor);
  let h = 0; for (const ch of nome) h = (h * 31 + ch.charCodeAt(0)) % 6;
  return String(h);
}
function miniatura(nome) {
  const m = el('span', 'au-capa'), b = obraDaBiblioteca(nome);
  const inicial = () => m.replaceChildren(el('span', null, (nome.trim()[0] || '?').toUpperCase()));
  if (b && b.capa && typeof urlCapa === 'function') { const f = el('img'); f.alt = ''; f.loading = 'lazy'; f.decoding = 'async'; f.src = urlCapa(b); f.addEventListener('error', inicial); m.append(f); } else inicial();
  return m;
}

function linhaCapitulo(obra, c) {
  const l = el('div', 'au-cap');
  l.append(el('span', 'num', 'Cap. ' + c.numero));
  if (c.rotulo && c.rotulo.toLowerCase() !== ('chapter ' + c.numero)) l.append(el('span', 'suave', c.rotulo));
  const acoes = el('div', 'au-cap-acoes');
  if (seguro(c.url)) { const a = el('a', 'au-link'); a.innerHTML = SVG_LINK; a.append(el('span', null, 'Abrir no site')); a.href = c.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; acoes.append(a); }
  acoes.append(botaoPequeno('Baixar…', () => levarParaBaixar(obra, c), 'btn pequeno principal'));
  l.append(acoes);
  return l;
}

function cartaoNovos(o) {
  const c = el('article', 'au-novo'); c.dataset.cor = corDaObra(o.nome);
  const cab = el('div', 'au-novo-cab'), quem = el('div', 'au-quem');
  quem.append(el('strong', null, o.nome), el('span', 'suave', 'verificada em ' + dataHora(o.t)));
  cab.append(miniatura(o.nome), quem, el('span', 'chip ok', o.novos.length === 1 ? '1 capítulo novo' : o.novos.length + ' capítulos novos'),
             botaoPequeno('Dispensar aviso', async () => { try { await chamar('/api/verificacao/dispensar', {obra: o.nome}); carregarAtualizacoes(); } catch (e) { aviso(e.message); } }));
  const lista = el('div', 'au-caps'); o.novos.forEach((n) => lista.append(linhaCapitulo(o.nome, n)));
  c.append(cab, lista);
  if (o.fora_total > o.novos.length) {
    const d = el('details', 'au-mais'); d.append(el('summary', 'suave', `Todos os ${o.fora_total} capítulos do site que ainda não estão na biblioteca`));
    const todos = el('div', 'au-caps'); o.fora.forEach((n) => todos.append(linhaCapitulo(o.nome, n))); d.append(todos); c.append(d);
  }
  return c;
}

function linhaObra(o) {
  const a = atDados && atDados.andamento, verificando = !!(a && a.rodando && a.obra === o.nome);
  const l = el('article', 'au-item' + (o.ligada ? '' : ' desligada') + (verificando ? ' verificando' : '')); l.dataset.cor = corDaObra(o.nome);
  const cx = el('input', 'au-sw'); cx.type = 'checkbox'; cx.checked = o.ligada; cx.setAttribute('aria-label', 'Verificar ' + o.nome); cx.title = 'Incluir esta obra nas verificações';
  cx.addEventListener('change', async () => {
    const desligadas = atDados.obras.filter((x) => !(x.nome === o.nome ? cx.checked : x.ligada)).map((x) => x.nome);
    try { await chamar('/api/verificacao/config', {desligadas}); o.ligada = cx.checked; l.classList.toggle('desligada', !o.ligada); } catch (e) { aviso(e.message); cx.checked = !cx.checked; }
  });
  const selo = el('span', 'au-selo ' + (verificando ? 'ativo' : CLASSE_STATUS[o.status] || ''), verificando ? 'verificando…' : (ROTULO_STATUS[o.status] || o.status));
  if (o.erro) selo.title = o.erro;
  const meta = [o.t ? dataHora(o.t) : '', o.total_site ? `${o.total_site} no site · ${o.fora_total} fora da biblioteca` : ''].filter(Boolean).join(' · ');
  const info = el('div', 'au-info'); info.append(selo); if (meta) info.append(el('span', 'suave', meta));
  l.append(miniatura(o.nome), el('strong', 'au-nome', o.nome), cx, info, botaoPequeno('Verificar só esta', () => iniciarVerificacao([o.nome])));
  if (o.erro && o.status !== 'ok') l.append(el('p', 'au-erro-txt', o.erro));
  return l;
}

function notificar(d) {                                  // avisa uma vez por verificação com novidades (toast sempre; aviso do navegador se a pessoa permitiu)
  const ultima = d.historico[0];
  let visto = Number(localStorage.getItem('at-visto'));
  if (!visto) { visto = Date.now(); localStorage.setItem('at-visto', String(visto)); }
  const novas = d.historico.filter((h) => h.t > visto && h.novos > 0);
  if (!novas.length) return;
  localStorage.setItem('at-visto', String(ultima.t));
  const total = novas.reduce((s, h) => s + h.novos, 0), nomes = [...new Set(novas.flatMap((h) => h.obras.map((o) => o.nome)))];
  const texto = `${total} capítulo(s) novo(s) em ${nomes.length} obra(s): ${nomes.slice(0, 3).join(', ')}${nomes.length > 3 ? '…' : ''}`;
  aviso(texto);
  if ($('at-notificar').checked && 'Notification' in window && Notification.permission === 'granted') { try { new Notification('Capítulos novos', {body: texto}); } catch (_) {} }
}

function desenharAtualizacoes(d) {
  atDados = d;
  if (document.activeElement !== $('at-periodica')) $('at-periodica').checked = d.config.periodica;
  if (document.activeElement !== $('at-intervalo')) $('at-intervalo').value = String(d.config.intervalo_h);
  const rodando = !!(d.andamento && d.andamento.rodando);
  $('at-verificar').disabled = rodando; $('at-verificar').classList.toggle('rodando', rodando);
  $('at-verificar-txt').textContent = rodando ? 'Verificando…' : 'Verificar agora';
  const pct = rodando && d.andamento.total ? Math.round((d.andamento.feitas || 0) / d.andamento.total * 100) : 0;
  $('at-progresso').hidden = !rodando; $('at-prog-barra').style.width = Math.max(4, pct) + '%'; $('at-estado').classList.toggle('rodando', rodando);
  $('at-estado').textContent = rodando ? `Verificando ${d.andamento.feitas || 0} de ${d.andamento.total || 0}${d.andamento.obra ? ': ' + d.andamento.obra : ''}` : `Última verificação: ${dataHora(d.ultima)}`;
  const comNovos = d.obras.filter((o) => o.novos.length);
  $('aba-at-ponto').hidden = !comNovos.length;
  const cabNovos = el('div', 'au-cab'); cabNovos.append(el('h2', null, 'Obras com capítulos novos'), el('span', 'chip ok', comNovos.length + ' obra(s)'));
  $('at-novos').replaceChildren(...(comNovos.length ? [cabNovos, ...comNovos.map(cartaoNovos)] : []));
  $('at-vazio').hidden = !!comNovos.length || rodando;
  $('at-qtd').textContent = `(${d.obras.filter((o) => o.ligada).length} de ${d.obras.length} ligadas)`;
  $('at-obras').replaceChildren(...d.obras.map(linhaObra));
  $('at-hist').replaceChildren(...(d.historico.length ? d.historico.map((h) => {
    const l = el('div', 'au-evento' + (h.erros ? ' erro' : h.novos ? ' ok' : ''));
    const t = el('div', 'au-evento-t'); t.append(el('strong', null, dataHora(h.t)), el('span', h.novos ? 'chip ok' : 'suave', h.novos ? `${h.novos} novo(s)` : 'sem novidades'));
    if (h.erros) t.append(el('span', 'chip erro', `${h.erros} com problema`));
    const obras = h.obras && h.obras.length ? h.obras.map((o) => `${o.nome} (${o.novos})`).join(', ') : '';
    l.append(t, el('div', 'au-evento-s suave', [`${h.verificadas} obra(s)`, `${h.segundos}s`, obras].filter(Boolean).join(' · ')));
    return l;
  }) : [el('p', 'nota', 'Nenhuma verificação ainda.')]));
  notificar(d);
}

async function carregarAtualizacoes() {
  try { desenharAtualizacoes(await ler('/api/verificacao')); } catch (_) {}
  clearTimeout(atTimer);
  const ativa = !$('pg-atualizacoes').hidden, rodando = atDados && atDados.andamento && atDados.andamento.rodando;
  atTimer = setTimeout(carregarAtualizacoes, rodando ? 2000 : ativa ? 15000 : 60000);   // acompanha de perto só quando há verificação rodando
}
async function iniciarVerificacao(obras) {
  try { await chamar('/api/verificacao/iniciar', obras ? {obras, forcar: true} : {forcar: true}); } catch (e) { aviso(e.message); }
  carregarAtualizacoes();
}
$('at-verificar').addEventListener('click', () => iniciarVerificacao(null));
$('at-periodica').addEventListener('change', async () => { try { await chamar('/api/verificacao/config', {periodica: $('at-periodica').checked}); aviso($('at-periodica').checked ? 'Verificação periódica ligada.' : 'Verificação periódica desligada.'); } catch (e) { aviso(e.message); } });
$('at-intervalo').addEventListener('change', async () => { try { await chamar('/api/verificacao/config', {intervalo_h: Number($('at-intervalo').value)}); } catch (e) { aviso(e.message); } });
$('at-notificar').checked = localStorage.getItem('at-notificar') === '1' && 'Notification' in window && Notification.permission === 'granted';
$('at-notificar').addEventListener('change', async () => {
  if ($('at-notificar').checked && 'Notification' in window && Notification.permission !== 'granted') {
    if (await Notification.requestPermission() !== 'granted') { $('at-notificar').checked = false; aviso('O navegador não permitiu avisos.'); }
  }
  localStorage.setItem('at-notificar', $('at-notificar').checked ? '1' : '0');
});
document.addEventListener('pagina', (ev) => { if (ev.detail === 'atualizacoes') carregarAtualizacoes(); });
carregarAtualizacoes();