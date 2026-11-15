import { TranslationError } from '../errors.js';

// Chaves do plano gratuito terminam em ":fx" e usam outro endereço.
const host = (key) => (key.endsWith(':fx') ? 'api-free.deepl.com' : 'api.deepl.com');

export function createDeepL({ apiKey, fetchFn = fetch }) {
  return {
    name: 'DeepL',
    async translate(text) {
      let res;
      try {
        res = await fetchFn(`https://${host(apiKey)}/v2/translate`, {
          method: 'POST',
          headers: { 'content-type': 'application/json', authorization: `DeepL-Auth-Key ${apiKey}` },
          body: JSON.stringify({
            text: [text], // o texto inteiro numa só chamada, para o motor ver o contexto
            source_lang: 'EN',
            target_lang: 'PT-BR',
            model_type: 'prefer_quality_optimized', // modelo mais novo quando existir para o par; senão o padrão
            preserve_formatting: true,
          }),
          signal: AbortSignal.timeout(30_000),
        });
      } catch {
        throw new TranslationError('UPSTREAM_UNREACHABLE', 'Não consegui falar com o DeepL. Verifique a conexão e tente de novo.', 502);
      }
      if (res.status === 456) {
        throw new TranslationError('RATE_LIMITED', 'A cota mensal do DeepL acabou. Ela renova no próximo ciclo ou com um plano maior.', 429);
      }
      if (res.status === 429) {
        throw new TranslationError('RATE_LIMITED', 'O DeepL recebeu requisições demais. Espere um pouco e tente de novo.', 429);
      }
      if (res.status === 403) {
        throw new TranslationError('UPSTREAM_ERROR', 'O DeepL recusou a chave. Confira DEEPL_API_KEY.', 502);
      }
      if (!res.ok) {
        throw new TranslationError('UPSTREAM_ERROR', `O DeepL respondeu com erro (HTTP ${res.status}). Tente de novo.`, 502);
      }
      const data = await res.json().catch(() => ({}));
      const out = data.translations?.[0]?.text?.trim();
      if (!out) throw new TranslationError('EMPTY_RESPONSE', 'O serviço não devolveu tradução. Tente de novo.', 502);
      return out;
    },
  };
}
