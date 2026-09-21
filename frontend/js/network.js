function updateOltOriginUi() {
  const sel = document.getElementById('oltConnector');
  const site = (document.getElementById('oltSite')?.value || document.getElementById('oltFilterSite')?.value || '').trim();
  const context = _networkContextForSite(site, sel?.value || '');
  const origin = context.connectorId ? 'connector' : 'local';
  const originEl = document.getElementById('oltOrigin');
  if (originEl) originEl.value = origin;
  const status = document.getElementById('oltConnectorStatus');
  if (sel) sel.disabled = false;

  if (origin !== 'connector') {
    if (status) status.innerHTML = 'Sem conector para este site: usando servidor local/VPN ja roteada.';
    return;
  }

  if (status) {
    status.innerHTML = context.online
      ? `<span style="color:var(--primary);font-weight:700">Online</span> -- ${esc(_connectorLabel(context.connector))}${context.hasTunnel ? ' -- VPN configurada para coleta real' : ' -- configure a VPN antes da coleta da OLT'}`
      : `<span style="color:var(--danger);font-weight:700">Offline</span> -- conector indisponivel.`;
  }
  const siteEl = document.getElementById('oltSite');
  if (context.connector?.site && siteEl && !siteEl.value.trim()) siteEl.value = context.connector.site;
}

// 4840E e EPON com 4 portas PON fisicas; os demais modelos suportados (8820i,
// 8840E) sao GPON de 8 portas. Sem isso o select fica preso no default de 8
// mesmo pra OLT que so tem 4.
function _oltPonCountForModel(model) {
  const m = String(model || '').trim().toLowerCase();
  if (m === '4840e' || m === '4840' || m.includes('4840e')) return 4;
  return 8;
}

function updateOltPonOptions() {
  const modelEl = document.getElementById('oltModel');
  const ponEl = document.getElementById('oltPon');
  if (!ponEl) return;
  const total = _oltPonCountForModel(modelEl?.value);
  const previous = ponEl.value;
  const options = ['<option value="all">TODAS</option>'];
  for (let p = 1; p <= total; p += 1) options.push(`<option value="${p}">PON ${p}</option>`);
  ponEl.innerHTML = options.join('');
  ponEl.value = [...ponEl.options].some(opt => opt.value === previous) ? previous : 'all';
}

function openOltCollectModal() {
  document.getElementById('modalOltCollect')?.classList.remove('hidden');
  const siteEl = document.getElementById('oltSite');
  const currentSite = document.getElementById('oltFilterSite')?.value || '';
  if (siteEl && currentSite && !siteEl.value.trim()) siteEl.value = currentSite;
  refreshOltConnectors().finally(updateOltOriginUi);
  const modelEl = document.getElementById('oltModel');
  if (modelEl && !modelEl.dataset.oltPonBound) {
    modelEl.dataset.oltPonBound = '1';
    modelEl.addEventListener('change', updateOltPonOptions);
  }
  updateOltPonOptions();
  lucide.createIcons();
}

async function oltCollect() {
  const ip   = document.getElementById('oltIp')?.value.trim();
  const user = document.getElementById('oltUser')?.value.trim() || 'admin';
  const pass = document.getElementById('oltPassword')?.value;
  const site = document.getElementById('oltSite')?.value.trim();
  const pon  = document.getElementById('oltPon')?.value || 'all';
  const model= document.getElementById('oltModel')?.value || '8820i';
  const reuse= document.getElementById('oltReuse')?.checked || false;
  const context = _networkContextForSite(site, document.getElementById('oltConnector')?.value || '');
  const origin = context.connectorId ? 'connector' : 'local';
  const connectorId = context.connectorId;

  if (!ip) { showToast('Informe o IP da OLT', true); return; }
  if (origin === 'connector') {
    if (!context.online) {
      showToast('O conector selecionado esta offline.', true);
      return;
    }
    if (!context.hasTunnel) {
      showToast('Prepare a VPN do conector antes de coletar OLT remota.', true);
      return;
    }
  }

  // Abre terminal
  const term = document.getElementById('oltTerminal');
  const cons = document.getElementById('oltConsole');
  if (term) term.classList.remove('hidden');
  if (cons) cons.innerHTML = '';
  setText('oltTermTitle', `OLT  ${ip}`);
  setText('oltTermFooter', 'Iniciando');
  lucide.createIcons();

  // Conecta no WS de console (mantem vivo + recebe acks)
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  let ws = null;
  try {
    ws = new WebSocket(`${wsProto}://${location.host}/ws/olt-console`);
    ws.onopen = () => {};
    ws.onmessage = (e) => {
      try {
        const m = JSON.parse(e.data);
        if (m.type === 'status' || m.type === 'log') {
          oltConsoleLog(m.message, 'info');
        }
      } catch {}
    };
  } catch {}

  // Mensagem inicial honesta -- nao ha como saber de verdade em que ponto da
  // coleta a OLT esta (nenhum log real chega em tempo real, so o ticker de
  // tempo decorrido abaixo). Antes disso havia uma sequencia de mensagens
  // com tempos fixos ("PON 2 encontrada...") que disparava sozinha via
  // setTimeout, sem relacao nenhuma com o que a OLT estava realmente
  // fazendo -- inclusive continuava "progredindo" se a OLT tivesse travado.
  const ponLabel = pon === 'all' ? 'TODAS as PONs' : `PON ${pon}`;
  oltConsoleLog(
    `[INFO] Conectando em ${ip}${site ? ` [site: ${site}]` : ''}${origin === 'connector' ? ' via VPN do conector' : ''}, coletando ${ponLabel}...`,
    'info',
  );
  const timers = [];

  // Ticker "ainda trabalhando"
  let tick = 0;
  const tickTimer = setInterval(() => {
    tick++;
    setText('oltTermFooter', `Coletando via SSH ${tick}s`);
  }, 1000);

  const payload = {
    olt_ip: ip,
    user,
    password: pass,
    pon,
    olt_model: model,
    reuse_json: reuse,
    scan_origin: origin,
    connector_id: origin === 'connector' ? connectorId : '',
    remote_connector_id: origin === 'connector' ? connectorId : '',
    ...(site && { site }),
  };

  try {
    const res = await api('/api/olt/collect-macs', { method: 'POST', body: JSON.stringify(payload), skipLogout: true });
    timers.forEach(t => clearTimeout(t));
    clearInterval(tickTimer);
    if (ws) { try { ws.close(); } catch {} }

    if (res?.ok) {
      const data = await res.json();
      const total = data?.count ?? data?.total ?? (Array.isArray(data?.rows) ? data.rows.length : null) ?? '?';
      oltConsoleLog('[INFO] Salvando base OLT no banco...', 'info');
      oltConsoleLog(`[OK] Coleta concluida! Total: ${total} registros.`, 'ok');
      setText('oltTermFooter', `Concluido  ${total} registros`);
      loadOlt();
    } else {
      const err = await res?.json().catch(() => ({}));
      oltConsoleLog('[ERRO] ' + (err?.detail || 'Falha na coleta.'), 'err');
      setText('oltTermFooter', 'Erro na coleta.');
    }
  } catch (e) {
    timers.forEach(t => clearTimeout(t));
    clearInterval(tickTimer);
    if (ws) { try { ws.close(); } catch {} }
    oltConsoleLog('[ERRO] ' + (e.message || 'Erro de conexao.'), 'err');
    setText('oltTermFooter', 'Erro.');
  }
}

let _switchRows = [];
let _switchCamByMac = {};
let _switchPlatform = '';

async function loadSwitch() {
  // /api/cameras sozinho so devolve o modo OLT -- busca os 3 modos pro
  // cruzamento MAC->camera, senao cameras cadastradas so em Basico/Switch
  // aparecem como se a porta nao tivesse camera nenhuma.
  const [swData, camBasico, camOlt, camSwitch] = await Promise.all([
    apiJson('/api/switch/rows'),
    apiJson('/api/cameras?mode=basico').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=olt').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=switch').catch(() => ({ cameras: [] })),
  ]);
  const rawRows = swData?.rows || (Array.isArray(swData) ? swData : []);
  const ports = swData?.ports || [];
  _switchPlatform = swData?.switch?.platform || '';

  const portInfoByKey = {};
  ports.forEach(p => { portInfoByKey[`${p.switch_ip || ''}|${p.port || ''}`] = p; });

  // MACs aprendidos na porta uplink sao de equipamentos atras do switch (outra
  // rede/segmento), nao ligados fisicamente nela -- fora da tabela por completo
  // (inclusive nao vira linha "vazia": a porta uplink tem trafego real).
  const uplinkPorts = new Set(
    rawRows.filter(r => r.port_role_guess === 'uplink').map(r => `${r.switch_ip || ''}|${r.port || ''}`)
  );
  const edgeRows = rawRows.filter(r => r.port_role_guess !== 'uplink');

  // Portas sem nenhum MAC aprendido nao aparecem no mac_table (nada circulou
  // por elas) -- usamos a lista de portas fisicas coletada junto pra mostrar
  // essas tambem. Switch nao tem MAC por porta, entao usamos o MAC fisico do
  // proprio aparelho (dado real) em vez de um texto generico.
  const withRow = new Set(edgeRows.map(r => `${r.switch_ip || ''}|${r.port || ''}`));
  const emptyPortRows = ports
    .filter(p => p.port && !withRow.has(`${p.switch_ip || ''}|${p.port || ''}`) && !uplinkPorts.has(`${p.switch_ip || ''}|${p.port || ''}`))
    .map(p => ({
      site: p.site, switch_ip: p.switch_ip, switch_name: p.switch_name,
      port: p.port, mac: p.switch_mac || '', vlan: '', entry_type: '', port_role_guess: 'edge',
      _linkUp: !!p.up, _synthetic: true,
    }));

  _switchRows = [...edgeRows, ...emptyPortRows].map(r => {
    const info = portInfoByKey[`${r.switch_ip || ''}|${r.port || ''}`] || {};
    return {
      ...r,
      port_id: info.port_id,
      bandwidth: info.bandwidth || '',
      duplex: info.duplex || '',
      poe_enabled: info.poe_enabled,
      poe_power_watts: info.poe_power_watts,
      admin_enabled: info.admin_enabled,
    };
  });

  _switchCamByMac = {};
  [camBasico, camOlt, camSwitch].forEach(camData => {
    const cams = camData?.cameras || (Array.isArray(camData) ? camData : []);
    cams.forEach(c => { if (c.mac) _switchCamByMac[String(c.mac).toLowerCase()] = c; });
  });

  populateSwitchFilters();
  renderSwitchTable(_switchRows);
}

function populateSwitchFilters() {
  const sites = [...new Set(_switchRows.map(r => r.site).filter(Boolean))].sort();
  const selSite = document.getElementById('switchFilterSite');
  const selDevice = document.getElementById('switchFilterDevice');
  if (selSite) {
    const cur = selSite.value;
    selSite.innerHTML = '<option value="">Todos os sites</option>' +
      sites.map(s => `<option${s === cur ? ' selected' : ''}>${esc(s)}</option>`).join('');
  }
  if (selDevice) {
    // Chave pelo IP (unico) -- switches com o mesmo modelo/nome (ou sem nome
    // definido no coletar) ficariam indistinguiveis se a chave fosse so o nome.
    const byIp = new Map();
    _switchRows.forEach(r => {
      const ip = r.switch_ip || '';
      if (!ip || byIp.has(ip)) return;
      const label = r.switch_name && r.switch_name !== ip ? `${r.switch_name} (${ip})` : ip;
      byIp.set(ip, label);
    });
    const devices = [...byIp.entries()].sort((a, b) => a[1].localeCompare(b[1]));
    const cur = selDevice.value;
    selDevice.innerHTML = '<option value="">Todos os switches</option>' +
      devices.map(([ip, label]) => `<option value="${esc(ip)}"${ip === cur ? ' selected' : ''}>${esc(label)}</option>`).join('');
  }
}

function renderSwitchTable(rows) {
  const tbody = document.getElementById('switchTable');
  if (!tbody) return;

  const withMac = rows.filter(r => !r._synthetic);
  const switches = new Set(rows.map(r => String(r.switch_ip || r.switch_name || '').trim()).filter(Boolean));
  const sites = new Set(rows.map(r => String(r.site || '').trim()).filter(Boolean));
  const activePorts = new Set(withMac.map(r => `${r.switch_ip || ''}|${r.port || ''}`).filter(k => k !== '|'));
  setText('switchCount', switches.size);
  setText('switchPortCount', activePorts.size);
  setText('switchMacTotal', withMac.length);
  setText('switchSiteCount', sites.size);
  setText('switchFooter', `${rows.length} registro${rows.length !== 1 ? 's' : ''}`);

  if (!rows.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="10">Nenhum dado. Execute a coleta.</td></tr>';
    return;
  }

  const canToggle = _switchPlatform === 'hikvision';

  const cellNowrap = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap';

  tbody.innerHTML = rows.map(r => {
    const isEmpty = !!r._synthetic;
    const cam = isEmpty ? null : _switchCamByMac[String(r.mac || '').toLowerCase()];
    const speed = [r.bandwidth, r.duplex].filter(Boolean).join(' / ');
    const switchLabel = r.switch_name || r.switch_ip || '';

    let poeCell = '<span class="text-muted">-</span>';
    if (r.poe_enabled === true) {
      const watts = r.poe_power_watts != null ? `${Number(r.poe_power_watts).toFixed(1)}W` : 'ligado';
      poeCell = `<span class="badge badge-green">${esc(watts)}</span>`;
    } else if (r.poe_enabled === false) {
      poeCell = '<span class="badge badge-gray">desligado</span>';
    }

    // Vermelho = estado atual ligado (apertar desliga); verde = estado atual
    // desligado (apertar liga) -- a cor do botao mostra o que vai acontecer.
    const btnStyle = 'width:26px;height:26px';
    const actions = [];
    if (cam?.ip) {
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="ping" data-ip="${esc(cam.ip)}" title="Testar ping" style="${btnStyle}"><i data-lucide="activity"></i></button>`);
    }
    if (canToggle && r.port_id != null && r.poe_enabled !== undefined && r.poe_enabled !== null) {
      const poeOn = r.poe_enabled === true;
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="poe" data-switch-ip="${esc(r.switch_ip || '')}" data-site="${esc(r.site || '')}" data-port="${esc(r.port || '')}" data-enabled="${poeOn ? '0' : '1'}" title="${poeOn ? 'Desligar PoE' : 'Ligar PoE'}" style="${btnStyle};color:${poeOn ? 'var(--danger)' : 'var(--primary)'}"><i data-lucide="zap"></i></button>`);
    }
    if (canToggle && r.port_id != null) {
      const portOn = r.admin_enabled !== false;
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="port" data-switch-ip="${esc(r.switch_ip || '')}" data-site="${esc(r.site || '')}" data-port="${esc(r.port || '')}" data-enabled="${portOn ? '0' : '1'}" title="${portOn ? 'Desativar porta' : 'Ativar porta'}" style="${btnStyle};color:${portOn ? 'var(--danger)' : 'var(--primary)'}"><i data-lucide="power"></i></button>`);
    }
    const actionsHtml = actions.length
      ? `<div style="display:flex;gap:4px;align-items:center;justify-content:center">${actions.join('')}</div>`
      : '<span class="text-muted">-</span>';

    return `
    <tr${isEmpty ? ' style="opacity:.65"' : ''}>
      <td class="text-muted monospace" style="white-space:nowrap">${esc(r.port || '')}</td>
      <td class="monospace" style="white-space:nowrap">${r.mac ? esc(r.mac) : '<span class="text-muted">-</span>'}</td>
      <td class="text-muted" style="text-align:center;white-space:nowrap">${isEmpty ? '-' : esc(r.vlan || 'default')}</td>
      <td class="text-muted" style="white-space:nowrap">${isEmpty ? (r._linkUp ? 'conectado' : 'sem cabo') : esc(r.entry_type || '')}</td>
      <td class="text-muted" style="${cellNowrap}" title="${esc(switchLabel)}">${esc(switchLabel)}</td>
      <td class="text-muted monospace" style="white-space:nowrap">${esc(r.switch_ip || '')}</td>
      <td class="text-muted" style="white-space:nowrap">${speed ? esc(speed) : '<span class="text-muted">-</span>'}</td>
      <td style="white-space:nowrap">${poeCell}</td>
      <td class="text-muted" style="${cellNowrap}" title="${esc(r.site || '')}">${esc(r.site || '')}</td>
      <td style="white-space:nowrap;text-align:center">${actionsHtml}</td>
    </tr>`;
  }).join('');
  lucide.createIcons();
}

async function switchPortAction(el) {
  const action = el.dataset.action;
  if (action === 'ping') {
    openPingTerminal(el.dataset.ip);
    return;
  }

  const switchIp = el.dataset.switchIp;
  const site = el.dataset.site;
  const port = el.dataset.port;
  const enabled = el.dataset.enabled === '1';

  const labels = {
    poe: enabled ? 'ligar o PoE' : 'desligar o PoE',
    port: enabled ? 'ativar a porta' : 'desativar a porta',
  };
  const ok = await showConfirm({
    eyebrow: 'Switch',
    title: `Confirmar acao na porta ${port}`,
    msg: `Isso vai ${labels[action]} da porta ${port}. Se houver um equipamento ligado nela, pode ficar offline. Continuar?`,
    label: 'Confirmar',
  });
  if (!ok) return;

  const path = action === 'poe' ? '/api/switch/port/poe' : '/api/switch/port/enabled';
  try {
    const res = await api(path, {
      method: 'POST',
      body: JSON.stringify({ switch_ip: switchIp, site, port, enabled }),
    });
    const data = await res?.json().catch(() => ({}));
    if (res?.ok) {
      showToast('Acao aplicada.');
      loadSwitch();
    } else {
      showToast(data?.detail || data?.error || 'Falha ao aplicar acao.', true);
    }
  } catch (e) {
    showToast(e.message || 'Erro de conexao com o switch.', true);
  }
}

function filterSwitchTable() {
  const site = document.getElementById('switchFilterSite')?.value || '';
  const device = document.getElementById('switchFilterDevice')?.value || '';
  const status = document.getElementById('switchFilterStatus')?.value || '';
  const q = (document.getElementById('switchSearch')?.value || '').toLowerCase();
  const filtered = _switchRows.filter(r => {
    if (site && r.site !== site) return false;
    if (device && r.switch_ip !== device) return false;
    if (status === 'active' && r._synthetic) return false;
    if (status === 'down' && !(r._synthetic && !r._linkUp)) return false;
    if (status === 'disabled' && r.admin_enabled !== false) return false;
    if (q) {
      const cam = _switchCamByMac[String(r.mac || '').toLowerCase()];
      return [r.site, r.switch_name, r.switch_ip, r.port, r.mac, r.vlan, r.entry_type, cam?.titulo, cam?.local]
        .some(f => (f || '').toString().toLowerCase().includes(q));
    }
    return true;
  });
  renderSwitchTable(filtered);
}

async function refreshSwitchConnectors() {
  const sel = document.getElementById('switchConnector');
  if (!sel) return;
  try {
    const data = await apiJson('/api/connectors');
    _connectors = Array.isArray(data?.connectors) ? data.connectors : (_connectors || []);
  } catch {
    _connectors = _connectors || [];
  }
  const rows = _routerConnectors();
  const current = sel.value;
  sel.innerHTML = '<option value="">Opcional: usar servidor local/VPN</option>' + rows.map(c => {
    const online = _connectorIsOnline(c);
    const tunnel = _connectorHasTunnel(c) ? ' + VPN' : '';
    return `<option value="${esc(c.id || '')}" ${online ? '' : 'disabled'}>${esc(_connectorLabel(c))}${tunnel}${online ? '' : ' (offline)'}</option>`;
  }).join('');

  const site = document.getElementById('switchSite')?.value.trim() || '';
  const match = current ? _connectorById(current) : _findConnectorForSite(site);
  if (match?.id) sel.value = match.id;
}

function updateSwitchConnectorUi() {
  const site = document.getElementById('switchSite')?.value.trim() || '';
  const connectorId = document.getElementById('switchConnector')?.value || '';
  const context = _networkContextForSite(site, connectorId);
  const status = document.getElementById('switchConnectorStatus');
  if (status) {
    status.innerHTML = context.connectorId
      ? `${context.online ? '<b style="color:var(--primary)">Conector online</b>' : '<b style="color:var(--danger)">Conector offline</b>'} -- ${esc(_connectorLabel(context.connector))}${context.hasTunnel ? ' -- VPN configurada.' : ' -- configure a VPN antes de coletar remoto.'}`
      : 'Sem conector para este site: usando servidor local/VPN ja roteada.';
  }
  const siteEl = document.getElementById('switchSite');
  if (context.connector?.site && siteEl && !siteEl.value.trim()) siteEl.value = context.connector.site;
  return context;
}

function openSwitchCollectModal() {
  document.getElementById('modalSwitchCollect')?.classList.remove('hidden');
  refreshSwitchConnectors().finally(updateSwitchConnectorUi);
  lucide.createIcons();
}

function closeSwitchCollectModal() {
  document.getElementById('modalSwitchCollect')?.classList.add('hidden');
}

async function switchCollect() {
  const platform = document.getElementById('switchPlatform')?.value || 'intelbras';
  const switch_ip = document.getElementById('switchIp')?.value.trim() || '';
  const switch_name = document.getElementById('switchName')?.value.trim() || '';
  const site = document.getElementById('switchSite')?.value.trim() || '';
  const user = document.getElementById('switchUser')?.value.trim() || 'admin';
  const password = document.getElementById('switchPassword')?.value || '';
  const reuse_json = document.getElementById('switchReuse')?.checked || false;
  const connectorId = document.getElementById('switchConnector')?.value || '';
  const context = _networkContextForSite(site, connectorId);

  if (!switch_ip) { showToast('Informe o IP do switch', true); return; }
  if (!password) { showToast('Informe a senha do switch', true); return; }
  if (context.connectorId) {
    if (!context.online) { showToast('O conector selecionado esta offline.', true); return; }
    if (!context.hasTunnel) { showToast('Configure a VPN do conector antes de coletar remoto.', true); return; }
  }

  const btn = document.getElementById('btnSwitchStart');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader-circle"></i> Coletando'; lucide.createIcons(); }

  try {
    const res = await api('/api/switch/collect-macs', {
      method: 'POST',
      body: JSON.stringify({ platform, switch_ip, switch_name, site, user, password, reuse_json, connector_id: context.connectorId || '' }),
    });
    const data = await res?.json().catch(() => ({}));
    if (res?.ok) {
      showToast(`Coleta concluida: ${data?.count ?? 0} registros novos.`);
      closeSwitchCollectModal();
      loadSwitch();
    } else {
      showToast(data?.detail || data?.error || 'Falha na coleta do switch.', true);
    }
  } catch (e) {
    showToast(e.message || 'Erro de conexao com o switch.', true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="scan-search"></i> Coletar'; lucide.createIcons(); }
  }
}

function netToolSetLog(html, status = '') {
  const log = document.getElementById('netToolLog');
  const statusEl = document.getElementById('netToolStatus');
  if (log) log.innerHTML = html || 'Nenhum resultado.';
  if (statusEl && status) statusEl.textContent = status;
}

function netToolText(value) {
  if (value === null || value === undefined) return '';
  return String(value);
}

function netToolFormatLocal(data) {
  const result = data?.result || {};
  const items = result.items || [];
  if (Array.isArray(items) && items.length) {
    return items.map(item => {
      const ok = item.online === true || item.open === true || item.ok === true || (Number(item.status_code || 0) > 0 && Number(item.status_code || 0) < 500);
      const klass = ok ? 'network-tool-line-ok' : 'network-tool-line-fail';
      const parts = [
        ok ? 'OK' : 'FAIL',
        item.target || item.url || '',
        item.method ? `via ${item.method}` : '',
        item.port ? `porta ${item.port}` : '',
        item.status_code ? `HTTP ${item.status_code}` : '',
        item.rtt_ms ? `${item.rtt_ms}ms` : item.elapsed_ms ? `${item.elapsed_ms}ms` : '',
        item.server ? `server=${item.server}` : '',
        item.addresses ? `addr=${item.addresses.join(', ')}` : '',
        !ok && item.error ? `erro=${item.error}` : '',
      ].filter(Boolean).join(' ');
      return `<div class="${klass}">${esc(parts)}</div>`;
    }).join('');
  }
  if (result.stdout || result.stderr || result.error) {
    return `<div class="network-tool-line-muted">${esc([result.stdout, result.stderr, result.error].filter(Boolean).join('\n'))}</div>`;
  }
  return `<div>${esc(JSON.stringify(data, null, 2))}</div>`;
}

function netToolFormatJob(job) {
  const result = job?.result || {};
  const routerosPing = result.routeros_ping || result.result?.routeros_ping || '';
  const inventory = result.inventory || result.result?.inventory || null;
  if (routerosPing) {
    return routerosPing.split(/[;,]/).filter(Boolean).map(item => {
      const separator = item.includes('=') ? '=' : ':';
      const [target, ok] = item.split(separator);
      const normalized = String(ok || '').toLowerCase();
      const success = normalized === 'true' || normalized === '1';
      return `<div class="${success ? 'network-tool-line-ok' : 'network-tool-line-fail'}">${success ? 'OK' : 'FAIL'} ${esc(target || item)}</div>`;
    }).join('');
  }
  if (inventory) {
    return [
      `<div class="network-tool-line-ok">DHCP leases: ${esc(inventory.dhcp_leases ?? 0)}</div>`,
      `<div class="network-tool-line-ok">ARP entries: ${esc(inventory.arp_entries ?? 0)}</div>`,
      `<div class="network-tool-line-ok">Neighbors: ${esc(inventory.neighbors ?? 0)}</div>`,
    ].join('');
  }
  if (job?.error) return `<div class="network-tool-line-fail">${esc(job.error)}</div>`;
  return `<div class="network-tool-line-muted">Aguardando MikroTik.</div>`;
}

async function pollNetToolRemoteJob(connectorId, jobId) {
  for (let attempt = 0; attempt < 12; attempt++) {
    await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 2500 : 5000));
    const data = await apiJson(`/api/connectors/${encodeURIComponent(connectorId)}/jobs`);
    const job = (data?.jobs || []).find(item => String(item.id || '') === String(jobId || ''));
    if (!job) continue;
    if (job.status === 'done' || job.status === 'failed') {
      netToolSetLog(netToolFormatJob(job), job.status === 'done' ? 'Job concluido.' : 'Job falhou.');
      return;
    }
    netToolSetLog(`<span class="network-tool-line-muted">Job ${esc(job.status || 'queued')} no MikroTik. Aguardando resultado...</span>`, 'Aguardando MikroTik...');
  }
  netToolSetLog('<span class="network-tool-line-muted">Job enviado, mas ainda sem resultado. Atualize ou execute novamente para consultar.</span>', 'Aguardando resultado.');
}

function netToolSelectedConnector() {
  return document.getElementById('netToolConnector')?.value || '';
}

async function loadNetOperate() {
  const data = await apiJson('/api/connectors');
  _connectors = data?.connectors || _connectors || [];
  const sel = document.getElementById('netToolConnector');
  if (sel) {
    sel.innerHTML = _connectors.map(row => `<option value="${esc(row.id)}">${esc(row.name || row.id)} - ${esc(row.site || '')}</option>`).join('');
  }
  updateNetToolFormState();
  lucide.createIcons();
}

function updateNetToolFormState() {
  const origin = document.getElementById('netToolOrigin')?.value || 'local';
  const test = document.getElementById('netToolTest')?.value || 'ping';
  const conn = document.getElementById('netToolConnector');
  const ports = document.getElementById('netToolPorts');
  const targets = document.getElementById('netToolTargets');
  if (conn) conn.disabled = origin !== 'connector';
  if (ports) ports.disabled = !['tcp', 'port_scan', 'http'].includes(test);
  if (targets) {
    targets.disabled = test === 'lan_inventory';
    if (test === 'lan_inventory') targets.placeholder = 'A coleta LAN usa DHCP, ARP e Neighbors do MikroTik selecionado.';
    else targets.placeholder = '10.10.9.20, 192.168.20.1-192.168.20.20 ou 192.168.20.0/24';
  }
}

async function runNetTool(e) {
  e?.preventDefault();
  const origin = document.getElementById('netToolOrigin')?.value || 'local';
  const test = document.getElementById('netToolTest')?.value || 'ping';
  const targetsRaw = document.getElementById('netToolTargets')?.value.trim() || '';
  const ports = document.getElementById('netToolPorts')?.value.trim() || '';
  const timeout = Number(document.getElementById('netToolTimeout')?.value || 3);
  const concurrency = Number(document.getElementById('netToolConcurrency')?.value || 64);
  const btn = document.getElementById('btnRunNetTool');

  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Executando'; lucide.createIcons(); }
  netToolSetLog('<span class="network-tool-line-muted">Executando teste...</span>', 'Executando...');
  try {
    if (origin === 'connector') {
      const connectorId = netToolSelectedConnector();
      if (!connectorId) throw new Error('Selecione um conector MikroTik.');
      if (test !== 'ping' && test !== 'lan_inventory') {
        throw new Error('No MikroTik, esta primeira versao executa Ping e Coletar LAN. Para TCP/HTTP/DNS/Traceroute use Servidor local/VPN.');
      }
      const type = test === 'lan_inventory' ? 'lan_inventory' : 'ping_many';
      const targets = targetsRaw.split(/[\s,;]+/).map(x => x.trim()).filter(Boolean);
      if (type === 'ping_many' && !targets.length) throw new Error('Informe ao menos um alvo para ping.');
      const res = await api('/api/connectors/jobs', {
        method: 'POST',
        body: JSON.stringify({ connector_id: connectorId, type, payload: type === 'ping_many' ? { targets } : {} }),
      });
      const body = await res?.json().catch(() => ({}));
      if (!res?.ok || body?.ok === false) throw new Error(body?.detail || 'Erro ao criar job remoto.');
      netToolSetLog(`Job ${esc(type)} enviado para o MikroTik.\n\nAguardando o conector executar no proximo ciclo.\nID: ${esc(body?.job?.id || '-')}`, 'Job remoto enviado.');
      await loadConnectorJobs(connectorId);
      pollNetToolRemoteJob(connectorId, body?.job?.id || '');
      return;
    }

    if (!targetsRaw) throw new Error('Informe ao menos um alvo.');
    const res = await api('/api/network/tools/run', {
      method: 'POST',
      body: JSON.stringify({ test, targets: targetsRaw, ports, timeout, concurrency }),
    });
    const body = await res?.json().catch(() => ({}));
    if (!res?.ok || body?.ok === false) throw new Error(body?.detail || 'Falha ao executar teste.');
    netToolSetLog(netToolFormatLocal(body), `${body.count || 0} alvo(s) testado(s).`);
  } catch (err) {
    netToolSetLog(`<span class="network-tool-line-fail">${esc(err?.message || err)}</span>`, 'Falha no teste.');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="play"></i> Executar'; lucide.createIcons(); }
  }
}

//  Implantacao
let _deployCurrentId = '';
let _deployConnectors = [];
let _deploySites = [];
let _deployAvailableRecorders = [];
let _deployRecorderListTimer = null;
let _deployPullTargetIp = ''; // IP achado no Mikrotik, so pra conectar/puxar -- nao vai no campo visivel
let _deployConfirmedCameraIp = ''; // ultimo IP confirmado por um pull bem sucedido (usado como alvo de conexao)
const DEPLOY_LOCAL_ORIGIN = '__local__';

function deploymentPreferredInventoryMode() {
  try {
    const value = localStorage.getItem('so_deployment_inventory_mode') || 'basic';
    return ['basic', 'olt', 'switch'].includes(value) ? value : 'basic';
  } catch { return 'basic'; }
}

function deploymentApplyPreferredInventoryMode() {
  const value = deploymentPreferredInventoryMode();
  document.querySelectorAll('.deployment-inventory-mode').forEach(select => { select.value = value; });
}

function deploymentSetPreferredInventoryMode(value) {
  const mode = ['basic', 'olt', 'switch'].includes(value) ? value : 'basic';
  try { localStorage.setItem('so_deployment_inventory_mode', mode); } catch {}
  document.querySelectorAll('.deployment-inventory-mode').forEach(select => { select.value = mode; });
}

function deployPayload() {
  return {
    id: _deployCurrentId || '',
    olt_id: Number(document.getElementById('deployOltContext')?.value || 0) || null,
    connector_id: deploySelectedConnectorId(),
    site: document.getElementById('deploySite')?.value.trim() || '',
    camera_mac: document.getElementById('deployCameraMac')?.value.trim() || '',
    camera_ip: document.getElementById('deployCameraIp')?.value.trim() || '',
    camera_title: document.getElementById('deployCameraTitle')?.value.trim() || '',
    camera_model: document.getElementById('deployCameraModel')?.value.trim() || '',
    camera_manufacturer: document.getElementById('deployCameraManufacturer')?.value.trim() || '',
    location: document.getElementById('deployCameraLocation')?.value.trim() || '',
    camera_user: document.getElementById('deployCameraUser')?.value.trim() || '',
    camera_password: document.getElementById('deployCameraPassword')?.value || '',
    inventory_mode: document.getElementById('deployInventoryMode')?.value || 'basic',
    recorder_type: document.getElementById('deployRecorderType')?.value || '',
    recorder_host: document.getElementById('deployRecorderHost')?.value.trim() || '',
    recorder_user: document.getElementById('deployRecorderUser')?.value.trim() || '',
    recorder_password: document.getElementById('deployRecorderPassword')?.value || '',
    recorder_channel: document.getElementById('deployRecorderChannel')?.value.trim() || '',
    recorder_camera_ip: document.getElementById('deployRecorderCameraIp')?.value.trim() || document.getElementById('deployCameraIp')?.value.trim() || '',
    recorder_title: document.getElementById('deployRecorderTitle')?.value.trim() || '',
  };
}

function deploySyncRecorderCameraIp() {
  const el = document.getElementById('deployRecorderCameraIp');
  if (!el) return;
  const ip = document.getElementById('deployCameraIp')?.value.trim() || _deployConfirmedCameraIp || _deployPullTargetIp || '';
  el.value = ip;
}

function deployConnectorKey(conn) {
  return String(conn?.id || conn?.connector_id || '');
}

function deployConnectorRawValue() {
  return document.getElementById('deployConnector')?.value || '';
}

function deployIsLocalOrigin() {
  return deployConnectorRawValue() === DEPLOY_LOCAL_ORIGIN;
}

function deploySelectedConnectorId() {
  const raw = deployConnectorRawValue();
  return raw && raw !== DEPLOY_LOCAL_ORIGIN ? raw : '';
}

function deployConnectorSite(conn) {
  return String(conn?.site || conn?.client || '').trim();
}

function deployConnectorOnline(conn) {
  return _connectorIsOnline(conn);
}

function deployConnectorVpnReady(conn) {
  return _connectorHasTunnel(conn);
}

function deployConnectorLabel(conn) {
  return _connectorLabel(conn);
}

function deployOriginReady() {
  if (deployIsLocalOrigin()) return true;
  const conn = deploySelectedConnector();
  return Boolean(conn && deployConnectorOnline(conn) && deployConnectorVpnReady(conn));
}

function deployApplyOriginFields() {
  const site = document.getElementById('deploySite');
  const raw = deployConnectorRawValue();
  const conn = deploySelectedConnector();
  if (!site) return;
  site.disabled = !raw;
  site.readOnly = false;
  if (!raw) site.value = '';
  if (conn && !deployIsLocalOrigin()) site.value = deployConnectorSite(conn);
}

function deploySelectedConnector() {
  const id = deploySelectedConnectorId();
  return _deployConnectors.find(c => deployConnectorKey(c) === id) || null;
}

function deployRenderConnectorStatus() {
  const box = document.getElementById('deployConnectorStatus');
  if (!box) return;
  const raw = deployConnectorRawValue();
  if (!raw) {
    box.innerHTML = 'Escolha Local/VPN do servidor ou um conector online com VPN. Os dados do CFTV ficam bloqueados ate definir a origem.';
    box.classList.add('error');
    return;
  }
  if (deployIsLocalOrigin()) {
    box.innerHTML = '<b style="color:var(--primary)">● Local / VPN do servidor</b> -- informe o site/local e use apenas redes acessiveis pelo servidor.';
    box.classList.remove('error');
    return;
  }
  const conn = deploySelectedConnector();
  if (!conn) {
    box.innerHTML = 'Conector nao encontrado. Atualize a lista.';
    box.classList.add('error');
    return;
  }
  const online = deployConnectorOnline(conn);
  const vpnReady = deployConnectorVpnReady(conn);
  const inv = conn.inventory || {};
  const counts = [
    inv.dhcp_leases != null ? `${esc(inv.dhcp_leases)} DHCP` : '',
    inv.arp_entries != null ? `${esc(inv.arp_entries)} ARP` : '',
    inv.neighbors != null ? `${esc(inv.neighbors)} vizinhos` : '',
  ].filter(Boolean).join(' / ');
  const lastSeen = conn.last_seen ? esc(formatDateTimeShort(conn.last_seen)) : 'nunca';
  box.classList.toggle('error', !online || !vpnReady);
  box.innerHTML = `<b style="color:${online && vpnReady ? 'var(--primary)' : 'var(--danger)'}">${online ? '● Online' : '○ Offline'}</b> -- ${esc(deployConnectorLabel(conn))} - ${vpnReady ? 'VPN pronta' : 'sem VPN configurada'} - Ultimo sinal: ${lastSeen} - ${counts || 'sem inventario recebido ainda'}`;
}

