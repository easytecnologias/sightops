/* SightOps Rua — aplicativo do tecnico de campo.
 *
 * Por que nao e o app web embrulhado: o frontend do SightOps tem 29 mil linhas
 * de JS e um index de 6.800 linhas, feito para desktop com barra lateral de
 * 226px. Dentro de um APK isso fica lento para abrir e cheio de tela que
 * ninguem usa no poste. Aqui e um cliente pequeno da MESMA API.
 *
 * A divisao que organiza o app inteiro:
 *
 *   CONSULTA   funciona sem sinal. Baixa quando ha rede, le no poste.
 *              (dashboard, inventario do site, projeto)
 *   COMANDO    exige sinal AGORA. Sao ordens a equipamento vivo pelo tunel do
 *              conector -- nao podem entrar em fila, e a tela diz isso.
 *              (ativar ONU, ativar camera, mexer em gravador)
 *
 * O celular nunca fala com a camera: fala com o servidor, que fala pelo
 * conector. Por isso nao ha descoberta de rede local aqui.
 */

const API = '';                       // mesma origem enquanto servido em /v3/rua/
const CHAVE_TOKEN = 'rua_token';
const CHAVE_SITE = 'rua_site';
const CACHE_PREFIXO = 'rua_cache:';
const CACHE_VALIDADE_MS = 24 * 60 * 60 * 1000;   // um dia de trabalho

let _token = null;
let _eu = null;
let _conectores = [];
let _siteAtual = null;                 // { id, nome }
let _view = 'dashboard';

// ───────────────────────────── utilidades ─────────────────────────────

const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

let _avisoTimer = null;
function aviso(texto, ruim = false) {
  const el = $('#aviso');
  el.textContent = texto;
  el.classList.toggle('ruim', !!ruim);
  el.hidden = false;
  clearTimeout(_avisoTimer);
  _avisoTimer = setTimeout(() => { el.hidden = true; }, ruim ? 5200 : 2800);
}

function guardar(chave, valor) {
  // localStorage pode estourar (cota) ou estar bloqueado. Nenhuma tela pode
  // morrer por causa disso: cache e conveniencia, nao fonte da verdade.
  try { localStorage.setItem(chave, JSON.stringify(valor)); } catch (_) {}
}
function ler(chave) {
  try { return JSON.parse(localStorage.getItem(chave) || 'null'); } catch (_) { return null; }
}

function emCache(nome) {
  const item = ler(CACHE_PREFIXO + nome);
  if (!item || !item.em) return null;
  return { dados: item.dados, em: item.em, velho: (Date.now() - item.em) > CACHE_VALIDADE_MS };
}
function paraCache(nome, dados) {
  guardar(CACHE_PREFIXO + nome, { em: Date.now(), dados });
}

function quando(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).slice(0, 16);
  const min = Math.floor((Date.now() - d.getTime()) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `ha ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `ha ${h} h`;
  return `ha ${Math.floor(h / 24)} d`;
}

// ───────────────────────────── rede ─────────────────────────────

function marcarRede(online) {
  const chip = $('#chipRede');
  chip.className = 'chip ' + (online ? 'ok' : 'off');
  chip.querySelector('span').textContent = online ? 'Online' : 'Sem sinal';
  chip.querySelector('i').className = 'ponto ' + (online ? 'ok' : 'off');
}
window.addEventListener('online', () => { marcarRede(true); desenhar(); });
window.addEventListener('offline', () => marcarRede(false));

async function pedir(caminho, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (_token) headers.Authorization = `Bearer ${_token}`;
  const res = await fetch(API + caminho, { credentials: 'same-origin', ...opts, headers });
  if (res.status === 401) { sair(false); return null; }
  return res;
}

async function json(caminho) {
  try {
    const res = await pedir(caminho);
    if (!res || !res.ok) return null;
    return await res.json();
  } catch (_) {
    // Sem rede: quem chamou decide se usa cache.
    return null;
  }
}

/** Busca na rede e guarda; sem rede, devolve o que foi guardado antes.
 *  Retorna { dados, doCache, em } para a tela poder dizer a verdade. */
async function buscarComCache(nome, caminho) {
  const vivo = navigator.onLine ? await json(caminho) : null;
  if (vivo) {
    paraCache(nome, vivo);
    return { dados: vivo, doCache: false, em: Date.now() };
  }
  const guardado = emCache(nome);
  if (guardado) return { dados: guardado.dados, doCache: true, em: guardado.em };
  return { dados: null, doCache: false, em: 0 };
}

// ───────────────────────────── login ─────────────────────────────

async function entrar(usuario, senha) {
  const res = await fetch(API + '/api/auth/login', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: usuario, password: senha }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    return { ok: false, msg: err.detail || 'Usuario ou senha invalidos' };
  }
  const data = await res.json();
  // O token tambem e guardado porque dentro do APK a origem muda e o cookie
  // de sessao deixa de valer; o Bearer continua valendo.
  _token = data.access_token || data.token || null;
  if (_token) guardar(CHAVE_TOKEN, _token);
  return { ok: true };
}

function sair(avisar = true) {
  pedir('/api/auth/logout', { method: 'POST' }).catch(() => {});
  _token = null;
  try { localStorage.removeItem(CHAVE_TOKEN); } catch (_) {}
  $('#app').hidden = true;
  $('#telaLogin').hidden = false;
  fecharGaveta();
  if (avisar) aviso('Sessao encerrada.');
}

// ───────────────────────────── gaveta ─────────────────────────────

const MENU = [
  { sec: 'Consulta' },
  { view: 'dashboard', rot: 'Dashboard', icone: 'grid' },
  { view: 'site', rot: 'Site', icone: 'pin' },
  { view: 'projeto', rot: 'Projeto do site', icone: 'pasta' },
  { sec: 'Implantacao' },
  { view: 'onu', rot: 'Ativar ONU', icone: 'onu', sinal: true },
  { view: 'ativar', rot: 'Ativar camera', icone: 'raio', sinal: true },
  { view: 'instalar', rot: 'Instalar camera', icone: 'cam', sinal: true },
  { sec: 'Ajustar' },
  { view: 'gravador', rot: 'Gravador', icone: 'nvr', sinal: true },
  { view: 'camera', rot: 'Camera', icone: 'engrenagem', sinal: true },
];

const ICONES = {
  grid: '<rect x="3" y="3" width="7" height="8" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="11" width="7" height="10" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>',
  pin: '<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z"/><circle cx="12" cy="10" r="2.4"/>',
  pasta: '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2.5h6.5A1.5 1.5 0 0 1 20 8v10a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18Z"/>',
  onu: '<path d="M5 12a7 7 0 0 1 14 0"/><path d="M8.5 12a3.5 3.5 0 0 1 7 0"/><circle cx="12" cy="17" r="1.6"/>',
  raio: '<path d="M13 3 5 13.5h6L10.5 21 19 10.5h-6Z"/>',
  cam: '<rect x="3" y="6.5" width="18" height="12" rx="2"/><circle cx="12" cy="12.5" r="3.2"/>',
  nvr: '<rect x="3" y="5" width="18" height="6" rx="1.6"/><rect x="3" y="13" width="18" height="6" rx="1.6"/>',
  engrenagem: '<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M21 12h-2.5M5.5 12H3"/>',
  alerta: '<path d="M12 8.5v5"/><path d="M12 17h.01"/><circle cx="12" cy="12" r="9"/>',
};
const svg = (nome) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true">${ICONES[nome] || ''}</svg>`;

function montarGaveta() {
  $('#gavetaNav').innerHTML = MENU.map((it) => {
    if (it.sec) return `<div class="gaveta-sec">${esc(it.sec)}</div>`;
    return `<button type="button" class="gaveta-item" data-view="${esc(it.view)}"
      ${it.view === _view ? 'aria-current="page"' : ''}>
      ${svg(it.icone)}<span>${esc(it.rot)}</span>
      ${it.sinal ? '<span class="tag">exige sinal</span>' : ''}
    </button>`;
  }).join('');
}
function abrirGaveta() { montarGaveta(); $('#gaveta').hidden = false; $('#gavetaFundo').hidden = false; }
function fecharGaveta() { $('#gaveta').hidden = true; $('#gavetaFundo').hidden = true; }

// ───────────────────────────── dados ─────────────────────────────

async function carregarConectores() {
  const r = await buscarComCache('conectores', '/api/connectors');
  _conectores = Array.isArray(r.dados?.connectors) ? r.dados.connectors : [];
  return r;
}

function siteDoConector(c) {
  return String(c?.site || c?.client || c?.name || '').trim();
}

/** Cameras do site escolhido, de todos os modos de inventario. */
async function carregarCameras() {
  const modos = ['olt', 'basico', 'switch'];
  const partes = await Promise.all(modos.map((m) =>
    buscarComCache(`cameras:${m}`, `/api/cameras?mode=${encodeURIComponent(m)}`)));
  const vistas = new Map();
  let doCache = false;
  let em = 0;
  partes.forEach((p) => {
    if (p.doCache) doCache = true;
    if (p.em) em = Math.max(em, p.em);
    const linhas = Array.isArray(p.dados?.cameras) ? p.dados.cameras
      : (Array.isArray(p.dados?.rows) ? p.dados.rows : []);
    linhas.forEach((row) => {
      // A mesma camera aparece em mais de um modo de inventario: a chave
      // ip+mac evita conta-la duas vezes, como o dashboard do app web faz.
      const chave = `${row.ip || ''}|${row.mac || ''}`;
      if (!vistas.has(chave)) vistas.set(chave, row);
    });
  });
  return { linhas: [...vistas.values()], doCache, em };
}

function doSite(linhas, site) {
  if (!site) return linhas;
  const alvo = site.toLowerCase();
  return linhas.filter((r) => String(r.site || r.site_name || r.local || '').toLowerCase() === alvo);
}

function estadoDaCamera(row) {
  const s = String(row.status || '').toLowerCase();
  if (s === 'online') return 'online';
  if (s === 'unknown' || s === 'desconhecido' || !s) return 'sem';
  return 'offline';
}

// ───────────────────────────── telas ─────────────────────────────

const TITULOS = {
  dashboard: 'Dashboard', site: 'Site', projeto: 'Projeto', menu: 'Menu',
  onu: 'Ativar ONU', ativar: 'Ativar camera', instalar: 'Instalar camera',
  gravador: 'Gravador', camera: 'Camera',
};

function irPara(view) {
  _view = view;
  $('#tbTitulo').textContent = TITULOS[view] || 'SightOps';
  document.querySelectorAll('.bottom button').forEach((b) => {
    b.setAttribute('aria-current', b.dataset.view === view ? 'page' : 'false');
  });
  fecharGaveta();
  desenhar();
}

function carregando() {
  $('#conteudo').innerHTML = '<div class="carregando">Carregando…</div>';
}

function selo(r) {
  if (!r) return '';
  if (r.doCache) {
    return `<span class="badge badge-amber">no aparelho &middot; ${esc(quando(new Date(r.em).toISOString()))}</span>`;
  }
  return '<span class="badge badge-green">agora</span>';
}

async function desenhar() {
  if (_view === 'dashboard') return telaDashboard();
  if (_view === 'site') return telaSite();
  if (_view === 'projeto') return telaProjeto();
  if (_view === 'menu') { abrirGaveta(); return telaDashboard(); }
  return telaEmBreve();
}

function telaEmBreve() {
  const rot = TITULOS[_view] || 'Esta tela';
  $('#conteudo').innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">Implantacao</p>
      <h1>${esc(rot)}</h1>
      <p>Comando em equipamento vivo, pelo tunel do conector.</p>
    </div>
    <section class="panel atencao">
      <div class="panel-body">
        <p style="margin:0;font-size:13.5px">
          Ainda nao disponivel neste aplicativo. Use o SightOps no navegador por enquanto.
        </p>
        <p style="margin:0;font-size:12.5px;color:var(--muted)">
          Esta tela nao pode funcionar sem sinal: ela manda ordens para o equipamento
          na hora, e nao tem como entrar numa fila para subir depois.
        </p>
      </div>
    </section>`;
}

// ── Dashboard ───────────────────────────────────────────────────────
async function telaDashboard() {
  carregando();
  const r = await buscarComCache('dashboard', '/api/dashboard/summary');
  if (!r.dados) {
    $('#conteudo').innerHTML = `
      <div class="page-heading"><p class="eyebrow">Central operacional</p><h1>Dashboard</h1></div>
      <section class="panel"><div class="vazio">Sem dados e sem copia no aparelho.<br>Conecte uma vez para baixar.</div></section>`;
    return;
  }
  const inv = r.dados.inventory || {};
  const ip = inv.ip || {}, nvr = inv.nvr || {}, dvr = inv.dvr || {};
  const sites = Array.isArray(r.dados.sites) ? r.dados.sites.length : (r.dados.sites?.total ?? '—');
  const alertas = Array.isArray(r.dados.alerts) ? r.dados.alerts : [];

  const cartao = (cor, icone, rot, num, sub) => `
    <div class="kpi">
      <span class="metric-icon ${cor}">${svg(icone)}</span>
      <span style="min-width:0;flex:1">
        <span class="rot">${esc(rot)}</span>
        <span class="num">${esc(num)}</span>
        <span class="sub">${esc(sub)}</span>
      </span>
    </div>`;

  $('#conteudo').innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">Central operacional</p>
      <h1>Dashboard</h1>
      <p>Disponibilidade e cobertura de todo o parque.</p>
    </div>
    <div style="display:flex;gap:9px;align-items:center;margin-bottom:12px">
      ${selo(r)}
      <button type="button" class="acao" id="btnAtualizar" style="width:auto;min-height:44px;flex:1">Atualizar</button>
    </div>
    <div class="metrics">
      ${cartao('green', 'cam', 'Cameras IP', ip.online ?? '—', `de ${ip.total ?? '—'} total`)}
      ${cartao('blue', 'nvr', 'Gravadores', (nvr.total ?? 0) + (dvr.total ?? 0), `${dvr.total ?? 0} DVR &middot; ${nvr.total ?? 0} NVR`)}
      ${cartao('red', 'alerta', 'Fora do ar', ip.offline ?? 0, 'cameras sem resposta')}
      ${cartao('amber', 'alerta', 'Sem leitura', ip.unknown ?? 0, 'nao deu para medir')}
      ${cartao('purple', 'pin', 'Sites', sites, 'no inventario')}
      ${cartao('cyan', 'onu', 'Sem snapshot', ip.missing_snapshot ?? 0, 'cameras sem foto')}
    </div>
    ${alertas.length ? `
    <hr class="sep">
    <section class="panel atencao">
      <div class="panel-header"><div><h2>Precisam de atencao</h2><p>Parque inteiro</p></div>
        <span class="badge badge-red">${alertas.length}</span></div>
      ${alertas.map((a) => `
        <div class="linha">
          <span class="mi">${svg('alerta')}</span>
          <span style="min-width:0"><span class="t">${esc(a.label || '—')}</span>
          <span class="s">${esc(a.level || '')}</span></span>
          <span class="badge badge-${a.level === 'danger' ? 'red' : a.level === 'warning' ? 'amber' : 'gray'}">${esc(a.count ?? '')}</span>
        </div>`).join('')}
    </section>` : ''}`;

  $('#btnAtualizar')?.addEventListener('click', async () => {
    if (!navigator.onLine) { aviso('Sem sinal: mostrando a copia do aparelho.', true); return; }
    await telaDashboard();
    aviso('Atualizado.');
  });
}

// ── Site ────────────────────────────────────────────────────────────
async function telaSite() {
  carregando();
  await carregarConectores();
  if (!_siteAtual) {
    const salvo = ler(CHAVE_SITE);
    if (salvo) _siteAtual = salvo;
  }

  if (!_siteAtual) return escolherSite();

  const r = await carregarCameras();
  const linhas = doSite(r.linhas, _siteAtual.nome);
  const total = linhas.length;
  const online = linhas.filter((x) => estadoDaCamera(x) === 'online').length;
  const fora = linhas.filter((x) => estadoDaCamera(x) === 'offline');
  const sem = linhas.filter((x) => estadoDaCamera(x) === 'sem');

  const cartao = (cor, icone, rot, num, sub) => `
    <div class="kpi">
      <span class="metric-icon ${cor}">${svg(icone)}</span>
      <span style="min-width:0;flex:1">
        <span class="rot">${esc(rot)}</span><span class="num">${esc(num)}</span><span class="sub">${esc(sub)}</span>
      </span>
    </div>`;

  const visita = [...fora, ...sem].slice(0, 25);

  $('#conteudo').innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">Campo</p>
      <h1>${esc(_siteAtual.nome || 'Site')}</h1>
      <p>O que esta de pe aqui e o que precisa de visita.</p>
    </div>
    <div style="display:flex;gap:9px;align-items:center;margin-bottom:12px">
      ${selo({ doCache: r.doCache, em: r.em })}
      <button type="button" class="acao" id="btnTrocarSite" style="width:auto;min-height:44px;flex:1">Trocar de site</button>
    </div>
    <div class="metrics">
      ${cartao('green', 'cam', 'Respondendo', online, `de ${total} no site`)}
      ${cartao('red', 'alerta', 'Fora do ar', fora.length, fora.length ? 'precisa de visita' : 'nenhuma')}
      ${cartao('amber', 'alerta', 'Sem leitura', sem.length, sem.length ? 'conector ou rede' : 'nenhuma')}
      ${cartao('blue', 'pasta', 'No projeto', total, 'cameras cadastradas')}
    </div>
    <hr class="sep">
    <section class="panel ${visita.length ? 'atencao' : ''}">
      <div class="panel-header">
        <div><h2>Precisam de visita</h2><p>Fora do ar e sem leitura</p></div>
        <span class="badge badge-${visita.length ? 'red' : 'green'}">${visita.length}</span>
      </div>
      ${visita.length ? visita.map((c) => `
        <div class="linha">
          <span class="mi">${svg('cam')}</span>
          <span style="min-width:0">
            <span class="t">${esc(c.titulo || c.title || c.ip || '—')}</span>
            <span class="s mono">${esc(c.ip || '')}${c.recorder_channel ? ' &middot; CH ' + esc(c.recorder_channel) : ''}</span>
          </span>
          <span class="badge badge-${estadoDaCamera(c) === 'offline' ? 'red' : 'amber'}">
            ${estadoDaCamera(c) === 'offline' ? 'fora' : 'sem ler'}</span>
        </div>`).join('')
      : '<div class="vazio">Tudo respondendo neste site.</div>'}
    </section>`;

  $('#btnTrocarSite')?.addEventListener('click', escolherSite);
}

function escolherSite() {
  const sites = [...new Set(_conectores.map(siteDoConector).filter(Boolean))].sort();
  $('#conteudo').innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">Campo</p>
      <h1>Onde voce esta</h1>
      <p>Escolha o site para o resto do aplicativo se situar.</p>
    </div>
    <section class="panel">
      ${sites.length ? sites.map((s) => `
        <button type="button" class="linha" data-site="${esc(s)}">
          <span class="mi">${svg('pin')}</span>
          <span style="min-width:0"><span class="t">${esc(s)}</span></span>
          <svg viewBox="0 0 24 24" fill="none" stroke="#66747e" stroke-width="2.2" style="width:17px;height:17px"><path d="m9 6 6 6-6 6"/></svg>
        </button>`).join('')
      : '<div class="vazio">Nenhum conector com site. Conecte uma vez para baixar a lista.</div>'}
    </section>`;

  $('#conteudo').querySelectorAll('[data-site]').forEach((b) => {
    b.addEventListener('click', () => {
      _siteAtual = { nome: b.dataset.site };
      guardar(CHAVE_SITE, _siteAtual);
      $('#gavetaCliente').textContent = _siteAtual.nome;
      telaSite();
    });
  });
}

// ── Projeto ─────────────────────────────────────────────────────────
let _filtroProjeto = 'todas';
let _buscaProjeto = '';

async function telaProjeto() {
  carregando();
  if (!_siteAtual) { const s = ler(CHAVE_SITE); if (s) _siteAtual = s; }
  const r = await carregarCameras();
  const todas = doSite(r.linhas, _siteAtual?.nome);

  const porEstado = (e) => todas.filter((c) => estadoDaCamera(c) === e);
  const conta = { todas: todas.length, offline: porEstado('offline').length, sem: porEstado('sem').length };

  let lista = todas;
  if (_filtroProjeto === 'offline') lista = porEstado('offline');
  if (_filtroProjeto === 'sem') lista = porEstado('sem');
  if (_buscaProjeto) {
    const q = _buscaProjeto.toLowerCase();
    lista = lista.filter((c) => [c.titulo, c.title, c.ip, c.mac, c.modelo, c.recorder_channel]
      .some((v) => String(v || '').toLowerCase().includes(q)));
  }

  // Agrupar por gravador: e como o tecnico pensa o site.
  const grupos = new Map();
  lista.forEach((c) => {
    const g = String(c.recorder_host || '').trim() || '__sem__';
    if (!grupos.has(g)) grupos.set(g, []);
    grupos.get(g).push(c);
  });

  $('#conteudo').innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">Consulta</p>
      <h1>Projeto do site</h1>
      <p>${esc(_siteAtual?.nome || 'Todos os sites')} &middot; ${todas.length} cameras</p>
    </div>
    <div style="margin-bottom:11px">${selo({ doCache: r.doCache, em: r.em })}</div>
    <div class="busca">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>
      <label for="q" style="position:absolute;left:-9999px">Procurar</label>
      <input id="q" placeholder="Titulo, IP, MAC ou canal" value="${esc(_buscaProjeto)}">
    </div>
    <div class="abas">
      <button type="button" class="aba" data-f="todas" aria-pressed="${_filtroProjeto === 'todas'}">Todas ${conta.todas}</button>
      <button type="button" class="aba" data-f="offline" aria-pressed="${_filtroProjeto === 'offline'}">Fora do ar ${conta.offline}</button>
      <button type="button" class="aba" data-f="sem" aria-pressed="${_filtroProjeto === 'sem'}">Sem leitura ${conta.sem}</button>
    </div>
    ${[...grupos.entries()].map(([host, cams]) => `
      <section class="panel">
        <div class="panel-header">
          <div><h2>${host === '__sem__' ? 'Sem gravador' : esc(host)}</h2>
          <p>${cams.length} camera${cams.length === 1 ? '' : 's'}</p></div>
        </div>
        ${cams.map((c) => {
          const e = estadoDaCamera(c);
          return `<div class="linha">
            <span class="mi">${svg('cam')}</span>
            <span style="min-width:0">
              <span class="t">${esc(c.titulo || c.title || '(sem titulo)')}</span>
              <span class="s mono">${esc(c.ip || '')}${c.modelo ? ' &middot; ' + esc(c.modelo) : ''}</span>
            </span>
            <span class="badge badge-${e === 'online' ? 'green' : e === 'offline' ? 'red' : 'amber'}">
              ${c.recorder_channel ? 'CH ' + esc(c.recorder_channel) : (e === 'online' ? 'ok' : e === 'offline' ? 'fora' : '?')}
            </span>
          </div>`;
        }).join('')}
      </section>`).join('') || '<section class="panel"><div class="vazio">Nada com esse filtro.</div></section>'}`;

  $('#q')?.addEventListener('input', (ev) => {
    _buscaProjeto = ev.target.value;
    clearTimeout(_buscaProjeto._t);
    setTimeout(telaProjeto, 220);
  });
  $('#conteudo').querySelectorAll('[data-f]').forEach((b) => {
    b.addEventListener('click', () => { _filtroProjeto = b.dataset.f; telaProjeto(); });
  });
}

// ───────────────────────────── inicio ─────────────────────────────

async function comecar() {
  $('#telaLogin').hidden = true;
  $('#app').hidden = false;
  marcarRede(navigator.onLine);

  const me = await json('/api/auth/me');
  _eu = me?.user || me || null;
  const cliente = _eu?.tenant_name || _eu?.tenant || _eu?.client || '';
  $('#gavetaCliente').textContent = cliente || (_eu?.username ?? '');
  $('#gavetaAmbiente').textContent = 'Producao' + (cliente ? ' · ' + cliente : '');

  const s = ler(CHAVE_SITE);
  if (s) _siteAtual = s;

  irPara('dashboard');
}

function ligar() {
  $('#formLogin').addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = $('#btnEntrar');
    const erro = $('#loginErro');
    erro.hidden = true;
    btn.disabled = true;
    btn.textContent = 'Entrando…';
    try {
      const r = await entrar($('#loginUser').value.trim(), $('#loginPass').value);
      if (!r.ok) { erro.textContent = r.msg; erro.hidden = false; return; }
      await comecar();
    } catch (_) {
      erro.textContent = 'Sem conexao com o servidor.';
      erro.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Entrar';
    }
  });

  document.querySelectorAll('.bottom button').forEach((b) => {
    b.addEventListener('click', () => irPara(b.dataset.view));
  });
  $('#btnMenu').addEventListener('click', abrirGaveta);
  $('#gavetaFundo').addEventListener('click', fecharGaveta);
  $('#btnSair').addEventListener('click', () => sair());
  $('#gavetaNav').addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-view]');
    if (b) irPara(b.dataset.view);
  });
}

(async function iniciar() {
  ligar();
  _token = ler(CHAVE_TOKEN);
  // Sessao viva? O /me confirma sem pedir senha de novo. Sem rede, o app
  // ainda abre: as telas de consulta vivem do cache.
  const me = await json('/api/auth/me');
  if (me) { await comecar(); return; }
  if (!navigator.onLine && emCache('dashboard')) { await comecar(); return; }
  $('#telaLogin').hidden = false;
})();
