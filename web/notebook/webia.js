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
    const estado = new Map(); let linhas = [];                           // só os capítulos que ainda precisam de tradução (vêm do servidor)                                            // rel → {textos, importados, completo}
    const marcados = new Set(), jaVistos = new Set();
    preselecionados.forEach((r) => marcados.add(r));
    let gerados = [];                                                    // arquivos exportados (para copiar/baixar)

    const cab = h('div', 'webia-cab'); cab.append(h('h3', '', `IA na web — ${obra.nome}`));
    const fechar = btn('✕', 'webia-x', () => dlg.close()); fechar.setAttribute('aria-label', 'Fechar'); cab.append(fechar);
    const nota = h('p', 'nota', 'Você copia os textos, traduz no ChatGPT, Gemini ou Claude e cola o resultado aqui. Este programa não envia nada para a internet.');

    /* ---- 1. capítulos */
    const sCaps = h('section', 'webia-sec'); sCaps.append(h('h4', '', '1. Escolher capítulos e preparar os textos'));
    const lista = h('div', 'webia-lista'); lista.setAttribute('role', 'group'); lista.setAttribute('aria-label', 'Capítulos');
    const resumoSel = h('span', 'nota num'), preparo = h('p', 'nota');
    const acoesCaps = h('div', 'webia-linha');
    const btnTodos = btn('Selecionar todos', 'pequeno', () => { const todos = linhas.length === marcados.size; marcados.clear(); if (!todos) linhas.forEach((c) => marcados.add(c.rel)); desenharLista(); });
    let carregou = false, ocupado = false; const emFila = new Set();                   // preparação em andamento: não deixa pedir de novo
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
      if (!linhas.length) { lista.replaceChildren(h('p', 'nota vazio', carregou ? 'Todos os capítulos desta obra já estão traduzidos.' : 'Carregando…')); resumo(); return; }
      lista.replaceChildren(...linhas.slice().reverse().map((c) => {
        const e = estado.get(c.rel), l = h('label', 'webia-cap');
        const i = h('input'); i.type = 'checkbox'; i.checked = marcados.has(c.rel);
        i.addEventListener('change', () => { if (i.checked) marcados.add(c.rel); else marcados.delete(c.rel); resumo(); });
        const t = !e?.textos && emFila.has(c.rel) ? 'preparando…' : e?.textos ? `${e.importados}/${e.textos} traduzidos` + (e.completo ? ' · completo' : e.importados ? ` · parcial, faltam ${e.textos - e.importados}` : ' · preparado') : (e?.incompleta ? `${e.incompleta} fala(s) com erro · preparar de novo` : 'textos não preparados');
        l.append(i, h('span', 'nome', c.numero != null && c.numero !== '' ? 'Cap. ' + c.numero : c.rotulo), h('span', 'est' + (e?.textos ? (e.completo ? ' ok' : ' ativo') : ''), t));
        return l;
      }));
      lista.scrollTop = topo; resumo();
    }
    function resumo() {
      const prontos = [...marcados].filter((r) => estado.get(r)?.textos).length;
      resumoSel.textContent = `${marcados.size} selecionado(s) · ${prontos} com textos prontos`;
      btnPreparar.disabled = !novos().length;       // com preparação em andamento, capítulos da mesma obra entram nela (o servidor bloqueia outra obra) gerar.disabled = !prontos; resumoSel.title = '';
    }
    async function atualizar() {
      try {
        const t = await ler('/api/traducao/estado', '&log=0'), a = (t.itens || []).find((i) => i.estado === 'traduzindo');
        ocupado = t.estado === 'executando'; emFila.clear(); (t.itens || []).forEach((i) => { if (ocupado && (i.estado === 'fila' || i.estado === 'traduzindo')) emFila.add(i.rel); });
        preparo.textContent = t.estado === 'executando' ? `Preparando textos${a ? ': ' + a.nome + (a.etapa ? ' — ' + a.etapa : '') : '…'} (pode levar alguns minutos; o conteúdo aparece abaixo quando terminar).` : '';
      } catch (_) {}
      try {
        const r = await chamar('/api/web/capitulos', {obra: obra.nome});
        estado.clear(); linhas = r.capitulos; carregou = true; [...marcados].forEach((m) => { if (!r.capitulos.some((c) => c.rel === m)) marcados.delete(m); });
        r.capitulos.forEach((c) => { estado.set(c.rel, c); if (c.textos && !jaVistos.has(c.rel)) { jaVistos.add(c.rel); marcados.add(c.rel); } });
        limite.value = limite.value || r.limite_padrao; desenharLista(); gerarAgora();
      } catch (e) { /* janela fechada ou servidor ocupado: tenta na próxima */ }
    }

    /* ---- 2. exportar */
    const sExp = h('section', 'webia-sec'); sExp.append(h('h4', '', '2. Exportar os textos'));
    const cbIntro = h('input'); cbIntro.type = 'checkbox'; cbIntro.checked = true;
    const lIntro = h('label', 'marcar'); lIntro.append(cbIntro, ' Incluir introdução com instruções para a IA (PT-BR, manter identificadores, não resumir…)');
    const cbPend = h('input'); cbPend.type = 'checkbox';
    const lPend = h('label', 'marcar'); lPend.append(cbPend, ' Só as falas pendentes (sem tradução importada ainda)');
    const rUm = h('input'); rUm.type = 'radio'; rUm.name = 'webia-modo'; rUm.checked = true;
    const rVarios = h('input'); rVarios.type = 'radio'; rVarios.name = 'webia-modo';
    const lUm = h('label', 'marcar'); lUm.append(rUm, ' Um único arquivo');
    const limite = h('input'); limite.type = 'number'; limite.min = '2000'; limite.max = '100000'; limite.step = '1000'; limite.setAttribute('aria-label', 'Caracteres por arquivo');
    const lVarios = h('label', 'marcar'); lVarios.append(rVarios, ' Vários arquivos, de até ', limite, ' caracteres');
    const modo = h('div', 'webia-linha'); modo.append(lUm, lVarios);
    const resultado = h('div', 'webia-resultado');
    const pedido = () => ({obra: obra.nome, rels: [...marcados].filter((r) => estado.get(r)?.textos), introducao: cbIntro.checked, dividir: rVarios.checked, limite: Number(limite.value) || 12000, somente_pendentes: cbPend.checked});
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
    [cbIntro, cbPend, rUm, rVarios, limite].forEach((i) => i.addEventListener('change', () => gerarAgora()));
    sExp.append(lIntro, lPend, modo, h('div', 'webia-linha').appendChild(gerar).parentNode, resultado);
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
      seq++; final.textContent = ''; final.className = 'nota';
      mostrar(r, gravar);
      if (!gravar) return;
      if (r.relatorio.capitulos.length && !r.relatorio.capitulos.some((c) => c.original_reenviado)) limparRasc();   // só limpa depois de gravar com sucesso
      atualizar();
      if (r.aviso) { final.className = 'nota aviso'; final.textContent = r.aviso; }
      if (r.aplicando?.length && r.iniciou) { document.dispatchEvent(new CustomEvent('traducao-iniciada')); confirmar(r.aplicando, Object.fromEntries(r.relatorio.capitulos.map((c) => [c.rel, c.rotulo]))); }
    };
    const chaveRasc = 'webia-rascunho:' + obra.nome;                       // rascunho: sobrevive a fechar o modal e a recarregar a página
    try { area.value = localStorage.getItem(chaveRasc) || ''; } catch (_) {}
    let tRasc = 0;
    area.addEventListener('input', () => { clearTimeout(tRasc); tRasc = setTimeout(() => { try { area.value ? localStorage.setItem(chaveRasc, area.value) : localStorage.removeItem(chaveRasc); } catch (_) {} }, 400); });
    const limparRasc = () => { clearTimeout(tRasc); try { localStorage.removeItem(chaveRasc); } catch (_) {} area.value = ''; };
    const escolher = btn('Escolher arquivos TXT…', '', () => arq.click());
    const acoesImp = h('div', 'webia-linha');
    acoesImp.append(btn('Limpar rascunho', 'pequeno', limparRasc), escolher, nomes, btn('Verificar (não grava)', '', () => enviar(false)), btn('Importar', 'principal', () => enviar(true)), arq);
    sImp.append(area, acoesImp, relatorio);

    function mostrar(r, gravou) {
      const rel = r.relatorio, linhasR = [], caps = rel.capitulos;
      const novas = caps.reduce((n, c) => n + c.novas, 0);
      const cab2 = `${rel.linhas} linha(s) de fala reconhecida(s)` + (rel.introducao_ignorada ? ` · ${rel.introducao_ignorada} linha(s) da introdução de instruções reconhecida(s) e ignorada(s)` : '') + (rel.total_fora ? ` · ${rel.total_fora} linha(s) fora da estrutura ignorada(s)` : '');
      linhasR.push(['nota', cab2]);
      if (!caps.length) linhasR.push(['erro', 'Nada foi importado: nenhum identificador conhecido foi encontrado. Confira se colou o texto devolvido pela IA, com as linhas [código:fala] intactas.']);
      caps.forEach((c) => {
        if (c.original_reenviado) { linhasR.push(['erro', `${c.rotulo}: REJEITADO — o texto colado é o original em inglês, sem tradução (${c.iguais_ao_original.length} falas iguais ao original). Nada deste capítulo foi importado.`]); return; }
        const ok = c.completo && !c.desconhecidos.length && !c.duplicados.length && !c.quebrados.length && !c.vazios.length;
        linhasR.push([ok ? 'ok' : (c.completo ? 'aviso' : 'erro'), `${c.rotulo}: ${c.ja_importados + c.novas}/${c.esperados} traduzidos${gravou ? '' : ` (${c.novas} novos)`}` + (c.completo ? ' · todas as falas têm tradução' : ` · faltam ${c.qtd_faltam}`)]);
        const det = (rot, v) => { if (v.length) linhasR.push(['nota', `   ${rot}: ${v.join(', ')}`]); };
        linhasR.push([c.faltam.length ? 'erro' : 'nota', '   ' + c.mensagem]);
        if (c.ausentes.length) linhasR.push(['nota ausentes', '   Identificadores que faltam:\n' + c.ausentes.join(c.ausentes.length > 30 ? ' ' : '\n')]);
        if (c.mantidas.length) linhasR.push(['nota', `   já traduzidos antes (mantida a tradução anterior, não sobrescrita): ${c.mantidas.join(', ')}`]);
        det('identificador desconhecido (ignorado)', c.desconhecidos); det('duplicados com textos diferentes (ignorados)', c.duplicados);
        det('linha quebrada ou com texto extra (ignorada)', c.quebrados); det('sem texto traduzido (ignorada)', c.vazios);
        if (c.iguais_ao_original.length) linhasR.push(['aviso', `   iguais ao original (aceitas, confira se deviam mudar): ${c.iguais_ao_original.join(', ')}`]);
      });
      const amb = Object.entries(rel.codigos_ambiguos || {});
      if (amb.length) linhasR.push(['erro', 'Código repetido em mais de um capítulo (nada importado para eles): ' + amb.map(([k, v]) => `${k} → ${v.join(' / ')}`).join('; ')]);
      if (rel.codigos_desconhecidos.length) linhasR.push(['aviso', `Códigos de capítulo desconhecidos (ignorados): ${rel.codigos_desconhecidos.join(', ')}. Prepare os textos e exporte de novo.`]);
      if (rel.total_fora) linhasR.push(['nota', `Fora da estrutura (ignoradas): ${rel.linhas_fora_da_estrutura.join(' | ')}`]);
      const incompletos = caps.filter((c) => !c.completo);
      if (!gravou) linhasR.push(['nota', 'Verificação feita: nada foi gravado.']);
      else if (!novas && !caps.some((c) => c.ja_importados)) linhasR.push(['erro', 'Nada foi importado: nenhuma tradução válida foi encontrada no texto colado.']);
      else if (incompletos.length) linhasR.push(['aviso', `Traduções válidas guardadas (${novas} nova(s)). ${incompletos.length} capítulo(s) ainda incompleto(s): importe as falas que faltam e ele é aplicado sozinho. Nada foi aplicado neles.`]);
      relatorio.replaceChildren(...linhasR.map(([cl, t]) => { const p = h('p', 'nota ' + cl, t); if (cl.includes('ausentes')) p.style.whiteSpace = 'pre-wrap'; return p; }));
    }
    const final = h('p', 'nota'); final.setAttribute('role', 'status'); relatorio.after(final);
    let seq = 0;
    async function confirmar(rels, rotulos) {                              // só diz "aplicado" depois de conferir no capítulo
      const meu = ++seq, nome = (r) => rotulos[r] || r;
      final.className = 'nota aviso'; final.textContent = `Aplicando ${rels.length} capítulo(s)… aguarde a confirmação.`;
      let ultimo = {}, parou = 0;
      for (let k = 0; k < 400 && meu === seq && dlg; k++) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
          ultimo = (await chamar('/api/web/aplicados', {rels})).aplicados;
          const t = await ler('/api/traducao/estado', '&log=0');
          if (rels.every((r) => ultimo[r])) break;
          parou = t.estado === 'executando' ? 0 : parou + 1;
          if (parou >= 3) break;                                          // a tarefa acabou e o capítulo não ficou aplicado
        } catch (_) {}
      }
      if (meu !== seq) return;
      const ok = rels.filter((r) => ultimo[r]), mal = rels.filter((r) => !ultimo[r]);
      final.className = 'nota ' + (mal.length ? (ok.length ? 'aviso' : 'erro') : 'ok');
      final.textContent = (ok.length ? `Concluído e aplicado: ${ok.map(nome).join(', ')}. ` : '') + (mal.length ? `NÃO aplicado: ${mal.map(nome).join(', ')} — veja a aba Traduções; as traduções importadas continuam guardadas, clique em Importar de novo para tentar outra vez.` : 'Os capítulos já podem ser lidos.');
      atualizar();
    }

    /* ---- 4. glossário da obra */
    const sGlo = h('section', 'webia-sec'); sGlo.append(h('h4', '', 'Glossário da obra'));
    sGlo.append(h('p', 'nota', 'Um termo por linha, no formato TERMO = tradução. Vale só para esta obra: entra na introdução enviada à IA e é conferido pelo tradutor local.'));
    const areaGlo = h('textarea', 'webia-area'); areaGlo.rows = 8; areaGlo.spellcheck = false; areaGlo.setAttribute('aria-label', 'Glossário');
    const doTexto = (t) => Object.fromEntries(t.split('\n').map((l) => l.split('=')).filter((p) => p.length >= 2 && p[0].trim()).map((p) => [p[0].trim(), p.slice(1).join('=').trim()]));
    (async () => { try { const g = await chamar('/api/web/glossario', {obra: obra.nome}); areaGlo.value = Object.entries(g.termos).map(([k, v]) => `${k} = ${v}`).join('\n'); } catch (_) {} })();
    sGlo.append(areaGlo, btn('Salvar glossário', 'principal', async () => { try { const g = await chamar('/api/web/glossario/salvar', {obra: obra.nome, termos: doTexto(areaGlo.value)}); aviso(`Glossário salvo: ${Object.keys(g.termos).length} termo(s).`); } catch (e) { aviso(e.message); } }));

    /* ---- 5. revisão por IA */
    const sRev = h('section', 'webia-sec'); sRev.append(h('h4', '', 'Revisão por IA'));
    sRev.append(h('p', 'nota', 'Exporta só as falas marcadas “revisar” ou “erro” (original + tradução atual). Cole a resposta da IA abaixo: só essas falas são atualizadas.'));
    const areaRev = h('textarea', 'webia-area'); areaRev.rows = 5; areaRev.spellcheck = false; areaRev.setAttribute('aria-label', 'Texto revisado');
    const saidaRev = h('p', 'nota'); saidaRev.setAttribute('role', 'status');
    const enviarRev = async (gravar) => {
      if (!areaRev.value.trim()) { aviso('Cole o texto revisado.'); return; }
      try { const r = await chamar('/api/web/revisao/importar', {obra: obra.nome, textos: [areaRev.value], gravar}); saidaRev.className = 'nota ' + (r.alteradas ? 'ok' : 'erro'); saidaRev.textContent = `${gravar ? 'Atualizadas' : 'Atualizaria'} ${r.alteradas} fala(s)` + (r.ignoradas.length ? ` · ${r.ignoradas.length} ignorada(s): ${r.ignoradas.slice(0, 5).map((x) => x.id + ' (' + x.motivo + ')').join(', ')}` : '') + (r.desconhecidas ? ` · ${r.desconhecidas} linha(s) com código desconhecido` : ''); if (gravar && r.alteradas) { areaRev.value = ''; document.dispatchEvent(new CustomEvent('biblioteca-mudou')); } } catch (e) { aviso(e.message); }
    };
    sRev.append(btn('Copiar falas para revisar', 'principal pequeno', async () => { try { const r = await chamar('/api/web/revisao/exportar', {obra: obra.nome}); aviso((await copiar(r.arquivo.conteudo)) ? `${r.arquivo.textos} fala(s) copiada(s). Cole na IA.` : 'Não consegui copiar.'); } catch (e) { aviso(e.message); } }),
      areaRev, h('div', 'webia-linha').appendChild(btn('Verificar (não grava)', '', () => enviarRev(false))).parentNode, saidaRev);
    sRev.querySelector('.webia-linha').append(btn('Aplicar revisão', 'principal', () => enviarRev(true)));

    const abas = h('div', 'webia-abas'), corpo = h('div', 'webia-corpo'), secoes = [sCaps, sExp, sImp, sGlo, sRev];
    abas.setAttribute('role', 'tablist');
    const botoes = ['Capítulos', 'Exportar', 'Importar', 'Glossário', 'Revisão'].map((t, k) => { const b = h('button', 'webia-aba', t); b.type = 'button'; b.setAttribute('role', 'tab'); b.addEventListener('click', () => ir(k)); return b; });
    function ir(k) { secoes.forEach((x, i) => { x.hidden = i !== k; botoes[i].classList.toggle('ativa', i === k); botoes[i].setAttribute('aria-selected', String(i === k)); }); corpo.scrollTop = 0; }
    abas.append(...botoes); corpo.append(nota, ...secoes); ir(0);
    dlg.append(cab, abas, corpo);
    document.body.append(dlg);
    dlg.addEventListener('close', () => { clearInterval(timer); dlg.remove(); dlg = null; });
    desenharLista(); atualizar(); timer = setInterval(atualizar, 4000);
    dlg.showModal();
  }
  window.WebIA = {abrir};
})();
