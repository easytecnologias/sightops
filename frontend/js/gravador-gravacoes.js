// Gravador aberto > Gravacoes (parte 4 do mini DVR).
//
// O indice do PROPRIO gravador, dia a dia: o que esta gravado, onde teve
// movimento e onde tem buraco, canal por canal. Clicar na linha do tempo toca
// a gravacao dali no player (mesmo playback da Investigacao, pelo go2rtc).
// Daqui: foto do instante, MP4 de 2 min e "Abrir na Investigacao".
//
// Mora fora do deploy.js de proposito: entra pelo recRegistrarSecao, para a
// parte 5 (Canais/Discos/Historico) ser feita ao mesmo tempo em outro arquivo.
//
// O gravador e um so: as trilhas sao lidas UMA POR VEZ, e o player toca um
// canal so. A Intelbras trava calada com sessoes RTSP demais.

let _grv = null;   // {chave, dia, canal, instante, trilhas:{canal:{...}}, lendo, handle, nome}

function grvHoje() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function grvEstado(d) {
  const chave = recChave();
  if (!_grv || _grv.chave !== chave) {
    grvParar();
    _grv = { chave, dia: grvHoje(), canal: 0, instante: null, trilhas: {}, lendo: false, handle: null, stream: '' };
  }
  return _grv;
}

function grvJanela(dia) {
  const ini = new Date(`${dia}T00:00:00`);
  const fim = new Date(ini.getTime() + 86400e3);
  const agora = recAgoraNoGravador();
  return { ini, fim, ate: fim > agora ? agora : fim };
}

async function grvLerTrilhas(d) {
  const g = grvEstado(d);
  if (g.lendo) return;
  const alvo = recAvAlvo();
  const { ini, ate } = grvJanela(g.dia);
  const dia = g.dia;
  const canais = (d.canais || []).filter(c => c.ip).map(c => Number(c.canal));
  if (!g.canal && canais.length) g.canal = canais[0];
  g.lendo = true;
  for (const canal of canais) {
    if (_grv !== g || g.dia !== dia) return;            // trocou de gravador ou de dia
    if (g.trilhas[canal] && !g.trilhas[canal].erro) continue;
    g.trilhas[canal] = { carregando: true };
    try {
      const q = new URLSearchParams({ host: alvo.host, http_port: alvo.http_port, connector_id: alvo.connector_id,
        canal, inicio: recFmtHora(ini), fim: recFmtHora(ate) });
      const res = await api(`/api/nvr/driver/indice?${q}`);
      const j = await res.json().catch(() => ({}));
      if (_grv !== g || g.dia !== dia) return;
      g.trilhas[canal] = res.ok
        ? { segs: j.segmentos || [], ini: recFmtHora(ini), fim: recFmtHora(new Date(ini.getTime() + 86400e3)), ate: recFmtHora(ate) }
        : { erro: j.detail || `HTTP ${res.status}` };
    } catch (e) {
      if (_grv === g) g.trilhas[canal] = { erro: e.message };
    }
    if (_recSec === 'grav') recPintarApp();
  }
  if (_grv === g) g.lendo = false;
}

// Trilha clicavel: buracos entre segmentos, gravado e movimento; o futuro do
// dia de hoje fica neutro (nao e buraco: ainda nao aconteceu).
function grvTrilha(t, canal, g) {
  if (!t || t.carregando) return '<div class="grv-trilha carregando"></div>';
  if (t.erro) return `<div class="grv-trilha erro" title="${esc(t.erro)}">não li o índice: ${esc(t.erro)}</div>`;
  const ini = new Date(t.ini.replace(' ', 'T')).getTime();
  const pos = s => Math.max(0, Math.min(100, ((new Date(String(s).replace(' ', 'T')).getTime() - ini) / 864e5) * 100));
  const ate = pos(t.ate);
  const segs = (t.segs || []).map(s => [pos(s.inicio), pos(s.fim), s.tipo]).sort((a, b) => a[0] - b[0]);
  const blocos = [];
  let cursor = 0;
  segs.forEach(([a, b]) => { if (a - cursor > 0.3) blocos.push(['buraco', cursor, a]); cursor = Math.max(cursor, b); });
  if (ate - cursor > 0.3) blocos.push(['buraco', cursor, ate]);
  if (ate < 100) blocos.push(['futuro', ate, 100]);
  const ordem = { futuro: 0, grav: 1, mov: 2, buraco: 3 };
  segs.forEach(([a, b, tipo]) => blocos.push([tipo === 'movimento' ? 'mov' : 'grav', a, b]));
  blocos.sort((x, y) => ordem[x[0]] - ordem[y[0]]);
  let cursorAgora = '';
  if (g.instante && g.canal === canal) {
    const p = pos(recFmtHora(g.instante));
    if (p > 0 && p < 100) cursorAgora = `<i class="cursor" style="left:${p.toFixed(2)}%"></i>`;
  }
  return `<div class="grv-trilha" data-grv-trilha="${canal}" role="slider" tabindex="0"
      aria-label="Linha do tempo do canal ${canal}: clique para tocar daquele horário"
      aria-valuemin="0" aria-valuemax="1440" aria-valuenow="0">${blocos.map(([k, a, b]) =>
    `<i class="${k}" style="left:${a.toFixed(2)}%;width:${Math.max(0.25, b - a).toFixed(2)}%"></i>`).join('')}${cursorAgora}</div>`;
}

function grvResumoDia(d, g) {
  const lidas = Object.values(g.trilhas).filter(t => t.segs);
  const comBuraco = lidas.filter(t => {
    const ini = new Date(t.ini.replace(' ', 'T')).getTime(), ate = new Date(t.ate.replace(' ', 'T')).getTime();
    let cobre = 0;
    (t.segs || []).filter(s => s.tipo !== 'movimento').forEach(s => {
      cobre += Math.max(0, Math.min(ate, new Date(s.fim.replace(' ', 'T')).getTime()) - Math.max(ini, new Date(s.inicio.replace(' ', 'T')).getTime()));
    });
    return ate - ini > 0 && cobre / (ate - ini) < 0.98;
  }).length;
  const total = (d.canais || []).filter(c => c.ip).length;
  const lendo = lidas.length < total && g.lendo ? ` · lendo o índice ${lidas.length} de ${total}…` : '';
  return `${lidas.length} canal(is) lido(s)${comBuraco ? ` · ${comBuraco} com buraco no dia` : ''}${lendo}`;
}

function recSecGravacoes(d) {
  const g = grvEstado(d);
  if (!g.lendo && !Object.keys(g.trilhas).length) setTimeout(() => grvLerTrilhas(d), 0);
  const canais = (d.canais || []).filter(c => c.ip);
  const atual = canais.find(c => Number(c.canal) === g.canal) || canais[0];
  const nomeAtual = atual ? `${String(atual.canal).padStart(2, '0')} · ${atual.nome || atual.ip}` : '';
  const horaAtual = g.instante ? recFmtHora(g.instante) : '';

  return `<div class="bloco grv">
    <div class="bloco-cab">
      <div><h2>Gravações</h2><p>O índice do próprio gravador: o que está gravado, onde teve movimento e onde tem buraco. ${esc(grvResumoDia(d, g))}</p></div>
      <div class="bloco-dir">
        <label class="grv-dia">Dia <input type="date" data-grv-dia value="${esc(g.dia)}" max="${esc(grvHoje())}"></label>
      </div>
    </div>
    <div class="grv-player">
      <div class="grv-palco">
        <video id="grvVideo" autoplay muted playsinline></video>
        <div class="grv-aviso" id="grvAviso">${g.instante ? 'Pedindo o gravado ao gravador… pode levar até 40 s' : 'Clique numa linha do tempo para tocar daquele horário.'}</div>
        <div class="grv-id"><b>${esc(nomeAtual)}</b>${horaAtual ? ` · <span class="n">${esc(horaAtual)}</span>` : ''}</div>
      </div>
      <div class="grv-ctrl">
        <button type="button" class="acao" data-grv-pular="-10" ${g.instante ? '' : 'disabled'}>−10 s</button>
        <button type="button" class="acao" data-grv-pular="10" ${g.instante ? '' : 'disabled'}>+10 s</button>
        <button type="button" class="acao" data-grv-pular="-60" ${g.instante ? '' : 'disabled'}>−1 min</button>
        <span class="grv-espaco"></span>
        <button type="button" class="acao" data-grv-foto ${g.instante ? '' : 'disabled'}>Foto deste instante</button>
        <button type="button" class="acao" data-grv-mp4 ${g.instante ? '' : 'disabled'}>Baixar 2 min (MP4)</button>
        <button type="button" class="acao forte" data-grv-inv ${atual ? '' : 'disabled'}>Abrir na Investigação</button>
      </div>
      <div class="grv-status" id="grvStatus" role="status"></div>
    </div>
    <div class="grv-regua"><span></span><div><span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>24h</span></div></div>
    <div class="grv-linhas">${canais.map(c => {
      const n = Number(c.canal);
      return `<div class="grv-linha ${n === g.canal ? 'on' : ''}">
        <button type="button" class="grv-nome" data-grv-canal="${n}" title="${esc(c.nome || c.ip)}">${esc(String(n).padStart(2, '0'))} · ${esc(c.nome || c.ip)}</button>
        ${grvTrilha(g.trilhas[n], n, g)}</div>`;
    }).join('') || '<p class="rec-muted" style="padding:12px 15px">Nenhum canal com câmera.</p>'}</div>
    <div class="rec-legenda grv-leg"><span><i class="grav"></i>gravado</span><span><i class="mov"></i>movimento</span><span><i class="buraco"></i>buraco</span></div>
  </div>`;
}

function grvParar() {
  if (_grv?.handle) { try { _grv.handle.stop(); } catch (_) {} _grv.handle = null; }
  if (_grv) { _grv.videoEl = null; _grv.avisoOculto = false; }
}

// Toca a gravacao do canal a partir de `instante` (hora do gravador).
function grvTocar(canal, instante) {
  const g = _grv;
  if (!g) return;
  g.canal = canal;
  g.instante = instante;
  grvParar();
  recPintarApp();
  const video = document.getElementById('grvVideo');
  if (!video) return;
  g.videoEl = video;
  const alvo = recAvAlvo();
  const inicio = recFmtHora(instante);
  g.handle = mountLiveStream(video, {
    ip: alvo.host, user: 'admin', pass: '', subtype: 0,
    registrar: async () => {
      const res = await api('/api/nvr/driver/playback', {
        method: 'POST', body: JSON.stringify({ host: alvo.host, http_port: Number(alvo.http_port) || 80,
          connector_id: alvo.connector_id, canal, inicio }),
      });
      const r = await res?.json().catch(() => ({}));
      if (res?.status === 428) throw new Error('Este gravador nao tem senha guardada.');
      if (!res?.ok || !r?.stream_name) throw new Error(r?.detail || 'nao consegui pedir o gravado');
      return r.stream_name;
    },
    onStatus: texto => {
      // Procura o aviso a cada vez: a tela e redesenhada enquanto toca.
      const aviso = document.getElementById('grvAviso');
      if (!aviso) return;
      if (texto) { aviso.hidden = false; aviso.textContent = texto; } else aviso.hidden = true;
      if (g.handle) g.avisoOculto = !texto;
    },
  });
}

function grvStatus(texto, erro = false) {
  const el = document.getElementById('grvStatus');
  if (el) { el.textContent = texto || ''; el.classList.toggle('erro', !!erro); }
}

async function grvFoto() {
  const g = _grv;
  if (!g?.instante) return;
  const alvo = recAvAlvo();
  grvStatus('Tirando a foto do gravado…');
  try {
    const q = new URLSearchParams({ host: alvo.host, http_port: alvo.http_port, connector_id: alvo.connector_id,
      canal: g.canal, ts: recFmtHora(g.instante) });
    const res = await api(`/api/nvr/driver/quadro?${q}`);
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.detail || `HTTP ${res.status}`); }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = url;
    a.download = `${alvo.host}-canal${String(g.canal).padStart(2, '0')}-${recFmtHora(g.instante).replace(/[: ]/g, '')}.jpg`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    grvStatus('Foto baixada.');
  } catch (e) { grvStatus(`Não consegui a foto: ${e.message}`, true); }
}

async function grvMp4() {
  const g = _grv;
  if (!g?.instante) return;
  const alvo = recAvAlvo();
  const ini = g.instante, fim = new Date(ini.getTime() + 120e3);
  grvStatus('Baixando 2 min do gravador… leva uns 2 min (o gravador entrega em tempo real).');
  try {
    const res = await api('/api/nvr/driver/trecho/iniciar', { method: 'POST', body: JSON.stringify({
      host: alvo.host, http_port: Number(alvo.http_port) || 80, connector_id: alvo.connector_id,
      canal: g.canal, inicio: recFmtHora(ini), fim: recFmtHora(fim) }) });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
    for (;;) {
      await new Promise(r => setTimeout(r, 2000));
      if (_grv !== g) return;
      const st = await apiJson(`/api/nvr/driver/trecho/status?job_id=${encodeURIComponent(j.job_id)}`, { cacheTtl: 0 });
      if (!st) throw new Error('perdi o andamento do download');
      if (st.estado === 'pronto') {
        grvStatus('MP4 pronto, abrindo o download.');
        window.open(_invLinkArquivo(st.url), '_blank', 'noopener');
        return;
      }
      if (st.estado === 'erro') throw new Error(st.erro || 'o gravador nao entregou o trecho');
      grvStatus(`Baixando… ${st.decorrido || 0} de ~${st.dur || 120} s${st.baixado ? ` · ${(st.baixado / 1048576).toFixed(1)} MB` : ''}`);
    }
  } catch (e) { grvStatus(`Não consegui o MP4: ${e.message}`, true); }
}

function grvInvestigar(d) {
  const g = _grv;
  if (!g) return;
  const alvo = recAvAlvo();
  const centro = g.instante || new Date(`${g.dia}T12:00:00`);
  const ini = g.instante ? new Date(centro.getTime() - 30 * 60e3) : new Date(`${g.dia}T00:00:00`);
  const fim = g.instante ? new Date(centro.getTime() + 30 * 60e3) : new Date(`${g.dia}T23:59:59`);
  grvParar();
  invAbrirDoMapa({
    chaves: [`${alvo.host}|${Number(alvo.http_port) || 80}|${g.canal}`],
    ini, fim,
    rotulo: `do gravador ${d.equipamento?.modelo || alvo.host}, canal ${String(g.canal).padStart(2, '0')}`,
  });
}

function grvLigar(app, d) {
  if (_recSec !== 'grav') { grvParar(); return; }
  const g = grvEstado(d);
  // A tela inteira e redesenhada a cada trilha lida (e quando avisos/resumo
  // chegam). O <video> que esta tocando e devolvido ao lugar, em vez de
  // derrubar o gravado e pedir de novo ao gravador.
  const novo = app.querySelector('#grvVideo');
  if (g.handle && g.videoEl && novo && novo !== g.videoEl) {
    novo.replaceWith(g.videoEl);
    g.videoEl.play?.().catch(() => {});
    const aviso = app.querySelector('#grvAviso');
    if (aviso && g.avisoOculto) aviso.hidden = true;
  }
  app.querySelector('[data-grv-dia]')?.addEventListener('change', ev => {
    const v = ev.target.value;
    if (!v || v === g.dia) return;
    grvParar();
    g.dia = v; g.instante = null; g.trilhas = {}; g.lendo = false;
    recPintarApp();
  });
  app.querySelectorAll('[data-grv-canal]').forEach(b => b.addEventListener('click', () => {
    g.canal = Number(b.dataset.grvCanal);
    if (g.instante) grvTocar(g.canal, g.instante); else recPintarApp();
  }));
  app.querySelectorAll('[data-grv-trilha]').forEach(el => {
    const tocarEm = frac => {
      const ini = new Date(`${g.dia}T00:00:00`).getTime();
      const alvo = new Date(ini + Math.max(0, Math.min(1, frac)) * 864e5);
      const agora = recAgoraNoGravador();
      grvTocar(Number(el.dataset.grvTrilha), alvo > agora ? new Date(agora.getTime() - 30e3) : alvo);
    };
    el.addEventListener('click', ev => {
      const r = el.getBoundingClientRect();
      tocarEm((ev.clientX - r.left) / r.width);
    });
    el.addEventListener('keydown', ev => {
      if (ev.key !== 'Enter' && ev.key !== ' ') return;
      ev.preventDefault();
      tocarEm(g.instante && g.canal === Number(el.dataset.grvTrilha)
        ? (g.instante.getTime() - new Date(`${g.dia}T00:00:00`).getTime()) / 864e5 : 0.5);
    });
  });
  app.querySelectorAll('[data-grv-pular]').forEach(b => b.addEventListener('click', () => {
    if (g.instante) grvTocar(g.canal, new Date(g.instante.getTime() + Number(b.dataset.grvPular) * 1000));
  }));
  app.querySelector('[data-grv-foto]')?.addEventListener('click', () => grvFoto());
  app.querySelector('[data-grv-mp4]')?.addEventListener('click', () => grvMp4());
  app.querySelector('[data-grv-inv]')?.addEventListener('click', () => grvInvestigar(d));
}

recRegistrarSecao('grav', 'Gravações', recSecGravacoes, grvLigar, 'achados');
