let _monitoringEntities = [];

const MONITORING_LABELS = {
  connector: 'Conectores', olt: 'OLTs', onu: 'ONUs/ONTs', camera: 'Cameras',
  nvr: 'NVRs', dvr: 'DVRs', windows: 'Computadores',
  access_device: 'Controladoras de Acesso', whatsapp: 'WhatsApp',
};

function monitoringStatusLabel(status) {
  return ({ up: 'Up', down: 'Down', unstable: 'Instavel', unknown: 'Nao verificado', maintenance: 'Manutencao' })[status] || status;
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
  _drawerRenderRows(rows.map(row => `
    <div class="drawer-item monitoring-attention-item">
      ${_drawerStatusDot(row.status)}
      <div class="drawer-item-main">
        <div class="drawer-item-title">${esc(row.display_name || row.entity_key)}</div>
        <div class="drawer-item-sub" title="${esc(monitoringDrawerMeta(row))}">${esc(monitoringDrawerMeta(row) || 'Sem detalhes adicionais')}</div>
        <div class="monitoring-attention-checked">Verificado em ${esc(monitoringDate(row.last_checked_at))}</div>
      </div>
      <div class="monitoring-attention-side">
        <span class="monitoring-type-chip">${esc(MONITORING_LABELS[row.entity_type] || row.entity_type)}</span>
        <span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span>
      </div>
    </div>
  `).join(''));
}

const MONITORING_ATTENTION = ['down', 'unstable', 'unknown'];
let _monitoringTab = 'attention';

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
  const rows = _monitoringEntities;
  const total = rows.length;
  const up = rows.filter(row => row.status === 'up').length;
  const down = rows.filter(row => row.status === 'down').length;
  const attention = rows.filter(row => row.status === 'unstable' || row.status === 'unknown').length;
  const pct = total ? (up / total) * 100 : 0;
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
      <div class="mn-score"><strong>${total ? pct.toFixed(1).replace('.', ',') : '--'}%</strong><span>disponivel</span></div>
      <div class="mn-bar" role="img" aria-label="${up} up, ${down} down, ${attention} em atencao">
        <i class="up" style="width:${total ? (up / total) * 100 : 0}%"></i>
        <i class="down" style="width:${total ? (down / total) * 100 : 0}%"></i>
        <i class="warn" style="width:${total ? (attention / total) * 100 : 0}%"></i>
      </div>
      <div class="mn-legend">
        <span class="up"><i class="mn-dot up"></i><b>${up}</b> up</span>
        <span class="down"><i class="mn-dot down"></i><b>${down}</b> down</span>
        <span class="warn"><i class="mn-dot warn"></i><b>${attention}</b> atencao</span>
      </div>
    </div>
    <div>
      <div class="mn-cap">Parque monitorado</div>
      <div class="mn-score"><strong>${total}</strong><span>equipamento${total === 1 ? '' : 's'}</span></div>
      <div class="mn-caption">Em ${sites.size} site${sites.size === 1 ? '' : 's'}.</div>
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
  _monitoringEntities.filter(monitoringIsAttention).forEach(row => {
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
    return { ...group, oldest, network, onlyStale, count: group.rows.length };
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
    if (group.network) tags.push('<span class="badge badge-red">provavel rede</span>');
    else if (group.count === 1) tags.push('<span class="badge badge-gray">isolada</span>');
    if (group.onlyStale) tags.push('<span class="badge badge-amber">dado velho</span>');
    if (group.prefix) tags.push(`<span class="badge badge-gray">${esc(group.prefix)}.0/24</span>`);
    const label = MONITORING_LABELS[group.rows[0].entity_type] || group.rows[0].entity_type;
    return `
    <details class="mn-inc${group.onlyStale ? ' warn' : ''}"${index === 0 ? ' open' : ''}>
      <summary class="mn-inc-head">
        <span class="mn-inc-main">
          <span class="mn-inc-title">${esc(group.site || 'Sem site')} · ${group.count} ${esc(group.count === 1 ? label.replace(/s$/, '') : label).toLowerCase()} ${group.onlyStale ? 'sem verificacao' : 'fora'} ${tags.join(' ')}</span>
          <span class="mn-inc-sub">${group.network
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
            <span class="mn-member-name" title="${esc(row.display_name || row.entity_key)}">${esc(row.display_name || row.entity_key)}</span>
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
  const rows = _monitoringEntities.filter(row => {
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
  const attention = _monitoringEntities.filter(monitoringIsAttention).length;
  const all = _monitoringEntities.length;
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

function renderMonitoringKpis(summary) {
  const types = summary?.types || {};
  const el = document.getElementById('monitoringKpis');
  if (!el) return;
  const items = Object.entries(MONITORING_LABELS).map(([key, label]) => {
    const item = types[key] || { total: 0, up: 0, down: 0, unstable: 0, unknown: 0 };
    const attention = (item.unstable || 0) + (item.unknown || 0);
    return { key, label, total: item.total || 0, up: item.up || 0, down: item.down || 0, attention };
  });
  const used = items.filter(item => item.total > 0).sort((a, b) => b.total - a.total);
  const empty = items.filter(item => !item.total);

  el.innerHTML = used.map(item => {
    const pct = value => (item.total ? (value / item.total) * 100 : 0);
    let state = '<span class="mn-inv-state">tudo online</span>';
    if (item.down) state = `<span class="mn-inv-state bad">${item.down} fora</span>`;
    else if (item.attention) state = `<span class="mn-inv-state warn">${item.attention} em atencao</span>`;
    return `<button class="mn-inv" type="button" data-monitoring-type="${esc(item.key)}" aria-label="Abrir detalhes de ${esc(item.label)}">
      <span class="mn-inv-label">${esc(item.label)}</span>
      <span class="mn-inv-total">${item.total}</span>
      <span class="mn-inv-bar"><i class="up" style="width:${pct(item.up)}%"></i><i class="down" style="width:${pct(item.down)}%"></i><i class="warn" style="width:${pct(item.attention)}%"></i></span>
      ${state}
      <i data-lucide="chevron-right" class="mn-inv-arrow"></i>
    </button>`;
  }).join('') + (empty.length
    ? `<div class="mn-inv-empty">Sem equipamentos cadastrados: ${empty.map(item => esc(item.label)).join(', ')}.</div>`
    : '');

  el.querySelectorAll('[data-monitoring-type]').forEach(card => {
    card.addEventListener('click', () => openMonitoringDrawer(card.dataset.monitoringType, 'all'));
  });
}

async function loadMonitoring() {
  const summaryText = document.getElementById('monitoringSummaryText');
  if (summaryText) summaryText.textContent = 'Carregando estados...';
  try {
    const [summary, entities] = await Promise.all([
      apiJson('/api/monitoring/summary', { forceRefresh: true }),
      apiJson('/api/monitoring/entities?limit=2000', { forceRefresh: true }),
    ]);
    _monitoringEntities = entities?.entities || [];
    renderMonitoringHealth();
    renderMonitoringIncidents();
    renderMonitoringKpis(summary);
    renderMonitoringSites();
    renderMonitoringTabs();
    renderMonitoringRows();
    lucide.createIcons();
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
  document.getElementById('monitoringSearch')?.addEventListener('input', renderMonitoringRows);
  document.getElementById('monitoringType')?.addEventListener('change', renderMonitoringRows);
  document.getElementById('monitoringStatus')?.addEventListener('change', renderMonitoringRows);
  document.getElementById('monitoringSite')?.addEventListener('change', renderMonitoringRows);
  document.querySelectorAll('[data-monitoring-tab]').forEach(button => {
    button.addEventListener('click', () => { monitoringSetTab(button.dataset.monitoringTab); renderMonitoringRows(); });
  });
}
