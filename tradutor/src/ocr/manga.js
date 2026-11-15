import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fixWord, isWord } from './lexicon.js';

const require = createRequire(import.meta.url);
const letters = (s) => s.replace(/[^A-Za-z]/g, '');

// Worker próprio, reaproveitado por todas as regiões da execução (subir um por região custaria ~0,3 s cada).
// Dados e núcleo WebAssembly vêm de node_modules, dentro do projeto.
async function loadWorker() {
  const { createWorker } = require('tesseract.js');
  const langPath = join(dirname(require.resolve('@tesseract.js-data/eng')), '4.0.0_best_int');
  const corePath = dirname(require.resolve('tesseract.js-core/package.json'));
  const worker = await createWorker('eng', 1, { langPath, corePath, cacheMethod: 'none', errorHandler: () => {} });
  await worker.setParameters({ tessedit_pageseg_mode: '6', user_defined_dpi: '300' }); // bloco único de texto
  return worker;
}

// TSV → palavras { text, conf } na ordem de leitura, sem os fragmentos de contorno e arte que o Tesseract lê como "texto".
export function readWords(tsv) {
  const words = [];
  for (const row of tsv.split('\n')) {
    const c = row.replace(/\r$/, '').split('\t');
    if (c.length < 12 || c[0] !== '5') continue;
    const text = c.slice(11).join('\t').trim();
    const conf = Number(c[10]);
    if (!text) continue;
    const n = text.replace(/[^A-Za-z0-9|]/g, '').length;
    const keep = /^[.?!…]+$/.test(text) || n >= 2 || (/^[IAa|][,.;:!?]*$/.test(text) && conf >= 50);
    if (keep) words.push({ text, conf });
  }
  return words;
}

// Tem texto de verdade? Fragmentos de contorno e arte viram palavrinhas soltas ("ye", "BN", "LLLINTI"). Texto real
// tem uma palavra de 3+ letras que existe em inglês e a maioria das palavras de 2+ letras existe.
export function hasText(words) {
  const ws = words.map((w) => letters(w.text)).filter((w) => w.length >= 2);
  const good = ws.filter(isWord);
  return good.some((w) => w.length >= 3) && good.length >= ws.length / 2;
}

// Palavras → { text, status, confidence }. status: "ok" | "revisar" (palavra desconhecida ou incerta) | "vazio" (sem texto).
export function toResult(words) {
  if (!hasText(words)) return { text: '', status: 'vazio', confidence: 0 };
  const fixed = words.map((w) => ({ ...w, text: fixWord(w.text, w.conf) }));
  const text = fixed.map((w) => w.text).join(' ');
  const checked = fixed.filter((w) => letters(w.text).length >= 2);
  const shaky = checked.filter((w) => !isWord(letters(w.text)) || w.conf < 50 || /\d|\|/.test(w.text));
  const confidence = Math.round(fixed.reduce((s, w) => s + w.conf, 0) / fixed.length);
  return { text, status: shaky.length ? 'revisar' : 'ok', confidence, doubtful: shaky.map((w) => w.text) };
}

export function createMangaReader() {
  let worker;
  return {
    async read(png, psm = '6') {
      worker ??= await loadWorker();
      await worker.setParameters({ tessedit_pageseg_mode: psm });
      const { data } = await worker.recognize(png, {}, { tsv: true });
      return toResult(readWords(data.tsv ?? ''));
    },
    async close() {
      await worker?.terminate().catch(() => {});
      worker = undefined;
    },
  };
}
