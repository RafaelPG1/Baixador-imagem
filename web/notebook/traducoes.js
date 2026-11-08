/* Aba Traduções: acompanha a tradução em andamento (a mesma tarefa usada pela Biblioteca e pelo "Traduzir automaticamente"). */
(() => {
  let cursorLog = 0, rodando = false, vistoInicio = 0, pendente = null;
  const ROTULO = {fila: 'Na fila', traduzindo: 'Traduzindo…', pronto: 'Pronto', falhou: 'Falhou', cancelado: 'Cancelado'};
  const REFINO = {fila: 'aguardando refino', refinando: 'refinando', pronto: 'refinado', cancelado: 'refino cancelado', indisponivel: 'refino indisponível', falhou: 'refino falhou'};
  const hms = (s) => { s = Math.max(0, Math.round(s)); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = s % 60; return (h ? h + 'h ' : '') + (h || m ? String(m).padStart(h ? 2 : 1, '0') + 'min ' : '') + String(x).padStart(h || m ? 2 : 1, '0') + 's'; };
  const visivel = () => !$('pg-traducoes').hidden;

  function desenhar(e) {
    const ativo = e.estado === 'executando', itens = e.itens || [];
    const algo = ativo || itens.length > 0;
    $('aba-trad-ponto').hidden = !ativo;
    $('tr-vazio').hidden = algo; $('tr-painel').hidden = !algo;
    $('tr-cancelar').hidden = !ativo; $('tr-cancelar').disabled = !!e.cancelando;
    $('tr-cancelar').textContent = e.cancelando ? 'Cancelando…' : e.fase === 'refino' ? 'Cancelar refinamento' : 'Cancelar tradução';
    atualizarRefinar(ativo);
    const refinando = ativo && e.fase === 'refino';
    const chip = $('tr-chip');
    chip.className = 'chip ' + (ativo ? 'ativo' : e.estado === 'concluido' ? 'ok' : e.estado === 'erro' ? (e.erro === 'Tradução cancelada.' ? 'espera' : 'erro') : '');
    chip.textContent = ativo ? (e.cancelando ? 'Cancelando…' : refinando ? 'Refinando' : 'Traduzindo') : e.estado === 'concluido' ? 'Concluída' : e.estado === 'erro' ? (e.erro === 'Tradução cancelada.' ? 'Cancelada' : 'Com erro') : 'Nenhuma tradução';
    if (!algo) return;
    const dep = e.dependencias || {};
    $('tr-aviso').hidden = !!(dep.ocr && dep.traducao);
    $('tr-erro').hidden = !(e.estado === 'erro' && e.erro); $('tr-erro').textContent = e.erro || '';

    const atual = itens.find((i) => i.estado === 'traduzindo');
    const av = $('tr-avisos'); av.hidden = !(e.avisos && e.avisos.length); av.textContent = (e.avisos || []).join(' ');
    const total = e.total || 0, feitas = Math.min(e.feitas || 0, total || e.feitas || 0);
    const emRefino = itens.find((i) => i.refino === 'refinando');
    const fracRefino = e.refino_total ? ((e.refino_feitas || 0) + (emRefino && emRefino.rtotal ? (emRefino.rfeitas || 0) / emRefino.rtotal : 0)) / e.refino_total : 0;
    const pct = e.estado === 'concluido' ? 100 : refinando ? Math.floor(fracRefino * 100) : total ? Math.floor(feitas / total * 100) : 0;
    $('tr-atual').textContent = refinando ? `Refinando com o Hy-MT2: ${emRefino ? emRefino.nome : 'preparando…'} — a tradução do Argos já pode ser lida` : ativo ? (atual ? `Traduzindo agora: ${atual.nome}` : 'Preparando (carregando os modelos de leitura e tradução)…')
      : e.estado === 'concluido' ? 'Tradução concluída.' : e.estado === 'erro' ? (e.erro === 'Tradução cancelada.' ? 'Tradução cancelada.' : 'A tradução parou.') : '';
    const barra = $('tr-barra'); barra.setAttribute('aria-valuenow', String(pct));
    barra.className = 'tr-barra' + (e.estado === 'concluido' ? ' ok' : e.estado === 'erro' && e.erro !== 'Tradução cancelada.' ? ' erro' : '');
    $('tr-barra-in').style.width = pct + '%';
    const fim = e.fim || e.agora, dec = Math.max(0, fim - e.inicio);
    const partes = [`${pct}%${refinando ? ' do refinamento' : ''}`, `${e.prontos}/${e.capitulos} capítulo(s) prontos para ler`, `decorrido ${hms(dec)}`];
    if (ativo && !refinando && feitas > 0 && total > feitas) partes.push(`faltam cerca de ${hms(dec * (total - feitas) / feitas)}`);
    $('tr-numeros').textContent = partes.join(' · ');

    const ul = $('tr-fila');
    ul.replaceChildren(...itens.map((i) => {
      const li = document.createElement('li'); li.className = i.estado;
      const nome = document.createElement('span'); nome.className = 'nome'; nome.textContent = i.nome;
      const est = document.createElement('span'); est.className = 'est';
      est.textContent = (ROTULO[i.estado] || i.estado) + (i.estado === 'traduzindo' && i.total ? ` ${Math.floor((i.feitas || 0) / i.total * 100)}%` : '')
        + (i.refino ? ` · ${REFINO[i.refino] || i.refino}${i.refino === 'refinando' && i.rtotal ? ' ' + Math.floor((i.rfeitas || 0) / i.rtotal * 100) + '%' : ''}` : '');
      li.append(nome, est);
      if (i.rel && ativo && !refinando && (i.estado === 'fila' || (i.estado === 'traduzindo' && itens.length > 1))) {
        const x = document.createElement('button'); x.type = 'button'; x.className = 'btn pequeno'; x.textContent = 'Cancelar';
        x.title = i.estado === 'fila' ? 'Tirar da fila' : 'Cancelar só este capítulo (a fila continua)';
        x.addEventListener('click', async () => { await acao('/api/traducao/cancelar-item', {rel: i.rel}, (r) => (r.onde === 'fila' ? 'Capítulo tirado da fila.' : 'Cancelando este capítulo…')); sondar(); });
        li.append(x);
      }
      if (i.estado === 'traduzindo' && i.total) { const m = document.createElement('div'); m.className = 'mini'; const b = document.createElement('div'); b.style.width = Math.floor((i.feitas || 0) / i.total * 100) + '%'; m.append(b); li.append(m); }
      if (i.estado === 'falhou' && i.motivo) { const x = document.createElement('span'); x.className = 'motivo'; x.textContent = i.motivo; li.append(x); }
      return li;
    }));
    const r = e.resumo;
    $('tr-resumo').textContent = r ? `Resultado: ${r.blocos} trecho(s) traduzido(s) em ${r.com_texto} de ${r.imagens} imagem(ns)` + (r.falhas && r.falhas.length ? ` · ${r.falhas.length} falha(s)` : '') + '.' : '';
    if (e.log && e.log.length) { anexarLog($('tr-log'), e.log); cursorLog = e.log_total; }
  }

  async function sondar() {
    clearTimeout(pendente);
    let proximo = 6000;
    if (!document.hidden) {
      try {
        let e = await ler('/api/traducao/estado', '&log=' + cursorLog);
        if (e.inicio !== vistoInicio || e.log_total < cursorLog) {      // tradução nova: recomeça o registro do zero
          vistoInicio = e.inicio; cursorLog = 0; $('tr-log').textContent = '';
          if (e.log_total) e = await ler('/api/traducao/estado', '&log=0');
        }
        rodando = e.estado === 'executando'; desenhar(e);
        proximo = rodando ? 1000 : visivel() ? 3000 : 6000;
      } catch (_) {}
    }
    pendente = setTimeout(sondar, proximo);
  }
  /* ---- motor de tradução (a configuração é a mesma da Biblioteca) */
  function desenharMotores(cfg) {
    const caixa = $('tr-motor-opcoes');
    if (!caixa.children.length) {
      Object.entries(cfg.motores || {}).forEach(([valor, rotulo]) => {
        const l = document.createElement('label'); l.className = 'marcar';
        const r = document.createElement('input'); r.type = 'radio'; r.name = 'tr-motor'; r.value = valor;
        r.addEventListener('change', async () => { await Motor.escolher(valor); if (valor !== 'argos') verificarHy(); else $('tr-hy-status').textContent = ''; });
        const t = document.createElement('span'); t.textContent = rotulo;
        l.append(r, ' ', t); caixa.append(l);
      });
    }
    caixa.querySelectorAll('input').forEach((r) => { r.checked = r.value === cfg.motor; });
  }
  document.addEventListener('motor-mudou', (ev) => desenharMotores(ev.detail));
  async function verificarHy() {
    const st = $('tr-hy-status'), b = $('tr-hy-verificar'); b.disabled = true; st.textContent = 'Verificando…';
    const h = await Motor.verificar(Motor.atual.motor);
    st.textContent = h.mensagem ? (h.pronto ? '✔ ' : '✖ ') + h.mensagem : ''; st.className = 'nota ' + (h.pronto ? 'ok' : 'erro');
    b.disabled = false;
  }
  $('tr-hy-verificar').addEventListener('click', verificarHy);
  /* ---- botão Refinar: capítulos que já têm tradução do Argos */
  let pendentesRefino = 0, ultimoAtivo = null;
  async function atualizarRefinar(ativo) {
    const b = $('tr-refinar');
    if (ultimoAtivo !== ativo) { ultimoAtivo = ativo; try { pendentesRefino = (await ler('/api/refinar/pendentes')).capitulos; } catch (_) {} }
    b.disabled = ativo || pendentesRefino === 0;
    b.textContent = pendentesRefino ? `Refinar ${pendentesRefino} capítulo${pendentesRefino > 1 ? 's' : ''} já traduzido${pendentesRefino > 1 ? 's' : ''}` : 'Refinar capítulos já traduzidos';
    b.title = pendentesRefino ? 'Melhora com o Hy-MT2 o que o Argos já traduziu; você continua lendo normalmente' : 'Nenhum capítulo traduzido precisa de refinamento';
  }
  $('tr-refinar').addEventListener('click', async () => {
    const st = $('tr-hy-status'); $('tr-refinar').disabled = true;
    try { await chamar('/api/refinar', {}); aviso('Refinamento iniciado.'); document.dispatchEvent(new Event('traducao-iniciada')); }
    catch (e) { st.textContent = '✖ ' + e.message; st.className = 'nota erro'; aviso(e.message); }
    ultimoAtivo = null; sondar();
  });
  Motor.carregar();
  $('tr-cancelar').addEventListener('click', async () => { try { await chamar('/api/traducao/cancelar'); aviso('Cancelando a tradução…'); sondar(); } catch (e) { aviso(e.message); } });
  document.addEventListener('pagina', (ev) => { if (ev.detail === 'traducoes') sondar(); });
  document.addEventListener('traducao-iniciada', sondar);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) sondar(); });
  sondar();
})();
