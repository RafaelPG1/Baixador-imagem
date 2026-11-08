/* Aba "Baixar imagens": abrir o site, procurar, escolher e baixar (manual ou automático). */
let modo = 'manual', pastaEditada = false;
let estadoManual = 'ocioso', salvandoManual = false, automaticoAtivo = false, ultimoAviso = '';

function mensagem(texto, ok = false) {
  $('mensagem').textContent = texto || '';
  $('mensagem').className = 'msg' + (ok ? ' ok' : '');
  $('mensagem-busca').textContent = ok ? '' : (texto || '');
}
function nomeDe(url) {
  if (url.startsWith('(')) return 'imagem embutida';
  try {
    const p = decodeURIComponent(new URL(url).pathname.split('/').filter(Boolean).pop() || '');
    return p || new URL(url).hostname;
  } catch (_) { return url.slice(0, 40); }
}

/* ---- navegador */
async function carregarNavegadores() {
  try {
    const j = await ler('/api/navegadores');
    j.opcoes.forEach((o) => {
      const op = document.createElement('option');
      op.value = o.id;
      op.textContent = o.nome + (o.encontrado === true ? ' (encontrado)' : o.encontrado === false ? ' (não encontrado)' : '');
      $('navegador').append(op);
    });
    $('navegador').value = j.padrao;
  } catch (_) {}
  atualizarCaminho();
}
function atualizarCaminho() { $('campo-caminho').hidden = $('navegador').value !== 'outro'; }
$('navegador').addEventListener('change', atualizarCaminho);

/* ---- modo */
/* "Atualizar obra": só aparece com "Continuar…" e "Traduzir…" desligadas; ligada, bloqueia as duas (uma só rotina por vez). */
function opcaoAtualizar() {
  const ligado = $('atualizar-auto').checked, outras = $('continuar-auto').checked || $('traduzir-auto').checked;
  $('opcao-atualizar').hidden = outras && !ligado;
  $('nota-atualizar').hidden = !ligado;
  $('continuar-auto').disabled = $('traduzir-auto').disabled = ligado;
}
function aplicarModo() {
  const manual = modo === 'manual';
  $('opcoes-continuar').hidden = manual;
  opcaoAtualizar();
  $('iniciar').textContent = manual ? 'Abrir site no navegador' : 'Baixar tudo automaticamente';
  atualizarBotoes();
}
document.querySelectorAll('input[name=modo]').forEach((r) => r.addEventListener('change', () => { modo = r.value; mensagem(''); aplicarModo(); }));

function atualizarBotoes() {
  const ativo = ['abrindo', 'aguardando', 'procurando'].includes(estadoManual);
  document.querySelectorAll('input[name=modo]').forEach((r) => { r.disabled = ativo; });
  $('iniciar').disabled = ativo;
  $('fechar-nav').disabled = !ativo;
  $('procurar').disabled = estadoManual !== 'aguardando' || automaticoAtivo;
  $('cancelar-busca').disabled = estadoManual !== 'procurando';
  $('proximo-cap').disabled = estadoManual !== 'aguardando' || automaticoAtivo;
  atualizarSelecao();
}

/* ---- imagens encontradas */
let exM = -1, logM = 0, cvM = -1;
const selecionadas = new Set(), vistos = new Set(), elementos = new Map();
let itensManual = [];

const INSTRUCOES = {
  ocioso: 'Informe o endereço e clique em “Abrir site no navegador”. Uma janela do navegador escolhido vai abrir.',
  abrindo: 'Abrindo o navegador…',
  aguardando: 'Navegador aberto. Faça o que for preciso nele (entrar na conta, esperar o conteúdo carregar) e clique em “Procurar imagens na página”. Dá para procurar de novo depois de trocar de página: as novas imagens são somadas à lista.',
  procurando: 'Procurando imagens… Para interromper, use “Cancelar busca”.',
  fechado: 'O navegador foi fechado. A lista continua aqui e você ainda pode baixar as marcadas.',
  erro: 'Não foi possível continuar.',
};
const ROTULOS = {ocioso: 'Pronto', abrindo: 'Abrindo…', aguardando: 'Aguardando você', procurando: 'Procurando…', fechado: 'Navegador fechado', erro: 'Erro'};
const CLASSES = {abrindo: 'ativo', procurando: 'ativo', aguardando: 'espera', erro: 'erro'};

function etiqueta(leg, texto, ok, dica) {
  const t = document.createElement('span');
  t.className = 'etiqueta' + (ok ? ' ok' : ''); t.textContent = texto; if (dica) t.title = dica;
  leg.append(t);
}
function legendaItem(fig, i) {
  const leg = fig.querySelector('figcaption');
  leg.replaceChildren();
  leg.append(document.createTextNode(`${nomeDe(i.url)} · ${i.largura}×${i.altura} · ${Math.max(1, Math.round(i.bytes / 1024))} KB`));
  if (i.origem === 'sequencia') etiqueta(leg, 'sequência');
  if (i.origem === 'print') etiqueta(leg, 'print');
  if (i.variante_de) etiqueta(leg, 'versão menor', false, 'Mesmo arquivo de outra imagem da lista, em tamanho menor (desmarcada por padrão)');
  if (i.salva) etiqueta(leg, 'salva', true);
}

function criarFigura(i) {
  const fig = document.createElement('figure');
  fig.className = 'mini';
  const rotulo = document.createElement('label'); rotulo.className = 'marca-img';
  const caixa = document.createElement('input'); caixa.type = 'checkbox';
  caixa.setAttribute('aria-label', 'Marcar ' + nomeDe(i.url));
  caixa.addEventListener('change', () => { if (caixa.checked) selecionadas.add(i.id); else selecionadas.delete(i.id); atualizarSelecao(); });
  rotulo.append(caixa);
  const botao = document.createElement('button'); botao.type = 'button'; botao.className = 'ampliar'; botao.title = 'Ampliar';
  const img = document.createElement('img'); img.loading = 'lazy'; img.alt = nomeDe(i.url); img.src = rota('/api/manual/imagem/' + i.id);
  botao.append(img);
  botao.addEventListener('click', () => ampliar(img.src, img.alt));
  const abaixo = document.createElement('button'); abaixo.type = 'button'; abaixo.className = 'abaixo'; abaixo.textContent = 'Desmarcar daqui para baixo';
  abaixo.addEventListener('click', () => {
    let a_partir = false;
    for (const f of $('galeria-manual').children) {
      if (f === fig) a_partir = true;
      if (a_partir) { const c = f.querySelector('input[type=checkbox]'); if (c) c.checked = false; }
    }
    for (const [id, f] of elementos) { const c = f.querySelector('input[type=checkbox]'); if (c && !c.checked) selecionadas.delete(id); }
    atualizarSelecao();
  });
  const leg = document.createElement('figcaption');
  fig.append(rotulo, botao, leg, abaixo);
  return fig;
}

function sincronizarGaleria(itens) {
  itensManual = itens;
  const comDados = itens.filter((i) => !i.erro && i.bytes > 0);
  const presentes = new Set(comDados.map((i) => i.id));
  for (const [id, fig] of elementos) if (!presentes.has(id)) { fig.remove(); elementos.delete(id); selecionadas.delete(id); }
  comDados.forEach((i) => {
    let fig = elementos.get(i.id);
    if (!fig) {
      fig = criarFigura(i); elementos.set(i.id, fig); $('galeria-manual').append(fig);
      if (!vistos.has(i.id)) { vistos.add(i.id); if (!i.salva && !i.variante_de) selecionadas.add(i.id); }
    }
    legendaItem(fig, i);
    if (i.salva) selecionadas.delete(i.id);
    fig.querySelector('input').disabled = !!i.salva;
    fig.classList.toggle('salva', !!i.salva);
  });
  const desejada = comDados.map((i) => elementos.get(i.id));
  const atual = [...$('galeria-manual').children];
  if (desejada.length !== atual.length || desejada.some((f, k) => f !== atual[k])) $('galeria-manual').append(...desejada);

  const falhas = itens.filter((i) => i.erro);
  $('falhas-manual').hidden = falhas.length === 0;
  $('falhas-titulo').textContent = `${falhas.length} imagem(ns) sem acesso (veja o motivo)`;
  $('lista-falhas').replaceChildren();
  falhas.forEach((f) => { const li = document.createElement('li'); li.textContent = `${f.url} — ${f.erro}`; $('lista-falhas').append(li); });
  $('vazio-manual').hidden = comDados.length > 0;
  $('contagem-manual').textContent = comDados.length ? `(${comDados.length})` : '';
  $('abrir-pasta-manual').hidden = !comDados.some((i) => i.salva);
  $('abrir-leitor-manual').hidden = $('abrir-pasta-manual').hidden;
  atualizarSelecao();
}

function atualizarSelecao() {
  const pendentes = [...selecionadas].filter((id) => { const i = itensManual.find((x) => x.id === id); return i && !i.salva && !i.erro; });
  elementos.forEach((fig, id) => {
    const marcada = selecionadas.has(id);
    fig.classList.toggle('marcada', marcada);
    const caixa = fig.querySelector('input');
    if (caixa.checked !== marcada) caixa.checked = marcada;
  });
  const total = elementos.size;
  $('contagem-marcadas').textContent = total ? `${pendentes.length} marcada(s) de ${total}` : '';
  $('baixar-marcadas').textContent = pendentes.length ? `Baixar marcadas (${pendentes.length})` : 'Baixar marcadas';
  $('baixar-marcadas').disabled = pendentes.length === 0 || salvandoManual || automaticoAtivo;
  $('limpar-lista').disabled = total === 0 && itensManual.length === 0;
  $('marcar-tudo').disabled = $('marcar-nada').disabled = total === 0;
}

function aplicarManual(e) {
  if (e.reiniciar) {
    exM = e.execucao; logM = 0; cvM = -1;
    $('log-manual').textContent = ''; $('galeria-manual').replaceChildren();
    elementos.clear(); selecionadas.clear(); vistos.clear(); itensManual = [];
  }
  anexarLog($('log-manual'), e.log);
  logM = e.log_total;
  estadoManual = e.estado; salvandoManual = e.salvando; automaticoAtivo = !!e.automatico;
  if (automaticoAtivo && typeof e.continuar === 'boolean' && $('continuar-auto').checked !== e.continuar) $('continuar-auto').checked = e.continuar;
  if (e.aviso && e.aviso !== ultimoAviso) { ultimoAviso = e.aviso; mensagem(e.aviso); } else if (!e.aviso) ultimoAviso = '';
  if (navegadorAtivo() && e.pagina && e.pagina.url && (e.pagina.titulo !== paginaAtual.titulo || e.pagina.url !== paginaAtual.url)) {
    paginaAtual = e.pagina; urlLida = e.pagina.url; detectarCapitulo(e.pagina.titulo, e.pagina.url);
  }
  if (!navegadorAtivo() && paginaAtual.titulo) paginaAtual = {titulo: '', url: ''};   // sem navegador não há aba: nada da sessão anterior
  if (e.itens !== null) { sincronizarGaleria(e.itens); cvM = e.versao; }
  $('instrucao').textContent = e.estado === 'erro' && e.erro ? e.erro
    : (automaticoAtivo ? 'Modo automático em andamento: o programa abre, procura, baixa e fecha o navegador sozinho. Não precisa clicar em nada.' : INSTRUCOES[e.estado]);
  $('estado').className = 'chip ' + (CLASSES[e.estado] || '');
  $('estado').textContent = ROTULOS[e.estado] || e.estado;
  atualizarBotoes();
}

$('marcar-tudo').addEventListener('click', () => { itensManual.forEach((i) => { if (!i.erro && i.bytes > 0 && !i.salva) selecionadas.add(i.id); }); atualizarSelecao(); });
$('marcar-nada').addEventListener('click', () => { selecionadas.clear(); atualizarSelecao(); });
$('limpar-lista').addEventListener('click', async () => { try { await chamar('/api/manual/limpar'); selecionadas.clear(); } catch (e) { mensagem(e.message); } });
function notaTraduzir() { $('nota-traduzir').hidden = !($('traduzir-auto').checked && !$('continuar-auto').checked); }
$('traduzir-auto').addEventListener('change', () => { notaTraduzir(); opcaoAtualizar(); });
$('atualizar-auto').addEventListener('change', opcaoAtualizar);
$('continuar-auto').addEventListener('change', async () => {
  $('nota-continuar').hidden = !$('continuar-auto').checked;
  notaTraduzir(); opcaoAtualizar();
  if (!automaticoAtivo) return;                       // com o automático rodando, vale na hora (no fim do capítulo atual)
  try { await chamar('/api/manual/continuar', {ativo: $('continuar-auto').checked}); } catch (e) { mensagem(e.message); }
});
$('procurar').addEventListener('click', async () => {
  mensagem(''); $('procurar').disabled = true;
  try { await chamar('/api/manual/procurar', {modo: $('modo-busca').value, espera: Number($('espera').value || 30), ignorar_comentarios: $('sem-comentarios').checked}); }
  catch (e) { mensagem(e.message); }
  atualizarJa();
});
$('proximo-cap').addEventListener('click', async () => {
  mensagem('');
  if (itensManual.length && !confirm('Passar para o próximo capítulo zera a lista de imagens encontradas (o que não foi baixado se perde). Continuar?')) return;
  $('proximo-cap').disabled = true;
  try { await chamar('/api/manual/proximo'); } catch (e) { mensagem(e.message); }
  atualizarJa();
});
$('cancelar-busca').addEventListener('click', async () => { try { await chamar('/api/manual/cancelar'); } catch (e) { mensagem(e.message); } });
$('limpar-tudo').addEventListener('click', async () => {
  mensagem('');
  const ativo = ['abrindo', 'aguardando', 'procurando'].includes(estadoManual);
  const naoSalvas = itensManual.filter((i) => !i.salva && !i.erro).length;
  const aviso1 = (naoSalvas ? `Há ${naoSalvas} imagem(ns) encontrada(s) que ainda não foi(ram) salva(s): serão descartadas. ` : '')
    + (ativo ? 'O navegador aberto será fechado. ' : '') + 'O que já está salvo na biblioteca não é apagado.';
  if ((naoSalvas || ativo) && !confirm(`Limpar tudo?\n\n${aviso1}`)) return;
  $('limpar-tudo').disabled = true;
  try {
    if (ativo) {
      await chamar('/api/manual/fechar');
      for (let k = 0; k < 40; k++) { await new Promise((r) => setTimeout(r, 250)); aplicarManual(await ler('/api/manual/estado', `&ex=${exM}&log=${logM}&cv=${cvM}`)); if (!['abrindo', 'aguardando', 'procurando'].includes(estadoManual)) break; }
    }
    await chamar('/api/manual/limpar-tudo');
    clearTimeout(window.__atrasoUrl); sequenciaDeteccao++;       // leitura pendente do endereço antigo não pode repovoar os campos
    $('url').value = ''; $('obra').value = ''; $('cap-num').value = ''; $('cap-titulo').value = ''; $('cap-previa').textContent = ''; $('obra-aviso').hidden = true;
    editado.obra = editado.num = editado.titulo = false; paginaAtual = {titulo: '', url: ''}; urlDoCapitulo = ''; urlLida = '';
    selecionadas.clear(); ultimoAviso = '';
    aviso('Tudo limpo. Informe o novo endereço.');
  } catch (e) { mensagem(e.message); }
  $('limpar-tudo').disabled = false;
  atualizarJa();
});
$('fechar-nav').addEventListener('click', async () => { try { await chamar('/api/manual/fechar'); } catch (e) { mensagem(e.message); } });

$('baixar-marcadas').addEventListener('click', async () => {
  mensagem('');
  const pasta = $('pasta').value.trim();
  if (!pasta) { mensagem('Informe a pasta de destino.'); $('pasta').focus(); return; }
  const ids = [...selecionadas].filter((id) => { const i = itensManual.find((x) => x.id === id); return i && !i.salva && !i.erro; });
  $('baixar-marcadas').disabled = true;
  try {
    if (obraInformada() && !$('cap-num').value.trim() && !$('cap-titulo').value.trim()) {
      mensagem('Informe o número do capítulo (ou o nome dele) para guardar na obra “' + $('obra').value.trim() + '”.'); $('cap-num').focus();
      atualizarSelecao(); return;
    }
    const r = await chamar('/api/manual/baixar', {indices: ids, pasta, ...dadosCapitulo(), meta: {...dadosCapitulo(), url: paginaAtual.url || ''}});
    ids.forEach((id) => selecionadas.delete(id));
    mensagem(`${r.salvos.length} imagem(ns) salva(s)` + (r.falhas.length ? `; ${r.falhas.length} não puderam ser salvas (veja o andamento).` : '.'), r.falhas.length === 0);
  } catch (e) { mensagem(e.message); }
  atualizarSelecao();
});
$('abrir-leitor-manual').addEventListener('click', async () => { try { await chamar('/api/manual/abrir-leitor'); } catch (e) { mensagem(e.message); } });
$('abrir-pasta-manual').addEventListener('click', async () => { try { await chamar('/api/manual/abrir-pasta'); } catch (e) { mensagem(e.message); } });

/* ---- obra e capítulo: preenchidos pela aba do site (ou pelo link) e corrigíveis à mão */
const editado = {obra: false, num: false, titulo: false};
let paginaAtual = {titulo: '', url: ''}, urlDoCapitulo = '', atrasoPrevia = null;
const obraInformada = () => $('obra').value.trim() !== '';
function dadosCapitulo() { return {obra: $('obra').value.trim(), numero: $('cap-num').value.trim(), titulo: $('cap-titulo').value.trim()}; }
function atualizarPrevia() {
  clearTimeout(atrasoPrevia);
  atrasoPrevia = setTimeout(async () => {
    const d = dadosCapitulo();
    if (!d.obra && !d.numero && !d.titulo) { $('cap-previa').textContent = ''; return; }
    try {
      const url = paginaAtual.url || $('url').value.trim();
      const j = await ler('/api/capitulo/previa', '&obra=' + encodeURIComponent(d.obra) + '&numero=' + encodeURIComponent(d.numero) + '&titulo=' + encodeURIComponent(d.titulo)
        + '&pasta=' + encodeURIComponent($('pasta').value) + '&url=' + encodeURIComponent(url));
      const jaSalvo = itensManual.some((i) => i.salva);                       // salvando em partes o mesmo capítulo é normal
      const atualizando = automaticoAtivo && $('continuar-auto').checked;      // modo automático com continuação: o capítulo salvo é pulado, não bloqueado
      $('cap-previa').textContent = j.existe && !jaSalvo && atualizando ? `Este capítulo já está na biblioteca (${j.existe}); o modo automático vai pulá-lo e passar para o próximo.`
        : j.existe && !jaSalvo ? `Este capítulo já existe na biblioteca (${j.existe}). O download será bloqueado para não duplicar.`
        : j.sem_numero ? 'Falta o número do capítulo.' : 'Será guardado em: ' + (j.rel || '—');
      $('cap-previa').classList.toggle('erro', !!(j.existe && !jaSalvo && !atualizando));
    } catch (_) {}
  }, 250);
}
function mostrarAvisoObra(d) {
  const caixa = $('obra-aviso'); caixa.replaceChildren();
  if (d.candidatas && d.candidatas.length > 1) {
    caixa.append('Esta obra pode ser uma destas. Escolha qual é: ');
    [...d.candidatas, null].forEach((nome) => {
      const b = document.createElement('button'); b.type = 'button'; b.className = 'btn pequeno'; b.textContent = nome || 'É uma obra nova';
      b.addEventListener('click', () => { if (nome) { $('obra').value = nome; editado.obra = true; } caixa.hidden = true; atualizarPrevia(); });
      caixa.append(b, ' ');
    });
    caixa.hidden = false;
  } else if (d.existente && d.motivo_obra) { caixa.textContent = `${d.motivo_obra} Selecionada: “${d.obra}”. Corrija no campo Obra se não for essa.`; caixa.hidden = false; }
  else caixa.hidden = true;
}
let sequenciaDeteccao = 0, urlLida = '';        // urlLida: último endereço digitado/aberto cujos dados estão nos campos
const navegadorAtivo = () => ['abrindo', 'aguardando', 'procurando'].includes(estadoManual);
const normalizarUrl = (v) => { v = (v || '').trim(); return !v ? '' : /^[a-z]+:\/\//i.test(v) ? v : 'https://' + v; };
// Endereço novo = capítulo novo: nada do endereço anterior (campos, avisos, prévia, página lida) sobrevive.
function reiniciarDadosDoCapitulo() {
  sequenciaDeteccao++;                                       // respostas pendentes do endereço antigo são descartadas
  editado.obra = editado.num = editado.titulo = false; urlDoCapitulo = ''; urlLida = '';
  $('obra').value = ''; $('cap-num').value = ''; $('cap-titulo').value = ''; $('cap-previa').textContent = ''; $('obra-aviso').hidden = true;
}
async function detectarCapitulo(aba, url) {
  const minha = ++sequenciaDeteccao;
  try {
    const d = await ler('/api/capitulo', '&aba=' + encodeURIComponent(aba) + '&url=' + encodeURIComponent(url) + '&pasta=' + encodeURIComponent($('pasta').value));
    if (minha !== sequenciaDeteccao) return;                 // chegou depois de um endereço mais novo
    if (url !== urlDoCapitulo) { editado.num = false; editado.titulo = false; urlDoCapitulo = url; }
    if (!editado.obra && d.obra) $('obra').value = d.obra;
    if (!editado.num) $('cap-num').value = d.numero || '';
    if (!editado.titulo) $('cap-titulo').value = d.titulo || '';
    mostrarAvisoObra(d);
    atualizarPrevia();
  } catch (_) {}
}
async function carregarObras() {
  try {
    const d = await ler('/api/biblioteca');
    $('lista-obras').replaceChildren();
    d.obras.forEach((o) => { const op = document.createElement('option'); op.value = o.nome; $('lista-obras').append(op); });
  } catch (_) {}
}
$('obra').addEventListener('input', () => { editado.obra = true; atualizarPrevia(); });
$('obra').addEventListener('focus', carregarObras);
$('cap-num').addEventListener('input', () => { editado.num = true; atualizarPrevia(); });
$('cap-titulo').addEventListener('input', () => { editado.titulo = true; atualizarPrevia(); });
$('pasta').addEventListener('input', () => { pastaEditada = true; });
$('url').addEventListener('input', () => {
  if (navegadorAtivo() && paginaAtual.titulo) return;  // com o navegador aberto, vale a aba
  clearTimeout(window.__atrasoUrl);
  const v = normalizarUrl($('url').value);
  if (v !== urlLida) { paginaAtual = {titulo: '', url: ''}; reiniciarDadosDoCapitulo(); }   // link novo: descarta tudo do anterior
  window.__atrasoUrl = setTimeout(() => { if (v.length > 8) { urlLida = v; detectarCapitulo('', v); } }, 400);
});

async function urlParaAtualizar(nome) {
  nome = (nome || '').trim().toLowerCase();
  if (!nome) return '';
  try { const o = ((await ler('/api/biblioteca')).obras || []).find((x) => x.nome.toLowerCase() === nome); return o && o.ultima_url ? o.ultima_url : ''; } catch (_) { return ''; }
}
$('formulario').addEventListener('submit', async (ev) => {
  ev.preventDefault(); mensagem('');
  clearTimeout(window.__atrasoUrl);
  const enviado = normalizarUrl($('url').value);
  if (enviado && enviado !== urlLida && !(navegadorAtivo() && paginaAtual.url === enviado)) {   // link mudou desde a última leitura
    paginaAtual = {titulo: '', url: ''}; reiniciarDadosDoCapitulo(); urlLida = enviado; await detectarCapitulo('', enviado);
  }
  const comum = {url: $('url').value, navegador: $('navegador').value, caminho: $('caminho').value, ...dadosCapitulo(), perfil: $('perfil').value, bloquear_abas: $('bloquear-abas').checked};
  try {
    if (modo === 'manual') await chamar('/api/manual/abrir', comum);
    else {
      if (!$('pasta').value.trim()) { mensagem('Informe a pasta de destino.'); $('pasta').focus(); return; }
      const atualizando = $('atualizar-auto').checked;
      if (atualizando) {                                   // parte do último capítulo salvo da obra; nada do capítulo digitado é reaproveitado
        const alvo = await urlParaAtualizar($('obra').value);
        if (alvo) { Object.assign(comum, {url: alvo, numero: '', titulo: ''}); aviso('Atualizando a obra a partir do último capítulo salvo; o que já existe é pulado.'); }
        else aviso('Esta obra ainda não está na biblioteca: começando pelo endereço informado.');
      }
      await chamar('/api/manual/automatico', {...comum, pasta: $('pasta').value, espera: Number($('espera').value || 30), ignorar_comentarios: $('sem-comentarios').checked,
        continuar: atualizando || $('continuar-auto').checked, modo_busca: $('modo-busca').value,
        traduzir: !atualizando && $('traduzir-auto').checked && $('continuar-auto').checked, trad_de: $('trad-de').value, trad_para: $('trad-para').value});
    }
    $('iniciar').disabled = true;
  } catch (e) { mensagem(e.message); }
  atualizarJa();
});

/* ---- atualização periódica (e imediata ao voltar para a aba) */
let temporizador = null, emAtualizacao = false, ultimaAtualizacao = 0;
function atualizarJa() { if (emAtualizacao) return; clearTimeout(temporizador); atualizar(); }
window.addEventListener('focus', atualizarJa);
document.addEventListener('visibilitychange', () => { if (!document.hidden) atualizarJa(); });
document.addEventListener('pointerdown', () => { if (Date.now() - ultimaAtualizacao > 300) atualizarJa(); }, {passive: true, capture: true});

async function atualizar() {
  emAtualizacao = true;
  let proximo = 1500;
  try {
    aplicarManual(await ler('/api/manual/estado', `&ex=${exM}&log=${logM}&cv=${cvM}`));
    if (['abrindo', 'procurando'].includes(estadoManual) || salvandoManual) proximo = 400;
    $('offline').hidden = true;
  } catch (_) { $('offline').hidden = false; }
  emAtualizacao = false; ultimaAtualizacao = Date.now();
  temporizador = setTimeout(atualizar, proximo);
}

(async function iniciar() {
  try { const c = await ler('/api/config'); if (!$('pasta').value) $('pasta').value = c.pasta_padrao; } catch (_) {}
  aplicarModo(); carregarNavegadores(); carregarObras(); atualizar();
})();


/* ---- usado pela Biblioteca */
const Baixar = {
  configuracaoNavegador: () => ({navegador: $('navegador').value, caminho: $('caminho').value, perfil: $('perfil').value, bloquear_abas: $('bloquear-abas').checked}),
  /* "Atualizar" a obra: parte do último capítulo salvo. Só começa se a aba Baixar estiver livre. Devolve true se começou. */
  async atualizarObra(urlUltimo, nomeObra) {
    let e;
    try { e = await ler('/api/manual/estado', `&ex=${exM}&log=${logM}&cv=${cvM}`); } catch (erro) { aviso(erro.message); return false; }
    const coletadas = (e.itens || itensManual || []).filter((i) => !i.erro).length;
    if (['abrindo', 'aguardando', 'procurando'].includes(e.estado) || e.automatico || e.salvando || coletadas) {
      aviso('Espere: a aba “Baixar imagens” está baixando ou aguardando você. Termine, feche o navegador ou use “Limpar tudo” e tente de novo.');
      return false;
    }
    try {
      aplicarManual(e);
      $('url').value = urlUltimo; paginaAtual = {titulo: '', url: ''}; urlDoCapitulo = ''; urlLida = '';
      editado.obra = editado.num = editado.titulo = false; $('obra').value = nomeObra; $('cap-num').value = ''; $('cap-titulo').value = '';
      const comum = {url: urlUltimo, ...Baixar.configuracaoNavegador(), obra: nomeObra, numero: '', titulo: ''};
      if (!$('pasta').value.trim()) { aviso('Informe a pasta de destino (em “Navegador e destino”) para o modo automático.'); return false; }
      modo = 'auto'; document.querySelector('input[name=modo][value=auto]').checked = true; aplicarModo();   // "Atualizar" sempre usa o automático, qualquer que seja o modo escolhido
      $('continuar-auto').checked = true; $('nota-continuar').hidden = false; opcaoAtualizar();
      await chamar('/api/manual/automatico', {...comum, pasta: $('pasta').value, espera: Number($('espera').value || 30), ignorar_comentarios: $('sem-comentarios').checked,
        continuar: true, atualizar: true, modo_busca: $('modo-busca').value, traduzir: $('traduzir-auto').checked, trad_de: $('trad-de').value, trad_para: $('trad-para').value});
      aviso(`Atualizando “${nomeObra}” no modo automático: o último capítulo salvo não é baixado de novo: o programa aperta em “próximo” e baixa só os novos.`);
      atualizarJa();
      return true;
    } catch (erro) { aviso(erro.message); return false; }
  },
};
