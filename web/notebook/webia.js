/* Tradução com IA na web (ChatGPT, Gemini, Claude...): preparar textos, copiar/baixar, importar de volta.
   Sem API, sem chave e sem modelo local: a tradução é feita por você no site da IA. */
(() => {
  const h = (tag, classe, texto) => { const e = document.createElement(tag); if (classe) e.className = classe; if (texto != null) e.textContent = texto; return e; };
  const btn = (texto, classe, aoClicar) => { const b = h('button', 'btn ' + (classe || ''), texto); b.type = 'button'; b.addEventListener('click', aoClicar); return b; };
  let dlg = null, timer = 0;

  async function copiar(texto) {
    try { await navigator.clipboard.writeText(texto); return true; } catch (_) { /* sem permissão: cai para o método antigo */ }
    const t = h('textarea'); t.value = texto; t.style.cssText = 'position:fixed;opacity:0'; document.body.append(t); t.select();
    let ok = false; try { ok = document.execCommand('copy'); } catch (_) {} t.remove(); return ok;
  }
  function baixarTexto(nome, conteudo) {
    const a = h('a'); a.href = URL.createObjectURL(new Blob([conteudo], {type: 'text/plain;charset=utf-8'})); a.download = nome; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }
  async function baixarServidor(corpo) {                                // um arquivo ou ZIP organizado, montado pelo servidor
    const r = await fetch(rota('/api/web/baixar'), {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(corpo)});
    if (!r.ok) { let j = {}; try { j = await r.json(); } catch (_) {} throw new Error(j.erro || `Erro ${r.status}`); }
    const nome = /filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '')?.[1] || 'textos.zip';
    const a = h('a'); a.href = URL.createObjectURL(await r.blob()); a.download = nome; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }

  function abrir(obra, preselecionados = new Set()) {
    if (dlg) dlg.remove();
    dlg = h('dialog', 'webia'); dlg.setAttribute('aria-label', 'Tradução com IA na web');
    const estado = new Map();                                            // rel → {textos, importados, completo}
    const marcados = new Set(), jaVistos = new Set();
    preselecionados.forEach((r) => marcados.add(r));
    let gerados = [];                                                    // arquivos exportados (para copiar/baixar)

    const cab = h('div', 'webia-cab'); cab.append(h('h3', '', `IA na web — ${obra.nome}`));
    const fechar = btn('Fechar', 'pequeno', () => dlg.close()); cab.append(fechar);
    const nota = h('p', 'nota', 'Você copia os textos, traduz no ChatGPT, Gemini ou Claude e cola o resultado aqui. Este programa não envia nada para a internet.');

    /* ---- 1. capítulos */
    const sCaps = h('section', 'webia-sec'); sCaps.append(h('h4', '', '1. Escolher capítulos e preparar os textos'));
    const lista = h('div', 'webia-lista'); lista.setAttribute('role', 'group'); lista.setAttribute('aria-label', 'Capítulos');
    const resumoSel = h('span', 'nota num'), preparo = h('p', 'nota');
    const acoesCaps = h('div', 'webia-linha');
    const btnTodos = btn('Selecionar todos', 'pequeno', () => { const todos = obra.capitulos.length === marcados.size; marcados.clear(); if (!todos) obra.capitulos.forEach((c) => marcados.add(c.rel)); desenharLista(); });
    let ocupado = false; const emFila = new Set();                   // preparação em andamento: não deixa pedir de novo
    const novos = () => [...marcados].filter((r) => !estado.get(r)?.textos && !emFila.has(r));
    const btnPreparar = btn('Preparar textos dos selecionados', 'principal pequeno', async () => {
      const rels = novos();
      if (!rels.length) { aviso('Os capítulos selecionados já estão preparados (ou sendo preparados).'); return; }
      try { await chamar('/api/traduzir', {rels, motor: 'web'}); ocupado = true; rels.forEach((r) => emFila.add(r)); desenharLista(); aviso(`Preparando ${rels.length} capítulo(s): detecta os balões e lê o texto. Acompanhe na aba Traduções.`); document.dispatchEvent(new CustomEvent('traducao-iniciada')); }
      catch (e) { aviso(e.message); }
    });
    acoesCaps.append(btnTodos, btnPreparar, resumoSel);
    sCaps.append(lista, acoesCaps, preparo);

    function desenharLista() {
      const topo = lista.scrollTop;
      lista.replaceChildren(...obra.capitulos.slice().reverse().map((c) => {
        const e = estado.get(c.rel), l = h('label', 'webia-cap');
        const i = h('input'); i.type = 'checkbox'; i.checked = marcados.has(c.rel);
        i.addEventListener('change', () => { if (i.checked) marcados.add(c.rel); else marcados.delete(c.rel); resumo(); });
        const t = !e?.textos && emFila.has(c.rel) ? 'preparando…' : e?.textos ? `${e.importados}/${e.textos} traduzidos` + (e.completo ? ' · completo' : '') : 'textos não preparados';
        l.append(i, h('span', 'nome', c.numero != null && c.numero !== '' ? 'Cap. ' + c.numero : c.rotulo), h('span', 'est' + (e?.textos ? (e.completo ? ' ok' : ' ativo') : ''), t));
        return l;
      }));
      lista.scrollTop = topo; resumo();
    }
    function resumo() {
      const prontos = [...marcados].filter((r) => estado.get(r)?.textos).length;
      resumoSel.textContent = `${marcados.size} selecionado(s) · ${prontos} com textos prontos`;
      btnPreparar.disabled = ocupado || !novos().length; gerar.disabled = !prontos; resumoSel.title = '';
    }
    async function atualizar() {
      try {
        const t = await ler('/api/traducao/estado', '&log=0'), a = (t.itens || []).find((i) => i.estado === 'traduzindo');
        ocupado = t.estado === 'executando'; emFila.clear(); (t.itens || []).forEach((i) => { if (ocupado && (i.estado === 'fila' || i.estado === 'traduzindo')) emFila.add(i.rel); });
        preparo.textContent = t.estado === 'executando' ? `Preparando textos${a ? ': ' + a.nome + (a.etapa ? ' — ' + a.etapa : '') : '…'} (pode levar alguns minutos; o conteúdo aparece abaixo quando terminar).` : '';
      } catch (_) {}
      try {
        const r = await chamar('/api/web/capitulos', {obra: obra.nome});
        estado.clear(); r.capitulos.forEach((c) => { estado.set(c.rel, c); if (c.textos && !jaVistos.has(c.rel)) { jaVistos.add(c.rel); marcados.add(c.rel); } });
        limite.value = limite.value || r.limite_padrao; desenharLista(); gerarAgora();
      } catch (e) { /* janela fechada ou servidor ocupado: tenta na próxima */ }
    }

    /* ---- 2. exportar */
    const sExp = h('section', 'webia-sec'); sExp.append(h('h4', '', '2. Exportar os textos'));
    const cbIntro = h('input'); cbIntro.type = 'checkbox'; cbIntro.checked = true;
    const lIntro = h('label', 'marcar'); lIntro.append(cbIntro, ' Incluir introdução com instruções para a IA (PT-BR, manter identificadores, não resumir…)');
    const rUm = h('input'); rUm.type = 'radio'; rUm.name = 'webia-modo'; rUm.checked = true;
    const rVarios = h('input'); rVarios.type = 'radio'; rVarios.name = 'webia-modo';
    const lUm = h('label', 'marcar'); lUm.append(rUm, ' Um único arquivo');
    const limite = h('input'); limite.type = 'number'; limite.min = '2000'; limite.max = '100000'; limite.step = '1000'; limite.setAttribute('aria-label', 'Caracteres por arquivo');
    const lVarios = h('label', 'marcar'); lVarios.append(rVarios, ' Vários arquivos, de até ', limite, ' caracteres');
    const modo = h('div', 'webia-linha'); modo.append(lUm, lVarios);
    const resultado = h('div', 'webia-resultado');
    const pedido = () => ({obra: obra.nome, rels: [...marcados].filter((r) => estado.get(r)?.textos), introducao: cbIntro.checked, dividir: rVarios.checked, limite: Number(limite.value) || 12000});
    let assin = '';                                                      // o que já está mostrado: evita refazer (e piscar) a cada consulta
    async function gerarAgora(forcar) {
      const ped = pedido(), chave = JSON.stringify(ped) + '|' + ped.rels.map((r) => estado.get(r)?.textos).join(',');
      if (!forcar && chave === assin) return;
      assin = chave;
      if (!ped.rels.length) { gerados = []; resultado.replaceChildren(h('p', 'nota', 'Marque capítulos com textos preparados para ver aqui o conteúdo que vai para a IA.')); return; }
      let r; try { r = await chamar('/api/web/exportar', ped); } catch (e) { aviso(e.message); return; }
      gerados = r.arquivos; resultado.replaceChildren();
      gerados.forEach((a, k) => {
        const caixa = h('div', 'webia-arq');
        const prev = h('textarea', 'webia-area webia-previa'); prev.readOnly = true; prev.rows = gerados.length === 1 ? 12 : 6; prev.value = a.conteudo; prev.spellcheck = false;
        prev.setAttribute('aria-label', 'Conteúdo de ' + a.nome);
        const topo = h('div', 'webia-linha');
        topo.append(h('span', 'nome', a.nome), h('span', 'nota num', `${a.textos} texto(s) · ${a.capitulos} capítulo(s) · ${a.caracteres.toLocaleString('pt-BR')} caracteres`));
        const copia = btn(gerados.length === 1 ? 'Copiar conteúdo completo' : 'Copiar', 'principal pequeno', async () => { aviso((await copiar(a.conteudo)) ? `“${a.nome}” copiado. Cole na IA.` : 'Não consegui copiar; selecione o texto e use Ctrl+C, ou baixe o arquivo.'); });
        topo.append(copia, btn('Baixar', 'pequeno', () => baixarTexto(a.nome, a.conteudo)));
        caixa.append(topo, prev); resultado.append(caixa);
      });
      if (gerados.length > 1) resultado.append(btn('Baixar todos organizados (ZIP)', '', async () => { try { await baixarServidor(pedido()); } catch (e) { aviso(e.message); } }));
    }
    const gerar = btn('Atualizar conteúdo', 'pequeno', () => gerarAgora(true));
    [cbIntro, rUm, rVarios, limite].forEach((i) => i.addEventListener('change', () => gerarAgora()));
    sExp.append(lIntro, modo, h('div', 'webia-linha').appendChild(gerar).parentNode, resultado);
    sExp.append(h('p', 'nota', 'Cada linha leva um identificador único [código:fala] que liga a tradução à imagem e à posição. Não mude os identificadores.'));

    /* ---- 3. importar */
    const sImp = h('section', 'webia-sec'); sImp.append(h('h4', '', '3. Importar a tradução'));
    const area = h('textarea', 'webia-area'); area.rows = 6; area.placeholder = 'Cole aqui a tradução que a IA devolveu (várias partes podem ser coladas juntas ou em vezes diferentes)…'; area.spellcheck = false;
    area.setAttribute('aria-label', 'Texto traduzido');
    const arq = h('input'); arq.type = 'file'; arq.multiple = true; arq.accept = '.txt,text/plain'; arq.hidden = true;
    const nomes = h('span', 'nota');
    arq.addEventListener('change', () => { nomes.textContent = arq.files.length ? `${arq.files.length} arquivo(s) escolhido(s)` : ''; });
    const relatorio = h('div', 'webia-relatorio'); relatorio.setAttribute('role', 'status');
    const conteudos = async () => [area.value, ...(await Promise.all([...arq.files].map((f) => f.text())))].filter((t) => t.trim());
    const enviar = async (gravar) => {
      const textos = await conteudos();
      if (!textos.length) { aviso('Cole o texto traduzido ou escolha os arquivos TXT.'); return; }
      let r; try { r = await chamar('/api/web/importar', {obra: obra.nome, textos, gravar}); } catch (e) { aviso(e.message); return; }
      mostrar(r, gravar);
      if (gravar) { aviso(r.iniciou ? `${r.iniciou} capítulo(s) completo(s): terminando a tradução (aba Traduções).` : (r.aviso || 'Traduções importadas.')); if (r.iniciou) document.dispatchEvent(new CustomEvent('traducao-iniciada')); atualizar(); }
    };
    const escolher = btn('Escolher arquivos TXT…', '', () => arq.click());
    const acoesImp = h('div', 'webia-linha');
    acoesImp.append(escolher, nomes, btn('Verificar (não grava)', '', () => enviar(false)), btn('Importar', 'principal', () => enviar(true)), arq);
    sImp.append(area, acoesImp, relatorio);

    function mostrar(r, gravou) {
      const rel = r.relatorio, linhas = [];
      const caps = rel.capitulos;
      if (!caps.length) linhas.push(['erro', 'Nenhum identificador conhecido foi encontrado. Confira se colou o texto devolvido pela IA, com as linhas [código:fala] intactas.']);
      caps.forEach((c) => {
        const ok = c.completo && !c.desconhecidos.length && !c.duplicados.length && !c.quebrados.length && !c.vazios.length;
        linhas.push([ok ? 'ok' : (c.completo ? 'aviso' : 'erro'), `${c.rotulo}: ${c.ja_importados + c.novas}/${c.esperados} traduzidos${gravou ? '' : ` (${c.novas} novos)`}` + (c.completo ? ' · completo' : ` · faltam ${c.qtd_faltam}`)]);
        const det = (rot, v) => { if (v.length) linhas.push(['nota', `   ${rot}: ${v.join(', ')}`]); };
        det('faltam', c.faltam); det('identificador desconhecido', c.desconhecidos); det('duplicados com textos diferentes (não usados)', c.duplicados);
        det('linha quebrada ou com texto extra (não usados)', c.quebrados); det('sem texto traduzido', c.vazios);
      });
      if (rel.codigos_desconhecidos.length) linhas.push(['aviso', `Códigos de capítulo desconhecidos (ignorados): ${rel.codigos_desconhecidos.join(', ')}. Prepare os textos e exporte de novo.`]);
      if (rel.total_fora) linhas.push(['nota', `${rel.total_fora} linha(s) fora da estrutura foram ignoradas: ${rel.linhas_fora_da_estrutura.join(' | ')}`]);
      const incompletos = caps.filter((c) => !c.completo).length;
      linhas.push(['nota', !gravou ? 'Verificação feita: nada foi gravado.' : incompletos ? `Traduções válidas guardadas. ${incompletos} capítulo(s) ainda incompleto(s): importe as falas que faltam (listadas acima) e ele é aplicado sozinho.` : 'Todas as falas traduzidas: aplicando nos capítulos.']);
      relatorio.replaceChildren(...linhas.map(([cl, t]) => h('p', 'nota ' + cl, t)));
    }

    dlg.append(cab, nota, sCaps, sExp, sImp);
    document.body.append(dlg);
    dlg.addEventListener('close', () => { clearInterval(timer); dlg.remove(); dlg = null; });
    desenharLista(); atualizar(); timer = setInterval(atualizar, 4000);
    dlg.showModal();
  }
  window.WebIA = {abrir};
})();
