function winText(v) { return String(v ?? '').trim(); }
function winKey(row) { return winText(row.ip) || winText(row.hostname) || winText(row.serial); }
function winIsOnline(row) {
  const s = winText(row.status).toLowerCase();
  return s === 'online' || s === 'agent_reported';
}
function winOsLabel(row) {
  const os = row.os && typeof row.os === 'object' ? row.os : {};
  return [os.name || row.os_name, os.build].filter(Boolean).join(' / ') || '-';
}
function winUserLabel(row) { return winText(row.logged_user || row.user || row.username) || '-'; }
function winModelLabel(row) {
  return [row.manufacturer, row.model].map(winText).filter(Boolean).join(' ') || '-';
}
function winCpuLabel(row) {
  const cpu = row.cpu && typeof row.cpu === 'object' ? row.cpu : {};
  const name = winText(cpu.name || row.cpu_name || row.cpu);
  if (!name) return '-';
  return name.replace(/\s+/g, ' ').replace(/Intel\(R\)|Core\(TM\)|CPU|@.*$/gi, '').trim() || name;
}
function winRamLabel(row) {
  if (row.memory_summary) return winText(row.memory_summary);
  const ram = Number(row.ram_gb || row.total_ram_gb || 0);
  return ram ? `${Math.round(ram)} GB` : '-';
}
function winPrimaryDisk(row) {
  const disks = Array.isArray(row.disks) ? row.disks.filter(d => d && typeof d === 'object') : [];
  return disks[0] || {};
}
function winDiskModel(row) {
  const disk = winPrimaryDisk(row);
  return winText(disk.model || disk.caption || disk.name) || '-';
}
function winDiskSerial(row) {
  const disk = winPrimaryDisk(row);
  return winText(disk.serial || disk.serial_number) || '-';
}
function winDiskType(row) {
  const disk = winPrimaryDisk(row);
  const diskType = winText(disk.media_type || disk.interface_type).toUpperCase();
  if (diskType && diskType !== 'UNSPECIFIED') return diskType;
  const kind = winText(row.disk_kind).toUpperCase();
  if (kind) return kind;
  const label = winText(row.disk_summary).toUpperCase();
  if (label.includes('NVME')) return 'NVME';
  if (label.includes('SSD')) return 'SSD';
  if (label.includes('HDD') || label.includes('FIXED')) return 'HDD';
  return '-';
}
function winDiskGb(row) {
  const disk = winPrimaryDisk(row);
  const diskSize = Number(disk.size_gb || disk.capacity_gb || 0);
  if (diskSize) return String(Math.round(diskSize));
  const total = Number(row.disk_total_gb || 0);
  if (total) return String(Math.round(total));
  const label = winText(row.disk_summary);
  const match = label.match(/(\d+(?:\.\d+)?)\s*(TB|GB)/i);
  if (!match) return '-';
  const value = Number(match[1]);
  return match[2].toUpperCase() === 'TB' ? String(Math.round(value * 1024)) : String(Math.round(value));
}
function winDiskLabel(row) {
  const type = winDiskType(row);
  const gb = winDiskGb(row);
  if (type === '-' && gb === '-') return winText(row.disk_summary) || '-';
  return [type, gb !== '-' ? `${gb} GB` : ''].filter(Boolean).join(' ');
}
function winPhysical(row) {
  return row.physical && typeof row.physical === 'object' ? row.physical : {};
}
function winPhysicalLabel(row) {
  const p = winPhysical(row);
  const parts = [p.switch_name, p.switch_port, p.patch_panel, p.patch_port, p.outlet, p.rack, p.asset_tag].map(winText).filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}
function winMissingData(row) {
  return !winText(row.mac) || !winText(row.hostname) || !winText(row.model) || !winText(row.site) || !winText(row.sector || row.setor) || winPhysicalLabel(row) === '-';
}
function winMatchesFilter(row) {
  const status = document.getElementById('filterWinStatus')?.value || '';
  const site = document.getElementById('filterWinSite')?.value || '';
  const sector = document.getElementById('filterWinSector')?.value || '';
  const q = (document.getElementById('searchInvWindows')?.value || '').toLowerCase().trim();
  if (site && winText(row.site) !== site) return false;
  if (sector && winText(row.sector || row.setor) !== sector) return false;
  if (status === 'online' && !winIsOnline(row)) return false;
  if (status === 'offline' && winIsOnline(row)) return false;
  if (status === 'with_ssd' && !row.has_ssd) return false;
  if (status === 'without_ssd' && row.has_ssd) return false;
  if (status === 'with_anydesk' && !winText(row.anydesk_id)) return false;
  if (status === 'without_anydesk' && winText(row.anydesk_id)) return false;
  if (status === 'windows11' && !winOsLabel(row).toLowerCase().includes('windows 11')) return false;
  if (status === 'windows10' && !winOsLabel(row).toLowerCase().includes('windows 10')) return false;
  if (status === 'missing_data' && !winMissingData(row)) return false;
  if (!q) return true;
  return [row.ip, row.mac, row.hostname, winUserLabel(row), winOsLabel(row), winModelLabel(row), winCpuLabel(row), winDiskLabel(row), row.anydesk_id, row.site, row.sector, row.error, winDiskModel(row), winDiskSerial(row), winPhysicalLabel(row)]
    .some(v => winText(v).toLowerCase().includes(q));
}
function populateWinFilters() {
  const fill = (id, values, label) => {
    const el = document.getElementById(id);
    if (!el) return;
    const cur = el.value;
    const unique = [...new Set(values.map(winText).filter(Boolean))].sort((a,b) => a.localeCompare(b));
    el.innerHTML = `<option value="">${label}</option>` + unique.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    if (unique.includes(cur)) el.value = cur;
  };
  fill('filterWinSite', _winRows.map(r => r.site), 'Todos os sites');
  fill('filterWinSector', _winRows.map(r => r.sector || r.setor), 'Todos os setores');
}
function updateWinSummary() {
  const total = _winRows.length;
  const online = _winRows.filter(winIsOnline).length;
  const ssd = _winRows.filter(r => !!r.has_ssd).length;
  setText('winTotal', total);
  setText('winOnline', online);
  setText('winOffline', Math.max(0, total - online));
  setText('winSsd', ssd);
  setText('winNoSsd', Math.max(0, total - ssd));
}
function updateWinSelectionUi() {
  setText('winSelectedCount', `${_winSelected.size} selecionado${_winSelected.size === 1 ? '' : 's'}`);
  const visibleKeys = _winFilteredRows.map(winKey).filter(Boolean);
  const selectedVisible = visibleKeys.filter(k => _winSelected.has(k)).length;
  const all = document.getElementById('chkWinAll');
  if (all) {
    all.checked = visibleKeys.length > 0 && selectedVisible === visibleKeys.length;
    all.indeterminate = selectedVisible > 0 && selectedVisible < visibleKeys.length;
  }
}
function renderWinRows(rows) {
  const tbody = document.getElementById('invWindowsTable');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="27">Nenhum computador encontrado.</td></tr>';
    setText('invWindowsFooter', '0 hosts');
    updateWinSelectionUi();
    return;
  }
  tbody.innerHTML = rows.map(row => {
    const key = winKey(row);
    const online = winIsOnline(row);
    const anydesk = winText(row.anydesk_id);
    const phys = winPhysicalLabel(row);
    const physical = winPhysical(row);
    const diskModel = winDiskModel(row);
    const diskType = winDiskType(row);
    const diskGb = winDiskGb(row);
    const diskSerial = winDiskSerial(row);
    const manufacturer = winText(row.manufacturer) || '-';
    const model = winText(row.model) || '-';
    const statusText = online ? 'online' : (winText(row.status) || 'offline');
    return `
      <tr class="win-row" data-key="${esc(key)}">
        <td><input type="checkbox" class="chk-win" value="${esc(key)}" ${_winSelected.has(key) ? 'checked' : ''}></td>
        <td class="monospace" title="${esc(row.ip || '-')}">${esc(row.ip || '-')}</td>
        <td class="monospace text-muted" title="${esc(row.mac || '-')}">${esc(row.mac || '-')}</td>
        <td title="${esc(row.hostname || '-')}"><strong>${esc(row.hostname || '-')}</strong></td>
        <td class="text-muted" title="${esc(winUserLabel(row))}">${esc(winUserLabel(row))}</td>
        <td class="text-muted" title="${esc(winOsLabel(row))}">${esc(winOsLabel(row))}</td>
        <td class="text-muted" title="${esc(manufacturer)}">${esc(manufacturer)}</td>
        <td class="text-muted" title="${esc(model)}">${esc(model)}</td>
        <td title="${esc(row.site || '-')}">${esc(row.site || '-')}</td>
        <td class="text-muted" title="${esc(row.sector || row.setor || '-')}">${esc(row.sector || row.setor || '-')}</td>
        <td title="${esc(row.error || statusText)}"><span style="color:${online ? 'var(--primary)' : 'var(--danger)'};font-weight:700">${esc(statusText)}</span></td>
        <td class="text-muted" title="${esc(winCpuLabel(row))}">${esc(winCpuLabel(row))}</td>
        <td class="text-muted" title="${esc(winRamLabel(row))}">${esc(winRamLabel(row))}</td>
        <td class="text-muted" title="${esc(diskModel)}">${esc(diskModel)}</td>
        <td class="text-muted" title="${esc(winDiskLabel(row))}">${esc(diskType)}</td>
        <td class="text-muted" title="${esc(winDiskLabel(row))}">${esc(diskGb)}</td>
        <td class="text-muted monospace" title="${esc(diskSerial)}">${esc(diskSerial)}</td>
        <td>${anydesk ? `<a href="anydesk:${encodeURIComponent(anydesk)}" class="monospace" style="color:var(--primary);font-weight:700">${esc(anydesk)}</a>` : '<span class="text-muted">-</span>'}</td>
        <td class="text-muted" title="${esc(physical.switch_name || '-')}">${esc(physical.switch_name || '-')}</td>
        <td class="text-muted" title="${esc(physical.switch_port || '-')}">${esc(physical.switch_port || '-')}</td>
        <td class="text-muted" title="${esc(physical.patch_panel || '-')}">${esc(physical.patch_panel || '-')}</td>
        <td class="text-muted" title="${esc(physical.patch_port || '-')}">${esc(physical.patch_port || '-')}</td>
        <td class="text-muted" title="${esc(physical.outlet || '-')}">${esc(physical.outlet || '-')}</td>
        <td class="text-muted" title="${esc(physical.rack || '-')}">${esc(physical.rack || '-')}</td>
        <td class="text-muted" title="${esc(physical.cable_id || '-')}">${esc(physical.cable_id || '-')}</td>
        <td class="text-muted" title="${esc(physical.asset_tag || '-')}">${esc(physical.asset_tag || '-')}</td>
        <td class="text-muted" title="${esc(physical.notes || '-')}">${esc(physical.notes || '-')}</td>
      </tr>`;
  }).join('');
  setText('invWindowsFooter', `${rows.length} host${rows.length === 1 ? '' : 's'}`);
  tbody.querySelectorAll('.chk-win').forEach(chk => {
    chk.addEventListener('click', e => e.stopPropagation());
    chk.addEventListener('change', () => {
      if (chk.checked) _winSelected.add(chk.value); else _winSelected.delete(chk.value);
      updateWinSelectionUi();
    });
  });
  tbody.querySelectorAll('.win-row').forEach(tr => tr.addEventListener('click', () => {
    const row = _winRows.find(r => winKey(r) === tr.dataset.key);
    if (row) openWinPanel(row);
  }));
  updateWinSelectionUi();
}
function applyWindowsFilters() {
  _winFilteredRows = _winRows.filter(winMatchesFilter);
  renderWinRows(_winFilteredRows);
}
async function loadInvWindows() {
  const data = await apiJson('/api/windows/inventory');
  _winRows = data?.inventory || data?.hosts || (Array.isArray(data) ? data : []);
  _winRows.sort((a,b) => ipToInt(a.ip) - ipToInt(b.ip));
  _winSelected = new Set([..._winSelected].filter(key => _winRows.some(r => winKey(r) === key)));
  updateWinSummary();
  populateWinFilters();
  applyWindowsFilters();
}
function clearWinFilters() {
  ['searchInvWindows','filterWinStatus','filterWinSite','filterWinSector'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  _winSelected.clear();
  applyWindowsFilters();
}
function openWinScanModal() {
  document.getElementById('winScanErro').hidden = true;
  document.getElementById('winScanLog').textContent = 'Aguardando inicio...';
  document.getElementById('modalWinScan')?.classList.remove('hidden');
  setTimeout(() => document.getElementById('winScanTargets')?.focus(), 80);
  lucide.createIcons();
}
function closeWinScanModal() { document.getElementById('modalWinScan')?.classList.add('hidden'); }
async function runWinScan() {
  const erro = document.getElementById('winScanErro');
  const log = document.getElementById('winScanLog');
  const btn = document.getElementById('startWinScan');
  const payload = {
    targets: document.getElementById('winScanTargets').value.trim(),
    username: document.getElementById('winScanUser').value.trim(),
    password: document.getElementById('winScanPass').value,
    domain: document.getElementById('winScanDomain').value.trim(),
    timeout_sec: Number(document.getElementById('winScanTimeout').value || 8),
    concurrency: Number(document.getElementById('winScanConcurrency').value || 32),
    use_https: document.getElementById('winScanHttps').checked,
    save: true,
  };
  if (!payload.targets || !payload.username || !payload.password) {
    erro.textContent = 'Informe alvo, usuario e senha.';
    erro.hidden = false;
    return;
  }
  erro.hidden = true;
  log.textContent = `Conectando em ${payload.targets}...`;
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-2"></i> Executando';
  lucide.createIcons();
  try {
    const res = await api('/api/windows/scan', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) throw new Error(data?.detail || data?.error || 'Falha na varredura.');
    log.textContent = `Concluido. Alvos: ${data.scanned || 0}. Online: ${data.online || 0}. Falhas: ${data.failed || 0}.`;
    showToast(`Windows atualizado: ${data.online || 0} online, ${data.failed || 0} falha(s).`);
    await loadInvWindows();
  } catch (err) {
    erro.textContent = err.message || 'Falha na varredura.';
    erro.hidden = false;
    log.textContent += `\nErro: ${erro.textContent}`;
    showToast(erro.textContent, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i data-lucide="scan-search"></i> Executar';
    lucide.createIcons();
  }
}
function winSetPanelText(id, value) {
  setText(id, winText(value) || '-');
}
function winFormatDate(value) {
  const raw = winText(value);
  if (!raw) return '-';
  const d = new Date(raw);
  if (Number.isNaN(d.getTime())) return raw;
  return d.toLocaleString('pt-BR');
}
function openWinPanel(row) {
  _winActive = row;
  const key = winKey(row);
  document.querySelectorAll('.win-row').forEach(tr => tr.classList.toggle('row-selected', tr.dataset.key === key));
  const online = winIsOnline(row);
  const status = document.getElementById('winPanelStatus');
  if (status) {
    status.textContent = online ? 'online' : (winText(row.status) || 'offline');
    status.style.color = online ? 'var(--primary)' : 'var(--danger)';
  }
  winSetPanelText('winPanelTitle', row.hostname || row.ip || 'Windows');
  winSetPanelText('wpIp', row.ip);
  winSetPanelText('wpMac', row.mac);
  winSetPanelText('wpUser', winUserLabel(row));
  winSetPanelText('wpOs', winOsLabel(row));
  winSetPanelText('wpManufacturer', row.manufacturer);
  winSetPanelText('wpModel', row.model);
  winSetPanelText('wpSerial', row.serial);
  winSetPanelText('wpSite', row.site);
  winSetPanelText('wpSector', row.sector || row.setor);
  winSetPanelText('wpCpu', winCpuLabel(row));
  winSetPanelText('wpMemory', winRamLabel(row));
  winSetPanelText('wpDisk', [winDiskModel(row), winDiskType(row), winDiskGb(row) !== '-' ? `${winDiskGb(row)} GB` : '', winDiskSerial(row)].filter(v => v && v !== '-').join(' / '));
  winSetPanelText('wpAnydesk', row.anydesk_id);
  winSetPanelText('wpUpdated', winFormatDate(row.updated_at || row.last_seen));
  const p = winPhysical(row);
  winSetPanelText('wpSwitch', p.switch_name);
  winSetPanelText('wpSwitchPort', p.switch_port);
  winSetPanelText('wpPatch', p.patch_panel);
  winSetPanelText('wpPatchPort', p.patch_port);
  winSetPanelText('wpOutlet', p.outlet);
  winSetPanelText('wpRack', p.rack);
  winSetPanelText('wpCable', p.cable_id);
  winSetPanelText('wpAsset', p.asset_tag);
  winSetPanelText('wpNotes', p.notes);
  document.getElementById('wpBtnAnydesk')?.toggleAttribute('disabled', !winText(row.anydesk_id));
  document.getElementById('winPanelBackdrop')?.classList.remove('hidden');
  document.getElementById('winPanel')?.classList.remove('hidden');
  lucide.createIcons();
}
function closeWinPanel() {
  _winActive = null;
  document.getElementById('winPanelBackdrop')?.classList.add('hidden');
  document.getElementById('winPanel')?.classList.add('hidden');
  document.querySelectorAll('.win-row').forEach(tr => tr.classList.remove('row-selected'));
}
function winPanelAction(action) {
  if (!_winActive && !['agent','prepare','pdf','refresh'].includes(action)) return;
  if (action === 'ping') return openPingTerminal(_winActive.ip);
  if (action === 'anydesk') {
    const id = winText(_winActive.anydesk_id);
    if (!id) return showToast('Este computador nao tem AnyDesk informado.', true);
    window.open(`anydesk:${encodeURIComponent(id)}`, '_blank');
    return;
  }
  if (action === 'edit') {
    const key = winKey(_winActive);
    _winSelected = new Set([key]);
    applyWindowsFilters();
    openWinPhysicalModal();
    return;
  }
  if (action === 'agent') return downloadWithAuth('/api/windows/agent-script', 'sightops-agente-windows.ps1');
  if (action === 'prepare') return downloadWithAuth('/api/windows/prepare-script', 'sightops-preparar-windows.ps1');
  if (action === 'pdf') return downloadWithAuth('/api/windows/report.pdf', 'windows-inventory.pdf');
  if (action === 'refresh') return loadInvWindows();
}
function selectedWinRows() {
  return _winRows.filter(r => _winSelected.has(winKey(r)));
}
function openWinPhysicalModal() {
  const rows = selectedWinRows();
  if (!rows.length) { showToast('Selecione um computador para editar.', true); return; }
  const row = rows[0];
  _winEditingKey = winKey(row);
  const p = winPhysical(row);
  setText('winPhysicalTitle', `Editar - ${row.hostname || row.ip || 'computador'}`);
  const map = {
    SwitchName: p.switch_name,
    SwitchPort: p.switch_port,
    PatchPanel: p.patch_panel,
    PatchPort: p.patch_port,
    Outlet: p.outlet,
    Rack: p.rack,
    CableId: p.cable_id,
    AssetTag: p.asset_tag,
    Notes: p.notes,
  };
  Object.entries(map).forEach(([k,v]) => { const el = document.getElementById(`winPhysical${k}`); if (el) el.value = winText(v); });
  document.getElementById('winPhysicalErro').hidden = true;
  document.getElementById('modalWinPhysical')?.classList.remove('hidden');
  lucide.createIcons();
}
function closeWinPhysicalModal() { document.getElementById('modalWinPhysical')?.classList.add('hidden'); }
async function saveWinPhysical() {
  if (!_winEditingKey) return;
  const erro = document.getElementById('winPhysicalErro');
  const btn = document.getElementById('saveWinPhysical');
  const physical = {
    switch_name: document.getElementById('winPhysicalSwitchName').value.trim(),
    switch_port: document.getElementById('winPhysicalSwitchPort').value.trim(),
    patch_panel: document.getElementById('winPhysicalPatchPanel').value.trim(),
    patch_port: document.getElementById('winPhysicalPatchPort').value.trim(),
    outlet: document.getElementById('winPhysicalOutlet').value.trim(),
    rack: document.getElementById('winPhysicalRack').value.trim(),
    cable_id: document.getElementById('winPhysicalCableId').value.trim(),
    asset_tag: document.getElementById('winPhysicalAssetTag').value.trim(),
    notes: document.getElementById('winPhysicalNotes').value.trim(),
  };
  btn.disabled = true;
  try {
    const res = await api('/api/windows/inventory/manual', { method: 'PATCH', body: JSON.stringify({ key: _winEditingKey, physical }) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) throw new Error(data?.detail || data?.error || 'Falha ao salvar.');
    showToast('Caminho fisico salvo.');
    closeWinPhysicalModal();
    await loadInvWindows();
  } catch (err) {
    erro.textContent = err.message || 'Falha ao salvar.';
    erro.hidden = false;
    showToast(erro.textContent, true);
  } finally {
    btn.disabled = false;
  }
}
async function deleteSelectedWindows() {
  const keys = [..._winSelected];
  if (!keys.length) { showToast('Selecione ao menos um computador.', true); return; }
  if (!await showConfirm({ title: 'Remover computadores', msg: `Remover ${keys.length} computador(es) do inventario Windows?`, label: 'Remover' })) return;
  const res = await api('/api/windows/inventory/delete', { method: 'POST', body: JSON.stringify({ keys }) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) { showToast(data?.detail || data?.error || 'Falha ao remover.', true); return; }
  _winSelected.clear();
  showToast(`${data.removed || keys.length} computador(es) removido(s).`);
  await loadInvWindows();
}
async function clearWindowsInventory() {
  if (!await showConfirm({ title: 'Apagar inventario Windows', msg: 'Apagar todos os computadores Windows salvos?', label: 'Apagar tudo' })) return;
  const res = await api('/api/windows/clear', { method: 'POST', body: '{}' });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) { showToast(data?.detail || data?.error || 'Falha ao limpar.', true); return; }
  _winRows = [];
  _winSelected.clear();
  updateWinSummary();
  populateWinFilters();
  applyWindowsFilters();
  showToast('Inventario Windows limpo.');
}
async function enrichWindowsPhotos() {
  showToast('Buscando fotos de referencia...');
  const res = await api('/api/windows/enrich/photos', { method: 'POST', body: '{}' });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) { showToast(data?.detail || data?.error || 'Falha ao buscar fotos.', true); return; }
  showToast(`Fotos vinculadas: ${data.assets || 0}.`);
  await loadInvWindows();
}
// Snapshots 
let _snapCamAll = [];

async function loadSnapCam() {
  // /api/cameras sozinho so devolve o modo OLT -- busca os 3 modos e
  // mescla por chave, senao cameras cadastradas so em Basico/Switch nunca
  // aparecem aqui (mesmo tendo snapshot).
  const [basico, olt, sw] = await Promise.all([
    apiJson('/api/cameras?mode=basico').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=olt').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=switch').catch(() => ({ cameras: [] })),
  ]);
  const merged = new Map();
  [basico, olt, sw].forEach(data => {
    (data?.cameras || []).forEach(c => {
      const key = c.inventory_key || c.ip;
      if (key && !merged.has(key)) merged.set(key, c);
    });
  });
  _snapCamAll = [...merged.values()]
    .sort((a, b) => {
      const toInt = ip => (ip||'0.0.0.0').split('.').reduce((a,b) => (a<<8)|(parseInt(b)||0), 0) >>> 0;
      return toInt(a.ip) - toInt(b.ip);
    });

  // Popula filtro de sites
  const sites = [...new Set(_snapCamAll.map(c => c.local).filter(Boolean))].sort();
  const selSite = document.getElementById('filterSnapCamSite');
  if (selSite) {
    const cur = selSite.value;
    selSite.innerHTML = '<option value="">Todos os sites</option>' +
      sites.map(s => `<option${s===cur?' selected':''}>${esc(s)}</option>`).join('');
  }

  applySnapCamFilters();
}

function applySnapCamFilters() {
  const q      = (document.getElementById('searchSnapCam')?.value || '').toLowerCase();
  const status = document.getElementById('filterSnapCamStatus')?.value || '';
  const site   = document.getElementById('filterSnapCamSite')?.value   || '';

  const filtered = _snapCamAll.filter(c => {
    const temFoto = !!(c.snapshot_url);
    if (status === 'com' && !temFoto) return false;
    if (status === 'sem' && temFoto)  return false;
    if (site && c.local !== site)     return false;
    if (q) return [c.ip, c.titulo, c.local, c.model, c.fabricante]
      .some(f => (f||'').toLowerCase().includes(q));
    return true;
  });

  // Contadores
  setText('snapCamTotal',   _snapCamAll.length);
  setText('snapCamComFoto', _snapCamAll.filter(c => c.snapshot_url).length);
  setText('snapCamSemFoto', _snapCamAll.filter(c => !c.snapshot_url).length);

  renderSnapCamGrid(filtered);
}
