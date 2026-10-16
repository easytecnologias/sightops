// Implantacao > Projetos: fibra optica do projeto.
// - Cores ABNT das fibras e ramais (verde, amarelo, branco, azul...).
// - Grafo do cabo (rotas tracadas) para calcular, trecho a trecho, qual
//   fibra esta ativa e para onde vai -- o que hoje se escreve a mao no KMZ.
// - Potencia prevista em cada CTO (orcamento optico) x potencia medida.
// - Cartao da CTO/CDO: splitter, quem alimenta, porta a porta.
// - "Novo projeto": em branco ou importando a rede do Google Earth.

// Cor fisica da fibra (fica fora da paleta do sistema de proposito: e a cor
// do tubete/fibra na norma, que o tecnico ve na caixa).
const PLANNING_FIBER_HEX = {
  verde: '#2f9e44', amarelo: '#f2c200', branco: '#f8f9fa', azul: '#1971c2', vermelho: '#e03131', lilas: '#9c36b5',
  marrom: '#8b5a2b', rosa: '#f06595', preto: '#212529', cinza: '#868e96', laranja: '#f76707', agua: '#15aabf',
};
const PLANNING_FIBER_ORDER = ['verde', 'amarelo', 'branco', 'azul', 'vermelho', 'lilas', 'marrom', 'rosa', 'preto', 'cinza', 'laranja', 'agua'];
// Perdas tipicas usadas no orcamento optico (dB). Ajustaveis depois.
const PLANNING_OPTICS = {
  oltTxDbm: 5, oltClass: 'C+', fiberDbPerKm: 0.35, splice: 0.1, connector: 0.5,
  splitter: { 2: 3.7, 4: 7.3, 8: 10.5, 16: 13.7, 32: 17.1 },
  onuMinDbm: -27,
};

function planningFiberLabel(color) {
  const key = String(color || '').toLowerCase();
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : '';
}

function planningFiberDot(color) {
  const hex = PLANNING_FIBER_HEX[String(color || '').toLowerCase()] || '#adb5bd';
  return `<span class="pf-dot" style="background:${hex}" title="Fibra ${planningEscape(planningFiberLabel(color))}"></span>`;
}

function planningFiberChip(color, text = '') {
  const key = String(color || '').toLowerCase();
  const hex = PLANNING_FIBER_HEX[key] || '#adb5bd';
  return `<span class="pf-chip"><i style="background:${hex}"></i>${planningEscape(text || planningFiberLabel(key) || 'Sem cor')}</span>`;
}

function planningFeedColor(item) {
  const list = Array.isArray(item?.metadata?.cor_fibra) ? item.metadata.cor_fibra : [];
  return String(list[0] || '').toLowerCase();
}

// Splitter de verdade: o informado (1x8, 1x16) ou, na CTO terminal, o numero
// de portas. CDO sem splitter no cadastro e emenda de passagem: nao soma perda.
function planningSplitterOf(item) {
  const text = String(item?.metadata?.splitter || '');
  const match = text.match(/1\s*x\s*(\d+)/i);
  if (match) return Number(match[1]);
  if (item?.device_type === 'cto' && item?.metadata?.papel !== 'splitter_primario') return Number(item?.metadata?.port_capacity || 0) || 0;
  return 0;
}

// ---------------------------------------------------------------------------
// Grafo do cabo e ocupacao das fibras por trecho
// ---------------------------------------------------------------------------

function planningCableGraph() {
  const routes = (_planningCurrent?.routes || []).filter(route => route.kind !== 'utp');
  const graph = new Map();
  const add = (a, b, routeId, meters) => {
    if (!graph.has(a)) graph.set(a, []);
    graph.get(a).push({ to: b, routeId, meters });
  };
  routes.forEach(route => {
    let prev = null; let acc = 0;
    route.path.forEach((pt, index) => {
      if (index > 0) acc += Number(route.segments_m?.[index - 1] || 0);
      if (!pt.device_id) return;
      const id = Number(pt.device_id);
      if (prev !== null && prev !== id) { add(prev, id, route.id, acc); add(id, prev, route.id, acc); }
      prev = id; acc = 0;
    });
  });
  return graph;
}

// Caminho mais curto (em metros) entre dois equipamentos pelo cabo. As
// distancias a partir de cada origem ficam em cache: muitas CTOs saem do
// mesmo CDO, e o mapa inteiro e recalculado a cada desenho.
function planningCableTree(graph, startId, cache) {
  const start = Number(startId);
  if (cache?.has(start)) return cache.get(start);
  const dist = new Map([[start, 0]]); const prev = new Map(); const done = new Set();
  const frontier = [start];
  while (frontier.length) {
    let bestIndex = 0;
    for (let i = 1; i < frontier.length; i += 1) if (dist.get(frontier[i]) < dist.get(frontier[bestIndex])) bestIndex = i;
    const node = frontier.splice(bestIndex, 1)[0];
    if (done.has(node)) continue;
    done.add(node);
    (graph.get(node) || []).forEach(edge => {
      const next = dist.get(node) + edge.meters;
      if (next < (dist.get(edge.to) ?? Infinity)) {
        dist.set(edge.to, next); prev.set(edge.to, { from: node, routeId: edge.routeId }); frontier.push(edge.to);
      }
    });
  }
  const tree = { dist, prev };
  cache?.set(start, tree);
  return tree;
}

function planningCablePath(graph, fromId, toId, cache = null) {
  const start = Number(fromId); const goal = Number(toId);
  if (!graph.has(start) || !graph.has(goal)) return null;
  const { dist, prev } = planningCableTree(graph, start, cache);
  if (!dist.has(goal)) return null;
  const routeIds = new Set();
  let cursor = goal;
  while (prev.has(cursor)) { const step = prev.get(cursor); routeIds.add(Number(step.routeId)); cursor = step.from; }
  return { meters: dist.get(goal), routeIds };
}

// { routeId: { cor: { label, target } } } -- calculado de quem e alimentado
// por qual cor: CTO pela cor fundida no CDO pai; CDO pela cor que leva o
// link ate ele.
function planningFiberOccupancy() {
  const devices = _planningCurrent?.devices || [];
  const byId = new Map(devices.map(item => [Number(item.id), item]));
  const graph = planningCableGraph();
  const cache = new Map();
  const occupancy = {};
  const feeds = {};
  devices.filter(item => item.device_type === 'cto').forEach(item => {
    const color = planningFeedColor(item);
    const parent = byId.get(Number(item.parent_id));
    if (!color || !parent) return;
    const path = planningCablePath(graph, parent.id, item.id, cache);
    feeds[item.id] = { parent, color, meters: path?.meters ?? null, traced: !!path };
    if (!path) return;
    const isLink = item.metadata?.papel === 'splitter_primario';
    path.routeIds.forEach(routeId => {
      occupancy[routeId] = occupancy[routeId] || {};
      occupancy[routeId][color] = { label: isLink ? `link → ${item.name}` : item.name, target: item.id, link: isLink };
    });
  });
  return { occupancy, feeds, byId, graph, cache };
}

// ---------------------------------------------------------------------------
// Orcamento optico: potencia prevista chegando na CTO
// ---------------------------------------------------------------------------

function planningOpticalChain(item, context) {
  const chain = []; const seen = new Set();
  let current = item;
  while (current && !seen.has(Number(current.id))) {
    seen.add(Number(current.id));
    chain.unshift(current);
    if (current.device_type === 'olt') break;
    current = context.byId.get(Number(current.parent_id));
  }
  return chain;
}

function planningPowerEstimate(item, context) {
  const chain = planningOpticalChain(item, context);
  if (!chain.length || chain[0].device_type !== 'olt') return null;
  let loss = PLANNING_OPTICS.connector * 2; let meters = 0; let estimated = false;
  const unknown = [];
  for (let i = 1; i < chain.length; i += 1) {
    const node = chain[i]; const up = chain[i - 1];
    const path = planningCablePath(context.graph, up.id, node.id, context.cache);
    if (path) meters += path.meters;
    else if (planningHasCoords(up) && planningHasCoords(node)) { meters += planningDistanceMeters(up.latitude, up.longitude, node.latitude, node.longitude) * 1.15; estimated = true; }
    loss += PLANNING_OPTICS.splice * 2;
    const ratio = planningSplitterOf(node);
    if (ratio && PLANNING_OPTICS.splitter[ratio]) loss += PLANNING_OPTICS.splitter[ratio];
    else if (node.metadata?.papel === 'splitter_primario' && !node.metadata?.sem_splitter) unknown.push(node);
  }
  loss += (meters / 1000) * PLANNING_OPTICS.fiberDbPerKm;
  return { dbm: PLANNING_OPTICS.oltTxDbm - loss, loss, meters, estimated, chain, unknown };
}

function planningFormatDbm(value) {
  return Number.isFinite(value) ? `${value.toFixed(1).replace('.', ',')} dBm` : '-';
}

// ---------------------------------------------------------------------------
// Cartao da CTO / CDO (mapa do projeto e editor)
// ---------------------------------------------------------------------------

function planningCtoCardHtml(item, context = planningFiberOccupancy()) {
  const devices = _planningCurrent?.devices || [];
  const isCdo = item.metadata?.papel === 'splitter_primario';
  const ratio = planningSplitterOf(item);
  const feed = planningFeedColor(item);
  const parent = context.byId.get(Number(item.parent_id));
  const linkHow = item.metadata?.ligacao === 'proximidade' ? ' <small class="pf-warn">ligacao sugerida pela proximidade</small>' : '';
  const power = planningPowerEstimate(item, context);
  const measured = item.metadata?.port_power_dbm || {};
  const children = devices.filter(child => Number(child.parent_id) === Number(item.id));
  const ports = Math.max(ratio || 0, ...Object.keys(measured).map(Number), ...children.map(child => Number(child.metadata?.port_number) || 0));
  const camerasOf = box => planningDescendants(box.id).filter(row => row.device_type === 'camera');
  const rows = [];
  for (let port = 1; port <= ports; port += 1) {
    const who = children.find(child => Number(child.metadata?.port_number) === port);
    const value = Number(measured[String(port)]);
    let occupant = '<span class="pf-free">livre</span>';
    if (who) {
      const cams = who.device_type === 'box' ? camerasOf(who) : [];
      occupant = `<strong>${planningEscape(who.name)}</strong>${cams.length ? `<small>${cams.length} camera(s): ${planningEscape(cams.slice(0, 3).map(c => c.name).join(', '))}${cams.length > 3 ? '...' : ''}</small>` : ''}`;
    } else if (Number.isFinite(value)) {
      occupant = '<span>cliente (potencia anotada)</span>';
    }
    const delta = Number.isFinite(value) && power ? value - power.dbm : null;
    const tone = Number.isFinite(value) ? (value < PLANNING_OPTICS.onuMinDbm ? 'danger' : delta !== null && delta < -3 ? 'warn' : 'ok') : '';
    rows.push(`<tr><td class="pf-port">${port}</td><td>${occupant}</td><td class="pf-dbm ${tone}">${Number.isFinite(value) ? planningFormatDbm(value) : '-'}</td></tr>`);
  }
  const loose = children.filter(child => !Number(child.metadata?.port_number) && child.device_type !== 'cto');
  const subCdos = children.filter(child => child.device_type === 'cto');
  return `<div class="pf-card">
    <div class="pf-card-head">
      <span class="pf-card-icon">${planningIconSvg(isCdo ? 'emenda' : 'cto', '', feed)}</span>
      <div><strong>${planningEscape(item.name)}</strong><small>${isCdo ? 'CDO / caixa de emenda' : 'CTO'}${ratio ? ` · splitter 1x${ratio}` : ''}</small></div>
    </div>
    <div class="pf-feed">
      <span>Alimentada por</span>
      <div>${parent ? `<strong>${planningEscape(parent.name)}</strong>` : '<em>sem ligacao</em>'} ${feed ? `· fibra ${planningFiberChip(feed)}` : '<small class="pf-warn">cor da fibra nao informada</small>'}${linkHow}</div>
    </div>
    ${power ? `<div class="pf-power"><span>Prevista na entrada</span><strong>${planningFormatDbm(power.dbm + (ratio && PLANNING_OPTICS.splitter[ratio] ? PLANNING_OPTICS.splitter[ratio] : 0))}</strong><span>Prevista nas portas</span><strong>${planningFormatDbm(power.dbm)}</strong><small>OLT ${PLANNING_OPTICS.oltTxDbm > 0 ? '+' : ''}${PLANNING_OPTICS.oltTxDbm} dBm (classe ${PLANNING_OPTICS.oltClass}) · ${(power.meters / 1000).toFixed(2).replace('.', ',')} km de fibra${power.estimated ? ' (parte em linha reta)' : ''} · perda ${power.loss.toFixed(1).replace('.', ',')} dB · ${power.chain.map(n => planningEscape(n.name)).join(' → ')}</small></div>` : ''}
    ${power?.unknown?.length ? `<div class="pf-report-warn pf-mini">Splitter nao informado em ${power.unknown.map(n => `<strong>${planningEscape(n.name)}</strong>`).join(', ')}: se tiver splitter, a previsao fica ate ${(PLANNING_OPTICS.splitter[8]).toFixed(1).replace('.', ',')} dB menor. Informe 1xN no cadastro (ou "sem splitter").</div>` : ''}
    ${ports ? `<table class="pf-ports"><thead><tr><th>Porta</th><th>Ligado</th><th>Medida</th></tr></thead><tbody>${rows.join('')}</tbody></table>` : ''}
    ${loose.length ? `<div class="pf-note">${loose.length} ligado(s) sem porta definida: ${planningEscape(loose.slice(0, 4).map(row => row.name).join(', '))}</div>` : ''}
    ${subCdos.length ? `<div class="pf-note">Alimenta: ${subCdos.map(row => `${planningEscape(row.name)} ${planningFiberChip(planningFeedColor(row), ' ')}`).join(' · ')}</div>` : ''}
    <div class="pe-pop-actions"><button type="button" onclick="planningEditorEditDevice(${Number(item.id)})">Editar dados</button>${typeof planningEditorDeleteDevice === 'function' && planningEditorOpen() ? `<button type="button" class="danger" onclick="planningEditorDeleteDevice(${Number(item.id)})">Apagar</button>` : ''}</div>
  </div>`;
}

// Fibras de um cabo (rota), calculadas x anotadas no KMZ de origem.
function planningRouteFibersHtml(route, context = planningFiberOccupancy()) {
  const count = Math.max(1, Number(route.fiber_count || 12));
  const computed = context.occupancy[route.id] || {};
  const noted = route.metadata?.kmz_ocupacao || {};
  const rows = [];
  for (let i = 0; i < count; i += 1) {
    const color = PLANNING_FIBER_ORDER[i % 12];
    const tube = Math.floor(i / 12) + 1;
    const calc = i < 12 ? computed[color] : null;
    const kmz = i < 12 ? noted[color] : null;
    const kmzText = kmz ? (kmz === 'link' ? 'link' : kmz === 'inativa' ? 'inativa' : kmz) : '';
    const agrees = !kmz || (calc ? (kmz === 'link' ? calc.link : kmz.replace(/\s/g, '') === String(calc.label).replace(/\s/g, '')) : kmz === 'inativa');
    rows.push(`<div class="pf-fiber-row ${calc ? 'is-used' : ''}">
      <span class="pf-fiber-n">${count > 12 ? `T${tube}·` : ''}${i + 1}</span>
      ${planningFiberChip(color)}
      <span class="pf-fiber-state">${calc ? planningEscape(calc.label) : '<span class="pf-free">livre</span>'}</span>
      ${kmzText ? `<span class="pf-fiber-kmz ${agrees ? '' : 'diff'}" title="Anotado no KMZ de origem">${planningEscape(kmzText)}</span>` : ''}
    </div>`);
  }
  const used = Object.keys(computed).length;
  return `<div class="pf-fibers"><span class="pe-group">Fibras do cabo · ${used} em uso de ${count}</span>${rows.join('')}
    ${Object.keys(noted).length ? '<small class="pf-legend">A direita: o que estava anotado no KMZ. Em vermelho quando nao bate com o calculado.</small>' : ''}</div>`;
}

// ---------------------------------------------------------------------------
// Novo projeto: em branco ou importando a rede do Google Earth
// ---------------------------------------------------------------------------

function planningNewProject() {
  planningModal({
    eyebrow: 'Novo projeto', title: 'Como voce quer comecar?', primary: 'Continuar', wide: true,
    body: `<div class="pf-new">
      <label class="pf-new-card"><input type="radio" name="pfNew" value="kmz" checked>
        <span class="pf-new-icon">${planningIconSvg('cto', '', 'verde')}</span>
        <strong>Importar rede do Google Earth (KMZ)</strong>
        <small>Le as pastas por cor (FIBRA VERDE, CTO, CDO), postes, linhas de fibra, potencia anotada nas CTOs e as cameras com IP, MAC e ONU.</small>
      </label>
      <label class="pf-new-card"><input type="radio" name="pfNew" value="blank">
        <span class="pf-new-icon">${planningIconSvg('box')}</span>
        <strong>Projeto em branco</strong>
        <small>Comece do zero e desenhe no mapa, monte caixas ou importe uma planilha.</small>
      </label>
    </div>
    <div class="planning-form-grid pf-new-kmz">
      <label class="planning-field full"><span>Arquivo KMZ ou KML</span><input type="file" id="pfNewFile" accept=".kmz,.kml"></label>
      ${planningField('Nome do projeto', 'pfNewName', '', 'placeholder="Usa o nome do arquivo se ficar vazio"')}
      ${planningField('Cliente', 'pfNewClient', '', 'placeholder="Nome do cliente"')}
    </div>`,
    onSave: async root => {
      const mode = root.querySelector('input[name="pfNew"]:checked')?.value;
      if (mode === 'blank') { closePlanningModal(); openPlanningProjectModal(true); return; }
      const file = root.querySelector('#pfNewFile')?.files?.[0];
      if (!file) throw new Error('Escolha o arquivo KMZ.');
      const form = new FormData();
      form.append('file', file);
      form.append('name', root.querySelector('#pfNewName').value.trim());
      form.append('client_name', root.querySelector('#pfNewClient').value.trim());
      planningShowProgress('Lendo a rede do KMZ...');
      try {
        const data = await planningMultipart('/api/planning/import-network', form);
        closePlanningModal();
        await loadPlanning(true);
        await selectPlanningProject(data.report.projeto_id);
        planningShowImportReport(data.report);
      } finally {
        planningHideProgress();
      }
    },
  });
  const root = document.getElementById('planningModal');
  const sync = () => root.querySelector('.pf-new-kmz')?.classList.toggle('hidden', root.querySelector('input[name="pfNew"]:checked')?.value !== 'kmz');
  root.querySelectorAll('input[name="pfNew"]').forEach(input => input.addEventListener('change', sync));
  sync();
}

function planningShowImportReport(report) {
  const c = report.contagem || {};
  const line = (n, label) => (n ? `<li><strong>${n}</strong> ${label}</li>` : '');
  const warn = [];
  if (report.ctos_sem_cor) warn.push(`${report.ctos_sem_cor} CTO(s) sem a cor da fibra anotada`);
  if (report.cameras_sem_onu) warn.push(`${report.cameras_sem_onu} camera(s) sem serial de ONU (ficaram fora de caixa)`);
  if (report.sem_ligacao?.length) warn.push(`Sem ligacao: ${report.sem_ligacao.slice(0, 6).join(', ')}`);
  if (report.ligados_por_proximidade) warn.push(`${report.ligados_por_proximidade} ligacao(oes) sugerida(s) pela proximidade, nao pelo cabo: confira no mapa`);
  planningModal({
    eyebrow: 'Importacao concluida', title: 'Rede importada', primary: 'Abrir no mapa',
    body: `<div class="pf-report">
      <ul>${line(c.olt, 'OLT')}${line(c.cdo, 'CDO / caixas de emenda')}${line(c.cto, 'CTOs')}${line(c.pole, 'postes')}${line(report.rotas, 'trechos de fibra')}${line(c.camera, 'cameras')}${line(report.caixas_por_onu, 'caixas de CFTV (uma por ONU)')}${line(report.sites, 'sites')}</ul>
      ${report.ligados_pelo_cabo ? `<p class="pf-ok">${report.ligados_pelo_cabo} CTO/CDO ligados seguindo o cabo desenhado a partir da OLT.</p>` : ''}
      ${warn.length ? `<div class="pf-report-warn"><strong>Para conferir</strong><ul>${warn.map(w => `<li>${planningEscape(w)}</li>`).join('')}</ul></div>` : ''}
      ${report.total_ignorados ? `<details><summary>${report.total_ignorados} item(ns) nao importado(s)</summary><small>${planningEscape((report.ignorados || []).join(' · '))}</small></details>` : ''}
    </div>`,
    onSave: async () => { closePlanningModal(); openPlanningRouteEditor(); },
  });
}
