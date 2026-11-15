// Fluxo completo do Baixador: pipeline REAL (detecção, OCR Tesseract, limpeza) com um Ollama falso que responde no formato
// do TranslateGemma. Mostra o que o Python vai encontrar no disco: traducao.json + traducao/limpeza/*.png, e nada mais.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdir, mkdtemp, readFile, readdir, stat, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import sharp from 'sharp';
import { traduzirCapitulo, verificarMotor, resultadoValido } from '../src/processar-capitulo.js';

const TRAD = [[/CAN'?T BELIEVE/i, 'NÃO ACREDITO QUE VOCÊ FEZ ISSO!'], [/HAVE TO LEAVE/i, 'TEMOS QUE SAIR ANTES QUE ELES CHEGUEM.'], [/WORRY/i, 'NÃO SE PREOCUPE. EU VOU PROTEGER VOCÊ.']];
const traduz = (s) => (TRAD.find(([re]) => re.test(s)) ?? [null, `(traduzido) ${s}`])[1];

// Ollama falso: /api/tags lista o modelo; /api/chat devolve as falas numeradas, ou erro 500 enquanto `estado.quebrado`.
async function ollamaFalso(t) {
  const estado = { quebrado: false, modelos: ['translategemma:4b'], chamadas: 0 };
  const server = http.createServer((req, res) => {
    if (req.url === '/api/tags') return res.end(JSON.stringify({ models: estado.modelos.map((name) => ({ name })) }));
    let body = '';
    req.on('data', (c) => (body += c));
    req.on('end', () => {
      estado.chamadas++;
      if (estado.quebrado) { res.statusCode = 500; return res.end(JSON.stringify({ error: 'falha simulada' })); }
      const texto = JSON.parse(body).messages[0].content.split('Please translate the following English text into Portuguese:\n\n\n')[1];
      const out = texto.split('\n').map((l) => { const m = l.match(/^\[(\d+)\]\s*(.*)$/); return m ? `[${m[1]}] ${traduz(m[2])}` : traduz(l); }).join('\n');
      res.write(`${JSON.stringify({ message: { content: out } })}\n`);
      res.end(`${JSON.stringify({ done: true, message: { content: '' } })}\n`);
    });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  t.after(() => server.close());
  estado.env = { OLLAMA_URL: `http://127.0.0.1:${server.address().port}` };
  return estado;
}

async function pagina(file) {
  const balao = (cx, cy, rx, ry, linhas) => `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="#fff" stroke="#111" stroke-width="4"/>` +
    linhas.map((l, i) => `<text x="${cx}" y="${cy - (linhas.length - 1) * 14 + i * 30 + 8}" font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold" font-size="26" text-anchor="middle" fill="#111">${l}</text>`).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="800" height="1100"><rect width="800" height="1100" fill="#b9c4d6"/><rect x="40" y="620" width="720" height="400" fill="#8a97ad"/>` +
    balao(260, 200, 200, 110, ["I CAN'T BELIEVE", 'YOU DID THAT!']) + balao(560, 480, 190, 100, ['WE HAVE TO LEAVE', 'BEFORE THEY COME.']) + balao(300, 800, 210, 110, ["DON'T WORRY.", 'I WILL PROTECT YOU.']) + '</svg>';
  await sharp(Buffer.from(svg)).png().toFile(file);
}

// obras/Obra/Capítulo/img/001_a.png — a estrutura real do Baixador
async function biblioteca() {
  const raiz = await mkdtemp(path.join(tmpdir(), 'obras-'));
  const cap = path.join(raiz, 'Obra', 'Capitulo 01');
  await mkdir(path.join(cap, 'img'), { recursive: true });
  await pagina(path.join(cap, 'img', '001_a.png'));
  return { raiz, obra: path.join(raiz, 'Obra'), cap };
}
const sha = async (f) => createHash('sha256').update(await readFile(f)).digest('hex');
const existe = (f) => stat(f).then(() => true, () => false);
const mudo = { log() {} };

test('capítulo do Baixador: traduz com o pipeline real, deixa só traducao.json + traducao/limpeza e não toca nas imagens', { timeout: 180_000 }, async (t) => {
  const ollama = await ollamaFalso(t);
  const { cap } = await biblioteca();
  const antes = await sha(path.join(cap, 'img', '001_a.png'));
  const eventos = [];
  const r = await traduzirCapitulo({ capitulo: cap, motor: 'local', env: { ...process.env, ...ollama.env }, log: (m) => eventos.push(m) });
  assert.equal(r.falas, 3);
  assert.deepEqual(await readdir(cap), ['img', 'traducao', 'traducao.json']); // sem traducao.nova, sem etapas, sem manifest
  assert.deepEqual(await readdir(path.join(cap, 'traducao')), ['limpeza']);
  assert.equal(await sha(path.join(cap, 'img', '001_a.png')), antes);
  const d = JSON.parse(await readFile(path.join(cap, 'traducao.json'), 'utf8'));
  assert.equal(d.formato, 2);
  assert.equal(d.engine, 'local');
  assert.match(d.provider, /translategemma:4b/);
  const [p] = d.pages;
  assert.equal(p.file, '001_a.png');
  assert.equal(p.balloons.length, 3);
  assert.ok(await existe(path.join(cap, 'traducao', 'limpeza', p.patch)));
  const meta = await sharp(path.join(cap, 'traducao', 'limpeza', p.patch)).metadata();
  assert.equal(meta.hasAlpha, true);
  assert.deepEqual([meta.width, meta.height], [800, 1100]);
  const fala = (re) => p.units.find((u) => re.test(u.source));
  assert.match(fala(/BELIEVE/).translation, /NÃO ACREDITO/);
  assert.equal(fala(/BELIEVE/).status, 'ok');
  assert.equal(fala(/BELIEVE/).render.mode, 'balao');
  assert.equal(fala(/LEAVE/).render.flag, 'ok');
  assert.ok(fala(/WORRY/).ocr.confidence > 0);
  assert.ok(d.pages[0].balloons[0].polygon.length > 3);
  assert.equal(await resultadoValido(path.join(cap, 'traducao.json')), true);
});

test('já traduzido: não chama o motor de novo, a não ser com refazer', { timeout: 180_000 }, async (t) => {
  const ollama = await ollamaFalso(t);
  const { cap } = await biblioteca();
  const env = { ...process.env, ...ollama.env };
  await traduzirCapitulo({ capitulo: cap, motor: 'local', env, ...mudo });
  const chamadas = ollama.chamadas;
  const r = await traduzirCapitulo({ capitulo: cap, motor: 'local', env, ...mudo });
  assert.equal(r.jaTraduzido, true);
  assert.equal(ollama.chamadas, chamadas);
  await traduzirCapitulo({ capitulo: cap, motor: 'local', refazer: true, env, ...mudo });
  assert.ok(ollama.chamadas > chamadas);
});

test('falha no meio de "traduzir de novo": a tradução antiga continua valendo e a retomada pula as etapas prontas', { timeout: 240_000 }, async (t) => {
  const ollama = await ollamaFalso(t);
  const { cap, obra } = await biblioteca();
  const env = { ...process.env, ...ollama.env };
  await traduzirCapitulo({ capitulo: cap, motor: 'local', env, ...mudo });
  const antiga = await readFile(path.join(cap, 'traducao.json'), 'utf8');

  await writeFile(path.join(obra, 'glossario.json'), JSON.stringify({ PROTECT: 'proteger' })); // glossário da obra
  await writeFile(path.join(cap, 'correcoes.json'), JSON.stringify({ 'p001-b9': 'x' }));          // correção do capítulo
  ollama.quebrado = true;
  await assert.rejects(traduzirCapitulo({ capitulo: cap, motor: 'local', refazer: true, env, ...mudo }), /Ollama/);
  assert.equal(await readFile(path.join(cap, 'traducao.json'), 'utf8'), antiga); // resultado anterior intacto
  assert.ok(await existe(path.join(cap, 'traducao', 'limpeza')));
  assert.ok(await existe(path.join(cap, 'traducao.nova', 'etapa4a', 'glossario.json'))); // glossário e correções entraram
  assert.ok(await existe(path.join(cap, 'traducao.nova', 'etapa4a', 'correcoes.json')));

  ollama.quebrado = false;
  const linhas = [];
  await traduzirCapitulo({ capitulo: cap, motor: 'local', refazer: true, env, log: (m) => linhas.push(m) });
  assert.ok(linhas.some((l) => /etapa3: pronta, pulada/.test(l)), 'a Etapa 3 não deveria rodar de novo');
  assert.ok(linhas.some((l) => /etapa4a: pronta, pulada/.test(l)));
  assert.equal(await existe(path.join(cap, 'traducao.nova')), false);
  assert.equal(await existe(path.join(cap, 'traducao.velha')), false);
});

test('glossário fora do formato é ignorado com aviso (o antigo do Baixador tinha outra estrutura)', { timeout: 180_000 }, async (t) => {
  const ollama = await ollamaFalso(t);
  const { cap, obra } = await biblioteca();
  await writeFile(path.join(obra, 'glossario.json'), JSON.stringify({ manter: ['Naruto'], auto: [], termos: { a: 'b' } }));
  ollama.quebrado = true; // para na 4b: só interessa a preparação
  const linhas = [];
  await assert.rejects(traduzirCapitulo({ capitulo: cap, motor: 'local', env: { ...process.env, ...ollama.env }, log: (m) => linhas.push(m) }));
  assert.ok(linhas.some((l) => /não está no formato/.test(l)));
  assert.equal(await existe(path.join(cap, 'traducao.nova', 'etapa4a', 'glossario.json')), false);
});

test('motor explícito: Ollama parado, modelo ausente, motor sem chave e motor inválido falham logo, sem trocar de motor', async (t) => {
  const ollama = await ollamaFalso(t);
  await assert.doesNotReject(verificarMotor('local', { ...ollama.env }));
  ollama.modelos = ['outro:7b'];
  await assert.rejects(verificarMotor('local', { ...ollama.env }), /não está instalado.*ollama pull translategemma:4b/);
  await assert.rejects(verificarMotor('local', { OLLAMA_URL: 'http://127.0.0.1:1' }), /Ollama não está rodando/);
  await assert.rejects(verificarMotor('deepl', {}), /exige a chave/);
  await assert.rejects(verificarMotor('gemini', {}), /exige a chave/);
  await assert.rejects(verificarMotor('openrouter', {}), /inválido/);
  assert.equal((await verificarMotor('deepl', { DEEPL_API_KEY: 'k:fx' })).motor, 'deepl');
  assert.equal((await verificarMotor('mymemory', {})).motor, 'mymemory');
  ollama.modelos = ['translategemma:12b'];
  assert.equal((await verificarMotor('local', { ...ollama.env, LOCAL_MODEL: 'translategemma:12b' })).motor, 'local');
});

test('formato antigo (traducao.json do Baixador v1) não conta como resultado', async () => {
  const dir = await mkdtemp(path.join(tmpdir(), 'old-'));
  await writeFile(path.join(dir, 'traducao.json'), JSON.stringify({ versao: 1, imagens: {} }));
  assert.equal(await resultadoValido(path.join(dir, 'traducao.json')), false);
  assert.equal(await resultadoValido(path.join(dir, 'nao-existe.json')), false);
});
