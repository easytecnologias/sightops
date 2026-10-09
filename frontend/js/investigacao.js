// Investigacao: acha o momento nas gravacoes sem saber o horario exato.
//
// Substitui as telas Reproducao (IP/senha digitados a mao, so download) e
// IA - NVR (janela maxima de 10 min, video inteiro mandado ao Gemini). Tudo
// aqui sai do driver de gravador (/api/nvr/driver/*):
//   indice   -> linha do tempo: o que esta gravado e onde teve movimento
//   playback -> o player toca a GRAVACAO pelo go2rtc (mesmo caminho do ao vivo)
//   quadro   -> miniatura de um instante (cache no servidor)
//   trecho   -> MP4 na resolucao original
//   casos    -> o que interessa vira um caso, com anotacao
// Deteccao de pessoa/veiculo ainda nao existe: os chips aparecem desligados,
// com aviso, em vez de fingir resultado.

const INV_MAX_CAMERAS = 8;
const INV_PRE_GRAVACAO_S = 10;   // perfil do driver: a etiqueta comeca 10 s antes do disparo
const INV_JUNTA_EVENTOS_S = 30;  // movimentos a menos de 30 s viram uma aparicao so

const _inv = {
  bound: false,
  targets: [],
  selecionadas: new Map(),   // chave -> target
  periodo: null,             // {ini: Date, fim: Date, preset}
  linhas: new Map(),         // chave -> {segs, erro, carregando}
  eventos: [],               // {chave, ini: Date, fim: Date}
  ordem: 'hora',
  player: null,              // {chave, base: Date, handle}
  pularParado: true,
  casos: [],
  caso: null,
  relogios: new Map(),       // host -> diferenca_s
  quadros: new Map(),        // url -> objectURL
  timerPulo: null,
};

function _invChave(t) { return `${t.host}|${t.http_port || 80}|${t.channel}`; }
function _invPad(n) { return String(n).padStart(2, '0'); }
function _invFmt(d) {
  return `${d.getFullYear()}-${_invPad(d.getMonth() + 1)}-${_invPad(d.getDate())} ${_invPad(d.getHours())}:${_invPad(d.getMinutes())}:${_invPad(d.getSeconds())}`;
}
function _invParse(s) { return new Date(String(s).replace(' ', 'T')); }
function _invHora(d) { return `${_invPad(d.getHours())}:${_invPad(d.getMinutes())}:${_invPad(d.getSeconds())}`; }
function _invDataHora(d) { return `${_invPad(d.getDate())}/${_invPad(d.getMonth() + 1)}/${d.getFullYear()} ${_invHora(d)}`; }
function _invDur(seg) {
  const m = Math.floor(seg / 60), s = Math.round(seg % 60);
  return m ? `${m}min${s ? _invPad(s) : ''}` : `${s}s`;
}
function _invHoras(seg) {
  const h = Math.floor(seg / 3600), m = Math.round((seg % 3600) / 60);
  return h ? `${h}h${_invPad(m)}` : `${m} min`;
}

function _invCameraNome(t) {
  const titulo = String(t.title || '').trim();
  return titulo || `Camera ${_invPad(t.channel || 0)}`;
}
function _invCurto(t) {
  const nome = _invCameraNome(t).replace(/^\d+\s*-\s*/, '');
  return `${_invPad(t.channel)} · ${nome}`;
}

// ---------------------------------------------------------------- carga
async function loadInvestigacao() {
  if (!_inv.bound) bindInvestigacao();
  if (!_inv.periodo) invAplicarPreset('ontem');
  const data = await apiJson('/api/ia/nvr/targets');
  _inv.targets = data?.targets || [];
  invRenderArvore();
  invRenderChips();
  invCarregarCasos();
}

function bindInvestigacao() {
  _inv.bound = true;
  const $ = id => document.getElementById(id);
  $('invBusca')?.addEventListener('input', invRenderArvore);
  $('invChipInput')?.addEventListener('input', e => { $('invBusca').value = e.target.value; invRenderArvore(); });
  document.querySelectorAll('#invPresets [data-preset]').forEach(b => b.addEventListener('click', () => invAplicarPreset(b.dataset.preset)));
  $('invIni')?.addEventListener('change', invPeriodoManual);
  $('invFim')?.addEventListener('change', invPeriodoManual);
  $('btnInvestigar')?.addEventListener('click', invInvestigar);
  document.querySelectorAll('#invOrdem [data-ordem]').forEach(b => b.addEventListener('click', () => {
    _inv.ordem = b.dataset.ordem;
    document.querySelectorAll('#invOrdem [data-ordem]').forEach(x => x.classList.toggle('on', x === b));
    invRenderResultados();
  }));
  $('invBtnVoltar')?.addEventListener('click', () => invPular(-10));
  $('invBtnAvancar')?.addEventListener('click', () => invPular(10));
  $('invBtnPlay')?.addEventListener('click', invPlayPause);
  $('invPularParado')?.addEventListener('change', e => { _inv.pularParado = e.target.checked; });
  $('invBtnAddCaso')?.addEventListener('click', () => invAdicionarAoCaso(null));
  $('invBtnTrecho')?.addEventListener('click', invBaixarTrechoAtual);
  $('invCasoSel')?.addEventListener('change', e => invSelecionarCaso(e.target.value));
  $('invCasoNovo')?.addEventListener('click', invNovoCaso);
  $('invCasoNotas')?.addEventListener('input', invSalvarNotasDepois);
  $('invCasoBaixar')?.addEventListener('click', invBaixarTrechosDoCaso);
  $('invBtnAnteriores')?.addEventListener('click', invMostrarAnteriores);
}

// --------------------------------------------------------------- periodo
function invAplicarPreset(preset) {
  const agora = new Date();
  let ini, fim = agora;
  if (preset === 'hora') ini = new Date(agora.getTime() - 3600e3);
  else if (preset === 'hoje') { ini = new Date(agora); ini.setHours(0, 0, 0, 0); }
  else if (preset === 'ontem') {
    ini = new Date(agora); ini.setDate(ini.getDate() - 1); ini.setHours(18, 0, 0, 0);
    fim = new Date(agora); fim.setHours(7, 0, 0, 0);
    if (fim > agora) fim = agora;
  } else {
    ini = _inv.periodo?.ini || new Date(agora.getTime() - 3600e3);
    fim = _inv.periodo?.fim || agora;
  }
  _inv.periodo = { ini, fim, preset };
  document.querySelectorAll('#invPresets [data-preset]').forEach(b => b.classList.toggle('on', b.dataset.preset === preset));
  const custom = document.getElementById('invPeriodoCustom');
  if (custom) custom.hidden = preset !== 'custom';
  const toLocal = d => _invFmt(d).slice(0, 16).replace(' ', 'T');
  const iniEl = document.getElementById('invIni'), fimEl = document.getElementById('invFim');
  if (iniEl) iniEl.value = toLocal(ini);
  if (fimEl) fimEl.value = toLocal(fim);
  invRenderPeriodo();
}

function invPeriodoManual() {
  const ini = new Date(document.getElementById('invIni').value);
  const fim = new Date(document.getElementById('invFim').value);
  if (!(ini < fim)) { showToast('O fim precisa ser depois do inicio.', true); return; }
  if (fim - ini > 48 * 3600e3) { showToast('Periodo de ate 48 horas.', true); return; }
  _inv.periodo = { ini, fim, preset: 'custom' };
  invRenderPeriodo();
}

function invRenderPeriodo() {
  const el = document.getElementById('invPeriodoTexto');
  if (!el || !_inv.periodo) return;
  const f = d => `${_invPad(d.getDate())}/${_invPad(d.getMonth() + 1)} ${_invPad(d.getHours())}:${_invPad(d.getMinutes())}`;
  el.textContent = `${f(_inv.periodo.ini)} → ${f(_inv.periodo.fim)}`;
}

// ---------------------------------------------------------------- arvore
function _invNomesGravadores() {
  const porSite = {};
  _inv.targets.forEach(t => {
    const s = t.site || t.local || '';
    porSite[s] = porSite[s] || new Set();
    porSite[s].add(t.host);
  });
  const nomes = {};
  Object.values(porSite).forEach(hosts => {
    [...hosts].sort((a, b) => a.localeCompare(b, 'pt', { numeric: true })).forEach((h, i) => {
      const comNome = _inv.targets.find(t => t.host === h && t.recorder_name);
      nomes[h] = comNome?.recorder_name || `Gravador ${_invPad(i + 1)}`;
    });
  });
  return nomes;
}

function invRenderArvore() {
  const box = document.getElementById('invArvore');
  if (!box) return;
  const q = (document.getElementById('invBusca')?.value || '').trim().toLowerCase();
  const nomes = _invNomesGravadores();
  const filtrados = _inv.targets.filter(t => !q || [t.site, t.title, t.host, String(t.channel), nomes[t.host]]
    .some(v => String(v || '').toLowerCase().includes(q)));
  if (!filtrados.length) {
    box.innerHTML = `<p class="inv-vazio">${_inv.targets.length ? 'Nenhuma camera com esse nome.' : 'Nenhum gravador cadastrado.'}</p>`;
    return;
  }
  const porSite = new Map();
  filtrados.forEach(t => {
    const s = t.site || t.local || 'Sem site';
    if (!porSite.has(s)) porSite.set(s, new Map());
    const porHost = porSite.get(s);
    if (!porHost.has(t.host)) porHost.set(t.host, []);
    porHost.get(t.host).push(t);
  });
  let html = '';
  porSite.forEach((porHost, site) => {
    html += `<div class="inv-t-site">${esc(site)}</div>`;
    porHost.forEach((cams, host) => {
      const total = _inv.targets.filter(t => t.host === host).length;
      const modelo = cams[0]?.modelo ? `${cams[0].modelo} · ` : '';
      html += `<div class="inv-t-rec">${esc(modelo + nomes[host])}<small>${total} canais</small></div>`;
      cams.sort((a, b) => a.channel - b.channel).forEach(t => {
        const k = _invChave(t);
        const sel = _inv.selecionadas.has(k);
        const off = /off|down|fora/i.test(String(t.status || '')) ? ' off' : '';
        html += `<label class="inv-t-cam${sel ? ' sel' : ''}" title="${esc(host)} · canal ${t.channel}">
          <input type="checkbox" data-k="${esc(k)}"${sel ? ' checked' : ''}>
          <i class="inv-thumb-mini"></i><span>${esc(_invCurto(t))}</span><i class="inv-st${off}"></i></label>`;
      });
    });
  });
  box.innerHTML = html;
  box.querySelectorAll('input[data-k]').forEach(cb => cb.addEventListener('change', () => invAlternar(cb.dataset.k, cb.checked)));
}

function invAlternar(k, ligar) {
  if (ligar) {
    if (_inv.selecionadas.size >= INV_MAX_CAMERAS) {
      showToast(`No maximo ${INV_MAX_CAMERAS} cameras por investigacao.`, true);
      invRenderArvore();
      return;
    }
    const t = _inv.targets.find(x => _invChave(x) === k);
    if (t) _inv.selecionadas.set(k, t);
  } else {
    _inv.selecionadas.delete(k);
  }
  invRenderArvore();
  invRenderChips();
}

function invRenderChips() {
  const box = document.getElementById('invChips');
  if (!box) return;
  box.innerHTML = [..._inv.selecionadas.entries()].map(([k, t]) =>
    `<span class="inv-chip on">${esc(_invCurto(t))} <button type="button" class="inv-x" data-k="${esc(k)}" aria-label="Tirar">×</button></span>`).join('');
  box.querySelectorAll('.inv-x').forEach(b => b.addEventListener('click', () => invAlternar(b.dataset.k, false)));
}

// ------------------------------------------------------------ investigar
async function invInvestigar() {
  if (!_inv.selecionadas.size) { showToast('Escolha ao menos uma camera.', true); return; }
  if (!_inv.periodo) return;
  const btn = document.getElementById('btnInvestigar');
  btn.disabled = true;
  _inv.linhas.clear();
  _inv.eventos = [];
  invGuardarBusca();
  _inv.selecionadas.forEach((t, k) => _inv.linhas.set(k, { carregando: true, segs: [] }));
  invRenderJob();
  invRenderLinhaTempo();
  invRenderResultados();

  const ini = _invFmt(_inv.periodo.ini), fim = _invFmt(_inv.periodo.fim);
  const fila = [..._inv.selecionadas.entries()];
  const trabalhar = async () => {
    while (fila.length) {
      const [k, t] = fila.shift();
      const qs = new URLSearchParams({ host: t.host, http_port: t.http_port || 80, canal: t.channel, inicio: ini, fim });
      try {
        const res = await api(`/api/nvr/driver/indice?${qs}`);
        if (!res) return;
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.detail === 'SEM_CREDENCIAL' ? 'sem senha salva para este gravador' : (data?.detail || 'falhou'));
        _inv.linhas.set(k, { segs: data.segmentos || [], resumo: data.resumo });
      } catch (e) {
        _inv.linhas.set(k, { segs: [], erro: e.message });
      }
      invMontarEventos();
      invRenderJob();
      invRenderLinhaTempo();
      invRenderResultados();
    }
  };
  // Tres gravadores por vez: o indice e leve, mas a mesma maquina responde a todos.
  await Promise.all([trabalhar(), trabalhar(), trabalhar()]);
  btn.disabled = false;
  invRelogiosDosGravadores();
  if (!_inv.player && _inv.eventos.length) invTocar(_inv.eventos[0].chave, _inv.eventos[0].ini);
}

function invMontarEventos() {
  const evs = [];
  _inv.linhas.forEach((linha, k) => {
    const mov = (linha.segs || []).filter(s => s.tipo === 'movimento')
      .map(s => ({ ini: _invParse(s.inicio), fim: _invParse(s.fim) }))
      .sort((a, b) => a.ini - b.ini);
    let atual = null;
    mov.forEach(m => {
      if (atual && (m.ini - atual.fim) / 1000 <= INV_JUNTA_EVENTOS_S) {
        if (m.fim > atual.fim) atual.fim = m.fim;
      } else {
        atual = { chave: k, ini: m.ini, fim: m.fim };
        evs.push(atual);
      }
    });
  });
  const { ini, fim } = _inv.periodo;
  _inv.eventos = evs.filter(e => e.fim > ini && e.ini < fim).sort((a, b) => a.ini - b.ini);
}

function invRenderJob() {
  const el = document.getElementById('invJob');
  if (!el) return;
  const total = _inv.linhas.size;
  const prontas = [..._inv.linhas.values()].filter(l => !l.carregando).length;
  const falhas = [..._inv.linhas.values()].filter(l => l.erro).length;
  const movS = _inv.eventos.reduce((n, e) => n + (e.fim - e.ini) / 1000, 0);
  const periodoS = _inv.periodo ? (_inv.periodo.fim - _inv.periodo.ini) / 1000 : 0;
  const pct = total ? Math.round((prontas / total) * 100) : 0;
  const ok = prontas === total && total > 0;
  el.hidden = !total;
  el.innerHTML = `
    <span class="inv-steps">
      <span><i class="inv-dot ${ok ? 'ok' : 'run'}"></i> Indice lido ${prontas}/${total}${falhas ? ` · ${falhas} com falha` : ''}</span>
      <span><i class="inv-dot ${ok ? 'ok' : ''}"></i> ${_invHoras(movS)} de movimento em ${_invHoras(periodoS)}</span>
      <span title="Fase 2: detectar pessoa e veiculo nos trechos com movimento"><i class="inv-dot"></i> Deteccao de pessoas · em breve</span>
    </span>
    <div class="inv-bar"><i style="width:${pct}%"></i></div>
    <span><b class="mono">${pct}%</b> · ${_inv.eventos.length} trecho${_inv.eventos.length === 1 ? '' : 's'} com movimento</span>`;
}

// ------------------------------------------------------- linha do tempo
function _invPct(d) {
  const { ini, fim } = _inv.periodo;
  return Math.max(0, Math.min(100, ((d - ini) / (fim - ini)) * 100));
}

function invRenderLinhaTempo() {
  const box = document.getElementById('invLinhas');
  const regua = document.getElementById('invRegua');
  if (!box || !_inv.periodo) return;
  const { ini, fim } = _inv.periodo;
  const marcas = [];
  for (let i = 0; i <= 6; i++) {
    const d = new Date(ini.getTime() + ((fim - ini) * i) / 6);
    marcas.push(`<span>${_invPad(d.getHours())}h${d.getMinutes() ? _invPad(d.getMinutes()) : ''}</span>`);
  }
  if (regua) regua.innerHTML = marcas.join('');
  if (!_inv.linhas.size) {
    box.innerHTML = '<p class="inv-vazio">Escolha as cameras e o periodo e clique em Investigar.</p>';
    document.getElementById('invBuracos').textContent = '';
    return;
  }
  const buracos = [];
  let html = '';
  _inv.linhas.forEach((linha, k) => {
    const t = _inv.selecionadas.get(k);
    if (!t) return;
    const evs = _inv.eventos.filter(e => e.chave === k);
    let sub = linha.carregando ? 'lendo indice...' : linha.erro ? esc(linha.erro) : `${evs.length} trecho${evs.length === 1 ? '' : 's'} com movimento`;
    let trilha = '';
    const segs = (linha.segs || []).map(s => ({ ...s, i: _invParse(s.inicio), f: _invParse(s.fim) })).sort((a, b) => a.i - b.i);
    segs.forEach(s => {
      const l = _invPct(s.i), w = Math.max(0.15, _invPct(s.f) - l);
      trilha += `<i class="${s.tipo === 'movimento' ? 'inv-mov' : 'inv-rec'}" style="left:${l}%;width:${w}%"></i>`;
    });
    // Buraco de gravacao maior que 2 min dentro do periodo pedido.
    if (!linha.carregando && !linha.erro) {
      let cursor = ini;
      segs.forEach(s => {
        if ((s.i - cursor) / 1000 > 120) buracos.push(`${_invCurto(t)} sem gravacao ${_invHora(cursor).slice(0, 5)}–${_invHora(s.i).slice(0, 5)}`);
        if (s.f > cursor) cursor = s.f;
      });
      const limite = new Date(Math.min(fim, Date.now() - 120e3));
      if ((limite - cursor) / 1000 > 120 && segs.length) buracos.push(`${_invCurto(t)} sem gravacao desde ${_invHora(cursor).slice(0, 5)}`);
    }
    evs.forEach(e => {
      trilha += `<i class="inv-hit" style="left:${_invPct(e.ini)}%" data-k="${esc(k)}" data-ts="${e.ini.getTime()}" title="${_invHora(e.ini)} · ${_invDur((e.fim - e.ini) / 1000)}"></i>`;
    });
    if (_inv.player?.chave === k) trilha += `<i class="inv-cursor" id="invCursor" style="left:${_invPct(invPosicao())}%"></i>`;
    html += `<div class="inv-tl-row">
      <div class="inv-tl-name">${esc(_invCurto(t))}<small class="${linha.erro ? 'inv-erro' : ''}">${sub}</small></div>
      <div class="inv-track" data-k="${esc(k)}">${trilha}</div></div>`;
  });
  box.innerHTML = html;
  document.getElementById('invBuracos').textContent = buracos.slice(0, 3).join(' · ');
  box.querySelectorAll('.inv-track').forEach(tr => tr.addEventListener('click', e => {
    if (e.target.classList.contains('inv-hit')) {
      invTocar(e.target.dataset.k, new Date(Number(e.target.dataset.ts)));
      return;
    }
    const r = tr.getBoundingClientRect();
    const frac = (e.clientX - r.left) / r.width;
    const d = new Date(_inv.periodo.ini.getTime() + frac * (_inv.periodo.fim - _inv.periodo.ini));
    invTocar(tr.dataset.k, d);
  }));
}

// -------------------------------------------------------------- player
function invPosicao() {
  const p = _inv.player;
  if (!p) return _inv.periodo?.ini || new Date();
  if (p.parado) return p.base;
  const v = document.getElementById('invVideo');
  // O go2rtc entrega a partir do inicio pedido; o player MSE toca ~2 s atras da borda.
  return new Date(p.base.getTime() + (v?.currentTime || 0) * 1000);
}

function invTocar(chave, momento) {
  const t = _inv.selecionadas.get(chave) || _inv.targets.find(x => _invChave(x) === chave);
  if (!t) return;
  if (_inv.player?.handle) _inv.player.handle.stop();
  const video = document.getElementById('invVideo');
  const status = document.getElementById('invPlayerStatus');
  const base = new Date(momento);
  _inv.player = { chave, base, parado: false, handle: null };
  document.getElementById('invOsdCamera').textContent = _invCameraNome(t).toUpperCase();
  document.getElementById('invPlayerVazio').hidden = true;
  _inv.player.handle = mountLiveStream(video, {
    registrar: async () => {
      // Reconexao recomeca de onde estava, nao do inicio pedido.
      const desde = _inv.player?.chave === chave ? invPosicao() : base;
      if (_inv.player) _inv.player.base = desde;
      const res = await api('/api/nvr/driver/playback', {
        method: 'POST',
        body: JSON.stringify({ host: t.host, http_port: t.http_port || 80, canal: t.channel, inicio: _invFmt(desde) }),
      });
      const data = await jsonOrReadableError(res, 'Falha ao abrir a gravacao.');
      return data.stream_name;
    },
    onStatus: txt => {
      if (!status) return;
      status.textContent = txt === 'credential_required' ? 'Sem senha salva para este gravador' : txt;
      status.hidden = !txt;
    },
  });
  invAtualizarBotaoPlay();
  invMarcarCartao();
  invRenderLinhaTempo();
  clearInterval(_inv.timerPulo);
  _inv.timerPulo = setInterval(invTique, 1000);
}

function invTique() {
  const p = _inv.player;
  if (!p || p.parado) return;
  const pos = invPosicao();
  const relogio = document.getElementById('invOsdHora');
  if (relogio) relogio.textContent = _invDataHora(pos);
  const cur = document.getElementById('invCursor');
  if (cur) cur.style.left = `${_invPct(pos)}%`;
  if (!_inv.pularParado) return;
  const evs = _inv.eventos.filter(e => e.chave === p.chave);
  if (!evs.length) return;
  const dentro = evs.some(e => pos >= new Date(e.ini.getTime() - 2000) && pos <= e.fim);
  if (dentro) return;
  const prox = evs.find(e => e.ini > pos);
  if (prox && (prox.ini - pos) > 5000) invTocar(p.chave, prox.ini);
}

function invPular(seg) {
  if (!_inv.player) return;
  invTocar(_inv.player.chave, new Date(invPosicao().getTime() + seg * 1000));
}

function invPlayPause() {
  const p = _inv.player;
  if (!p) {
    if (_inv.eventos.length) invTocar(_inv.eventos[0].chave, _inv.eventos[0].ini);
    return;
  }
  if (p.parado) { invTocar(p.chave, p.base); return; }
  // O stream de gravacao e continuo como o ao vivo: pausar = fechar e lembrar onde parou.
  p.base = invPosicao();
  p.parado = true;
  p.handle?.stop();
  invAtualizarBotaoPlay();
}

function invAtualizarBotaoPlay() {
  const b = document.getElementById('invBtnPlay');
  if (!b) return;
  const tocando = _inv.player && !_inv.player.parado;
  b.innerHTML = `<i data-lucide="${tocando ? 'pause' : 'play'}"></i>`;
  lucide.createIcons();
}

// ---------------------------------------------------------- resultados
async function _invQuadro(t, momento) {
  const qs = new URLSearchParams({ host: t.host, http_port: t.http_port || 80, canal: t.channel, ts: _invFmt(momento) });
  const chave = qs.toString();
  if (_inv.quadros.has(chave)) return _inv.quadros.get(chave);
  const res = await api(`/api/nvr/driver/quadro?${qs}`);
  if (!res || !res.ok) return '';
  const url = URL.createObjectURL(await res.blob());
  _inv.quadros.set(chave, url);
  return url;
}

let _invObservador = null;
function _invObservar(el) {
  if (!_invObservador) {
    _invObservador = new IntersectionObserver(entries => entries.forEach(async en => {
      if (!en.isIntersecting) return;
      const ph = en.target;
      _invObservador.unobserve(ph);
      const t = _inv.selecionadas.get(ph.dataset.k);
      if (!t) return;
      const url = await _invQuadro(t, new Date(Number(ph.dataset.ts)));
      if (url) ph.style.backgroundImage = `url("${url}")`;
      else ph.classList.add('inv-sem-quadro');
    }), { rootMargin: '120px' });
  }
  _invObservador.observe(el);
}

function invRenderResultados() {
  const box = document.getElementById('invResultados');
  const sub = document.getElementById('invResultadosSub');
  if (!box) return;
  let evs = [..._inv.eventos];
  if (_inv.ordem === 'camera') evs.sort((a, b) => a.chave.localeCompare(b.chave, 'pt', { numeric: true }) || a.ini - b.ini);
  if (sub) sub.textContent = evs.length
    ? `${evs.length} trecho${evs.length === 1 ? '' : 's'} com movimento · movimentos a menos de ${INV_JUNTA_EVENTOS_S} s viram um so`
    : 'Movimento marcado pelo proprio gravador';
  if (!evs.length) {
    box.innerHTML = `<p class="inv-vazio">${_inv.linhas.size ? 'Nenhum movimento marcado no periodo.' : 'Os trechos com movimento aparecem aqui.'}</p>`;
    return;
  }
  box.innerHTML = evs.slice(0, 200).map(e => {
    const t = _inv.selecionadas.get(e.chave);
    if (!t) return '';
    // A etiqueta comeca na pre-gravacao; a foto vem do momento do disparo.
    const foto = new Date(Math.min(e.ini.getTime() + INV_PRE_GRAVACAO_S * 1000, e.fim.getTime()));
    const noite = foto.getHours() >= 18 || foto.getHours() < 6;
    return `<div class="inv-card" data-k="${esc(e.chave)}" data-ts="${e.ini.getTime()}">
      <div class="inv-ph${noite ? ' night' : ''}" data-k="${esc(e.chave)}" data-ts="${foto.getTime()}">
        <span class="inv-kind">MOVIMENTO</span><span class="inv-tm mono">${_invHora(e.ini)}</span></div>
      <div class="inv-meta"><b>${esc(_invCurto(t))}</b><span>${_invDur((e.fim - e.ini) / 1000)} de movimento</span>
        <div class="inv-row"><span>${_invHora(e.fim)}</span><button class="inv-mini" type="button" data-add>+ caso</button></div></div></div>`;
  }).join('');
  box.querySelectorAll('.inv-ph').forEach(_invObservar);
  box.querySelectorAll('.inv-card').forEach(c => c.addEventListener('click', ev => {
    const e = _inv.eventos.find(x => x.chave === c.dataset.k && x.ini.getTime() === Number(c.dataset.ts));
    if (ev.target.closest('[data-add]')) { invAdicionarAoCaso(e); return; }
    invTocar(c.dataset.k, new Date(Number(c.dataset.ts)));
  }));
  invMarcarCartao();
}

function invMarcarCartao() {
  const p = _inv.player;
  document.querySelectorAll('#invResultados .inv-card').forEach(c => {
    const ts = Number(c.dataset.ts);
    const e = _inv.eventos.find(x => x.chave === c.dataset.k && x.ini.getTime() === ts);
    const pos = p ? invPosicao() : null;
    c.classList.toggle('sel', !!(p && e && c.dataset.k === p.chave && pos >= new Date(ts - 2000) && pos <= e.fim));
  });
}

// --------------------------------------------------------------- trecho
async function _invGerarTrecho(t, ini, fim) {
  const res = await api('/api/nvr/driver/trecho', {
    method: 'POST',
    body: JSON.stringify({ host: t.host, http_port: t.http_port || 80, canal: t.channel, inicio: _invFmt(ini), fim: _invFmt(fim) }),
  });
  return jsonOrReadableError(res, 'Falha ao baixar o trecho.');
}

function _invLinkArquivo(path) {
  const sep = path.includes('?') ? '&' : '?';
  return `${API_BASE}${path}${_token ? `${sep}token=${encodeURIComponent(_token)}` : ''}`;
}

async function invBaixarTrechoAtual() {
  const p = _inv.player;
  if (!p) { showToast('Abra um momento no player primeiro.', true); return; }
  const t = _inv.selecionadas.get(p.chave);
  const pos = invPosicao();
  const ev = _inv.eventos.find(e => e.chave === p.chave && pos >= new Date(e.ini.getTime() - 2000) && pos <= e.fim);
  const ini = ev ? ev.ini : new Date(pos.getTime() - 30e3);
  let fim = ev ? ev.fim : new Date(pos.getTime() + 90e3);
  if (fim - ini > 30 * 60e3) fim = new Date(ini.getTime() + 30 * 60e3);
  const btn = document.getElementById('invBtnTrecho');
  btn.disabled = true;
  showToast('Baixando o trecho do gravador...');
  try {
    const d = await _invGerarTrecho(t, ini, fim);
    window.open(_invLinkArquivo(d.url), '_blank', 'noopener');
  } catch (e) {
    showToast(e.message, true);
  } finally {
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------- casos
async function invCarregarCasos(selecionar) {
  const data = await apiJson('/api/nvr/driver/casos', { cacheTtl: 0 });
  _inv.casos = data?.casos || [];
  const sel = document.getElementById('invCasoSel');
  const alvo = selecionar || _inv.caso?.id || _inv.casos[0]?.id || '';
  if (sel) {
    sel.innerHTML = _inv.casos.length
      ? _inv.casos.map(c => `<option value="${esc(c.id)}">#${String(c.numero).padStart(4, '0')} · ${esc(c.titulo)}</option>`).join('')
      : '<option value="">Nenhum caso aberto</option>';
    sel.value = alvo;
  }
  const badge = document.getElementById('invCasosBadge');
  if (badge) { badge.textContent = String(_inv.casos.length); badge.hidden = !_inv.casos.length; }
  invSelecionarCaso(alvo);
}

function invSelecionarCaso(id) {
  _inv.caso = _inv.casos.find(c => c.id === id) || null;
  invRenderCaso();
}

async function invNovoCaso() {
  const titulo = (window.prompt('Titulo do caso (ex.: Furto de ferramentas na oficina):') || '').trim();
  if (!titulo) return null;
  const primeira = [..._inv.selecionadas.values()][0];
  const res = await api('/api/nvr/driver/casos', {
    method: 'POST',
    body: JSON.stringify({ titulo, site: primeira?.site || '', autor: _currentUser?.name || _currentUser?.username || '' }),
  });
  try {
    const caso = await jsonOrReadableError(res, 'Falha ao criar o caso.');
    await invCarregarCasos(caso.id);
    return caso;
  } catch (e) {
    showToast(e.message, true);
    return null;
  }
}

async function invAdicionarAoCaso(ev) {
  let alvoEv = ev;
  let chave, momento;
  if (alvoEv) {
    chave = alvoEv.chave;
    momento = new Date(alvoEv.ini.getTime() + INV_PRE_GRAVACAO_S * 1000);
  } else {
    if (!_inv.player) { showToast('Abra um momento no player primeiro.', true); return; }
    chave = _inv.player.chave;
    momento = invPosicao();
    alvoEv = _inv.eventos.find(e => e.chave === chave && momento >= new Date(e.ini.getTime() - 2000) && momento <= e.fim);
  }
  const t = _inv.selecionadas.get(chave);
  if (!t) return;
  if (!_inv.caso && !(await invNovoCaso())) return;
  const ini = alvoEv ? alvoEv.ini : new Date(momento.getTime() - 30e3);
  let fim = alvoEv ? alvoEv.fim : new Date(momento.getTime() + 90e3);
  if (fim - ini > 30 * 60e3) fim = new Date(ini.getTime() + 30 * 60e3);
  const res = await api(`/api/nvr/driver/casos/${encodeURIComponent(_inv.caso.id)}/itens`, {
    method: 'POST',
    body: JSON.stringify({ host: t.host, http_port: t.http_port || 80, canal: t.channel, camera: _invCurto(t),
      momento: _invFmt(momento), inicio: _invFmt(ini), fim: _invFmt(fim) }),
  });
  try {
    const caso = await jsonOrReadableError(res, 'Falha ao adicionar ao caso.');
    _inv.casos = _inv.casos.map(c => (c.id === caso.id ? caso : c));
    _inv.caso = caso;
    invRenderCaso();
    showToast('Adicionado ao caso.');
  } catch (e) {
    showToast(e.message, true);
  }
}

async function invRemoverItem(itemId) {
  const res = await api(`/api/nvr/driver/casos/${encodeURIComponent(_inv.caso.id)}/itens/${encodeURIComponent(itemId)}/remover`, { method: 'POST' });
  try {
    _inv.caso = await jsonOrReadableError(res, 'Falha ao remover.');
    _inv.casos = _inv.casos.map(c => (c.id === _inv.caso.id ? _inv.caso : c));
    invRenderCaso();
  } catch (e) { showToast(e.message, true); }
}

let _invNotasTimer = null;
function invSalvarNotasDepois() {
  if (!_inv.caso) return;
  clearTimeout(_invNotasTimer);
  const id = _inv.caso.id;
  _invNotasTimer = setTimeout(async () => {
    const notas = document.getElementById('invCasoNotas').value;
    const res = await api(`/api/nvr/driver/casos/${encodeURIComponent(id)}/notas`, { method: 'POST', body: JSON.stringify({ notas }) });
    if (res?.ok && _inv.caso?.id === id) _inv.caso.notas = notas;
  }, 800);
}

async function _invSalvarNotaItem(itemId, nota) {
  await api(`/api/nvr/driver/casos/${encodeURIComponent(_inv.caso.id)}/notas`, {
    method: 'POST', body: JSON.stringify({ item_id: itemId, nota_item: nota }),
  });
  const it = _inv.caso.itens.find(i => i.id === itemId);
  if (it) it.nota = nota;
}

async function invRelogiosDosGravadores() {
  const hosts = new Map();
  _inv.selecionadas.forEach(t => hosts.set(t.host, t));
  (_inv.caso?.itens || []).forEach(i => { if (!hosts.has(i.host)) hosts.set(i.host, { host: i.host, http_port: i.http_port }); });
  await Promise.all([...hosts.values()].filter(t => !_inv.relogios.has(t.host)).map(async t => {
    const d = await apiJson(`/api/nvr/driver/relogio?host=${encodeURIComponent(t.host)}&http_port=${t.http_port || 80}`, { cacheTtl: 0 });
    if (d && typeof d.diferenca_s === 'number') _inv.relogios.set(t.host, d.diferenca_s);
  }));
  invRenderCaso();
}

function invRenderCaso() {
  const c = _inv.caso;
  const $ = id => document.getElementById(id);
  const vazio = !c;
  $('invCasoTitulo').textContent = c ? `#${String(c.numero).padStart(4, '0')} · ${c.titulo}` : 'Nenhum caso aberto';
  $('invCasoSub').textContent = c
    ? [c.site, c.autor ? `aberto por ${c.autor}` : '', c.criado_em ? _invDataHora(_invParse(c.criado_em)).slice(0, 16) : ''].filter(Boolean).join(' · ')
    : 'Crie um caso para juntar os momentos que interessam.';
  const notas = $('invCasoNotas');
  if (notas && document.activeElement !== notas) notas.value = c?.notas || '';
  if (notas) notas.disabled = vazio;
  $('invCasoBaixar').disabled = vazio || !c.itens.length;

  // Aviso de relogio: o horario da imagem pode nao bater com o do indice.
  const hostsDoCaso = new Set([...(c?.itens || []).map(i => i.host), ..._inv.selecionadas.size ? [..._inv.selecionadas.values()].map(t => t.host) : []]);
  const tortos = [...hostsDoCaso].filter(h => Math.abs(_inv.relogios.get(h) || 0) > 60);
  const aviso = $('invCasoAviso');
  if (aviso) {
    aviso.hidden = !tortos.length;
    aviso.innerHTML = tortos.length ? `<span>⚠</span><span>Relogio ${tortos.map(h => {
      const s = _inv.relogios.get(h);
      return `de <b>${esc(h)}</b> ${Math.round(Math.abs(s) / 60)} min ${s > 0 ? 'adiantado' : 'atrasado'}`;
    }).join(', ')} em relacao ao servidor. O horario escrito na imagem pode diferir do indice.</span>` : '';
  }

  const lista = $('invCasoItens');
  if (!c || !c.itens.length) {
    lista.innerHTML = `<p class="inv-vazio">${c ? 'Use "+ caso" num trecho ou "Adicionar ao caso" no player.' : ''}</p>`;
    $('invCasoSugestao').hidden = true;
    return;
  }
  lista.innerHTML = c.itens.map(i => {
    const m = _invParse(i.momento);
    const faixa = i.inicio && i.fim ? `Clipe ${_invHora(_invParse(i.inicio))} → ${_invHora(_invParse(i.fim))}` : '';
    return `<div class="inv-ev" data-id="${esc(i.id)}">
      <i class="inv-thumb-mini" data-host="${esc(i.host)}" data-port="${i.http_port}" data-canal="${i.canal}" data-ts="${m.getTime()}"></i>
      <div><b class="mono">${_invHora(m)} · ${esc(i.camera || `canal ${i.canal}`)}</b><span>${faixa}</span>
        <p contenteditable="true" class="inv-ev-nota" data-placeholder="Anotacao...">${esc(i.nota || '')}</p></div>
      <button class="inv-mini inv-ev-x" type="button" title="Tirar do caso">×</button></div>`;
  }).join('');
  lista.querySelectorAll('.inv-thumb-mini[data-ts]').forEach(async el => {
    const url = await _invQuadro({ host: el.dataset.host, http_port: el.dataset.port, channel: el.dataset.canal }, new Date(Number(el.dataset.ts)));
    if (url) el.style.backgroundImage = `url("${url}")`;
  });
  lista.querySelectorAll('.inv-ev').forEach(row => {
    const id = row.dataset.id;
    row.querySelector('.inv-ev-x').addEventListener('click', () => invRemoverItem(id));
    const nota = row.querySelector('.inv-ev-nota');
    nota.addEventListener('blur', () => _invSalvarNotaItem(id, nota.textContent.trim()));
    row.querySelector('b').addEventListener('click', () => {
      const it = c.itens.find(x => x.id === id);
      const k = `${it.host}|${it.http_port}|${it.canal}`;
      if (!_inv.selecionadas.has(k)) {
        const t = _inv.targets.find(x => _invChave(x) === k);
        if (t) { _inv.selecionadas.set(k, t); invRenderChips(); invRenderArvore(); }
      }
      invTocar(k, _invParse(it.inicio || it.momento));
    });
  });

  // Sugestao: cameras vizinhas (canal +-1 no mesmo gravador) que ainda nao estao no caso.
  const usados = new Set(c.itens.map(i => `${i.host}|${i.canal}`));
  const vizinhas = [];
  c.itens.forEach(i => [i.canal - 1, i.canal + 1].forEach(n => {
    const t = _inv.targets.find(x => x.host === i.host && x.channel === n);
    if (t && !usados.has(`${t.host}|${n}`) && !vizinhas.includes(t)) vizinhas.push(t);
  }));
  const sug = $('invCasoSugestao');
  sug.hidden = !vizinhas.length;
  if (vizinhas.length) {
    sug.innerHTML = `<i data-lucide="arrow-right"></i><span>Sugestao: cameras vizinhas no mesmo horario — ${vizinhas.slice(0, 3)
      .map(t => `<a href="#" data-k="${esc(_invChave(t))}">${esc(_invCurto(t))}</a>`).join(', ')}</span>`;
    sug.querySelectorAll('a[data-k]').forEach(a => a.addEventListener('click', e => {
      e.preventDefault();
      invAlternar(a.dataset.k, true);
    }));
    lucide.createIcons();
  }
}

async function invBaixarTrechosDoCaso() {
  const c = _inv.caso;
  if (!c?.itens.length) return;
  const btn = document.getElementById('invCasoBaixar');
  const saida = document.getElementById('invCasoDownloads');
  btn.disabled = true;
  saida.innerHTML = '';
  for (const i of c.itens) {
    const linha = document.createElement('div');
    linha.className = 'inv-dl';
    linha.textContent = `${_invHora(_invParse(i.momento))} · ${i.camera}: baixando...`;
    saida.appendChild(linha);
    try {
      const d = await _invGerarTrecho({ host: i.host, http_port: i.http_port, channel: i.canal },
        _invParse(i.inicio || i.momento), _invParse(i.fim || i.momento));
      linha.innerHTML = `<a href="${esc(_invLinkArquivo(d.url))}" target="_blank" rel="noopener">${esc(`${_invHora(_invParse(i.momento))} · ${i.camera}`)} (${(d.size / 1048576).toFixed(1)} MB)</a>`;
    } catch (e) {
      linha.textContent = `${_invHora(_invParse(i.momento))} · ${i.camera}: ${e.message}`;
      linha.classList.add('inv-erro');
    }
  }
  btn.disabled = false;
}

// --------------------------------------------------- buscas anteriores
// Conveniencia por navegador (localStorage): perder isso nao perde nada.
function invGuardarBusca() {
  try {
    const lista = JSON.parse(localStorage.getItem('inv_buscas') || '[]');
    lista.unshift({ cams: [..._inv.selecionadas.keys()], ini: _inv.periodo.ini.getTime(), fim: _inv.periodo.fim.getTime(), quando: Date.now() });
    localStorage.setItem('inv_buscas', JSON.stringify(lista.slice(0, 8)));
  } catch (_) { /* navegador sem storage: segue sem historico */ }
}

function invMostrarAnteriores() {
  let lista = [];
  try { lista = JSON.parse(localStorage.getItem('inv_buscas') || '[]'); } catch (_) { lista = []; }
  const menu = document.getElementById('invAnteriores');
  if (!menu) return;
  if (!menu.hidden) { menu.hidden = true; return; }
  menu.innerHTML = lista.length ? lista.map((b, i) => {
    const nomes = b.cams.map(k => _inv.targets.find(t => _invChave(t) === k)).filter(Boolean).map(_invCurto);
    const f = d => `${_invPad(d.getDate())}/${_invPad(d.getMonth() + 1)} ${_invPad(d.getHours())}:${_invPad(d.getMinutes())}`;
    return `<button type="button" data-i="${i}"><b>${esc(f(new Date(b.ini)))} → ${esc(f(new Date(b.fim)))}</b><span>${esc(nomes.join(', ') || 'cameras removidas')}</span></button>`;
  }).join('') : '<p class="inv-vazio">Nenhuma busca ainda neste navegador.</p>';
  menu.hidden = false;
  menu.querySelectorAll('button[data-i]').forEach(b => b.addEventListener('click', () => {
    const busca = lista[Number(b.dataset.i)];
    _inv.selecionadas.clear();
    busca.cams.forEach(k => { const t = _inv.targets.find(x => _invChave(x) === k); if (t) _inv.selecionadas.set(k, t); });
    _inv.periodo = { ini: new Date(busca.ini), fim: new Date(busca.fim), preset: 'custom' };
    invAplicarPreset('custom');
    invRenderArvore();
    invRenderChips();
    menu.hidden = true;
    invInvestigar();
  }));
}
