/* Lixeira (restaurar / apagar de vez) e espaço em disco (tamanho por obra, restos seguros de apagar). */
const Armazenamento = (() => {
  let dlg = null;
  const tam = (b) => b >= 1073741824 ? (b / 1073741824).toFixed(1) + ' GB' : b >= 1048576 ? Math.round(b / 1048576) + ' MB' : Math.max(1, Math.round((b || 0) / 1024)) + ' KB';
  const h = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x != null) n.textContent = x; return n; };
  const btn = (t, c, f) => { const b = h('button', 'btn ' + (c || ''), t); b.type = 'button'; b.addEventListener('click', f); return b; };
  const data = (s) => new Date(s * 1000).toLocaleString('pt-BR', {dateStyle: 'short', timeStyle: 'short'});

  function montar() {
    dlg = h('dialog', 'webia');
    const cab = h('div', 'webia-cab'); cab.append(h('h3', '', 'Lixeira e espaço em disco'));
    const x = btn('✕', 'webia-x', () => dlg.close()); x.setAttribute('aria-label', 'Fechar'); cab.append(x);
    const abas = h('div', 'webia-abas'), corpo = h('div', 'webia-corpo');
    const secL = h('section', 'webia-sec'), secE = h('section', 'webia-sec');
    const bs = ['Lixeira', 'Espaço'].map((t, k) => { const b = h('button', 'webia-aba', t); b.type = 'button'; b.addEventListener('click', () => ir(k)); return b; });
    const ir = (k) => { [secL, secE].forEach((s, i) => { s.hidden = i !== k; bs[i].classList.toggle('ativa', i === k); }); corpo.scrollTop = 0; if (k === 0) lixeira(secL); else espaco(secE); };
    abas.append(...bs); corpo.append(secL, secE); dlg.append(cab, abas, corpo); document.body.append(dlg);
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });
    dlg.ir = ir;
  }

  async function lixeira(sec) {
    sec.replaceChildren(h('p', 'nota', 'Carregando…'));
    let r; try { r = await ler('/api/lixeira'); } catch (e) { sec.replaceChildren(h('p', 'nota erro', e.message)); return; }
    const nota = h('p', 'nota', `Obras e capítulos excluídos ficam aqui por ${r.dias} dias, com imagens e traduções, e depois são apagados de vez.`);
    if (!r.itens.length) { sec.replaceChildren(nota, h('p', 'nota', 'A lixeira está vazia.')); return; }
    const lista = r.itens.map((m) => {
      const caixa = h('div', 'webia-cap');
      const info = h('div'); info.style.flex = '1';
      const n = m.capitulos.length;
      info.append(h('strong', '', m.tipo === 'obra' ? `Obra “${m.obra}”` : `${n} capítulo${n === 1 ? '' : 's'} de “${m.obra}”`),
        h('div', 'nota', `${data(m.quando)} · ${tam(m.bytes)} · apagada de vez em ${m.dias_restantes} dia(s)` + (m.tipo === 'obra' ? ` · ${n} capítulo(s)` : '')));
      const rest = btn('Restaurar', 'pequeno principal', async () => {
        try {
          const o = await chamar('/api/lixeira/restaurar', {id: m.id});
          aviso(o.conflitos.length ? `Restaurado, exceto ${o.conflitos.length} que já existe(m) na biblioteca (nada foi sobrescrito).` : 'Restaurado.');
          document.dispatchEvent(new CustomEvent('biblioteca-mudou'));
        } catch (e) { aviso(e.message); }
        lixeira(sec);
      });
      const del = btn('Apagar de vez', 'pequeno', async () => {
        if (!confirm('Apagar de vez? Isto não pode ser desfeito.')) return;
        try { await chamar('/api/lixeira/apagar', {id: m.id}); } catch (e) { aviso(e.message); }
        lixeira(sec);
      });
      caixa.append(info, rest, del); return caixa;
    });
    const esv = btn('Esvaziar lixeira', 'pequeno', async () => {
      if (!confirm(`Apagar de vez os ${r.itens.length} item(ns) da lixeira? Isto não pode ser desfeito.`)) return;
      try { await chamar('/api/lixeira/esvaziar', {}); } catch (e) { aviso(e.message); }
      lixeira(sec);
    });
    sec.replaceChildren(nota, ...lista, esv);
  }

  async function espaco(sec) {
    sec.replaceChildren(h('p', 'nota', 'Calculando…'));
    let r; try { r = await ler('/api/armazenamento'); } catch (e) { sec.replaceChildren(h('p', 'nota erro', e.message)); return; }
    const obras = Object.entries(r.obras).sort((a, b) => b[1] - a[1]);
    const linhas = obras.map(([n, b]) => { const l = h('div', 'webia-cap'); const t = h('span', '', n); t.style.flex = '1'; l.append(t, h('span', 'nota', tam(b))); return l; });
    const total = h('p', 'nota', `Total: ${tam(r.total)} (obras ${tam(r.total - r.lixeira)} · lixeira ${tam(r.lixeira)})`);
    const sobras = r.orfaos.reduce((s, o) => s + o.bytes, 0);
    const bloco = h('div');
    if (!r.orfaos.length) bloco.append(h('p', 'nota', 'Nenhum resto de processamento encontrado.'));
    else {
      bloco.append(h('p', 'nota', `Restos que podem ser apagados (${tam(sobras)}). Só entram capítulos já traduzidos e fora da fila, e arquivos temporários antigos; imagens e traduções nunca.`));
      r.orfaos.forEach((o) => { const l = h('div', 'webia-cap'); const t = h('span', '', `${o.tipo} — ${o.rel}`); t.style.flex = '1'; l.append(t, h('span', 'nota', tam(o.bytes))); bloco.append(l); });
      bloco.append(btn('Limpar restos', 'pequeno principal', async () => {
        try { const o = await chamar('/api/armazenamento/limpar', {}); aviso(`${tam(o.bytes)} liberados (${o.apagados} item(ns)).`); } catch (e) { aviso(e.message); }
        espaco(sec);
      }));
    }
    sec.replaceChildren(total, ...linhas, h('hr'), bloco);
  }

  return {abrir(aba = 0) { if (!dlg) montar(); dlg.showModal(); dlg.ir(aba); }};
})();

document.getElementById('abrir-lixeira')?.addEventListener('click', () => Armazenamento.abrir(0));
document.getElementById('abrir-espaco')?.addEventListener('click', () => Armazenamento.abrir(1));
document.addEventListener('biblioteca-mudou', () => { if (typeof carregar === 'function') carregar(); });
