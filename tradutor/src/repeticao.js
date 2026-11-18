// Detecção de repetição em tradução gerada por modelo.
//
// Por que existe: o Ollama aborta a geração quando o MESMO token (sem espaços nas pontas) sai mais de 30 vezes seguidas
// ("prediction aborted, token repeat limit reached"; o limite é fixo no servidor e não dá para mudar pela API). Isso acontece em
// dois casos bem diferentes:
//   1. o modelo entrou num laço (comum com temperatura 0, que sempre escolhe o token mais provável), ou
//   2. o texto de origem tem repetição de verdade ("AAAAAAAAAAAAH", "HA HA HA HA ...", "..........") e a tradução a repete.
// Aqui ficam os testes para separar os dois casos e achar o laço cedo (sem esperar minutos no notebook).

const BLOCK = /(.{2,60}?)\1{7,}/gsu; // um trecho de 2 a 60 caracteres repetido 8 vezes ou mais, colado
const CHARRUN = /(.)\1{15,}/gsu; // um mesmo caractere 16 vezes ou mais

// Tamanho (em caracteres) da maior repetição colada do texto.
export function longestRun(text) {
  const t = String(text ?? '');
  let max = 0;
  for (const m of t.matchAll(BLOCK)) max = Math.max(max, m[0].length);
  for (const m of t.matchAll(CHARRUN)) max = Math.max(max, m[0].length);
  return max;
}

// A origem já tem repetição própria (risada, grito, reticências)? Então repetição na tradução pode ser legítima.
export const hasRuns = (text) => longestRun(text) >= 24;

// O final do texto gerado é um trecho repetido sem parar ("a casa da casa da casa da casa ...")? Só vale quando a origem NÃO
// tem repetição própria. Exige 8 repetições somando 40+ caracteres, para não confundir "ha ha ha ha ha ha" com laço.
export function loopedTail(output, source = '') {
  const tail = String(output ?? '').slice(-240);
  if (tail.length < 48 || hasRuns(source)) return false;
  const m = /(.{2,60}?)\1{7,}$/su.exec(tail);
  return Boolean(m) && m[0].length >= 40;
}

// Resposta pronta que parece defeituosa: laço no meio do texto, dezenas de espaços ou muito maior do que uma tradução EN→PT
// poderia ser (o modelo continuou escrevendo).
export function degenerate(source, translation) {
  const s = String(source ?? ''), t = String(translation ?? '');
  if (/\s{60,}/.test(t)) return true;
  if (t.length > s.length * 3 + 120) return true;
  return !hasRuns(s) && longestRun(t.replace(/\s+/g, ' ')) >= 40;
}

// Trecho repetitivo na ORIGEM, reduzido antes de ir ao modelo: nada se perde de sentido ("AAAAAAAAAAAAAH" → "AAAAAAH"), e a
// resposta deixa de ter dezenas de tokens iguais seguidos, que é o que dispara o limite do Ollama.
export const squeezeRuns = (text) =>
  String(text ?? '')
    .replace(/(.)\1{7,}/gsu, (_, c) => c.repeat(6)) // AAAAAAAAAAH, ........., !!!!!!!!!!
    .replace(/(?<![\p{L}'])([\p{L}']{1,12})((?:[\s,.!?-]+\1(?![\p{L}'])){5,})/giu, (_, w) => Array(5).fill(w).join(' ')); // HA HA HA HA HA HA HA
