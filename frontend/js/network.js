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
let _switchPorts = [];
let _switchInfo = {};

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
  _switchPorts = ports;
  _switchInfo = swData?.switch || {};
  _switchPlatform = _switchInfo.platform || '';

  const portInfoByKey = {};
  ports.forEach(p => { portInfoByKey[`${p.switch_ip || ''}|${p.port || ''}`] = p; });

  // MACs aprendidos na porta uplink sao de equipamentos atras do switch (outra
  // rede/segmento), nao ligados fisicamente nela. Antes a porta sumia da tela;
  // agora vira UMA linha de resumo ("uplink -- N equipamentos atras").
  const uplinkCount = {};
  rawRows.filter(r => r.port_role_guess === 'uplink').forEach(r => {
    const k = `${r.switch_ip || ''}|${r.port || ''}`;
    uplinkCount[k] = uplinkCount[k] || { row: r, n: 0 };
    uplinkCount[k].n += 1;
  });
  const uplinkRows = Object.values(uplinkCount).map(({ row, n }) => ({
    site: row.site, switch_ip: row.switch_ip, switch_name: row.switch_name,
    port: row.port, mac: '', vlan: '', entry_type: '', port_role_guess: 'uplink',
    _uplink: true, _uplinkMacs: n,
  }));
  const edgeRows = rawRows.filter(r => r.port_role_guess !== 'uplink');

  // Portas sem nenhum MAC aprendido nao aparecem no mac_table (nada circulou
  // por elas) -- a lista de portas fisicas coletada junto mostra essas tambem.
  const withRow = new Set([...edgeRows, ...uplinkRows].map(r => `${r.switch_ip || ''}|${r.port || ''}`));
  const emptyPortRows = ports
    .filter(p => p.port && !withRow.has(`${p.switch_ip || ''}|${p.port || ''}`))
    .map(p => ({
      site: p.site, switch_ip: p.switch_ip, switch_name: p.switch_name,
      port: p.port, mac: '', vlan: '', entry_type: '', port_role_guess: 'edge',
      _linkUp: !!p.up, _synthetic: true,
    }));

  _switchRows = [...edgeRows, ...uplinkRows, ...emptyPortRows].map(r => {
    const info = portInfoByKey[`${r.switch_ip || ''}|${r.port || ''}`] || {};
    return {
      ...r,
      port_id: info.port_id,
      _linkUp: r._synthetic ? r._linkUp : (info.up !== false),
      bandwidth: info.bandwidth || '',
      duplex: info.duplex || '',
      poe_enabled: info.poe_enabled,
      poe_power_watts: info.poe_power_watts,
      admin_enabled: info.admin_enabled,
    };
  }).sort((a, b) => String(a.switch_ip || '').localeCompare(String(b.switch_ip || ''))
    || (switchPortNumber(a.port) - switchPortNumber(b.port)));

  _switchCamByMac = {};
  [camBasico, camOlt, camSwitch].forEach(camData => {
    const cams = camData?.cameras || (Array.isArray(camData) ? camData : []);
    cams.forEach(c => { if (c.mac) _switchCamByMac[String(c.mac).toLowerCase()] = c; });
  });

  populateSwitchFilters();
  renderSwitchCards();
  renderSwitchTable(_switchRows);
}

function switchPortNumber(port) {
  const m = String(port || '').match(/(\d+)\s*$/);
  return m ? Number(m[1]) : 9999;
}

function switchCamOf(r) {
  return r && r.mac ? _switchCamByMac[String(r.mac).toLowerCase()] : null;
}

// O que esta ligado na porta, em uma frase: o operador quer "qual camera", nao
// o MAC. Usado no mapa de portas e na coluna Equipamento.
function switchPortDevice(r) {
  if (!r) return { titulo: 'sem dados', detalhe: '', tom: 'muted' };
  if (r._uplink) return { titulo: 'Uplink', detalhe: `${r._uplinkMacs} equipamentos atras`, tom: 'uplink' };
  if (r._synthetic) return { titulo: r._linkUp ? 'Conectado, sem trafego' : 'Sem cabo', detalhe: '', tom: 'muted' };
  const cam = switchCamOf(r);
  if (cam) {
    return {
      titulo: cam.titulo || cam.nome || cam.name || cam.ip || 'Camera',
      detalhe: [cam.ip, cam.modelo || cam.model].filter(Boolean).join(' · '),
      // No mapa de portas cabe uma palavra: o IP diferencia, o nome nao (na
      // SIERRA as 37 cameras se chamam "VIPC INTELBRAS").
      curto: cam.ip || cam.titulo,
      tom: 'ok', ip: cam.ip,
      // Sem o conector o ping vai ao IP real, que num site isolado nao tem rota
      // (10.200.0.0/23 existe em mais de um cliente) e da timeout com a camera viva.
      connector: cam.remote_connector_id || cam.connector_id || '',
    };
  }
  return { titulo: 'Nao cadastrado', detalhe: 'MAC sem camera no inventario', tom: 'warn' };
}

function renderSwitchCards() {
  const box = document.getElementById('switchCards');
  if (!box) return;
  const porSwitch = new Map();
  _switchPorts.forEach(p => {
    const k = p.switch_ip || '';
    if (!porSwitch.has(k)) porSwitch.set(k, []);
    porSwitch.get(k).push(p);
  });
  if (!porSwitch.size) { box.innerHTML = ''; return; }

  box.innerHTML = [...porSwitch.entries()].map(([ip, ports]) => {
    ports = [...ports].sort((a, b) => switchPortNumber(a.port) - switchPortNumber(b.port));
    const linhas = _switchRows.filter(r => r.switch_ip === ip);
    const meta = linhas.find(r => r.switch_model) || {};
    const info = _switchInfo.ip === ip ? _switchInfo : {};
    const nome = info.name || ports[0]?.switch_name || ip;
    const modelo = info.model || meta.switch_model || '';
    const firmware = info.firmware || meta.switch_firmware || '';
    const site = info.site || ports[0]?.site || '';
    const comLink = ports.filter(p => p.up).length;
    const poe = ports.reduce((s, p) => s + (p.poe_enabled && p.poe_power_watts ? Number(p.poe_power_watts) : 0), 0);

    const tiles = ports.map(p => {
      const linhasPorta = linhas.filter(r => r.port === p.port);
      const principal = linhasPorta.find(r => r._uplink) || linhasPorta.find(r => !r._synthetic) || linhasPorta[0];
      const dev = switchPortDevice(principal);
      const extra = linhasPorta.filter(r => !r._synthetic && !r._uplink).length;
      const estado = p.admin_enabled === false ? 'off' : (p.up ? (dev.tom === 'uplink' ? 'uplink' : 'up') : 'down');
      const watts = p.poe_enabled && p.poe_power_watts != null ? `${Number(p.poe_power_watts).toFixed(1)} W` : (p.poe_enabled === false ? 'PoE off' : '');
      const nomeCurto = dev.curto || dev.titulo;
      const titulo = extra > 1 ? `${nomeCurto} +${extra - 1}` : nomeCurto;
      return `<button type="button" class="sw-port sw-port-${estado}" data-port="${esc(p.port || '')}" title="${esc(`${p.port}: ${dev.titulo}${dev.detalhe ? ' -- ' + dev.detalhe : ''}`)}">
        <span class="sw-port-num">${esc(p.port || '')}</span>
        <span class="sw-port-dev">${esc(titulo)}</span>
        <span class="sw-port-meta">${esc([p.up ? (p.bandwidth || 'link') : (p.admin_enabled === false ? 'desativada' : 'sem link'), watts].filter(Boolean).join(' · '))}</span>
      </button>`;
    }).join('');

    return `<div class="panel sw-card">
      <div class="sw-card-head">
        <div class="sw-card-title">
          <i data-lucide="network"></i>
          <div><a href="#" class="sw-web" data-ip="${esc(ip)}" title="Abrir a interface web do switch"><strong>${esc(nome)}</strong>
            <span class="monospace">${esc(ip)}</span> <i data-lucide="external-link" class="sw-web-icon"></i></a>
            <small>${esc([modelo, firmware, site].filter(Boolean).join(' · '))}</small></div>
        </div>
        <div class="sw-card-stats">
          <span><b>${comLink}/${ports.length}</b> portas com link</span>
          <span><b>${poe.toFixed(1)} W</b> de PoE</span>
        </div>
      </div>
      <div class="sw-ports" data-switch-ip="${esc(ip)}">${tiles}</div>
    </div>`;
  }).join('');

  // Clicar na porta filtra a tabela por ela; clicar de novo limpa.
  box.onclick = (ev) => {
    const web = ev.target.closest('.sw-web');
    if (web) {
      ev.preventDefault();
      openDeviceWeb(web.dataset.ip, 80);
      return;
    }
    const tile = ev.target.closest('.sw-port');
    if (!tile) return;
    const busca = document.getElementById('switchSearch');
    if (!busca) return;
    busca.value = busca.value === tile.dataset.port ? '' : tile.dataset.port;
    filterSwitchTable();
  };
  lucide.createIcons();
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

  const withMac = _switchRows.filter(r => !r._synthetic && !r._uplink);
  const switches = new Set(_switchRows.map(r => String(r.switch_ip || r.switch_name || '').trim()).filter(Boolean));
  const sites = new Set(_switchRows.map(r => String(r.site || '').trim()).filter(Boolean));
  const activePorts = new Set(_switchRows.filter(r => !r._synthetic).map(r => `${r.switch_ip || ''}|${r.port || ''}`));
  setText('switchCount', switches.size);
  setText('switchPortCount', activePorts.size);
  setText('switchMacTotal', withMac.length);
  setText('switchSiteCount', sites.size);
  setText('switchFooter', `${rows.length} porta${rows.length !== 1 ? 's' : ''}/equipamento${rows.length !== 1 ? 's' : ''}`);

  if (!rows.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Nenhum dado. Execute a coleta.</td></tr>';
    return;
  }

  const canToggle = _switchPlatform === 'hikvision';
  const variosSwitches = new Set(rows.map(r => r.switch_ip)).size > 1;
  let ultimoSwitch = null;

  tbody.innerHTML = rows.map(r => {
    let cabecalho = '';
    if (variosSwitches && r.switch_ip !== ultimoSwitch) {
      ultimoSwitch = r.switch_ip;
      cabecalho = `<tr class="sw-group"><td colspan="6"><i data-lucide="network"></i> <b>${esc(r.switch_name || r.switch_ip || '')}</b> <span class="monospace">${esc(r.switch_ip || '')}</span> <span class="text-muted">${esc(r.site || '')}</span></td></tr>`;
    }
    const dev = switchPortDevice(r);
    const speed = [r.bandwidth, r.duplex].filter(Boolean).join(' ');
    const link = r._synthetic && !r._linkUp
      ? '<span class="sw-dot sw-dot-down"></span><span class="text-muted">sem link</span>'
      : (r.admin_enabled === false
        ? '<span class="sw-dot sw-dot-off"></span><span style="color:var(--danger)">desativada</span>'
        : `<span class="sw-dot sw-dot-up"></span>${esc(speed || 'link')}`);

    let poeCell = '<span class="text-muted">-</span>';
    if (r.poe_enabled === true) {
      const watts = r.poe_power_watts != null ? `${Number(r.poe_power_watts).toFixed(1)} W` : 'ligado';
      poeCell = `<span class="badge badge-green">${esc(watts)}</span>`;
    } else if (r.poe_enabled === false) {
      poeCell = '<span class="badge badge-gray">desligado</span>';
    }

    // Vermelho = estado atual ligado (apertar desliga); verde = estado atual
    // desligado (apertar liga) -- a cor do botao mostra o que vai acontecer.
    const btn = 'width:28px;height:28px';
    const base = `data-switch-ip="${esc(r.switch_ip || '')}" data-site="${esc(r.site || '')}" data-port="${esc(r.port || '')}"`;
    const actions = [];
    if (dev.ip) {
      const conector = dev.connector || (r.switch_ip === _switchInfo.ip ? (_switchInfo.connector_id || '') : '');
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="ping" data-ip="${esc(dev.ip)}" data-connector="${esc(conector)}" title="Testar ping em ${esc(dev.ip)}" style="${btn}"><i data-lucide="activity"></i></button>`);
    }
    if (canToggle && r.port_id != null && r.poe_enabled === true && !r._uplink) {
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="cycle" ${base} title="Reiniciar pelo PoE (desliga 6 s e religa)" style="${btn};color:var(--amber)"><i data-lucide="rotate-ccw"></i></button>`);
    }
    if (canToggle && r.port_id != null && r.poe_enabled !== undefined && r.poe_enabled !== null && !r._uplink) {
      const poeOn = r.poe_enabled === true;
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="poe" ${base} data-enabled="${poeOn ? '0' : '1'}" title="${poeOn ? 'Desligar PoE' : 'Ligar PoE'}" style="${btn};color:${poeOn ? 'var(--danger)' : 'var(--primary)'}"><i data-lucide="zap"></i></button>`);
    }
    if (canToggle && r.port_id != null && !r._uplink) {
      const portOn = r.admin_enabled !== false;
      actions.push(`<button type="button" class="icon-button switch-port-action" data-action="port" ${base} data-enabled="${portOn ? '0' : '1'}" title="${portOn ? 'Desativar porta' : 'Ativar porta'}" style="${btn};color:${portOn ? 'var(--danger)' : 'var(--primary)'}"><i data-lucide="power"></i></button>`);
    }
    const actionsHtml = actions.length
      ? `<div style="display:flex;gap:4px;align-items:center;justify-content:flex-end">${actions.join('')}</div>`
      : '';

    const vlan = r.vlan && String(r.vlan).toLowerCase() !== 'default' ? ` <span class="badge badge-gray">VLAN ${esc(r.vlan)}</span>` : '';
    const corDev = dev.tom === 'warn' ? 'color:var(--amber)' : (dev.tom === 'muted' ? 'color:var(--muted)' : '');
    return `${cabecalho}
    <tr${r._synthetic ? ' style="opacity:.6"' : ''}>
      <td class="monospace" style="white-space:nowrap;font-weight:600">${esc(r.port || '')}</td>
      <td style="overflow:hidden">
        <div style="font-weight:600;${corDev};overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(dev.titulo)}">${dev.tom === 'uplink' ? '<i data-lucide="corner-left-up" style="width:14px;height:14px;vertical-align:-2px"></i> ' : ''}${esc(dev.titulo)}${vlan}</div>
        ${dev.detalhe ? `<div class="text-muted monospace" style="font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(dev.detalhe)}</div>` : ''}
      </td>
      <td class="monospace text-muted" style="white-space:nowrap;font-size:12px">${r.mac ? esc(r.mac) : '-'}</td>
      <td style="white-space:nowrap">${link}</td>
      <td style="white-space:nowrap">${poeCell}</td>
      <td style="white-space:nowrap">${actionsHtml}</td>
    </tr>`;
  }).join('');
  lucide.createIcons();
}

// Reinicia o equipamento da porta cortando o PoE: e o "tirar e por na tomada"
// remoto, para camera travada. Desliga, espera 6 s e religa -- e confere a
// religacao, porque se ela falhar a camera fica desligada ate alguem agir.
async function switchPoeCycle(el) {
  const port = el.dataset.port;
  const ok = await showConfirm({
    eyebrow: 'Switch',
    title: `Reiniciar o equipamento da porta ${port}`,
    msg: `O PoE da porta ${port} vai ser desligado por 6 segundos e religado. O equipamento ligado nela reinicia e fica fora do ar por 1 a 2 minutos. Continuar?`,
    label: 'Reiniciar',
  });
  if (!ok) return;
  const corpo = (enabled) => JSON.stringify({ switch_ip: el.dataset.switchIp, site: el.dataset.site, port, enabled });
  el.disabled = true;
  try {
    const off = await api('/api/switch/port/poe', { method: 'POST', body: corpo(false) });
    if (!off?.ok) {
      const data = await off?.json().catch(() => ({}));
      showToast(data?.detail || data?.error || 'O switch recusou desligar o PoE.', true);
      return;
    }
    showToast(`PoE da porta ${port} desligado. Religando em 6 s...`);
    await new Promise(r => setTimeout(r, 6000));
    let on = null;
    for (let tentativa = 0; tentativa < 3 && !on?.ok; tentativa++) {
      on = await api('/api/switch/port/poe', { method: 'POST', body: corpo(true) }).catch(() => null);
      if (!on?.ok) await new Promise(r => setTimeout(r, 3000));
    }
    if (on?.ok) {
      showToast(`Porta ${port}: PoE religado. O equipamento volta em 1 a 2 minutos.`);
    } else {
      showToast(`ATENCAO: o PoE da porta ${port} NAO religou. Use o botao de PoE para ligar.`, true);
    }
  } catch (e) {
    showToast(e.message || 'Erro de conexao com o switch.', true);
  } finally {
    el.disabled = false;
    loadSwitch();
  }
}

async function switchPortAction(el) {
  const action = el.dataset.action;
  if (action === 'ping') {
    openPingTerminal(el.dataset.ip, el.dataset.connector || '');
    return;
  }
  if (action === 'cycle') {
    await switchPoeCycle(el);
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
      return [r.site, r.switch_name, r.switch_ip, r.port, r.mac, r.vlan, r.entry_type, cam?.titulo, cam?.local, cam?.ip, r._uplink ? 'uplink' : '']
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
  // A tela de Rede nao tem mais o terminal: sem esta queda, seis mensagens
  // (inclusive a de falha) ficariam mudas.
  if (!log) {
    const resumo = document.getElementById('redeFerrResumo');
    if (resumo && (status || html)) {
      // O texto real antes do status generico: era ele que dizia POR QUE
      // falhou, e "Falha no teste." engolia a explicacao.
      const texto = document.createElement('div');
      texto.innerHTML = html || '';
      resumo.textContent = texto.textContent.trim() || status;
    }
  }
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
      // O conector diz ao servidor por qual tunel sair -- IP privado se repete
      // entre clientes, e sem isso o teste pode bater no site errado.
      body: JSON.stringify({ test, targets: targetsRaw, ports, timeout, concurrency,
                             connector_id: netToolSelectedConnector() }),
    });
    const body = await res?.json().catch(() => ({}));
    if (!res?.ok || body?.ok === false) throw new Error(body?.detail || 'Falha ao executar teste.');
    pintarRedeFerramentas(body);  // tabela, nao terminal
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
    // Sem isto o backend assumia 80. O NVR da RESERVA PERUCABA atende em
    // 8086, entao dava "Connection refused" -- e, pior, `_credencial_gravador`
    // procura a senha salva por (host, PORTA): com 80 ele nao achava a
    // credencial guardada em 8086 e ainda pedia senha. Um esquecimento, dois
    // sintomas que pareciam problemas diferentes.
    recorder_http_port: deployRecorderPortaSelecionada(),
    recorder_user: document.getElementById('deployRecorderUser')?.value.trim() || '',
    recorder_password: document.getElementById('deployRecorderPassword')?.value || '',
    recorder_channel: document.getElementById('deployRecorderChannel')?.value.trim() || '',
    // Os campos proprios do gravador sairam da tela: o IP e o titulo da camera
    // JA foram decididos na etapa 2, e repetir a pergunta so criava duas
    // respostas possiveis para a mesma coisa -- e um jeito de o canal do NVR
    // ficar com nome diferente do inventario.
    recorder_camera_ip: document.getElementById('deployCameraIp')?.value.trim() || '',
    // Vem da CAMERA. O campo da etapa 2 e preenchido com o titulo lido dela
    // ao entrar, e e ele que tambem sera gravado nela no "Registrar camera" --
    // entao canal do NVR e inventario nascem com o mesmo nome. `_deployTituloDaCamera`
    // cobre o caso de o campo ainda estar vazio.
    recorder_title: document.getElementById('deployCameraTitle')?.value.trim()
      || (typeof _deployTituloDaCamera !== 'undefined' ? _deployTituloDaCamera : '') || '',
  };
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
  const sel = document.getElementById('deploySiteEscolha');
  const raw = deployConnectorRawValue();
  const conn = deploySelectedConnector();
  if (!site) return;
  site.readOnly = false;
  if (sel) sel.disabled = !raw;
  if (!raw) {
    site.value = '';
    site.hidden = true;
    if (sel) sel.innerHTML = '<option value="">Escolha o site acima</option>';
    return;
  }
  // O conector ja sabe o site dele: chega preenchido, e a lista continua
  // disponivel para o caso de o tecnico estar num local novo do mesmo
  // conector.
  if (conn && !deployIsLocalOrigin()) site.value = deployConnectorSite(conn);
  if (typeof deployPreencherSites === 'function') deployPreencherSites(site.value);
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
    // Antes isto nascia VERMELHO: a tela abria acusando o tecnico de um erro
    // que ele ainda nao teve chance de cometer. Enquanto ele nao escolheu, nao
    // ha erro nenhum -- ha uma instrucao. Vermelho fica para quando algo
    // realmente deu errado, senao ninguem mais le vermelho nesta tela.
    box.innerHTML = 'Comece escolhendo o site acima. O resto da tela libera em seguida.';
    box.classList.remove('error');
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
  const lastSeen = conn.last_seen ? esc(formatDateTimeShort(conn.last_seen)) : 'nunca';
  // Pilula de estado + numeros soltos, como na barra do console de gravador.
  // O texto corrido anterior repetia o nome do site -- que esta no seletor
  // logo acima -- e ainda enfileirava tudo com hifens numa linha so.
  //
  // `.error` fica reservado para erro NOSSO (conector sumido da lista). Estado
  // do equipamento quem diz e a pilula: pintar a faixa inteira de vermelho
  // alem dela seria dizer a mesma coisa duas vezes.
  box.classList.remove('error');
  const pilula = online && vpnReady ? 'ok' : (online ? 'aviso' : 'erro');
  const estado = online ? (vpnReady ? 'Online' : 'Online, sem VPN') : 'Offline';
  const meta = [
    `Ultimo sinal <b>${lastSeen}</b>`,
    inv.dhcp_leases != null ? `<b>${esc(inv.dhcp_leases)}</b> DHCP` : '',
    inv.arp_entries != null ? `<b>${esc(inv.arp_entries)}</b> ARP` : '',
    inv.neighbors != null ? `<b>${esc(inv.neighbors)}</b> vizinhos` : '',
  ].filter(Boolean);
  box.innerHTML = `<span class="barra-status">`
    + `<span class="sinal ${pilula}"><i></i>${esc(estado)}</span>`
    + `<span class="barra-meta">${meta.map(x => `<span>${x}</span>`).join('')}</span>`
    + `</span>`;
}

