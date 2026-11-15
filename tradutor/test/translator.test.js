import test from 'node:test';
import assert from 'node:assert/strict';
import { validate, translate, MAX_CHARS } from '../src/translator.js';
import { chunkLine, createMyMemory } from '../src/services/mymemory.js';
import { createGemini } from '../src/services/gemini.js';
import { createDeepL } from '../src/services/deepl.js';
import { createLocal } from '../src/services/local.js';
import { createEngines, defaultEngineId } from '../src/services/index.js';
import { TranslationError } from '../src/errors.js';

const rejectsWith = (promise, code) => assert.rejects(promise, (e) => e.code === code);
const throwsWith = (fn, code) => assert.throws(fn, (e) => e.code === code);

test('validate: rejeita vazio, rejeita texto longo, apara espaços', () => {
  throwsWith(() => validate('   '), 'EMPTY_TEXT');
  throwsWith(() => validate(null), 'EMPTY_TEXT');
  throwsWith(() => validate('a'.repeat(MAX_CHARS + 1)), 'TEXT_TOO_LONG');
  assert.equal(validate('  hi  '), 'hi');
});

test('chunkLine: cada pedaço cabe no limite e nada se perde', () => {
  const sentences = Array.from({ length: 40 }, (_, i) => `This is sentence number ${i} of a long paragraph.`).join(' ');
  const chunks = chunkLine(sentences);
  assert.ok(chunks.length > 1);
  assert.ok(chunks.every((c) => Buffer.byteLength(c) <= 450));
  assert.equal(chunks.join(' '), sentences);

  const url = 'https://example.com/' + 'a'.repeat(1200);
  const pieces = chunkLine(url);
  assert.ok(pieces.every((c) => Buffer.byteLength(c) <= 450));
  assert.equal(pieces.join(''), url);

  const accents = 'ação '.repeat(300).trim();
  assert.ok(chunkLine(accents).every((c) => Buffer.byteLength(c) <= 450));
});

const okFetch = (log = []) => async (url) => {
  log.push(url);
  const q = url.searchParams.get('q');
  return { status: 200, json: async () => ({ responseStatus: 200, responseData: { translatedText: `PT(${q}) &#39;ok&#39;` } }) };
};

test('MyMemory: preserva parágrafos, decodifica entidades e envia en|pt-BR', async () => {
  const log = [];
  const out = await createMyMemory({ fetchFn: okFetch(log), email: 'a@b.c' }).translate('Hello.\n\nBye.');
  assert.equal(out, "PT(Hello.) 'ok'\n\nPT(Bye.) 'ok'");
  assert.equal(log[0].searchParams.get('langpair'), 'en|pt-BR');
  assert.equal(log[0].searchParams.get('de'), 'a@b.c');
});

test('MyMemory: limite diário vira RATE_LIMITED; falha de rede vira UPSTREAM_UNREACHABLE', async () => {
  const quota = async () => ({ status: 200, json: async () => ({ responseStatus: 429 }) });
  await rejectsWith(createMyMemory({ fetchFn: quota }).translate('Hi'), 'RATE_LIMITED');
  const down = async () => {
    throw new Error('offline');
  };
  await rejectsWith(createMyMemory({ fetchFn: down }).translate('Hi'), 'UPSTREAM_UNREACHABLE');
});

test('Gemini: envia chave no cabeçalho e devolve o texto', async () => {
  let seen;
  const fetchFn = async (url, opts) => {
    seen = { url: String(url), opts };
    return { ok: true, status: 200, json: async () => ({ candidates: [{ content: { parts: [{ text: 'Olá, mundo.' }] } }] }) };
  };
  const out = await createGemini({ apiKey: 'k', model: 'm', fetchFn }).translate('Hello, world.');
  assert.equal(out, 'Olá, mundo.');
  assert.equal(seen.opts.headers['x-goog-api-key'], 'k');
  assert.ok(seen.url.includes('/models/m:generateContent'));
  assert.equal(JSON.parse(seen.opts.body).contents[0].parts[0].text, 'Hello, world.');
});

test('Gemini: 429, erro HTTP e resposta vazia viram erros claros', async () => {
  const reply = (status, body = {}) => async () => ({ ok: status < 400, status, json: async () => body });
  await rejectsWith(createGemini({ apiKey: 'k', fetchFn: reply(429) }).translate('Hi'), 'RATE_LIMITED');
  await rejectsWith(createGemini({ apiKey: 'k', fetchFn: reply(403) }).translate('Hi'), 'UPSTREAM_ERROR');
  await rejectsWith(createGemini({ apiKey: 'k', fetchFn: reply(200, {}) }).translate('Hi'), 'EMPTY_RESPONSE');
});

test('DeepL: envia o texto inteiro numa chamada, en→PT-BR, e escolhe o host pela chave', async () => {
  const calls = [];
  const fetchFn = async (url, opts) => {
    calls.push({ url, opts });
    return { ok: true, status: 200, json: async () => ({ translations: [{ text: ' Eu topo. Vamos lá. ' }] }) };
  };
  const text = "I'm down for it.\n\nLet's go.";
  assert.equal(await createDeepL({ apiKey: 'abc:fx', fetchFn }).translate(text), 'Eu topo. Vamos lá.');
  await createDeepL({ apiKey: 'abc', fetchFn }).translate('Hi');
  assert.equal(calls[0].url, 'https://api-free.deepl.com/v2/translate');
  assert.equal(calls[1].url, 'https://api.deepl.com/v2/translate');
  assert.equal(calls[0].opts.headers.authorization, 'DeepL-Auth-Key abc:fx');
  const body = JSON.parse(calls[0].opts.body);
  assert.deepEqual(body.text, [text]);
  assert.equal(body.source_lang, 'EN');
  assert.equal(body.target_lang, 'PT-BR');
  assert.equal(calls.length, 2);
});

test('DeepL: 456, 429, 403, 500, resposta vazia e rede viram erros claros', async () => {
  const reply = (status, body = {}) => async () => ({ ok: status < 400, status, json: async () => body });
  const run = (fetchFn) => createDeepL({ apiKey: 'k', fetchFn }).translate('Hi');
  await rejectsWith(run(reply(456)), 'RATE_LIMITED');
  await rejectsWith(run(reply(429)), 'RATE_LIMITED');
  await rejectsWith(run(reply(403)), 'UPSTREAM_ERROR');
  await rejectsWith(run(reply(500)), 'UPSTREAM_ERROR');
  await rejectsWith(run(reply(200, { translations: [] })), 'EMPTY_RESPONSE');
  await rejectsWith(run(async () => { throw new Error('offline'); }), 'UPSTREAM_UNREACHABLE');
});

// Resposta em fluxo do Ollama: uma linha JSON por pedaço, cortada em lugares arbitrários.
const ndjson = (parts, cut = 7) => {
  const raw = new TextEncoder().encode(parts.map((p) => JSON.stringify(p)).join('\n') + '\n');
  return (async function* () {
    for (let i = 0; i < raw.length; i += cut) yield raw.slice(i, i + cut);
  })();
};
const ollama = (parts, status = 200) => async () => ({ ok: status < 400, status, body: ndjson(parts), json: async () => parts[0] });

test('Local: monta o prompt en→pt-BR, junta o fluxo e usa o modelo e a URL configurados', async () => {
  let seen;
  const fetchFn = async (url, opts) => {
    seen = { url, body: JSON.parse(opts.body) };
    return { ok: true, status: 200, body: ndjson([{ message: { content: 'Eu ' } }, { message: { content: 'topo.' } }, { done: true }]) };
  };
  const out = await createLocal({ model: 'm:1', url: 'http://x:1', fetchFn }).translate("I'm down for it.");
  assert.equal(out, 'Eu topo.');
  assert.equal(seen.url, 'http://x:1/api/chat');
  assert.equal(seen.body.model, 'm:1');
  assert.equal(seen.body.options.temperature, 0);
  assert.ok(seen.body.messages[0].content.includes('(pt-BR)'));
  assert.ok(seen.body.messages[0].content.endsWith("\n\n\nI'm down for it."));
});

test('Local: modelo ausente, Ollama parado, erro no meio do fluxo e resposta vazia', async () => {
  const run = (fetchFn) => createLocal({ model: 'm:1', fetchFn }).translate('Hi');
  await rejectsWith(run(ollama([{ error: "model 'm:1' not found" }], 404)), 'MODEL_MISSING');
  await rejectsWith(run(async () => { throw new TypeError('fetch failed'); }), 'UPSTREAM_UNREACHABLE');
  await rejectsWith(run(ollama([{ message: { content: 'a' } }, { error: 'out of memory' }])), 'UPSTREAM_ERROR');
  await rejectsWith(run(ollama([{ done: true }])), 'EMPTY_RESPONSE');
  await assert.rejects(run(ollama([{ error: 'x' }], 500)), /Ollama/);
});

test('createEngines: só entram os motores com chave; local e mymemory sempre', () => {
  assert.deepEqual(Object.keys(createEngines({})), ['local', 'mymemory']);
  assert.deepEqual(Object.keys(createEngines({ DEEPL_API_KEY: 'a', GEMINI_API_KEY: 'b' })), ['local', 'deepl', 'gemini', 'mymemory']);
  assert.equal(createEngines({ LOCAL_MODEL: 'translategemma:12b' }).local.name, 'Local (translategemma:12b)');
});

test('defaultEngineId: explícito, local se vazio, valida', () => {
  const env = { DEEPL_API_KEY: 'a' };
  assert.equal(defaultEngineId(createEngines(env), env), 'local');
  assert.equal(defaultEngineId(createEngines(env), { ...env, TRANSLATION_ENGINE: ' DeepL ' }), 'deepl');
  assert.throws(() => defaultEngineId(createEngines({}), { TRANSLATION_ENGINE: 'deepl' }), /exige a chave/);
  assert.throws(() => defaultEngineId(createEngines({}), { TRANSLATION_ENGINE: 'xyz' }), /inválido/);
});

test('translate: valida antes de chamar o motor e devolve qual motor traduziu', async () => {
  let called = false;
  const engines = { fake: { name: 'Fake', translate: async (t) => ((called = true), `PT:${t}`) } };
  await rejectsWith(translate('  ', 'fake', engines), 'EMPTY_TEXT');
  assert.equal(called, false);
  assert.deepEqual(await translate(' Hi ', 'fake', engines), { translation: 'PT:Hi', engine: 'fake', provider: 'Fake' });
});

test('translate: motor desconhecido é recusado e falha do motor não troca por outro', async () => {
  const calls = [];
  const engines = {
    broken: { name: 'Broken', translate: async () => { calls.push('broken'); throw new TranslationError('UPSTREAM_ERROR', 'caiu', 502); } },
    other: { name: 'Other', translate: async () => { calls.push('other'); return 'x'; } },
  };
  await rejectsWith(translate('Hi', 'broken', engines), 'UPSTREAM_ERROR');
  assert.deepEqual(calls, ['broken']);
  for (const bad of ['nope', '__proto__', 'toString', 42, {}]) await rejectsWith(translate('Hi', bad, engines), 'UNKNOWN_ENGINE');
});
