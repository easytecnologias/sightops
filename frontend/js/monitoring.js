let _monitoringEntities = [];

const MONITORING_LABELS = {
  connector: 'Conectores', olt: 'OLTs', onu: 'ONUs/ONTs', camera: 'Cameras',
  nvr: 'NVRs', dvr: 'DVRs', windows: 'Computadores',
  access_device: 'Controladoras de Acesso', whatsapp: 'WhatsApp',
  access_point: 'Access Points', pdv: 'Caixas (PDV)',
};

function monitoringStatusLabel(status) {
  return ({ up: 'Up', down: 'Down', unstable: 'Instavel', unknown: 'Nao verificado', maintenance: 'Manutencao' })[status] || status;
}

// Onde a camera esta (ou estava) na OLT. Camera caida some da coleta da OLT e
// perde a ONU; a ultima conhecida vem em detail.onu_ultima e e o que diz ao
// tecnico onde procurar.
function monitoringOnuTexto(detail) {
  const fmt = o => [o.olt_name || o.olt_ip, o.pon && `PON ${o.pon}`, o.onu_id && `ONU ${o.onu_id}`,
    o.onu_name, !o.onu_id && o.onu_serial && `serial ${o.onu_serial}`].filter(Boolean).join(' · ');
  if (detail?.onu) return fmt(detail.onu);
  const u = detail?.onu_ultima;
  if (!u) return '';
  // So visto_em: sumiu_em e a hora em que o sistema notou, e na leitura vira "agora".
  const quando = u.visto_em;
  return `Última ONU: ${fmt(u)}${quando ? ` (até ${monitoringDate(quando)})` : ''}`;
}

// Linha de baixo de cada membro de ocorrencia: onde o equipamento esta na
// fibra. Camera caida mostra a ultima ONU conhecida -- e por ela que o tecnico
// acha a camera em campo.
function monitoringMembroOnu(row) {
  let detail = {};
  try { detail = JSON.parse(row.detail_json || '{}'); } catch (_) { return ''; }
  if (row.entity_type === 'camera') return monitoringOnuTexto(detail);
  if (row.entity_type === 'onu') return [detail.pon && `PON ${detail.pon}`, detail.serial && `serial ${detail.serial}`].filter(Boolean).join(' · ');
  return '';
}

function monitoringDetail(row) {
  try {
    const detail = JSON.parse(row.detail_json || '{}');
    if (row.entity_type === 'onu') {
      // Mostra so o que a OLT entrega de verdade. Antes vinha "OLT RX --" fixo
      // em toda ONU EPON (4840E/VSOL), que nao tem RX por ONU -- parecia dado
      // faltando quando na verdade aquele modelo nunca teve essa medida.
      const partes = [];
      if (detail.onu_rx) partes.push(`ONU ${detail.onu_rx} dBm`);
      if (detail.olt_rx) partes.push(`OLT ${detail.olt_rx} dBm`);
      if (detail.onu_tx) partes.push(`TX ${detail.onu_tx} dBm`);
      if (detail.temperatura) partes.push(`${detail.temperatura} C`);
      if (detail.distance_km) partes.push(`${detail.distance_km} km`);
      if (detail.omci_status) partes.push(`OMCI ${detail.omci_status}`);
      if (detail.offline_reason) partes.push(detail.offline_reason);
      return partes.join(' · ') || 'sem telemetria';
    }
    if (row.entity_type === 'camera') return [detail.ip, monitoringOnuTexto(detail)].filter(Boolean).join(' · ');
    return detail.host || detail.ip || detail.model || detail.serial || '';
  } catch (_) { return ''; }
}

function monitoringDate(value) {
  if (!value) return '--';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('pt-BR');
}

function monitoringDrawerMeta(row) {
  let detail = {};
  try { detail = JSON.parse(row.detail_json || '{}'); } catch (_) {}
  const parts = [];
  if (row.site) parts.push(row.site);
  if (row.entity_type === 'onu') {
    if (detail.pon) parts.push(`PON ${detail.pon}`);
    if (detail.serial) parts.push(`Serial ${detail.serial}`);
    const signal = monitoringDetail(row);
    if (signal) parts.push(signal);
  } else {
    const address = detail.host || detail.ip || detail.last_seen || '';
    const model = detail.model || '';
    if (address) parts.push(address);
    if (model) parts.push(model);
    if (row.entity_type === 'camera') parts.push(monitoringOnuTexto(detail));
    if (detail.motivo) parts.push(detail.motivo);
  }
  return parts.filter(Boolean).join(' · ');
}

function monitoringFocusRow(row) {
  const type = document.getElementById('monitoringType');
  const status = document.getElementById('monitoringStatus');
  const site = document.getElementById('monitoringSite');
  const search = document.getElementById('monitoringSearch');
  if (type) type.value = row.entity_type || '';
  if (status) status.value = '';
  if (site) site.value = row.site || '';
  if (search) search.value = row.display_name || row.entity_id || '';
  // A aba de problemas esconderia um equipamento saudavel aberto pela gaveta.
  monitoringSetTab('all');
  renderMonitoringRows();
  document.getElementById('monitoringTablePanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  closeDashDrawer();
}

async function openMonitoringDrawer(entityType, activeStatus = 'all', activeSite = null, refreshData = true) {
  const label = MONITORING_LABELS[entityType] || entityType;
  _openDashDrawer('Monitoramento', label);
  if (refreshData || !_monitoringEntities.length) {
    _drawerRenderRows('<div class="drawer-empty-state">Carregando equipamentos...</div>');
    try {
      const response = await apiJson('/api/monitoring/entities?limit=2000', { forceRefresh: true });
      _monitoringEntities = response?.entities || [];
    } catch (error) {
      _drawerRenderRows(`<div class="drawer-empty-state">Nao foi possivel carregar os equipamentos: ${esc(error.message || error)}</div>`);
      return;
    }
  }
  const typeRows = _monitoringEntities.filter(row => row.entity_type === entityType);
  const sites = [...new Set(typeRows.map(row => String(row.site || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  if (activeSite && !sites.includes(activeSite)) activeSite = null;
  const isAttention = row => ['down', 'unstable', 'unknown'].includes(row.status);
  const siteRows = activeSite ? typeRows.filter(row => row.site === activeSite) : typeRows;
  const counts = {
    all: siteRows.length,
    up: siteRows.filter(row => row.status === 'up').length,
    down: siteRows.filter(row => row.status === 'down').length,
    attention: siteRows.filter(isAttention).length,
    maintenance: siteRows.filter(row => row.status === 'maintenance').length,
  };

  _drawerFilterBar([
    { key: 'all', label: 'Todos', count: counts.all },
    { key: 'up', label: 'Up', count: counts.up },
    { key: 'down', label: 'Down', count: counts.down },
    { key: 'attention', label: 'Atencao', count: counts.attention },
    ...(counts.maintenance ? [{ key: 'maintenance', label: 'Manutencao', count: counts.maintenance }] : []),
  ], activeStatus, sites, activeSite,
  status => openMonitoringDrawer(entityType, status, activeSite, false),
  site => openMonitoringDrawer(entityType, activeStatus, site, false));

  let rows = siteRows;
  if (activeStatus === 'attention') rows = rows.filter(isAttention);
  else if (activeStatus !== 'all') rows = rows.filter(row => row.status === activeStatus);
  rows = rows.slice().sort((a, b) => {
    const order = { down: 0, unstable: 1, unknown: 2, maintenance: 3, up: 4 };
    const statusDiff = (order[a.status] ?? 5) - (order[b.status] ?? 5);
    return statusDiff || String(a.display_name || '').localeCompare(String(b.display_name || ''), 'pt-BR', { numeric: true });
  });

  _drawerRenderRows(rows.map((row, index) => `
    <button class="drawer-item monitoring-drawer-item" type="button" data-monitoring-drawer-index="${index}">
      ${_drawerStatusDot(row.status)}
      <span class="drawer-item-main">
        <span class="drawer-item-title">${esc(row.display_name || row.entity_key)}</span>
        <span class="drawer-item-sub" title="${esc(monitoringDrawerMeta(row))}">${esc(monitoringDrawerMeta(row) || 'Sem detalhes adicionais')}</span>
      </span>
      <span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span>
      <i data-lucide="chevron-right"></i>
    </button>
  `).join(''));
  document.querySelectorAll('[data-monitoring-drawer-index]').forEach(button => {
    button.addEventListener('click', () => monitoringFocusRow(rows[Number(button.dataset.monitoringDrawerIndex)]));
  });
}

// A entity_key de uma ONU carrega tudo que a tela de implantacao precisa:
// "onu:<connector_id>|<olt_ip>|<pon>|<onu>". Sem isso o tecnico via "gpon 1 onu
// 11 / fora do ar" e tinha que reescolher conector, OLT, PON e posicao a mao
// para consultar ou excluir (30/09/2026).
function monitoringOnuAlvo(row) {
  if (!row || row.entity_type !== 'onu') return null;
  const partes = String(row.entity_key || '').replace(/^onu:/, '').split('|');
  if (partes.length < 4) return null;
  const [connectorId, oltIp, pon, onu] = partes.map(x => String(x || '').trim());
  if (!oltIp || !pon || !onu) return null;
  return { connectorId, oltIp, pon, onu };
}

async function openMonitoringAttentionDrawer(activeType = 'all', activeSite = null, refreshData = true) {
  _openDashDrawer('Atencao operacional', 'Equipamentos que precisam de cuidado');
  // Abrir este painel e um ato deliberado para ver o estado de AGORA.
  // Antes so buscava com o cache vazio, entao equipamento excluido
  // continuava na lista ate alguem dar F5 -- e o operador concluia que
  // a exclusao nao tinha funcionado.
  if (refreshData || !_monitoringEntities.length) {
    _drawerRenderRows('<div class="drawer-empty-state">Carregando equipamentos...</div>');
    try {
      const response = await apiJson('/api/monitoring/entities?limit=2000', { forceRefresh: true });
      _monitoringEntities = response?.entities || [];
    } catch (error) {
      _drawerRenderRows(`<div class="drawer-empty-state">Nao foi possivel carregar os equipamentos: ${esc(error.message || error)}</div>`);
      return;
    }
  }

  const attentionRows = _monitoringEntities.filter(row => ['down', 'unstable', 'unknown'].includes(row.status));
  const availableTypes = Object.keys(MONITORING_LABELS).filter(type => attentionRows.some(row => row.entity_type === type));
  const scopedByType = activeType === 'all' ? attentionRows : attentionRows.filter(row => row.entity_type === activeType);
  const sites = [...new Set(scopedByType.map(row => String(row.site || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  if (activeSite && !sites.includes(activeSite)) activeSite = null;
  const siteScopedRows = activeSite ? attentionRows.filter(row => row.site === activeSite) : attentionRows;
  const typeCounts = siteScopedRows.reduce((counts, row) => {
    counts[row.entity_type] = (counts[row.entity_type] || 0) + 1;
    return counts;
  }, {});
  const visibleRows = activeType === 'all' ? siteScopedRows : siteScopedRows.filter(row => row.entity_type === activeType);

  const filters = document.getElementById('dashDrawerFilters');
  filters.innerHTML = `
    <div class="monitoring-attention-summary">
      <strong>${visibleRows.length}</strong><span>equipamento${visibleRows.length === 1 ? '' : 's'} exigem verificacao</span>
    </div>
    <div class="drawer-filter-row">
      <button class="drawer-filter-btn${activeType === 'all' ? ' active' : ''}" data-attention-type="all">Todos (${siteScopedRows.length})</button>
      ${availableTypes.map(type => `<button class="drawer-filter-btn${activeType === type ? ' active' : ''}" data-attention-type="${esc(type)}">${esc(MONITORING_LABELS[type])} (${typeCounts[type] || 0})</button>`).join('')}
    </div>
    ${sites.length ? `<div class="drawer-site-filter">
      <label for="attentionDrawerSiteSelect"><i data-lucide="map-pin"></i><span>Site</span></label>
      <select id="attentionDrawerSiteSelect" class="drawer-site-select">
        <option value="">Todos os sites</option>
        ${sites.map(site => `<option value="${esc(site)}"${activeSite === site ? ' selected' : ''}>${esc(site)}</option>`).join('')}
      </select>
    </div>` : ''}`;
  filters.querySelectorAll('[data-attention-type]').forEach(button => {
    button.addEventListener('click', () => openMonitoringAttentionDrawer(button.dataset.attentionType || 'all', activeSite));
  });
  filters.querySelector('#attentionDrawerSiteSelect')?.addEventListener('change', event => {
    openMonitoringAttentionDrawer(activeType, event.target.value || null);
  });

  let rows = visibleRows;
  rows = rows.slice().sort((a, b) => {
    const order = { down: 0, unstable: 1, unknown: 2 };
    const statusDiff = (order[a.status] ?? 3) - (order[b.status] ?? 3);
    const typeDiff = String(a.entity_type).localeCompare(String(b.entity_type), 'pt-BR');
    return statusDiff || typeDiff || String(a.display_name || '').localeCompare(String(b.display_name || ''), 'pt-BR', { numeric: true });
  });
  _drawerRenderRows(rows.map(row => {
    const alvo = monitoringOnuAlvo(row);
    const dados = alvo
      ? ` data-onu-connector="${esc(alvo.connectorId)}" data-onu-olt="${esc(alvo.oltIp)}" data-onu-pon="${esc(alvo.pon)}" data-onu-num="${esc(alvo.onu)}"`
      : '';
    return `
    <div class="drawer-item monitoring-attention-item${alvo ? ' monitoring-attention-acionavel' : ''}"${dados}>
      ${_drawerStatusDot(row.status)}
      <div class="drawer-item-main">
        <div class="drawer-item-title">${esc(row.display_name || row.entity_key)}</div>
        <div class="drawer-item-sub" title="${esc(monitoringDrawerMeta(row))}">${esc(monitoringDrawerMeta(row) || 'Sem detalhes adicionais')}</div>
        <div class="monitoring-attention-checked">Verificado em ${esc(monitoringDate(row.last_checked_at))}</div>
        ${alvo ? `<div class="monitoring-attention-acoes">
          <button type="button" class="drawer-filter-btn" data-onu-acao="consultar">Consultar sinal</button>
          <button type="button" class="drawer-filter-btn" data-onu-acao="excluir">Excluir ONU</button>
        </div>` : ''}
      </div>
      <div class="monitoring-attention-side">
        <span class="monitoring-type-chip">${esc(MONITORING_LABELS[row.entity_type] || row.entity_type)}</span>
        <span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span>
      </div>
    </div>`;
  }).join(''));

  // Um listener no container, nao um por linha: a lista e reconstruida a cada
  // troca de filtro.
  const lista = document.getElementById('dashDrawerBody') || document.getElementById('dashDrawerList');
  if (lista && !lista.dataset.onuAcaoBound) {
    lista.dataset.onuAcaoBound = '1';
    lista.addEventListener('click', event => {
      const botao = event.target.closest('[data-onu-acao]');
      const item = event.target.closest('[data-onu-olt]');
      if (!item) return;
      if (typeof window.onuAbrirAlvo !== 'function') return;
      if (typeof closeDashDrawer === 'function') closeDashDrawer();
      window.onuAbrirAlvo({
        connectorId: item.dataset.onuConnector || '',
        oltIp: item.dataset.onuOlt || '',
        pon: item.dataset.onuPon || '',
        onu: item.dataset.onuNum || '',
        acao: botao?.dataset.onuAcao || 'consultar',
      });
    });
  }
}

const MONITORING_ATTENTION = ['down', 'unstable', 'unknown'];
let _monitoringTab = 'attention';

// Site escolhido no topo da tela: filtra todos os cards, a tabela e as gavetas.
let _monitoringScope = (() => { try { return localStorage.getItem('sightops.monitoring.site') || ''; } catch (_) { return ''; } })();

// Conectores fora (por entity_id) e o que depende deles. Atras de conector fora
// nao da para afirmar nada sobre o equipamento: ele fica "sem visibilidade",
// nunca conta como disponivel nem como fora.
function monitoringConectoresFora() {
  const fora = new Map();
  _monitoringEntities.forEach(row => {
    if (row.entity_type === 'connector' && row.status === 'down') fora.set(String(row.entity_id || ''), row);
  });
  return fora;
}

function monitoringIsBlind(row, fora = monitoringConectoresFora()) {
  return row.entity_type !== 'connector' && fora.has(String(row.connector_id || ''));
}

function monitoringScoped() {
  return _monitoringScope ? _monitoringEntities.filter(row => String(row.site || '').trim() === _monitoringScope) : _monitoringEntities;
}

function monitoringSetScope(site) {
  _monitoringScope = site || '';
  try { localStorage.setItem('sightops.monitoring.site', _monitoringScope); } catch (_) { /* sem storage: so nesta aba */ }
  const select = document.getElementById('monitoringScope');
  if (select) select.value = _monitoringScope;
  const tableSite = document.getElementById('monitoringSite');
  if (tableSite) { tableSite.value = _monitoringScope; tableSite.hidden = !!_monitoringScope; }
  renderMonitoringAll();
}

function renderMonitoringAll() {
  renderMonitoringHealth();
  renderMonitoringSitesStrip();
  renderMonitoringIncidents();
  renderMonitoringKpis();
  renderMonitoringTabs();
  renderMonitoringRows();
  lucide.createIcons();
}

function renderMonitoringScopeSelect() {
  const select = document.getElementById('monitoringScope');
  if (!select) return;
  const sites = [...new Set(_monitoringEntities.map(row => String(row.site || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  if (_monitoringScope && !sites.includes(_monitoringScope)) _monitoringScope = '';
  select.innerHTML = '<option value="">Todos os sites</option>' + sites.map(site => `<option value="${esc(site)}">${esc(site)}</option>`).join('');
  select.value = _monitoringScope;
  select.hidden = sites.length < 2 && !_monitoringScope;
}

// Com "Todos os sites", a situacao de cada site embaixo dos cards. Site com o
// conector fora nao ganha porcentagem: o que esta atras dele nao tem leitura.
function renderMonitoringSitesStrip() {
  const el = document.getElementById('monitoringSitesStrip');
  if (!el) return;
  const fora = monitoringConectoresFora();
  const groups = new Map();
  _monitoringEntities.forEach(row => {
    const site = String(row.site || '').trim() || 'Sem site';
    if (!groups.has(site)) groups.set(site, { site, total: 0, up: 0, down: 0, attention: 0, blind: 0, conectores: [] });
    const g = groups.get(site);
    g.total += 1;
    if (row.entity_type === 'connector' && row.status === 'down') g.conectores.push(row);
    if (monitoringIsBlind(row, fora)) g.blind += 1;
    else if (row.status === 'up') g.up += 1;
    else if (row.status === 'down') g.down += 1;
    else if (row.status === 'unstable' || row.status === 'unknown') g.attention += 1;
  });
  if (_monitoringScope || groups.size < 2) { el.hidden = true; el.innerHTML = ''; return; }
  const peso = g => (g.conectores.length ? 0 : g.down ? 1 : g.attention ? 2 : 3);
  const list = [...groups.values()].sort((a, b) => peso(a) - peso(b) || a.site.localeCompare(b.site, 'pt-BR', { numeric: true }));
  el.hidden = false;
  el.innerHTML = `<table class="mn-sitetab">
    <thead><tr><th>Site</th><th class="n">Equipamentos</th><th class="n opt">Disponiveis</th><th class="n opt">Indisponiveis</th><th class="n opt">Sem leitura</th><th>Situacao</th></tr></thead>
    <tbody>${list.map(g => {
      let situacao = '<span class="mn-sit ok">Normal</span>';
      if (g.conectores.length) {
        const desde = Math.min(...g.conectores.map(c => monitoringTime(c.last_changed_at)).filter(Boolean));
        situacao = `<span class="mn-sit bad">Conector indisponivel${desde ? ` ha ${esc(monitoringElapsed(desde))}` : ''}</span><span class="mn-sit-sub">${g.blind} equipamento${g.blind === 1 ? '' : 's'} sem visibilidade</span>`;
      } else if (g.down) situacao = `<span class="mn-sit bad">${g.down} indisponive${g.down === 1 ? 'l' : 'is'}</span>`;
      else if (g.attention) situacao = `<span class="mn-sit warn">${g.attention} sem leitura ou instave${g.attention === 1 ? 'l' : 'is'}</span>`;
      const semSite = g.site === 'Sem site';
      return `<tr${semSite ? '' : ` data-monitoring-scope="${esc(g.site)}" tabindex="0"`}>
        <td><strong>${esc(g.site)}</strong></td>
        <td class="n">${g.total}</td>
        <td class="n opt">${g.conectores.length ? '<span class="mn-muted">--</span>' : `${g.up} de ${g.total}`}</td>
        <td class="n opt">${g.down || '--'}</td>
        <td class="n opt">${(g.attention + g.blind) || '--'}</td>
        <td>${situacao}</td>
      </tr>`;
    }).join('')}</tbody></table>`;
  el.querySelectorAll('[data-monitoring-scope]').forEach(tr => {
    tr.addEventListener('click', () => monitoringSetScope(tr.dataset.monitoringScope));
    tr.addEventListener('keydown', ev => { if (ev.key === 'Enter') monitoringSetScope(tr.dataset.monitoringScope); });
  });
}

function monitoringIsAttention(row) {
  return MONITORING_ATTENTION.includes(row.status);
}

function monitoringHostOf(row) {
  try {
    const detail = JSON.parse(row.detail_json || '{}');
    return String(detail.host || detail.ip || '').trim();
  } catch (_) { return ''; }
}

// Prefixo /24 do IP. E o que permite dizer "cairam todas na mesma faixa",
// que na pratica quer dizer o mesmo switch ou o mesmo trecho de rede.
function monitoringIpPrefix(host) {
  const match = String(host).match(/^(\d{1,3}\.\d{1,3}\.\d{1,3})\.\d{1,3}$/);
  return match ? match[1] : '';
}

function monitoringTime(value) {
  const time = new Date(value || 0).getTime();
  return Number.isNaN(time) ? 0 : time;
}

// "2 h 13", "45 min", "3 d 4 h" -- quanto tempo faz, nao a data.
function monitoringElapsed(value) {
  const time = monitoringTime(value);
  if (!time) return '';
  let seconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  const days = Math.floor(seconds / 86400); seconds -= days * 86400;
  const hours = Math.floor(seconds / 3600); seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  if (days) return hours ? `${days} d ${hours} h` : `${days} d`;
  if (hours) return `${hours} h ${String(minutes).padStart(2, '0')}`;
  return `${minutes} min`;
}

// O estado exibido so vale se a leitura for recente. Acima de 1 h, o "up"
// pode ser de um equipamento que ja caiu -- por isso vira aviso, nao silencio.
function monitoringIsStale(row) {
  const time = monitoringTime(row.last_checked_at);
  return !!time && (Date.now() - time) > 3600000;
}

function renderMonitoringHealth() {
  const el = document.getElementById('monitoringHealth');
  if (!el) return;
  const rows = monitoringScoped();
  const total = rows.length;
  const fora = monitoringConectoresFora();
  const blind = rows.filter(row => monitoringIsBlind(row, fora)).length;
  const vis = rows.filter(row => !monitoringIsBlind(row, fora));
  const up = vis.filter(row => row.status === 'up').length;
  const down = vis.filter(row => row.status === 'down').length;
  const attention = vis.filter(row => row.status === 'unstable' || row.status === 'unknown').length;
  const pct = vis.length ? (up / vis.length) * 100 : 0;
  const lastCheck = Math.max(0, ...rows.map(row => monitoringTime(row.last_checked_at)));
  const stale = rows.filter(monitoringIsStale).length;
  const changed24h = rows.filter(row => {
    const time = monitoringTime(row.last_changed_at);
    return time && (Date.now() - time) < 86400000;
  }).length;
  const sites = new Set(rows.map(row => String(row.site || '').trim()).filter(Boolean));

  el.innerHTML = `
    <div>
      <div class="mn-cap">Saude do parque</div>
      <div class="mn-score"><strong>${vis.length ? pct.toFixed(1).replace('.', ',') : '--'}%</strong><span>disponivel${blind ? ` dos ${vis.length} com leitura` : ''}</span></div>
      <div class="mn-bar" role="img" aria-label="${up} up, ${down} down, ${attention} em atencao">
        <i class="up" style="width:${total ? (up / total) * 100 : 0}%"></i>
        <i class="down" style="width:${total ? (down / total) * 100 : 0}%"></i>
        <i class="warn" style="width:${total ? (attention / total) * 100 : 0}%"></i>
        <i class="blind" style="width:${total ? (blind / total) * 100 : 0}%"></i>
      </div>
      <div class="mn-legend">
        <span class="up"><i class="mn-dot up"></i><b>${up}</b> up</span>
        <span class="down"><i class="mn-dot down"></i><b>${down}</b> down</span>
        <span class="warn"><i class="mn-dot warn"></i><b>${attention}</b> atencao</span>
        ${blind ? `<span class="blind"><i class="mn-dot blind"></i><b>${blind}</b> sem visibilidade (conector fora)</span>` : ''}
      </div>
    </div>
    <div>
      <div class="mn-cap">Parque monitorado</div>
      <div class="mn-score"><strong>${total}</strong><span>equipamento${total === 1 ? '' : 's'}</span></div>
      <div class="mn-caption">${_monitoringScope ? `Site <b>${esc(_monitoringScope)}</b>.` : `Em ${sites.size} site${sites.size === 1 ? '' : 's'}.`}</div>
      <div class="mn-caption"><b>${changed24h}</b> mudaram de estado nas ultimas 24 h.</div>
    </div>
    <div>
      <div class="mn-cap">Varredura</div>
      <div class="mn-scan"><span class="mn-pulse"></span><span>${lastCheck ? `Concluida ha <b>${esc(monitoringElapsed(lastCheck))}</b>` : 'Ainda nao executada'}</span></div>
      <div class="mn-caption">${lastCheck ? esc(monitoringDate(lastCheck)) : '--'}</div>
      ${stale ? `<div class="mn-warnline"><b>${stale}</b> sem resposta ha mais de 1 h</div>` : '<div class="mn-caption">Todas as leituras sao recentes.</div>'}
    </div>`;
}

// Junta os equipamentos em falha por site e faixa de IP. Dez cameras que
// cairam juntas na mesma faixa sao UM problema de rede, nao dez problemas.
function monitoringIncidentGroups() {
  const groups = new Map();
  const foraCon = monitoringConectoresFora();
  monitoringScoped().filter(monitoringIsAttention).forEach(row => {
    const prefix = monitoringIpPrefix(monitoringHostOf(row));
    const site = String(row.site || '').trim();
    const key = `${site}|${prefix || `tipo:${row.entity_type}`}`;
    if (!groups.has(key)) groups.set(key, { site, prefix, rows: [] });
    groups.get(key).rows.push(row);
  });
  const list = [...groups.values()].map(group => {
    const times = group.rows.map(row => monitoringTime(row.last_changed_at)).filter(Boolean);
    const oldest = times.length ? Math.min(...times) : 0;
    const spread = times.length ? Math.max(...times) - oldest : 0;
    // So chamo de rede quando 3+ equipamentos da mesma faixa mudaram de estado
    // dentro de 10 minutos. Espalhado no tempo e coincidencia, nao evento unico.
    const network = group.rows.length >= 3 && !!group.prefix && spread <= 600000;
    const onlyStale = group.rows.every(row => row.status === 'unknown' || monitoringIsStale(row));
    const blind = group.rows.every(row => monitoringIsBlind(row, foraCon));
    return { ...group, oldest, network: network && !blind, onlyStale: onlyStale && !blind, blind, count: group.rows.length };
  });
  list.sort((a, b) => b.count - a.count || a.oldest - b.oldest);
  return list;
}

function renderMonitoringIncidents() {
  const el = document.getElementById('monitoringIncidents');
  const counter = document.getElementById('monitoringIncidentCount');
  const summaryText = document.getElementById('monitoringSummaryText');
  if (!el) return;
  const groups = monitoringIncidentGroups();
  const affected = groups.reduce((sum, group) => sum + group.count, 0);
  if (counter) {
    counter.textContent = `${groups.length} ocorrencia${groups.length === 1 ? '' : 's'}`;
    counter.className = groups.length ? 'badge badge-red' : 'badge badge-green';
    counter.hidden = !groups.length;
  }
  if (summaryText) {
    summaryText.textContent = groups.length
      ? `${affected} equipamento${affected === 1 ? '' : 's'} agrupado${affected === 1 ? '' : 's'} por causa provavel.`
      : 'Nenhum equipamento precisa de verificacao agora.';
  }
  if (!groups.length) {
    el.innerHTML = '<div class="mn-inc-clear">Tudo respondendo. Nada exige verificacao neste momento.</div>';
    return;
  }

  el.innerHTML = groups.map((group, index) => {
    const visible = group.rows.slice(0, 4);
    const hidden = group.count - visible.length;
    const tags = [];
    if (group.blind) tags.push('<span class="badge badge-gray">conector indisponivel</span>');
    if (group.network) tags.push('<span class="badge badge-red">provavel rede</span>');
    else if (group.count === 1 && !group.blind) tags.push('<span class="badge badge-gray">isolada</span>');
    if (group.onlyStale) tags.push('<span class="badge badge-amber">dado velho</span>');
    if (group.prefix) tags.push(`<span class="badge badge-gray">${esc(group.prefix)}.0/24</span>`);
    const label = MONITORING_LABELS[group.rows[0].entity_type] || group.rows[0].entity_type;
    return `
    <details class="mn-inc${group.onlyStale ? ' warn' : ''}"${index === 0 ? ' open' : ''}>
      <summary class="mn-inc-head">
        <span class="mn-inc-main">
          <span class="mn-inc-title">${esc(group.site || 'Sem site')} · ${group.count} ${esc(group.count === 1 ? label.replace(/s$/, '') : label).toLowerCase()} ${group.blind ? 'sem visibilidade' : (group.onlyStale ? 'sem verificacao' : 'fora')} ${tags.join(' ')}</span>
          <span class="mn-inc-sub">${group.blind
            ? 'O conector do site esta indisponivel; o estado destes equipamentos nao pode ser verificado.'
            : group.network
            ? 'Mudaram de estado na mesma janela de tempo e na mesma faixa de IP.'
            : (group.count === 1 ? 'Ocorrencia isolada neste site.' : 'Mesmo site, sem evidencia de causa comum.')}</span>
        </span>
        <span class="mn-inc-since"><strong>${esc(monitoringElapsed(group.oldest) || '--')}</strong><span>${group.oldest ? `desde ${esc(monitoringDate(group.oldest))}` : 'sem registro'}</span></span>
        <i data-lucide="chevron-right" class="mn-chev"></i>
      </summary>
      <div class="mn-inc-body">
        ${visible.map(row => `
          <div class="mn-member">
            <span class="mn-sev ${esc(row.status)}"></span>
            <span class="mn-member-main">
              <span class="mn-member-name" title="${esc(row.display_name || row.entity_key)}">${esc(row.display_name || row.entity_key)}</span>
              ${(o => o ? `<span class="mn-member-onu${o.startsWith('Última') ? ' ultima' : ''}">${esc(o)}</span>` : '')(monitoringMembroOnu(row))}
            </span>
            <span class="mn-member-ip">${esc(monitoringHostOf(row) || '--')}</span>
            <span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span>
            <button class="mn-act" type="button" data-incident-focus="${esc(row.entity_key)}">Localizar</button>
          </div>`).join('')}
        ${hidden > 0 ? `<div class="mn-member"><span class="mn-sev ${esc(group.rows[0].status)}"></span><span class="mn-member-name mn-muted">mais ${hidden} na mesma faixa</span><button class="mn-act" type="button" data-incident-site="${esc(group.site)}">Ver os ${group.count}</button></div>` : ''}
      </div>
    </details>`;
  }).join('');

  el.querySelectorAll('[data-incident-focus]').forEach(button => {
    button.addEventListener('click', () => {
      const row = _monitoringEntities.find(item => item.entity_key === button.dataset.incidentFocus);
      if (row) monitoringFocusRow(row);
    });
  });
  el.querySelectorAll('[data-incident-site]').forEach(button => {
    button.addEventListener('click', () => {
      monitoringSetTab('attention');
      const site = document.getElementById('monitoringSite');
      const search = document.getElementById('monitoringSearch');
      const type = document.getElementById('monitoringType');
      if (site) site.value = button.dataset.incidentSite || '';
      if (search) search.value = '';
      if (type) type.value = '';
      renderMonitoringRows();
      document.getElementById('monitoringTablePanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });
}

function renderMonitoringRows() {
  const search = (document.getElementById('monitoringSearch')?.value || '').trim().toLowerCase();
  const type = document.getElementById('monitoringType')?.value || '';
  const status = document.getElementById('monitoringStatus')?.value || '';
  const site = document.getElementById('monitoringSite')?.value || '';
  const rows = monitoringScoped().filter(row => {
    if (_monitoringTab === 'attention' && !monitoringIsAttention(row)) return false;
    if (type && row.entity_type !== type) return false;
    if (status && row.status !== status) return false;
    if (site && row.site !== site) return false;
    return !search || `${row.display_name} ${row.site} ${row.entity_type} ${monitoringHostOf(row)} ${monitoringDetail(row)}`.toLowerCase().includes(search);
  });
  const body = document.getElementById('monitoringRows');
  if (!body) return;
  body.innerHTML = rows.length ? rows.map(row => `<tr>
    <td data-label="Tipo"><strong>${esc(MONITORING_LABELS[row.entity_type] || row.entity_type)}</strong></td>
    <td data-label="Equipamento" title="${esc(row.display_name || row.entity_key)}"><span class="mn-sev ${esc(row.status)}"></span><strong>${esc(row.display_name || row.entity_key)}</strong></td>
    <td data-label="Site">${esc(row.site || '--')}</td>
    <td data-label="Estado"><span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span></td>
    <td data-label="Ha quanto">${monitoringIsAttention(row) ? esc(monitoringElapsed(row.last_changed_at) || '--') : '<span class="mn-muted">--</span>'}</td>
    <td data-label="Ultima verificacao" class="${monitoringIsStale(row) ? 'mn-stale' : ''}">${esc(monitoringDate(row.last_checked_at))}</td>
    <td data-label="Detalhes" class="monitoring-detail" title="${esc(monitoringDetail(row) || '--')}">${esc(monitoringDetail(row) || '--')}</td>
  </tr>`).join('') : `<tr class="empty-row"><td colspan="7">${_monitoringTab === 'attention' ? 'Nenhum equipamento precisa de verificacao.' : 'Nenhum equipamento encontrado.'}</td></tr>`;
  const footer = document.getElementById('monitoringFooter');
  if (footer) {
    footer.textContent = _monitoringTab === 'attention'
      ? `${rows.length} equipamento(s) com problema`
      : `${rows.length} equipamento(s)`;
  }
}

function monitoringSetTab(tab) {
  _monitoringTab = tab === 'all' ? 'all' : 'attention';
  document.querySelectorAll('[data-monitoring-tab]').forEach(button => {
    button.setAttribute('aria-selected', String(button.dataset.monitoringTab === _monitoringTab));
  });
}

function renderMonitoringTabs() {
  const attention = monitoringScoped().filter(monitoringIsAttention).length;
  const all = monitoringScoped().length;
  const tabAttention = document.querySelector('[data-monitoring-tab="attention"]');
  const tabAll = document.querySelector('[data-monitoring-tab="all"]');
  if (tabAttention) tabAttention.textContent = `Com problema (${attention})`;
  if (tabAll) tabAll.textContent = `Todos os equipamentos (${all})`;
  // Parque inteiro saudavel: a aba de problemas vazia nao ajuda ninguem.
  if (!attention && _monitoringTab === 'attention') monitoringSetTab('all');
  else monitoringSetTab(_monitoringTab);
}

function renderMonitoringSites() {
  const select = document.getElementById('monitoringSite');
  if (!select) return;
  const selected = select.value;
  const sites = [...new Set(_monitoringEntities.map(row => String(row.site || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  select.innerHTML = '<option value="">Todos os sites</option>' + sites.map(site => `<option value="${esc(site)}">${esc(site)}</option>`).join('');
  if (sites.includes(selected)) select.value = selected;
}

function renderMonitoringKpis() {
  // Contado das entidades (e nao do /summary) para seguir o site escolhido no topo.
  const types = {};
  const fora = monitoringConectoresFora();
  monitoringScoped().forEach(row => {
    const t = types[row.entity_type] || (types[row.entity_type] = { total: 0, up: 0, down: 0, unstable: 0, unknown: 0, blind: 0 });
    t.total += 1;
    if (monitoringIsBlind(row, fora)) t.blind += 1;
    else if (row.status in t) t[row.status] += 1;
  });
  const el = document.getElementById('monitoringKpis');
  if (!el) return;
  const items = Object.entries(MONITORING_LABELS).map(([key, label]) => {
    const item = types[key] || { total: 0, up: 0, down: 0, unstable: 0, unknown: 0, blind: 0 };
    const attention = (item.unstable || 0) + (item.unknown || 0);
    return { key, label, total: item.total || 0, up: item.up || 0, down: item.down || 0, attention, blind: item.blind || 0 };
  });
  const used = items.filter(item => item.total > 0).sort((a, b) => b.total - a.total);
  const empty = items.filter(item => !item.total);

  el.innerHTML = used.map(item => {
    const pct = value => (item.total ? (value / item.total) * 100 : 0);
    let state = '<span class="mn-inv-state">tudo online</span>';
    if (item.down) state = `<span class="mn-inv-state bad">${item.down} fora</span>`;
    else if (item.attention) state = `<span class="mn-inv-state warn">${item.attention} em atencao</span>`;
    else if (item.blind) state = `<span class="mn-inv-state">${item.blind} sem visibilidade</span>`;
    return `<button class="mn-inv" type="button" data-monitoring-type="${esc(item.key)}" aria-label="Abrir detalhes de ${esc(item.label)}">
      <span class="mn-inv-label">${esc(item.label)}</span>
      <span class="mn-inv-total">${item.total}</span>
      <span class="mn-inv-bar"><i class="up" style="width:${pct(item.up)}%"></i><i class="down" style="width:${pct(item.down)}%"></i><i class="warn" style="width:${pct(item.attention)}%"></i><i class="blind" style="width:${pct(item.blind)}%"></i></span>
      ${state}
      <i data-lucide="chevron-right" class="mn-inv-arrow"></i>
    </button>`;
  }).join('') + (empty.length
    ? `<div class="mn-inv-empty">Sem equipamentos cadastrados: ${empty.map(item => esc(item.label)).join(', ')}.</div>`
    : '');

  el.querySelectorAll('[data-monitoring-type]').forEach(card => {
    card.addEventListener('click', () => openMonitoringDrawer(card.dataset.monitoringType, 'all', _monitoringScope || null));
  });
}

async function loadMonitoring() {
  const summaryText = document.getElementById('monitoringSummaryText');
  if (summaryText) summaryText.textContent = 'Carregando estados...';
  try {
    const entities = await apiJson('/api/monitoring/entities?limit=2000', { forceRefresh: true });
    _monitoringEntities = entities?.entities || [];
    renderMonitoringScopeSelect();
    renderMonitoringSites();
    const tableSite = document.getElementById('monitoringSite');
    if (tableSite) { tableSite.hidden = !!_monitoringScope; if (_monitoringScope) tableSite.value = _monitoringScope; }
    renderMonitoringAll();
  } catch (error) {
    if (summaryText) summaryText.textContent = `Falha ao carregar: ${error.message || error}`;
  }
}

async function refreshMonitoring() {
  const btn = document.getElementById('btnMonitoringRefresh');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader-circle" class="spin"></i> Atualizando'; lucide.createIcons(); }
  try {
    const response = await api('/api/monitoring/refresh', { method: 'POST' });
    const result = await jsonOrReadableError(response, 'Nao foi possivel atualizar os estados.');
    showToast(`${result.total || 0} equipamentos atualizados.`);
    await loadMonitoring();
  } catch (error) {
    showToast(error.message || 'Nao foi possivel atualizar os estados.', true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="refresh-cw"></i> Atualizar estados'; lucide.createIcons(); }
  }
}

function bindMonitoring() {
  document.getElementById('btnMonitoringRefresh')?.addEventListener('click', refreshMonitoring);
  document.getElementById('monitoringScope')?.addEventListener('change', event => monitoringSetScope(event.target.value));
  bindMonitoringReport();
  document.getElementById('monitoringSearch')?.addEventListener('input', renderMonitoringRows);
  document.getElementById('monitoringType')?.addEventListener('change', renderMonitoringRows);
  document.getElementById('monitoringStatus')?.addEventListener('change', renderMonitoringRows);
  document.getElementById('monitoringSite')?.addEventListener('change', renderMonitoringRows);
  document.querySelectorAll('[data-monitoring-tab]').forEach(button => {
    button.addEventListener('click', () => { monitoringSetTab(button.dataset.monitoringTab); renderMonitoringRows(); });
  });
}

// ---------------------------------------------------------------- relatorio
// Disponibilidade do periodo (tempo no ar, quedas, tempo fora). A tela mostra
// o resumo; o PDF (A4, logo do cliente) traz tudo, inclusive a lista de quedas.

function mnRelIso(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function mnRelPeriodo(tipo) {
  const hoje = new Date();
  let de = new Date(hoje), ate = new Date(hoje);
  if (tipo === 'mes') de = new Date(hoje.getFullYear(), hoje.getMonth(), 1);
  else if (tipo === 'mes-passado') { de = new Date(hoje.getFullYear(), hoje.getMonth() - 1, 1); ate = new Date(hoje.getFullYear(), hoje.getMonth(), 0); }
  else de.setDate(hoje.getDate() - (Number(tipo) || 7) + 1);
  document.getElementById('mnRelDe').value = mnRelIso(de);
  document.getElementById('mnRelAte').value = mnRelIso(ate);
}

function mnRelQuery() {
  const q = new URLSearchParams();
  [['de', 'mnRelDe'], ['ate', 'mnRelAte'], ['site', 'mnRelSite'], ['tipo', 'mnRelTipo']].forEach(([k, id]) => {
    const v = document.getElementById(id)?.value || '';
    if (v) q.set(k, v);
  });
  return q.toString();
}

function mnRelQuando(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const dois = n => String(n).padStart(2, '0');
  return `${dois(d.getDate())}/${dois(d.getMonth() + 1)} ${dois(d.getHours())}:${dois(d.getMinutes())}`;
}

function mnRelDur(seg) {
  seg = Math.floor(Number(seg) || 0);
  if (!seg) return '--';
  const d = Math.floor(seg / 86400), h = Math.floor((seg % 86400) / 3600), m = Math.floor((seg % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${String(m).padStart(2, '0')}m`;
  return m ? `${m} min` : `${seg}s`;
}

function mnRelP(v, zeroTraco = true) {
  if (v == null) return '--';
  if (zeroTraco && v === 0) return '--';
  return `${Number(v).toFixed(1).replace('.', ',')}%`;
}

function mnRelFora(v) {
  return v ? `<b class="mn-rel-bad">${mnRelP(v)}</b>` : mnRelP(v);
}

function mnRelBarra(noAr, fora, sem) {
  return `<span class="mn-rel-barra"><i class="ar" style="width:${noAr || 0}%"></i><i class="fora" style="width:${fora || 0}%"></i><i class="sem" style="width:${sem || 0}%"></i></span>`;
}

// Equipamentos do mesmo site que cairam e voltaram no mesmo minuto: uma linha so.
function mnRelAgrupar(ocorrencias) {
  const grupos = new Map();
  const out = [];
  ocorrencias.forEach(o => {
    if (o.tipo !== 'equipamento') { out.push(o); return; }
    const chave = `${o.site}|${o.inicio.slice(0, 16)}|${o.fim.slice(0, 16)}|${o.aberta}`;
    if (grupos.has(chave)) { grupos.get(chave).nomes.push(o.equipamento); return; }
    const g = { ...o, nomes: [o.equipamento] };
    grupos.set(chave, g);
    out.push(g);
  });
  return out;
}

function mnRelRender(r) {
  const el = document.getElementById('mnRelResultado');
  const rs = r.resumo, an = r.anterior;
  if (!rs.equipamentos) { el.innerHTML = '<p class="mn-muted">Nao ha equipamentos monitorados com os filtros informados.</p>'; return; }
  const num = v => Number(v || 0).toLocaleString('pt-BR');
  const br = iso => iso.split('-').reverse().join('/');
  const multi = !r.um_site;
  const tab = (cab, numericas, linhas) => `<div class="table-wrap"><table class="mn-rel-tab"><thead><tr>${cab.map((c, i) => `<th${numericas.includes(i) ? ' class="n"' : ''}>${esc(c)}</th>`).join('')}</tr></thead><tbody>${linhas}</tbody></table></div>`;
  const grupo = (titulo, cab, lista) => lista.length < 2 ? '' : `<h3>${esc(titulo)}</h3>` + tab(
    [cab, 'Equip.', 'No ar', 'Fora', 'Sem leitura', 'Quedas', 'Fora agora'], [1, 2, 3, 4, 5, 6],
    lista.map(g => `<tr><td><strong>${esc(g.nome)}</strong></td><td class="n">${g.equipamentos}</td><td class="n">${mnRelP(g.no_ar_pct, false)}</td><td class="n">${mnRelFora(g.fora_pct)}</td><td class="n">${mnRelP(g.sem_pct)}</td><td class="n">${g.quedas || '--'}</td><td class="n">${g.fora_agora || '--'}</td></tr>`).join(''));

  const pend = r.pendencias.length
    ? tab(['Equipamento', ...(multi ? ['Site'] : []), 'Situacao', 'Desde'], [],
      r.pendencias.map(p => `<tr><td><strong>${esc(p.equipamento)}</strong>${p.tipo_item ? ` <span class="mn-muted">· ${esc(p.tipo_item)}</span>` : ''}</td>${multi ? `<td>${esc(p.site)}</td>` : ''}<td>${p.situacao === 'Fora' ? '<b class="mn-rel-bad">Fora</b>' : esc(p.situacao)}</td><td class="d">${esc(mnRelQuando(p.desde))}</td></tr>`).join(''))
    : '<p>Nenhuma pendencia: todos os equipamentos estao no ar.</p>';

  const ocs = mnRelAgrupar(r.ocorrencias).slice(0, 20);
  const oc = ocs.length
    ? tab(['Inicio', 'Fim', 'Duracao', 'Equipamento', ...(multi ? ['Site'] : []), 'O que aconteceu'], [2],
      ocs.map(o => {
        const nome = o.tipo === 'conector' || o.nomes.length === 1
          ? `<strong>${esc(o.equipamento)}</strong>`
          : `<strong>${o.nomes.length} equipamentos</strong><br><span class="mn-muted">${esc(o.nomes.slice(0, 8).join(', '))}${o.nomes.length > 8 ? ` e mais ${o.nomes.length - 8}` : ''}</span>`;
        const oque = o.tipo === 'conector' ? `<b>Conector fora</b> · ${o.afetados} sem leitura` : '<b>Fora</b>';
        return `<tr><td class="d">${esc(mnRelQuando(o.inicio))}</td><td class="d">${o.aberta ? '<b class="mn-rel-bad">continua fora</b>' : esc(mnRelQuando(o.fim))}</td><td class="n">${mnRelDur(o.duracao_s)}</td><td>${nome}</td>${multi ? `<td>${esc(o.site)}</td>` : ''}<td>${oque}</td></tr>`;
      }).join(''))
    : '<p>Nenhuma queda de conector ou de equipamento no periodo.</p>';

  const dias = r.dias.filter(d => d.no_ar_pct != null);
  el.innerHTML = `
    <div class="mn-rel-tres">
      <div><span class="mn-cap">No ar</span><strong>${mnRelP(rs.no_ar_pct, false)}</strong><small>do tempo</small></div>
      <div><span class="mn-cap">Fora</span><strong class="${rs.fora_pct ? 'mn-rel-bad' : ''}">${mnRelP(rs.fora_pct, false)}</strong><small>do tempo</small></div>
      <div><span class="mn-cap">Sem leitura</span><strong>${mnRelP(rs.sem_pct, false)}</strong><small>do tempo</small></div>
    </div>
    ${mnRelBarra(rs.no_ar_pct, rs.fora_pct, rs.sem_pct)}
    <p class="mn-rel-legenda"><i class="ar"></i> no ar <i class="fora"></i> fora <i class="sem"></i> sem leitura${an.no_ar_pct != null ? ` &nbsp;·&nbsp; periodo anterior (${esc(br(r.anterior_de))} a ${esc(br(r.anterior_ate))}): ${mnRelP(an.no_ar_pct, false)} no ar, ${mnRelP(an.fora_pct, false)} fora, ${mnRelP(an.sem_pct, false)} sem leitura` : ''}</p>
    <h3>1 Pendencias agora</h3>${pend}
    <h3>2 Ocorrencias no periodo <span class="mn-muted">${num(r.ocorrencias_total)}${r.ocorrencias_total > ocs.length ? '; lista completa no PDF' : ''}</span></h3>${oc}
    ${dias.length ? `<h3>3 Dia a dia</h3>` + tab(['Dia', 'No ar', 'Fora', 'Sem leitura', 'Quedas', ''], [1, 2, 3, 4],
      dias.map(d => `<tr><td>${esc(d.rotulo)}</td><td class="n">${mnRelP(d.no_ar_pct, false)}</td><td class="n">${mnRelFora(d.fora_pct)}</td><td class="n">${mnRelP(d.sem_pct)}</td><td class="n">${d.quedas || '--'}</td><td class="mn-rel-col-barra">${mnRelBarra(d.no_ar_pct, d.fora_pct, d.sem_pct)}</td></tr>`).join('')) : ''}
    ${grupo('Por site', 'Site', r.por_site)}
    ${grupo('Por tipo de equipamento', 'Tipo', r.por_tipo)}
    <p class="mn-rel-nota"><b>No ar</b>: respondeu ao monitoramento. <b>Fora</b>: nao respondeu, confirmado por leituras seguidas. <b>Sem leitura</b>: nao foi possivel verificar, quase sempre porque o conector do site estava fora; esse tempo nao conta como fora. As tres partes somam 100%. A lista de todos os equipamentos esta no PDF.</p>`;
}

async function mnRelGerar() {
  const btn = document.getElementById('btnMnRelGerar');
  const el = document.getElementById('mnRelResultado');
  btn.disabled = true;
  el.innerHTML = '<p class="mn-muted">Calculando...</p>';
  try {
    const r = await apiJson(`/api/monitoring/relatorio?${mnRelQuery()}`, { forceRefresh: true });
    document.getElementById('mnRelDe').value = r.de;
    document.getElementById('mnRelAte').value = r.ate;
    mnRelRender(r);
  } catch (error) {
    el.innerHTML = `<p class="mn-rel-bad">Nao foi possivel gerar: ${esc(error.message || error)}</p>`;
  } finally {
    btn.disabled = false;
  }
}

async function mnRelPdf() {
  const btn = document.getElementById('btnMnRelPdf');
  btn.disabled = true;
  try {
    const res = await api(`/api/monitoring/relatorio/pdf?${mnRelQuery()}`);
    if (!res || !res.ok) {
      const det = res ? (await res.json().catch(() => ({}))).detail : '';
      throw new Error(det || 'Falha ao gerar o PDF.');
    }
    const nome = (res.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'disponibilidade.pdf';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await res.blob());
    a.download = nome;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  } catch (error) {
    showToast(error.message || 'Falha ao gerar o PDF.', true);
  } finally {
    btn.disabled = false;
  }
}

function openMonitoringReport() {
  const site = document.getElementById('mnRelSite');
  const sites = [...new Set(_monitoringEntities.map(row => String(row.site || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  site.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
  site.value = _monitoringScope;
  const tipo = document.getElementById('mnRelTipo');
  const tipos = [...new Set(_monitoringEntities.map(row => row.entity_type))];
  const atual = tipo.value;
  tipo.innerHTML = '<option value="">Todos os tipos</option>' + tipos.map(t => `<option value="${esc(t)}">${esc(MONITORING_LABELS[t] || t)}</option>`).join('');
  if (tipos.includes(atual)) tipo.value = atual;
  if (!document.getElementById('mnRelDe').value) mnRelPeriodo('7');
  document.getElementById('modalMonitoringReport').classList.remove('hidden');
  lucide.createIcons();
  mnRelGerar();
}

function closeMonitoringReport() {
  document.getElementById('modalMonitoringReport')?.classList.add('hidden');
}

function bindMonitoringReport() {
  document.getElementById('btnMonitoringReport')?.addEventListener('click', openMonitoringReport);
  document.getElementById('btnMnRelGerar')?.addEventListener('click', mnRelGerar);
  document.getElementById('btnMnRelPdf')?.addEventListener('click', mnRelPdf);
  document.querySelectorAll('[data-mn-rel-close]').forEach(b => b.addEventListener('click', closeMonitoringReport));
  document.querySelectorAll('[data-mn-rel-periodo]').forEach(b => b.addEventListener('click', () => { mnRelPeriodo(b.dataset.mnRelPeriodo); mnRelGerar(); }));
  // So X, Fechar ou Esc fecham (clique fora nao: perdia o que estava aberto).
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !document.getElementById('modalMonitoringReport')?.classList.contains('hidden')) closeMonitoringReport();
  });
}
