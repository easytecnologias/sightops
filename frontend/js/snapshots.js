function renderSnapCamGrid(cams) {
  const grid = document.getElementById('snapCamGrid');
  if (!cams.length) {
    grid.innerHTML = '<p style="padding:40px;color:var(--muted);grid-column:1/-1;text-align:center">Nenhuma camera encontrada.</p>';
    return;
  }

  grid.innerHTML = cams.map(c => {
    const temFoto  = !!(c.snapshot_url);
    const imgSrc   = temFoto ? `${API_BASE}${esc(c.snapshot_url)}` : '';
    const statusCl = (c.status||'').toLowerCase() === 'online' ? 'var(--primary)' : 'var(--danger)';

    return `<div class="snap-card" data-ip="${esc(c.ip)}" style="cursor:pointer">
      <div style="position:relative">
        <label style="position:absolute;top:8px;left:8px;z-index:2;cursor:pointer" onclick="event.stopPropagation()">
          <input type="checkbox" class="chk-snap-cam" value="${esc(c.ip)}" style="accent-color:var(--primary);width:15px;height:15px">
        </label>
        ${temFoto
          ? `<img src="${imgSrc}" alt="${esc(c.ip)}" loading="lazy" decoding="async" style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#1a1a2e" onerror="this.style.opacity='.3'">`
          : `<div style="width:100%;aspect-ratio:16/9;background:#e9ecef;display:flex;align-items:center;justify-content:center;color:#aaa"><svg width='40' height='40' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><rect x='2' y='2' width='20' height='20' rx='2'/><circle cx='12' cy='10' r='3'/><path d='m2 20 4-4 4 4 4-8 4 8'/></svg></div>`
        }
        <div style="position:absolute;bottom:0;left:0;right:0;padding:6px 10px;background:linear-gradient(transparent,rgba(0,0,0,.7));color:white;font-size:11px;display:flex;justify-content:space-between">
          <span class="monospace">${esc(c.ip)}</span>
          <span style="color:${statusCl};font-weight:600">${esc(c.status||'')}</span>
        </div>
      </div>
      <div style="padding:10px 12px">
        <div style="font-weight:600;font-size:13px;margin-bottom:2px">${esc(c.titulo||'')}</div>
        <div style="font-size:11px;color:var(--muted);display:flex;justify-content:space-between">
          <span>${esc(c.local||'')}</span>
          <span>${esc(c.model||'')}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  // Click na foto abre carrossel
  grid.querySelectorAll('.snap-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('input[type=checkbox]')) return;
      const idx = cams.findIndex(c => c.ip === card.dataset.ip);
      openCarrossel(cams, idx);
    });
  });
}

//  Carrossel de Gravadores (DVR+NVR) 
function openCarrosselGrav(rows, idx) {
  // Reutiliza o mesmo carrossel de cameras mas com dados de gravadores
  const adapted = rows.map(r => ({
    ip:           `${r.host} CH${r.channel}`,
    titulo:       r.title || `CH${r.channel}`,
    local:        r.local || '',
    model:        r.modelo || '',
    mac:          r.mac || '',
    fabricante:   r.fabricante || '',
    status:       r.status || '',
    snapshot_url: r.snapshot_url || '',
    pon: '', onu_id: '', onu_name: '', onu_serial: '',
  }));
  openCarrossel(adapted, idx);
}

//  Carrossel de Snapshots 
let _carCams  = [];
let _carIdx   = 0;

function openCarrossel(cams, idx = 0) {
  _carCams = cams;
  _carIdx  = idx;
  document.getElementById('modalCarrossel').style.display = 'flex';
  renderCarrossel();
  lucide.createIcons();
}

function closeCarrossel() {
  document.getElementById('modalCarrossel').style.display = 'none';
}

function renderCarrossel() {
  const c = _carCams[_carIdx];
  if (!c) return;

  // Header
  setText('carIdx',   `${_carIdx + 1} / ${_carCams.length}`);
  setText('carTitulo', c.titulo || c.ip);
  setText('carSub',   `${c.ip}    ${c.local || ''}    ${c.model || ''}`);

  // Imagem
  const img   = document.getElementById('carImg');
  const noImg = document.getElementById('carNoImg');
  if (c.snapshot_url) {
    img.src = `${API_BASE}${c.snapshot_url}`;
    img.style.display = 'block';
    noImg.style.display = 'none';
  } else {
    img.style.display = 'none';
    noImg.style.display = 'flex';
  }

  // Thumbnails
  const thumbs = document.getElementById('carThumbs');
  thumbs.innerHTML = _carCams.map((cam, i) => `
    <div onclick="carGoTo(${i})" style="
      flex-shrink:0;width:64px;height:42px;border-radius:4px;overflow:hidden;cursor:pointer;
      border:2px solid ${i === _carIdx ? 'var(--primary)' : 'transparent'};
      opacity:${i === _carIdx ? '1' : '0.5'};transition:all .15s">
      ${cam.snapshot_url
        ? `<img src="${API_BASE}${esc(cam.snapshot_url)}" loading="lazy" decoding="async" style="width:100%;height:100%;object-fit:cover">`
        : `<div style="width:100%;height:100%;background:#2d3748;display:grid;place-items:center"><svg width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='#718096' stroke-width='2'><rect x='2' y='2' width='20' height='20' rx='2'/></svg></div>`}
    </div>`).join('');
}

function carGoTo(idx) {
  _carIdx = Math.max(0, Math.min(_carCams.length - 1, idx));
  renderCarrossel();
}

let _snapGravAll = [];

async function loadSnapDvr() {
  const [dvrData, nvrData] = await Promise.all([
    apiJson('/api/dvr/inventory'),
    apiJson('/api/nvr/inventory'),
  ]);

  const dvrs = (dvrData?.inventory || []).map(r => ({ ...r, _tipo: 'dvr' }));
  const nvrs = (nvrData?.inventory || []).map(r => ({ ...r, _tipo: 'nvr' }));
  _snapGravAll = [...dvrs, ...nvrs];

  // Filtro de sites
  const sites = [...new Set(_snapGravAll.map(r => r.local).filter(Boolean))].sort();
  const selSite = document.getElementById('filterSnapGravSite');
  if (selSite) {
    const cur = selSite.value;
    selSite.innerHTML = '<option value="">Todos os sites</option>' +
      sites.map(s => `<option${s===cur?' selected':''}>${esc(s)}</option>`).join('');
  }

  applySnapGravFilters();
}

function applySnapGravFilters() {
  const q      = (document.getElementById('searchSnapGrav')?.value || '').toLowerCase();
  const tipo   = document.getElementById('filterSnapGravTipo')?.value   || '';
  const status = document.getElementById('filterSnapGravStatus')?.value || '';
  const site   = document.getElementById('filterSnapGravSite')?.value   || '';

  const filtered = _snapGravAll.filter(r => {
    const temFoto = !!(r.snapshot_url);
    if (tipo   && r._tipo !== tipo)   return false;
    if (status === 'com' && !temFoto) return false;
    if (status === 'sem' &&  temFoto) return false;
    if (site   && r.local !== site)   return false;
    if (q) return [r.host, r.title, r.local, r.modelo, String(r.channel)]
      .some(f => (f||'').toLowerCase().includes(q));
    return true;
  });

  setText('snapGravTotal',   _snapGravAll.length);
  setText('snapGravComFoto', _snapGravAll.filter(r => r.snapshot_url).length);
  setText('snapGravSemFoto', _snapGravAll.filter(r => !r.snapshot_url).length);

  renderSnapGravGrid(filtered);
}

function renderSnapGravGrid(rows) {
  const grid = document.getElementById('snapGravGrid');
  if (!rows.length) {
    grid.innerHTML = '<p style="padding:40px;color:var(--muted);grid-column:1/-1;text-align:center">Nenhum canal encontrado.</p>';
    return;
  }

  grid.innerHTML = rows.map((r, i) => {
    const temFoto  = !!(r.snapshot_url);
    const imgSrc   = temFoto ? `${API_BASE}${esc(r.snapshot_url)}` : '';
    const statusCl = (r.status||'').toLowerCase() === 'online' ? 'var(--primary)' : 'var(--danger)';
    const badge    = r._tipo === 'dvr'
      ? `<span style="background:#f0fdf9;color:var(--primary);font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;border:1px solid #b2f2d4">DVR</span>`
      : `<span style="background:#e7f5ff;color:var(--blue);font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;border:1px solid #a5d8ff">NVR</span>`;

    return `<div class="snap-card" data-grav-idx="${i}" style="cursor:pointer">
      <div style="position:relative">
        <label style="position:absolute;top:8px;left:8px;z-index:2;cursor:pointer" onclick="event.stopPropagation()">
          <input type="checkbox" class="chk-snap-grav" value="${i}" style="accent-color:var(--primary);width:15px;height:15px">
        </label>
        <div style="position:absolute;top:8px;right:8px;z-index:2">${badge}</div>
        ${temFoto
          ? `<img src="${imgSrc}" alt="CH${r.channel}" loading="lazy" decoding="async" style="width:100%;aspect-ratio:16/9;object-fit:cover;display:block;background:#1a1a2e" onerror="this.style.opacity='.3'">`
          : `<div style="width:100%;aspect-ratio:16/9;background:#e9ecef;display:flex;align-items:center;justify-content:center;color:#aaa"><svg width='40' height='40' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='1.5'><rect x='2' y='2' width='20' height='20' rx='2'/><circle cx='12' cy='10' r='3'/><path d='m2 20 4-4 4 4 4-8 4 8'/></svg></div>`}
        <div style="position:absolute;bottom:0;left:0;right:0;padding:6px 10px;background:linear-gradient(transparent,rgba(0,0,0,.7));color:white;font-size:11px;display:flex;justify-content:space-between">
          <span class="monospace">${esc(r.host)} CH${r.channel}</span>
          <span style="color:${statusCl};font-weight:600">${esc(r.status||'')}</span>
        </div>
      </div>
      <div style="padding:10px 12px">
        <div style="font-weight:600;font-size:13px;margin-bottom:2px">${esc(r.title||'')}</div>
        <div style="font-size:11px;color:var(--muted);display:flex;justify-content:space-between">
          <span>${esc(r.local||'')}</span>
          <span>${esc(r.modelo||'')}</span>
        </div>
      </div>
    </div>`;
  }).join('');

  // Click abre carrossel
  grid.querySelectorAll('.snap-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (e.target.closest('input[type=checkbox]')) return;
      const idx = parseInt(card.dataset.gravIdx);
      openCarrosselGrav(rows, idx);
    });
  });
}

async function loadSnapNvr() {
  const data = await apiJson('/api/nvr/inventory');
  const nvrs = data?.nvrs || data || [];
  const grid = document.getElementById('snapNvrGrid');
  if (!nvrs.length) {
    grid.innerHTML = '<p style="padding:40px;color:var(--muted);grid-column:1/-1;text-align:center">Nenhum NVR.</p>';
    return;
  }
  grid.innerHTML = nvrs.map(n => `
    <div class="snap-card">
      <img src="${API_BASE}/data/nvr_snapshot/${esc(n.snapshot_file || '')}" alt="${esc(n.ip)}" loading="lazy" decoding="async"
           onerror="this.style.background='#e9ecef';this.removeAttribute('src')">
      <div class="snap-card-body">
        <div class="snap-card-ip">${esc(n.ip)}</div>
        <div class="snap-card-sub">${esc(n.brand || '')}  ${esc(n.channels || '?')} canais</div>
      </div>
    </div>`).join('');
}

//  Manutencao
let _mntCamAll = [];
const _mntCamFilter = { q: '', site: '', status: '' };

function _mntSearchText(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .trim();
}

function _ipToInt(ip) {
  return ip.split('.').reduce((acc, o) => (acc << 8) + (parseInt(o, 10) || 0), 0) >>> 0;
}

function _isIpv4(ip) {
  const parts = String(ip || '').trim().split('.');
  return parts.length === 4 && parts.every((p) => {
    if (!/^\d{1,3}$/.test(p)) return false;
    const n = Number(p);
    return n >= 0 && n <= 255 && String(n) === String(Number(p));
  });
}

function _isValidSubnetMask(mask) {
  if (!_isIpv4(mask)) return false;
  const n = _ipToInt(mask);
  const inv = (~n) >>> 0;
  return ((inv + 1) & inv) === 0;
}

function _isInCameras22(ip) {
  return _isIpv4(ip) && ((_ipToInt(ip) & _ipToInt('255.255.252.0')) === _ipToInt('10.10.8.0'));
}

function _suggestNetworkForIp(ip) {
  if (_isInCameras22(ip)) {
    return {
      mask: '255.255.252.0',
      gateway: '10.10.10.1',
      label: 'Rede de cameras 10.10.8.0/22',
      locked: true,
    };
  }
  if (_isIpv4(ip)) {
    const base = ip.split('.').slice(0, 3).join('.');
    return {
      mask: '255.255.255.0',
      gateway: `${base}.1`,
      label: `Sugestao por /24: ${base}.0/24`,
      locked: false,
    };
  }
  return { mask: '', gateway: '', label: 'Informe novo IP, mascara e gateway reais da camera.', locked: false };
}

function _fillTrocarIpNetwork(ip, force = false) {
  const hint = document.getElementById('trocarIpNetworkHint');
  const maskEl = document.getElementById('trocarIpMask');
  const gwEl = document.getElementById('trocarIpGw');
  const s = _suggestNetworkForIp(ip);
  if (force || !maskEl.value.trim()) maskEl.value = s.mask;
  if (force || !gwEl.value.trim()) gwEl.value = s.gateway;
  if (hint) hint.textContent = s.locked
    ? `${s.label}: use mascara ${s.mask} e gateway ${s.gateway}.`
    : `${s.label}. Ajuste se a rede real for diferente.`;
}

// Retorna true/false se ip bate com term como range/CIDR, ou null se term n\u00e3o \u00e9 padr\u00e3o de IP.
