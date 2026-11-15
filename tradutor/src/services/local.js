import { TranslationError } from '../errors.js';

// Formato de prompt do TranslateGemma. Fica numa constante para ajustar sem mexer no resto.
const prompt = (text) =>
  'You are a professional English (en) to Brazilian Portuguese (pt-BR) translator. ' +
  'Your goal is to accurately convey the meaning and nuances of the original English text ' +
  'while adhering to Portuguese grammar, vocabulary, and cultural sensitivities.\n' +
  'Produce only the Portuguese translation, without any additional explanations or commentary. ' +
  'Please translate the following English text into Portuguese:\n\n\n' +
  text;

const fail = (code, message, status = 502) => new TranslationError(code, message, status);

export function createLocal({ model = 'translategemma:4b', url = 'http://127.0.0.1:11434', fetchFn = fetch } = {}) {
  return {
    name: `Local (${model})`,
    async translate(text) {
      let out = '';
      try {
        const res = await fetchFn(`${url}/api/chat`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            model,
            messages: [{ role: 'user', content: prompt(text) }],
            stream: true, // com stream o servidor responde na hora e não estoura o timeout de cabeçalho em textos longos
            keep_alive: '10m',
            options: { temperature: 0, num_ctx: 4096 },
          }),
          signal: AbortSignal.timeout(10 * 60_000),
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
          if (part.error) throw fail('UPSTREAM_ERROR', `O Ollama falhou: ${part.error}`);
          out += part.message?.content ?? '';
        };
        for await (const chunk of res.body) {
          buffer += decoder.decode(chunk, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop();
          lines.forEach(eat);
        }
        eat(buffer);
      } catch (err) {
        if (err instanceof TranslationError) throw err;
        if (err.name === 'TimeoutError') throw fail('UPSTREAM_TIMEOUT', 'A tradução local demorou mais de 10 minutos e foi cancelada. Tente um texto menor ou o modelo 4b.');
        if (err instanceof SyntaxError) throw fail('UPSTREAM_ERROR', 'O Ollama devolveu uma resposta ilegível.');
        throw fail('UPSTREAM_UNREACHABLE', 'O Ollama não está rodando. Abra o Ollama e tente de novo.');
      }
      out = out.trim();
      if (!out) throw fail('EMPTY_RESPONSE', 'O modelo não devolveu tradução. Tente de novo.');
      return out;
    },
  };
}
