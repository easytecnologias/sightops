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
      const onuRx = detail.onu_rx ? `ONU ${detail.onu_rx}` : 'ONU RX --';
      const oltRx = detail.olt_rx ? `OLT ${detail.olt_rx}` : 'OLT RX --';
      return `${onuRx} | ${oltRx}`;
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
  renderMonitoringRows();
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

async function openMonitoringAttentionDrawer(activeType = 'all', activeSite = null) {
  _openDashDrawer('Atencao operacional', 'Equipamentos que precisam de cuidado');
  if (!_monitoringEntities.length) {
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

function renderMonitoringRows() {
  const search = (document.getElementById('monitoringSearch')?.value || '').trim().toLowerCase();
  const type = document.getElementById('monitoringType')?.value || '';
  const status = document.getElementById('monitoringStatus')?.value || '';
  const site = document.getElementById('monitoringSite')?.value || '';
  const rows = _monitoringEntities.filter(row => {
    if (type && row.entity_type !== type) return false;
    if (status && row.status !== status) return false;
    if (site && row.site !== site) return false;
    return !search || `${row.display_name} ${row.site} ${row.entity_type} ${monitoringDetail(row)}`.toLowerCase().includes(search);
  });
  const body = document.getElementById('monitoringRows');
  if (!body) return;
  body.innerHTML = rows.length ? rows.map(row => `<tr>
    <td data-label="Tipo"><strong>${esc(MONITORING_LABELS[row.entity_type] || row.entity_type)}</strong></td>
    <td data-label="Equipamento" title="${esc(row.display_name || row.entity_key)}"><strong>${esc(row.display_name || row.entity_key)}</strong></td>
    <td data-label="Site">${esc(row.site || '--')}</td>
    <td data-label="Estado"><span class="monitoring-status ${esc(row.status)}">${esc(monitoringStatusLabel(row.status))}</span></td>
    <td data-label="Ultima verificacao">${esc(monitoringDate(row.last_checked_at))}</td>
    <td data-label="Detalhes" class="monitoring-detail" title="${esc(monitoringDetail(row) || '--')}">${esc(monitoringDetail(row) || '--')}</td>
  </tr>`).join('') : '<tr class="empty-row"><td colspan="6">Nenhum equipamento encontrado.</td></tr>';
  document.getElementById('monitoringFooter').textContent = `${rows.length} equipamento(s)`;
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
  el.innerHTML = Object.entries(MONITORING_LABELS).map(([key, label]) => {
    const item = types[key] || { total: 0, up: 0, down: 0, unstable: 0, unknown: 0 };
    const attention = (item.unstable || 0) + (item.unknown || 0);
    return `<article class="monitoring-kpi" data-monitoring-type="${esc(key)}" role="button" tabindex="0" aria-label="Abrir detalhes de ${esc(label)}">
      <span>${label}</span><strong>${item.total || 0}</strong>
      <small><b class="up">${item.up || 0} up</b><b class="down">${item.down || 0} down</b><b class="unstable">${attention} atencao</b></small>
      <i data-lucide="chevron-right" class="monitoring-kpi-arrow"></i>
    </article>`;
  }).join('');
  el.querySelectorAll('[data-monitoring-type]').forEach(card => {
    const open = () => openMonitoringDrawer(card.dataset.monitoringType, 'all');
    card.addEventListener('click', open);
    card.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
    });
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
    renderMonitoringKpis(summary);
    renderMonitoringSites();
    renderMonitoringRows();
    const attention = _monitoringEntities.filter(row => ['down', 'unstable', 'unknown'].includes(row.status)).length;
    if (summaryText) summaryText.textContent = `${attention} item(ns) precisam de verificacao.`;
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
}
