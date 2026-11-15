import { createRequire } from 'node:module';

// Correção de leitura para balões de mangá (caixa alta em inglês). O Tesseract troca letras parecidas na fonte
// itálica dos balões (D↔P, U↔L, S↔5, I↔|). Só se troca uma palavra que não existe por uma que existe, e só quando
// a candidata é única; nomes próprios ficam como lidos. Frequência vem de legendas (fala), pacote subtlex-word-frequencies.
const require = createRequire(import.meta.url);
let freq;
function load() {
  if (freq) return freq;
  freq = new Map();
  for (const { word, count } of require('subtlex-word-frequencies')) {
    const w = word.toLowerCase();
    freq.set(w, (freq.get(w) ?? 0) + count);
  }
  return freq;
}

// letras que o Tesseract confunde nesta fonte → possíveis letras certas
const SWAP = {
  D: 'PO', P: 'D', U: 'LV', L: 'UI', I: 'L|1', O: '0DQ', S: '5', B: '8', E: 'FC', F: 'E', H: 'N', N: 'H', C: 'GE',
  G: 'C6', T: '7I', A: '4', Z: '2', V: 'U', W: 'V', R: 'B', M: 'N', Y: 'V',
  0: 'O', 1: 'I', 5: 'S', 8: 'SB', 2: 'Z', 6: 'G', 7: 'T', 4: 'A', '|': 'I',
};
const NT_BASE = new Set(['is', 'are', 'was', 'were', 'do', 'does', 'did', 'can', 'could', 'would', 'should', 'have', 'has', 'had', 'wo', 'ca', 'ai']);

// frequência da palavra (0 se desconhecida); contrações: "didn't" = did + n't, "it's" = it + 's
export function wordFreq(w) {
  const f = load();
  const lw = w.toLowerCase();
  const m = lw.match(/^(.+?)(n't|'s|'ll|'re|'ve|'d|'m)$/);
  if (m) {
    const ok = m[2] === "n't" ? NT_BASE.has(m[1]) : f.has(m[1]) || m[1] === 'i';
    return ok ? (f.get(m[1]) ?? 1) : 0;
  }
  return f.get(lw) ?? 0;
}
// interjeições de mangá que a lista de legendas não tem
const INTERJECTION = /^(UGH+|ARGH+|AH+|OH+|HM+|HA+|HAH+|EH+|HUH|HEH|TCH|TSK|GRR+|AAA+H*|HYAA+H*)$/i;
export const isWord = (w) => wordFreq(w) > 0 || INTERJECTION.test(w);

function swaps(up, max) {
  const out = new Map();
  const walk = (from, s, n) => {
    if (n) {
      if (/^[A-Z']+$/.test(s) && wordFreq(s)) out.set(s, wordFreq(s));
      if (n === max) return;
    }
    for (let i = from; i < s.length; i++) for (const r of SWAP[s[i]] ?? '') walk(i + 1, s.slice(0, i) + r + s.slice(i + 1), n + 1);
  };
  walk(0, up, 0);
  return out;
}

// Devolve a palavra corrigida (ou a original). `conf` é a confiança do Tesseract (0 a 100).
export function fixWord(token, conf = 0) {
  const lead = token.match(/^[^A-Za-z0-9|]*/)[0];
  const trail = token.slice(lead.length).match(/[^A-Za-z0-9'|]*$/)[0];
  let core = token.slice(lead.length, token.length - trail.length);
  if (!core) return token;
  if (core === '|') return `${lead}I${trail}`;
  core = core.replace(/^\|(?=[A-Z])/, 'I'); // "|" colado no início é "I"
  const up = core.toUpperCase();
  if (up.length < 2) return lead + core + trail;
  const own = wordFreq(up);
  // palavra que existe só é trocada se a leitura é incerta e a troca é bem mais comum (ex.: PAYS → DAYS)
  if (own && ((conf >= 90 && !/\d/.test(up)) || up.length < 3 && !/\d/.test(up))) return lead + core + trail;
  let cands = swaps(up, 1);
  if (!cands.size && !own && (up.length >= 5 || /\d/.test(up))) cands = swaps(up, 2); // duas trocas só em palavra longa ou com dígito: em palavra curta sobra palpite
  if (!cands.size) return lead + core + trail;
  const [[word, f], second] = [...cands].sort((a, b) => b[1] - a[1]);
  if (/^\d+$/.test(core) && f < 1e5) return lead + core + trail; // número de verdade só vira palavra se for palavra muito comum (IS, SO)
  const clear = f >= 5 * (second?.[1] ?? 0); // candidata única ou bem mais comum que a segunda
  if (own) return clear && f >= 20 * own ? lead + word + trail : lead + core + trail;
  return clear ? lead + word + trail : lead + core + trail;
}
