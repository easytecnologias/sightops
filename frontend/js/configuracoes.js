// Console de Configuracoes do cliente: visao geral com saude da configuracao,
// alarmes (falhas seguidas e sinal da ONU), canais de aviso, integracoes e
// registro de auditoria. Tudo do cliente atual; nada da plataforma aqui.
// Usa os cartoes .so-card e os helpers de licencas.js (soCard, licNum, licBar).

const AUDIT_ACOES = {
  'auth.login': 'Entrou no sistema',
  'auth.logout': 'Saiu do sistema',
  'auth.act_as': 'Entrou como cliente (suporte Easy)',
  'user.create': 'Criou usuário',
  'user.revoke_sessions': 'Encerrou as sessões de um usuário',
  'user.delete': 'Excluiu usuário',
  'user.reset_password': 'Redefiniu senha',
  'user.set_active': 'Ativou/desativou usuário',
  'user.update_profile': 'Alterou usuário',
  'tenant.create': 'Cliente criado',
  'access.profile_save': 'Salvou perfil de acesso',
  'access.profile_delete': 'Excluiu perfil de acesso',
  'access.user_set': 'Mudou o acesso de um usuário',
  'tenant.update': 'Alterou dados do cliente',
  'tenant.set_modules': 'Alterou módulos do cliente',
  'user.rename': 'Trocou o login de um usuário',
  'licensing.tenant_plan': 'Alterou o plano do cliente',
  'exclusao_autorizada': 'Autorizou uma exclusão (senha do administrador)',
};
const ALARME_TIPOS = {
  camera: 'Câmeras', nvr: 'Gravadores NVR', dvr: 'Gravadores DVR', onu: 'ONUs', olt: 'OLTs',
  switch: 'Switches', access_point: 'Access points', access_device: 'Controladoras de acesso',
  connector: 'Conectores', windows: 'Computadores', whatsapp: 'Canal WhatsApp', pdv: 'Caixas (PDV)',
};
const ALARME_ICONES = {
  camera: 'camera', nvr: 'hard-drive', dvr: 'hard-drive', onu: 'wifi', olt: 'radio-tower', switch: 'server',
  access_point: 'router', access_device: 'scan-face', connector: 'plug', windows: 'monitor', whatsapp: 'message-circle', pdv: 'scan-barcode',
};

let _cfgAudit = []; // ultimos eventos, para o cartao "mudancas recentes" da visao geral
let _cfgTelegram = null; // configuracao do Telegram como esta salva (nao como esta na tela)

function cfgQuando(iso) {
  return typeof formatDateTimeShort === 'function' ? formatDateTimeShort(iso || '') : String(iso || '');
}

function cfgMinutos(iso) {
  const t = Date.parse(String(iso || '').replace(' ', 'T'));
  if (!t) return '';
  const m = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (m < 1) return 'agora';
  if (m < 60) return `há ${m} min`;
  const h = Math.round(m / 60);
  return h < 48 ? `há ${h} h` : `há ${Math.round(h / 24)} dias`;
}

function cfgCheck(icone, cor, titulo, detalhe, botao) {
  return `<div class="so-check-item"><span class="so-card-logo ${cor}" style="width:34px;height:34px"><i data-lucide="${icone}"></i></span>
    <div><strong>${titulo}</strong><small>${detalhe}</small></div>${botao || ''}</div>`;
}

function cfgBotao(texto, alvo, primario) {
  return `<button class="${primario ? 'primary' : 'secondary'}-action" type="button" ${alvo}>${texto}</button>`;
}

function cfgAnel(pct) {
  const c = 2 * Math.PI * 50;
  const cor = pct >= 80 ? 'var(--primary)' : pct >= 50 ? 'var(--amber)' : 'var(--danger)';
  return `<svg class="so-ring" viewBox="0 0 120 120" role="img" aria-label="${pct} por cento configurado">
    <circle cx="60" cy="60" r="50" fill="none" stroke="var(--border)" stroke-width="11"/>
    <circle cx="60" cy="60" r="50" fill="none" stroke="${cor}" stroke-width="11" stroke-linecap="round" stroke-dasharray="${(c * pct / 100).toFixed(1)} 999" transform="rotate(-90 60 60)"/>
    <text x="60" y="64" text-anchor="middle" font-size="26" font-weight="800" fill="var(--text)">${pct}%</text>
    <text x="60" y="81" text-anchor="middle" font-size="10" fill="var(--muted)">configurado</text></svg>`;
}

// Estado real do envio ao Zabbix: exige o ultimo sync deste cliente com sucesso,
// recente e com dado enviado. Ter host (zabbix_hostid) nao basta: o campo nunca e
// limpo e continua preenchido com o sync parado.
function cfgZabbix(h) {
  const u = h?.zabbix_ultimo_sync || {};
  const ciclo = Number(h?.intervalo_verificacao_s || 120) * 1000;
  if (!u.em) return { st: 'espera', cor: 'gray', txt: 'Aguardando sincronização', det: 'O primeiro envio acontece em até alguns minutos depois que o sistema reinicia.' };
  const idade = Date.now() - Date.parse(u.em);
  if (!u.ok) return { st: 'falha', cor: 'red', txt: 'Sincronização falhou', det: u.erro || 'O último envio ao Zabbix deu erro.' };
  if (idade > 3 * ciclo + 60000) return { st: 'parado', cor: 'red', txt: 'Sincronização parada', det: `Último envio ${cfgMinutos(u.em)}.` };
  if ((h?.sem_zabbix || 0) > 0) return { st: 'sem_host', cor: 'red', txt: 'Equipamento sem host', det: `${licNum(h.sem_zabbix)} equipamento(s) sem host no Zabbix.` };
  if (!u.pushed && (h?.total || 0) > 0) return { st: 'sem_dado', cor: 'amber', txt: 'Nenhum valor enviado', det: 'O último ciclo achou os hosts mas não enviou nenhum valor.' };
  return { st: 'ok', cor: 'green', txt: 'Sincronizado', det: `Último envio ${cfgMinutos(u.em)}: ${licNum(u.pushed)} valores.` };
}

function cfgEhAdmin(u) {
  return ['owner', 'admin'].includes(String(u?.role || '').toLowerCase());
}

async function renderSettingsConsole(currentUser, userRows, telegram) {
  const admin = cfgEhAdmin(currentUser);
  const [health, plan, audit, profiles] = await Promise.all([
    apiJson('/api/monitoring/health', { forceRefresh: true }),
    admin ? apiJson('/api/auth/my-plan', { forceRefresh: true }) : null,
    admin ? apiJson('/api/auth/audit?limit=100', { forceRefresh: true }) : null,
    apiJson('/api/monitoring/profiles', { forceRefresh: true }),
  ]);
  _cfgAudit = audit?.events || [];
  _cfgTelegram = telegram || null;
  const navAudit = document.getElementById('settingsNavAudit');
  if (navAudit) navAudit.hidden = !admin;
  if (!admin && sessionStorage.getItem('sightops.settings.tab') === 'audit') sessionStorage.setItem('sightops.settings.tab', 'overview');

  renderSettingsOverview(currentUser, userRows, telegram, health, plan, admin);
  renderSettingsHealth(userRows, telegram, health, plan, admin);
  renderSettingsRecent(userRows, admin);
  renderAlarmProfiles(profiles?.profiles || [], health);
  if (admin && typeof ntCarregar === 'function') ntCarregar();
  else if (!admin) {
    const nt = document.getElementById('ntConteudo');
    if (nt) nt.innerHTML = '<div class="so-note"><i data-lucide="lock"></i><span>Só administradores configuram as notificações.</span></div>';
  }
  renderIntegrationCards(health, telegram);
  if (admin) renderSettingsAudit(userRows);
  const alarmW = document.getElementById('alarmWarnRx');
  const alarmC = document.getElementById('alarmCriticalRx');
  if (alarmW) alarmW.value = telegram?.warn_rx ?? -27;
  if (alarmC) alarmC.value = telegram?.critical_rx ?? -29;
  lucide.createIcons();
}

function renderSettingsOverview(currentUser, userRows, telegram, health, plan, admin) {
  const box = document.getElementById('settingsOverviewStatus');
  if (!box) return;
  const tg = telegram?.configured ? (telegram.enabled ? 'Telegram ativo' : 'Configurado, desligado') : 'Não configurado';
  const perfis = { owner: 'Dono da conta', admin: 'Administrador', operator: 'Operador', viewer: 'Visualizador' };
  const card = (rotulo, valor, extra = '') => `<div class="settings-status-card"><span>${esc(rotulo)}</span><strong title="${esc(String(valor).replace(/<[^>]+>/g, ''))}">${valor}</strong>${extra}</div>`;
  const limite = plan && plan.license_limit !== null && plan.license_limit !== undefined;
  const cards = [
    card('Cliente atual', esc(currentUser.tenant_name || currentUser.tenant_slug || '-'), `<small>${esc(currentUser.effective_tenant_slug || currentUser.tenant_slug || '')}</small>`),
    card('Seu perfil', esc(perfis[currentUser.role] || currentUser.role || '-'), `<small>${esc(currentUser.username || '')}</small>`),
    // Quem nao e admin nao lista a equipe: mostrar "0" seria falso.
    !admin ? card('Usuários da equipe', '—', '<small>visível para administradores</small>') : card('Usuários da equipe', `${licNum(userRows.length)}${plan?.user_limit !== null && plan?.user_limit !== undefined ? ` <em>/ ${licNum(plan.user_limit)}</em>` : ''}`,
      plan?.user_limit ? licBar(userRows.length, plan.user_limit) : `<small>${userRows.filter(u => !Number(u.active)).length} inativo(s)</small>`),
  ];
  if (plan) {
    cards.push(card('Equipamentos', `${licNum(plan.licenses_used)} <em>${limite ? `/ ${licNum(plan.license_limit)} licenças` : 'licenças'}</em>`,
      limite ? licBar(plan.licenses_used, plan.license_limit) : `<small>${esc(plan.plan?.name ? `plano ${plan.plan.name}, sem limite` : 'plano ainda não definido')}</small>`));
  }
  cards.push(card('Notificações', esc(tg), `<small>${telegram?.notify_recovery ? 'avisa também quando volta' : 'só avisa a queda'}</small>`));
  if (health) {
    cards.push(card('Monitorado agora', `${licNum(health.total)} <em>equipamentos</em>`,
      `<small>${health.fora ? `${licNum(health.fora)} fora do ar` : 'nenhum fora do ar'} · ${esc(cfgMinutos(health.ultima_verificacao) || 'sem verificação')}</small>`));
  }
  box.innerHTML = cards.join('');
}

function renderSettingsHealth(userRows, telegram, health, plan, admin) {
  const box = document.getElementById('settingsHealth');
  if (!box) return;
  const itens = [];
  const ok = [];
  const add = (passou, html) => { ok.push(passou); itens.push({ passou, html }); };
  const vaiPara = aba => `data-settings-goto="${aba}"`;

  const avisa = !!(telegram?.configured && telegram?.enabled);
  add(avisa, avisa
    ? cfgCheck('bell-ring', 'g', 'Avisos de queda ligados.', `Telegram ativo${telegram.notify_recovery ? ', avisando também quando volta' : ''}.`, '')
    : cfgCheck('bell-off', 'r', 'Ninguém recebe aviso quando um equipamento cai.', 'Nenhum canal de aviso está ligado.', cfgBotao('Configurar', vaiPara('notifications'), true)));

  if (health) {
    const zb = cfgZabbix(health);
    if (zb.st !== 'espera') {
      add(zb.st === 'ok', zb.st === 'ok'
        ? cfgCheck('check-circle-2', 'g', 'Dados chegando ao Zabbix.', `${licNum(health.total)} equipamentos com host. ${esc(zb.det)}`, '')
        : cfgCheck('alert-octagon', zb.cor === 'amber' ? 'a' : 'r', `Zabbix: ${esc(zb.txt.toLowerCase())}.`, esc(zb.det), cfgBotao('Ver integrações', vaiPara('integrations'))));
    }
    add(health.fora === 0, health.fora === 0
      ? cfgCheck('activity', 'g', 'Nenhum equipamento fora do ar agora.', `Última verificação ${esc(cfgMinutos(health.ultima_verificacao) || '—')}.`, '')
      : cfgCheck('activity', 'a', `${licNum(health.fora)} equipamento(s) fora do ar agora.`, `${health.instavel ? `${licNum(health.instavel)} instável(is) também. ` : ''}Última verificação ${esc(cfgMinutos(health.ultima_verificacao) || '—')}.`, cfgBotao('Ver monitoramento', 'data-cfg-nav="monitoring"')));
    const con = health.conectores || {};
    const conTotal = Object.values(con).reduce((a, b) => a + b, 0);
    if (conTotal) {
      const conFora = (con.down || 0) + (con.unstable || 0);
      add(conFora === 0, conFora === 0
        ? cfgCheck('plug', 'g', 'Conectores no ar.', `${licNum(conTotal)} de ${licNum(conTotal)} respondendo.`, '')
        : cfgCheck('plug', 'r', `${licNum(conFora)} conector(es) sem resposta.`, 'O que está atrás deles fica sem informação.', cfgBotao('Ver conectores', 'data-cfg-nav="connectors"')));
    }
  }

  if (plan) {
    const st = plan.status;
    const limite = plan.license_limit !== null && plan.license_limit !== undefined;
    if (st === 'sem_plano') {
      add(false, cfgCheck('package', 'a', 'Plano ainda não definido.', 'Fale com a Easy para definir o plano deste cliente.', cfgBotao('Ver uso', vaiPara('plan'))));
    } else {
      const bom = ['ok', 'sem_limite'].includes(st);
      add(bom, bom
        ? cfgCheck('package', 'g', `Dentro do plano ${esc(plan.plan?.name || '')}.`, limite ? `${licNum(plan.licenses_used)} de ${licNum(plan.license_limit)} licenças.` : 'Sem limite de equipamentos.', '')
        : cfgCheck('package', st === 'aviso' ? 'a' : 'r', st === 'aviso' ? 'Perto do limite do plano.' : 'Acima do limite do plano.',
          `${licNum(plan.licenses_used)} de ${licNum(plan.license_limit)} licenças.${plan.tolerance_until ? ` Ajuste até ${licDia(plan.tolerance_until)}.` : ''}`, cfgBotao('Ver plano', vaiPara('plan'))));
    }
  }

  const ativos = userRows.filter(u => Number(u.active));
  const donos = ativos.filter(u => ['owner', 'admin'].includes(String(u.role || '').toLowerCase()));
  if (admin) add(donos.length >= 2, donos.length >= 2
    ? cfgCheck('users', 'g', `${licNum(donos.length)} pessoas podem administrar.`, `${licNum(ativos.length)} usuário(s) ativo(s) na equipe.`, '')
    : cfgCheck('user-x', 'a', 'Só uma pessoa administra este cliente.', 'Se ela sair ou esquecer a senha, ninguém da equipe consegue gerenciar.', cfgBotao('Ver usuários', vaiPara('users'))));

  const pct = ok.length ? Math.round((ok.filter(Boolean).length * 100) / ok.length) : 0;
  const pend = ok.filter(x => !x).length;
  const badge = document.getElementById('settingsHealthBadge');
  if (badge) badge.innerHTML = pend ? `<span class="badge badge-amber">${pend} pendência${pend === 1 ? '' : 's'}</span>` : '<span class="badge badge-green">Tudo certo</span>';
  setText('settingsNavOverviewSub', pend ? `${pend} pendência${pend === 1 ? '' : 's'}` : 'Tudo certo');
  // pendencias primeiro
  itens.sort((a, b) => Number(a.passou) - Number(b.passou));
  box.innerHTML = `${cfgAnel(pct)}<div class="so-check">${itens.map(i => i.html).join('')}</div>`;
}

function renderSettingsRecent(userRows, admin) {
  const panel = document.getElementById('settingsRecentPanel');
  const box = document.getElementById('settingsRecent');
  if (!box) return;
  if (panel) panel.hidden = !admin;
  const nomes = Object.fromEntries(userRows.map(u => [Number(u.id), u.username]));
  const mudancas = _cfgAudit.filter(e => !['auth.login', 'auth.logout', 'acao.negada'].includes(e.action)).slice(0, 5);
  box.innerHTML = mudancas.length ? mudancas.map(e => {
    const quem = nomes[Number(e.user_id)] || 'Easy (suporte)';
    return `<div><span class="avatar">${esc(String(quem).slice(0, 1).toUpperCase())}</span>
      <span><strong>${esc(quem)}</strong> · ${esc(histOque(e, histDetalhe(e)))}${e.resource_id ? ` <span class="text-muted">${esc(e.resource_id)}</span>` : ''}</span>
      <time>${esc(cfgMinutos(e.created_at))}</time></div>`;
  }).join('') : '<p class="text-muted" style="margin:8px 0">Nenhuma mudança registrada ainda.</p>';
}

function renderAlarmProfiles(profiles, health) {
  const box = document.getElementById('alarmProfileCards');
  if (!box) return;
  const ordem = Object.keys(ALARME_TIPOS);
  const lista = profiles.filter(p => ALARME_TIPOS[p.entity_type])
    .sort((a, b) => ordem.indexOf(a.entity_type) - ordem.indexOf(b.entity_type));
  // O ritmo vem do laco de monitoramento (igual para todos os tipos), nao do perfil.
  const min = Math.max(1, Math.round(Number(health?.intervalo_verificacao_s || 120) / 60));
  setText('alarmIntervalNote', `O sistema verifica todos os equipamentos a cada ${licNum(min)} min.`);
  const minGrav = Math.max(1, Math.round(Number(health?.intervalo_gravador_s || 2400) / 60));
  const tempo = (tipo, n) => (['nvr', 'dvr'].includes(tipo)
    ? `até ≈ ${licNum(minGrav + n * min)} min`
    : `≈ ${licNum(n * min)} min`);
  box.innerHTML = lista.map(p => {
    const n = Number(p.failure_threshold || 2);
    return soCard({
      logo: `<i data-lucide="${ALARME_ICONES[p.entity_type] || 'activity'}"></i>`,
      cor: 'g',
      title: ALARME_TIPOS[p.entity_type],
      rows: [
        ['Falhas seguidas', `<span class="so-unit" style="justify-content:flex-end"><input type="number" min="1" max="10" data-alarm-profile="${esc(p.profile_key)}" data-alarm-orig="${n}" value="${n}" aria-label="Falhas seguidas para ${esc(ALARME_TIPOS[p.entity_type])}"></span>`],
        ['Fora do ar após', tempo(p.entity_type, n)],
      ],
      foot: ['nvr', 'dvr'].includes(p.entity_type) ? `<small class="text-muted">O gravador é medido a cada ${licNum(minGrav)} min; as falhas contam releituras dessa medição.</small>` : '',
    });
  }).join('') || '<p class="text-muted">Nenhum perfil de monitoramento.</p>';
  box.querySelectorAll('[data-alarm-profile]').forEach(inp => inp.addEventListener('input', () => {
    const dd = inp.closest('dl')?.querySelectorAll('dd')[1];
    const p = lista.find(x => x.profile_key === inp.dataset.alarmProfile);
    if (dd && p) dd.textContent = tempo(p.entity_type, Math.max(1, Number(inp.value) || 1));
  }));
}

async function saveAlarmProfiles() {
  const mudados = [...document.querySelectorAll('[data-alarm-profile]')].filter(i => i.value !== i.dataset.alarmOrig);
  if (!mudados.length) { showToast('Nada mudou nos alarmes.'); return; }
  try {
    for (const inp of mudados) {
      const res = await api(`/api/monitoring/profiles/${encodeURIComponent(inp.dataset.alarmProfile)}`, {
        method: 'PUT', body: JSON.stringify({ failure_threshold: Number(inp.value) }),
      });
      await jsonOrReadableError(res, 'Não foi possível salvar o alarme.');
      inp.dataset.alarmOrig = inp.value;
    }
    showToast(`${mudados.length} alarme${mudados.length === 1 ? '' : 's'} salvo${mudados.length === 1 ? '' : 's'}. Vale a partir da próxima verificação.`);
  } catch (e) { showToast(e?.message || 'Não foi possível salvar o alarme.', true); }
}

async function saveOnuThresholds() {
  const warn = Number(document.getElementById('alarmWarnRx')?.value);
  const crit = Number(document.getElementById('alarmCriticalRx')?.value);
  if (!Number.isFinite(warn) || !Number.isFinite(crit)) { showToast('Informe os dois limites em dBm.', true); return; }
  if (crit >= warn) { showToast('O crítico precisa ser menor (mais negativo) que o alerta.', true); return; }
  const t = _cfgTelegram || {};
  try {
    const res = await api('/api/monitoring/notificacoes/sinal', { method: 'PUT', body: JSON.stringify({ warn_rx: warn, critical_rx: crit }) });
    await jsonOrReadableError(res, 'Não foi possível salvar os limites.');
    _cfgTelegram = { ...t, warn_rx: warn, critical_rx: crit };
    showToast('Limites de sinal da ONU salvos.');
  } catch (e) { showToast(e?.message || 'Não foi possível salvar os limites.', true); }
}

function renderIntegrationCards(health, telegram) {
  const box = document.getElementById('integrationCards');
  if (!box) return;
  const h = health || {};
  const con = h.conectores || {};
  const conTotal = Object.values(con).reduce((a, b) => a + b, 0);
  const conUp = con.up || 0;
  const zb = cfgZabbix(h);
  const zu = h.zabbix_ultimo_sync || {};
  const wa = h.whatsapp || {};
  const waTotal = Object.values(wa).reduce((a, b) => a + b, 0);
  box.innerHTML = [
    soCard({
      logo: 'Zb', cor: 'r', title: 'Zabbix',
      badge: `<span class="badge badge-${zb.cor} so-dot">${esc(zb.txt)}</span>`,
      actions: '<span class="so-tag">gerenciado pela Easy</span>',
      rows: [
        ['Equipamentos com host', `${licNum((h.total || 0) - (h.sem_zabbix || 0))} / ${licNum(h.total || 0)}`],
        ['Último envio', esc(zu.em ? cfgMinutos(zu.em) : '—')],
        ['Valores no último envio', zu.em ? licNum(zu.pushed || 0) : '—'],
        ['Fora do ar (SightOps)', licNum(h.fora || 0)],
      ],
    }),
    soCard({
      logo: '<i data-lucide="plug"></i>', cor: 'c', title: 'Conectores',
      badge: !conTotal ? '<span class="badge badge-gray so-dot">Nenhum</span>' : conUp === conTotal ? '<span class="badge badge-green so-dot">Todos no ar</span>' : `<span class="badge badge-red so-dot">${licNum(conTotal - conUp)} sem resposta</span>`,
      actions: '<button class="secondary-action" type="button" data-cfg-nav="connectors">Abrir</button>',
      rows: [
        ['No ar', `${licNum(conUp)} / ${licNum(conTotal)}`],
        ['Instáveis', licNum(con.unstable || 0)],
        ['Fora do ar', licNum(con.down || 0)],
        ['Sem informação', licNum(con.unknown || 0)],
      ],
    }),
    soCard({
      logo: '<i data-lucide="message-circle"></i>', cor: 'g', title: 'WhatsApp (Evolution)',
      badge: waTotal ? ((wa.up || 0) === waTotal ? '<span class="badge badge-green so-dot">Conectado</span>' : '<span class="badge badge-red so-dot">Com problema</span>') : '<span class="badge badge-gray so-dot">Não usado</span>',
      actions: '<span class="so-tag">gerenciado pela Easy</span>',
      rows: [['Canais', waTotal ? licNum(waTotal) : '—'], ['Conectados', licNum(wa.up || 0)]],
    }),
    soCard({
      logo: '<i data-lucide="send"></i>', cor: 'b', title: 'Telegram',
      badge: telegram?.configured ? (telegram.enabled ? '<span class="badge badge-green so-dot">Ativo</span>' : '<span class="badge badge-amber so-dot">Desligado</span>') : '<span class="badge badge-gray so-dot">Não configurado</span>',
      actions: `<button class="secondary-action" type="button" data-settings-goto="notifications">${telegram?.configured ? 'Editar' : 'Ligar'}</button>`,
      rows: [['Grupo / chat', esc(telegram?.chat_id || '—')], ['Avisa quando volta', telegram?.notify_recovery ? 'sim' : 'não']],
    }),
  ].join('');
}

// --------------------------------------------------------------- Historico
// Tudo que a equipe mudou (rota /api/auth/historico): logins, usuarios e cada
// acao nos equipamentos, com filtro e "carregar mais" (pagina por id).
const _hist = { linhas: [], proximo: null, nomes: {}, carregando: false, pedido: 0, filtros: {} };

function histFiltros() {
  const v = id => document.getElementById(id)?.value || '';
  return { usuario: v('histUsuario'), tipo: v('histTipo'), de: v('histDe'), ate: v('histAte'), q: v('histBusca').trim() };
}

function histDetalhe(e) {
  try { return e.detail_json ? JSON.parse(e.detail_json) : {}; } catch { return {}; }
}

function histQuem(e) {
  return e.username || _hist.nomes[Number(e.user_id)] || 'Easy (suporte)';
}

function histOque(e, d) {
  const acao = String(e.action || '');
  return acao.startsWith('acao') ? (d.r || acao) : (AUDIT_ACOES[acao] || acao);
}

function histLinha(e) {
  const d = histDetalhe(e);
  const acao = String(e.action || '');
  const ehAcao = acao.startsWith('acao');
  const oque = histOque(e, d);
  let alvo = e.resource_id || '';
  if (acao.startsWith('auth.log')) alvo = '';
  if (acao === 'exclusao_autorizada') alvo = `${d.operador || ''} → ${d.caminho || alvo}`;
  let res = '<span class="so-hist-res ok">ok</span>';
  if (acao === 'acao.negada') res = '<span class="so-hist-res negada">barrada</span>';
  else if (ehAcao && d.ok === false) res = `<span class="so-hist-res falha" title="código ${esc(String(d.s || ''))}">falhou</span>`;
  const extra = [d.autorizado_por ? `autorizado por ${d.autorizado_por}` : '', d.suporte ? 'suporte Easy' : '', d.ip ? `IP ${d.ip}` : '']
    .filter(Boolean).join(' · ');
  return `<tr>
    <td class="settings-cell-date"><span class="text-muted">${esc(cfgQuando(e.created_at))}</span></td>
    <td class="settings-cell-truncate" title="${esc(e.full_name || histQuem(e))}">${esc(histQuem(e))}</td>
    <td class="settings-cell-truncate ${acao === 'acao.exclusao' ? 'so-hist-exc' : ''}" title="${esc(oque)}">${esc(oque)}</td>
    <td class="settings-cell-truncate" title="${esc(alvo)}">${esc(alvo)}${extra ? `<span class="so-hist-aut">${esc(extra)}</span>` : ''}</td>
    <td>${res}</td></tr>`;
}

async function histCarregar(continuar = false) {
  const body = document.getElementById('settingsAuditBody');
  const mais = document.getElementById('histMais');
  if (!body) return;
  if (continuar && _hist.carregando) return;
  // Filtro novo enquanto o anterior carrega: vale so a resposta do ultimo pedido.
  const pedido = ++_hist.pedido;
  _hist.carregando = true;
  try {
    // "Carregar mais" continua com os filtros da lista que esta na tela.
    const f = continuar ? _hist.filtros : histFiltros();
    if (!continuar) _hist.filtros = f;
    const qs = new URLSearchParams({ limite: '100' });
    Object.entries(f).forEach(([k, v]) => { if (v) qs.set(k, v); });
    if (continuar && _hist.proximo) qs.set('antes', String(_hist.proximo));
    if (!continuar) body.innerHTML = '<tr class="empty-row"><td colspan="5">Carregando…</td></tr>';
    const res = await api(`/api/auth/historico?${qs}`);
    const data = await res?.json().catch(() => ({}));
    if (pedido !== _hist.pedido) return;
    if (!res?.ok) throw new Error(data?.detail || 'falha ao consultar');
    const novos = data?.eventos || [];
    _hist.linhas = continuar ? _hist.linhas.concat(novos) : novos;
    _hist.proximo = data?.mais ? data.proximo : null;
    body.innerHTML = _hist.linhas.length ? _hist.linhas.map(histLinha).join('')
      : '<tr class="empty-row"><td colspan="5">Nada encontrado com esses filtros.</td></tr>';
    if (mais) mais.hidden = !_hist.proximo;
    const filtrado = Object.values(f).some(Boolean);
    const n = _hist.linhas.length;
    setText('settingsAuditSummary', `${n}${_hist.proximo ? '+' : ''} registro${n === 1 ? '' : 's'}${filtrado ? ' com esses filtros' : ''}. Tudo que a equipe mudou no sistema: quem, quando, o quê e se deu certo.`);
  } catch (err) {
    if (pedido === _hist.pedido) body.innerHTML = `<tr class="empty-row"><td colspan="5">Não foi possível carregar o histórico: ${esc(err?.message || err)}</td></tr>`;
  } finally {
    if (pedido === _hist.pedido) _hist.carregando = false;
  }
}

function histCsv() {
  // Texto digitado por operador (nome de camera) que comeca com = + - @ vira
  // formula no Excel: o apostrofo o mantem como texto.
  const cel = v => {
    let t = String(v ?? '');
    if (/^[=+\-@\t\r]/.test(t)) t = `'${t}`;
    return `"${t.replace(/"/g, '""')}"`;
  };
  const linhas = [['Quando', 'Quem', 'O quê', 'Em quê', 'Resultado', 'Autorizado por', 'IP'].map(cel).join(';')];
  _hist.linhas.forEach(e => {
    const d = histDetalhe(e);
    const acao = String(e.action || '');
    const res = acao === 'acao.negada' ? 'barrada' : (d.ok === false ? 'falhou' : 'ok');
    linhas.push([cfgQuando(e.created_at), histQuem(e), histOque(e, d), e.resource_id || '', res,
      d.autorizado_por || '', d.ip || ''].map(cel).join(';'));
  });
  const blob = new Blob(['﻿' + linhas.join('\r\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `historico-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function renderSettingsAudit(userRows) {
  _hist.nomes = Object.fromEntries((userRows || []).map(u => [Number(u.id), u.username]));
  const sel = document.getElementById('histUsuario');
  if (sel) {
    const atual = sel.value;
    sel.innerHTML = '<option value="">Todos</option>' + (userRows || [])
      .slice().sort((a, b) => String(a.username).localeCompare(String(b.username)))
      .map(u => `<option value="${Number(u.id)}">${esc(u.full_name ? `${u.full_name} (${u.username})` : u.username)}</option>`).join('');
    sel.value = atual;
  }
  histCarregar(false);
}

let _histTimer = null;
(function bindHistorico() {
  const form = document.getElementById('histFiltros');
  if (!form) return;
  form.addEventListener('submit', ev => { ev.preventDefault(); histCarregar(false); });
  form.addEventListener('change', ev => { if (ev.target.id !== 'histBusca') histCarregar(false); });
  document.getElementById('histBusca')?.addEventListener('input', () => {
    clearTimeout(_histTimer);
    _histTimer = setTimeout(() => histCarregar(false), 400);
  });
  document.getElementById('histMais')?.addEventListener('click', () => histCarregar(true));
  document.getElementById('histExportar')?.addEventListener('click', histCsv);
})();

(function bindConfiguracoes() {
  document.getElementById('btnSaveAlarmProfiles')?.addEventListener('click', saveAlarmProfiles);
  document.getElementById('btnSaveOnuThresholds')?.addEventListener('click', saveOnuThresholds);
  document.getElementById('viewSettings')?.addEventListener('click', ev => {
    const ir = ev.target.closest('[data-settings-goto]');
    if (ir) { activateSettingsTab(ir.dataset.settingsGoto); return; }
    const nav = ev.target.closest('[data-cfg-nav]');
    if (nav) { navigateTo(nav.dataset.cfgNav); return; }
    const sc = ev.target.closest('[data-cfg-scroll]');
    if (sc) {
      const alvo = document.getElementById(sc.dataset.cfgScroll);
      alvo?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      alvo?.focus();
    }
  });
})();
