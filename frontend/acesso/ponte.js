// Ponte do Controle de Acesso dentro do /v3 (22/10/2026). O Painel nasceu numa
// pagina propria (/acesso/, com shell.js); agora roda dentro do SightOps, no
// menu Controle de Acesso. Estas funcoes sao o que o shell.js dava a ele, em
// cima do que o /v3 ja tem (api, showToast, _currentUser).
//
// acJson e diferente do apiJson do /v3 de proposito: sem cache (ao vivo,
// relatorio e conversa precisam do dado de agora) e com erro que aparece.

const AC_RAIZ = './';
const AC_AGENTE = 'http://127.0.0.1:47600';

async function acJson(path) {
  const res = await api(path);
  if (!res) return null;
  if (!res.ok) throw new Error('HTTP ' + res.status);
  return res.json();
}

// Escrita: devolve o JSON ou lanca com a mensagem do backend ("detail").
async function acEnviar(method, path, body) {
  const res = await api(path, { method, body: body ? JSON.stringify(body) : undefined });
  if (!res) throw new Error('Sessão expirada.');
  let data = null;
  try { data = await res.json(); } catch (_) { data = null; }
  if (!res.ok) {
    const d = data && data.detail;
    const msg = typeof d === 'string' ? d : Array.isArray(d) ? d.map(x => x.msg || '').join('; ') : '';
    throw new Error(res.status === 403 ? 'Seu perfil não pode fazer isso.' : (msg || 'HTTP ' + res.status));
  }
  return data;
}

function acToast(msg, erro) { showToast(msg, !!erro); }

// Usuario logado do /v3 (Conexoes usa para saber se e administrador).
Object.defineProperty(window, 'acUsuario', {
  get() { return typeof _currentUser !== 'undefined' ? _currentUser : null; },
  configurable: true,
});

// Pagina web de uma controladora: pelo SightOps Agent no PC (127.0.0.1:47600),
// que abre tunel ate o IP virtual do conector; sem o agente, proxy do servidor.
async function acAbrirWeb(ip, porta) {
  ip = String(ip || '').trim();
  if (!ip) return;
  const proxyUrl = `${API_BASE}/api/maintenance/web/${encodeURIComponent(ip)}/`;
  let win = null;   // abre ainda no clique: depois dos awaits viraria pop-up bloqueado
  try {
    win = window.open('', '_blank');
    if (win) {
      win.opener = null;
      win.document.title = `Abrindo ${ip}…`;
      win.document.body.innerHTML = `<p style="font:14px sans-serif;padding:24px">Abrindo <b>${esc(ip)}</b> pela rede do cliente…</p>`;
    }
  } catch (_) { win = null; }
  const ir = url => { if (win && !win.closed) win.location.href = url; else window.open(url, '_blank', 'noopener'); };
  acToast(`Abrindo ${ip} pela rede do cliente…`);
  let saude = null, aberto = null, erro = '';
  try {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(`${AC_AGENTE}/health`, { signal: ctrl.signal });
    clearTimeout(t);
    saude = r.ok ? await r.json() : null;
  } catch (e) { erro = 'agente: ' + ((e && e.message) || e); }
  if (saude && saude.ok) {
    try {
      const tr = await acJson('/api/auth/agent-token').catch(() => null);
      const token = (tr && tr.token) || '';
      const wsbase = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host;
      const q = `wsbase=${encodeURIComponent(wsbase)}&ip=${encodeURIComponent(ip)}&port=${encodeURIComponent(porta || 80)}&token=${encodeURIComponent(token)}`;
      const res = await fetch(`${AC_AGENTE}/open?${q}`);
      aberto = await res.json();
      if (aberto && aberto.ok && aberto.url) { ir(aberto.url); return; }
      erro = 'agente: ' + ((aberto && aberto.error) || 'sem url');
    } catch (e) { erro = 'agente: ' + ((e && e.message) || e); }
    acToast(`O agente não abriu ${ip} (${erro}). Abrindo pelo acesso web do servidor.`, true);
  } else {
    acToast('SightOps Agent não está rodando neste computador. Abrindo pelo acesso web do servidor.', true);
  }
  console.warn('[SightOps Agent]', JSON.stringify(saude), JSON.stringify(aberto), erro, '-> proxy');
  ir(proxyUrl);
}
