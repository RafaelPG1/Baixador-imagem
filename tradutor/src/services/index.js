import { createDeepL } from './deepl.js';
import { createGemini } from './gemini.js';
import { createLocal } from './local.js';
import { createMyMemory } from './mymemory.js';

// Cada fábrica devolve undefined quando falta a chave do motor, e ele não fica disponível.
const factories = {
  local: (env) => createLocal({ model: env.LOCAL_MODEL || undefined, url: env.OLLAMA_URL || undefined }),
  deepl: (env) => env.DEEPL_API_KEY && createDeepL({ apiKey: env.DEEPL_API_KEY }),
  gemini: (env) => env.GEMINI_API_KEY && createGemini({ apiKey: env.GEMINI_API_KEY, model: env.GEMINI_MODEL || undefined }),
  mymemory: (env) => createMyMemory({ email: env.MYMEMORY_EMAIL || undefined }),
};

// { id: provider } só dos motores disponíveis.
export function createEngines(env = process.env) {
  const engines = {};
  for (const [id, make] of Object.entries(factories)) {
    const provider = make(env);
    if (provider) engines[id] = provider;
  }
  return engines;
}

// Motor padrão: sempre explícito. TRANSLATION_ENGINE, ou "local" se vazio. Nunca troca sozinho.
export function defaultEngineId(engines, env = process.env) {
  const id = env.TRANSLATION_ENGINE?.trim().toLowerCase() || 'local';
  if (!(id in factories)) throw new Error(`TRANSLATION_ENGINE="${id}" é inválido. Use: ${Object.keys(factories).join(', ')}.`);
  if (!engines[id]) throw new Error(`O motor ${id} exige a chave ${{ deepl: 'DEEPL_API_KEY', gemini: 'GEMINI_API_KEY' }[id]} no arquivo .env do Baixador.`);
  return id;
}
