// Configuracoes > Usuarios e acessos: lista da equipe e detalhe de cada usuario
// (o que pode usar, sessoes abertas, atividade), com editar, redefinir senha,
// encerrar sessoes, ativar/desativar e excluir.
// Backend: /api/auth/users/overview, /users/{id}/detail, /users/{id}/sessions/revoke,
// /users/{id}/password. Perfis de acesso vem de permissoes.js (_perm).

const EQ_PERFIS = { owner: 'Dono da conta', admin: 'Administrador', operator: 'Operador', viewer: 'Visualizador' };
const EQ_PERFIL_COR = { owner: 'amber', admin: 'blue', operator: 'green', viewer: 'gray' };
const EQ_SESSAO = { web: 'Navegador', 'agent-web': 'SightOps Agent' };
const EQ_CORES_AVATAR = ['var(--primary)', 'var(--blue)', 'var(--cyan)', 'var(--amber)', '#7048e8', '#c2255c'];

let _eq = { users: [], sel: null, tab: 'acesso', filtro: 'todos', admin: false, plan: null, me: null };

function eqIniciais(u) {
  const base = String(u.full_name || u.username || '?').trim();
  const p = base.split(/\s+/).filter(Boolean);
  return (p.length > 1 ? p[0][0] + p[1][0] : base.slice(0, 2)).toUpperCase();
}

function eqCor(u) {
  return EQ_CORES_AVATAR[Number(u.id || 0) % EQ_CORES_AVATAR.length];
}

function eqDias(iso) {
  const t = Date.parse(String(iso || '').replace(' ', 'T'));
  return t ? (Date.now() - t) / 86400000 : Infinity;
}

function eqPerfilAcesso(u) {
  const pu = (_perm?.usuarios || []).find(x => Number(x.id) === Number(u.id));
  if (!pu?.profile) return '';
  return (_perm?.perfis || {})[pu.profile]?.name || pu.profile;
}

async function loadTeam(currentUser) {
  _eq.me = currentUser;
  _eq.admin = ['owner', 'admin'].includes(String(currentUser?.role || '').toLowerCase());
  const btn = document.getElementById('btnTeamNewUser');
  if (btn) btn.hidden = !_eq.admin;
  if (!_eq.admin) {
    setText('teamSummary', 'Somente administradores veem e gerenciam a equipe.');
    document.getElementById('teamBody').innerHTML = '<tr class="empty-row"><td colspan="6">Peça a um administrador do cliente para mudar usuários.</td></tr>';
    document.getElementById('teamFilters').innerHTML = '';
    document.getElementById('teamDetail').hidden = true;
    return;
  }
  const [data, plan] = await Promise.all([
    apiJson('/api/auth/users/overview', { forceRefresh: true }),
    apiJson('/api/auth/my-plan'),
  ]);
  _eq.users = data?.users || [];
  _eq.plan = plan;
  if (_eq.sel && !_eq.users.some(u => Number(u.id) === Number(_eq.sel))) _eq.sel = null;
  if (!_eq.sel) _eq.sel = (_eq.users.find(u => Number(u.id) !== Number(currentUser.id)) || _eq.users[0] || {}).id || null;
  renderTeam();
}

function renderTeam() {
  const us = _eq.users;
  const ativos = us.filter(u => Number(u.active));
  const lim = _eq.plan?.user_limit;
  setText('teamSummary', `${us.length} usuário${us.length === 1 ? '' : 's'}${lim !== null && lim !== undefined ? ` de ${lim} do plano` : ''} · ${ativos.length} ativo${ativos.length === 1 ? '' : 's'}`);
  const filtros = [
    ['todos', 'Todos', us.length],
    ['ativos', 'Ativos', ativos.length],
    ['inativos', 'Inativos', us.length - ativos.length],
    ['admins', 'Administram', us.filter(u => ['owner', 'admin'].includes(u.role)).length],
    ['nunca', 'Nunca entraram', us.filter(u => Number(u.active) && !u.last_seen).length],
    ['parados', 'Sem acesso há 30+ dias', us.filter(u => Number(u.active) && u.last_seen && eqDias(u.last_seen) > 30).length],
  ];
  document.getElementById('teamFilters').innerHTML = filtros.map(([k, l, n]) =>
    `<button type="button" class="so-chip ${_eq.filtro === k ? 'active' : ''}" data-team-filter="${k}">${l} ${n}</button>`).join('');
  const lista = us.filter(u => ({
    todos: true, ativos: Number(u.active), inativos: !Number(u.active),
    admins: ['owner', 'admin'].includes(u.role),
    nunca: Number(u.active) && !u.last_seen,
    parados: Number(u.active) && u.last_seen && eqDias(u.last_seen) > 30,
  })[_eq.filtro]);
  document.getElementById('teamBody').innerHTML = lista.length ? lista.map(u => {
    const acesso = eqPerfilAcesso(u);
    const sel = Number(u.id) === Number(_eq.sel);
    const voce = Number(u.id) === Number(_eq.me?.id);
    return `<tr class="so-click ${sel ? 'row-selected' : ''}" data-team-user="${Number(u.id)}">
      <td><div class="so-user"><span class="avatar" style="background:${eqCor(u)}">${esc(eqIniciais(u))}</span><div style="min-width:0"><strong>${esc(u.full_name || u.username)}${voce ? ' <span class="text-muted">(você)</span>' : ''}</strong><small>${esc(u.username)}${u.email ? ` · ${esc(u.email)}` : ''}</small></div></div></td>
      <td><span class="badge badge-${EQ_PERFIL_COR[u.role] || 'gray'}">${esc(EQ_PERFIS[u.role] || u.role)}</span></td>
      <td class="settings-cell-truncate">${acesso ? esc(acesso) : '<span class="text-muted">padrão do perfil</span>'}</td>
      <td>${Number(u.active) ? '<span class="badge badge-green so-dot">Ativo</span>' : '<span class="badge badge-red so-dot">Inativo</span>'}</td>
      <td class="text-muted">${u.last_seen ? esc(cfgMinutos(u.last_seen)) : 'nunca entrou'}</td>
      <td>${u.active_sessions ? `${licNum(u.active_sessions)} aberta${u.active_sessions === 1 ? '' : 's'}` : '<span class="text-muted">nenhuma</span>'}</td></tr>`;
  }).join('') : '<tr class="empty-row"><td colspan="6">Nenhum usuário neste filtro.</td></tr>';
  renderTeamDetail();
  lucide.createIcons();
}

function renderTeamDetail() {
  const box = document.getElementById('teamDetail');
  const u = _eq.users.find(x => Number(x.id) === Number(_eq.sel));
  if (!box) return;
  box.hidden = !u;
  if (!u) return;
  box.classList.add('active');
  const voce = Number(u.id) === Number(_eq.me?.id);
  const dono = u.role === 'owner';
  const euDono = _eq.me?.role === 'owner';
  const podeMexer = !voce && (!dono || euDono);
  const av = document.getElementById('teamDetAvatar');
  av.textContent = eqIniciais(u);
  av.style.background = eqCor(u);
  setText('teamDetName', u.full_name || u.username);
  setText('teamDetSub', `${u.username}${u.email ? ` · ${u.email}` : ''} · ${EQ_PERFIS[u.role] || u.role} · ${u.last_seen ? `último acesso ${cfgMinutos(u.last_seen)}` : 'nunca entrou'}`);
  const b = (txt, icone, acao, perigo) => `<button class="secondary-action" type="button" data-team-act="${acao}" ${perigo ? 'style="color:var(--danger)"' : ''}><i data-lucide="${icone}"></i> ${txt}</button>`;
  document.getElementById('teamDetActions').innerHTML = [
    b('Editar', 'pencil', 'editar'),
    podeMexer ? b('Redefinir senha', 'key-round', 'senha') : '',
    podeMexer && u.active_sessions ? b('Encerrar sessões', 'log-out', 'sessoes') : '',
    podeMexer ? (Number(u.active) ? b('Desativar', 'user-x', 'desativar') : b('Ativar', 'user-check', 'ativar')) : '',
    podeMexer ? b('Excluir', 'trash-2', 'excluir', true) : '',
  ].join('');
  document.querySelectorAll('#teamDetTabs [data-team-tab]').forEach(t => t.classList.toggle('active', t.dataset.teamTab === _eq.tab));
  renderTeamTab(u);
}

async function renderTeamTab(u) {
  const box = document.getElementById('teamDetBody');
  if (!box) return;
  if (_eq.tab === 'acesso') { box.innerHTML = eqAcessoHtml(u); lucide.createIcons(); return; }
  box.innerHTML = '<p class="text-muted" style="margin:0">Carregando.</p>';
  const d = await apiJson(`/api/auth/users/${Number(u.id)}/detail`, { forceRefresh: true });
  if (Number(_eq.sel) !== Number(u.id)) return; // trocou de usuario enquanto carregava
  if (!d) { box.innerHTML = '<p class="text-muted" style="margin:0">Não foi possível carregar.</p>'; return; }
  if (_eq.tab === 'sessoes') {
    const ss = d.sessions || [];
    box.innerHTML = ss.length ? `<div class="table-wrap settings-table-wrap"><table class="data-table settings-table" style="min-width:560px">
      <thead><tr><th>Onde</th><th>Entrou</th><th>Último uso</th><th>Expira</th></tr></thead><tbody>
      ${ss.map(s => `<tr><td>${esc(EQ_SESSAO[s.label] || s.label || 'Navegador')}</td><td class="text-muted">${esc(cfgQuando(s.created_at))}</td><td>${esc(s.last_seen_at ? cfgMinutos(s.last_seen_at) : '—')}</td><td class="text-muted">${esc(cfgQuando(s.expires_at))}</td></tr>`).join('')}
      </tbody></table></div>` : '<p class="text-muted" style="margin:0">Nenhuma sessão aberta agora.</p>';
  } else {
    const ev = d.events || [];
    box.innerHTML = ev.length ? `<div class="so-feed" style="padding:0">${ev.map(e => `<div><span class="avatar" style="background:${eqCor(u)}">${esc(eqIniciais(u))}</span>
      <span>${esc(AUDIT_ACOES[e.action] || e.action)}${e.resource_id && !String(e.action).startsWith('auth.log') ? ` <span class="text-muted">${esc(e.resource_id)}</span>` : ''}</span>
      <time>${esc(cfgQuando(e.created_at))}</time></div>`).join('')}</div>` : '<p class="text-muted" style="margin:0">Nenhuma atividade registrada.</p>';
  }
  lucide.createIcons();
}

function eqAcessoHtml(u) {
  const modulos = _perm?.modulos || [];
  const plano = _perm?.modulos_no_plano;
  const fora = m => Array.isArray(plano) && m.views.length && !m.views.some(v => plano.includes(v));
  const valendo = _perm?.modo === 'valer';
  const pu = (_perm?.usuarios || []).find(x => Number(x.id) === Number(u.id)) || {};
  const nivelFixo = { owner: 3, admin: 3, operator: 2, viewer: 1 }[u.role] ?? 0;
  // Mostra o que vale DE VERDADE: em sombra, o perfil fixo; valendo, o perfil de acesso.
  const nivel = m => (valendo && pu.niveis ? Number(pu.niveis[m.key] ?? 0) : nivelFixo);
  const podeAjustar = (valendo || !!_currentUser?.is_platform_admin) && u.role !== 'owner' && Number(u.id) !== Number(_eq.me?.id) && typeof openUserAccessModal === 'function';
  let nota = '';
  if (u.role === 'owner') nota = '<div class="so-note"><i data-lucide="crown"></i><span>Dono da conta: acesso total a tudo que está no plano. Não pode ser restringido.</span></div>';
  else if (!valendo && pu.profile) nota = `<div class="so-note amber"><i data-lucide="flask-conical"></i><span>Tem o perfil de acesso <strong>${esc(eqPerfilAcesso(u))}</strong> configurado, mas ele ainda está em teste. Hoje vale o perfil fixo <strong>${esc(EQ_PERFIS[u.role] || u.role)}</strong>, mostrado abaixo.</span></div>`;
  else if (!valendo) nota = `<div class="so-note"><i data-lucide="info"></i><span>Hoje vale o perfil fixo <strong>${esc(EQ_PERFIS[u.role] || u.role)}</strong> em todos os módulos.${u.role !== 'admin' ? ' Administrar (backup de pessoas, trocar IP de gravador...) exige perfil Administrador.' : ''}</span></div>`;
  const grade = modulos.map(m => {
    const n = fora(m) ? 0 : nivel(m);
    return `<div class="so-mod ${n === 0 ? 'off' : ''}"><span>${esc(m.label)}</span>${fora(m) ? '<span class="badge badge-gray">fora do plano</span>' : `<span class="badge badge-${PERM_BADGE[n] || 'gray'}">${permNivelLabel(n)}</span>`}</div>`;
  }).join('');
  return `${nota}<div class="so-mod-grid" style="margin-top:12px">${grade || '<p class="text-muted">Carregando módulos.</p>'}</div>
    ${podeAjustar ? `<div class="page-heading-actions" style="justify-content:flex-start;margin-top:14px"><button class="primary-action" type="button" data-team-act="acesso"><i data-lucide="sliders-horizontal"></i> Ajustar acesso</button></div>` : ''}`;
}

function eqAbrirSenha(u) {
  _eq.senhaAlvo = u;
  setText('userPassSub', u.full_name ? `${u.full_name} (${u.username})` : u.username);
  ['userPassNew', 'userPassConfirm'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('userPassErro').hidden = true;
  document.getElementById('modalUserPassword').classList.remove('hidden');
  document.getElementById('userPassNew').focus();
  lucide.createIcons();
}

function eqFecharSenha() {
  _eq.senhaAlvo = null;
  document.getElementById('modalUserPassword')?.classList.add('hidden');
}

async function eqSalvarSenha() {
  const u = _eq.senhaAlvo;
  if (!u) return;
  const a = document.getElementById('userPassNew').value;
  const b = document.getElementById('userPassConfirm').value;
  const err = document.getElementById('userPassErro');
  const erro = msg => { err.textContent = msg; err.hidden = false; };
  if (a.length < 8) return erro('A senha precisa de pelo menos 8 caracteres.');
  if (a !== b) return erro('As duas senhas não são iguais.');
  try {
    const res = await api(`/api/auth/users/${Number(u.id)}/password`, { method: 'POST', body: JSON.stringify({ new_password: a }) });
    await jsonOrReadableError(res, 'Não foi possível redefinir a senha.');
    showToast(`Senha de ${u.username} redefinida. As sessões abertas foram encerradas.`);
    eqFecharSenha();
    await loadTeam(_eq.me);
  } catch (e) { erro(e?.message || 'Não foi possível redefinir a senha.'); }
}

async function eqAcao(acao) {
  const u = _eq.users.find(x => Number(x.id) === Number(_eq.sel));
  if (!u) return;
  if (acao === 'editar') return openEditUserModal(u.id);
  if (acao === 'senha') return eqAbrirSenha(u);
  if (acao === 'ativar' || acao === 'desativar') return toggleUserActive(u.id, acao === 'ativar');
  if (acao === 'excluir') return deleteUserRow(u.id, u.username);
  if (acao === 'acesso') return openUserAccessModal(u.id);
  if (acao === 'sessoes') {
    const ok = await showConfirm({ eyebrow: 'Usuários', title: `Encerrar as sessões de ${u.username}?`,
      msg: `${u.active_sessions} sessão(ões) aberta(s). Ele precisa entrar de novo em todos os aparelhos.`, label: 'Encerrar', danger: true });
    if (!ok) return;
    try {
      const res = await api(`/api/auth/users/${Number(u.id)}/sessions/revoke`, { method: 'POST' });
      const d = await jsonOrReadableError(res, 'Não foi possível encerrar as sessões.');
      showToast(`${d.revoked} sessão(ões) encerrada(s).`);
      await loadTeam(_eq.me);
    } catch (e) { showToast(e?.message || 'Não foi possível encerrar as sessões.', true); }
  }
}

(function bindEquipe() {
  const on = (id, ev, fn) => document.getElementById(id)?.addEventListener(ev, fn);
  on('btnTeamNewUser', 'click', () => {
    const f = document.getElementById('teamNewUserForm');
    f.hidden = !f.hidden;
    if (!f.hidden) document.getElementById('newUserFullName')?.focus();
  });
  on('btnTeamNewUserCancel', 'click', () => { document.getElementById('teamNewUserForm').hidden = true; });
  on('teamFilters', 'click', ev => {
    const b = ev.target.closest('[data-team-filter]');
    if (b) { _eq.filtro = b.dataset.teamFilter; renderTeam(); }
  });
  on('teamBody', 'click', ev => {
    const r = ev.target.closest('[data-team-user]');
    if (r) { _eq.sel = Number(r.dataset.teamUser); renderTeam(); }
  });
  on('teamDetTabs', 'click', ev => {
    const t = ev.target.closest('[data-team-tab]');
    if (t) { _eq.tab = t.dataset.teamTab; renderTeamDetail(); }
  });
  on('teamDetail', 'click', ev => {
    const a = ev.target.closest('[data-team-act]');
    if (a) eqAcao(a.dataset.teamAct);
  });
  on('btnCloseUserPass', 'click', eqFecharSenha);
  on('btnCancelUserPass', 'click', eqFecharSenha);
  on('btnSaveUserPass', 'click', eqSalvarSenha);
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && !document.getElementById('modalUserPassword')?.classList.contains('hidden')) eqFecharSenha();
  });
})();
