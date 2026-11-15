import { TranslationError } from '../errors.js';

const LIMIT = 450; // a API aceita 500 bytes por requisição
const BATCH = 4; // requisições em paralelo
const bytes = (s) => Buffer.byteLength(s);

// Junta unidades até o limite; unidade maior que o limite é quebrada por `split`.
function pack(units, sep, split) {
  const out = [];
  let cur = '';
  for (const u of units) {
    for (const p of bytes(u) > LIMIT ? split(u) : [u]) {
      const next = cur ? cur + sep + p : p;
      if (bytes(next) <= LIMIT) cur = next;
      else {
        out.push(cur);
        cur = p;
      }
    }
  }
  if (cur) out.push(cur);
  return out;
}

// Quebra uma linha em frases; frase longa em palavras; palavra longa (URL) em caracteres.
export function chunkLine(line) {
  return pack(line.split(/(?<=[.!?…])\s+/), ' ', (s) =>
    pack(s.split(/\s+/), ' ', (w) => pack(Array.from(w), '', () => [])),
  );
}

const ENTITIES = { quot: '"', amp: '&', lt: '<', gt: '>', apos: "'" };
const decode = (s) =>
  s.replace(/&#(\d+);|&(quot|amp|lt|gt|apos);/g, (_, n, name) => (n ? String.fromCodePoint(Number(n)) : ENTITIES[name]));

export function createMyMemory({ email, fetchFn = fetch } = {}) {
  async function translateChunk(chunk) {
    const url = new URL('https://api.mymemory.translated.net/get');
    url.search = new URLSearchParams({ q: chunk, langpair: 'en|pt-BR', ...(email && { de: email }) });
    let res;
    try {
      res = await fetchFn(url, { signal: AbortSignal.timeout(15_000) });
    } catch {
      throw new TranslationError('UPSTREAM_UNREACHABLE', 'Não consegui falar com o serviço de tradução. Verifique a conexão e tente de novo.', 502);
    }
    const data = await res.json().catch(() => ({}));
    const status = Number(data.responseStatus ?? res.status);
    if (status === 429) {
      throw new TranslationError('RATE_LIMITED', 'O limite diário gratuito do MyMemory acabou. Tente amanhã ou defina MYMEMORY_EMAIL para aumentar o limite.', 429);
    }
    if (status !== 200) {
      throw new TranslationError('UPSTREAM_ERROR', `O serviço de tradução respondeu com erro (${status}). Tente de novo.`, 502);
    }
    return decode(data.responseData?.translatedText ?? '');
  }

  return {
    name: 'MyMemory',
    async translate(text) {
      const lines = text.split('\n').map((l) => (l.trim() ? chunkLine(l.trim()) : []));
      const flat = lines.flat();
      const done = [];
      for (let i = 0; i < flat.length; i += BATCH) {
        done.push(...(await Promise.all(flat.slice(i, i + BATCH).map(translateChunk))));
      }
      let at = 0;
      return lines.map((l) => done.slice(at, (at += l.length)).join(' ')).join('\n');
    },
  };
}
