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
    voce ? '<span class="text-muted" style="font-size:12px">É você: desativar ou excluir a própria conta fica com outro administrador.</span>' : '',
    !voce && dono && !euDono ? '<span class="text-muted" style="font-size:12px">Só o dono da conta mexe em outro dono.</span>' : '',
  ].join('');
  document.querySelectorAll('#teamDetTabs [data-team-tab]').forEach(t => t.classList.toggle('active', t.dataset.teamTab === _eq.tab));
  renderTeamTab(u);
}

async function renderTeamTab(u) {
  const box = document.getElementById('teamDetBody');
  if (!box) return;
  if (_eq.tab === 'acesso') { box.innerHTML = eqAcessoHtml(u); lucide.createIcons(); return; }
  if (_eq.tab === 'editar') { box.innerHTML = eqEditorHtml(u); eqLigarEditor(u); lucide.createIcons(); return; }
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
  const podeAjustar = u.role !== 'owner' && Number(u.id) !== Number(_eq.me?.id);
  let nota = '';
  if (u.role === 'owner') nota = '<div class="so-note"><i data-lucide="crown"></i><span>Dono da conta: acesso total a tudo que está no plano. Não pode ser restringido.</span></div>';
  else if (!valendo && pu.profile) nota = `<div class="so-note amber"><i data-lucide="flask-conical"></i><span>Tem o perfil de acesso <strong>${esc(eqPerfilAcesso(u))}</strong> configurado, mas ele ainda está em teste. Hoje vale o perfil fixo <strong>${esc(EQ_PERFIS[u.role] || u.role)}</strong>, mostrado abaixo.</span></div>`;
  else if (!valendo) nota = `<div class="so-note"><i data-lucide="info"></i><span>Hoje vale o perfil fixo <strong>${esc(EQ_PERFIS[u.role] || u.role)}</strong> em todos os módulos.${u.role !== 'admin' ? ' Administrar (backup de pessoas, trocar IP de gravador...) exige perfil Administrador.' : ''}</span></div>`;
  const grade = modulos.map(m => {
    const n = fora(m) ? 0 : nivel(m);
    return `<div class="so-mod ${n === 0 ? 'off' : ''}"><span>${esc(m.label)}</span>${fora(m) ? '<span class="badge badge-gray">fora do plano</span>' : `<span class="badge badge-${PERM_BADGE[n] || 'gray'}">${permNivelLabel(n)}</span>`}</div>`;
  }).join('');
  const sitesU = pu.sites || [];
  const totalSites = (_perm?.sites_do_cliente || []).length;
  const linhaSites = u.role === 'owner' || !totalSites ? '' : `<div class="so-note" style="margin-top:10px"><i data-lucide="map-pin"></i><span><strong>Sites:</strong> ${sitesU.length ? `${sitesU.map(esc).join(', ')} <span class="text-muted">(${sitesU.length} de ${totalSites})</span>` : `todos (${totalSites})`}${sitesU.length && !valendo ? ' <span class="text-muted">· em teste</span>' : ''}</span></div>`;
  return `${nota}${linhaSites}<div class="so-mod-grid" style="margin-top:12px">${grade || '<p class="text-muted">Carregando módulos.</p>'}</div>
    ${podeAjustar ? `<div class="page-heading-actions" style="justify-content:flex-start;margin-top:14px"><button class="primary-action" type="button" data-team-act="editar"><i data-lucide="sliders-horizontal"></i> Ajustar acesso</button></div>` : ''}`;
}

const EQ_PERFIL_INFO = {
  viewer: 'Vê câmeras, gravadores, mapa e relatórios. Não altera nada.',
  operator: 'Tudo do visualizador e opera no dia a dia: reinicia câmera, abre porta, provisiona ONU, edita conector.',
  admin: 'Tudo do operador, as ações sensíveis (trocar IP de gravador, backup de pessoas) e gerencia usuários e configurações.',
  owner: 'Tudo do administrador. Não pode ser restringido; só um dono cria ou rebaixa outro dono.',
};

function eqEditorHtml(u) {
  const voce = Number(u.id) === Number(_eq.me?.id);
  const euDono = _eq.me?.role === 'owner';
  const dono = u.role === 'owner';
  const valendo = _perm?.modo === 'valer';
  const pu = (_perm?.usuarios || []).find(x => Number(x.id) === Number(u.id)) || {};
  const perfis = ['viewer', 'operator', 'admin', 'owner'].map(r => {
    const bloqueado = (r === 'owner' && !euDono) || (voce && !euDono) || (dono && !euDono);
    return `<label class="so-role"><input type="radio" name="eqRole" value="${r}" ${u.role === r ? 'checked' : ''} ${bloqueado ? 'disabled' : ''}>
      <strong>${EQ_PERFIS[r]}</strong><small>${EQ_PERFIL_INFO[r]}</small></label>`;
  }).join('');
  const modulos = _perm?.modulos || [];
  const acesso = dono || voce || !modulos.length ? `<p class="text-muted" style="margin:0;font-size:12.5px">${dono ? 'O dono da conta tem acesso total a tudo que está no plano.' : voce ? 'Você não pode mudar o próprio acesso.' : 'Carregando módulos.'}</p>` : `
      ${valendo ? '' : '<div class="so-note amber"><i data-lucide="flask-conical"></i><span><strong>Em teste.</strong> Você já pode montar o acesso por módulo; ele passa a valer quando a Easy ativar. Até lá vale o perfil acima.</span></div>'}
      <div class="form-row"><div class="form-group" style="margin:0"><label for="eqAccessProfile">Perfil de acesso</label>
        <select id="eqAccessProfile"><option value="">Igual ao perfil acima</option>${Object.entries(_perm?.perfis || {}).map(([k, p]) => `<option value="${esc(k)}" ${pu.profile === k ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select></div>
        <div class="form-group" style="margin:0"><label>&nbsp;</label><button class="secondary-action" type="button" data-settings-goto="profiles"><i data-lucide="key-round"></i> Criar ou editar perfis</button></div></div>
      <div class="table-wrap settings-table-wrap"><table class="data-table settings-table so-table" style="min-width:520px"><colgroup><col style="width:44%"><col style="width:22%"><col></colgroup>
        <thead><tr><th>Módulo</th><th>Do perfil</th><th>Só para esta pessoa</th></tr></thead><tbody id="eqAccessMatrix"></tbody></table></div>`;
  return `<div class="so-edit">
    <section><h3>Dados</h3>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="eqNome">Nome</label><input id="eqNome" value="${esc(u.full_name || '')}" placeholder="Nome completo"></div>
        <div class="form-group" style="margin:0"><label for="eqEmail">E-mail</label><input id="eqEmail" type="email" value="${esc(u.email || '')}" placeholder="opcional, para avisos"></div>
      </div>
      <div class="form-group" style="margin:0"><label for="eqLogin">Login para entrar</label><input id="eqLogin" value="${esc(u.username)}" autocomplete="off"><small class="text-muted">Letras, números, ponto e traço. Trocar o login não encerra as sessões abertas.</small></div>
    </section>
    <section><h3>Perfil <small>o que a pessoa pode fazer</small></h3>
      <div class="so-roles">${perfis}</div>
      ${voce && !euDono ? '<p class="text-muted" style="margin:0;font-size:12px">Só o dono da conta muda o próprio perfil.</p>' : ''}
    </section>
    ${dono || voce ? '' : `<section><h3>Sites que acessa</h3>${eqSitesHtml('eq', pu.sites || [])}</section>`}
    <section><h3>Acesso por módulo <small>o que a pessoa vê e opera</small></h3>${acesso}</section>
    ${voce ? '' : `<section><h3>Situação</h3>
      <label class="so-toggle"><input type="checkbox" id="eqAtivo" ${Number(u.active) ? 'checked' : ''} ${dono && !euDono ? 'disabled' : ''}> Usuário ativo</label>
      <p class="text-muted" style="margin:0;font-size:12px">Inativo não consegue entrar; o histórico dele continua guardado.</p></section>
    <section><h3>Nova senha <small>opcional</small></h3>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="eqSenha">Nova senha</label><input id="eqSenha" type="password" autocomplete="new-password" placeholder="deixe vazio para manter"></div>
        <div class="form-group" style="margin:0"><label for="eqSenha2">Repita</label><input id="eqSenha2" type="password" autocomplete="new-password"></div>
      </div>
      <p class="text-muted" style="margin:0;font-size:12px">Trocar a senha encerra as sessões abertas dessa pessoa.</p></section>`}
    <p id="eqEditErro" class="login-error" hidden></p>
    <div class="so-edit-foot">
      <button class="secondary-action" type="button" data-team-act="cancelar">Cancelar</button>
      <button class="primary-action" type="button" data-team-act="salvar" id="eqBtnSalvar"><i data-lucide="save"></i> Salvar alterações</button>
    </div>
  </div>`;
}

function eqMatrizAcesso(u) {
  const tb = document.getElementById('eqAccessMatrix');
  if (!tb || !_perm) return;
  const pu = (_perm.usuarios || []).find(x => Number(x.id) === Number(u.id)) || {};
  const sel = document.getElementById('eqAccessProfile')?.value || '';
  // perfil fixo escolhido agora no formulario (ainda nao salvo) define o "do perfil"
  const role = document.querySelector('input[name="eqRole"]:checked')?.value || u.role;
  const doPerfil = permNiveisDoPerfil({ ...u, role }, sel);
  const ajustes = _eq.ajustesTela || pu.overrides || {};
  const plano = _perm.modulos_no_plano;
  tb.innerHTML = (_perm.modulos || []).map(m => {
    const fora = Array.isArray(plano) && m.views.length && !m.views.some(v => plano.includes(v));
    return `<tr><td>${esc(m.label)}${fora ? ' <span class="badge badge-gray">fora do plano</span>' : ''}</td>
      <td><span class="badge badge-${PERM_BADGE[doPerfil[m.key]] || 'gray'}">${permNivelLabel(doPerfil[m.key])}</span></td>
      <td><div class="so-unit">${permSelect(ajustes[m.key] ?? '', `data-eq-ajuste="${esc(m.key)}" aria-label="Ajuste em ${esc(m.label)}"`, 'igual ao perfil')}</div></td></tr>`;
  }).join('');
}

function eqGuardarAjustes() {
  const atuais = {};
  document.querySelectorAll('#eqAccessMatrix [data-eq-ajuste]').forEach(sel => { if (sel.value !== '') atuais[sel.dataset.eqAjuste] = Number(sel.value); });
  _eq.ajustesTela = atuais;
}

function eqLigarEditor(u) {
  _eq.ajustesTela = null;
  eqMatrizAcesso(u);
  eqLigarSites('eq');
  document.getElementById('eqAccessProfile')?.addEventListener('change', () => { eqGuardarAjustes(); eqMatrizAcesso(u); });
  document.querySelectorAll('input[name="eqRole"]').forEach(r => r.addEventListener('change', () => { eqGuardarAjustes(); eqMatrizAcesso(u); }));
}

async function eqSalvarEdicao(u) {
  const err = document.getElementById('eqEditErro');
  const erro = msg => { err.textContent = msg; err.hidden = false; };
  err.hidden = true;
  const voce = Number(u.id) === Number(_eq.me?.id);
  const nome = document.getElementById('eqNome').value.trim();
  const email = document.getElementById('eqEmail').value.trim();
  const role = document.querySelector('input[name="eqRole"]:checked')?.value || u.role;
  const login = document.getElementById('eqLogin').value.trim();
  const senha = document.getElementById('eqSenha')?.value || '';
  if (!/^[A-Za-z0-9._-]{3,40}$/.test(login)) return erro('Login com 3 a 40 caracteres: letras, números, ponto, traço ou sublinhado.');
  const senha2 = document.getElementById('eqSenha2')?.value || '';
  if (senha && senha.length < 8) return erro('A senha precisa de pelo menos 8 caracteres.');
  if (senha !== senha2) return erro('As duas senhas não são iguais.');
  const btn = document.getElementById('eqBtnSalvar');
  btn.disabled = true;
  const feito = [];
  try {
    if (nome !== (u.full_name || '') || email !== (u.email || '') || role !== u.role || login !== u.username) {
      const r = await api(`/api/auth/users/${Number(u.id)}`, { method: 'POST', body: JSON.stringify({ full_name: nome, email, role, ...(login !== u.username ? { username: login } : {}) }) });
      await jsonOrReadableError(r, 'Não foi possível salvar os dados.');
      feito.push(login !== u.username ? `dados (login agora é ${login})` : 'dados');
    }
    const matriz = document.getElementById('eqAccessMatrix');
    if (matriz && role !== 'owner' && !voce) {
      const pu = (_perm?.usuarios || []).find(x => Number(x.id) === Number(u.id)) || {};
      const perfil = document.getElementById('eqAccessProfile')?.value || '';
      const overrides = {};
      matriz.querySelectorAll('[data-eq-ajuste]').forEach(sel => { if (sel.value !== '') overrides[sel.dataset.eqAjuste] = Number(sel.value); });
      const sitesLidos = eqSitesLidos('eq');
      if (sitesLidos && document.querySelector('input[name="eqModo"]:checked')?.value === 'alguns' && !sitesLidos.length) {
        btn.disabled = false;
        return erro('Marque pelo menos um site, ou escolha "Todos os sites".');
      }
      const sitesNovos = sitesLidos === null ? (pu.sites || []) : sitesLidos;
      const antes = JSON.stringify([pu.profile || '', pu.overrides || {}, pu.sites || []]);
      if (antes !== JSON.stringify([perfil, overrides, sitesNovos])) {
        const r = await api(`/api/auth/users/${Number(u.id)}/access`, { method: 'PUT', body: JSON.stringify({ profile: perfil, overrides, sites: sitesNovos }) });
        await jsonOrReadableError(r, 'Não foi possível salvar o acesso por módulo.');
        feito.push('acesso e sites');
      }
    }
    const ativoEl = document.getElementById('eqAtivo');
    if (ativoEl && !ativoEl.disabled && ativoEl.checked !== !!Number(u.active)) {
      const r = await api(`/api/auth/users/${Number(u.id)}/active`, { method: 'POST', body: JSON.stringify({ active: ativoEl.checked }) });
      await jsonOrReadableError(r, 'Não foi possível mudar a situação.');
      feito.push(ativoEl.checked ? 'ativado' : 'desativado');
    }
    if (senha) {
      const r = await api(`/api/auth/users/${Number(u.id)}/password`, { method: 'POST', body: JSON.stringify({ new_password: senha }) });
      await jsonOrReadableError(r, 'Não foi possível trocar a senha.');
      feito.push('senha');
    }
  } catch (e) {
    btn.disabled = false;
    return erro(`${e?.message || 'Não foi possível salvar.'}${feito.length ? ` (já salvo: ${feito.join(', ')})` : ''}`);
  }
  btn.disabled = false;
  showToast(feito.length ? `${u.username}: ${feito.join(', ')} salvo.` : 'Nada mudou.');
  _eq.tab = 'acesso';
  if (typeof loadAccessProfiles === 'function') await loadAccessProfiles(_currentUser);
  await loadTeam(_eq.me);
}

function eqSitesHtml(prefixo, escolhidos) {
  const sites = _perm?.sites_do_cliente || [];
  if (!sites.length) return '<p class="text-muted" style="margin:0;font-size:12.5px">Este cliente ainda não tem sites cadastrados: a pessoa vê tudo.</p>';
  const todos = !escolhidos || !escolhidos.length;
  const marcados = new Set((escolhidos || []).map(x => String(x).toUpperCase()));
  return `<div class="so-escolha">
      <label><input type="radio" name="${prefixo}Modo" value="todos" ${todos ? 'checked' : ''}> Todos os sites${sites.length > 1 ? ` (${sites.length})` : ''}</label>
      <label><input type="radio" name="${prefixo}Modo" value="alguns" ${todos ? '' : 'checked'}> Só os sites marcados</label></div>
    <div class="so-sites" id="${prefixo}Lista" ${todos ? 'hidden' : ''}>${sites.map(st => `<label><input type="checkbox" data-site="${esc(st.name)}" ${marcados.has(st.name.toUpperCase()) ? 'checked' : ''}> ${esc(st.name)}<small>${licNum(st.equipamentos)} equip.</small></label>`).join('')}</div>
    ${_perm?.modo === 'valer' ? '' : '<p class="text-muted" style="margin:6px 0 0;font-size:12px">Em teste: a limitação por site passa a valer junto com os perfis de acesso.</p>'}`;
}

function eqLigarSites(prefixo) {
  document.querySelectorAll(`input[name="${prefixo}Modo"]`).forEach(r => r.addEventListener('change', () => {
    const lista = document.getElementById(`${prefixo}Lista`);
    if (lista) lista.hidden = document.querySelector(`input[name="${prefixo}Modo"]:checked`)?.value !== 'alguns';
  }));
}

// null = nao ha sites para escolher; [] = todos; [...] = so esses
function eqSitesLidos(prefixo) {
  const modo = document.querySelector(`input[name="${prefixo}Modo"]:checked`)?.value;
  if (!modo) return null;
  if (modo === 'todos') return [];
  return [...document.querySelectorAll(`#${prefixo}Lista [data-site]:checked`)].map(c => c.dataset.site);
}

function eqLoginDoNome(nome) {
  const partes = String(nome || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase()
    .replace(/[^a-z0-9 ]+/g, ' ').trim().split(/\s+/).filter(p => p && !['da', 'de', 'do', 'das', 'dos', 'e'].includes(p));
  return partes.slice(0, 2).join('.');
}

function eqGerarSenha() {
  const letras = 'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789';
  const a = new Uint32Array(12);
  crypto.getRandomValues(a);
  return Array.from(a, n => letras[n % letras.length]).join('');
}

function eqAbrirNovo() {
  const f = document.getElementById('teamNewUserForm');
  if (!f.hidden) { f.hidden = true; return; }
  const euDono = _eq.me?.role === 'owner';
  document.getElementById('nuPerfis').innerHTML = ['viewer', 'operator', 'admin', 'owner'].map(r =>
    `<label class="so-role"><input type="radio" name="nuRole" value="${r}" ${r === 'viewer' ? 'checked' : ''} ${r === 'owner' && !euDono ? 'disabled' : ''}>
      <strong>${EQ_PERFIS[r]}</strong><small>${EQ_PERFIL_INFO[r]}</small></label>`).join('');
  document.getElementById('nuSites').innerHTML = eqSitesHtml('nu', []);
  eqLigarSites('nu');
  ['nuNome', 'nuEmail', 'nuLogin', 'nuSenha'].forEach(id => { document.getElementById(id).value = ''; });
  document.getElementById('nuLogin').dataset.manual = '';
  document.getElementById('nuSenha').type = 'password';
  document.getElementById('nuErro').hidden = true;
  f.hidden = false;
  document.getElementById('nuNome').focus();
  lucide.createIcons();
}

async function eqCriarUsuario() {
  const err = document.getElementById('nuErro');
  const erro = msg => { err.textContent = msg; err.hidden = false; };
  err.hidden = true;
  const nome = document.getElementById('nuNome').value.trim();
  const email = document.getElementById('nuEmail').value.trim();
  const login = document.getElementById('nuLogin').value.trim();
  const senha = document.getElementById('nuSenha').value;
  const role = document.querySelector('input[name="nuRole"]:checked')?.value || 'viewer';
  const sites = eqSitesLidos('nu');
  if (!nome) return erro('Informe o nome da pessoa.');
  if (!/^[A-Za-z0-9._-]{3,40}$/.test(login)) return erro('Login com 3 a 40 caracteres: letras, números, ponto, traço ou sublinhado.');
  if (senha.length < 8) return erro('A senha precisa de pelo menos 8 caracteres. Use "Gerar" se preferir.');
  if (sites && role !== 'owner' && document.querySelector('input[name="nuModo"]:checked')?.value === 'alguns' && !sites.length) return erro('Marque pelo menos um site, ou escolha "Todos os sites".');
  const btn = document.getElementById('btnTeamCreate');
  btn.disabled = true;
  try {
    const r = await api('/api/auth/users', { method: 'POST', body: JSON.stringify({ username: login, password: senha, role, full_name: nome, email }) });
    const d = await jsonOrReadableError(r, 'Não foi possível criar o usuário.');
    if (sites && sites.length && role !== 'owner' && d?.user?.id) {
      const r2 = await api(`/api/auth/users/${Number(d.user.id)}/access`, { method: 'PUT', body: JSON.stringify({ profile: '', overrides: {}, sites }) });
      await jsonOrReadableError(r2, 'Usuário criado, mas não foi possível gravar os sites.');
    }
    showToast(`${nome} criado. Login: ${login}`);
    document.getElementById('teamNewUserForm').hidden = true;
    _eq.sel = d?.user?.id || _eq.sel;
    if (typeof loadAccessProfiles === 'function') await loadAccessProfiles(_currentUser);
    await loadTeam(_eq.me);
  } catch (e) {
    erro(e?.message || 'Não foi possível criar o usuário.');
  } finally {
    btn.disabled = false;
  }
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
  if (acao === 'editar') { _eq.tab = 'editar'; return renderTeamDetail(); }
  if (acao === 'salvar') return eqSalvarEdicao(u);
  if (acao === 'cancelar') { _eq.tab = 'acesso'; return renderTeamDetail(); }
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
  on('btnTeamNewUser', 'click', eqAbrirNovo);
  on('btnTeamCreate', 'click', eqCriarUsuario);
  on('nuNome', 'input', () => {
    const l = document.getElementById('nuLogin');
    if (!l.dataset.manual) l.value = eqLoginDoNome(document.getElementById('nuNome').value);
  });
  on('nuLogin', 'input', () => { document.getElementById('nuLogin').dataset.manual = '1'; });
  on('nuGerar', 'click', () => {
    const i = document.getElementById('nuSenha');
    i.value = eqGerarSenha();
    i.type = 'text';
  });
  on('nuMostrar', 'click', () => {
    const i = document.getElementById('nuSenha');
    i.type = i.type === 'password' ? 'text' : 'password';
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
