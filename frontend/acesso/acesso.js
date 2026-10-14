// Painel novo do controle de acesso (/v3/acesso/), fase 1: so leitura.
// Usa o mesmo login das telas atuais (cookie) e a mesma API; as rotas
// /api/access-control/painel/* sao novas e nao mudam nada que o legado usa.
(function () {
  'use strict';
  const BASE = typeof API_BASE !== 'undefined' ? API_BASE : window.location.origin;
  const $ = (sel) => document.querySelector(sel);
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  let tela = 'vivo';
  let site = '';
  let fonte = null;
  let timer = null;
  let carregando = false;

  async function get(caminho) {
    const res = await fetch(BASE + caminho, { credentials: 'same-origin' });
    if (res.status === 401) { window.location.href = '../'; throw new Error('sem login'); }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return res.json();
  }

  // ---- datas: o leitor grava hora local sem fuso; o WhatsApp grava UTC ----
  const local = (s) => { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T')); return isNaN(d) ? null : d; };
  const utc = (s) => { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T') + 'Z'); return isNaN(d) ? null : d; };
  const hm = (d) => d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '';
  const hms = (d) => d ? d.toLocaleTimeString('pt-BR') : '';
  function haQuanto(d) {
    if (!d) return 'nunca';
    const m = Math.round((Date.now() - d.getTime()) / 60000);
    if (m < 1) return 'agora';
    if (m < 60) return `há ${m} min`;
    if (m < 48 * 60) return `há ${Math.round(m / 60)} h`;
    return d.toLocaleDateString('pt-BR');
  }
  const iniciais = (n) => String(n || '?').trim().split(/\s+/).filter(Boolean).slice(0, 2).map((x) => x[0]).join('').toUpperCase() || '?';
  const foto = (p) => p.pessoa_id && p.tem_foto
    ? `<img src="${BASE}/api/access-control/people/${encodeURIComponent(p.pessoa_id)}/face-photo" alt="" loading="lazy" onerror="this.remove()">` : '';
  const tipoTxt = (t) => (t === 'saida' || t === 'saida_manual') ? 'SAIU' : 'ENTROU';

  // Porta "viva": o status gravado do leitor nao e confiavel (na escola os dois
  // apareciam offline com 182 marcacoes no dia). Ultima marcacao conta junto.
  function portaViva(p) {
    const ultima = local(p.ultima);
    const recente = ultima && (Date.now() - ultima.getTime()) < 30 * 60000;
    return String(p.status).toLowerCase() === 'online' || recente;
  }

  // ---------------------------------------------------------------- ao vivo
  function recibo(p) {
    const a = p.aviso || {};
    if (a.status === 'sem_pessoa') return '<div class="recibo"><div>Pessoa sem cadastro no SightOps: sem aviso.</div></div>';
    if (a.status === 'sem_aviso') return usaAvisos ? '<div class="recibo"><div>Sem número de responsável cadastrado: sem aviso.</div></div>' : '';
    if (!a.status) return `<div class="recibo"><div>Aviso ainda não registrado${a.para ? ' para ' + esc(a.para) : ''}.</div></div>`;
    const env = utc(a.enviado), at = utc(a.atualizado);
    const ordem = { enviado: 1, entregue: 2, lido: 3 };
    const nivel = ordem[a.status] || 0;
    const passo = (rot, n, hora) => `<div class="passo ${a.status === 'falha' && n === 2 ? 'falha' : (nivel >= n ? 'feito' : '')}">
        <i>${a.status === 'falha' && n === 2 ? '!' : '✓'}</i><b>${rot}</b><span class="mono">${hora || ''}</span></div>`;
    const liga = (n) => `<div class="liga ${nivel >= n ? 'feito' : ''}"></div>`;
    const passos = a.status === 'falha'
      ? passo('Enviado', 1, hms(env)) + liga(2) + passo('Não entregue', 2, hms(at)) +
        `<div style="flex:2;font-size:12.5px;color:#f3c1c5;padding:4px 0 0 10px">${esc(a.erro || 'a Meta recusou o envio')}</div>`
      : passo('Enviado', 1, hms(env)) + liga(2) + passo('Entregue', 2, nivel >= 2 ? hms(nivel === 2 ? at : null) : '') + liga(3) + passo('Lido', 3, nivel >= 3 ? hms(at) : '');
    return `<div class="recibo"><div>Aviso para <b style="color:#e6f0f3">${esc(a.para || 'responsável')}</b> · WhatsApp</div><div class="passos">${passos}</div></div>`;
  }

  function zap(p) {
    const s = (p.aviso || {}).status;
    if (s === 'lido') return '<span class="z-lido">✓✓ lido</span>';
    if (s === 'entregue') return '<span>✓✓ entregue</span>';
    if (s === 'enviado') return '<span>✓ enviado</span>';
    if (s === 'falha') return '<span class="z-falha">aviso falhou</span>';
    if (s === 'sem_pessoa') return '<span class="z-falha">sem cadastro</span>';
    return usaAvisos ? '<span>sem aviso</span>' : '';
  }

  let usaAvisos = false;
  function desenharVivo(d) {
    const el = $('#tela-vivo');
    usaAvisos = Object.keys(d.avisos_hoje || {}).length > 0;
    const passagens = d.passagens || [];
    const ult = passagens[0];
    const r = d.resumo || {};
    const portas = (d.portas || []).map((p) => {
      const viva = portaViva(p);
      return `<div class="v-porta ${viva ? '' : 'ruim'}"><span class="pt ${viva ? 'ok' : 'ruim'}"></span>
        <div>${esc(p.nome)}<small>${p.hoje} hoje · ${p.ultima ? 'última ' + hm(local(p.ultima)) : 'sem marcação hoje'}</small></div></div>`;
    }).join('');
    const alertas = [];
    const ag = d.avisos_agora || {};
    if (ag.alerta) {
      alertas.push(`<div class="v-alerta" role="alert"><span class="pt ruim"></span><div><b>Avisos de WhatsApp falhando agora</b>
        <span>· ${ag.falhas} de ${ag.enviados} nos últimos ${ag.janela_min} min · ${esc(ag.erro_principal || 'sem motivo da Meta')}</span></div></div>`);
    }
    if (ult && !ult.pessoa_id && (Date.now() - (local(ult.hora) || 0)) < 5 * 60000) {
      alertas.push(`<div class="v-alerta" role="alert"><span class="pt ruim"></span><div><b>Passagem de pessoa sem cadastro no SightOps</b>
        <span>· ${esc(ult.porta)} · ${hm(local(ult.hora))}${ult.nome ? ' · leitor diz "' + esc(ult.nome) + '"' : ''}</span></div></div>`);
    }
    const ah = d.avisos_hoje || {};
    const totAv = (ah.lido || 0) + (ah.entregue || 0) + (ah.enviado || 0) + (ah.falha || 0);
    const turmas = (d.turmas || []).filter((t) => t.total);
    const temTurmas = turmas.length > 1 || (turmas[0] && turmas[0].turma !== 'Sem turma');

    el.innerHTML = `
      <div class="v-cab">
        <div class="v-titulo"><small>PORTARIA · AO VIVO</small><b>${esc(site || 'Todos os sites')}</b></div>
        <div class="v-relogio"><b class="mono" id="relogio">${hms(new Date())}</b><span>${new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' })}</span></div>
      </div>
      <div class="v-portas">${portas}</div>
      ${alertas.join('')}
      <div class="v-meio">
        ${ult ? `<section class="v-hero" aria-label="Última passagem">
          <div class="v-foto">${iniciais(ult.nome)}${foto(ult)}<span class="dir ${ult.tipo.startsWith('saida') ? 'saida' : ''}">${tipoTxt(ult.tipo)}</span></div>
          <div class="v-info">
            <div><div class="rot">Última passagem · ${haQuanto(local(ult.hora))}</div>
              <div class="v-nome">${esc(ult.nome || 'Pessoa não identificada')}</div>
              <div class="v-sub">${esc([ult.turma, ult.pessoa_id ? '' : 'sem cadastro no SightOps'].filter(Boolean).join(' · '))}</div></div>
            <div class="v-dados">
              <div><small>Porta</small><b>${esc(ult.porta)}</b></div>
              <div><small>Horário</small><b class="mono">${hms(local(ult.hora))}</b></div>
            </div>
            ${recibo(ult)}
          </div></section>` : '<section class="v-hero"><div class="v-vazio">Nenhuma passagem hoje.</div></section>'}
        <section class="v-lado" aria-label="Hoje">
          <h2>Hoje</h2>
          <div class="v-num">
            <div><small>Presentes agora</small><b>${r.inside_now ?? 0}</b></div>
            <div><small>Entradas</small><b>${r.entries ?? 0}</b></div>
            <div><small>Saídas</small><b>${(r.exits ?? 0)}</b></div>
            <div><small>Sem cadastro</small><b>${r.without_person ?? 0}</b></div>
            ${usaAvisos ? `<div><small>Avisos lidos</small><b>${totAv ? Math.round((ah.lido || 0) * 100 / totAv) + '%' : '—'}</b></div>
            <div><small>Avisos falhos</small><b>${ah.falha || 0}</b></div>` : ''}
          </div>
          ${temTurmas ? `<h2>Presença por turma</h2><div class="turmas">${turmas.map((t) => `<div class="turma">
            <div><b>${esc(t.turma)}</b><span class="mono">${t.presentes}/${t.total}</span></div>
            <div class="trilho"><i style="width:${t.total ? Math.round(t.presentes * 100 / t.total) : 0}%"></i></div></div>`).join('')}</div>` : ''}
        </section>
      </div>
      <section aria-label="Passagens recentes">
        <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px">
          <h2 style="margin:0;font-size:16px">Passagens recentes</h2><span style="font-size:13px;color:#9fb4bd">${r.total ?? passagens.length} hoje</span></div>
        <div class="fila">${passagens.slice(1, 25).map((p) => `<div class="cartao ${p.pessoa_id ? '' : 'ruim'}">
          <div class="mini">${iniciais(p.nome)}${foto(p)}<span class="dir ${p.tipo.startsWith('saida') ? 'saida' : ''}">${tipoTxt(p.tipo)}</span><span class="h mono">${hm(local(p.hora))}</span></div>
          <b>${esc(p.nome || 'sem nome')}</b><small><span>${esc(p.turma || p.porta)}</span>${zap(p)}</small></div>`).join('')}</div>
      </section>`;
  }

  // ---------------------------------------------------------------- visao geral
  function pct(a, b) { return b ? Math.round(a * 100 / b) : 0; }

  function desenharGeral(d) {
    const el = $('#tela-geral');
    const av = d.avisos || {}, s7 = av.sete_dias || {};
    const env = s7.enviados || 0;
    const entregue = (s7.lidos || 0) + (s7.entregues || 0);
    const m7 = d.marcacoes_7d || {}, fotos = d.fotos || {}, leit = d.leitores || {};
    const semP = pct(m7.sem_pessoa || 0, m7.total || 0);
    const card = (rot, val, sub, cls) => `<div class="card ${cls === 'cor-ruim' ? 'ruim' : cls === 'cor-aviso' ? 'aviso' : ''}">
      <small><span class="pt ${cls}"></span>${rot}</small><b>${val}</b><span>${sub}</span></div>`;
    const maxDia = Math.max(1, ...(av.serie_30d || []).map((x) => x.lido + x.entregue + x.enviado + x.falha));
    const h = (n) => Math.round(n * 100 / maxDia) + '%';
    const fmtDia = (s) => s ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : '';
    const serie = av.serie_30d || [];
    const usaAvisosGeral = serie.some((x) => x.lido + x.entregue + x.enviado + x.falha) || (av.incidentes || []).length > 0;
    // So portas com volume que importa: 1 marcacao sem pessoa em 370 nao e problema.
    const portasSem = (m7.por_porta || []).filter((p) => p.sem_pessoa >= 20 || pct(p.sem_pessoa, p.total) >= 5);

    el.innerHTML = `
      <div class="g-cab"><small>CONTROLE DE ACESSO</small><h1>Visão geral</h1>
        <p>O que está funcionando, o que parou e o que precisa de alguém · ${esc(site || 'todos os sites')}</p></div>
      <div class="cards">
        ${env ? card('Avisos entregues · 7 dias', pct(entregue, env) + '%', `${pct(s7.lidos || 0, env)}% lidos pelos responsáveis`, pct(entregue, env) >= 95 ? 'cor-ok' : 'cor-ruim')
              : card('Avisos de WhatsApp', '—', 'nenhum aviso nos últimos 7 dias', '')}
        ${card('Marcações sem pessoa · 7 dias', semP + '%', `${m7.sem_pessoa || 0} de ${m7.total || 0}`, semP > 10 ? 'cor-ruim' : 'cor-ok')}
        ${card('Fotos recusadas pelo leitor', fotos.falhou || 0, 'pessoas que não abrem a porta', fotos.falhou ? 'cor-aviso' : 'cor-ok')}
        ${card('Leitores com status online', `${leit.online || 0} / ${leit.total || 0}`, 'status informado pelo leitor', leit.online === leit.total ? 'cor-ok' : 'cor-aviso')}
      </div>

      ${env || (av.incidentes || []).length ? `<section class="bloco">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;align-items:baseline">
          <div><h2>Avisos aos responsáveis · 30 dias</h2><p style="margin:0;font-size:13px;color:#66747e">O WhatsApp informa entrega e leitura de cada aviso.</p></div>
          <div class="legenda"><span><i style="background:#087f5b"></i>lido</span><span><i style="background:#8fd3b8"></i>entregue</span><span><i style="background:#dfe4e8"></i>sem confirmação</span><span><i style="background:#c92a2a"></i>não entregue</span></div>
        </div>
        <div class="grafico">${serie.map((x) => `<div class="dia" title="${fmtDia(x.dia)}: ${x.lido} lidos, ${x.entregue} entregues, ${x.falha} não entregues">
          <i style="height:${h(x.falha)};background:#c92a2a"></i><i style="height:${h(x.enviado)};background:#dfe4e8"></i>
          <i style="height:${h(x.entregue)};background:#8fd3b8"></i><i style="height:${h(x.lido)};background:#087f5b"></i></div>`).join('')}</div>
        <div class="eixo mono"><span>${fmtDia(serie[0]?.dia)}</span><span>${fmtDia(serie[15]?.dia)}</span><span>${fmtDia(serie[29]?.dia)}</span></div>
        ${(av.incidentes || []).slice().reverse().slice(0, 3).map((i) => `<div class="incidente"><span class="pt"></span><div>
          <b>${fmtDia(i.inicio)}${i.fim !== i.inicio ? ' a ' + fmtDia(i.fim) : ''}: ${i.falhas.toLocaleString('pt-BR')} avisos não chegaram aos responsáveis.</b>
          ${i.erro ? ` Motivo informado pela Meta: "${esc(i.erro)}"${/payment/i.test(i.erro) ? ' (pendência de pagamento da conta do WhatsApp Business)' : ''}.` : ''}</div></div>`).join('')}
        <div class="dica">Agora, se mais de 10% dos avisos falharem em 30 minutos, o canal de WhatsApp fica fora no monitoramento: aparece no painel e no Zabbix, e vai ao Telegram com o motivo.</div>
      </section>` : ''}

      <div class="duas">
        ${!usaAvisosGeral ? `<section class="bloco"><h2>Avisos por WhatsApp</h2>
          <p class="vazio">Nenhum aviso enviado nos últimos 60 dias: este cliente não usa os avisos aos responsáveis.</p></section>` : `<section class="bloco">
          <h2>Responsáveis que não estão recebendo</h2>
          <p>O último aviso para estes números falhou. Motivo dado pela Meta.</p>
          ${(av.falhando || []).length ? av.falhando.map((f) => `<div class="linha"><div class="cresce"><b>${esc(f.responsavel || 'número sem cadastro')}</b>
              <small>${esc([f.pessoa, f.turma].filter(Boolean).join(' · '))}</small></div>
            <span class="mono" style="font-size:13px">${esc(f.numero)}</span><span class="erro">${esc(f.erro || 'falhou')}</span></div>`).join('')
            : '<p class="vazio">Nenhum responsável com aviso falhando.</p>'}
          ${av.sem_numero_total ? `<div class="dica">${av.sem_numero_total} aluno${av.sem_numero_total === 1 ? '' : 's'} sem número de responsável: não recebe${av.sem_numero_total === 1 ? '' : 'm'} aviso nenhum.</div>` : ''}
        </section>`}
        <section class="bloco">
          <h2>Marcações sem pessoa no SightOps</h2>
          <p>A pessoa está no leitor, mas não no cadastro: fica fora de relatório, presença e aviso.</p>
          ${portasSem.length ? portasSem.map((p) => `<div class="linha"><div class="cresce"><b>${esc(p.porta)}</b>
              <small>${p.sem_pessoa} de ${p.total} marcações · ${p.nomes_distintos} nome${p.nomes_distintos === 1 ? '' : 's'} diferentes${p.exemplos.length ? ' · ex.: ' + p.exemplos.map(esc).join(', ') : ''}</small>
              <div class="barra"><i style="width:${pct(p.sem_pessoa, p.total)}%"></i></div></div>
            <b class="ruim-txt">${pct(p.sem_pessoa, p.total)}%</b></div>`).join('')
            : '<p class="vazio">Todas as marcações estão ligadas a uma pessoa.</p>'}
          ${portasSem.length ? '<div class="dica">Para corrigir hoje: na tela atual, Controle de Acesso › Dispositivos › importar pessoas do leitor.</div>' : ''}
        </section>
      </div>

      <div class="duas">
        <section class="bloco">
          <h2>Fotos recusadas pelos leitores</h2>
          <p>${fotos.ok || 0} fotos aceitas · ${fotos.falhou || 0} recusadas${fotos.pendente ? ' · ' + fotos.pendente + ' aguardando' : ''}</p>
          ${(fotos.recusadas || []).length ? fotos.recusadas.map((f) => `<div class="linha"><div class="cresce"><b>${esc(f.pessoa)}</b>
              <small>${esc([f.turma, f.leitor].filter(Boolean).join(' · '))}</small></div><span class="erro">${esc(f.erro || 'recusada')}</span></div>`).join('')
            : '<p class="vazio">Nenhuma foto recusada.</p>'}
        </section>
        <section class="bloco">
          <h2>Leitores</h2>
          <p>Status informado pelo leitor e última vez que o SightOps falou com ele.</p>
          ${(leit.lista || []).map((l) => `<div class="linha"><span class="pt ${String(l.status).toLowerCase() === 'online' ? 'cor-ok' : 'cor-ruim'}"></span>
            <div class="cresce"><b>${esc(l.nome)}</b><small>${esc(l.site)} · visto ${haQuanto(utc(l.visto) || local(l.visto))}</small></div>
            <span class="${String(l.status).toLowerCase() === 'online' ? 'ok-txt' : 'ruim-txt'}">${esc(l.status || 'sem status')}</span></div>`).join('') || '<p class="vazio">Nenhum leitor cadastrado.</p>'}
        </section>
      </div>`;
  }

  // ---------------------------------------------------------------- ciclo
  async function atualizar() {
    if (carregando) return;
    carregando = true;
    try {
      const q = site ? `?site=${encodeURIComponent(site)}` : '';
      if (tela === 'vivo') desenharVivo(await get(`/api/access-control/painel/ao-vivo${q}`));
      else desenharGeral(await get(`/api/access-control/painel/visao-geral${q}`));
    } catch (e) {
      const alvo = tela === 'vivo' ? $('#tela-vivo') : $('#tela-geral');
      if (alvo && !alvo.innerHTML) alvo.innerHTML = `<p class="vazio">Não consegui carregar: ${esc(e.message)}</p>`;
    } finally {
      carregando = false;
    }
  }

  function ligarAoVivo() {
    if (fonte) { fonte.close(); fonte = null; }
    if (tela !== 'vivo' || typeof EventSource === 'undefined') return;
    const q = site ? `?site=${encodeURIComponent(site)}` : '';
    fonte = new EventSource(`${BASE}/api/access-control/live/stream${q}`, { withCredentials: true });
    fonte.addEventListener('access-event', () => atualizar());
  }

  function trocarTela(nova) {
    tela = nova;
    document.body.classList.toggle('portaria', tela === 'vivo');
    document.querySelectorAll('[data-tela]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.tela === tela)));
    $('#tela-vivo').hidden = tela !== 'vivo';
    $('#tela-geral').hidden = tela !== 'geral';
    try { localStorage.setItem('sightops.acesso.tela', tela); } catch (_) {}
    ligarAoVivo();
    atualizar();
  }

  async function iniciar() {
    // Sites: os dos leitores do cliente.
    try {
      const g = await get('/api/access-control/painel/visao-geral');
      const sites = [...new Set(((g.leitores || {}).lista || []).map((l) => l.site).filter(Boolean))].sort();
      $('#site').innerHTML = '<option value="">Todos os sites</option>' + sites.map((s) => `<option>${esc(s)}</option>`).join('');
      if (sites.length === 1) { site = sites[0]; $('#site').value = site; }
    } catch (_) { /* sem login: get() ja redirecionou */ }
    $('#site').addEventListener('change', () => { site = $('#site').value; ligarAoVivo(); atualizar(); });
    document.querySelectorAll('[data-tela]').forEach((b) => b.addEventListener('click', () => trocarTela(b.dataset.tela)));
    let salva = 'vivo';
    try { salva = localStorage.getItem('sightops.acesso.tela') || 'vivo'; } catch (_) {}
    trocarTela(salva === 'geral' ? 'geral' : 'vivo');
    // Rede de seguranca do stream: atualiza a cada 20 s mesmo sem evento.
    timer = setInterval(() => { if (!document.hidden) atualizar(); }, 20000);
    setInterval(() => { const r = $('#relogio'); if (r) r.textContent = hms(new Date()); }, 1000);
  }

  iniciar();
})();
