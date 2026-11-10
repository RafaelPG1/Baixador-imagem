/* Funções comuns do app do notebook: token, chamadas à API, abas, avisos. */
const T = new URLSearchParams(location.search).get('t') || (document.cookie.match(/(?:^|; )bt=([^;]*)/) || [])[1] || '';
const $ = (id) => document.getElementById(id);
const rota = (caminho, extra = '') => `${caminho}?t=${encodeURIComponent(T)}${extra}`;

async function chamar(caminho, corpo) {
  const r = await fetch(rota(caminho), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(corpo || {})});
  let j = {};
  try { j = await r.json(); } catch (_) {}
  if (!r.ok) throw new Error(j.erro || `Erro ${r.status}`);
  return j;
}
async function ler(caminho, extra) {
  const r = await fetch(rota(caminho, extra), {cache: 'no-store'});
  if (!r.ok) throw new Error(String(r.status));
  return r.json();
}

let _toast = null;
function aviso(texto) {
  const t = $('toast');
  t.textContent = texto; t.hidden = false;
  clearTimeout(_toast); _toast = setTimeout(() => { t.hidden = true; }, 3500);
}

function anexarLog(pre, linhas) {
  const noFim = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 30;
  linhas.forEach((l) => pre.append(l + '\n'));
  if (noFim) pre.scrollTop = pre.scrollHeight;
}

function ampliar(src, alt) {
  const grande = document.createElement('img');
  grande.alt = alt; grande.src = src;
  $('ampliada').replaceChildren(grande); $('ampliada').hidden = false;
}
$('ampliada').addEventListener('click', () => { $('ampliada').hidden = true; $('ampliada').replaceChildren(); });
document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') $('ampliada').click(); });

/* abas: #baixar | #biblioteca | #traducoes | #celular */
const PAGINAS = ['baixar', 'biblioteca', 'traducoes', 'celular'];
function irPara(pagina, foco) {
  if (!PAGINAS.includes(pagina)) pagina = 'baixar';
  PAGINAS.forEach((p) => {
    $('pg-' + p).hidden = p !== pagina;
    $('aba-' + p).setAttribute('aria-selected', String(p === pagina));
    $('aba-' + p).tabIndex = p === pagina ? 0 : -1;
  });
  if (location.hash !== '#' + pagina) history.replaceState(null, '', location.pathname + location.search + '#' + pagina);
  if (foco) $('aba-' + pagina).focus();
  document.dispatchEvent(new CustomEvent('pagina', {detail: pagina}));
}
PAGINAS.forEach((p, i) => {
  $('aba-' + p).addEventListener('click', () => irPara(p));
  $('aba-' + p).addEventListener('keydown', (ev) => {
    const d = ev.key === 'ArrowRight' ? 1 : ev.key === 'ArrowLeft' ? -1 : 0;
    if (d) { ev.preventDefault(); irPara(PAGINAS[(i + d + PAGINAS.length) % PAGINAS.length], true); }
  });
});
window.addEventListener('hashchange', () => irPara(location.hash.slice(1)));


/* Motor de tradução: uma só configuração (guardada no computador), vista na Biblioteca e na aba Traduções. */
const Motor = (() => {
  let cfg = {motor: 'hibrido', motores: {}};
  const mudou = () => document.dispatchEvent(new CustomEvent('motor-mudou', {detail: cfg}));
  async function carregar() { try { cfg = await ler('/api/traducao/config'); mudou(); } catch (_) {} return cfg; }
  async function escolher(valor) {
    try { cfg = await chamar('/api/traducao/config', {motor: valor}); aviso('Motor de tradução salvo.'); }
    catch (e) { aviso(e.message); }
    mudou();
    return cfg;
  }
  async function escolherModelo(valor) {
    try { cfg = await chamar('/api/traducao/config', {modelo: valor}); aviso('Modelo local salvo.'); }
    catch (e) { aviso(e.message); }
    mudou();
    return cfg;
  }
  /* Confere o que o motor escolhido precisa (Ollama + modelo; chave do Gemini). Sem rede para o Gemini, nunca trava a tela. */
  async function verificar(valor) {
    if (valor === 'argos') return {pronto: true, mensagem: ''};
    try { return await chamar(valor === 'gemini' ? '/api/traducao/gemini' : valor === 'openrouter' ? '/api/traducao/openrouter' : '/api/traducao/hy', {}); }
    catch (e) { return {pronto: false, mensagem: e.message}; }
  }
  return {carregar, escolher, escolherModelo, verificar, get atual() { return cfg; }};
})();
