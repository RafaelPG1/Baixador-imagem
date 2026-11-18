// "prediction aborted, token repeat limit reached": o que o Ollama faz, como o tradutor reage e o que NUNCA pode ser salvo.
import test from 'node:test';
import assert from 'node:assert/strict';
import { createLocal, numPredictFor, RETRY_LEVELS } from '../src/services/local.js';
import { degenerate, hasRuns, longestRun, loopedTail, squeezeRuns } from '../src/repeticao.js';
import { buildBatchText, translateBatch, translateOne, splitSentences, makeBatches } from '../src/vision/translate.js';
import { TranslationError } from '../src/errors.js';

const enc = new TextEncoder();
const msg = (t, extra = {}) => ({ message: { content: t }, ...extra });
const DONE = msg('', { done: true, done_reason: 'stop' });
// fetch falso: devolve os pedaços como o Ollama (uma linha JSON por pedaço) e guarda o corpo enviado
function ollama(chunks, seen = []) {
  return async (url, init) => {
    seen.push(JSON.parse(init.body));
    return { ok: true, status: 200, body: (async function* () { for (const c of chunks) yield enc.encode(`${JSON.stringify(c)}\n`); })() };
  };
}
const code = (p) => p.then(() => null, (e) => e.code);

test('resposta que não terminou nunca vira tradução: sem done, ou cortada por tamanho', async () => {
  assert.equal(await code(createLocal({ fetchFn: ollama([msg('NÃO ACREDITO QUE VOCÊ FE')]) }).translate('I CAN\'T BELIEVE YOU')), 'TRUNCATED');
  assert.equal(await code(createLocal({ fetchFn: ollama([msg('NÃO ACRE'), msg('', { done: true, done_reason: 'length' })]) }).translate('X')), 'TRUNCATED');
  const ok = await createLocal({ fetchFn: ollama([msg('NÃO ACREDITO '), msg('QUE VOCÊ FEZ ISSO!'), DONE]) }).translate('I CAN\'T BELIEVE YOU DID THAT!');
  assert.equal(ok, 'NÃO ACREDITO QUE VOCÊ FEZ ISSO!');
  // versões antigas do Ollama não mandam done_reason: com done:true continua valendo
  assert.equal(await createLocal({ fetchFn: ollama([msg('OI'), msg('', { done: true })]) }).translate('HI'), 'OI');
});

test('o erro de repetição do Ollama vira REPETITION (recuperável), com o que já tinha sido gerado; outros erros continuam UPSTREAM_ERROR', async () => {
  const e = await createLocal({ fetchFn: ollama([msg('ha ha ha'), { error: 'prediction aborted, token repeat limit reached' }]) }).translate('HA').catch((x) => x);
  assert.equal(e.code, 'REPETITION');
  assert.equal(e.partial, 'ha ha ha');
  assert.match(e.message, /repetição de tokens/);
  assert.equal(await code(createLocal({ fetchFn: ollama([{ error: 'out of memory' }]) }).translate('HA')), 'UPSTREAM_ERROR');
});

test('opções enviadas: normal = temperatura 0 (fidelidade), com teto de tokens proporcional; retentativa muda a amostragem', async () => {
  const seen = [];
  const local = createLocal({ fetchFn: ollama([msg('OI'), DONE], seen) });
  await local.translate('HELLO THERE');
  await local.translate('HELLO THERE', { retry: 1 });
  await local.translate('HELLO THERE', { retry: 2 });
  await local.translate('HELLO THERE', { retry: 99 });
  const [n0, n1, n2, n99] = seen.map((b) => b.options);
  assert.deepEqual({ ...n0 }, { temperature: 0, num_ctx: 4096, num_predict: numPredictFor('HELLO THERE') });
  assert.equal(n1.temperature, 0.3); assert.equal(n1.repeat_penalty, 1.18); assert.equal(n1.seed, 7);
  assert.equal(n2.temperature, 0.6); assert.equal(n2.repeat_penalty, 1.3);
  assert.deepEqual(n99, n2, 'nível acima do último usa o último');
  assert.equal(RETRY_LEVELS, 3);
  // teto: nunca menos que 160, cresce com o texto (MAIÚSCULAS gastam mais tokens), nunca passa de 2048
  assert.equal(numPredictFor('A'), 160);
  assert.equal(numPredictFor('x'.repeat(1500)), 1296);
  assert.equal(numPredictFor('x'.repeat(100000)), 2048);
});

test('laço do modelo no meio da geração: a chamada é abortada cedo (não espera minutos) e vira REPETITION', async () => {
  let lidos = 0;
  const fetchFn = async (url, init) => ({
    ok: true, status: 200,
    body: (async function* () {
      yield enc.encode(`${JSON.stringify(msg('A casa grande fica no alto da colina. '))}\n`);
      for (let i = 0; i < 100000; i++) {
        if (init.signal.aborted) throw init.signal.reason ?? new Error('abortado');
        lidos++;
        yield enc.encode(`${JSON.stringify(msg('da casa '))}\n`);
        await new Promise((r) => setImmediate(r));
      }
    })(),
  });
  const e = await createLocal({ fetchFn }).translate('THE BIG HOUSE STANDS ON THE HILL.').catch((x) => x);
  assert.equal(e.code, 'REPETITION');
  assert.ok(lidos < 60, `desistiu depois de ${lidos} pedaços`);
  assert.match(e.partial, /da casa da casa/);
});

test('repetição que está NA ORIGEM (risada, grito, reticências) não é tratada como laço', () => {
  const risada = 'HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA HA';
  assert.equal(hasRuns(risada), true);
  assert.equal(loopedTail('Rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá rá', risada), false);
  assert.equal(degenerate(risada, 'RÁ '.repeat(20)), false);
  // laço de verdade, com origem normal
  const laco = `A casa grande fica no alto. ${'da casa '.repeat(12)}`;
  assert.equal(loopedTail(laco, 'THE BIG HOUSE'), true);
  assert.equal(degenerate('THE BIG HOUSE', laco), true);
  // seis risadas curtas não são laço
  assert.equal(loopedTail(`Ele riu muito, ${'ha '.repeat(6)}`, 'HE LAUGHED A LOT HA HA HA'), false);
  // resposta muito maior que o original, ou dezenas de espaços
  assert.equal(degenerate('HI', 'x'.repeat(200)), true);
  assert.equal(degenerate('HELLO', `OLÁ${' '.repeat(80)}fim`), true);
  assert.equal(degenerate('I CAN\'T BELIEVE YOU DID THAT!', 'NÃO ACREDITO QUE VOCÊ FEZ ISSO!'), false);
  assert.ok(longestRun('AAAAAAAAAAAAAAAAAAAAAAAAH') >= 24);
});

test('squeezeRuns: reduz a repetição da origem antes do modelo, sem mudar o sentido nem textos normais', () => {
  assert.equal(squeezeRuns('AAAAAAAAAAAAAAAH!'), 'AAAAAAH!');
  assert.equal(squeezeRuns('WAIT.................'), 'WAIT......');
  assert.equal(squeezeRuns('HA HA HA HA HA HA HA HA HA HA!'), 'HA HA HA HA HA!');
  assert.equal(squeezeRuns('NO, NO, NO, NO, NO, NO, NO!'), 'NO NO NO NO NO!');
  for (const normal of ["I CAN'T BELIEVE YOU DID THAT!", 'WHAT?!', 'WAIT... WHAT?', 'HA HA HA', 'NO, NO, NO.', '139', 'Zzz...']) assert.equal(squeezeRuns(normal), normal, normal);
  // e o lote que vai ao modelo já sai reduzido
  assert.equal(buildBatchText({ context: [], units: [{ source: 'AAAAAAAAAAAAAAAH' }, { source: 'OK' }] }), '[1] AAAAAAH\n[2] OK');
});

const rep = (partial = 'ha ha ha') => Object.assign(new TranslationError('REPETITION', 'O Ollama interrompeu a tradução por repetição de tokens.', 502), { partial });

test('lote que repete: cada fala vai sozinha e uma fala ruim não derruba as outras (nem o capítulo)', async () => {
  const batch = { context: [], units: [{ id: 'u1', source: 'HELLO THERE' }, { id: 'u2', source: 'GRRRR RUN AWAY' }, { id: 'u3', source: 'BYE' }] };
  const logs = [];
  const fn = async (text, engine, opts = {}) => {
    if (text.startsWith('[1]')) throw rep();
    if (text.includes('GRRRR')) throw rep('grrr grrr'); // essa nunca sai
    return { translation: `PT ${text}` };
  };
  const r = await translateBatch(batch, 'local', fn, (m) => logs.push(m));
  assert.equal(r.mode, 'individual');
  assert.deepEqual(r.results.map((x) => x.id), ['u1', 'u2', 'u3']);
  assert.equal(r.results[0].translation, 'PT HELLO THERE');
  assert.equal(r.results[2].translation, 'PT BYE');
  assert.equal(r.results[1].translation, undefined, 'nada pela metade: sem tradução');
  assert.match(r.results[1].error, /repetição/);
  assert.ok(logs.some((l) => /fim da resposta: «grrr grrr»/.test(l)), 'o log mostra o que o modelo estava repetindo');
  assert.ok(logs.some((l) => /GRRRR RUN AWAY.*SEM tradução/.test(l)));
});

test('fala que repete e é recuperada com a amostragem alternativa (tentativa 2 ou 3)', async () => {
  const niveis = [];
  const fn = async (text, engine, opts = {}) => { niveis.push(opts.retry); if ((opts.retry ?? 0) < 2) throw rep(); return { translation: 'OK COMPLETO' }; };
  assert.equal(await translateOne('HELLO', 'local', fn, {}), 'OK COMPLETO');
  assert.deepEqual(niveis, [0, 1, 2]);
});

test('última chance: fala com várias frases que não sai inteira é traduzida frase por frase', async () => {
  const fn = async (text) => { if (text.length > 40) throw rep(); return { translation: `PT[${text}]` }; };
  const r = await translateOne('I WILL FIND YOU. AND I WILL END THIS NOW. DO NOT RUN.', 'local', fn, {});
  assert.equal(r, 'PT[I WILL FIND YOU.] PT[AND I WILL END THIS NOW. DO NOT RUN.]');
  assert.deepEqual(splitSentences('HI THERE MY FRIEND. HELLO THERE MY FRIEND! OK?'), ['HI THERE MY FRIEND.', 'HELLO THERE MY FRIEND! OK?']); // frase curta vai junto da vizinha
});

test('motores de nuvem não repetem tentativas com "amostragem" (uma só chamada por fala)', async () => {
  let n = 0;
  const fn = async () => { n++; throw rep(); };
  await assert.rejects(translateOne('ONE SENTENCE ONLY', 'gemini', fn, {}), { code: 'REPETITION' });
  assert.equal(n, 1);
});

test('erro de infraestrutura (Ollama fora do ar, timeout) continua abortando; resposta com resultado defeituoso do lote cai para individual', async () => {
  const batch = { context: [], units: [{ id: 'u1', source: 'HI THERE' }] };
  await assert.rejects(translateBatch(batch, 'local', async () => { throw new TranslationError('UPSTREAM_UNREACHABLE', 'O Ollama não está rodando.', 502); }), { code: 'UPSTREAM_UNREACHABLE' });
  await assert.rejects(translateBatch(batch, 'local', async () => { throw new TranslationError('UPSTREAM_TIMEOUT', 'demorou', 502); }), { code: 'UPSTREAM_TIMEOUT' });
  // o lote "funcionou", mas uma fala saiu com laço no meio da frase: vai para o modo individual
  const duas = { context: [], units: [{ id: 'a', source: 'HELLO' }, { id: 'b', source: 'BYE' }] };
  const fn = async (text) => ({ translation: text.startsWith('[1]') ? `[1] OLÁ\n[2] ${'tchau '.repeat(30)}` : `OK ${text}` });
  const r = await translateBatch(duas, 'local', fn);
  assert.equal(r.mode, 'individual');
  assert.deepEqual(r.results.map((x) => x.translation), ['OK HELLO', 'OK BYE']);
});

test('makeBatches não muda: continua até 8 falas e 1500 caracteres por lote', () => {
  const units = Array.from({ length: 20 }, (_, i) => ({ id: `u${i}`, source: `WORD ${i}` }));
  assert.equal(makeBatches(units)[0].units.length, 8);
});
