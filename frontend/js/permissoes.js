// Fase 3: perfis de acesso por modulo x nivel.
// Configuracoes: aba "Perfis de acesso" e painel "Acesso por usuario".
// Painel do Dono / Auditoria: modo sombra (divergencias) e o botao de passar a valer.
// Backend: /api/auth/access-profiles*, /api/auth/users/{id}/access, /api/auth/permissions/*.

const PERM_NIVEIS = [
  { v: 0, label: 'Sem acesso' },
  { v: 1, label: 'Ver' },
  { v: 2, label: 'Operar' },
  { v: 3, label: 'Administrar' },
];
const PERM_BADGE = { 0: 'gray', 1: 'blue', 2: 'green', 3: 'amber' };
const PERM_PADRAO = { viewer: 1, operator: 2, admin: 3, owner: 3 };

let _perm = null;            // ultimo /api/auth/access-profiles
let _permEditando = null;    // chave do perfil no editor ('' = novo)
let _permUsuario = null;     // usuario no modal

function permNivelLabel(n) {
  return (PERM_NIVEIS.find(x => x.v === Number(n)) || PERM_NIVEIS[0]).label;
}

function permSelect(valor, attrs, comVazio) {
  const ops = (comVazio ? [`<option value="">${esc(comVazio)}</option>`] : [])
    .concat(PERM_NIVEIS.map(n => `<option value="${n.v}" ${String(valor) === String(n.v) ? 'selected' : ''}>${n.label}</option>`));
  return `<select ${attrs}>${ops.join('')}</select>`;
}

function permModoNota() {
  if (!_perm) return '';
  if (_perm.modo === 'valer') {
    return '<div class="so-note"><i data-lucide="shield-check"></i><span>Os perfis de acesso estão valendo. Cada pessoa usa o nível do perfil dela em cada módulo.</span></div>';
  }
  return '<div class="so-note amber"><i data-lucide="flask-conical"></i><span><strong>Em teste.</strong> Os perfis podem ser montados, mas ainda <strong>não valem</strong>: cada pessoa continua com o perfil fixo (Visualizador, Operador, Administrador ou Dono). A Easy ativa quando terminar a verificação.</span></div>';
}

async function loadAccessProfiles(currentUser) {
  const admin = ['owner', 'admin'].includes(String(currentUser?.role || '').toLowerCase());
  const nav = document.getElementById('settingsNavProfiles');
  const painelUsuarios = document.getElementById('userAccessPanel');
  if (!admin) {
    if (nav) nav.hidden = true;
    if (painelUsuarios) painelUsuarios.hidden = true;
    return;
  }
  _perm = await apiJson('/api/auth/access-profiles', { forceRefresh: true });
  if (!_perm) return;
  // Admin do cliente ve e monta os perfis mesmo em teste; o aviso "Em teste" diz que ainda nao valem.
  const visivel = true;
  if (nav) nav.hidden = !visivel;
  if (painelUsuarios) painelUsuarios.hidden = !visivel;
  if (!visivel && ['profiles'].includes(sessionStorage.getItem('sightops.settings.tab'))) sessionStorage.setItem('sightops.settings.tab', 'overview');
  if (!visivel) return;
  const nPerfis = Object.keys(_perm.perfis || {}).length;
  setText('settingsNavProfilesSub', `${4 + nPerfis} perfis${_perm.modo === 'valer' ? '' : ' · em teste'}`);
  const nota = document.getElementById('accessModeNote');
  if (nota) nota.innerHTML = permModoNota();
  const badge = document.getElementById('userAccessModeBadge');
  if (badge) badge.innerHTML = _perm.modo === 'valer' ? '<span class="badge badge-green so-dot">Valendo</span>' : '<span class="badge badge-amber so-dot">Em teste</span>';
  renderAccessProfileCards();
  renderUserAccessTable();
  lucide.createIcons();
}

function permContaUsuarios(chave) {
  return (_perm?.usuarios || []).filter(u => (chave in PERM_PADRAO ? (!u.profile && u.role === chave) : u.profile === chave)).length;
}

function renderAccessProfileCards() {
  const box = document.getElementById('accessProfileCards');
  if (!box || !_perm) return;
  const modulos = _perm.modulos || [];
  const padrao = (_perm.perfis_padrao || []).map(p => soCard({
    logo: esc(licIniciais(p.name)), cor: 'n', title: p.name,
    badge: '<span class="badge badge-gray so-dot">padrão</span>',
    rows: [['Todos os módulos', permNivelLabel(PERM_PADRAO[p.key])], ['Usuários', licNum(permContaUsuarios(p.key))]],
    foot: `<small class="text-muted">${esc(p.descricao || '')}</small>`,
  }));
  const proprios = Object.entries(_perm.perfis || {}).map(([chave, p]) => {
    const niveis = p.levels || {};
    const contagem = [3, 2, 1, 0].map(v => [v, modulos.filter(m => Number(niveis[m.key] ?? 0) === v).length]).filter(([, n]) => n);
    return soCard({
      logo: esc(licIniciais(p.name)), cor: 'g', title: p.name,
      badge: '<span class="badge badge-green so-dot">personalizado</span>',
      actions: `<button class="secondary-action" type="button" data-perm-edit="${esc(chave)}"><i data-lucide="pencil"></i> Editar</button>`,
      rows: [...contagem.map(([v, n]) => [permNivelLabel(v), `${licNum(n)} módulo${n === 1 ? '' : 's'}`]), ['Usuários', licNum(permContaUsuarios(chave))]],
    });
  });
  box.innerHTML = padrao.concat(proprios).join('');
}

function openAccessProfileEditor(chave) {
  const ed = document.getElementById('accessProfileEditor');
  if (!ed || !_perm) return;
  _permEditando = chave || '';
  const p = chave ? (_perm.perfis || {})[chave] : null;
  setText('accessEditorTitle', p ? p.name : 'Novo perfil');
  setText('accessEditorSub', `${p ? `${licNum(permContaUsuarios(chave))} usuário(s) usam este perfil. ` : ''}Administrar só vale para quem tem o perfil fixo Administrador; para os outros, conta como Operar.`);
  document.getElementById('accessProfileName').value = p?.name || '';
  document.getElementById('accessProfileBase').value = '';
  document.getElementById('btnDeleteAccessProfile').hidden = !p;
  const niveis = p?.levels || {};
  const plano = _perm.modulos_no_plano;
  document.getElementById('accessProfileMatrix').innerHTML = (_perm.modulos || []).map(m => {
    const fora = Array.isArray(plano) && m.views.length && !m.views.some(v => plano.includes(v));
    return `<tr><td>${esc(m.label)}${fora ? ' <span class="badge badge-gray">fora do plano</span>' : ''}</td>
      <td><div class="so-unit">${permSelect(niveis[m.key] ?? (p ? 0 : 1), `data-perm-mod="${esc(m.key)}" aria-label="Nível em ${esc(m.label)}"`)}</div></td></tr>`;
  }).join('');
  ed.hidden = false;
  ed.classList.add('active');
  ed.scrollIntoView({ behavior: 'smooth', block: 'start' });
  lucide.createIcons();
}

async function saveAccessProfile() {
  const nome = document.getElementById('accessProfileName').value.trim();
  if (!nome) { showToast('Informe o nome do perfil.', true); return; }
  const chave = _permEditando || nome.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);
  if (!chave || chave in PERM_PADRAO) { showToast('Escolha outro nome: esse é de um perfil padrão.', true); return; }
  if (!_permEditando && (_perm?.perfis || {})[chave]) { showToast('Já existe um perfil com esse nome.', true); return; }
  const levels = {};
  document.querySelectorAll('#accessProfileMatrix [data-perm-mod]').forEach(sel => { levels[sel.dataset.permMod] = Number(sel.value); });
  try {
    const res = await api(`/api/auth/access-profiles/${encodeURIComponent(chave)}`, { method: 'PUT', body: JSON.stringify({ name: nome, levels }) });
    await jsonOrReadableError(res, 'Não foi possível salvar o perfil.');
    showToast(`Perfil ${nome} salvo.`);
    document.getElementById('accessProfileEditor').hidden = true;
    await loadAccessProfiles(_currentUser);
  } catch (e) { showToast(e?.message || 'Não foi possível salvar o perfil.', true); }
}

async function deleteAccessProfile() {
  if (!_permEditando) return;
  const btn = document.getElementById('btnDeleteAccessProfile');
  if (btn.dataset.confirmar !== '1') {
    btn.dataset.confirmar = '1';
    btn.innerHTML = '<i data-lucide="trash-2"></i> Confirmar exclusão';
    lucide.createIcons();
    setTimeout(() => { btn.dataset.confirmar = ''; btn.innerHTML = '<i data-lucide="trash-2"></i> Excluir'; lucide.createIcons(); }, 4000);
    return;
  }
  try {
    const res = await api(`/api/auth/access-profiles/${encodeURIComponent(_permEditando)}`, { method: 'DELETE' });
    await jsonOrReadableError(res, 'Não foi possível excluir o perfil.');
    showToast('Perfil excluído.');
    document.getElementById('accessProfileEditor').hidden = true;
    await loadAccessProfiles(_currentUser);
  } catch (e) { showToast(e?.message || 'Não foi possível excluir o perfil.', true); }
}

function renderUserAccessTable() {
  const body = document.getElementById('userAccessBody');
  if (!body || !_perm) return;
  const fixos = Object.fromEntries((_perm.perfis_padrao || []).map(p => [p.key, p.name]));
  body.innerHTML = (_perm.usuarios || []).map(u => {
    const perfil = u.profile ? ((_perm.perfis || {})[u.profile]?.name || u.profile) : `${fixos[u.role] || u.role} (padrão)`;
    const ajustes = Object.entries(u.overrides || {});
    const eu = Number(u.id) === Number(_currentUser?.id);
    const dono = u.role === 'owner';
    return `<tr>
      <td class="settings-cell-truncate"><strong>${esc(u.username)}</strong>${u.full_name ? ` <span class="text-muted">${esc(u.full_name)}</span>` : ''}</td>
      <td>${esc(fixos[u.role] || u.role)}</td>
      <td class="settings-cell-truncate">${esc(perfil)}</td>
      <td class="settings-cell-truncate">${ajustes.length ? ajustes.map(([m, v]) => `<span class="badge badge-${PERM_BADGE[v] || 'gray'}">${esc((_perm.modulos.find(x => x.key === m) || {}).label || m)}: ${permNivelLabel(v)}</span>`).join(' ') : '<span class="text-muted">—</span>'}</td>
      <td>${dono ? '<span class="text-muted">acesso total</span>' : eu ? '<span class="text-muted">você</span>' : `<button class="secondary-action" type="button" data-perm-user="${Number(u.id)}" style="padding:5px 10px;font-size:12px"><i data-lucide="sliders-horizontal"></i> Ajustar</button>`}</td></tr>`;
  }).join('') || '<tr class="empty-row"><td colspan="5">Nenhum usuário.</td></tr>';
}

function permNiveisDoPerfil(u, chavePerfil) {
  const base = PERM_PADRAO[u.role] ?? 1;
  const p = chavePerfil ? (_perm.perfis || {})[chavePerfil] : null;
  const out = {};
  (_perm.modulos || []).forEach(m => {
    let v = p ? Number(p.levels?.[m.key] ?? base) : base;
    if (m.key === 'administracao') v = Math.min(v, base);
    out[m.key] = v;
  });
  return out;
}

function openUserAccessModal(userId) {
  const u = (_perm?.usuarios || []).find(x => Number(x.id) === Number(userId));
  if (!u) return;
  _permUsuario = u;
  const fixos = Object.fromEntries((_perm.perfis_padrao || []).map(p => [p.key, p.name]));
  setText('userAccessTitle', u.username);
  setText('userAccessSub', `Perfil fixo: ${fixos[u.role] || u.role}. Administração nunca passa dele.`);
  const sel = document.getElementById('userAccessProfile');
  sel.innerHTML = `<option value="">${esc(fixos[u.role] || u.role)} (padrão)</option>` +
    Object.entries(_perm.perfis || {}).map(([k, p]) => `<option value="${esc(k)}">${esc(p.name)}</option>`).join('');
  sel.value = u.profile || '';
  renderUserAccessMatrix();
  document.getElementById('userAccessErro').hidden = true;
  document.getElementById('modalUserAccess').classList.remove('hidden');
  lucide.createIcons();
}

function renderUserAccessMatrix() {
  const u = _permUsuario;
  if (!u) return;
  const doPerfil = permNiveisDoPerfil(u, document.getElementById('userAccessProfile').value);
  const ajustes = u._ajustesTela || u.overrides || {};
  document.getElementById('userAccessMatrix').innerHTML = (_perm.modulos || []).map(m => `<tr>
    <td>${esc(m.label)}</td>
    <td><span class="badge badge-${PERM_BADGE[doPerfil[m.key]] || 'gray'}">${permNivelLabel(doPerfil[m.key])}</span></td>
    <td><div class="so-unit">${permSelect(ajustes[m.key] ?? '', `data-perm-ajuste="${esc(m.key)}" aria-label="Ajuste em ${esc(m.label)}"`, 'igual ao perfil')}</div></td></tr>`).join('');
}

function closeUserAccessModal() {
  if (_permUsuario) delete _permUsuario._ajustesTela;
  _permUsuario = null;
  document.getElementById('modalUserAccess')?.classList.add('hidden');
}

async function saveUserAccess() {
  const u = _permUsuario;
  if (!u) return;
  const overrides = {};
  document.querySelectorAll('#userAccessMatrix [data-perm-ajuste]').forEach(sel => {
    if (sel.value !== '') overrides[sel.dataset.permAjuste] = Number(sel.value);
  });
  const err = document.getElementById('userAccessErro');
  try {
    const res = await api(`/api/auth/users/${Number(u.id)}/access`, {
      method: 'PUT', body: JSON.stringify({ profile: document.getElementById('userAccessProfile').value, overrides }),
    });
    await jsonOrReadableError(res, 'Não foi possível salvar o acesso.');
    showToast(`Acesso de ${u.username} salvo.`);
    closeUserAccessModal();
    await loadAccessProfiles(_currentUser);
  } catch (e) {
    err.textContent = e?.message || 'Não foi possível salvar o acesso.';
    err.hidden = false;
  }
}

// ------------------------------------------------------------ Painel do Dono: modo sombra

async function renderOwnerPermissions() {
  if (!_currentUser?.is_platform_admin) return;
  const d = await apiJson('/api/auth/permissions/shadow', { forceRefresh: true });
  if (!d) return;
  const valendo = d.modo === 'valer';
  const badge = document.getElementById('ownerPermBadge');
  if (badge) badge.innerHTML = valendo ? '<span class="badge badge-green so-dot">Valendo</span>' : '<span class="badge badge-amber so-dot">Modo sombra</span>';
  setText('ownerPermSub', valendo
    ? `As permissões por módulo estão valendo. ${licNum(d.total)} decisão(ões) diferiram da regra antiga desde o último reinício.`
    : `Vale a regra antiga; a nova é calculada ao lado. ${d.total ? `${licNum(d.total)} divergência(s) desde o último reinício.` : 'Nenhuma divergência desde o último reinício.'}`);
  const btn = document.getElementById('btnOwnerPermMode');
  if (btn) {
    btn.dataset.alvo = valendo ? 'sombra' : 'valer';
    btn.dataset.confirmar = '';
    btn.innerHTML = valendo ? '<i data-lucide="undo-2"></i> Voltar ao modo sombra' : '<i data-lucide="shield-check"></i> Passar a valer';
  }
  const body = document.getElementById('ownerPermBody');
  if (body) {
    body.innerHTML = (d.grupos || []).length ? d.grupos.map(g => `<tr>
      <td class="settings-cell-truncate">${esc(g.tenant || '-')}</td><td>${esc(g.metodo)}</td>
      <td class="settings-cell-truncate monospace" title="${esc(g.rota)}">${esc(g.rota)}</td>
      <td>${g.mudanca === 'negava->permite' ? '<span class="badge badge-blue">passaria a permitir</span>' : '<span class="badge badge-red">passaria a negar</span>'}</td>
      <td>${licNum(g.vezes)}</td></tr>`).join('')
      : '<tr class="empty-row"><td colspan="5">Nenhuma divergência. A regra nova está decidindo igual à antiga.</td></tr>';
  }
  lucide.createIcons();
}

async function toggleOwnerPermMode() {
  const btn = document.getElementById('btnOwnerPermMode');
  if (!btn) return;
  const alvo = btn.dataset.alvo;
  if (btn.dataset.confirmar !== '1') {
    btn.dataset.confirmar = '1';
    btn.innerHTML = alvo === 'valer' ? '<i data-lucide="shield-check"></i> Confirmar: passar a valer' : '<i data-lucide="undo-2"></i> Confirmar: voltar ao sombra';
    lucide.createIcons();
    setTimeout(() => { if (btn.dataset.confirmar === '1') renderOwnerPermissions(); }, 5000);
    return;
  }
  try {
    const res = await api('/api/auth/permissions/mode', { method: 'PUT', body: JSON.stringify({ modo: alvo }) });
    await jsonOrReadableError(res, 'Não foi possível trocar o modo.');
    showToast(alvo === 'valer' ? 'Permissões por módulo valendo.' : 'De volta ao modo sombra: vale a regra antiga.');
    await renderOwnerPermissions();
  } catch (e) { showToast(e?.message || 'Não foi possível trocar o modo.', true); }
}

(function bindPermissoes() {
  const on = (id, fn) => document.getElementById(id)?.addEventListener('click', fn);
  on('btnNewAccessProfile', () => openAccessProfileEditor(''));
  on('btnSaveAccessProfile', saveAccessProfile);
  on('btnDeleteAccessProfile', deleteAccessProfile);
  on('btnCloseUserAccess', closeUserAccessModal);
  on('btnCancelUserAccess', closeUserAccessModal);
  on('btnSaveUserAccess', saveUserAccess);
  on('btnOwnerPermMode', toggleOwnerPermMode);
  document.getElementById('accessProfileCards')?.addEventListener('click', ev => {
    const b = ev.target.closest('[data-perm-edit]');
    if (b) openAccessProfileEditor(b.dataset.permEdit);
  });
  document.getElementById('userAccessBody')?.addEventListener('click', ev => {
    const b = ev.target.closest('[data-perm-user]');
    if (b) openUserAccessModal(Number(b.dataset.permUser));
  });
  document.getElementById('userAccessProfile')?.addEventListener('change', () => {
    if (!_permUsuario) return;
    const atuais = {};
    document.querySelectorAll('#userAccessMatrix [data-perm-ajuste]').forEach(s => { if (s.value !== '') atuais[s.dataset.permAjuste] = Number(s.value); });
    _permUsuario._ajustesTela = atuais;
    renderUserAccessMatrix();
  });
  document.getElementById('accessProfileBase')?.addEventListener('change', ev => {
    const v = ev.target.value;
    if (!v) return;
    const n = v === 'viewer' ? 1 : v === 'operator' ? 2 : 0;
    document.querySelectorAll('#accessProfileMatrix [data-perm-mod]').forEach(s => { s.value = String(s.dataset.permMod === 'administracao' ? Math.min(n, 1) : n); });
  });
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && !document.getElementById('modalUserAccess')?.classList.contains('hidden')) closeUserAccessModal();
  });
})();
