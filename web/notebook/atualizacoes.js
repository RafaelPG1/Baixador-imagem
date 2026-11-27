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

function linhaCapitulo(obra, c) {
  const l = el('div', 'at-cap');
  l.append(el('span', 'num', 'Cap. ' + c.numero));
  if (c.rotulo && c.rotulo.toLowerCase() !== ('chapter ' + c.numero)) l.append(el('span', 'suave', c.rotulo));
  l.append(botaoPequeno('Baixar…', () => levarParaBaixar(obra, c)));
  if (seguro(c.url)) { const a = el('a', null, 'Abrir no site'); a.href = c.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; l.append(a); }
  return l;
}

function cartaoNovos(o) {
  const c = el('div', 'at-obra');
  const cab = el('div', 'at-obra-cab');
  cab.append(el('strong', null, o.nome), el('span', 'chip ok', o.novos.length === 1 ? '1 capítulo novo' : o.novos.length + ' capítulos novos'),
             el('span', 'suave', 'verificada em ' + dataHora(o.t)),
             botaoPequeno('Dispensar aviso', async () => { try { await chamar('/api/verificacao/dispensar', {obra: o.nome}); carregarAtualizacoes(); } catch (e) { aviso(e.message); } }));
  const lista = el('div', 'at-caps'); o.novos.forEach((n) => lista.append(linhaCapitulo(o.nome, n)));
  c.append(cab, lista);
  if (o.fora_total > o.novos.length) {
    const d = el('details'); d.append(el('summary', 'suave', `Todos os ${o.fora_total} capítulos do site que ainda não estão na biblioteca`));
    const todos = el('div', 'at-caps'); o.fora.forEach((n) => todos.append(linhaCapitulo(o.nome, n))); d.append(todos); c.append(d);
  }
  return c;
}

function linhaObra(o) {
  const l = el('div', 'at-linha');
  const cx = el('input'); cx.type = 'checkbox'; cx.checked = o.ligada; cx.setAttribute('aria-label', 'Verificar ' + o.nome);
  cx.addEventListener('change', async () => {
    const desligadas = atDados.obras.filter((x) => !(x.nome === o.nome ? cx.checked : x.ligada)).map((x) => x.nome);
    try { await chamar('/api/verificacao/config', {desligadas}); o.ligada = cx.checked; } catch (e) { aviso(e.message); cx.checked = !cx.checked; }
  });
  const status = el('span', o.status === 'ok' || o.status === 'nunca' ? 'suave' : 'suave at-erro', ROTULO_STATUS[o.status] || o.status);
  if (o.erro) status.title = o.erro;
  l.append(cx, el('span', 'nome', o.nome), status,
           el('span', 'suave', o.t ? dataHora(o.t) : ''),
           el('span', 'suave', o.total_site ? `${o.total_site} no site · ${o.fora_total} fora da biblioteca` : ''),
           botaoPequeno('Verificar só esta', () => iniciarVerificacao([o.nome])));
  if (o.erro && o.status !== 'ok') l.append(el('span', 'suave at-erro', o.erro));
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
  $('at-verificar').disabled = rodando;
  $('at-verificar').textContent = rodando ? 'Verificando…' : 'Verificar agora';
  $('at-estado').textContent = rodando ? `Verificando ${d.andamento.feitas || 0} de ${d.andamento.total || 0}${d.andamento.obra ? ': ' + d.andamento.obra : ''}` : `Última verificação: ${dataHora(d.ultima)}`;
  const comNovos = d.obras.filter((o) => o.novos.length);
  $('aba-at-ponto').hidden = !comNovos.length;
  $('at-novos').replaceChildren(...(comNovos.length ? [el('div', 'secao-cab'), ...comNovos.map(cartaoNovos)] : []));
  if (comNovos.length) $('at-novos').firstChild.append(el('h2', null, 'Obras com capítulos novos'), el('span', 'suave', comNovos.length + ' obra(s)'));
  $('at-vazio').hidden = !!comNovos.length || rodando;
  $('at-qtd').textContent = `(${d.obras.filter((o) => o.ligada).length} de ${d.obras.length} ligadas)`;
  $('at-obras').replaceChildren(...d.obras.map(linhaObra));
  $('at-hist').replaceChildren(...(d.historico.length ? d.historico.map((h) => {
    const l = el('div', 'at-linha');
    l.append(el('span', 'nome', dataHora(h.t)), el('span', null, `${h.verificadas} obra(s)`), el('span', h.novos ? 'chip ok' : 'suave', h.novos ? `${h.novos} novo(s)` : 'sem novidades'),
             el('span', h.erros ? 'at-erro' : 'suave', h.erros ? `${h.erros} com problema` : ''), el('span', 'suave', `${h.segundos}s`));
    if (h.obras && h.obras.length) l.append(el('span', 'suave', h.obras.map((o) => `${o.nome} (${o.novos})`).join(', ')));
    return l;
  }) : [el('span', 'suave', 'Nenhuma verificação ainda.')]));
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