// Planos e licencas por equipamento.
// Painel do Dono: cartoes por cliente, tela Planos e licencas, alerta na visao geral.
// Configuracoes: aba "Meu plano e uso" (so leitura para o cliente).
// Backend: /api/auth/licensing* (so admin da plataforma) e /api/auth/my-plan.

let _licData = null;          // ultimo /api/auth/licensing
let _licTenantTarget = null;  // { id, name } do modal de plano do cliente
let _licPlanTarget = null;    // chave do plano em edicao (null = novo)

const LIC_STATUS = {
  ok: ['green', 'Dentro do plano'],
  aviso: ['amber', 'Perto do limite'],
  tolerancia: ['red', 'Em tolerância'],
  excedido: ['red', 'Acima do limite'],
  sem_limite: ['gray', 'Sem limite'],
  sem_plano: ['gray', 'Sem plano'],
};
const LIC_LOGO = { ok: 'g', aviso: 'a', tolerancia: 'r', excedido: 'r', sem_limite: 'n', sem_plano: 'n' };

function licNum(n) {
  return Number(n || 0).toLocaleString('pt-BR', { maximumFractionDigits: 1 });
}

function licPreco(p) {
  if (p === null || p === undefined || p === '') return 'negociado';
  if (Number(p) === 0) return 'grátis';
  return `R$ ${Number(p).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function licDia(iso) {
  const m = String(iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}` : '';
}

function licIniciais(nome) {
  const partes = String(nome || '?').trim().split(/\s+/).filter(Boolean);
  return (partes.length > 1 ? partes[0][0] + partes[1][0] : (partes[0] || '?').slice(0, 2)).toUpperCase();
}

function licBadge(s) {
  const [cor, texto] = LIC_STATUS[s.status] || ['gray', s.status || '-'];
  let t = texto;
  if (s.status === 'aviso' && s.license_limit) t = `${Math.round((s.licenses_used * 100) / s.license_limit)}% do limite`;
  if (s.status === 'tolerancia' && s.tolerance_until) t = `Tolerância até ${licDia(s.tolerance_until)}`;
  return `<span class="badge badge-${cor} so-dot">${esc(t)}</span>`;
}

function licBar(used, limit) {
  if (limit === null || limit === undefined) return '<div class="so-bar"><i class="n" style="width:100%"></i></div>';
  const r = limit > 0 ? used / limit : (used > 0 ? 2 : 0);
  const cls = r > 1 ? 'b' : r >= 0.9 ? 'w' : '';
  return `<div class="so-bar"><i class="${cls}" style="width:${Math.min(r, 1) * 100}%"></i></div>`;
}

function licUso(s) {
  return s.license_limit === null || s.license_limit === undefined
    ? `${licNum(s.licenses_used)} <span class="text-muted">· sem limite</span>`
    : `${licNum(s.licenses_used)} / ${licNum(s.license_limit)}`;
}

function soCard({ logo, cor = 'n', title, badge = '', actions = '', rows = [], foot = '', cls = '' }) {
  const dl = rows.map(([k, v]) => (k === '' ? `<dd class="full">${v}</dd>` : `<dt>${esc(k)}</dt><dd>${v}</dd>`)).join('');
  return `<div class="so-card ${cls}">
    <div class="so-card-h"><span class="so-card-logo ${cor}">${logo}</span>
      <div class="so-card-t"><strong title="${esc(title)}">${esc(title)}</strong>${badge}</div>
      <div class="so-card-a">${actions}</div></div>
    ${dl ? `<dl>${dl}</dl>` : ''}${foot ? `<div class="so-card-f">${foot}</div>` : ''}</div>`;
}

function licBreakdownRows(rows) {
  if (!rows || !rows.length) return '<tr class="empty-row"><td colspan="4">Nenhum equipamento cadastrado no monitoramento.</td></tr>';
  const total = rows.reduce((acc, r) => acc + Number(r.licenses || 0), 0);
  return rows.map(r => `<tr>
      <td>${esc(r.label)}</td><td class="num">${licNum(r.count)}</td>
      <td class="num">× ${licNum(r.weight)}</td><td class="num"><strong>${licNum(r.licenses)}</strong></td></tr>`).join('')
    + `<tr><td colspan="3"><strong>Total</strong> <span class="text-muted">(fração conta como licença inteira)</span></td><td class="num"><strong>${licNum(Math.ceil(total - 1e-9))}</strong></td></tr>`;
}

async function licLoad(force = true) {
  _licData = await apiJson('/api/auth/licensing', { forceRefresh: force });
  return _licData;
}

// ------------------------------------------------------------ Painel do Dono

async function renderOwnerLicenseCards() {
  const box = document.getElementById('ownerLicCards');
  if (!box || !_currentUser?.is_platform_admin) return;
  const data = await licLoad();
  if (!data) { box.innerHTML = ''; return; }
  box.innerHTML = (data.tenants || []).map(s => soCard({
    logo: esc(licIniciais(s.tenant_name)),
    cor: LIC_LOGO[s.status] || 'n',
    title: s.tenant_name,
    badge: licBadge(s),
    actions: `<button class="secondary-action" type="button" data-lic-tenant="${Number(s.tenant_id)}"><i data-lucide="package"></i> Plano</button>`,
    rows: [
      ['Plano', esc(s.plan?.name || 'Sem plano')],
      ['Equipamentos', licUso(s)],
      ['', licBar(s.licenses_used, s.license_limit)],
      ['Usuários', `${licNum(s.users ?? 0)}${s.user_limit !== null && s.user_limit !== undefined ? ` / ${licNum(s.user_limit)}` : ''}`],
      ['Renovação', esc(s.renewal || '—')],
    ],
  })).join('');
  if (!box.dataset.bound) {
    box.addEventListener('click', ev => {
      const b = ev.target.closest('[data-lic-tenant]');
      if (b) openTenantPlanModal(Number(b.dataset.licTenant));
    });
    box.dataset.bound = '1';
  }
  lucide.createIcons();
}

async function renderOwnerLicenseAttention() {
  const box = document.getElementById('ownerLicAttention');
  if (!box || !_currentUser?.is_platform_admin) return;
  const data = await licLoad();
  if (!data) { box.innerHTML = ''; return; }
  const ts = data.tenants || [];
  const pagantes = ts.filter(s => s.license_limit !== null && s.license_limit !== undefined);
  const usado = pagantes.reduce((a, s) => a + s.licenses_used, 0);
  const contratado = pagantes.reduce((a, s) => a + s.license_limit, 0);
  const total = ts.reduce((a, s) => a + s.licenses_used, 0);
  const semPlano = ts.filter(s => s.status === 'sem_plano').length;
  const atencao = ts.filter(s => ['aviso', 'tolerancia', 'excedido'].includes(s.status))
    .sort((a, b) => ['excedido', 'tolerancia', 'aviso'].indexOf(a.status) - ['excedido', 'tolerancia', 'aviso'].indexOf(b.status));
  const ico = { excedido: ['alert-octagon', 'r'], tolerancia: ['alert-octagon', 'r'], aviso: ['trending-up', 'a'] };
  const itens = atencao.map(s => {
    const [i, c] = ico[s.status];
    const msg = s.status === 'aviso'
      ? `${esc(s.tenant_name)} está em ${licNum(s.licenses_used)} de ${licNum(s.license_limit)}.`
      : `${esc(s.tenant_name)} passou do limite: ${licNum(s.licenses_used)} de ${licNum(s.license_limit)}.`;
    const det = s.status === 'tolerancia' && s.tolerance_until ? `Em tolerância até ${licDia(s.tolerance_until)}.`
      : s.status === 'excedido' ? 'A tolerância acabou.' : `Plano ${esc(s.plan?.name || '')}.`;
    return `<div class="so-check-item"><span class="so-card-logo ${c}" style="width:34px;height:34px"><i data-lucide="${i}"></i></span>
      <div><strong>${msg}</strong><small>${det}</small></div>
      <button class="secondary-action" type="button" data-lic-tenant="${Number(s.tenant_id)}">Ver plano</button></div>`;
  }).join('');
  box.innerHTML = `
    <div class="settings-status-grid" style="grid-template-columns:repeat(3,minmax(140px,1fr));padding:0;margin-top:12px">
      <div class="settings-status-card"><span>Licenças em uso (com limite)</span><strong>${licNum(usado)} <em>/ ${licNum(contratado)}</em></strong>${licBar(usado, contratado)}</div>
      <div class="settings-status-card"><span>Equipamentos monitorados</span><strong>${licNum(total)} <em>licenças em todos os clientes</em></strong><small>conta pelo peso de cada tipo</small></div>
      <div class="settings-status-card"><span>Clientes sem plano</span><strong>${licNum(semPlano)}</strong><small>${semPlano ? 'defina em Clientes → Plano' : 'todos com plano definido'}</small></div>
    </div>
    ${atencao.length ? `<div class="panel settings-wide-panel" style="margin-top:20px">
      <div class="panel-header"><div><h2>Precisa de atenção</h2><p>Clientes perto ou acima do limite de equipamentos.</p></div><span class="badge badge-amber">${atencao.length} cliente${atencao.length === 1 ? '' : 's'}</span></div>
      <div class="so-check">${itens}</div></div>` : ''}`;
  if (!box.dataset.bound) {
    box.addEventListener('click', ev => {
      const b = ev.target.closest('[data-lic-tenant]');
      if (b) openTenantPlanModal(Number(b.dataset.licTenant));
    });
    box.dataset.bound = '1';
  }
  lucide.createIcons();
}

async function loadOwnerPlans() {
  if (!_currentUser?.is_platform_admin) return;
  const data = await licLoad();
  if (!data) { showToast('Não foi possível carregar os planos.', true); return; }
  const cores = ['n', 'b', 'g', 'o', 'c', 'a'];
  const cards = document.getElementById('licPlanCards');
  if (cards) {
    cards.innerHTML = (data.plans || []).map((p, i) => soCard({
      logo: esc(licIniciais(p.name)),
      cor: cores[i % cores.length],
      title: p.name,
      badge: `<span class="badge badge-gray so-dot">${licNum(p.tenants || 0)} cliente${Number(p.tenants) === 1 ? '' : 's'}</span>`,
      actions: `<button class="secondary-action" type="button" data-lic-plan="${esc(p.key)}"><i data-lucide="pencil"></i> Editar</button>`,
      rows: [
        ['Equipamentos', p.license_limit === null || p.license_limit === undefined ? 'sem limite' : `até ${licNum(p.license_limit)}`],
        ['Preço', p.price === null || p.price === undefined ? 'negociado' : Number(p.price) === 0 ? 'grátis' : `${licPreco(p.price)} / equip.`],
        ['Usuários', p.user_limit === null || p.user_limit === undefined ? 'sem limite' : licNum(p.user_limit)],
        ['Teste', p.trial_days ? `${licNum(p.trial_days)} dias` : '—'],
      ],
      foot: (p.features || []).map(f => `<span class="badge badge-gray">${esc(f)}</span>`).join(''),
    })).join('');
    if (!cards.dataset.bound) {
      cards.addEventListener('click', ev => {
        const b = ev.target.closest('[data-lic-plan]');
        if (b) openLicPlanModal(b.dataset.licPlan);
      });
      cards.dataset.bound = '1';
    }
  }

  const totais = {};
  (data.tenants || []).forEach(s => (s.breakdown || []).forEach(r => { totais[r.type] = (totais[r.type] || 0) + r.count; }));
  const body = document.getElementById('licWeightsBody');
  if (body) {
    body.innerHTML = (data.entity_types || []).map(t => {
      const w = data.weights?.[t.type] ?? t.weight;
      const n = totais[t.type] || 0;
      return `<tr><td>${esc(t.label)}</td><td class="num">${licNum(n)}</td>
        <td><div class="so-unit"><input type="text" inputmode="decimal" data-lic-weight="${esc(t.type)}" value="${esc(String(w).replace('.', ','))}" aria-label="Peso de ${esc(t.label)}"></div></td>
        <td class="num"><strong>${licNum(n * Number(w))}</strong></td></tr>`;
    }).join('');
  }
  const pol = data.policy || {};
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v ?? ''; };
  set('licWarnPct', pol.warn_pct);
  set('licTolPct', pol.tolerance_pct);
  set('licTolDays', pol.tolerance_days);
  set('licAfter', pol.after || 'block');
  set('licOverPrice', pol.overage_price === undefined ? '' : String(pol.overage_price).replace('.', ','));
  scheduleResponsiveHydration(document.getElementById('viewOwnerPlans'));
  lucide.createIcons();
}

async function saveLicWeights() {
  const weights = {};
  document.querySelectorAll('[data-lic-weight]').forEach(i => { weights[i.dataset.licWeight] = i.value.trim(); });
  try {
    const res = await api('/api/auth/licensing/weights', { method: 'PUT', body: JSON.stringify({ weights }) });
    await jsonOrReadableError(res, 'Não foi possível salvar os pesos.');
    showToast('Pesos salvos. O uso de todos os clientes foi recalculado.');
    await loadOwnerPlans();
  } catch (e) { showToast(e?.message || 'Não foi possível salvar os pesos.', true); }
}

async function saveLicPolicy() {
  const v = id => document.getElementById(id)?.value ?? '';
  const payload = {
    warn_pct: v('licWarnPct'), tolerance_pct: v('licTolPct'), tolerance_days: v('licTolDays'),
    after: v('licAfter'), overage_price: v('licOverPrice') || '0',
  };
  try {
    const res = await api('/api/auth/licensing/policy', { method: 'PUT', body: JSON.stringify(payload) });
    await jsonOrReadableError(res, 'Não foi possível salvar a regra.');
    showToast('Regra do limite salva.');
    await loadOwnerPlans();
  } catch (e) { showToast(e?.message || 'Não foi possível salvar a regra.', true); }
}

// ------------------------------------------------------------ modal: plano do cliente

async function openTenantPlanModal(tenantId) {
  if (!_licData) await licLoad();
  const s = (_licData?.tenants || []).find(t => Number(t.tenant_id) === Number(tenantId));
  if (!s) { showToast('Cliente não encontrado.', true); return; }
  _licTenantTarget = { id: Number(tenantId), name: s.tenant_name };
  const sel = document.getElementById('tenantPlanKey');
  sel.innerHTML = '<option value="">Sem plano</option>' + (_licData.plans || []).map(p =>
    `<option value="${esc(p.key)}">${esc(p.name)} · ${p.license_limit === null || p.license_limit === undefined ? 'sem limite' : `até ${licNum(p.license_limit)}`}</option>`).join('');
  sel.value = s.plan?.key || '';
  const plano = (_licData.plans || []).find(p => p.key === s.plan?.key);
  const setv = (id, v, ph) => { const el = document.getElementById(id); el.value = v ?? ''; if (ph !== undefined) el.placeholder = ph; };
  setv('tenantPlanLimit', s.license_limit_override ? s.license_limit : '', plano && plano.license_limit !== null ? `do plano: ${plano.license_limit}` : 'do plano');
  setv('tenantPlanUsers', '', plano && plano.user_limit !== null ? `do plano: ${plano.user_limit}` : 'do plano');
  setv('tenantPlanRenewal', s.renewal);
  setv('tenantPlanTolPct', '', `padrão: ${_licData.policy?.tolerance_pct ?? 10}`);
  setv('tenantPlanTolDays', '', `padrão: ${_licData.policy?.tolerance_days ?? 15}`);
  setv('tenantPlanNote', s.note);
  document.getElementById('tenantPlanTitle').textContent = s.tenant_name;
  document.getElementById('tenantPlanSubtitle').textContent = `${s.tenant_slug} · ${licNum(s.users ?? 0)} usuário(s)`;
  document.getElementById('tenantPlanUsage').innerHTML = `Uso hoje: ${licUso(s)} licenças ${licBadge(s)}`;
  document.getElementById('tenantPlanBreakdown').innerHTML = licBreakdownRows(s.breakdown);
  const err = document.getElementById('tenantPlanErro');
  err.hidden = true;
  document.getElementById('modalTenantPlan').classList.remove('hidden');
  lucide.createIcons();
}

function closeTenantPlanModal() {
  _licTenantTarget = null;
  document.getElementById('modalTenantPlan')?.classList.add('hidden');
}

async function saveTenantPlan() {
  if (!_licTenantTarget) return;
  const v = id => document.getElementById(id)?.value.trim() ?? '';
  const payload = {
    plan: v('tenantPlanKey'), license_limit: v('tenantPlanLimit'), user_limit: v('tenantPlanUsers'),
    tolerance_pct: v('tenantPlanTolPct'), tolerance_days: v('tenantPlanTolDays'),
    renewal: v('tenantPlanRenewal'), note: v('tenantPlanNote'),
  };
  const err = document.getElementById('tenantPlanErro');
  try {
    const res = await api(`/api/auth/licensing/tenants/${_licTenantTarget.id}`, { method: 'PUT', body: JSON.stringify(payload) });
    await jsonOrReadableError(res, 'Não foi possível salvar o plano.');
    showToast(`Plano de ${_licTenantTarget.name} salvo.`);
    closeTenantPlanModal();
    await licLoad();
    await renderOwnerLicenseCards();
    await renderOwnerLicenseAttention();
  } catch (e) {
    err.textContent = e?.message || 'Não foi possível salvar o plano.';
    err.hidden = false;
  }
}

// ------------------------------------------------------------ modal: plano (catalogo)

function openLicPlanModal(key) {
  const p = key ? (_licData?.plans || []).find(x => x.key === key) : null;
  _licPlanTarget = p ? p.key : null;
  const setv = (id, v) => { const el = document.getElementById(id); el.value = v ?? ''; };
  document.getElementById('licPlanTitle').textContent = p ? p.name : 'Novo plano';
  setv('licPlanName', p?.name);
  setv('licPlanKeyInput', p?.key);
  document.getElementById('licPlanKeyInput').disabled = !!p;
  setv('licPlanLimit', p?.license_limit);
  setv('licPlanUsers', p?.user_limit);
  setv('licPlanPrice', p?.price === null || p?.price === undefined ? '' : String(p.price).replace('.', ','));
  setv('licPlanTrial', p?.trial_days || '');
  setv('licPlanFeatures', (p?.features || []).join('\n'));
  document.getElementById('licPlanErro').hidden = true;
  document.getElementById('modalLicPlan').classList.remove('hidden');
  lucide.createIcons();
}

function closeLicPlanModal() {
  _licPlanTarget = null;
  document.getElementById('modalLicPlan')?.classList.add('hidden');
}

async function saveLicPlan() {
  const v = id => document.getElementById(id)?.value ?? '';
  const key = _licPlanTarget || v('licPlanKeyInput').trim().toLowerCase();
  const err = document.getElementById('licPlanErro');
  if (!key) { err.textContent = 'Informe a chave do plano.'; err.hidden = false; return; }
  const payload = {
    name: v('licPlanName').trim(), license_limit: v('licPlanLimit'), user_limit: v('licPlanUsers'),
    price: v('licPlanPrice').trim(), trial_days: v('licPlanTrial'), features: v('licPlanFeatures'),
  };
  try {
    const res = await api(`/api/auth/licensing/plans/${encodeURIComponent(key)}`, { method: 'PUT', body: JSON.stringify(payload) });
    await jsonOrReadableError(res, 'Não foi possível salvar o plano.');
    showToast(`Plano ${payload.name} salvo.`);
    closeLicPlanModal();
    await loadOwnerPlans();
  } catch (e) {
    err.textContent = e?.message || 'Não foi possível salvar o plano.';
    err.hidden = false;
  }
}

// ------------------------------------------------------------ Configuracoes: Meu plano e uso

async function loadMyPlan(currentUser) {
  const nav = document.getElementById('settingsNavPlan');
  const pode = ['owner', 'admin'].includes(String(currentUser?.role || '').toLowerCase());
  if (nav) nav.hidden = !pode;
  if (!pode) {
    if (sessionStorage.getItem('sightops.settings.tab') === 'plan') sessionStorage.setItem('sightops.settings.tab', 'overview');
    return;
  }
  const s = await apiJson('/api/auth/my-plan', { forceRefresh: true });
  if (!s) return;
  const limite = s.license_limit !== null && s.license_limit !== undefined;
  setText('settingsNavPlanSub', limite ? `${licNum(s.licenses_used)} de ${licNum(s.license_limit)} equipamentos` : `${licNum(s.licenses_used)} equipamentos`);
  setText('myPlanTitle', s.plan ? `Plano ${s.plan.name}` : 'Meu plano e uso');
  setText('myPlanSubtitle', s.plan
    ? `${limite ? `${licNum(s.license_limit)} equipamentos` : 'Sem limite de equipamentos'}${s.user_limit !== null && s.user_limit !== undefined ? ` · ${licNum(s.user_limit)} usuários` : ''}${s.renewal ? ` · renova ${s.renewal}` : ''}. Mudança de plano é feita pela Easy.`
    : 'Este cliente ainda não tem plano definido. Fale com a Easy.');
  const badge = document.getElementById('myPlanBadge');
  if (badge) badge.innerHTML = licBadge(s);
  const sobra = limite ? s.license_limit - s.licenses_used : null;
  const cards = document.getElementById('myPlanCards');
  if (cards) {
    cards.innerHTML = `
      <div class="settings-status-card"><span>Equipamentos</span><strong>${licNum(s.licenses_used)} <em>${limite ? `/ ${licNum(s.license_limit)} licenças` : 'licenças'}</em></strong>${licBar(s.licenses_used, s.license_limit)}<small>${limite ? (sobra >= 0 ? `sobram ${licNum(sobra)}` : `${licNum(-sobra)} acima do limite`) : 'sem limite no plano'}</small></div>
      <div class="settings-status-card"><span>Usuários</span><strong>${licNum(s.users ?? 0)} <em>${s.user_limit !== null && s.user_limit !== undefined ? `/ ${licNum(s.user_limit)}` : ''}</em></strong>${licBar(s.users ?? 0, s.user_limit)}<small>da equipe deste cliente</small></div>
      <div class="settings-status-card"><span>Situação</span><strong>${esc((LIC_STATUS[s.status] || ['', '-'])[1])}</strong><small>${s.status === 'tolerancia' && s.tolerance_until ? `ajuste até ${licDia(s.tolerance_until)}` : s.status === 'excedido' ? 'cadastro novo pode ser bloqueado' : s.status === 'aviso' ? 'perto do limite do plano' : 'monitoramento normal'}</small></div>`;
  }
  setText('myPlanBreakdownTitle', `Como chegamos em ${licNum(s.licenses_used)}`);
  const tb = document.getElementById('myPlanBreakdown');
  if (tb) tb.innerHTML = licBreakdownRows(s.breakdown);
  const feats = document.getElementById('myPlanFeatures');
  if (feats) {
    const lista = s.plan?.features || [];
    feats.hidden = !lista.length;
    feats.innerHTML = lista.length ? `<p class="so-section-title">O que o plano inclui</p><div style="display:flex;gap:8px;flex-wrap:wrap">${lista.map(f => `<span class="badge badge-green">${esc(f)}</span>`).join('')}</div>` : '';
  }
  const note = document.getElementById('myPlanNote');
  if (note) note.className = `so-note${['tolerancia', 'excedido'].includes(s.status) ? ' red' : s.status === 'aviso' ? ' amber' : ''}`;
}

// ------------------------------------------------------------ eventos

(function bindLicencas() {
  const on = (id, fn) => document.getElementById(id)?.addEventListener('click', fn);
  on('btnOwnerPlansRefresh', loadOwnerPlans);
  on('btnLicNewPlan', () => openLicPlanModal(null));
  on('btnLicSaveWeights', saveLicWeights);
  on('btnLicSavePolicy', saveLicPolicy);
  on('btnCloseTenantPlan', closeTenantPlanModal);
  on('btnCancelTenantPlan', closeTenantPlanModal);
  on('btnSaveTenantPlan', saveTenantPlan);
  on('btnCloseLicPlan', closeLicPlanModal);
  on('btnCancelLicPlan', closeLicPlanModal);
  on('btnSaveLicPlan', saveLicPlan);
  // Fecha so por X, Cancelar ou Esc -- clicar fora nao fecha (perdia o que foi digitado).
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape') return;
    if (!document.getElementById('modalTenantPlan')?.classList.contains('hidden')) closeTenantPlanModal();
    if (!document.getElementById('modalLicPlan')?.classList.contains('hidden')) closeLicPlanModal();
  });
})();
