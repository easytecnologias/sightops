// Implantacao > Projetos > Tracar rotas: editor de mapa em tela cheia.
// Marca pontos (poste, CTO, emenda, OLT, rack, caixa, camera) clicando no
// mapa, por coordenada digitada ou pelo GPS do aparelho, e puxa cabos
// (fibra principal, drop, UTP) de poste em poste. A metragem de cada rota
// vem do servidor (planning_routes) e alimenta os calculos de cabo.

const PLANNING_ROUTE_KINDS = {
  fiber_main: { label: 'Fibra principal', hint: 'OLT → emenda → CTO', color: '#b86b00', weight: 5, dash: null, key: 'F', cable: 'Cabo optico 12 FO autossustentado', fibers: 12, slack: 20 },
  fiber_drop: { label: 'Fibra drop', hint: 'CTO → caixa de CFTV', color: '#0b7285', weight: 3, dash: '9 6', key: 'D', cable: 'Cabo drop 1 FO', fibers: 1, slack: 10 },
  utp: { label: 'Cabo UTP', hint: 'caixa → camera · ate 100 m', color: '#1971c2', weight: 2.5, dash: '2 6', key: 'U', cable: 'Cabo UTP CAT5e externo', fibers: 0, slack: 3 },
};
const PLANNING_ROUTE_CABLES = {
  fiber_main: ['Cabo optico 6 FO autossustentado', 'Cabo optico 12 FO autossustentado', 'Cabo optico 24 FO autossustentado', 'Cabo optico 36 FO autossustentado', 'Cabo optico 48 FO autossustentado'],
  fiber_drop: ['Cabo drop 1 FO', 'Cabo drop 2 FO', 'Cabo drop 4 FO'],
  utp: ['Cabo UTP CAT5e externo', 'Cabo UTP CAT6 externo', 'Cabo UTP CAT5e interno'],
};
// Ferramentas de ponto: tipo gravado + metadata + prefixo do nome automatico.
const PLANNING_POINT_TOOLS = {
  pole: { label: 'Poste', key: 'P', type: 'pole', prefix: 'P-', metadata: {} },
  cto: { label: 'CTO', key: 'T', type: 'cto', prefix: 'CTO-', metadata: { port_capacity: 8 } },
  emenda: { label: 'Caixa de emenda', key: 'E', type: 'cto', prefix: 'EMENDA-', metadata: { papel: 'splitter_primario', port_capacity: 8 } },
  olt: { label: 'OLT', key: 'O', type: 'olt', prefix: 'OLT-', metadata: { pon_port_capacity: 8 } },
  rack: { label: 'Rack', key: 'R', type: 'rack', prefix: 'RACK-', metadata: {} },
  box: { label: 'Caixa de CFTV', key: 'X', type: 'box', prefix: 'CX-', metadata: {} },
  camera: { label: 'Camera', key: 'C', type: 'camera', prefix: 'CAM ', metadata: {} },
};
const PLANNING_SNAP_PX = 22;
const PLANNING_ROUTE_RESERVE = 0.10;

let _pe = null; // estado do editor: { map, tool, drawing, selectedRouteId, groups, markers }

// ---------------------------------------------------------------------------
// Icones (mesmo desenho no mapa e na barra de ferramentas)
// ---------------------------------------------------------------------------

function planningPointKind(item) {
  if (!item) return 'other';
  if (item.device_type === 'cto' && item.metadata?.papel === 'splitter_primario') return 'emenda';
  return item.device_type;
}

function planningIconSvg(kind, label = '') {
  const text = planningEscape(String(label || '').slice(0, 3));
  switch (kind) {
    case 'pole':
      return `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="#fff" stroke="#445159" stroke-width="2.4"/><path d="M12 6.5v11M8 9h8" stroke="#445159" stroke-width="2.2" stroke-linecap="round"/></svg>`;
    case 'cto':
      return `<svg viewBox="0 0 28 28" width="28" height="28" aria-hidden="true"><circle cx="14" cy="14" r="12" fill="#0b7285" stroke="#fff" stroke-width="2.5"/><path d="M8 14h4M12 14l5-4.5M12 14h7M12 14l5 4.5" stroke="#fff" stroke-width="1.9" stroke-linecap="round" fill="none"/></svg>`;
    case 'emenda':
      return `<svg viewBox="0 0 28 28" width="28" height="28" aria-hidden="true"><rect x="5" y="5" width="18" height="18" rx="3" transform="rotate(45 14 14)" fill="#b86b00" stroke="#fff" stroke-width="2.5"/><path d="M9 14h10M14 9.5v9" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`;
    case 'olt':
      return `<svg viewBox="0 0 36 26" width="36" height="26" aria-hidden="true"><rect x="1.5" y="1.5" width="33" height="23" rx="5" fill="#172026" stroke="#fff" stroke-width="2.5"/><text x="18" y="17.5" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="10" font-weight="800" fill="#fff">OLT</text></svg>`;
    case 'rack':
      return `<svg viewBox="0 0 26 30" width="24" height="28" aria-hidden="true"><rect x="2" y="1.5" width="22" height="27" rx="4" fill="#172026" stroke="#fff" stroke-width="2.5"/><path d="M7 8h12M7 13h12M7 18h12M7 23h12" stroke="#9fb0b8" stroke-width="2" stroke-linecap="round"/></svg>`;
    case 'dio':
      return `<svg viewBox="0 0 28 28" width="26" height="26" aria-hidden="true"><rect x="2" y="2" width="24" height="24" rx="5" fill="#8a5100" stroke="#fff" stroke-width="2.5"/><path d="M8 10h3M8 14h3M8 18h3M17 10h3M17 14h3M17 18h3" stroke="#fff" stroke-width="2" stroke-linecap="round"/></svg>`;
    case 'box':
    case 'box-full':
    case 'box-danger': {
      const fill = kind === 'box-danger' ? '#c92a2a' : kind === 'box-full' ? '#b86b00' : '#1971c2';
      return `<svg viewBox="0 0 34 34" width="32" height="32" aria-hidden="true"><rect x="2" y="2" width="30" height="30" rx="8" fill="${fill}" stroke="#fff" stroke-width="3"/>${text ? `<text x="17" y="21.5" text-anchor="middle" font-family="Inter,Arial,sans-serif" font-size="11" font-weight="800" fill="#fff">${text}</text>` : '<path d="M10 13l7-4 7 4v8l-7 4-7-4zM10 13l7 4 7-4M17 17v8" stroke="#fff" stroke-width="1.8" fill="none" stroke-linejoin="round"/>'}</svg>`;
    }
    case 'camera':
    case 'camera-danger': {
      const fill = kind === 'camera-danger' ? '#c92a2a' : '#087f5b';
      return `<svg viewBox="0 0 26 26" width="24" height="24" aria-hidden="true"><circle cx="13" cy="13" r="11" fill="${fill}" stroke="#fff" stroke-width="2.4"/><path d="M7.5 10.5h8.5v6H7.5zM16 12.5l3-1.8v5.6l-3-1.8" fill="#fff"/></svg>`;
    }
    default:
      return `<svg viewBox="0 0 22 22" width="18" height="18" aria-hidden="true"><circle cx="11" cy="11" r="8" fill="#b86b00" stroke="#fff" stroke-width="2.4"/></svg>`;
  }
}

const PLANNING_ICON_SIZE = {
  pole: [22, 22], cto: [28, 28], emenda: [28, 28], olt: [36, 26], rack: [24, 28], dio: [26, 26],
  box: [32, 32], 'box-full': [32, 32], 'box-danger': [32, 32], camera: [24, 24], 'camera-danger': [24, 24],
};

function planningMapIcon(kind, label = '', selected = false) {
  const size = PLANNING_ICON_SIZE[kind] || [18, 18];
  return L.divIcon({
    className: `pj-icon${selected ? ' is-selected' : ''}`,
    html: planningIconSvg(kind, label),
    iconSize: size, iconAnchor: [size[0] / 2, size[1] / 2], popupAnchor: [0, -size[1] / 2],
  });
}

function planningLineSwatch(kind) {
  const cfg = PLANNING_ROUTE_KINDS[kind];
  return `<svg width="34" height="12" viewBox="0 0 34 12" aria-hidden="true"><path d="M2 6H32" stroke="${cfg.color}" stroke-width="${cfg.weight}" ${cfg.dash ? `stroke-dasharray="${cfg.dash}"` : ''} stroke-linecap="round"/></svg>`;
}

// ---------------------------------------------------------------------------
// Rotas no projeto (usadas tambem pelos calculos e pelo mapa do workspace)
// ---------------------------------------------------------------------------

function planningRoutes() {
  return _planningCurrent?.routes || [];
}

// Rota tracada que liga dois equipamentos (em qualquer sentido).
function planningRouteBetween(aId, bId, kinds) {
  const a = Number(aId); const b = Number(bId);
  return planningRoutes().find(route => (!kinds || kinds.includes(route.kind))
    && ((Number(route.from_device_id) === a && Number(route.to_device_id) === b)
      || (Number(route.from_device_id) === b && Number(route.to_device_id) === a))) || null;
}

// Rota tracada que chega num equipamento (ou sai dele), do tipo pedido.
function planningRouteTouching(deviceId, kinds) {
  const id = Number(deviceId);
  return planningRoutes().find(route => kinds.includes(route.kind)
    && (Number(route.to_device_id) === id || Number(route.from_device_id) === id)) || null;
}

function planningRoutePurchase(route) {
  return (Number(route.length_m || 0) + Number(route.slack_m || 0)) * (1 + PLANNING_ROUTE_RESERVE);
}

// ---------------------------------------------------------------------------
// Abrir / fechar
// ---------------------------------------------------------------------------

function planningEditorMarkup() {
  const pointButtons = Object.entries(PLANNING_POINT_TOOLS).map(([key, cfg]) => `
    <button type="button" class="pe-tool" data-pe-tool="${key}" aria-pressed="false">
      <span class="pe-tool-icon">${planningIconSvg(key === 'box' ? 'box' : key)}</span>
      <span class="pe-tool-label">${cfg.label}</span><kbd>${cfg.key}</kbd>
    </button>`).join('');
  const cableButtons = Object.entries(PLANNING_ROUTE_KINDS).map(([key, cfg]) => `
    <button type="button" class="pe-tool" data-pe-tool="${key}" aria-pressed="false">
      <span class="pe-tool-icon">${planningLineSwatch(key)}</span>
      <span class="pe-tool-label">${cfg.label}<small>${cfg.hint}</small></span><kbd>${cfg.key}</kbd>
    </button>`).join('');
  return `
  <div class="pe-root" id="planningEditor" role="dialog" aria-modal="true" aria-label="Tracar rotas">
    <header class="pe-top">
      <button type="button" class="pe-back" onclick="closePlanningRouteEditor()"><i data-lucide="chevron-left"></i><span id="peProjectName">Projeto</span></button>
      <strong>Tracar rotas</strong>
      <span class="pe-saved" id="peSaved">Tudo salvo</span>
      <span class="pj-spacer"></span>
      <div class="pe-totals" id="peTotals"></div>
      <button type="button" class="pe-done" onclick="closePlanningRouteEditor()">Concluir</button>
    </header>
    <div class="pe-body">
      <aside class="pe-tools" aria-label="Ferramentas">
        <button type="button" class="pe-tool" data-pe-tool="select" aria-pressed="true">
          <span class="pe-tool-icon"><i data-lucide="mouse-pointer-2"></i></span><span class="pe-tool-label">Selecionar e mover</span><kbd>V</kbd>
        </button>
        <span class="pe-group">Marcar ponto</span>
        ${pointButtons}
        <span class="pe-group">Puxar cabo</span>
        ${cableButtons}
        <label class="pe-check"><input type="checkbox" id="peAutoPole" checked> Clique fora de um ponto vira poste</label>
        <div class="pe-coord">
          <span class="pe-group">Marcar por posicao</span>
          <label class="sr-only" for="peCoordInput">Coordenada</label>
          <input id="peCoordInput" placeholder="-9.665123, -35.735456" autocomplete="off">
          <div class="pe-coord-actions">
            <button type="button" class="secondary-action" onclick="planningEditorPlaceTyped()"><i data-lucide="map-pin"></i> Marcar</button>
            <button type="button" class="secondary-action" onclick="planningEditorPlaceGps()"><i data-lucide="locate-fixed"></i> Meu GPS</button>
          </div>
          <small id="peCoordHint">Cole do Google Maps ou use o GPS do celular no local.</small>
        </div>
      </aside>
      <section class="pe-map-area">
        <div id="planningEditorMap" class="pe-map"></div>
        <div class="pe-hud hidden" id="peHud" aria-live="polite"></div>
        <div class="pe-help" id="peHelp"></div>
      </section>
      <aside class="pe-side" id="peSide" aria-label="Rotas"></aside>
    </div>
  </div>`;
}

function openPlanningRouteEditor() {
  if (!_planningCurrent || typeof L === 'undefined') return;
  let root = document.getElementById('planningEditor');
  if (!root) {
    document.body.insertAdjacentHTML('beforeend', planningEditorMarkup());
    root = document.getElementById('planningEditor');
    root.querySelectorAll('[data-pe-tool]').forEach(button => button.addEventListener('click', () => planningEditorSetTool(button.dataset.peTool)));
    document.getElementById('peCoordInput').addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); planningEditorPlaceTyped(); } });
    document.addEventListener('keydown', planningEditorKeydown);
  }
  root.classList.remove('hidden');
  document.body.classList.add('pe-open');
  document.getElementById('peProjectName').textContent = _planningCurrent.name;
  if (typeof lucide !== 'undefined') lucide.createIcons();
  if (!_pe) {
    const map = L.map('planningEditorMap', { zoomControl: true, doubleClickZoom: false, maxZoom: 21 });
    const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 21, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 21, maxNativeZoom: 19, attribution: 'Imagens &copy; Esri' });
    satellite.addTo(map);
    L.control.layers({ Satelite: satellite, Mapa: streets }, null, { position: 'topright' }).addTo(map);
    map.on('click', event => planningEditorClick(event.latlng, null));
    map.on('mousemove', event => planningEditorMouseMove(event.latlng));
    map.on('dblclick', () => planningEditorFinish());
    _pe = { map, tool: 'select', drawing: null, selectedRouteId: null, groups: {}, markers: {}, fitted: false };
  }
  _pe.fitted = false;
  _pe.selectedRouteId = null;
  planningEditorSetTool('select');
  planningEditorRender();
  setTimeout(() => _pe.map.invalidateSize(), 60);
}

function closePlanningRouteEditor() {
  if (_pe?.drawing) planningEditorCancel();
  document.getElementById('planningEditor')?.classList.add('hidden');
  document.body.classList.remove('pe-open');
  if (_planningCurrent) {
    renderPlanningDetail();
    setTimeout(() => renderPlanningMap(), 50);
  }
}

function planningEditorOpen() {
  return !!document.getElementById('planningEditor') && !document.getElementById('planningEditor').classList.contains('hidden');
}

// ---------------------------------------------------------------------------
// Ferramentas e teclado
// ---------------------------------------------------------------------------

function planningEditorSetTool(tool) {
  if (!_pe) return;
  if (_pe.drawing && tool !== _pe.drawing.kind) planningEditorCancel();
  _pe.tool = tool;
  document.querySelectorAll('#planningEditor [data-pe-tool]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.peTool === tool)));
  const container = _pe.map.getContainer();
  container.classList.toggle('pe-crosshair', tool !== 'select');
  planningEditorRenderPoints();
  planningEditorHelp();
}

function planningEditorKeydown(event) {
  if (!planningEditorOpen() || !_pe) return;
  const tag = String(event.target?.tagName || '').toLowerCase();
  if (['input', 'select', 'textarea'].includes(tag)) return;
  if (document.getElementById('planningModal') && !document.getElementById('planningModal').classList.contains('hidden')) return;
  if (event.key === 'Escape') { event.preventDefault(); if (_pe.drawing) planningEditorCancel(); else planningEditorSetTool('select'); return; }
  if (event.key === 'Enter' && _pe.drawing) { event.preventDefault(); planningEditorFinish(); return; }
  if (event.key === 'Backspace' && _pe.drawing) { event.preventDefault(); planningEditorUndoPoint(); return; }
  if ((event.key === 'Delete' || event.key === 'Backspace') && _pe.selectedRouteId) { event.preventDefault(); planningEditorDeleteRoute(_pe.selectedRouteId); return; }
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const key = event.key.toUpperCase();
  if (key === 'V') { planningEditorSetTool('select'); return; }
  const point = Object.entries(PLANNING_POINT_TOOLS).find(([, cfg]) => cfg.key === key);
  if (point) { planningEditorSetTool(point[0]); return; }
  const cable = Object.entries(PLANNING_ROUTE_KINDS).find(([, cfg]) => cfg.key === key);
  if (cable) planningEditorSetTool(cable[0]);
}

function planningEditorHelp() {
  const help = document.getElementById('peHelp');
  if (!help || !_pe) return;
  const tool = _pe.tool;
  let text;
  if (tool === 'select') text = 'Clique num ponto para ver e editar. Arraste para corrigir a posicao. Clique numa linha para ver a rota.';
  else if (PLANNING_POINT_TOOLS[tool]) text = `Clique no mapa onde fica ${PLANNING_POINT_TOOLS[tool].label.toLowerCase()}. Cada clique marca um. Esc volta para selecionar.`;
  else if (_pe.drawing) text = 'Clique em cada poste do caminho (clique livre cria o poste). Clique no equipamento de destino para terminar, ou Enter. Backspace volta, Esc cancela.';
  else text = `${PLANNING_ROUTE_KINDS[tool].label}: clique no equipamento de onde o cabo sai.`;
  help.textContent = text;
}

// ---------------------------------------------------------------------------
// Desenho
// ---------------------------------------------------------------------------

function planningEditorDevices() {
  return (_planningCurrent?.devices || []).filter(item => planningHasCoords(item));
}

// Equipamento que fica dentro da caixa repete a coordenada dela; no mapa so
// a caixa aparece.
function planningEditorVisibleDevices() {
  const devices = _planningCurrent?.devices || [];
  const byId = new Map(devices.map(item => [Number(item.id), item]));
  const insideBox = item => {
    let current = item; const seen = new Set();
    while (current?.parent_id && !seen.has(Number(current.parent_id))) {
      seen.add(Number(current.parent_id));
      current = byId.get(Number(current.parent_id));
      if (current?.device_type === 'box') return true;
    }
    return false;
  };
  return planningEditorDevices().filter(item => !['onu', 'ont', 'switch', 'injector', 'recorder'].includes(item.device_type) || !insideBox(item));
}

function planningEditorRender() {
  if (!_pe) return;
  planningEditorRenderRoutes();
  planningEditorRenderPoints();
  planningEditorRenderSide();
  planningEditorRenderTotals();
  planningEditorHelp();
  if (!_pe.fitted) {
    const points = planningEditorDevices().map(item => [Number(item.latitude), Number(item.longitude)]);
    planningRoutes().forEach(route => route.path.forEach(pt => points.push([pt.lat, pt.lon])));
    if (points.length) _pe.map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 19 });
    else _pe.map.setView([-9.66, -35.73], 15);
    _pe.fitted = true;
  }
}

function planningEditorRenderRoutes() {
  _pe.groups.routes?.remove();
  _pe.groups.routes = L.layerGroup().addTo(_pe.map);
  planningRoutes().forEach(route => {
    const cfg = PLANNING_ROUTE_KINDS[route.kind] || PLANNING_ROUTE_KINDS.utp;
    const latlngs = route.path.map(pt => [pt.lat, pt.lon]);
    const selected = Number(route.id) === Number(_pe.selectedRouteId);
    if (selected) L.polyline(latlngs, { color: '#fff6df', weight: cfg.weight + 12, opacity: .9, interactive: false }).addTo(_pe.groups.routes);
    const over = route.kind === 'utp' && Number(route.length_m) + Number(route.slack_m || 0) > 100;
    const line = L.polyline(latlngs, { color: over ? '#c92a2a' : cfg.color, weight: cfg.weight + (selected ? 1 : 0), dashArray: cfg.dash, lineCap: 'round', lineJoin: 'round' })
      .bindTooltip(`${cfg.label} · ${Math.round(route.length_m)} m`, { sticky: true })
      .addTo(_pe.groups.routes);
    // Linha fina e larga por cima: facil de clicar mesmo tracejada.
    L.polyline(latlngs, { color: '#000', opacity: 0, weight: 16 })
      .on('click', event => { L.DomEvent.stopPropagation(event); if (_pe.tool === 'select') planningEditorSelectRoute(route.id); else planningEditorClick(event.latlng, null); })
      .addTo(_pe.groups.routes);
    if (selected) {
      route.segments_m.forEach((meters, index) => {
        const a = route.path[index]; const b = route.path[index + 1];
        L.marker([(a.lat + b.lat) / 2, (a.lon + b.lon) / 2], {
          interactive: false,
          icon: L.divIcon({ className: 'pe-seg-label', html: `<span>${Math.round(meters)} m</span>`, iconSize: [48, 18], iconAnchor: [24, 9] }),
        }).addTo(_pe.groups.routes);
      });
    }
    void line;
  });
}

function planningEditorRenderPoints() {
  if (!_pe) return;
  _pe.groups.points?.remove();
  _pe.groups.points = L.layerGroup().addTo(_pe.map);
  _pe.markers = {};
  const a = planningAnalyze();
  const boxState = new Map(a.boxInfo.map(info => [Number(info.box.id), info.state]));
  const draggable = _pe.tool === 'select';
  planningEditorVisibleDevices().forEach(item => {
    let kind = planningPointKind(item);
    let label = '';
    if (kind === 'box') {
      const state = boxState.get(Number(item.id));
      kind = state === 'danger' ? 'box-danger' : state === 'full' ? 'box-full' : 'box';
      label = planningShortLabel(item.name);
    }
    if (kind === 'camera' && a.cableByCamera.get(Number(item.id))?.overLimit) kind = 'camera-danger';
    const marker = L.marker([Number(item.latitude), Number(item.longitude)], {
      icon: planningMapIcon(kind, label), draggable, autoPan: true, keyboard: false,
      title: `${item.name} (${PLANNING_TYPES[planningPointKind(item)] || PLANNING_TYPES[item.device_type] || item.device_type})`,
      zIndexOffset: kind === 'pole' ? 0 : 500,
    });
    marker.on('click', event => { L.DomEvent.stopPropagation(event); planningEditorClick(event.latlng, item); });
    marker.on('dragend', () => planningEditorMoveDevice(item, marker.getLatLng()));
    marker.addTo(_pe.groups.points);
    _pe.markers[item.id] = marker;
  });
}

function planningEditorNearest(latlng) {
  if (!_pe) return null;
  const point = _pe.map.latLngToContainerPoint(latlng);
  let best = null; let bestDistance = PLANNING_SNAP_PX;
  planningEditorVisibleDevices().forEach(item => {
    const other = _pe.map.latLngToContainerPoint([Number(item.latitude), Number(item.longitude)]);
    const distance = point.distanceTo(other);
    if (distance < bestDistance) { best = item; bestDistance = distance; }
  });
  return best;
}

// Cliques entram numa fila: criar o poste vai ao servidor, e dois cliques
// rapidos nao podem chegar fora de ordem no tracado.
function planningEditorClick(latlng, device) {
  if (!_pe) return Promise.resolve();
  _pe.queue = (_pe.queue || Promise.resolve()).then(() => planningEditorClickNow(latlng, device)).catch(() => {});
  return _pe.queue;
}

async function planningEditorClickNow(latlng, device) {
  if (!_pe) return;
  const tool = _pe.tool;
  if (tool === 'select') {
    if (device) planningEditorDeviceMenu(device);
    else planningEditorSelectRoute(null);
    return;
  }
  if (PLANNING_POINT_TOOLS[tool]) {
    // Clicou em cima de um equipamento existente com ferramenta de ponto:
    // abre ele em vez de empilhar outro no mesmo lugar.
    if (device) { planningEditorDeviceMenu(device); return; }
    await planningEditorCreatePoint(tool, latlng.lat, latlng.lng);
    return;
  }
  if (PLANNING_ROUTE_KINDS[tool]) {
    const snapped = device || planningEditorNearest(latlng);
    if (!_pe.drawing) {
      if (!snapped) { planningEditorFlash('Comece clicando no equipamento de onde o cabo sai.'); return; }
      _pe.drawing = { kind: tool, points: [{ lat: Number(snapped.latitude), lon: Number(snapped.longitude), device_id: Number(snapped.id), device: snapped }] };
      planningEditorDrawPreview();
      planningEditorHelp();
      return;
    }
    const last = _pe.drawing.points[_pe.drawing.points.length - 1];
    if (snapped && Number(snapped.id) === Number(last.device_id)) return;
    let target = snapped;
    // Na pratica todo vertice do cabo e um poste: clique livre ja cria o poste.
    if (!target && document.getElementById('peAutoPole')?.checked) {
      const drawing = _pe.drawing;
      target = await planningEditorCreatePoint('pole', latlng.lat, latlng.lng);
      if (_pe.drawing !== drawing) return;
    }
    const point = target
      ? { lat: Number(target.latitude), lon: Number(target.longitude), device_id: Number(target.id), device: target }
      : { lat: latlng.lat, lon: latlng.lng, device_id: null };
    _pe.drawing.points.push(point);
    planningEditorDrawPreview();
    // Chegou num equipamento que nao e poste: o cabo termina ali.
    if (target && target.device_type !== 'pole') await planningEditorFinish();
  }
}

function planningEditorMouseMove(latlng) {
  if (!_pe?.drawing) return;
  _pe.cursor = latlng;
  planningEditorDrawPreview();
}

function planningEditorDrawPreview() {
  if (!_pe) return;
  _pe.groups.preview?.remove();
  _pe.groups.preview = L.layerGroup().addTo(_pe.map);
  const hud = document.getElementById('peHud');
  if (!_pe.drawing) { hud?.classList.add('hidden'); return; }
  const cfg = PLANNING_ROUTE_KINDS[_pe.drawing.kind];
  const pts = _pe.drawing.points;
  const latlngs = pts.map(pt => [pt.lat, pt.lon]);
  if (latlngs.length > 1) L.polyline(latlngs, { color: cfg.color, weight: cfg.weight, dashArray: cfg.dash, interactive: false }).addTo(_pe.groups.preview);
  let total = 0;
  for (let i = 1; i < pts.length; i += 1) total += planningDistanceMeters(pts[i - 1].lat, pts[i - 1].lon, pts[i].lat, pts[i].lon);
  let segment = 0; let snapName = '';
  const last = pts[pts.length - 1];
  if (_pe.cursor) {
    const snap = planningEditorNearest(_pe.cursor);
    const target = snap ? [Number(snap.latitude), Number(snap.longitude)] : [_pe.cursor.lat, _pe.cursor.lng];
    snapName = snap ? snap.name : '';
    segment = planningDistanceMeters(last.lat, last.lon, target[0], target[1]);
    L.polyline([[last.lat, last.lon], target], { color: cfg.color, weight: 2, dashArray: '4 6', opacity: .8, interactive: false }).addTo(_pe.groups.preview);
    if (snap) L.circleMarker(target, { radius: 16, color: cfg.color, weight: 2, fill: false, interactive: false }).addTo(_pe.groups.preview);
  }
  pts.forEach(pt => L.circleMarker([pt.lat, pt.lon], { radius: 4, color: '#fff', weight: 2, fillColor: cfg.color, fillOpacity: 1, interactive: false }).addTo(_pe.groups.preview));
  const from = pts[0].device?.name || 'origem';
  const limit = _pe.drawing.kind === 'utp' && total + segment > 90
    ? `<span class="pe-hud-warn">${total + segment > 100 ? 'Passa de 100 m de UTP' : 'Perto do limite de 100 m'}</span>` : '';
  if (hud) {
    hud.classList.remove('hidden');
    hud.innerHTML = `<strong>${cfg.label} · ${planningEscape(from)}</strong>
      <span>${snapName ? `Gruda em <b>${planningEscape(snapName)}</b> · ` : ''}trecho ${Math.round(segment)} m</span>
      <span>Total ${Math.round(total + segment)} m · ${pts.length} ponto(s)</span>${limit}`;
  }
}

function planningEditorUndoPoint() {
  if (!_pe?.drawing) return;
  _pe.drawing.points.pop();
  if (!_pe.drawing.points.length) { planningEditorCancel(); return; }
  planningEditorDrawPreview();
}

function planningEditorCancel() {
  if (!_pe) return;
  _pe.drawing = null;
  _pe.cursor = null;
  planningEditorDrawPreview();
  planningEditorHelp();
}

async function planningEditorFinish() {
  if (!_pe?.drawing) return;
  const drawing = _pe.drawing;
  if (drawing.points.length < 2) { planningEditorFlash('Marque pelo menos mais um ponto.'); return; }
  const cfg = PLANNING_ROUTE_KINDS[drawing.kind];
  const first = drawing.points[0];
  const last = drawing.points[drawing.points.length - 1];
  const payload = {
    kind: drawing.kind,
    from_device_id: first.device_id,
    to_device_id: last.device && last.device.device_type !== 'pole' ? last.device_id : null,
    path: drawing.points.map(pt => ({ lat: pt.lat, lon: pt.lon, device_id: pt.device_id })),
    cable_model: cfg.cable, fiber_count: cfg.fibers, slack_m: cfg.slack,
  };
  _pe.drawing = null; _pe.cursor = null;
  planningEditorDrawPreview();
  await planningEditorSave(async () => {
    const data = await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/routes`, { method: 'POST', body: JSON.stringify(payload) });
    _planningCurrent.routes = [...planningRoutes(), data.item];
    _pe.selectedRouteId = data.item.id;
  });
  planningEditorRender();
}

// ---------------------------------------------------------------------------
// Pontos
// ---------------------------------------------------------------------------

function planningEditorNextName(tool) {
  const cfg = PLANNING_POINT_TOOLS[tool];
  const used = (_planningCurrent?.devices || [])
    .filter(item => String(item.name || '').toUpperCase().startsWith(cfg.prefix.toUpperCase()))
    .map(item => Number(String(item.name).slice(cfg.prefix.length).match(/^\d+/)?.[0] || 0));
  const next = (used.length ? Math.max(...used) : 0) + 1;
  return `${cfg.prefix}${String(next).padStart(2, '0')}`;
}

function planningParseDevice(item) {
  if (!item) return item;
  if (!item.metadata) {
    try { item.metadata = JSON.parse(item.metadata_json || '{}'); } catch (_error) { item.metadata = {}; }
  }
  return item;
}

async function planningEditorCreatePoint(tool, lat, lon) {
  const cfg = PLANNING_POINT_TOOLS[tool];
  const site = (_planningCurrent.sites || [])[0];
  const payload = {
    device_type: cfg.type, name: planningEditorNextName(tool), site_id: site ? site.id : null,
    latitude: Number(lat.toFixed(7)), longitude: Number(lon.toFixed(7)), metadata: { ...cfg.metadata }, status: 'planned',
  };
  let created = null;
  await planningEditorSave(async () => {
    const data = await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/devices`, { method: 'POST', body: JSON.stringify(payload) });
    created = planningParseDevice({ ...data.item, site_name: site?.name || null });
    _planningCurrent.devices = [...(_planningCurrent.devices || []), created];
  });
  planningEditorRenderPoints();
  planningEditorRenderTotals();
  return created;
}

async function planningEditorMoveDevice(item, latlng) {
  const lat = Number(latlng.lat.toFixed(7)); const lon = Number(latlng.lng.toFixed(7));
  await planningEditorSave(async () => {
    await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/devices/${Number(item.id)}/position`, { method: 'PUT', body: JSON.stringify({ latitude: lat, longitude: lon }) });
    item.latitude = lat; item.longitude = lon;
    await planningEditorReloadRoutes();
  });
  planningEditorRender();
}

async function planningEditorReloadRoutes() {
  const data = await apiJson(`/api/planning/projects/${Number(_planningCurrent.id)}`, { forceRefresh: true, cacheTtl: 0 });
  if (data?.item) {
    _planningCurrent.routes = data.item.routes || [];
    _planningCurrent.devices = data.item.devices || _planningCurrent.devices;
  }
}

function planningEditorDeviceMenu(item) {
  const marker = _pe?.markers[item.id];
  if (!marker) return;
  const kind = planningPointKind(item);
  const routes = planningRoutes().filter(route => route.path.some(pt => Number(pt.device_id) === Number(item.id)));
  const coords = `${Number(item.latitude).toFixed(6)}, ${Number(item.longitude).toFixed(6)}`;
  marker.unbindPopup();
  marker.bindPopup(`<div class="pe-pop">
      <span class="pe-pop-icon">${planningIconSvg(kind === 'box' ? 'box' : kind)}</span>
      <strong>${planningEscape(item.name)}</strong>
      <small>${planningEscape(PLANNING_TYPES[kind] || PLANNING_TYPES[item.device_type] || item.device_type)}${item.model ? ` · ${planningEscape(item.model)}` : ''}</small>
      <code>${coords}</code>
      ${routes.length ? `<small>${routes.length} cabo(s) passam aqui</small>` : ''}
      <div class="pe-pop-actions">
        <button type="button" onclick="planningEditorEditDevice(${Number(item.id)})">Editar dados</button>
        <button type="button" class="danger" onclick="planningEditorDeleteDevice(${Number(item.id)})">Apagar</button>
      </div>
    </div>`, { minWidth: 200 }).openPopup();
}

async function planningEditorEditDevice(deviceId) {
  _pe?.map.closePopup();
  await openPlanningDeviceModal(deviceId);
}

async function planningEditorDeleteDevice(deviceId) {
  const item = (_planningCurrent?.devices || []).find(row => Number(row.id) === Number(deviceId));
  if (!item) return;
  _pe?.map.closePopup();
  if (!await showConfirm({ eyebrow: 'Projeto', title: `Apagar ${item.name}?`, msg: 'Os cabos que passam por ele continuam no mesmo lugar.', label: 'Apagar' })) return;
  await planningEditorSave(async () => {
    await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/devices/${Number(deviceId)}`, { method: 'DELETE' });
    await planningEditorReloadRoutes();
  });
  planningEditorRender();
}

function planningEditorParseCoords(text) {
  const match = String(text || '').trim().match(/^(-?\d+(?:[.,]\d+)?)\s*[,; ]\s*(-?\d+(?:[.,]\d+)?)$/);
  if (!match) return null;
  const lat = Number(match[1].replace(',', '.')); const lon = Number(match[2].replace(',', '.'));
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
}

async function planningEditorPlaceAt(lat, lon, source) {
  if (!_pe) return;
  _pe.map.setView([lat, lon], Math.max(_pe.map.getZoom(), 18));
  const hint = document.getElementById('peCoordHint');
  if (PLANNING_POINT_TOOLS[_pe.tool]) {
    await planningEditorCreatePoint(_pe.tool, lat, lon);
    if (hint) hint.textContent = `${PLANNING_POINT_TOOLS[_pe.tool].label} marcado ${source}.`;
  } else if (PLANNING_ROUTE_KINDS[_pe.tool]) {
    await planningEditorClick(L.latLng(lat, lon), planningEditorNearest(L.latLng(lat, lon)));
  } else if (hint) {
    hint.textContent = 'Mapa centralizado. Escolha um tipo de ponto (Poste, CTO...) para marcar ali.';
  }
}

async function planningEditorPlaceTyped() {
  const input = document.getElementById('peCoordInput');
  const coords = planningEditorParseCoords(input?.value);
  const hint = document.getElementById('peCoordHint');
  if (!coords) { if (hint) hint.textContent = 'Formato: latitude, longitude. Ex: -9.665123, -35.735456'; return; }
  await planningEditorPlaceAt(coords.lat, coords.lon, 'pela coordenada');
  if (input) input.value = '';
}

function planningEditorPlaceGps() {
  const hint = document.getElementById('peCoordHint');
  if (!navigator.geolocation) { if (hint) hint.textContent = 'Este aparelho nao informa a localizacao.'; return; }
  if (hint) hint.textContent = 'Pegando a localizacao...';
  navigator.geolocation.getCurrentPosition(
    position => {
      const { latitude, longitude, accuracy } = position.coords;
      planningEditorPlaceAt(latitude, longitude, `pelo GPS (precisao ~${Math.round(accuracy)} m)`);
    },
    error => { if (hint) hint.textContent = error.code === 1 ? 'Permissao de localizacao negada no navegador.' : 'Nao foi possivel pegar a localizacao.'; },
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
  );
}

// ---------------------------------------------------------------------------
// Painel lateral e totais
// ---------------------------------------------------------------------------

function planningDeviceName(id) {
  const item = (_planningCurrent?.devices || []).find(row => Number(row.id) === Number(id));
  return item ? item.name : '';
}

function planningEditorSelectRoute(routeId) {
  if (!_pe) return;
  _pe.selectedRouteId = routeId ? Number(routeId) : null;
  planningEditorRenderRoutes();
  planningEditorRenderSide();
}

function planningEditorRenderTotals() {
  const box = document.getElementById('peTotals');
  if (!box) return;
  const sum = kind => planningRoutes().filter(route => route.kind === kind).reduce((total, route) => total + Number(route.length_m || 0), 0);
  const poles = (_planningCurrent?.devices || []).filter(item => item.device_type === 'pole').length;
  box.innerHTML = `
    <span><b>${planningFormatMeters(sum('fiber_main'))}</b> fibra principal</span>
    <span><b>${planningFormatMeters(sum('fiber_drop'))}</b> drop</span>
    <span><b>${planningFormatMeters(sum('utp'))}</b> UTP</span>
    <span><b>${poles}</b> poste(s)</span>`;
}

function planningEditorRenderSide() {
  const side = document.getElementById('peSide');
  if (!side || !_pe) return;
  const route = planningRoutes().find(item => Number(item.id) === Number(_pe.selectedRouteId));
  if (!route) {
    const rows = planningRoutes().map(item => {
      const cfg = PLANNING_ROUTE_KINDS[item.kind];
      return `<button type="button" class="pe-route-row" onclick="planningEditorSelectRoute(${Number(item.id)})">
        ${planningLineSwatch(item.kind)}
        <span><strong>${planningEscape(planningDeviceName(item.from_device_id) || 'Ponto livre')} → ${planningEscape(planningDeviceName(item.to_device_id) || 'Ponto livre')}</strong><small>${cfg.label}</small></span>
        <b>${Math.round(item.length_m)} m</b>
      </button>`;
    }).join('');
    side.innerHTML = `
      <div class="pe-side-head"><h2>Rotas do projeto</h2><span>${planningRoutes().length} cabo(s) tracado(s)</span></div>
      ${rows ? `<div class="pe-route-list">${rows}</div>` : `<div class="pe-empty"><strong>Nenhum cabo tracado ainda.</strong><span>Marque os postes, escolha <b>Fibra principal</b> e clique da OLT ate a CTO passando pelos postes.</span></div>`}
      <div class="pe-howto"><strong>Como puxar um cabo</strong><span>1. Escolha o tipo de cabo (F, D ou U).</span><span>2. Clique no equipamento de origem.</span><span>3. Clique em cada poste do caminho: o cabo gruda nele.</span><span>4. Clique no equipamento de destino ou tecle Enter.</span></div>`;
    return;
  }
  const cfg = PLANNING_ROUTE_KINDS[route.kind];
  const cableOptions = PLANNING_ROUTE_CABLES[route.kind].concat(PLANNING_ROUTE_CABLES[route.kind].includes(route.cable_model) || !route.cable_model ? [] : [route.cable_model]);
  const poles = route.path.filter(pt => pt.device_id && (_planningCurrent.devices || []).find(item => Number(item.id) === Number(pt.device_id))?.device_type === 'pole').length;
  const purchase = planningRoutePurchase(route);
  const over = route.kind === 'utp' && Number(route.length_m) + Number(route.slack_m || 0) > 100;
  const segRows = route.segments_m.map((meters, index) => {
    const a = route.path[index]; const b = route.path[index + 1];
    const name = pt => planningDeviceName(pt.device_id) || 'ponto sem poste';
    return `<div class="pe-seg"><span>${planningEscape(name(a))} → ${planningEscape(name(b))}</span><b>${Math.round(meters)} m</b></div>`;
  }).join('');
  side.innerHTML = `
    <div class="pe-side-head">
      <button type="button" class="pj-link" onclick="planningEditorSelectRoute(null)">← Todas as rotas</button>
      <span class="pe-kind" style="color:${cfg.color}">${planningLineSwatch(route.kind)} ${cfg.label}</span>
      <h2>${planningEscape(planningDeviceName(route.from_device_id) || 'Ponto livre')} → ${planningEscape(planningDeviceName(route.to_device_id) || 'Ponto livre')}</h2>
    </div>
    <div class="pe-form">
      <label><span>Cabo</span><select id="peRouteCable">${cableOptions.map(option => `<option ${option === route.cable_model ? 'selected' : ''}>${planningEscape(option)}</option>`).join('')}</select></label>
      ${route.kind !== 'utp' ? `<label><span>Fibras no cabo</span><input id="peRouteFibers" type="number" min="0" max="288" value="${Number(route.fiber_count || 0)}"></label>` : ''}
      <label><span>Sobra tecnica (m)</span><input id="peRouteSlack" type="number" min="0" max="1000" step="1" value="${Number(route.slack_m || 0)}"></label>
      <button type="button" class="secondary-action" onclick="planningEditorSaveRouteFields(${Number(route.id)})">Salvar</button>
    </div>
    <div class="pe-metrics">
      <div><span>Tracado no mapa</span><strong>${Math.round(route.length_m)} m</strong></div>
      <div class="${over ? 'danger' : 'buy'}"><span>Para comprar</span><strong>${Math.round(purchase)} m</strong></div>
    </div>
    <p class="pe-note">${Math.round(route.length_m)} m tracados + ${Math.round(route.slack_m || 0)} m de sobra + ${Math.round(PLANNING_ROUTE_RESERVE * 100)}% de reserva. Passa por ${poles} poste(s).${over ? ' <b>Passa de 100 m: o UTP nao garante o sinal.</b>' : ''}</p>
    <div class="pe-segs"><span class="pe-group">Trechos</span>${segRows}</div>
    <div class="pe-side-foot">
      <button type="button" class="secondary-action danger-text" onclick="planningEditorDeleteRoute(${Number(route.id)})"><i data-lucide="trash-2"></i> Apagar rota</button>
    </div>`;
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

async function planningEditorSaveRouteFields(routeId) {
  const route = planningRoutes().find(item => Number(item.id) === Number(routeId));
  if (!route) return;
  const payload = {
    kind: route.kind, from_device_id: route.from_device_id, to_device_id: route.to_device_id, name: route.name || '',
    path: route.path.map(pt => ({ lat: pt.lat, lon: pt.lon, device_id: pt.device_id })),
    cable_model: document.getElementById('peRouteCable')?.value || route.cable_model,
    fiber_count: Number(document.getElementById('peRouteFibers')?.value ?? route.fiber_count ?? 0),
    slack_m: Number(document.getElementById('peRouteSlack')?.value ?? route.slack_m ?? 0),
    notes: route.notes || '', metadata: route.metadata || {},
  };
  await planningEditorSave(async () => {
    const data = await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/routes/${Number(routeId)}`, { method: 'PUT', body: JSON.stringify(payload) });
    _planningCurrent.routes = planningRoutes().map(item => (Number(item.id) === Number(routeId) ? data.item : item));
  });
  planningEditorRender();
}

async function planningEditorDeleteRoute(routeId) {
  if (!await showConfirm({ eyebrow: 'Projeto', title: 'Apagar esta rota?', msg: 'Os postes e equipamentos continuam no mapa.', label: 'Apagar rota' })) return;
  await planningEditorSave(async () => {
    await planningRequest(`/api/planning/projects/${Number(_planningCurrent.id)}/routes/${Number(routeId)}`, { method: 'DELETE' });
    _planningCurrent.routes = planningRoutes().filter(item => Number(item.id) !== Number(routeId));
  });
  _pe.selectedRouteId = null;
  planningEditorRender();
}

// Toda gravacao passa por aqui: mostra "Salvando..." e o erro de verdade.
async function planningEditorSave(work) {
  const label = document.getElementById('peSaved');
  if (label) { label.textContent = 'Salvando...'; label.classList.remove('is-error'); }
  try {
    await work();
    if (label) label.textContent = 'Tudo salvo';
  } catch (error) {
    if (label) { label.textContent = 'Nao salvou'; label.classList.add('is-error'); }
    showToast(error.message || 'Nao foi possivel salvar.', true);
  }
}

function planningEditorFlash(text) {
  const help = document.getElementById('peHelp');
  if (!help) return;
  help.textContent = text;
  help.classList.add('is-flash');
  setTimeout(() => { help.classList.remove('is-flash'); planningEditorHelp(); }, 2200);
}
