/* Aba "Piloto automático": controles e acompanhamento. Toda a lógica está no servidor; aqui só se mostra o estado e se enviam os comandos. */
let piDados = null, piTimer = null;
const ROTULO_PILOTO = {desativado: 'Desativado', ativo: 'Ativo, aguardando', pausado: 'Pausado', executando: 'Executando'};
const ROTULO_TAREFA = {pendente: 'na fila', executando: 'em andamento', feito: 'concluída', erro: 'falhou', atencao: 'precisa de atenção', cancelada: 'cancelada'};
const ROTULO_TIPO = {baixar: 'Baixar', traduzir: 'Traduzir'};

async function piEnviar(rota, corpo) { try { await chamar('/api/piloto/' + rota, corpo || {}); } catch (e) { aviso(e.message); } carregarPiloto(); }
const piCfg = (parte) => piEnviar('config', parte);

const PI_SELO = {executando: 'ativo', feito: 'ok', erro: 'erro', atencao: 'aviso', cancelada: 'aviso'};
function piLinhaTarefa(t) {
  const l = el('article', 'au-item' + (t.estado === 'executando' ? ' verificando' : '')); l.dataset.cor = corDaObra(t.obra);
  const info = el('div', 'au-info');
  info.append(el('span', 'au-selo ' + (PI_SELO[t.estado] || ''), ROTULO_TAREFA[t.estado] || t.estado), el('span', 'suave', ROTULO_TIPO[t.tipo] + ' cap. ' + t.numero));
  l.append(miniatura(t.obra), el('strong', 'au-nome', t.obra), info);
  if (t.estado === 'erro' || t.estado === 'cancelada') l.append(botaoPequeno('Tentar de novo', () => piEnviar('tentar', {id: t.id})));
  if (t.erro) l.append(el('p', 'au-erro-txt', t.erro));
  return l;
}

function desenharPiloto(d) {
  piDados = d;
  const c = d.config;
  $('pi-chip').textContent = ROTULO_PILOTO[d.estado] || d.estado;
  $('pi-chip').className = 'au-selo ' + ({executando: 'ativo', ativo: 'ok', pausado: 'aviso'}[d.estado] || '');
  $('pi-painel').dataset.estado = d.estado;
  $('pi-ativar-txt').textContent = c.ativo ? 'Desativar piloto' : 'Ativar piloto';
  $('pi-ativar').classList.toggle('principal', !c.ativo);
  $('pi-progresso').hidden = d.estado !== 'executando'; $('pi-estado').classList.toggle('rodando', d.estado === 'executando');
  $('pi-pausar').hidden = !c.ativo; $('pi-pausar').textContent = c.pausado ? 'Retomar' : 'Pausar';
  $('pi-executar').hidden = !c.ativo || c.pausado;
  const ativas = d.tarefas.some((t) => ['pendente', 'executando', 'atencao'].includes(t.estado));
  $('pi-cancelar').hidden = !ativas;
  $('pi-estado').textContent = !c.ativo ? 'O piloto está desligado: nada é verificado, baixado ou traduzido sozinho.'
    : `Última execução: ${d.ultima_execucao ? dataHora(d.ultima_execucao) : 'ainda não'}${d.proxima_execucao && !c.pausado ? ' · próxima: ' + (d.proxima_execucao <= Date.now() + 60000 ? 'em instantes' : dataHora(d.proxima_execucao)) : ''}${!d.manual_livre || !d.traducao_livre ? ' · aguardando o trabalho manual terminar' : ''}`;
  const at = d.atencao.length;
  $('pi-aviso').hidden = !at; $('pi-aviso').textContent = at ? `${at} tarefa(s) precisam da sua atenção (veja a fila abaixo).` : '';
  $('aba-pi-ponto').hidden = !at;
  for (const [id, k] of [['pi-et-verificar', 'verificar'], ['pi-et-baixar', 'baixar'], ['pi-et-traduzir', 'traduzir']]) if (document.activeElement !== $(id)) $(id).checked = c.etapas[k];
  if (document.activeElement !== $('pi-lim-baixar')) $('pi-lim-baixar').value = c.limite_baixar;
  if (document.activeElement !== $('pi-lim-traduzir')) $('pi-lim-traduzir').value = c.limite_traduzir;
  if (document.activeElement !== $('pi-intervalo')) $('pi-intervalo').value = String(c.intervalo_min);
  $('pi-motor').textContent = d.motor === 'web' ? 'Motor “IA na web”: o piloto só prepara os textos; colar a tradução e importar continua com você.' : `Motor de tradução: ${d.motor}.`;
  for (const [id, k] of [['pi-et-verificar', 'verificar'], ['pi-et-baixar', 'baixar'], ['pi-et-traduzir', 'traduzir']]) $(id).closest('.pi-etapa').classList.toggle('ligada', c.etapas[k]);
  $('pi-qtd').textContent = `(${d.obras.filter((o) => o.escolhida).length} de ${d.obras.length} escolhidas)`;
  $('pi-obras').replaceChildren(...d.obras.map((o) => {
    const l = el('article', 'au-item' + (o.escolhida ? '' : ' desligada')), cx = el('input', 'au-sw'); l.dataset.cor = corDaObra(o.nome);
    cx.type = 'checkbox'; cx.checked = o.escolhida; cx.setAttribute('aria-label', 'Acompanhar ' + o.nome);
    cx.addEventListener('change', () => { l.classList.toggle('desligada', !cx.checked); piCfg({obras: [...piDados.obras.filter((x) => x.nome === o.nome ? cx.checked : x.escolhida).map((x) => x.nome)]}); });
    const info = el('div', 'au-info'); info.append(el('span', 'au-selo ' + (o.escolhida ? 'ok' : ''), o.escolhida ? 'acompanhada' : 'não acompanhada'));
    l.append(miniatura(o.nome), el('strong', 'au-nome', o.nome), cx, info); return l;
  }));
  $('pi-fila').replaceChildren(...(d.tarefas.length ? d.tarefas.map(piLinhaTarefa) : [el('p', 'nota', 'Nenhuma tarefa do piloto. Quando houver capítulos para baixar ou traduzir, eles aparecem aqui.')]));
  $('pi-hist').replaceChildren(...(d.historico.length ? d.historico.map((h) => {
    const l = el('div', 'au-evento' + (h.nivel === 'erro' || h.nivel === 'atencao' ? ' erro' : ''));
    const t = el('div', 'au-evento-t'); t.append(el('strong', null, dataHora(h.t)), el('span', 'suave', h.texto));
    l.append(t); if (h.obra) l.append(el('div', 'au-evento-s suave', h.obra)); return l;
  }) : [el('p', 'nota', 'Nenhuma atividade ainda.')]));
}

async function carregarPiloto() {
  try { desenharPiloto(await ler('/api/piloto')); } catch (_) {}
  clearTimeout(piTimer);
  const ativa = !$('pg-piloto').hidden;
  piTimer = setTimeout(carregarPiloto, ativa ? 3000 : 30000);
}
$('pi-ativar').addEventListener('click', () => piCfg({ativo: !piDados.config.ativo}));
$('pi-pausar').addEventListener('click', () => piEnviar('pausar', {pausado: !piDados.config.pausado}));
$('pi-executar').addEventListener('click', () => piEnviar('executar'));
$('pi-cancelar').addEventListener('click', () => { if (confirm('Cancelar as tarefas do piloto? Nada é apagado e o que você iniciou à mão não é tocado.')) piEnviar('cancelar'); });
for (const [id, k] of [['pi-et-verificar', 'verificar'], ['pi-et-baixar', 'baixar'], ['pi-et-traduzir', 'traduzir']]) $(id).addEventListener('change', () => piCfg({etapas: {[k]: $(id).checked}}));
$('pi-lim-baixar').addEventListener('change', () => piCfg({limite_baixar: Number($('pi-lim-baixar').value)}));
$('pi-lim-traduzir').addEventListener('change', () => piCfg({limite_traduzir: Number($('pi-lim-traduzir').value)}));
$('pi-intervalo').addEventListener('change', () => piCfg({intervalo_min: Number($('pi-intervalo').value)}));
document.addEventListener('pagina', (ev) => { if (ev.detail === 'piloto') carregarPiloto(); });
carregarPiloto();