import { TranslationError } from './errors.js';
import { createEngines, defaultEngineId } from './services/index.js';

export const MAX_CHARS = Number(process.env.MAX_CHARS) || 5000;

export function validate(text) {
  if (typeof text !== 'string' || !text.trim()) {
    throw new TranslationError('EMPTY_TEXT', 'Digite ou cole um texto em inglês para traduzir.', 400);
  }
  if (text.length > MAX_CHARS) {
    throw new TranslationError('TEXT_TOO_LONG', `O texto passa de ${MAX_CHARS} caracteres. Divida em partes menores.`, 413);
  }
  return text.trim();
}

let registry;
export const getEngines = () => (registry ??= createEngines(process.env));
// O registro lê process.env uma vez; quem muda o ambiente depois (o Baixador passa as chaves ao chamar) pede para refazê-lo.
export const resetEngines = () => { registry = undefined; };
export const getDefaultEngine = () => defaultEngineId(getEngines(), process.env);

// Usa exatamente o motor pedido; se ele falhar, o erro sobe. Nenhum outro motor é tentado.
// `opts` (ex.: { retry: 1 }) vai para o motor; os de nuvem o ignoram.
export async function translate(text, engineId, engines = getEngines(), opts = {}) {
  const clean = validate(text);
  const id = engineId ?? getDefaultEngine();
  if (typeof id !== 'string' || !Object.hasOwn(engines, id)) {
    throw new TranslationError('UNKNOWN_ENGINE', 'Esse motor não está disponível. Escolha outro na lista.', 400);
  }
  return { translation: await engines[id].translate(clean, opts), engine: id, provider: engines[id].name };
}
