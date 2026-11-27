// "Celular" para os testes: o MESMO sincronia.js do app, com localStorage em arquivo e HTTP real (Bearer) contra o notebook.
// uso: node sincronia_cliente.mjs <arquivo_do_storage> <base> <chave> <acao> [json]   → imprime {hist, estados, erro}
import { createRequire } from 'node:module';
import fs from 'node:fs';
const [, , arq, base, chave, acao, extra] = process.argv;
const S = createRequire(import.meta.url)('../../web/compartilhado/sincronia.js');
const dados = fs.existsSync(arq) ? JSON.parse(fs.readFileSync(arq, 'utf8')) : {};
const st = { getItem: (k) => (k in dados ? dados[k] : null), setItem: (k, v) => { dados[k] = String(v); fs.writeFileSync(arq, JSON.stringify(dados)); }, removeItem: (k) => { delete dados[k]; fs.writeFileSync(arq, JSON.stringify(dados)); }, get length() { return Object.keys(dados).length; }, key: (i) => Object.keys(dados)[i] };
const H = S.criar(st), x = extra ? JSON.parse(extra) : {};
const estados = []; H.aoMudarEstado((e) => estados.push(e));
const enviar = async (corpo) => {
  const r = await fetch(base + '/api/app/sincronia', { method: 'POST', headers: { Authorization: 'Bearer ' + chave, 'Content-Type': 'application/json' }, body: x.cortar ? JSON.stringify(corpo).slice(0, 20) : JSON.stringify(corpo) });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  return r.json();
};
let erro = null;
if (acao === 'posicao') { const h = H.ler(); h.posicoes[x.rel] = { p: x.p, n: x.n, f: x.f, t: x.t }; H.gravar(h); }
if (acao === 'lido') { const h = H.ler(); h.lidos[x.rel] = { v: x.v, t: x.t }; H.gravar(h); }
if (acao === 'situacao') { const h = H.ler(); Object.assign(h.obras[x.id], { situacao: x.situacao, t_situacao: x.t, t_atualizado: x.t }); H.gravar(h); }
if (acao === 'sync' || x.sync) { try { await H.sincronizar(enviar, true); } catch (e) { erro = String(e.message || e); } }
console.log(JSON.stringify({ hist: H.ler(), estados, erro }));
