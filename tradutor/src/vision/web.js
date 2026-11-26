// Motor "web": a tradução é feita à mão numa IA da web (ChatGPT, Gemini, Claude...). Sem API, sem chave, sem modelo local.
//
//   1) prepararTextos: lista as falas com letras (as que precisam de tradução) em <trabalho>/web/textos.json, cada uma com o seu id
//      (p001-b3), a página (arquivo) e um hash do texto. O Baixador transforma isso em TXT para copiar/baixar.
//   2) O Baixador valida o que a pessoa traz de volta e grava <trabalho>/web/importadas.json ({ codigo, traducoes: { id: { t, h } } }).
//   3) translateWeb (etapa 4b) monta o mesmo traducao.json dos outros motores, ligando cada tradução à fala pelo ID (nunca pela ordem).
//      Tradução cujo hash não bate com o texto atual da fala (o OCR ou uma correção mudou) NÃO é usada: a fala fica com status "erro".
import { createHash, randomBytes } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { applyEdits, collectUnits, glossaryMisses } from './translate.js';

export const NOME_WEB = 'IA na web (manual)';
const hasLetters = (s) => /[A-Za-z]/.test(s);
export const umaLinha = (s) => String(s ?? '').replace(/\s+/g, ' ').trim();
export const hashFonte = (s) => createHash('sha1').update(s).digest('hex').slice(0, 12);

async function readJson(file, fallback) {
  try {
    return JSON.parse(await readFile(file, 'utf8'));
  } catch (err) {
    if (err.code === 'ENOENT') return fallback;
    throw new Error(`Não consegui ler ${file}: ${err.message}`);
  }
}

async function writeAtomic(file, data) {
  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  await writeFile(tmp, JSON.stringify(data, null, 1));
  await rename(tmp, file);
}

// Falas que precisam de tradução: as mesmas da 4b (correcoes.json vale), só as que têm letras.
async function unidadesDoCapitulo(ocrFile) {
  const ocr = await readJson(ocrFile, null);
  if (!ocr) throw new Error(`Não achei ${ocrFile}.`);
  const fixes = await readJson(path.join(path.dirname(ocrFile), 'correcoes.json'), {});
  return collectUnits(ocr, fixes).filter((u) => hasLetters(u.source));
}

const webDir = (work) => path.join(work, 'web');

// Grava web/textos.json. O código do capítulo (8 hex) vai em cada ID e fica o mesmo enquanto as falas forem as mesmas: texto exportado
// antes continua valendo. Se as falas mudarem, o código muda e o que foi exportado antes deixa de ser aceito (nada vai para o lugar errado).
export async function prepararTextos({ ocrFile, work, assinatura = null }) {
  const unidades = (await unidadesDoCapitulo(ocrFile)).map((u) => {
    const fonte = umaLinha(u.source);
    return { id: u.id, arquivo: u.file, fonte, hash: hashFonte(fonte) };
  });
  const file = path.join(webDir(work), 'textos.json');
  const atual = await readJson(file, null);
  const igual = atual?.codigo && JSON.stringify(atual.unidades) === JSON.stringify(unidades);
  const codigo = igual ? atual.codigo : randomBytes(4).toString('hex');
  await writeAtomic(file, { versao: 1, codigo, assinatura, geradoEm: igual ? atual.geradoEm : new Date().toISOString(), unidades });
  return { codigo, textos: unidades.length, ...(await situacao(work, { codigo, unidades })) };
}

// Quantas falas já têm tradução importada válida para o texto de hoje.
export async function situacao(work, textos = null) {
  textos ??= await readJson(path.join(webDir(work), 'textos.json'), null);
  const imp = await readJson(path.join(webDir(work), 'importadas.json'), null);
  const valida = imp && textos && imp.codigo === textos.codigo ? imp.traducoes ?? {} : {};
  const importadas = textos ? textos.unidades.filter((u) => valida[u.id]?.h === u.hash && umaLinha(valida[u.id]?.t)).length : 0;
  const total = textos?.unidades.length ?? 0;
  return { importadas, completo: total > 0 ? importadas === total : true };
}

// Etapa 4b do motor "web": sem chamar nenhum serviço. Mesmo formato de translateChapter.
export async function translateWeb(ocrFile, outDir, { log = console.log } = {}) {
  const base = path.dirname(ocrFile);
  const work = path.dirname(base);
  const ocr = await readJson(ocrFile, null);
  if (!ocr) throw new Error(`Não achei ${ocrFile}.`);
  const fixes = await readJson(path.join(base, 'correcoes.json'), {});
  const glossary = await readJson(path.join(base, 'glossario.json'), {});
  const edits = await readJson(path.join(base, 'edicoes.json'), {});
  const textos = await readJson(path.join(webDir(work), 'textos.json'), null);
  const imp = await readJson(path.join(webDir(work), 'importadas.json'), null);
  const valida = imp && textos && imp.codigo === textos.codigo ? imp.traducoes ?? {} : {};
  const units = collectUnits(ocr, fixes);
  const stats = { units: units.length, batches: 0, cached: 0, translated: 0, individual: 0, errors: 0 };
  const out = applyEdits(units.map((u) => {
    const b = { id: u.id, page: u.page, file: u.file, balloonId: u.balloonId, textIds: u.textIds, bbox: u.bbox, source: u.source };
    if (!hasLetters(u.source)) return { ...b, translation: u.source, status: 'copiado', mode: null, batch: null }; // só números/pontuação
    const r = valida[u.id];
    const t = umaLinha(r?.t);
    if (!t || r.h !== hashFonte(umaLinha(u.source))) {
      stats.errors++;
      return { ...b, translation: null, status: 'erro', error: t ? 'O texto original mudou depois da exportação; exporte de novo.' : 'Sem tradução importada.', mode: 'web', batch: null };
    }
    stats.translated++;
    const misses = glossaryMisses(u.source, t, glossary);
    return { ...b, translation: t, status: misses.length ? 'revisar' : 'ok', glossary: misses, mode: 'web', batch: null };
  }), edits);
  const doc = { generatedAt: new Date().toISOString(), engine: 'web', provider: NOME_WEB, source: path.relative(outDir, ocrFile).split(path.sep).join('/'), stats, units: out };
  await mkdir(outDir, { recursive: true });
  await writeFile(path.join(outDir, 'traducao.json'), JSON.stringify(doc, null, 2));
  log(`${out.length} falas: ${stats.translated} da IA na web, ${stats.errors} sem tradução → ${path.join(outDir, 'traducao.json')}`);
  return doc;
}
