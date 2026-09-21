function _mntIpMatchTerm(ip, term) {
  // Range completo: 10.10.9.20-10.10.9.30
  const fullRange = term.match(/^(\d{1,3}(?:\.\d{1,3}){3})-(\d{1,3}(?:\.\d{1,3}){3})$/);
  if (fullRange) {
    const n = _ipToInt(ip), lo = _ipToInt(fullRange[1]), hi = _ipToInt(fullRange[2]);
    return n >= lo && n <= hi;
  }
  // Range curto (\u00faltimo octeto): 10.10.9.20-30
  const shortRange = term.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})-(\d{1,3})$/);
  if (shortRange) {
    const parts = ip.split('.');
    if (parts.slice(0, 3).join('.') === shortRange[1]) {
      const last = parseInt(parts[3], 10);
      return last >= parseInt(shortRange[2], 10) && last <= parseInt(shortRange[3], 10);
    }
    return false;
  }
  // CIDR: 10.10.9.0/24
  const cidr = term.match(/^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/);
  if (cidr) {
    const bits = parseInt(cidr[2], 10);
    const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
    return (_ipToInt(ip) & mask) === (_ipToInt(cidr[1]) & mask);
  }
  return null; // n\u00e3o \u00e9 padr\u00e3o de range/CIDR
}

let _mntCamView = (() => {
  try { return sessionStorage.getItem('so_mnt_cam_view') || 'basico'; } catch { return 'basico'; }
})();

async function setMntCamView(view) {
  if (!['basico', 'olt', 'switch'].includes(view)) view = 'basico';
  _mntCamView = view;
  try { sessionStorage.setItem('so_mnt_cam_view', view); } catch {}
  const sel = document.getElementById('mntCamView');
  if (sel && sel.value !== view) sel.value = view;
  await loadMntCam();
}

function atualizarAbasMntCam() {
  const sel = document.getElementById('mntCamView');
  if (sel && sel.value !== _mntCamView) sel.value = _mntCamView;
}

async function loadMntCam() {
  const grid = document.getElementById('mntCamGrid');
  if (!grid) return;
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Carregando</div>';
  // Cada cliente usa um modo de inventario: quem tem OLT nao tem switch e
  // vice-versa. Pedir 'olt' fixo deixava a tela vazia para cliente de switch --
  // foi o caso da San Marine, cujas 48 cameras nunca apareceram aqui.
  const data = await apiJson(`/api/cameras?mode=${encodeURIComponent(_mntCamView)}`);
  _mntCamAll = data?.cameras || data || [];

  // Escondido o modo sem nenhuma camera, para o usuario nao clicar em vazio.
  // Basico fica sempre visivel por ser o denominador comum.
  atualizarAbasMntCam();

  const sites = [...new Set(_mntCamAll.map(c => c.local).filter(Boolean))].sort();
  const sel = document.getElementById('mntCamSite');
  if (sel) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    sel.value = cur;
  }
  _mntCamRender();
}

function _mntCamRender() {
  const grid = document.getElementById('mntCamGrid');
  if (!grid) return;
  const checked = new Set([...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value));
  const { q, site, status } = _mntCamFilter;
  const ql = _mntSearchText(q);

  // Separa query em termos por vírgula (OR entre termos)
  const terms = ql ? ql.split(',').map(t => t.trim()).filter(Boolean) : [];

  let filtered = _mntCamAll.filter(c => {
    if (site && (c.local || '') !== site) return false;
    if (status && (c.status || '').toLowerCase() !== status) return false;
    if (!terms.length) return true;
    const camIp   = (c.ip || '').trim();
    const haystack = [
      c.ip, c.host, c.camera_ip, c.ip_camera,
      c.titulo, c.title, c.nome, c.name,
      c.local, c.site,
      c.modelo, c.model, c.fabricante, c.brand,
      c.mac, c.onu_name, c.onu_serial,
    ].map(_mntSearchText).join(' ');
    // Basta UM termo bater (OR)
    return terms.some(term => {
      const ipMatch = _mntIpMatchTerm(camIp, term);
      if (ipMatch !== null) return ipMatch;      // era range/CIDR
      return haystack.includes(term);            // texto livre
    });
  });

  filtered.sort((a, b) => (a.titulo || a.ip || '').localeCompare(b.titulo || b.ip || '', 'pt', { numeric: true }));

  if (!filtered.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Nenhuma camera encontrada.</div>';
    _mntCamUpdateCount();
    return;
  }

  grid.innerHTML = filtered.map(c => {
    const ip  = c.ip || '';
    const st  = (c.status || '').toLowerCase();
    const dot = st === 'online' ? 'online' : st === 'offline' ? 'offline' : 'unknown';
    const snap = c.snapshot_url || c.imgbb_url || '';
    const sel = checked.has(ip);
    return `
      <div class="mnt-cam-card${sel ? ' selected' : ''}" data-ip="${esc(ip)}" data-titulo="${esc(c.titulo||ip)}" onclick="_mntCamCardClick(this,event)">
        <input type="checkbox" class="mnt-cam-card-chk chk-mnt-cam" value="${esc(ip)}" ${sel ? 'checked' : ''} onclick="event.stopPropagation();_mntCamToggle(this)">
        <div class="mnt-cam-card-img">
          ${snap ? `<img src="${esc(snap)}" loading="lazy" onerror="this.style.display='none'">` : `<div class="mnt-cam-no-snap"><i data-lucide="camera-off" style="width:22px;height:22px"></i></div>`}
          <span class="mnt-cam-dot ${dot}"></span>
          <button class="mnt-stream-btn" onclick="event.stopPropagation();openMntStream('${esc(ip)}','${esc(c.titulo||ip)}','${esc(snap)}')" title="Ver stream / links">
            <i data-lucide="play-circle" style="width:16px;height:16px"></i>
          </button>
        </div>
        <div class="mnt-cam-card-info">
          <div class="mnt-cam-card-title">${esc(c.titulo || ip)}</div>
          <div class="mnt-cam-card-sub">${esc(ip)}  ${esc(c.local || '')}</div>
          <div class="mnt-cam-card-sub">${esc(c.modelo || c.model || '')}</div>
        </div>
        <div class="mnt-cam-card-result" id="mntRes_${ip.replace(/\./g,'_')}"></div>
      </div>`;
  }).join('');

  lucide.createIcons();
  _mntCamUpdateCount();
}

function _mntCamCardClick(card, event) {
  if (event.target.classList.contains('chk-mnt-cam')) return;
  const chk = card.querySelector('.chk-mnt-cam');
  if (chk) { chk.checked = !chk.checked; _mntCamToggle(chk); }
}

function _mntCamToggle(chk) {
  chk.closest('.mnt-cam-card')?.classList.toggle('selected', chk.checked);
  _mntCamUpdateCount();
}

function _mntCamUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  const el = document.getElementById('mntCamSelectedCount');
  if (el) el.textContent = n === 0 ? '0 selecionadas' : `${n} selecionada${n !== 1 ? 's' : ''}`;
}

//  Stream modal — player MSE unico (liveStream.js)
let _mntStreamIp   = '';
let _mntStreamUser = '';
let _mntStreamPass = '';
let _mntStreamSubtype = 1; // 0=main 1080p  1=sub 480p
let _mntStreamMuted   = true;
let _mntLiveHandle = null;
let _mntClockTimer = null;

const _DAYS_PT   = ['Dom','Seg','Ter','Qua','Qui','Sex','Sáb'];
const _MONTHS_PT = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];

function _mntTickClock() {
  const now = new Date();
  const hh  = String(now.getHours()).padStart(2,'0');
  const mm  = String(now.getMinutes()).padStart(2,'0');
  const ss  = String(now.getSeconds()).padStart(2,'0');
  const clk = document.getElementById('mntStreamClock');
  if (clk) clk.textContent = `${hh}:${mm}:${ss}`;
  const dt  = document.getElementById('mntStreamDate');
  if (dt)  dt.textContent  = `${_DAYS_PT[now.getDay()]}, ${now.getDate()} ${_MONTHS_PT[now.getMonth()]}`;
}

function openMntStream(ip, titulo) {
  _mntStreamIp   = ip;
  _mntStreamUser = document.getElementById('mntCamUser')?.value || 'admin';
  _mntStreamPass = document.getElementById('mntCamPass')?.value || '';
  _mntStreamSubtype = 1;
  _mntStreamMuted   = true;
  const hint = cameraStreamHint(ip);

  document.getElementById('mntStreamTitle').textContent = titulo || ip;
  document.getElementById('mntStreamIp').textContent    = ip;
  document.getElementById('mntStreamRtspMain').value    = buildCameraRtspUrl(ip, _mntStreamUser, _mntStreamPass, 0, hint);
  document.getElementById('mntStreamRtspSub').value     = buildCameraRtspUrl(ip, _mntStreamUser, _mntStreamPass, 1, hint);
  const qualLabel = document.getElementById('mntStreamQualLabel');
  if (qualLabel) qualLabel.textContent = 'Sub-stream';
  const webLink = document.getElementById('mntStreamOpenWeb');
  if (webLink) webLink.href = `http://${ip}/`;
  const muteBtn = document.getElementById('mntStreamMuteBtn');
  if (muteBtn) muteBtn.innerHTML = '<i data-lucide="volume-x" style="width:15px;height:15px"></i>';

  document.getElementById('modalMntStream').classList.remove('hidden');
  lucide.createIcons();

  _mntTickClock();
  clearInterval(_mntClockTimer);
  _mntClockTimer = setInterval(_mntTickClock, 1000);

  _startLiveView(ip, _mntStreamUser, _mntStreamPass, _mntStreamSubtype);
}

function _startLiveView(ip, user, pass, subtype) {
  const video       = document.getElementById('mntStreamVideo');
  const placeholder = document.getElementById('mntStreamPlaceholder');
  const statusEl    = document.getElementById('mntStreamStatus');

  if (_mntLiveHandle) { _mntLiveHandle.stop(); _mntLiveHandle = null; }
  video.srcObject = null;
  video.classList.add('hidden');
  video.muted = true;
  if (placeholder) placeholder.style.display = '';
  if (statusEl) statusEl.textContent = 'Conectando...';

  const hint = cameraStreamHint(ip);
  _mntLiveHandle = mountLiveStream(video, {
    ip, user, pass, subtype,
    vendor: hint.vendor,
    model: hint.model,
    onStatus: (texto) => {
      if (texto) {
        if (statusEl) statusEl.textContent = texto;
      } else {
        video.muted = _mntStreamMuted;
        video.classList.remove('hidden');
        if (placeholder) placeholder.style.display = 'none';
        if (statusEl) statusEl.textContent = '';
      }
    },
  });
}

function closeMntStream() {
  clearInterval(_mntClockTimer);
  _mntClockTimer = null;
  if (_mntLiveHandle) { _mntLiveHandle.stop(); _mntLiveHandle = null; }
  _mntStreamIp = '';
  const video = document.getElementById('mntStreamVideo');
  if (video) { video.srcObject = null; video.classList.add('hidden'); }
  const placeholder = document.getElementById('mntStreamPlaceholder');
  if (placeholder) placeholder.style.display = '';
  document.getElementById('modalMntStream').classList.add('hidden');
}

function _mntStreamCopy(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard?.writeText(el.value).then(() => showToast('Copiado!')).catch(() => {});
}

function _mntStreamSnapshot() {
  const video = document.getElementById('mntStreamVideo');
  if (!video || video.readyState < 2) { showToast('Sem vídeo para capturar', true); return; }
  const canvas = document.createElement('canvas');
  canvas.width  = video.videoWidth  || 1280;
  canvas.height = video.videoHeight || 720;
  canvas.getContext('2d').drawImage(video, 0, 0);
  const ts = new Date().toISOString().slice(0,19).replace(/[T:]/g,'-');
  const a  = document.createElement('a');
  a.download = `snapshot_${_mntStreamIp}_${ts}.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
  showToast('Frame salvo');
}

function _mntStreamFullscreen() {
  const wrap = document.getElementById('mntVideoWrap');
  if (!wrap) return;
  if (document.fullscreenElement) document.exitFullscreen();
  else wrap.requestFullscreen().catch(() => {});
}

function _mntStreamMute() {
  const video  = document.getElementById('mntStreamVideo');
  const btn    = document.getElementById('mntStreamMuteBtn');
  _mntStreamMuted = !_mntStreamMuted;
  if (video) video.muted = _mntStreamMuted;
  if (btn) {
    btn.innerHTML = _mntStreamMuted
      ? '<i data-lucide="volume-x" style="width:15px;height:15px"></i>'
      : '<i data-lucide="volume-2" style="width:15px;height:15px"></i>';
    lucide.createIcons();
  }
}

async function _mntStreamReboot() {
  if (!_mntStreamIp) return;
  if (!confirm(`Reiniciar câmera ${_mntStreamIp}?`)) return;
  try {
    await api('/api/cameras/reboot', { method: 'POST', body: JSON.stringify({ ips: [_mntStreamIp] }) });
    showToast('Reboot enviado');
  } catch (e) { showToast('Erro ao reiniciar', true); }
}

function _mntStreamToggleQuality() {
  _mntStreamSubtype = _mntStreamSubtype === 1 ? 0 : 1;
  const label = document.getElementById('mntStreamQualLabel');
  if (label) label.textContent = _mntStreamSubtype === 1 ? 'Sub-stream' : 'Principal';
  if (_mntLiveHandle) _mntLiveHandle.setSubtype(_mntStreamSubtype);
}

//  Modals de configuracao
function openMntMirrorModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntMirror').classList.remove('hidden');
  lucide.createIcons();
}

function openMntDayNightModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntDayNight').classList.remove('hidden');
  lucide.createIcons();
}

function openMntQualityModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntQuality').classList.remove('hidden');
  lucide.createIcons();
}

function openMntNtpModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  const input = document.getElementById('mntNtpAddress');
  if (input && !input.value.trim()) input.value = 'time.cloudflare.com';
  document.getElementById('modalMntNtp')?.classList.remove('hidden');
  setTimeout(() => input?.focus(), 80);
  lucide.createIcons();
}

function closeMntNtpModal() {
  document.getElementById('modalMntNtp')?.classList.add('hidden');
}

function runMntNtp() {
  const input = document.getElementById('mntNtpAddress');
  const address = input?.value.trim() || 'time.cloudflare.com';
  closeMntNtpModal();
  _mntCamRunAction('ntp', { address });
}

function openMntRenameModal() {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const grid = document.getElementById('mntRenameRows');
  grid.innerHTML = ips.map(ip => {
    const card = document.querySelector(`.mnt-cam-card[data-ip="${CSS.escape(ip)}"]`);
    const titulo = card?.dataset.titulo || ip;
    return `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
      <span style="font-size:11px;color:var(--muted);min-width:100px;flex-shrink:0;font-family:monospace">${esc(ip)}</span>
      <input type="text" data-rename-ip="${esc(ip)}" value="${esc(titulo)}" style="flex:1;border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:13px">
    </div>`;
  }).join('');
  document.getElementById('modalMntRename').classList.remove('hidden');
  lucide.createIcons();
}

async function runMntRename() {
  const user = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntCamPass')?.value || '';
  const targets = [...document.querySelectorAll('[data-rename-ip]')].map(inp => ({
    ip: inp.dataset.renameIp, title: inp.value.trim()
  })).filter(t => t.title);
  if (!targets.length) return;
  document.getElementById('modalMntRename').classList.add('hidden');
  const body = document.getElementById('mntCamConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntCamConsole', 'mntCamConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] RENOMEAR ${targets.length} camera(s)`, true);
  try {
    const res  = await api('/api/maintenance/batch/rename', { method:'POST', body: JSON.stringify({ user, pass, targets }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => _mntLog('mntCamConsole', 'mntCamConsoleBody', r.ip || '', r.title ? ` "${r.title}" ${r.ok ? '' : ' ' + (r.error||'erro')}` : (r.error||'erro'), r.ok));
    showToast(data.message || 'Renomear: concluido');
    _mntCamAll = [];
    loadMntCam();
  } catch (err) {
    _mntLog('mntCamConsole', 'mntCamConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function runMntMirror() {
  const mirror = document.getElementById('mntMirrorCheck')?.checked || false;
  const flip   = document.getElementById('mntFlipCheck')?.checked || false;
  document.getElementById('modalMntMirror').classList.add('hidden');
  await _mntCamRunAction('mirror', { mirror, flip });
}

async function runMntDayNight() {
  const selected = document.querySelector('input[name="mntDayNightMode"]:checked');
  const mode = parseInt(selected?.value || '0');
  document.getElementById('modalMntDayNight').classList.add('hidden');
  await _mntCamRunAction('day_night', { mode });
}

async function runMntQuality() {
  const bitrate = parseInt(document.getElementById('mntQualityBitrate')?.value || '0') || null;
  const fps     = parseInt(document.getElementById('mntQualityFps')?.value || '0') || null;
  const codec   = document.getElementById('mntQualityCodec')?.value || '';
  document.getElementById('modalMntQuality').classList.add('hidden');
  await _mntCamRunAction('video_quality', { bitrate, fps, codec: codec || undefined });
}

//  Configuracao de rede em lote
function openMntNetworkModal() {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const rows = document.getElementById('mntNetRows');
  rows.innerHTML = ips.sort((a, b) => {
    const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
    for (let i = 0; i < 4; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
    return 0;
  }).map(ip => `
    <div style="display:flex;gap:8px;align-items:center">
      <span style="font-size:11px;color:var(--muted);min-width:110px;font-family:monospace;flex-shrink:0">${esc(ip)}</span>
      <span style="color:var(--muted)"></span>
      <input type="text" data-net-old="${esc(ip)}" value="${esc(ip)}"
        style="flex:1;border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:13px;font-family:monospace;background:var(--surface)">
    </div>`).join('');
  document.getElementById('modalMntNetwork').classList.remove('hidden');
  lucide.createIcons();
}

async function runMntNetwork() {
  const mask    = document.getElementById('mntNetMask')?.value || '';
  const gateway = document.getElementById('mntNetGateway')?.value?.trim() || '';
  const user    = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass    = document.getElementById('mntCamPass')?.value || '';
  const targets = [...document.querySelectorAll('[data-net-old]')].map(inp => ({
    old_ip: inp.dataset.netOld, new_ip: inp.value.trim()
  })).filter(t => t.new_ip);

  if (!targets.length) return;
  if (!mask && !gateway && targets.every(t => t.old_ip === t.new_ip)) {
    showToast('Nada a alterar  preencha mascara, gateway ou edite algum IP', true); return;
  }
  document.getElementById('modalMntNetwork').classList.add('hidden');
  const consoleId = 'mntCamConsole', bodyId = 'mntCamConsoleBody';
  document.getElementById(consoleId)?.classList.remove('hidden');
  document.getElementById(bodyId).innerHTML = '';
  _mntLog(consoleId, bodyId, null, `Aplicando configuracao de rede em ${targets.length} camera(s)`, true);
  try {
    const r = await api('/api/maintenance/batch/network_config', {
      method: 'POST',
      body: JSON.stringify({ targets, mask, gateway, user, pass })
    });
    const data = await r.json();
    (data.results || []).forEach(res => {
      const detail = res.new_ip !== res.ip ? ` ${res.new_ip}` : '';
      _mntLog(consoleId, bodyId, res.ip, `${detail}  ${res.msg}`, res.ok);
    });
    _mntLog(consoleId, bodyId, null, 'Concluido. Cameras reiniciam em ~30s.', true);
  } catch (e) {
    _mntLog(consoleId, bodyId, null, `Erro: ${e.message}`, false);
  }
}

//  Deslocar IPs em lote
function openMntShiftIpModal() {
  const firstIp = document.querySelector('.chk-mnt-cam:checked')?.value || '';
  if (firstIp) {
    const parts = firstIp.split('.');
    if (parts.length === 4) {
      document.getElementById('mntShiftPrefix').value = parts.slice(0, 3).join('.') + '.';
    }
  }
  _mntShiftPreview();
  document.getElementById('modalMntShiftIp').classList.remove('hidden');
  lucide.createIcons();
}

function _mntShiftPreview() {
  const prefix = document.getElementById('mntShiftPrefix')?.value || '';
  const start  = parseInt(document.getElementById('mntShiftStart')?.value || '');
  const end    = parseInt(document.getElementById('mntShiftEnd')?.value || '');
  const delta  = parseInt(document.getElementById('mntShiftDelta')?.value || '0');
  const box    = document.getElementById('mntShiftPreviewBox');
  if (!box) return;
  if (!prefix || isNaN(start) || isNaN(end) || isNaN(delta) || delta === 0 || start > end) {
    box.innerHTML = '<em style="color:var(--muted)">Preencha os campos acima</em>';
    return;
  }
  let octets = [];
  for (let i = start; i <= end; i++) octets.push(i);
  if (delta > 0) octets = octets.slice().reverse();
  const sign = delta > 0 ? '+' : '';
  const lines = octets.map(o => {
    const n = o + delta;
    const ok = n >= 1 && n <= 254;
    const color = ok ? 'var(--primary)' : 'var(--danger)';
    const warn  = ok ? '' : '  invalido';
    return `<div style="display:flex;gap:12px;padding:2px 0"><span style="opacity:.6;min-width:120px">${prefix}${o}</span><span style="color:var(--muted)"></span><span style="color:${color};font-weight:600">${prefix}${n}${warn}</span></div>`;
  });
  box.innerHTML = `<div style="margin-bottom:6px;opacity:.6;font-size:11px">Ordem de execucao (delta ${sign}${delta})  ${octets.length} camera(s)</div>` + lines.join('');
}

async function runMntShiftIp() {
  const prefix  = document.getElementById('mntShiftPrefix')?.value?.trim() || '';
  const start   = parseInt(document.getElementById('mntShiftStart')?.value || '');
  const end     = parseInt(document.getElementById('mntShiftEnd')?.value || '');
  const delta   = parseInt(document.getElementById('mntShiftDelta')?.value || '0');
  const user    = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass    = document.getElementById('mntCamPass')?.value || '';
  const gateway0 = document.getElementById('mntShiftGateway')?.value?.trim() || '';
  const mask    = document.getElementById('mntShiftMask')?.value?.trim() || '255.255.255.0';
  // o backend exige mascara E gateway; sem os dois ele recusa antes de falar com
  // a camera. Gateway vazio vira prefixo + 1, que e o que o rotulo do campo diz.
  const gateway = gateway0 || `${prefix}1`;

  if (!prefix || isNaN(start) || isNaN(end) || isNaN(delta) || delta === 0 || start > end) {
    showToast('Preencha todos os campos corretamente', true); return;
  }
  document.getElementById('modalMntShiftIp').classList.add('hidden');
  const consoleId = 'mntCamConsole', bodyId = 'mntCamConsoleBody';
  document.getElementById(consoleId)?.classList.remove('hidden');
  document.getElementById(bodyId).innerHTML = '';
  _mntLog(consoleId, bodyId, null, `Deslocando ${prefix}${start} ate ${prefix}${end} por ${delta > 0 ? '+' : ''}${delta}`, true);
  try {
    const r = await api('/api/maintenance/batch/shift_ips', {
      method: 'POST',
      body: JSON.stringify({ prefix, start_octet: start, end_octet: end, delta, user, pass, gateway, mask })
    });
    const data = await r.json();
    (data.results || []).forEach(res => {
      // o backend devolve 'error' quando falha e nada quando da certo;
      // ler 'msg' fazia toda linha (sucesso ou erro) sair como undefined
      const detalhe = res.error || res.msg || (res.ok ? 'OK' : 'falha');
      _mntLog(consoleId, bodyId, res.ip, `-> ${res.new_ip}  ${detalhe}`, res.ok);
    });
    _mntLog(consoleId, bodyId, null, 'Concluido. Aguarde as cameras reiniciarem (~30s).', true);
  } catch (e) {
    _mntLog(consoleId, bodyId, null, `Erro: ${e.message}`, false);
  }
}

function _mntLog(consoleId, bodyId, ip, msg, ok) {
  document.getElementById(consoleId)?.classList.remove('hidden');
  const body = document.getElementById(bodyId);
  if (body) {
    const line = document.createElement('div');
    line.innerHTML = `<span style="color:${ok ? '#6ee7b7' : '#fca5a5'}">${ok ? '[ok]' : '[falha]'}</span> <span style="color:#8ab">${esc(ip || '')}</span>${ip ? '  ' : ''}${esc(msg)}`;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
  }
  if (ip) {
    const res = document.getElementById(`mntRes_${ip.replace(/\./g,'_')}`);
    if (res) res.innerHTML = `<span style="color:${ok ? 'var(--primary)' : 'var(--danger)'}">${ok ? '' : ''} ${esc(msg)}</span>`;
  }
}

async function _mntCamRunAction(endpoint, extra = {}) {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const user = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntCamPass')?.value || '';

  const body = document.getElementById('mntCamConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntCamConsole', 'mntCamConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} camera(s)`, true);

  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass, ...extra }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => _mntLog('mntCamConsole', 'mntCamConsoleBody', r.ip || '', r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok));
    if (!(data.results || []).length) _mntLog('mntCamConsole', 'mntCamConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntCamConsole', 'mntCamConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function loadMntDvr() {
  const data  = await apiJson('/api/dvr/inventory');
  const dvrs  = data?.dvrs || data || [];
  const tbody = document.getElementById('mntDvrTable');
  const uniq  = new Map();
  dvrs.forEach(d => { if (!uniq.has(d.host || d.ip)) uniq.set(d.host || d.ip, d); });
  const rows = [...uniq.values()];
  if (!rows.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Nenhum DVR.</td></tr>'; return; }
  tbody.innerHTML = rows.map(d => {
    const ip = d.host || d.ip || '';
    return `<tr>
      <td><input type="checkbox" class="chk-mnt-dvr" value="${esc(ip)}"></td>
      <td class="monospace">${esc(ip)}</td>
      <td>${esc(d.brand || d.fabricante || '')} ${esc(d.model || d.modelo || '')}</td>
      <td>${esc(d.local || d.site || '')}</td>
      <td>${statusBadge(d.status)}</td>
      <td class="text-muted" id="mntDvrRes_${ip.replace(/\./g,'_')}"></td>
    </tr>`;
  }).join('');

  document.getElementById('chkMntDvrAll').onchange = function() {
    document.querySelectorAll('.chk-mnt-dvr').forEach(c => c.checked = this.checked);
    _mntDvrUpdateCount();
  };
  document.querySelectorAll('.chk-mnt-dvr').forEach(c => c.addEventListener('change', _mntDvrUpdateCount));
  _mntDvrUpdateCount();
}

function _mntDvrUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-dvr:checked').length;
  const el = document.getElementById('mntDvrSelectedCount');
  if (el) el.textContent = `${n} selecionado${n !== 1 ? 's' : ''}`;
}

async function _mntDvrRunAction(endpoint) {
  const ips = [...document.querySelectorAll('.chk-mnt-dvr:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos um DVR', true); return; }
  const user = document.getElementById('mntDvrUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntDvrPass')?.value || '';
  const body = document.getElementById('mntDvrConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} DVR(s)`, true);
  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => {
      const ip = r.ip || r.host || '';
      _mntLog('mntDvrConsole', 'mntDvrConsoleBody', ip, r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok);
      const el = document.getElementById(`mntDvrRes_${ip.replace(/\./g,'_')}`);
      if (el) el.innerHTML = `<span style="color:${r.ok ? 'var(--primary)' : 'var(--danger)'}">${r.ok ? '' : ''} ${esc(r.message || (r.ok ? 'OK' : 'Erro'))}</span>`;
    });
    if (!(data.results || []).length) _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function loadMntNvr() {
  const data  = await apiJson('/api/nvr/inventory');
  const nvrs  = data?.nvrs || data || [];
  const tbody = document.getElementById('mntNvrTable');
  const uniq  = new Map();
  nvrs.forEach(n => { if (!uniq.has(n.host || n.ip)) uniq.set(n.host || n.ip, n); });
  const rows = [...uniq.values()];
  if (!rows.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Nenhum NVR.</td></tr>'; return; }
  tbody.innerHTML = rows.map(n => {
    const ip = n.host || n.ip || '';
    return `<tr>
      <td><input type="checkbox" class="chk-mnt-nvr" value="${esc(ip)}"></td>
      <td class="monospace">${esc(ip)}</td>
      <td>${esc(n.brand || n.fabricante || '')} ${esc(n.model || n.modelo || '')}</td>
      <td>${esc(n.local || n.site || '')}</td>
      <td>${statusBadge(n.status)}</td>
      <td class="text-muted" id="mntNvrRes_${ip.replace(/\./g,'_')}"></td>
    </tr>`;
  }).join('');

  document.getElementById('chkMntNvrAll').onchange = function() {
    document.querySelectorAll('.chk-mnt-nvr').forEach(c => c.checked = this.checked);
    _mntNvrUpdateCount();
  };
  document.querySelectorAll('.chk-mnt-nvr').forEach(c => c.addEventListener('change', _mntNvrUpdateCount));
  _mntNvrUpdateCount();
}

function _mntNvrUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-nvr:checked').length;
  const el = document.getElementById('mntNvrSelectedCount');
  if (el) el.textContent = `${n} selecionado${n !== 1 ? 's' : ''}`;
}

async function _mntNvrRunAction(endpoint) {
  const ips = [...document.querySelectorAll('.chk-mnt-nvr:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos um NVR', true); return; }
  const user = document.getElementById('mntNvrUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntNvrPass')?.value || '';
  const body = document.getElementById('mntNvrConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} NVR(s)`, true);
  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => {
      const ip = r.ip || r.host || '';
      _mntLog('mntNvrConsole', 'mntNvrConsoleBody', ip, r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok);
      const el = document.getElementById(`mntNvrRes_${ip.replace(/\./g,'_')}`);
      if (el) el.innerHTML = `<span style="color:${r.ok ? 'var(--primary)' : 'var(--danger)'}">${r.ok ? '' : ''} ${esc(r.message || (r.ok ? 'OK' : 'Erro'))}</span>`;
    });
    if (!(data.results || []).length) _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

//  Reproducao DVR
let _playbackBound = false;
