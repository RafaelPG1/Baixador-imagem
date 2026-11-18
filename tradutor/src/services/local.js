import { TranslationError } from '../errors.js';
import { loopedTail } from '../repeticao.js';

// Formato de prompt do TranslateGemma. Fica numa constante para ajustar sem mexer no resto.
const prompt = (text) =>
  'You are a professional English (en) to Brazilian Portuguese (pt-BR) translator. ' +
  'Your goal is to accurately convey the meaning and nuances of the original English text ' +
  'while adhering to Portuguese grammar, vocabulary, and cultural sensitivities.\n' +
  'Produce only the Portuguese translation, without any additional explanations or commentary. ' +
  'Please translate the following English text into Portuguese:\n\n\n' +
  text;

const fail = (code, message, status = 502) => new TranslationError(code, message, status);

// Níveis de amostragem. O 0 (temperatura 0, igual ao que sempre foi usado) dá a tradução mais fiel e repetível; é o de todas as
// chamadas normais. Os níveis 1 e 2 só são usados DEPOIS de uma repetição ou de uma resposta cortada, para quebrar o laço:
// um pouco de aleatoriedade (com a semente fixa, o resultado continua repetível) e penalidade maior para token repetido.
const SAMPLING = [
  { temperature: 0 },
  { temperature: 0.3, top_k: 64, top_p: 0.95, repeat_penalty: 1.18, seed: 7 },
  { temperature: 0.6, top_k: 64, top_p: 0.95, repeat_penalty: 1.3, seed: 11 },
];
export const RETRY_LEVELS = SAMPLING.length;

// Teto de tokens de saída proporcional ao texto: uma tradução nunca precisa de muito mais que o original (e texto em
// MAIÚSCULAS, o normal em mangá, gasta mais tokens por letra). Sem teto, um laço ocupa o notebook até o limite de contexto.
export const numPredictFor = (text) => Math.min(2048, Math.max(160, Math.ceil(String(text).length * 0.8) + 96));

export function createLocal({ model = 'translategemma:4b', url = 'http://127.0.0.1:11434', fetchFn = fetch } = {}) {
  return {
    name: `Local (${model})`,
    // opts.retry: 0 = normal; 1 e 2 = amostragem alternativa depois de uma repetição (veja SAMPLING).
    async translate(text, opts = {}) {
      let out = '';
      let done = false;
      let doneReason;
      let loopAbort = false;
      const sampling = SAMPLING[Math.min(Math.max(Number(opts.retry) || 0, 0), SAMPLING.length - 1)];
      const stop = new AbortController();
      try {
        const res = await fetchFn(`${url}/api/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            model,
            messages: [{ role: 'user', content: prompt(text) }],
            stream: true, // com stream o servidor responde na hora e não estoura o timeout de cabeçalho em textos longos
            keep_alive: '10m',
            options: { ...sampling, num_ctx: 4096, num_predict: numPredictFor(text) },
          }),
          signal: AbortSignal.any([AbortSignal.timeout(10 * 60_000), stop.signal]),
        });
        if (!res.ok) {
          const detail = (await res.json().catch(() => ({}))).error ?? '';
          if (res.status === 404 || /not found/i.test(detail)) {
            throw fail('MODEL_MISSING', `O modelo ${model} não está instalado. Rode: ollama pull ${model}`);
          }
          throw fail('UPSTREAM_ERROR', `O Ollama respondeu com erro (HTTP ${res.status}). ${detail}`.trim());
        }
        const decoder = new TextDecoder();
        let buffer = '';
        const eat = (line) => {
          if (!line.trim()) return;
          const part = JSON.parse(line);
          if (part.error) {
            // limite de tokens repetidos do próprio Ollama (30 iguais seguidos): laço do modelo ou repetição legítima da origem
            if (/repeat limit/i.test(part.error)) throw Object.assign(fail('REPETITION', `O Ollama interrompeu a tradução por repetição de tokens (${part.error}).`), { partial: out });
            throw fail('UPSTREAM_ERROR', `O Ollama falhou: ${part.error}`);
          }
          out += part.message?.content ?? '';
          if (part.done) { done = true; doneReason = part.done_reason; }
          // laço no meio da geração: não espera o Ollama (ou o teto de tokens) para desistir
          if (!done && loopedTail(out, text)) { loopAbort = true; stop.abort(); }
        };
        for await (const chunk of res.body) {
          buffer += decoder.decode(chunk, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();
          lines.forEach(eat);
        }
        eat(buffer);
      } catch (err) {
        if (loopAbort) throw Object.assign(fail('REPETITION', 'O modelo entrou em repetição e a tradução foi interrompida.'), { partial: out });
        if (err instanceof TranslationError) throw err;
        if (err.name === 'TimeoutError') throw fail('UPSTREAM_TIMEOUT', 'A tradução local demorou mais de 10 minutos e foi cancelada. Tente um texto menor ou o modelo 4b.');
        if (err instanceof SyntaxError) throw fail('UPSTREAM_ERROR', 'O Ollama devolveu uma resposta ilegível.');
        throw fail('UPSTREAM_UNREACHABLE', 'O Ollama não está rodando. Abra o Ollama e tente de novo.');
      }
      // Resposta que não terminou NUNCA vale como tradução: cortada por tamanho, ou a conexão acabou sem o fim da resposta.
      if (!done) throw Object.assign(fail('TRUNCATED', 'A resposta do Ollama terminou antes do fim (cortada no meio); não foi usada.'), { partial: out });
      if (doneReason && doneReason !== 'stop') throw Object.assign(fail('TRUNCATED', `A resposta do Ollama foi cortada (${doneReason}); não foi usada.`), { partial: out });
      out = out.trim();
      if (!out) throw fail('EMPTY_RESPONSE', 'O modelo não devolveu tradução. Tente de novo.');
      return out;
    },
  };
}
