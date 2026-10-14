// Controle de Acesso · Painel novo (fase 1, so leitura).
// Tela do proprio SightOps (menu lateral > Controle de Acesso > Painel), ao lado
// das telas antigas, que continuam iguais. Dados: /api/access-control/painel/*
// (GET, so leitura). Ao vivo atualiza pelo stream de eventos + a cada 20 s.
let _apTela = 'vivo';
let _apSite = '';
let _apFonte = null;
let _apTimer = null;
let _apRelogio = null;
let _apCarregando = false;
let _apUsaAvisos = false;

// ---- datas: o leitor grava hora local sem fuso; o WhatsApp grava UTC ----
function apLocal(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T')); return isNaN(d) ? null : d; }
function apUtc(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T') + 'Z'); return isNaN(d) ? null : d; }
function apHm(d) { return d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''; }
function apHms(d) { return d ? d.toLocaleTimeString('pt-BR') : ''; }
function apHa(d) {
  if (!d) return 'nunca';
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 1) return 'agora';
  if (m < 60) return `há ${m} min`;
  if (m < 48 * 60) return `há ${Math.round(m / 60)} h`;
  return d.toLocaleDateString('pt-BR');
}
function apIniciais(n) {
  return String(n || '?').trim().split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join('').toUpperCase() || '?';
}
function apFoto(p) {
  return p.pessoa_id && p.tem_foto
    ? `<img src="${API_BASE}/api/access-control/people/${encodeURIComponent(p.pessoa_id)}/face-photo" alt="" loading="lazy" onerror="this.remove()">` : '';
}
function apSaida(tipo) { return String(tipo || '').startsWith('saida'); }
const AP_TIPO = { student: 'Aluno', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador' };
function apTipo(t) { return AP_TIPO[String(t || '').toLowerCase()] || ''; }
// "ENTRADA - ESCOLA PRESIDENTE DUTRA" -> "ENTRADA": o site ja esta no filtro e
// o nome inteiro nao cabia na linha.
function apPorta(nome) {
  // So com um site escolhido: em "Todos os sites" duas portas virariam "SAIDA".
  const n = String(nome || '');
  const suf = _apSite ? ' - ' + _apSite : '';
  return suf && n.toUpperCase().endsWith(suf.toUpperCase()) && n.length > suf.length ? n.slice(0, -suf.length) : n;
}
function apPct(a, b) { return b ? Math.round(a * 100 / b) : 0; }

// O status gravado do leitor nao e confiavel (os dois da escola apareciam
// offline com 182 marcacoes no dia): a ultima marcacao conta junto.
function apPortaViva(p) {
  const u = apLocal(p.ultima);
  return String(p.status).toLowerCase() === 'online' || (u && Date.now() - u.getTime() < 30 * 60000);
}

function apKpi(icone, cor, rot, val, sub) {
  return `<article><div class="metric-icon ${cor}"><i data-lucide="${icone}"></i></div>
    <div><span>${esc(rot)}</span><strong>${esc(val)}</strong><small>${esc(sub)}</small></div></article>`;
}

// ---------------------------------------------------------------- ao vivo
function apRecibo(p) {
  const a = p.aviso || {};
  if (a.status === 'sem_pessoa') return '<div class="ap-recibo">Pessoa sem cadastro no SightOps: sem aviso.</div>';
  if (a.status === 'sem_aviso') return _apUsaAvisos ? '<div class="ap-recibo">Sem número de responsável cadastrado: sem aviso.</div>' : '';
  if (!a.status) return _apUsaAvisos ? `<div class="ap-recibo">Aviso ainda não registrado${a.para ? ' para ' + esc(a.para) : ''}.</div>` : '';
  const env = apUtc(a.enviado), at = apUtc(a.atualizado);
  const nivel = { enviado: 1, entregue: 2, lido: 3 }[a.status] || 0;
  const falhou = a.status === 'falha';
  const passo = (rot, n, hora, ruim) => `<div class="ap-passo ${ruim ? 'ruim' : (nivel >= n ? 'feito' : '')}">
      <i data-lucide="${ruim ? 'x' : 'check'}"></i><b>${rot}</b><span>${hora || ''}</span></div>`;
  const liga = n => `<div class="ap-liga ${nivel >= n ? 'feito' : ''}"></div>`;
  const passos = falhou
    ? passo('Enviado', 1, apHms(env)) + liga(9) + passo('Não entregue', 2, apHms(at), true) +
      `<div class="ap-recibo-erro">${esc(a.erro || 'a Meta recusou o envio')}</div>`
    : passo('Enviado', 1, apHms(env)) + liga(2) + passo('Entregue', 2, nivel === 2 ? apHms(at) : '') + liga(3) + passo('Lido', 3, nivel >= 3 ? apHms(at) : '');
  return `<div class="ap-recibo"><div>Aviso para <b>${esc(a.para || 'responsável')}</b> · WhatsApp</div><div class="ap-passos">${passos}</div></div>`;
}

function apZap(p) {
  const s = (p.aviso || {}).status;
  if (s === 'lido') return '<span class="ap-ok">lido</span>';
  if (s === 'entregue') return '<span>entregue</span>';
  if (s === 'enviado') return '<span>enviado</span>';
  if (s === 'falha') return '<span class="ap-ruim">aviso falhou</span>';
  if (s === 'sem_pessoa') return _apUsaAvisos ? '<span class="ap-ruim">sem aviso</span>' : '';
  return _apUsaAvisos ? '<span>sem aviso</span>' : '';
}

function apDesenharVivo(d) {
  const el = document.getElementById('apVivo');
  if (!el) return;
  _apUsaAvisos = Object.keys(d.avisos_hoje || {}).length > 0;
  const passagens = d.passagens || [];
  const ult = passagens[0];
  const r = d.resumo || {};
  const ah = d.avisos_hoje || {};
  const totAv = (ah.lido || 0) + (ah.entregue || 0) + (ah.enviado || 0) + (ah.falha || 0);
  const ag = d.avisos_agora || {};
  const semCad = r.without_person || 0, total = r.total || 0;
  // Pessoa fora do cadastro so e ALERTA quando e excecao. No condominio 92%
  // das passagens sao de moradores que so estao no leitor: la a faixa vermelha
  // ficava acesa o dia inteiro e virava ruido. Nesse caso vira uma nota.
  const semCadComum = total >= 20 && semCad / total >= 0.2;
  const avisos = [];
  if (ag.alerta) {
    avisos.push(`<div class="ap-alerta"><i data-lucide="alert-triangle"></i><div><b>Avisos de WhatsApp falhando agora:</b>
      ${ag.falhas} de ${ag.enviados} · ${esc(ag.erro_principal || 'sem motivo informado pela Meta')}</div></div>`);
  }
  if (ult && !ult.pessoa_id && !semCadComum && Date.now() - (apLocal(ult.hora) || 0) < 5 * 60000) {
    avisos.push(`<div class="ap-alerta"><i data-lucide="user-x"></i><div><b>Passagem de pessoa sem cadastro no SightOps</b>
      · ${esc(ult.porta)} · ${apHm(apLocal(ult.hora))}${ult.nome ? ' · o leitor informa "' + esc(ult.nome) + '"' : ''}</div></div>`);
  }
  if (semCadComum) {
    avisos.push(`<div class="ap-nota"><i data-lucide="info"></i><div><b>${apPct(semCad, total)}% das passagens de hoje são de pessoas que só estão no leitor</b>
      (${semCad} de ${total}). Elas ficam fora da presença, dos relatórios e dos avisos.
      <a href="#" data-ap-ir="geral">Ver por porta</a></div></div>`);
  }
  const turmas = (d.turmas || []).filter(t => t.total);
  const temTurmas = turmas.length > 1 || (turmas[0] && turmas[0].turma !== 'Sem turma');
  const novo = p => Date.now() - (apLocal(p.hora) || 0) < 60000;

  el.innerHTML = `
    <div class="metrics ap-kpis">
      ${apKpi('users', 'cyan', 'Presentes agora', r.inside_now ?? 0, 'última marcação foi entrada')}
      ${apKpi('log-in', 'green', 'Entradas hoje', r.entries ?? 0, 'marcações de entrada')}
      ${apKpi('log-out', 'amber', 'Saídas hoje', r.exits ?? 0, (r.manual_exits ? r.manual_exits + ' manuais' : 'inclui saída manual'))}
      ${apKpi('user-x', semCad ? (semCadComum ? 'amber' : 'red') : 'blue', 'Sem cadastro', semCad, 'pessoa só no leitor')}
      ${_apUsaAvisos ? apKpi('message-circle', ah.falha ? 'red' : 'green', 'Avisos lidos', totAv ? apPct(ah.lido || 0, totAv) + '%' : '—', `${ah.falha || 0} não entregues hoje`) : ''}
    </div>
    ${avisos.join('')}
    <div class="ap-grade">
      <section class="panel ap-agora" aria-label="Passagens de hoje">
        <div class="panel-header ap-cab"><div><h3>Agora</h3><p>${total} passagens hoje · mais recente primeiro</p></div></div>
        ${passagens.length ? `<div class="ap-lista">${passagens.slice(0, 30).map(p => `
          <div class="ap-item ${novo(p) ? 'novo' : ''} ${p.pessoa_id ? '' : 'semcad'}">
            <div class="ap-av">${apIniciais(p.nome)}${apFoto(p)}</div>
            <div class="ap-quem"><b>${esc(p.nome || 'sem nome no leitor')}</b>
              <small>${p.pessoa_id ? esc(p.turma || apTipo(p.tipo_pessoa)) : '<span class="ap-chip aviso">só no leitor</span>'}</small></div>
            <div class="ap-onde" title="${esc(p.porta)}">${esc(apPorta(p.porta))}</div>
            <span class="ap-chip ${apSaida(p.tipo) ? 'saida' : 'entrada'}">${apSaida(p.tipo) ? 'Saiu' : 'Entrou'}</span>
            <div class="ap-zap">${apZap(p)}</div>
            <div class="ap-hora monospace">${apHm(apLocal(p.hora))}</div>
          </div>`).join('')}</div>` : '<p class="ap-vazio">Nenhuma passagem hoje.</p>'}
      </section>

      <div class="ap-lado">
        ${ult ? `<section class="panel ap-ultima">
          <div class="panel-header ap-cab"><div><h3>Última passagem</h3><p>${apHa(apLocal(ult.hora))}</p></div></div>
          <div class="ap-ultima-corpo">
            <div class="ap-foto">${apIniciais(ult.nome)}${apFoto(ult)}<span class="ap-dir ${apSaida(ult.tipo) ? 'saida' : ''}">${apSaida(ult.tipo) ? 'SAIU' : 'ENTROU'}</span></div>
            <div class="ap-info"><b>${esc(ult.nome || 'Pessoa não identificada')}</b>
              <small>${esc([ult.turma || apTipo(ult.tipo_pessoa), ult.pessoa_id ? '' : 'só no leitor'].filter(Boolean).join(' · ')) || '&nbsp;'}</small>
              <small>${esc(apPorta(ult.porta))} · <span class="monospace">${apHms(apLocal(ult.hora))}</span></small></div>
          </div>
          ${apRecibo(ult)}
        </section>` : ''}
        <section class="panel ap-portas-painel">
          <div class="panel-header ap-cab"><div><h3>Portas</h3><p>${(d.portas || []).filter(apPortaViva).length} de ${(d.portas || []).length} com sinal</p></div></div>
          ${(d.portas || []).map(p => {
            const viva = apPortaViva(p);
            return `<div class="ap-porta-linha"><span class="ap-pt ${viva ? 'ok' : 'ruim'}"></span>
              <div class="ap-cresce"><b title="${esc(p.nome)}">${esc(apPorta(p.nome))}</b><small>${p.ultima ? 'última ' + apHm(apLocal(p.ultima)) : 'sem marcação hoje'}${viva ? '' : ' · sem sinal'}</small></div>
              <span class="ap-num monospace">${p.hoje}</span></div>`;
          }).join('') || '<p class="ap-vazio">Nenhum leitor.</p>'}
        </section>
        ${temTurmas ? `<section class="panel ap-turmas"><div class="panel-header ap-cab"><div><h3>Presença por turma</h3></div></div>
          <div class="ap-turmas-grade">${turmas.map(t => `<div class="ap-turma">
            <div><b>${esc(t.turma)}</b><span class="monospace">${t.presentes}/${t.total}</span></div>
            <div class="ap-trilho"><i style="width:${apPct(t.presentes, t.total)}%"></i></div></div>`).join('')}</div></section>` : ''}
      </div>
    </div>`;
  el.querySelectorAll('[data-ap-ir]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); apTrocarTela(a.dataset.apIr); }));
  lucide.createIcons();
}

// ---------------------------------------------------------------- visao geral
function apDesenharGeral(d) {
  const el = document.getElementById('apGeral');
  if (!el) return;
  const av = d.avisos || {}, s7 = av.sete_dias || {};
  const env = s7.enviados || 0, entregue = (s7.lidos || 0) + (s7.entregues || 0);
  const m7 = d.marcacoes_7d || {}, fotos = d.fotos || {}, leit = d.leitores || {};
  const semP = apPct(m7.sem_pessoa || 0, m7.total || 0);
  const serie = av.serie_30d || [];
  const usaAvisos = serie.some(x => x.lido + x.entregue + x.enviado + x.falha) || (av.incidentes || []).length > 0;
  const maxDia = Math.max(1, ...serie.map(x => x.lido + x.entregue + x.enviado + x.falha));
  const h = n => Math.round(n * 100 / maxDia) + '%';
  const dia = s => s ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : '';
  // So portas com volume que importa: 1 marcacao sem pessoa em 370 nao e problema.
  const portasSem = (m7.por_porta || []).filter(p => p.sem_pessoa >= 20 || apPct(p.sem_pessoa, p.total) >= 5);

  el.innerHTML = `
    <div class="metrics">
      ${usaAvisos ? apKpi('message-circle', apPct(entregue, env) >= 95 ? 'green' : 'red', 'Avisos entregues · 7 dias', env ? apPct(entregue, env) + '%' : '—', `${apPct(s7.lidos || 0, env)}% lidos pelos responsáveis`)
                  : apKpi('message-circle', 'blue', 'Avisos de WhatsApp', '—', 'não usado neste cliente')}
      ${apKpi('user-x', semP > 10 ? 'red' : 'green', 'Marcações sem pessoa · 7 dias', semP + '%', `${m7.sem_pessoa || 0} de ${m7.total || 0}`)}
      ${apKpi('scan-face', fotos.falhou ? 'amber' : 'green', 'Fotos recusadas pelo leitor', fotos.falhou || 0, 'pessoas que não abrem a porta')}
      ${apKpi('door-open', leit.online === leit.total ? 'green' : 'amber', 'Leitores com status online', `${leit.online || 0} / ${leit.total || 0}`, 'status informado pelo leitor')}
    </div>

    ${usaAvisos ? `<section class="panel ap-bloco">
      <div class="ap-bloco-cab"><div><h3>Avisos aos responsáveis · 30 dias</h3><p>O WhatsApp informa entrega e leitura de cada aviso.</p></div>
        <div class="ap-legenda"><span><i class="lido"></i>lido</span><span><i class="entregue"></i>entregue</span><span><i class="enviado"></i>sem confirmação</span><span><i class="falha"></i>não entregue</span></div></div>
      <div class="ap-grafico">${serie.map(x => `<div title="${dia(x.dia)}: ${x.lido} lidos, ${x.entregue} entregues, ${x.falha} não entregues">
        <i class="falha" style="height:${h(x.falha)}"></i><i class="enviado" style="height:${h(x.enviado)}"></i>
        <i class="entregue" style="height:${h(x.entregue)}"></i><i class="lido" style="height:${h(x.lido)}"></i></div>`).join('')}</div>
      <div class="ap-eixo monospace"><span>${dia(serie[0]?.dia)}</span><span>${dia(serie[15]?.dia)}</span><span>${dia(serie[29]?.dia)}</span></div>
      ${(av.incidentes || []).slice().reverse().slice(0, 3).map(i => `<div class="ap-alerta"><i data-lucide="alert-triangle"></i><div>
        <b>${dia(i.inicio)}${i.fim !== i.inicio ? ' a ' + dia(i.fim) : ''}: ${i.falhas.toLocaleString('pt-BR')} avisos não chegaram aos responsáveis.</b>
        ${i.erro ? ` Motivo informado pela Meta: "${esc(i.erro)}"${/payment/i.test(i.erro) ? ' (pendência de pagamento da conta do WhatsApp Business)' : ''}.` : ''}</div></div>`).join('')}
      <p class="ap-dica">Se mais de 10% dos avisos falharem em 30 minutos, o canal de WhatsApp fica fora no Monitoramento, com o motivo.</p>
    </section>` : ''}

    <div class="ap-duas">
      ${usaAvisos ? `<section class="panel ap-bloco"><h3>Responsáveis que não estão recebendo</h3><p>O último aviso para estes números falhou. Motivo dado pela Meta.</p>
        ${(av.falhando || []).map(f => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(f.responsavel || 'número sem cadastro')}</b>
            <small>${esc([f.pessoa, f.turma].filter(Boolean).join(' · '))}</small></div>
          <span class="monospace">${esc(f.numero)}</span><span class="ap-ruim">${esc(f.erro || 'falhou')}</span></div>`).join('') || '<p class="ap-vazio">Nenhum responsável com aviso falhando.</p>'}
        ${av.sem_numero_total ? `<p class="ap-dica">${av.sem_numero_total} aluno${av.sem_numero_total === 1 ? '' : 's'} sem número de responsável: não recebe${av.sem_numero_total === 1 ? '' : 'm'} aviso nenhum.</p>` : ''}
      </section>` : `<section class="panel ap-bloco"><h3>Avisos por WhatsApp</h3><p class="ap-vazio">Nenhum aviso enviado nos últimos 60 dias: este cliente não usa os avisos aos responsáveis.</p></section>`}
      <section class="panel ap-bloco"><h3>Marcações sem pessoa no SightOps</h3><p>A pessoa está no leitor, mas não no cadastro: fica fora de relatório, presença e aviso.</p>
        ${portasSem.map(p => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(p.porta)}</b>
            <small>${p.sem_pessoa} de ${p.total} marcações · ${p.nomes_distintos} nome${p.nomes_distintos === 1 ? '' : 's'} diferentes${p.exemplos.length ? ' · ex.: ' + p.exemplos.map(esc).join(', ') : ''}</small>
            <div class="ap-barra"><i style="width:${apPct(p.sem_pessoa, p.total)}%"></i></div></div>
          <b class="ap-ruim">${apPct(p.sem_pessoa, p.total)}%</b></div>`).join('') || '<p class="ap-vazio">Todas as marcações estão ligadas a uma pessoa.</p>'}
        ${portasSem.length ? '<p class="ap-dica">Para corrigir hoje: Controle de Acesso › Dispositivos › importar pessoas do leitor.</p>' : ''}
      </section>
    </div>
    <div class="ap-duas">
      <section class="panel ap-bloco"><h3>Fotos recusadas pelos leitores</h3><p>${fotos.ok || 0} fotos aceitas · ${fotos.falhou || 0} recusadas${fotos.pendente ? ' · ' + fotos.pendente + ' aguardando' : ''}</p>
        ${(fotos.recusadas || []).map(f => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(f.pessoa)}</b>
            <small>${esc([f.turma, f.leitor].filter(Boolean).join(' · '))}</small></div><span class="ap-ruim">${esc(f.erro || 'recusada')}</span></div>`).join('') || '<p class="ap-vazio">Nenhuma foto recusada.</p>'}
      </section>
      <section class="panel ap-bloco"><h3>Leitores</h3><p>Status informado pelo leitor e última vez que o SightOps falou com ele.</p>
        ${(leit.lista || []).map(l => {
          const on = String(l.status).toLowerCase() === 'online';
          return `<div class="ap-linha"><span class="ap-pt ${on ? 'ok' : 'ruim'}"></span><div class="ap-cresce"><b>${esc(l.nome)}</b>
            <small>${esc(l.site)} · visto ${apHa(apUtc(l.visto) || apLocal(l.visto))}</small></div><span class="${on ? 'ap-ok' : 'ap-ruim'}">${esc(l.status || 'sem status')}</span></div>`;
        }).join('') || '<p class="ap-vazio">Nenhum leitor cadastrado.</p>'}
      </section>
    </div>`;
  lucide.createIcons();
}

// ---------------------------------------------------------------- ciclo
async function apAtualizar() {
  if (_apCarregando) return;
  _apCarregando = true;
  try {
    const q = _apSite ? `?site=${encodeURIComponent(_apSite)}` : '';
    if (_apTela === 'vivo') apDesenharVivo(await apiJson(`/api/access-control/painel/ao-vivo${q}`) || {});
    else apDesenharGeral(await apiJson(`/api/access-control/painel/visao-geral${q}`) || {});
  } catch (err) {
    const alvo = document.getElementById(_apTela === 'vivo' ? 'apVivo' : 'apGeral');
    if (alvo && !alvo.innerHTML.trim()) alvo.innerHTML = `<p class="ap-vazio">Não consegui carregar: ${esc(err?.message || err)}</p>`;
  } finally {
    _apCarregando = false;
  }
}

function apLigarStream() {
  if (_apFonte) { _apFonte.close(); _apFonte = null; }
  if (_apTela !== 'vivo' || typeof EventSource === 'undefined') return;
  const q = _apSite ? `?site=${encodeURIComponent(_apSite)}` : '';
  _apFonte = new EventSource(`${API_BASE}/api/access-control/live/stream${q}`);
  _apFonte.addEventListener('access-event', () => apAtualizar());
}

function apTrocarTela(tela) {
  _apTela = tela === 'geral' ? 'geral' : 'vivo';
  document.querySelectorAll('[data-ap-tela]').forEach(b => {
    const on = b.dataset.apTela === _apTela;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  document.getElementById('apVivo').hidden = _apTela !== 'vivo';
  document.getElementById('apGeral').hidden = _apTela !== 'geral';
  try { sessionStorage.setItem('sightops.acesso.painel.tela', _apTela); } catch (_) {}
  apLigarStream();
  apAtualizar();
}

// Chamado ao sair da tela (navigateTo): fecha o stream e para os timers.
function stopAccessPainel() {
  if (_apFonte) { _apFonte.close(); _apFonte = null; }
  clearInterval(_apTimer); _apTimer = null;
  clearInterval(_apRelogio); _apRelogio = null;
}

async function loadAccessPainel() {
  const sel = document.getElementById('apSite');
  if (sel && !sel.dataset.ligado) {
    sel.dataset.ligado = '1';
    sel.addEventListener('change', () => { _apSite = sel.value; apLigarStream(); apAtualizar(); });
    document.querySelectorAll('[data-ap-tela]').forEach(b => b.addEventListener('click', () => apTrocarTela(b.dataset.apTela)));
    document.getElementById('btnApAtualizar')?.addEventListener('click', () => apAtualizar());
  }
  try {
    const g = await apiJson('/api/access-control/painel/visao-geral');
    const sites = [...new Set(((g?.leitores || {}).lista || []).map(l => l.site).filter(Boolean))].sort();
    if (sel) {
      sel.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
      if (sites.includes(_apSite)) sel.value = _apSite;
      else if (sites.length === 1) { _apSite = sites[0]; sel.value = _apSite; }
      else _apSite = '';
    }
  } catch (_) { /* a propria tela mostra o erro ao carregar */ }
  let salva = 'vivo';
  try { salva = sessionStorage.getItem('sightops.acesso.painel.tela') || 'vivo'; } catch (_) {}
  stopAccessPainel();
  apTrocarTela(salva);
  _apTimer = setInterval(() => { if (!document.hidden) apAtualizar(); }, 20000);
  _apRelogio = setInterval(() => {
    const r = document.getElementById('apRelogio');
    if (r) r.textContent = new Date().toLocaleTimeString('pt-BR');
  }, 1000);
}
