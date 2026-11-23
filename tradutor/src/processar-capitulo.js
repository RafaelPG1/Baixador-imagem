// Ponto de entrada do Baixador: traduz UM capítulo que já está na biblioteca (obras/<Obra>/<Capítulo>/).
//
//   node src/processar-capitulo.js --capitulo <pasta do capítulo> --motor <local|deepl|gemini|mymemory> [--refazer]
//   node src/processar-capitulo.js --verificar --motor <motor>      (só confere se o motor está pronto; imprime um JSON)
//
// Lê as imagens de <capítulo>/img/ (ou do próprio capítulo, no formato antigo) e NÃO as altera nem copia.
// Resultado: <capítulo>/traducao.json (falas, balões, regiões, status) e <capítulo>/traducao/limpeza/*.png (texto original
// apagado). Enquanto roda, o trabalho fica em <capítulo>/traducao.nova/: se cancelar ou falhar, rodar de novo continua de
// onde parou (etapas prontas são puladas e os lotes já traduzidos vêm do cache), e a tradução anterior (se houver) continua
// valendo até o fim. Só no fim a pasta nova substitui a antiga. `--refazer` apenas dispensa o "já traduzido".
// Com TRADUTOR_EVENTOS=1 também escreve linhas "@@{json}" de progresso (veja progresso.js).
import { mkdir, readFile, readdir, rename, rm, stat, writeFile, copyFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { processChapter } from './obra/pipeline.js';
import { createEngines, defaultEngineId } from './services/index.js';
import { progresso } from './progresso.js';
import { resetEngines } from './translator.js';
import { NOME_WEB, prepararTextos, situacao } from './vision/web.js';

export const FORMATO = 2;
const isDir = (p) => stat(p).then((s) => s.isDirectory(), () => false);
const isFile = (p) => stat(p).then((s) => s.isFile(), () => false);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readJson(file) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return null;
    throw new Error(`Não consegui ler ${file}: ${err.message}`);
  }
}

// O resultado só vale se for do formato novo (o primeiro campo do arquivo é "formato").
export async function resultadoValido(file) {
  const d = await readJson(file).catch(() => null);
  return d?.formato === FORMATO && Array.isArray(d.pages);
}

// Antes de gastar minutos de OCR: o motor escolhido está de pé? Nada de trocar de motor sozinho.
export async function verificarMotor(motor, env = process.env, fetchFn = fetch) {
  if ((motor ?? env.TRANSLATION_ENGINE) === 'web') return { motor: 'web', nome: NOME_WEB }; // tradução manual: nada para conferir
  const engines = createEngines(env);
  const id = defaultEngineId(engines, { ...env, TRANSLATION_ENGINE: motor ?? env.TRANSLATION_ENGINE });
  if (id !== 'local') return { motor: id, nome: engines[id].name };
  const url = (env.OLLAMA_URL || 'http://127.0.0.1:11434').replace(/\/+$/, '');
  const model = env.LOCAL_MODEL || 'translategemma:4b';
  let tags;
  try {
    const res = await fetchFn(`${url}/api/tags`, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    tags = await res.json();
  } catch {
    throw new Error('O Ollama não está rodando. Abra o Ollama e tente de novo.');
  }
  const names = (tags.models ?? []).map((m) => m.name);
  const ok = names.some((n) => n === model || (!model.includes(':') && n === `${model}:latest`));
  if (!ok) throw new Error(`O modelo ${model} não está instalado no Ollama. Rode: ollama pull ${model}`);
  return { motor: id, nome: engines[id].name };
}

// Glossário da obra (obras/<Obra>/glossario.json: { "TERMO": "tradução" }) e correções de OCR do capítulo
// (<capítulo>/correcoes.json: { "id da fala": "texto certo" }) entram na etapa 4a. Arquivo fora do formato é ignorado com aviso.
async function prepararAuxiliares(cap, work, log) {
  const dest = path.join(work, 'etapa4a');
  await mkdir(dest, { recursive: true });
  const fontes = [
    [path.join(path.dirname(cap), 'glossario.json'), 'glossario.json', 'glossário da obra'],
    [path.join(cap, 'correcoes.json'), 'correcoes.json', 'correções do capítulo'],
  ];
  for (const [src, nome, rotulo] of fontes) {
    if (!(await isFile(src))) continue;
    const dados = await readJson(src).catch(() => null);
    const valido = dados && typeof dados === 'object' && !Array.isArray(dados) && Object.values(dados).every((v) => typeof v === 'string');
    if (!valido) { log(`AVISO: ${rotulo} (${src}) não está no formato { "chave": "texto" } e foi ignorado.`); continue; }
    await copyFile(src, path.join(dest, nome));
    log(`${rotulo}: ${Object.keys(dados).length} entradas`);
  }
}

// rename de pasta pode falhar no Windows se algo estiver lendo dentro dela naquele instante: tenta de novo.
async function renomear(de, para) {
  for (let i = 0; ; i++) {
    try { return await rename(de, para); } catch (err) {
      if (i >= 8 || !['EPERM', 'EBUSY', 'EACCES', 'ENOTEMPTY'].includes(err.code)) throw err;
      await sleep(250 * (i + 1));
    }
  }
}

// Fecha o capítulo: grava traducao.json (escrita atômica) e troca a pasta de trabalho pela definitiva.
async function publicar(cap, work) {
  const final = path.join(cap, 'traducao');
  const velha = path.join(cap, 'traducao.velha');
  const resultado = path.join(cap, 'traducao.json');
  const novo = path.join(cap, 'traducao.json.tmp');
  const leitor = path.join(work, 'leitor', 'leitor.json');
  const dados = await readFile(leitor, 'utf8');
  // só o que o leitor precisa fica: o PNG de cada página; as pastas das etapas (e o cache) saem
  await mkdir(path.join(work, 'limpeza'), { recursive: true });
  const limpeza = path.join(work, 'etapa6', 'limpeza');
  for (const f of (await isDir(limpeza)) ? await readdir(limpeza) : []) await renomear(path.join(limpeza, f), path.join(work, 'limpeza', f));
  for (const d of ['etapa3', 'etapa4a', 'etapa4b', 'etapa4c', 'etapa6', 'etapa8', 'leitor', 'web']) await rm(path.join(work, d), { recursive: true, force: true });
  await rm(path.join(work, 'manifest.json'), { force: true });
  await writeFile(novo, dados);
  await rm(velha, { recursive: true, force: true });
  if (await isDir(final)) await renomear(final, velha);
  await renomear(work, final);
  await renomear(novo, resultado);
  await rm(velha, { recursive: true, force: true });
  return JSON.parse(dados);
}

export async function traduzirCapitulo({ capitulo, motor, refazer = false, env = process.env, log = console.log } = {}) {
  const cap = path.resolve(capitulo);
  if (!(await isDir(cap))) throw new Error(`Capítulo não encontrado: ${cap}`);
  const imagesDir = (await isDir(path.join(cap, 'img'))) ? path.join(cap, 'img') : cap;
  const resultado = path.join(cap, 'traducao.json');
  if (!refazer && (await resultadoValido(resultado))) {
    log('Capítulo já traduzido (use "traduzir de novo" para refazer).');
    progresso({ evento: 'pronto', jaTraduzido: true });
    return { jaTraduzido: true };
  }
  // a tradução (Etapa 4b) lê o ambiente do processo: garante que ela veja o mesmo `env` que a verificação
  if (env !== process.env) { for (const [k, v] of Object.entries(env)) if (typeof v === 'string') process.env[k] = v; }
  resetEngines();
  let verificado;
  try {
    verificado = await verificarMotor(motor, env);
  } catch (err) {
    err.abortar = true; // motor fora do ar ou sem chave: os próximos capítulos falhariam igual
    throw err;
  }
  log(`Motor: ${verificado.nome}`);
  progresso({ evento: 'motor', motor: verificado.motor, nome: verificado.nome });
  const work = path.join(cap, 'traducao.nova');
  const chapter = { id: path.basename(cap), imagesDir, outDir: work };
  await mkdir(work, { recursive: true });
  await prepararAuxiliares(cap, work, log);
  if (verificado.motor === 'web') {
    // 1ª parte: detecta e lê as falas; se faltar a tradução que a pessoa traz da IA na web, para aqui SEM publicar nada
    // (a tradução anterior, se houver, continua valendo). Quando todas as falas têm tradução importada, segue até o fim.
    await processChapter(chapter, { engine: 'web', log, ate: 'etapa4a' });
    const prep = await prepararTextos({ ocrFile: path.join(work, 'etapa4a', 'ocr.json'), work });
    if (!prep.completo) {
      progresso({ evento: 'aguardando', textos: prep.textos, importadas: prep.importadas, codigo: prep.codigo });
      log(`${prep.textos} texto(s) prontos para levar à IA na web (${prep.importadas} já importados). A tradução termina quando todos forem importados.`);
      return { aguardando: true, textos: prep.textos, importadas: prep.importadas };
    }
  }
  await processChapter(chapter, { engine: verificado.motor, log });
  const dados = await publicar(cap, work);
  const falas = dados.pages.reduce((n, p) => n + p.units.length, 0);
  progresso({ evento: 'pronto', falas, contagens: dados.counts, avisos: dados.warnings?.length ?? 0 });
  log(`Pronto: ${falas} falas em ${dados.pages.length} páginas → ${resultado}`);
  return { falas, contagens: dados.counts };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const valor = (nome) => { const i = args.indexOf(nome); return i >= 0 ? args[i + 1] : undefined; };
  if (args.includes('--verificar')) {
    // usado pelo botão "Verificar" do Baixador: uma linha JSON, sempre com exit 0
    try {
      const v = await verificarMotor(valor('--motor'));
      console.log(JSON.stringify({ ok: true, motor: v.motor, nome: v.nome }));
    } catch (err) {
      console.log(JSON.stringify({ ok: false, mensagem: err.message }));
    }
    process.exit(0);
  }
  try {
    if (!valor('--capitulo')) throw new Error('Uso: node src/processar-capitulo.js --capitulo <pasta> --motor <local|deepl|gemini|mymemory> [--refazer]');
    await traduzirCapitulo({ capitulo: valor('--capitulo'), motor: valor('--motor'), refazer: args.includes('--refazer') });
  } catch (err) {
    progresso({ evento: 'erro', mensagem: err.message, abortar: Boolean(err.abortar || err.code) }); // erro de motor (TranslationError tem code) aborta a fila
    console.error(`Erro: ${err.message}\nO que já foi feito fica salvo; rode de novo para continuar.`);
    if (process.env.DEBUG) console.error(err.stack);
    process.exitCode = 1;
  }
}
