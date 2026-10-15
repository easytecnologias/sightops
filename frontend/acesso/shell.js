// Paginas novas do Controle de Acesso em /v3/acesso/ (Painel, Dispositivos...):
// paginas proprias, para testar sem mexer no SightOps em /v3/. Mesmo login
// (cookie de sessao), mesma API, mesmo visual: usam o styles.css do sistema e
// o menu lateral dele. Itens do menu com data-view voltam para /v3/?tela=...;
// itens com data-pagina abrem as paginas novas daqui.
// Cada pagina define window.acPagina = { id, iniciar } antes deste arquivo rodar.

// Raiz do SightOps (/v3/), funcione a pagina em /v3/acesso/ ou /v3/acesso/x/.
const AC_RAIZ = (() => {
  const p = window.location.pathname;
  const i = p.lastIndexOf('/acesso/');
  return i >= 0 ? p.slice(0, i + 1) : '../';
})();
const AC_PAGINAS = { painel: 'acesso/#vivo', dispositivos: 'acesso/#dispositivos' };

function esc(str) {
  return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function apiJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'same-origin' });
  if (res.status === 401) { window.location.href = AC_RAIZ; return null; }
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

// Escrita (POST/DELETE) nas rotas que ja existem. Devolve o JSON ou lanca com a
// mensagem do backend ("detail"), para a tela mostrar o motivo de verdade.
async function acEnviar(method, path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method, credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) { window.location.href = AC_RAIZ; throw new Error('Sessão expirada.'); }
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg || '').join('; ') : '';
    throw new Error(res.status === 403 ? 'Seu perfil não pode fazer isso.' : (msg || 'HTTP ' + res.status));
  }
  return data;
}

// Aviso rapido no canto (mesma ideia do showToast do /v3).
function acToast(msg, erro) {
  let box = document.getElementById('acToasts');
  if (!box) {
    box = document.createElement('div');
    box.id = 'acToasts';
    box.className = 'ac-toasts';
    document.body.appendChild(box);
  }
  const t = document.createElement('div');
  t.className = 'ac-toast' + (erro ? ' erro' : '');
  t.setAttribute('role', erro ? 'alert' : 'status');
  t.textContent = msg;
  box.appendChild(t);
  setTimeout(() => t.classList.add('sai'), erro ? 6000 : 3500);
  setTimeout(() => t.remove(), erro ? 6600 : 4100);
}

// Mesma regra do menu do /v3 (core.js applyModuleVisibility).
const AC_DESLIGADAS = new Set(['access-whatsapp-triage', 'ia-nvr']);
const AC_SO_EQUIPE = new Set(['script-zabbix', 'script-grafana']);
let acUsuario = null;

function acMenu(user) {
  const enabled = user && user.enabled_modules;
  const restrito = Array.isArray(enabled);
  document.querySelectorAll('#sidebar .nav-item[data-view]').forEach(btn => {
    const key = btn.dataset.view;
    const addon = restrito && (key === 'access-live' || key === 'access-painel') && enabled.includes('access-control');
    const visivel = !AC_DESLIGADAS.has(key) && !(AC_SO_EQUIPE.has(key) && !(user && user.is_platform_admin))
      && (!restrito || enabled.includes(key) || addon);
    btn.classList.toggle('nav-item-hidden', !visivel);
  });
  // Paginas novas aparecem para quem tem o Controle de Acesso.
  const temAcesso = !restrito || enabled.includes('access-control');
  document.querySelectorAll('#sidebar .nav-item[data-pagina]').forEach(btn => btn.classList.toggle('nav-item-hidden', !temAcesso));
  const snap = document.getElementById('ngSnapshots');
  if (snap) snap.classList.toggle('nav-item-hidden', ![...snap.querySelectorAll('.nav-sub-item[data-view]')].some(b => !b.classList.contains('nav-item-hidden')));
}

function acLigarShell() {
  const pagina = (window.acPagina && window.acPagina.id) || 'painel';
  document.querySelectorAll('#sidebar .nav-item').forEach(btn => btn.classList.remove('active'));
  document.querySelectorAll('#sidebar .nav-item[data-view]').forEach(btn => {
    // "Painel de Acesso" do menu do /v3 vira a pagina nova daqui.
    if (btn.dataset.view === 'access-painel') {
      btn.dataset.pagina = 'painel';
      delete btn.dataset.view;
      return;
    }
    btn.addEventListener('click', () => { window.location.href = AC_RAIZ + '?tela=' + encodeURIComponent(btn.dataset.view); });
  });
  document.querySelectorAll('#sidebar .nav-item[data-pagina]').forEach(btn => {
    const aqui = btn.dataset.pagina === pagina;
    btn.classList.toggle('active', aqui);
    // Mesmo documento com outra aba (#...) so troca a aba, sem recarregar.
    btn.addEventListener('click', () => { window.location.href = AC_RAIZ + AC_PAGINAS[btn.dataset.pagina]; });
  });
  document.querySelectorAll('#sidebar .nav-group-toggle').forEach(btn => btn.addEventListener('click', () => {
    const g = btn.closest('.nav-group');
    const abrindo = !g.classList.contains('open');
    document.querySelectorAll('#sidebar .nav-group.open').forEach(x => { if (x !== g) x.classList.remove('open'); });
    g.classList.toggle('open', abrindo);
  }));
  const fecha = () => { document.getElementById('sidebar').classList.remove('open'); document.getElementById('mobileBackdrop').classList.remove('open'); };
  document.getElementById('menuBtn')?.addEventListener('click', () => {
    document.getElementById('sidebar').classList.add('open'); document.getElementById('mobileBackdrop').classList.add('open');
  });
  document.getElementById('mobileBackdrop')?.addEventListener('click', fecha);
  const sair = () => {
    fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', credentials: 'same-origin' }).catch(() => {}).finally(() => { window.location.href = AC_RAIZ; });
  };
  document.getElementById('logoutBtn')?.addEventListener('click', sair);
  document.getElementById('logoutBtnTop')?.addEventListener('click', sair);
  document.getElementById('profileMenu')?.addEventListener('click', () => document.getElementById('profileDropdown')?.classList.toggle('open'));
  document.querySelectorAll('[data-ac-raiz]').forEach(a => { a.href = AC_RAIZ + a.dataset.acRaiz; });
}

async function acIniciar() {
  acLigarShell();
  if (window.lucide) lucide.createIcons();
  const me = await apiJson('/api/auth/me');
  if (!me) return;
  const user = me.user || me;
  acUsuario = user;
  const nome = user.full_name || user.username || user.email || '?';
  const pn = document.getElementById('profileName'); if (pn) pn.textContent = nome;
  const pr = document.getElementById('profileRole'); if (pr) pr.textContent = user.role || user.perfil || '';
  const pa = document.getElementById('profileAvatar'); if (pa) pa.textContent = nome[0].toUpperCase();
  acMenu(user);
  document.getElementById('appShell').removeAttribute('hidden');
  if (window.acPagina && typeof window.acPagina.iniciar === 'function') await window.acPagina.iniciar();
  if (window.lucide) lucide.createIcons();
}

document.addEventListener('DOMContentLoaded', () => {
  acIniciar().catch(err => {
    document.body.insertAdjacentHTML('beforeend', `<p style="padding:24px">Não consegui abrir a página: ${esc(err && err.message || err)}. <a href="${AC_RAIZ}">Voltar ao SightOps</a></p>`);
  });
});
