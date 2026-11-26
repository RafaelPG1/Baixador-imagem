/* Pesquisa no texto traduzido (índice SQLite FTS5 no servidor). Abre o capítulo direto na página da fala. */
const Busca = (() => {
  let dlg = null, caixa, lista, msg, selObra, t = 0, seq = 0;
  const h = (tag, c, x) => { const n = document.createElement(tag); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
  function trecho(s) { const p = h('span'); String(s).split(/(\[[^\]]*\])/).forEach((x) => { if (/^\[.*\]$/.test(x)) p.append(Object.assign(h('mark'), {textContent: x.slice(1, -1)})); else p.append(document.createTextNode(x)); }); return p; }
  async function buscar() {
    const q = caixa.value.trim(), eu = ++seq;
    if (q.length < 2) { lista.replaceChildren(); msg.textContent = 'Digite ao menos 2 letras.'; return; }
    msg.textContent = 'Pesquisando…';
    try {
      const r = await ler('/api/busca', '&q=' + encodeURIComponent(q) + (selObra.value ? '&obra=' + encodeURIComponent(selObra.value) : ''));
      if (eu !== seq) return;
      msg.textContent = r.resultados.length ? `${r.resultados.length} resultado(s)${r.resultados.length >= 50 ? ' (mostrando os 50 mais relevantes)' : ''}.` : 'Nada encontrado.';
      lista.replaceChildren(...r.resultados.map((x) => {
        const b = h('button', 'webia-cap busca-res'); b.type = 'button';
        const info = h('div'); info.append(h('strong', '', `${x.obra} — ${x.rotulo}`), h('div', 'nota', `página ${x.pagina}`), trecho(x.trecho)); b.append(info);
        b.addEventListener('click', () => window.open(urlLeitor(x.rel) + '&pagina=' + x.pagina + '&inicio=1', '_blank', 'noopener'));
        return b;
      }));
    } catch (e) { if (eu === seq) msg.textContent = e.message; }
  }
  function montar() {
    dlg = h('dialog', 'webia');
    const cab = h('div', 'webia-cab'); cab.append(h('h3', '', 'Pesquisar nas traduções'));
    const x = h('button', 'btn webia-x', '✕'); x.type = 'button'; x.setAttribute('aria-label', 'Fechar'); x.addEventListener('click', () => dlg.close()); cab.append(x);
    const corpo = h('div', 'webia-corpo'), sec = h('section', 'webia-sec');
    caixa = h('input'); caixa.type = 'search'; caixa.placeholder = 'Texto da fala traduzida'; caixa.setAttribute('aria-label', 'Texto a pesquisar'); caixa.autocomplete = 'off';
    selObra = h('select', 'bib-estado'); selObra.setAttribute('aria-label', 'Limitar a uma obra');
    msg = h('p', 'nota'); msg.setAttribute('role', 'status'); lista = h('div');
    caixa.addEventListener('input', () => { clearTimeout(t); t = setTimeout(buscar, 300); }); selObra.addEventListener('change', buscar);
    sec.append(caixa, selObra, msg, lista); corpo.append(sec); dlg.append(cab, corpo); document.body.append(dlg);
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
  }
  function abrir() {
    if (!dlg) montar();
    selObra.replaceChildren(Object.assign(h('option'), {value: '', textContent: 'Todas as obras'}), ...(typeof bib !== 'undefined' ? bib.obras : []).map((o) => Object.assign(h('option'), {value: o.nome, textContent: o.nome})));
    dlg.showModal(); caixa.focus();
  }
  return {abrir};
})();
document.getElementById('abrir-busca').addEventListener('click', () => Busca.abrir());
