import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { progresso } from '../progresso.js';
import { TranslationError } from '../errors.js';
import { getEngines, translate as translateWith, getDefaultEngine } from '../translator.js';
import { RETRY_LEVELS } from '../services/local.js';
import { degenerate, squeezeRuns } from '../repeticao.js';

const BATCH = 8; // falas por lote
const CONTEXT = 3; // falas anteriores mostradas como contexto
const MAX_CHARS = 1500; // teto de texto novo por lote (cabe no num_ctx 4096 do modelo local)
const ROW = 80; // px: balões na mesma faixa vertical leem-se da esquerda para a direita
const CACHE_VERSION = 2; // mude ao trocar o formato do prompt: invalida o cache (2: repetições longas da origem são reduzidas antes de ir ao modelo)
// Só estes erros justificam tentar de outro jeito (fala por fala, amostragem alternativa). Resposta ruim, repetição e resposta
// cortada são problemas DESTE texto; Ollama fora do ar, modelo ausente, limite ou timeout aborta a execução (o cache permite retomar).
const RECOVERABLE = new Set(['BAD_BATCH', 'EMPTY_RESPONSE', 'REPETITION', 'TRUNCATED']);

const hasLetters = (s) => /[A-Za-z]/.test(s);

// Falas a traduzir, na ordem de leitura (páginas em ordem; dentro da página, de cima para baixo e da esquerda para a direita).
// Texto de correcoes.json vence o da 4a; correção vazia descarta a fala. Região "vazia" não entra.
export function collectUnits(ocr, fixes = {}) {
  const out = [];
  for (const page of ocr.pages) {
    const units = page.units
      .map((u) => ({ ...u, source: (fixes[u.id] ?? u.text ?? '').trim() }))
      .filter((u) => u.source && (u.status !== 'vazio' || u.id in fixes));
    units.sort((a, b) => Math.round(a.bbox[1] / ROW) - Math.round(b.bbox[1] / ROW) || a.bbox[0] - b.bbox[0]);
    out.push(...units);
  }
  return out;
}

// Lotes de até BATCH falas (e MAX_CHARS caracteres), cada um com as CONTEXT falas anteriores.
// Só falas com letras vão ao motor; "139", "?!" e "..." são copiadas como estão.
export function makeBatches(units, { size = BATCH, context = CONTEXT, maxChars = MAX_CHARS } = {}) {
  const todo = units.filter((u) => hasLetters(u.source));
  const batches = [];
  for (let i = 0; i < todo.length; ) {
    let n = 0;
    let chars = 0;
    while (i + n < todo.length && n < size && (n === 0 || chars + todo[i + n].source.length <= maxChars)) chars += todo[i + n++].source.length;
    batches.push({ context: todo.slice(Math.max(0, i - context), i), units: todo.slice(i, i + n) });
    i += n;
  }
  return batches;
}

// Uma fala por linha, numerada: "[1] TEXTO". As de contexto vêm primeiro e também voltam traduzidas (validam a resposta inteira).
export const buildBatchText = ({ context, units }) =>
  [...context, ...units].map((u, i) => `[${i + 1}] ${squeezeRuns(u.source.replace(/\s*\n\s*/g, ' '))}`).join('\n');

// Lê a resposta e exige exatamente os números 1..n, cada um uma vez, todos com texto. Senão lança BAD_BATCH.
export function parseBatch(output, n) {
  const found = new Map();
  let last = null;
  for (const line of output.split('\n')) {
    const m = line.match(/^\s*\[(\d+)\]\s*(.*)$/);
    if (m) {
      last = Number(m[1]);
      if (found.has(last)) throw new TranslationError('BAD_BATCH', `A fala [${last}] veio duplicada na resposta.`, 502);
      found.set(last, m[2].trim());
    } else if (last && line.trim()) found.set(last, `${found.get(last)} ${line.trim()}`.trim()); // frase quebrada em duas linhas
  }
  const missing = Array.from({ length: n }, (_, i) => i + 1).filter((k) => !found.get(k));
  const extra = [...found.keys()].filter((k) => k < 1 || k > n);
  if (missing.length || extra.length) {
    throw new TranslationError('BAD_BATCH', `Resposta incompleta ou com números errados (faltam: ${missing.join(', ') || 'nenhum'}; sobram: ${extra.join(', ') || 'nenhum'}).`, 502);
  }
  return Array.from({ length: n }, (_, i) => found.get(i + 1));
}

const hash = (s) => createHash('sha256').update(s).digest('hex').slice(0, 24);
export const batchKey = (batch, provider, glossary) => hash(JSON.stringify([CACHE_VERSION, provider, buildBatchText(batch), batch.context.length, glossary]));

const snip = (s, n = 70) => String(s ?? '').replace(/\s+/g, ' ').trim().slice(0, n);
const friendly = (e) => (e.code === 'REPETITION' ? 'o modelo entrou em repetição e não saiu dela nas tentativas' : e.code === 'TRUNCATED' ? 'a resposta do Ollama veio cortada nas tentativas' : e.message);

// Frases de um texto (para o último recurso de uma fala que não sai inteira).
export function splitSentences(text) {
  const raw = String(text).split(/(?<=[.!?…])\s+/).map((x) => x.trim()).filter(Boolean);
  const out = [];
  for (const piece of raw) (out.length && (piece.length < 12 || out[out.length - 1].length < 12) ? (out[out.length - 1] += ` ${piece}`) : out.push(piece));
  return out;
}

// Uma fala sozinha, com tentativas. Falha recuperável (repetição, resposta cortada, vazia ou defeituosa) tenta de novo com
// amostragem alternativa; se ainda falhar e a fala tiver mais de uma frase, traduz frase por frase. Nunca devolve resposta
// incompleta: ou vem a tradução inteira, ou lança o último erro.
export async function translateOne(source, engine, translateFn, { log, label = '', split = true } = {}) {
  const levels = engine === 'local' ? RETRY_LEVELS : 1; // só o motor local muda de amostragem
  let last;
  for (let retry = 0; retry < levels; retry++) {
    try {
      const t = (await translateFn(squeezeRuns(source), engine, { retry })).translation.trim();
      if (!t) throw new TranslationError('EMPTY_RESPONSE', 'O modelo não devolveu tradução.', 502);
      if (degenerate(source, t)) throw new TranslationError('REPETITION', 'A tradução saiu repetitiva.', 502);
      if (retry) log?.(`  ${label}recuperada na tentativa ${retry + 1}/${levels} (amostragem alternativa)`);
      return t;
    } catch (e) {
      if (!RECOVERABLE.has(e.code)) throw e;
      last = e;
      log?.(`  ${label}tentativa ${retry + 1}/${levels} falhou: ${e.message}${e.partial ? ` | fim da resposta: «${e.partial.slice(-60).replace(/\s+/g, ' ')}»` : ''}`);
    }
  }
  const parts = split ? splitSentences(source) : [];
  if (parts.length > 1) {
    try {
      const out = [];
      for (const [i, part] of parts.entries()) out.push(await translateOne(part, engine, translateFn, { log, label: `${label}frase ${i + 1}/${parts.length} `, split: false }));
      log?.(`  ${label}recuperada traduzindo frase por frase`);
      return out.join(' ');
    } catch (e) {
      if (!RECOVERABLE.has(e.code)) throw e;
      last = e;
    }
  }
  throw last;
}

// Traduz um lote. Primeiro tudo junto; se a resposta não passar na validação (ou o modelo repetir/cortar), cada fala vai sozinha
// (modo "individual", com tentativas). Uma fala que ainda falhar fica com status "erro" e sem tradução, nunca com a tradução de
// outra nem com uma tradução pela metade. O capítulo segue: só erro de infraestrutura (Ollama fora do ar...) aborta.
export async function translateBatch(batch, engine, translateFn, log) {
  try {
    const items = [...batch.context, ...batch.units];
    const all = parseBatch((await translateFn(buildBatchText(batch), engine)).translation, items.length);
    items.forEach((u, i) => {
      if (degenerate(u.source, all[i])) throw new TranslationError('REPETITION', `A fala [${i + 1}] saiu repetitiva na resposta do lote.`, 502);
    });
    return { mode: 'lote', results: batch.units.map((u, i) => ({ id: u.id, translation: all[batch.context.length + i] })) };
  } catch (err) {
    if (!RECOVERABLE.has(err.code)) throw err;
    log?.(`lote: ${err.message}${err.partial ? ` | fim da resposta: «${err.partial.slice(-60).replace(/\s+/g, ' ')}»` : ''} → traduzindo as ${batch.units.length} falas uma a uma`);
    const results = [];
    for (const u of batch.units) {
      try {
        results.push({ id: u.id, translation: await translateOne(u.source, engine, translateFn, { log, label: `fala ${u.id} «${snip(u.source, 50)}» ` }) });
      } catch (e) {
        if (!RECOVERABLE.has(e.code)) throw e;
        log?.(`  fala ${u.id} «${snip(u.source, 50)}» ficou SEM tradução: ${friendly(e)}`);
        results.push({ id: u.id, error: friendly(e) });
      }
    }
    return { mode: 'individual', reason: err.message, results };
  }
}

// Termos do glossário (glossario.json: { "TERMO": "tradução" }) que a fala tem e a tradução não usou → marcar para revisão.
export function glossaryMisses(source, translation, glossary) {
  return Object.entries(glossary).filter(([term, pt]) => new RegExp(`\\b${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(source) && !translation.toLowerCase().includes(pt.toLowerCase())).map(([t]) => t);
}

// Edições feitas à mão (edicoes.json: { "id da fala": "texto" }) valem sobre qualquer tradução, inclusive ao refazer o capítulo.
export function applyEdits(units, edits) {
  return units.map((u) => {
    const t = typeof edits?.[u.id] === 'string' ? edits[u.id].trim() : '';
    return t ? { ...u, translation: t, status: 'ok', error: undefined, glossary: [], editada: true } : u;
  });
}

async function readJson(file, fallback) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return fallback;
    throw new Error(`Não consegui ler ${file}: ${err.message}`);
  }
}

export async function translateChapter(ocrFile, outDir, { engine, translateFn = (t, e, o) => translateWith(t, e, getEngines(), o), log = console.log, size, context } = {}) {
  const ocr = await readJson(ocrFile, null);
  if (!ocr) throw new Error(`Não achei ${ocrFile}. Rode "npm run ocr" antes.`);
  const base = path.dirname(ocrFile);
  const fixes = await readJson(path.join(base, 'correcoes.json'), {});
  const glossary = await readJson(path.join(base, 'glossario.json'), {});
  const edits = await readJson(path.join(base, 'edicoes.json'), {});
  engine ??= getDefaultEngine();
  const provider = getEngines()[engine]?.name ?? engine;
  const units = collectUnits(ocr, fixes);
  const batches = makeBatches(units, { size, context });
  await mkdir(path.join(outDir, 'cache'), { recursive: true });

  const done = new Map(); // id → { translation | error, mode, batch }
  const stats = { units: units.length, batches: batches.length, cached: 0, translated: 0, individual: 0, errors: 0 };
  const t0 = Date.now();
  for (const [i, batch] of batches.entries()) {
    const file = path.join(outDir, 'cache', `${batchKey(batch, provider, glossary)}.json`);
    let entry = await readJson(file, null);
    if (entry) stats.cached++;
    else {
      entry = await translateBatch(batch, engine, translateFn, log);
      if (entry.results.every((r) => !r.error)) await writeFile(file, JSON.stringify(entry, null, 2)); // lote com erro não é guardado: roda de novo
      stats.translated++;
      log(`lote ${i + 1}/${batches.length}: ${batch.units.length} falas (${entry.mode}) — ${((Date.now() - t0) / 1000).toFixed(0)} s`);
    }
    if (entry.mode === 'individual') stats.individual++;
    progresso({ etapa: 'etapa4b', feitas: i + 1, total: batches.length });
    for (const r of entry.results) done.set(r.id, { ...r, mode: entry.mode, batch: i + 1 });
  }

  const out = applyEdits(units.map((u) => {
    const r = done.get(u.id);
    const base = { id: u.id, page: u.page, file: u.file, balloonId: u.balloonId, textIds: u.textIds, bbox: u.bbox, source: u.source };
    if (!r) return { ...base, translation: u.source, status: 'copiado', mode: null, batch: null }; // só números/pontuação
    if (r.error) { stats.errors++; return { ...base, translation: null, status: 'erro', error: r.error, mode: r.mode, batch: r.batch }; }
    const misses = glossaryMisses(u.source, r.translation, glossary);
    return { ...base, translation: r.translation, status: misses.length || r.mode === 'individual' ? 'revisar' : 'ok', glossary: misses, mode: r.mode, batch: r.batch };
  }), edits);
  const doc = { generatedAt: new Date().toISOString(), engine, provider, source: path.relative(outDir, ocrFile).split(path.sep).join('/'), stats, units: out };
  await writeFile(path.join(outDir, 'traducao.json'), JSON.stringify(doc, null, 2));
  log(`${out.length} falas em ${batches.length} lotes (${stats.cached} do cache, ${stats.translated} traduzidos, ${stats.individual} caíram para tradução individual, ${stats.errors} com erro) → ${path.join(outDir, 'traducao.json')}`);
  return doc;
}
