// Implantacao > Projetos: pipeline de projetos e workspace de um projeto
// (cabecalho com etapas, indicadores, mapa, pendencias "Antes de implantar"
// e equipamentos por caixa). Os modais e calculos continuam em planning.js;
// aqui so se monta a tela a partir de _planningCurrent.

const PLANNING_STEP_ORDER = ['draft', 'planned', 'approved', 'deploying', 'completed'];
const PLANNING_STEP_HINT = {
  draft: 'desenhando', planned: 'pronto para revisar', approved: 'cliente aprovou',
  deploying: 'equipe em campo', completed: 'entregue',
};
const PLANNING_ADVANCE_LABEL = {
  draft: 'Marcar como planejado', planned: 'Marcar como aprovado',
  approved: 'Iniciar implantacao', deploying: 'Marcar como concluido',
};
const PLANNING_STATUS_TONE = { draft: 'gray', planned: 'blue', approved: 'cyan', deploying: 'amber', completed: 'green' };
// Tipos em que o modelo entra na proposta (caixa, poste e "outro" nao).
const PLANNING_MODEL_TYPES = new Set(['camera', 'onu', 'ont', 'olt', 'switch', 'injector', 'recorder', 'cto', 'dio']);
// Tipos que precisam de coordenada para aparecer no mapa e entrar no calculo de cabo.
const PLANNING_GEO_TYPES = new Set(['camera', 'box', 'cto', 'dio', 'olt', 'rack']);
const PLANNING_FIBER_NODE_TYPES = new Set(['olt', 'rack', 'dio', 'cto']);

let _planningTab = 'boxes';
let _planningMapGroups = {};
let _planningLayerOn = { cameras: true, boxes: true, network: true, fiber: true, utp: false, kmz: true };
let _planningIssues = [];

function planningShowPipeline() {
  document.getElementById('planningPipeline')?.classList.remove('hidden');
  document.getElementById('planningWorkspace')?.classList.add('hidden');
}

function planningShowWorkspace() {
  document.getElementById('planningPipeline')?.classList.add('hidden');
  document.getElementById('planningWorkspace')?.classList.remove('hidden');
}

function planningFormatMeters(value) {
  if (!Number.isFinite(value)) return '-';
  if (value >= 1000) return `${(value / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} km`;
  return `${Math.round(value).toLocaleString('pt-BR')} m`;
}

function planningFormatWhen(value) {
  let text = String(value || '').trim();
  if (!text) return '';
  // SQLite devolve "YYYY-MM-DD HH:MM:SS" em UTC, sem fuso.
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(text)) text = `${text.replace(' ', 'T')}Z`;
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return '';
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  const time = date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return sameDay ? `hoje as ${time}` : `${date.toLocaleDateString('pt-BR')} ${time}`;
}

function planningHasCoords(item) {
  return Number.isFinite(planningCoordinate(item?.latitude)) && Number.isFinite(planningCoordinate(item?.longitude));
}

// ---------------------------------------------------------------------------
// Pipeline: todos os projetos, uma coluna por etapa.
// ---------------------------------------------------------------------------

function planningRenderPipeline() {
  const board = document.getElementById('planningBoard');
  const summary = document.getElementById('planningPipelineSummary');
  const switcher = document.getElementById('planningProjectSwitch');
  const projects = _planningProjects || [];
  if (switcher) {
    switcher.innerHTML = projects.map(item => `<option value="${Number(item.id)}" ${Number(item.id) === Number(_planningCurrent?.id) ? 'selected' : ''}>${planningEscape(item.name)}</option>`).join('');
  }
  if (!board) return;
  const cameras = projects.reduce((total, item) => total + Number(item.cameras_count || 0), 0);
  if (summary) {
    summary.textContent = projects.length
      ? `${projects.length} projeto(s) · ${cameras.toLocaleString('pt-BR')} camera(s) planejada(s). Itens planejados nao entram no inventario nem no monitoramento.`
      : 'Nenhum projeto ainda. Crie o primeiro para desenhar o parque antes da instalacao.';
  }
  const term = String(document.getElementById('planningProjectSearch')?.value || '').trim().toLowerCase();
  const visible = projects.filter(item => !term || [item.name, item.client_name, item.description]
    .some(value => String(value || '').toLowerCase().includes(term)));
  board.innerHTML = PLANNING_STEP_ORDER.map(status => {
    const items = visible.filter(item => (PLANNING_STEP_ORDER.includes(item.status) ? item.status : 'draft') === status);
    const cards = items.map(item => {
      const devices = Number(item.devices_count || 0);
      return `
      <button type="button" class="pj-card" onclick="selectPlanningProject(${Number(item.id)})">
        <span class="pj-card-title"><strong>${planningEscape(item.name)}</strong><small>${planningEscape(item.client_name || 'Cliente nao informado')}</small></span>
        <span class="pj-card-stats"><span><strong>${Number(item.cameras_count || 0)}</strong> cameras</span><span><strong>${Number(item.onus_count || 0)}</strong> ONUs</span><span><strong>${Number(item.sites_count || 0)}</strong> sites</span></span>
        <span class="pj-card-foot">${devices ? `${devices} equipamento(s) planejado(s)` : 'Projeto vazio: escolha como comecar'}</span>
        ${item.updated_at ? `<span class="pj-card-when">Atualizado ${planningEscape(planningFormatWhen(item.updated_at))}</span>` : ''}
      </button>`;
    }).join('');
    const empty = status === 'draft' && !projects.length
      ? `<button type="button" class="pj-col-empty is-action" onclick="openPlanningProjectModal(true)"><i data-lucide="plus"></i> Criar o primeiro projeto</button>`
      : `<div class="pj-col-empty">${term ? 'Nenhum projeto nesta etapa bate com a busca.' : 'Nenhum projeto nesta etapa.'}</div>`;
    return `
      <section class="pj-col" aria-label="${planningEscape(PLANNING_STATUS[status])}">
        <header class="pj-col-head"><span class="pj-dot ${PLANNING_STATUS_TONE[status]}"></span><h2>${planningEscape(PLANNING_STATUS[status])}</h2><span class="pj-col-count">${items.length}</span></header>
        ${cards || empty}
      </section>`;
  }).join('');
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

// ---------------------------------------------------------------------------
// Analise do projeto: tudo que os indicadores, pendencias e caixas usam.
// ---------------------------------------------------------------------------

function planningAnalyze() {
  const project = _planningCurrent || {};
  const devices = project.devices || [];
  const byId = new Map(devices.map(item => [Number(item.id), item]));
  const childrenOf = new Map();
  devices.forEach(item => {
    const parentId = Number(item.parent_id);
    if (!parentId || !byId.has(parentId)) return;
    if (!childrenOf.has(parentId)) childrenOf.set(parentId, []);
    childrenOf.get(parentId).push(item);
  });
  const kids = id => childrenOf.get(Number(id)) || [];
  const descendants = id => {
    const found = []; const seen = new Set();
    const visit = parent => kids(parent).forEach(child => {
      if (seen.has(Number(child.id))) return;
      seen.add(Number(child.id)); found.push(child); visit(child.id);
    });
    visit(id);
    return found;
  };
  const cameras = devices.filter(item => item.device_type === 'camera');
  const boxes = devices.filter(item => item.device_type === 'box').sort((a, b) => planningNaturalCompare(a.name, b.name));

  const probe = document.createElement('div');
  const cableConfig = planningLoadCableQuote()?.config || planningCableConfig(probe);
  const cableRows = planningCableCalculation(cableConfig);
  const cableByCamera = new Map(cableRows.map(row => [Number(row.camera.id), row]));
  const fiberConfig = planningFiberConfig(probe);
  const fiberRows = planningFiberCalculation(fiberConfig);

  const boxInfo = boxes.map(box => {
    const inside = descendants(box.id);
    const distribution = inside.filter(item => ['switch', 'injector'].includes(item.device_type));
    const boxCameras = inside.filter(item => item.device_type === 'camera').sort((a, b) => planningNaturalCompare(a.name, b.name));
    const onu = inside.find(item => ['onu', 'ont'].includes(item.device_type));
    const ports = distribution.map(device => {
      const capacity = planningPoeCapacity(device.metadata || {});
      const attached = kids(device.id).filter(item => item.device_type === 'camera');
      return { device, capacity, used: attached.length, attached };
    });
    const capacity = ports.reduce((total, row) => total + row.capacity, 0);
    const used = ports.reduce((total, row) => total + row.used, 0);
    const state = capacity && used > capacity ? 'danger' : capacity && used >= capacity ? 'full' : 'ok';
    const parent = byId.get(Number(box.parent_id)) || null;
    const utpMeters = boxCameras.reduce((total, camera) => {
      const row = cableByCamera.get(Number(camera.id));
      return total + (row && !row.error ? row.purchase : 0);
    }, 0);
    return { box, inside, distribution, cameras: boxCameras, onu, ports, capacity, used, state, parent, utpMeters };
  });

  return {
    project, devices, byId, kids, descendants, cameras, boxes, boxInfo,
    cableConfig, cableRows, cableByCamera, fiberConfig, fiberRows,
    onus: devices.filter(item => ['onu', 'ont'].includes(item.device_type)),
    recorders: devices.filter(item => item.device_type === 'recorder'),
    fiberNodes: devices.filter(item => PLANNING_FIBER_NODE_TYPES.has(item.device_type)),
  };
}

// Pendencias que impedem ir a campo sem surpresa. Cada uma diz o que esta
// errado, onde, e oferece o atalho para resolver.
function planningReadiness(a) {
  const issues = [];
  const problem = new Set();
  const names = list => list.slice(0, 3).map(item => item.name).join(', ') + (list.length > 3 ? ` e mais ${list.length - 3}` : '');
  const add = (issue, items) => { issues.push(issue); (items || []).forEach(item => problem.add(Number(item.id))); };

  const over = a.cableRows.filter(row => !row.error && row.overLimit);
  if (over.length) {
    const worst = over.slice().sort((x, y) => y.installed - x.installed)[0];
    add({
      level: 'danger', badge: '!', key: 'utp-over',
      title: over.length === 1 ? `${worst.camera.name} a ${Math.round(worst.installed)} m do switch` : `${over.length} cameras passam de ${a.cableConfig.maxMeters} m de UTP`,
      detail: `O cabo de rede passa do limite de ${a.cableConfig.maxMeters} m. Mude a camera de caixa ou use extensor.`,
      action: 'Ver calculo', run: () => openPlanningCableModal(), ids: over.map(row => row.camera.id),
    }, over.map(row => row.camera));
  }

  const ipOwners = new Map();
  a.devices.forEach(item => {
    const ip = String(item.ip || '').trim();
    if (!ip) return;
    if (!ipOwners.has(ip)) ipOwners.set(ip, []);
    ipOwners.get(ip).push(item);
  });
  const repeated = [...ipOwners.values()].filter(list => list.length > 1).flat();
  if (repeated.length) {
    add({
      level: 'danger', badge: '!', key: 'ip-dup', title: `${repeated.length} equipamentos com IP repetido`,
      detail: `${names(repeated)}. Dois equipamentos no mesmo IP nao funcionam juntos.`,
      action: 'Ver lista', ids: repeated.map(item => item.id),
    }, repeated);
  }

  const crowded = a.boxInfo.filter(info => info.state === 'danger');
  if (crowded.length) {
    const items = crowded.flatMap(info => [info.box, ...info.distribution]);
    add({
      level: 'danger', badge: '!', key: 'ports-over',
      title: crowded.length === 1 ? `${crowded[0].box.name}: ${crowded[0].used} cameras para ${crowded[0].capacity} portas PoE` : `${crowded.length} caixas com mais cameras que portas PoE`,
      detail: 'Troque o switch por um maior ou mude cameras de caixa.',
      action: 'Ver caixas', ids: items.map(item => item.id),
    }, items);
  }

  const noIp = a.cameras.filter(item => !String(item.ip || '').trim());
  if (noIp.length) {
    add({
      level: 'amber', badge: String(noIp.length), key: 'cam-noip', title: `${noIp.length} camera(s) sem IP`,
      detail: `${names(noIp)}.`, action: 'Ver cameras', ids: noIp.map(item => item.id),
    }, noIp);
  }

  const loose = a.cameras.filter(item => !a.cableByCamera.get(Number(item.id))?.box);
  if (loose.length) {
    add({
      level: 'amber', badge: String(loose.length), key: 'cam-loose', title: `${loose.length} camera(s) fora de caixa`,
      detail: 'Sem switch ou injetor dentro de uma caixa, nao da para calcular o cabo nem a porta.',
      action: 'Ver cameras', ids: loose.map(item => item.id),
    }, loose);
  }

  const noGeo = a.devices.filter(item => PLANNING_GEO_TYPES.has(item.device_type) && !planningHasCoords(item));
  if (noGeo.length) {
    add({
      level: 'amber', badge: String(noGeo.length), key: 'no-geo', title: `${noGeo.length} equipamento(s) sem posicao no mapa`,
      detail: 'Sem coordenada nao aparecem no mapa e o cabo nao e calculado.', action: 'Ver lista', ids: noGeo.map(item => item.id),
    }, noGeo);
  }

  const noModel = a.devices.filter(item => PLANNING_MODEL_TYPES.has(item.device_type) && !String(item.model || '').trim());
  if (noModel.length) {
    add({
      level: 'blue', badge: String(noModel.length), key: 'no-model', title: `${noModel.length} equipamento(s) sem modelo`,
      detail: `${names(noModel)}. Saem sem modelo na proposta.`, action: 'Definir', ids: noModel.map(item => item.id),
    }, noModel);
  }

  const full = a.boxInfo.filter(info => info.state === 'full');
  if (full.length) {
    add({
      level: 'blue', badge: String(full.length), key: 'ports-full',
      title: full.length === 1 ? `${full[0].box.name} sem porta PoE livre` : `${full.length} caixas sem porta PoE livre`,
      detail: 'Funciona, mas nao sobra porta para uma camera extra.', action: 'Ver caixas',
      ids: full.flatMap(info => [info.box.id, ...info.distribution.map(item => item.id)]),
    }, []);
  }

  if (a.cameras.length && !a.recorders.length) {
    issues.push({
      level: 'blue', badge: 'i', key: 'no-recorder', title: 'Nenhum gravador planejado',
      detail: `${a.cameras.length} camera(s) precisam de onde gravar.`, action: 'Adicionar',
      run: () => openPlanningDeviceModal(0, { device_type: 'recorder' }),
    });
  }

  const relevant = a.devices.filter(item => PLANNING_MODEL_TYPES.has(item.device_type) || item.device_type === 'box');
  const bad = relevant.filter(item => problem.has(Number(item.id))).length;
  let score = relevant.length ? Math.round(((relevant.length - bad) / relevant.length) * 100) : 0;
  if (issues.some(issue => issue.key === 'no-recorder')) score = Math.min(score, 95);
  if (issues.some(issue => issue.level === 'danger')) score = Math.min(score, 89);
  const readyCameras = a.cameras.filter(item => !problem.has(Number(item.id))).length;
  return { issues, score, readyCameras, relevant: relevant.length };
}

// ---------------------------------------------------------------------------
// Workspace do projeto.
// ---------------------------------------------------------------------------

function planningRenderWorkspace() {
  const project = _planningCurrent;
  if (!project) return;
  const a = planningAnalyze();
  const ready = planningReadiness(a);
  _planningIssues = ready.issues;

  const status = PLANNING_STEP_ORDER.includes(project.status) ? project.status : 'draft';
  const statusEl = document.getElementById('planningStatus');
  if (statusEl) { statusEl.textContent = PLANNING_STATUS[status]; statusEl.dataset.tone = PLANNING_STATUS_TONE[status]; }
  const title = document.getElementById('planningTitle');
  if (title) title.textContent = project.name;
  const meta = document.getElementById('planningSubtitle');
  if (meta) {
    const parts = [
      project.client_name ? `Cliente: <strong>${planningEscape(project.client_name)}</strong>` : 'Cliente nao informado',
      `${(project.sites || []).length} site(s) · ${a.boxes.length} caixa(s) de CFTV`,
    ];
    const when = planningFormatWhen(project.updated_at);
    if (when) parts.push(`Atualizado ${planningEscape(when)}`);
    if (project.description) parts.push(planningEscape(project.description));
    meta.innerHTML = parts.map(part => `<span>${part}</span>`).join('');
  }

  planningRenderSteps(status);

  const empty = !a.devices.length;
  document.getElementById('planningStart')?.classList.toggle('hidden', !empty);
  document.getElementById('planningFilled')?.classList.toggle('hidden', empty);
  if (empty) { if (typeof lucide !== 'undefined') lucide.createIcons(); return; }

  planningRenderKpis(a, ready);
  planningRenderReady(a, ready);
  planningRenderChain(a);
  planningRenderBoxes(a);
  planningRenderLayers(a);
  const listBtn = document.getElementById('planningListTabBtn');
  if (listBtn) listBtn.textContent = `Lista (${a.devices.length})`;
  planningSetTab(_planningIssueFilter ? 'list' : (_planningTab === 'boxes' && !a.boxes.length ? 'list' : _planningTab), false);
  planningRenderIssueChip();
  if (typeof lucide !== 'undefined') lucide.createIcons();
}

function planningRenderSteps(status) {
  const list = document.getElementById('planningSteps');
  const current = PLANNING_STEP_ORDER.indexOf(status);
  if (list) {
    list.innerHTML = PLANNING_STEP_ORDER.map((key, index) => {
      const state = index < current ? 'done' : index === current ? 'now' : 'next';
      return `<li class="pj-step is-${state}"${state === 'now' ? ' aria-current="step"' : ''}>
        <span class="pj-step-dot">${state === 'done' ? '<i data-lucide="check"></i>' : index + 1}</span>
        <span class="pj-step-text"><strong>${planningEscape(PLANNING_STATUS[key])}</strong><small>${state === 'now' ? 'etapa atual' : planningEscape(PLANNING_STEP_HINT[key])}</small></span>
      </li>`;
    }).join('');
  }
  const advance = document.getElementById('btnPlanningAdvance');
  if (advance) {
    const label = PLANNING_ADVANCE_LABEL[status];
    advance.classList.toggle('hidden', !label);
    advance.textContent = label ? `${label} →` : '';
  }
}

async function planningAdvanceStatus() {
  const project = _planningCurrent;
  if (!project) return;
  const index = PLANNING_STEP_ORDER.indexOf(project.status);
  const next = PLANNING_STEP_ORDER[index + 1];
  if (!next) return;
  const blockers = _planningIssues.filter(issue => issue.level === 'danger');
  if (['approved', 'deploying'].includes(next) && blockers.length) {
    const ok = await showConfirm({
      eyebrow: 'Projeto', title: `Ainda ha ${blockers.length} problema(s) grave(s)`,
      msg: `${blockers.map(issue => issue.title).join('; ')}. Avancar para "${PLANNING_STATUS[next]}" mesmo assim?`, label: 'Avancar mesmo assim',
    });
    if (!ok) return;
  }
  const payload = {
    name: project.name, client_name: project.client_name || '', description: project.description || '',
    status: next, kmz_layer_id: project.kmz_layer_id || '',
  };
  const button = document.getElementById('btnPlanningAdvance');
  if (button) button.disabled = true;
  try {
    await planningRequest(`/api/planning/projects/${Number(project.id)}`, { method: 'PUT', body: JSON.stringify(payload) });
    showToast(`Projeto em "${PLANNING_STATUS[next]}".`);
    await loadPlanning(true);
  } catch (error) {
    showToast(error.message || 'Nao foi possivel mudar a etapa.', true);
  } finally {
    if (button) button.disabled = false;
  }
}

function planningRenderKpis(a, ready) {
  const box = document.getElementById('planningKpis');
  if (!box) return;
  const circumference = 2 * Math.PI * 23;
  const tone = ready.score >= 90 ? '#087f5b' : ready.score >= 60 ? '#b86b00' : '#c92a2a';
  const withIp = a.cameras.filter(item => String(item.ip || '').trim()).length;
  const fullBoxes = a.boxInfo.filter(info => info.state !== 'ok').length;
  const fiberValid = a.fiberRows.filter(row => !row.error);
  const fiberMeters = fiberValid.reduce((total, row) => total + row.purchase, 0);
  const cableValid = a.cableRows.filter(row => !row.error);
  const cableMeters = cableValid.reduce((total, row) => total + row.purchase, 0);
  const cableOver = cableValid.filter(row => row.overLimit).length;
  const ctoCount = a.devices.filter(item => ['cto', 'dio'].includes(item.device_type)).length;
  const kpi = (label, value, unit, sub, warn) => `
    <div class="pj-kpi"><span class="pj-kpi-label">${label}</span><strong>${value}${unit ? `<small>${unit}</small>` : ''}</strong><span class="pj-kpi-sub ${warn ? 'warn' : ''}">${sub}</span></div>`;
  const splitMeters = meters => {
    const text = planningFormatMeters(meters);
    const [value, unit] = text.split(' ');
    return [value, unit || ''];
  };
  const [fiberValue, fiberUnit] = fiberValid.length ? splitMeters(fiberMeters) : ['-', ''];
  const [cableValue, cableUnit] = cableValid.length ? splitMeters(cableMeters) : ['-', ''];
  box.innerHTML = `
    <div class="pj-kpi pj-kpi-ready">
      <svg width="56" height="56" viewBox="0 0 56 56" role="img" aria-label="Prontidao ${ready.score}%"><circle cx="28" cy="28" r="23" fill="none" stroke="var(--primary-soft)" stroke-width="7"></circle><circle cx="28" cy="28" r="23" fill="none" stroke="${tone}" stroke-width="7" stroke-linecap="round" stroke-dasharray="${(circumference * ready.score / 100).toFixed(1)} ${circumference.toFixed(1)}" transform="rotate(-90 28 28)"></circle><text x="28" y="33" text-anchor="middle" font-size="14" font-weight="800" fill="var(--text)">${ready.score}%</text></svg>
      <div><span class="pj-kpi-label">Prontidao</span><strong class="pj-kpi-small">${ready.issues.length ? `${ready.issues.length} ${ready.issues.length === 1 ? 'pendencia' : 'pendencias'}` : 'Sem pendencias'}</strong><span class="pj-kpi-sub">para implantar</span></div>
    </div>
    ${kpi('Cameras', a.cameras.length, '', a.cameras.length ? `${withIp} com IP${a.cameras.length - withIp ? ` · ${a.cameras.length - withIp} a definir` : ''}` : 'nenhuma ainda', a.cameras.length - withIp > 0)}
    ${kpi('Caixas de CFTV', a.boxes.length, '', a.boxes.length ? (fullBoxes ? `${fullBoxes} sem porta livre` : 'todas com porta livre') : 'nenhuma ainda', fullBoxes > 0)}
    ${kpi('ONUs / ONTs', a.onus.length, '', ctoCount ? `${ctoCount} CTO/DIO no caminho` : 'sem CTO/DIO cadastrada', false)}
    ${kpi('Fibra', fiberValue, fiberUnit, fiberValid.length ? `${fiberValid.length} trecho(s), em linha reta` : 'cadastre OLT e CTO com posicao', false)}
    ${kpi('Cabo UTP', cableValue, cableUnit, cableValid.length ? (cableOver ? `${cableOver} lance(s) acima de ${a.cableConfig.maxMeters} m` : 'todos dentro do limite') : 'cameras sem posicao ou caixa', cableOver > 0)}`;
}

function planningRenderReady(a, ready) {
  const box = document.getElementById('planningReady');
  if (!box) return;
  const rows = ready.issues.map((issue, index) => `
    <li class="pj-issue">
      <span class="pj-issue-badge ${issue.level}">${planningEscape(issue.badge)}</span>
      <span class="pj-issue-text"><strong>${planningEscape(issue.title)}</strong><small>${planningEscape(issue.detail)}</small></span>
      <button type="button" class="pj-issue-btn" onclick="planningRunIssue(${index})">${planningEscape(issue.action)}</button>
    </li>`).join('');
  const done = [];
  if (ready.readyCameras) done.push(`${ready.readyCameras} camera(s) completas`);
  const okBoxes = a.boxInfo.filter(info => info.state === 'ok' && info.cameras.length).length;
  if (okBoxes) done.push(`${okBoxes} caixa(s) com folga`);
  box.innerHTML = `
    <div class="pj-ready-head"><h2>Antes de implantar</h2><span>O que falta para a equipe ir a campo sem surpresa.</span></div>
    ${rows ? `<ul class="pj-issues">${rows}</ul>` : '<div class="pj-ready-clear"><i data-lucide="party-popper"></i><strong>Nada pendente.</strong><span>O projeto esta pronto para seguir.</span></div>'}
    ${done.length ? `<div class="pj-ready-foot"><i data-lucide="check"></i>${planningEscape(done.join(' · '))}</div>` : ''}`;
}

function planningRunIssue(index) {
  const issue = _planningIssues[index];
  if (!issue) return;
  if (issue.run) { issue.run(); return; }
  if (!issue.ids?.length) return;
  _planningIssueFilter = { label: issue.title, ids: new Set(issue.ids.map(Number)) };
  planningSetTab('list');
  planningRenderIssueChip();
  renderPlanningDevices();
  document.getElementById('planningListTab')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function planningRenderIssueChip() {
  const chip = document.getElementById('planningIssueChip');
  if (!chip) return;
  chip.classList.toggle('hidden', !_planningIssueFilter);
  chip.innerHTML = _planningIssueFilter
    ? `<span>Mostrando: <strong>${planningEscape(_planningIssueFilter.label)}</strong></span><button type="button" onclick="planningClearDeviceFilters()">Mostrar todos</button>`
    : '';
}

function planningRenderChain(a) {
  const box = document.getElementById('planningChain');
  if (!box) return;
  const olts = a.devices.filter(item => ['olt', 'rack'].includes(item.device_type));
  const splitters = a.devices.filter(item => ['dio', 'cto'].includes(item.device_type)).sort((x, y) => planningNaturalCompare(x.name, y.name));
  if (!olts.length && !splitters.length) {
    box.innerHTML = `<span class="pj-chain-label">Caminho da fibra</span><span class="pj-chain-muted">Cadastre a OLT e as CTOs para ver o caminho da fibra ate as caixas.</span>
      <button type="button" class="pj-link" onclick="openPlanningDeviceModal(0,{device_type:'olt'})">Adicionar OLT</button>`;
    return;
  }
  const usage = item => {
    const capacity = planningParentPortCapacity(item);
    const used = a.kids(item.id).length;
    return capacity ? `${used}/${capacity}` : `${used}`;
  };
  const chip = (item, kind) => `<button type="button" class="pj-chain-chip ${kind}" onclick="openPlanningDeviceDetails(${Number(item.id)})">${planningEscape(item.name)}<small>${kind === 'dark' && item.device_type === 'olt' ? `PON ${usage(item)}` : usage(item)}</small></button>`;
  const arrow = '<span class="pj-chain-arrow" aria-hidden="true"><i data-lucide="arrow-right"></i></span>';
  const shown = splitters.slice(0, 8);
  const fiberMeters = a.fiberRows.filter(row => !row.error).reduce((total, row) => total + row.purchase, 0);
  box.innerHTML = [
    '<span class="pj-chain-label">Caminho da fibra</span>',
    olts.map(item => chip(item, 'dark')).join(''),
    olts.length && shown.length ? arrow : '',
    shown.map(item => chip(item, item.device_type === 'dio' ? 'amber' : 'cyan')).join(''),
    splitters.length > shown.length ? `<span class="pj-chain-muted">+${splitters.length - shown.length}</span>` : '',
    a.boxes.length ? arrow : '',
    `<span class="pj-chain-muted">${a.boxes.length} caixa(s) de CFTV${fiberMeters ? ` · ${planningFormatMeters(fiberMeters)} de fibra (linha reta)` : ''}</span>`,
  ].join('');
}

function planningPortSquares(row) {
  const capacity = Math.max(0, row.capacity);
  const shown = Math.min(capacity, 24);
  const byPort = new Map();
  const loose = [];
  row.attached.forEach(camera => {
    const port = Number(camera.metadata?.port_number);
    if (port >= 1 && port <= shown && !byPort.has(port)) byPort.set(port, camera); else loose.push(camera);
  });
  const squares = [];
  for (let port = 1; port <= shown; port += 1) {
    let camera = byPort.get(port);
    if (!camera && loose.length) camera = loose.shift();
    squares.push(camera
      ? `<span class="pj-port used" title="Porta ${port}: ${planningEscape(camera.name)}">${port}</span>`
      : `<span class="pj-port" title="Porta ${port} livre">${port}</span>`);
  }
  loose.forEach(camera => squares.push(`<span class="pj-port over" title="Sem porta: ${planningEscape(camera.name)}">!</span>`));
  return squares.join('');
}

function planningRenderBoxes(a) {
  const box = document.getElementById('planningBoxes');
  if (!box) return;
  if (!a.boxes.length) {
    box.innerHTML = `<div class="planning-list-empty"><strong>Nenhuma caixa de CFTV ainda.</strong><span>A caixa junta ONU, switch e as cameras ligadas por porta.</span><button class="secondary-action" type="button" onclick="openPlanningBoxModal()">Montar caixa</button></div>`;
    return;
  }
  const max = Number(a.cableConfig.maxMeters) || 100;
  box.innerHTML = a.boxInfo.map(info => {
    const feed = [
      info.parent ? `${info.parent.name}${info.box.metadata?.port_number ? ` porta ${info.box.metadata.port_number}` : ''}` : 'Sem CTO/OLT ligada',
      info.onu ? `${PLANNING_TYPES[info.onu.device_type]} ${info.onu.model || ''}`.trim() : 'sem ONU',
    ].join(' · ');
    const portBlocks = info.ports.length ? info.ports.map(row => `
      <div class="pj-ports">
        <div class="pj-ports-head"><span>${planningEscape(PLANNING_TYPES[row.device.device_type])} ${planningEscape(row.device.model || row.device.name)}</span><strong class="${row.capacity && row.used > row.capacity ? 'danger' : row.capacity && row.used >= row.capacity ? 'warn' : ''}">${row.capacity ? `${row.used}/${row.capacity} portas${row.used >= row.capacity ? ' · sem folga' : ''}` : `${row.used} camera(s) · capacidade a definir`}</strong></div>
        ${row.capacity ? `<div class="pj-port-grid" aria-hidden="true">${planningPortSquares(row)}</div>` : ''}
      </div>`).join('') : '<div class="pj-ports-none">Sem switch ou injetor PoE nesta caixa.</div>';
    const camRows = info.cameras.slice(0, 6).map(camera => {
      const cable = a.cableByCamera.get(Number(camera.id));
      const meters = cable && !cable.error ? cable.installed : null;
      const tone = meters === null ? 'muted' : meters > max ? 'danger' : meters > max * 0.8 ? 'warn' : '';
      const ip = String(camera.ip || '').trim();
      return `<li><button type="button" onclick="openPlanningDeviceModal(${Number(camera.id)})">
        <span class="pj-cam-name">${planningEscape(camera.name)}</span>
        <span class="pj-cam-ip ${ip ? '' : 'warn'}">${planningEscape(ip || 'IP a definir')}</span>
        <span class="pj-cam-utp ${tone}" title="${cable?.error ? planningEscape(cable.error) : 'Cabo UTP instalado (linha reta + margem)'}">${meters === null ? '-' : `${Math.round(meters)} m`}</span>
      </button></li>`;
    }).join('');
    const more = info.cameras.length > 6 ? `+ ${info.cameras.length - 6} camera(s)` : info.cameras.length ? `UTP da caixa: ${planningFormatMeters(info.utpMeters)} para comprar` : 'Nenhuma camera ligada';
    return `
      <article class="pj-box is-${info.state}">
        <header>
          <span class="pj-box-tag">${planningEscape(info.box.name)}</span>
          <span class="pj-box-feed">${planningEscape(feed)}</span>
          <button type="button" class="icon-button" onclick="openPlanningBoxDetails(${Number(info.box.id)})" aria-label="Abrir ${planningEscape(info.box.name)}"><i data-lucide="chevron-right"></i></button>
        </header>
        ${portBlocks}
        ${camRows ? `<ul class="pj-cams">${camRows}</ul>` : ''}
        <button type="button" class="pj-box-more" onclick="openPlanningBoxDetails(${Number(info.box.id)})">${planningEscape(more)}</button>
      </article>`;
  }).join('');
}

function planningSetTab(tab, scroll = true) {
  _planningTab = tab === 'list' ? 'list' : 'boxes';
  document.querySelectorAll('[data-pj-tab]').forEach(button => {
    button.setAttribute('aria-selected', String(button.dataset.pjTab === _planningTab));
  });
  document.getElementById('planningBoxesTab')?.classList.toggle('hidden', _planningTab !== 'boxes');
  document.getElementById('planningListTab')?.classList.toggle('hidden', _planningTab !== 'list');
  if (scroll === false) return;
}

// ---------------------------------------------------------------------------
// Mapa do projeto, com camadas que ligam e desligam.
// ---------------------------------------------------------------------------

const PLANNING_LAYER_LABEL = {
  cameras: 'Cameras', boxes: 'Caixas', network: 'OLT / CTO', fiber: 'Fibra', utp: 'Cabo UTP', kmz: 'Area KMZ',
};

function planningRenderLayers(a) {
  const box = document.getElementById('planningLayers');
  if (!box) return;
  const counts = {
    cameras: a.cameras.length, boxes: a.boxes.length, network: a.fiberNodes.length,
    fiber: a.fiberRows.filter(row => !row.error).length, utp: a.cableRows.filter(row => !row.error).length,
    kmz: _planningCurrent?.kmz_layer_id ? 1 : 0,
  };
  box.innerHTML = Object.keys(PLANNING_LAYER_LABEL).filter(key => key !== 'kmz' || counts.kmz).map(key => `
    <button type="button" class="pj-layer ${key}" aria-pressed="${_planningLayerOn[key] ? 'true' : 'false'}" onclick="planningToggleLayer('${key}')">${PLANNING_LAYER_LABEL[key]}${key === 'kmz' ? '' : ` <span>${counts[key]}</span>`}</button>`).join('');
}

function planningToggleLayer(key) {
  _planningLayerOn[key] = !_planningLayerOn[key];
  const group = _planningMapGroups[key];
  if (group && _planningMap) {
    if (_planningLayerOn[key]) group.addTo(_planningMap); else group.remove();
  }
  document.querySelectorAll(`.pj-layer.${key}`).forEach(button => button.setAttribute('aria-pressed', String(_planningLayerOn[key])));
}

function planningBoxIcon(label, tone) {
  return L.divIcon({
    className: 'pj-map-box-icon',
    html: `<span class="pj-map-box ${tone}">${planningEscape(label)}</span>`,
    iconSize: [34, 34], iconAnchor: [17, 17], popupAnchor: [0, -16],
  });
}

function planningShortLabel(name) {
  const match = String(name || '').match(/(\d+)(?!.*\d)/);
  return match ? match[1].slice(-3) : String(name || '?').slice(0, 3).toUpperCase();
}

function planningPopupHtml(item) {
  const referenceImage = item.reference_image_url
    ? `<img class="planning-popup-image" src="${planningEscape(item.reference_image_url)}" alt="Imagem ilustrativa" loading="lazy"><small>Imagem ilustrativa do modelo</small>` : '';
  return `<div class="planning-popup">${referenceImage}<strong>${planningEscape(item.name)}</strong><span>${planningEscape(PLANNING_TYPES[item.device_type] || item.device_type)} · ${planningEscape(item.site_name || 'Sem site')}</span>${planningItemHasNoIp(item) ? '' : `<code>${planningEscape(item.ip || 'IP a definir')}</code>`}<span>${planningEscape([item.manufacturer, item.model].filter(Boolean).join(' / ') || 'Modelo a definir')}</span><button type="button" class="pj-popup-open" onclick="openPlanningDeviceDetails(${Number(item.id)})">Abrir</button></div>`;
}

async function renderPlanningMap() {
  const container = document.getElementById('planningMap');
  if (!container || !_planningCurrent || typeof L === 'undefined') return;
  if (!(_planningCurrent.devices || []).length) return;
  if (!_planningMap || _planningMap.getContainer() !== container) {
    _planningMap = L.map(container, { zoomControl: true }).setView([-9.76, -36.67], 14);
    const streets = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 20, maxNativeZoom: 19, attribution: '&copy; OpenStreetMap' });
    const satellite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 20, maxNativeZoom: 19, attribution: 'Imagens &copy; Esri' });
    streets.addTo(_planningMap);
    L.control.layers({ Mapa: streets, Satelite: satellite }, null, { position: 'topright' }).addTo(_planningMap);
  }
  Object.values(_planningMapGroups).forEach(group => group.remove());
  _planningMapGroups = {};
  Object.keys(PLANNING_LAYER_LABEL).forEach(key => { _planningMapGroups[key] = L.layerGroup(); });
  _planningMarkers = {};
  const a = planningAnalyze();
  const bounds = [];
  const projectId = Number(_planningCurrent.id);

  if (_planningCurrent.kmz_layer_id) {
    const data = await apiJson('/api/kmz/import/layers?include_features=true', { forceRefresh: true, cacheTtl: 0 });
    if (Number(_planningCurrent?.id) !== projectId) return;
    const layer = (data?.layers || []).find(item => item.id === _planningCurrent.kmz_layer_id);
    if (layer?.features?.length) {
      const geo = L.geoJSON({ type: 'FeatureCollection', features: layer.features }, {
        style: { color: '#0b7285', weight: 2, fillOpacity: .06, dashArray: '4 4' },
        pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 4, color: '#0b7285', weight: 1, fillOpacity: .5 }),
      }).addTo(_planningMapGroups.kmz);
      if (geo.getBounds().isValid()) bounds.push(geo.getBounds().getSouthWest(), geo.getBounds().getNorthEast());
    }
  }

  const boxState = new Map(a.boxInfo.map(info => [Number(info.box.id), info.state]));
  const max = Number(a.cableConfig.maxMeters) || 100;

  // Linhas primeiro, para ficarem por baixo dos marcadores.
  a.fiberRows.filter(row => !row.error).forEach(row => {
    L.polyline([[row.parent.latitude, row.parent.longitude], [row.node.latitude, row.node.longitude]], { color: '#b86b00', weight: 4, opacity: .85 })
      .bindTooltip(`${planningEscape(row.parent.name)} → ${planningEscape(row.node.name)} · ${Math.round(row.straight)} m em linha reta`, { sticky: true })
      .addTo(_planningMapGroups.fiber);
  });
  a.boxInfo.forEach(info => {
    const parent = info.parent;
    if (!parent || !planningHasCoords(parent) || !planningHasCoords(info.box)) return;
    L.polyline([[parent.latitude, parent.longitude], [info.box.latitude, info.box.longitude]], { color: '#0b7285', weight: 3, opacity: .85, dashArray: '9 6' })
      .bindTooltip(`Drop ${planningEscape(parent.name)} → ${planningEscape(info.box.name)}`, { sticky: true })
      .addTo(_planningMapGroups.fiber);
  });
  a.cableRows.filter(row => !row.error).forEach(row => {
    L.polyline([[row.box.latitude, row.box.longitude], [row.camera.latitude, row.camera.longitude]], { color: row.installed > max ? '#c92a2a' : '#1971c2', weight: 2, opacity: .9, dashArray: '2 5' })
      .bindTooltip(`${planningEscape(row.camera.name)} · ${Math.round(row.installed)} m de UTP`, { sticky: true })
      .addTo(_planningMapGroups.utp);
  });

  a.devices.forEach(item => {
    if (!planningHasCoords(item)) return;
    const lat = Number(item.latitude); const lon = Number(item.longitude);
    let marker; let group;
    if (item.device_type === 'camera') {
      const over = a.cableByCamera.get(Number(item.id))?.overLimit;
      marker = L.circleMarker([lat, lon], { radius: 7, color: '#fff', weight: 2, fillColor: over ? '#c92a2a' : '#087f5b', fillOpacity: 1 });
      group = 'cameras';
    } else if (item.device_type === 'box') {
      const state = boxState.get(Number(item.id));
      marker = L.marker([lat, lon], { icon: planningBoxIcon(planningShortLabel(item.name), state === 'danger' ? 'red' : state === 'full' ? 'amber' : 'blue') });
      group = 'boxes';
    } else if (['olt', 'rack'].includes(item.device_type)) {
      marker = L.marker([lat, lon], { icon: planningBoxIcon(item.device_type === 'olt' ? 'OLT' : 'RK', 'dark') });
      group = 'network';
    } else if (['cto', 'dio'].includes(item.device_type)) {
      marker = L.circleMarker([lat, lon], { radius: 9, color: '#fff', weight: 3, fillColor: '#0b7285', fillOpacity: 1 });
      group = 'network';
    } else {
      // Equipamento dentro da caixa repete a coordenada dela: nao desenha de novo.
      const insideBox = a.boxInfo.some(info => info.inside.some(child => Number(child.id) === Number(item.id)));
      if (insideBox) return;
      marker = L.circleMarker([lat, lon], { radius: 6, color: '#fff', weight: 2, fillColor: item.device_type === 'pole' ? '#66747e' : '#b86b00', fillOpacity: 1 });
      group = 'network';
    }
    marker.bindPopup(planningPopupHtml(item)).addTo(_planningMapGroups[group]);
    _planningMarkers[item.id] = marker;
    bounds.push([lat, lon]);
  });

  Object.entries(_planningMapGroups).forEach(([key, group]) => { if (_planningLayerOn[key]) group.addTo(_planningMap); });
  const hint = document.getElementById('planningMapHint');
  if (hint) {
    hint.textContent = bounds.length ? '' : 'Nenhum equipamento com posicao. Importe um KMZ ou informe as coordenadas.';
    hint.classList.toggle('hidden', !!bounds.length);
  }
  if (bounds.length) _planningMap.fitBounds(L.latLngBounds(bounds), { padding: [32, 32], maxZoom: 18 });
  setTimeout(() => _planningMap && _planningMap.invalidateSize(), 120);
}

function focusPlanningDevice(deviceId) {
  const marker = _planningMarkers[deviceId];
  if (!marker || !_planningMap) { openPlanningDeviceModal(deviceId); return; }
  const position = marker.getLatLng();
  document.getElementById('planningMap')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  _planningMap.flyTo(position, Math.max(_planningMap.getZoom(), 18), { duration: .45 });
  setTimeout(() => marker.openPopup(), 480);
}

// ---------------------------------------------------------------------------

function planningBindWorkspace() {
  const on = (id, event, handler) => { const el = document.getElementById(id); if (el) el.addEventListener(event, handler); };
  on('btnPlanningBack', 'click', () => { _planningIssueFilter = null; showPlanningEmpty(); });
  on('planningProjectSwitch', 'change', event => { const id = Number(event.target.value); if (id) selectPlanningProject(id); });
  on('planningProjectSearch', 'input', planningRenderPipeline);
  on('btnPlanningAdvance', 'click', planningAdvanceStatus);
  document.querySelectorAll('[data-pj-tab]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.pjTab === 'boxes' && _planningIssueFilter) { _planningIssueFilter = null; planningRenderIssueChip(); renderPlanningDevices(); }
    planningSetTab(button.dataset.pjTab);
  }));
  // Menus <details>: fecham ao escolher uma opcao ou clicar fora.
  document.addEventListener('click', event => {
    document.querySelectorAll('#viewPlanning details.pj-menu[open]').forEach(menu => {
      if (!menu.contains(event.target) || event.target.closest('.pj-menu-list button')) menu.removeAttribute('open');
    });
  });
}
