// Modulo Alerta (botao de panico) -- tela da central + cadastro de pessoas.
//
// Backend: app/api/endpoints/alert.py. App do celular: frontend/alerta/.
// A tela ao vivo faz poll a cada 3s so enquanto esta visivel; o badge do menu
// e a sirene rodam num poll leve (/api/alert/summary) em qualquer tela, pra
// central nao perder alerta porque estava olhando outra coisa.

let _alertMap = null;
let _alertMarkers = null;
let _alertTrail = null;
let _alertIncidents = [];
let _alertSelectedId = '';
let _alertDetail = null;
let _alertScope = 'live';
let _alertTimer = null;
let _alertBound = false;
let _alertLoading = false;
let _alertFittedOnce = false;
let _alertKnownIds = new Set();
let _alertNearbyKey = '';
let _alertNearbyHtml = '';
let _alertCamHandle = null;
let _alertMembers = [];
let _alertMembersBound = false;
let _alertSummaryTimer = null;
let _alertSirenTimer = null;
let _alertAudio = null;
let _alertConnectors = null;
// Sites que o usuario ve: null = todos; lista = so estes (vem do backend).
let _alertMeusSites = null;
let _alertMemberSite = '';
let _alertSoPendencia = false;
let _alertEditPonto = null;   // centro das cameras do local (botao no editar)
let _alertPostos = null;      // postos online (vem do /summary)
let _alertSeguir = true;       // mapa acompanha a pessoa
let _alertUnits = null;        // camada com as lotacoes (tela calma)
let _alertHoje = { at: 0, lista: [] };

const ALERT_REFRESH_MS = 3000;
// Consulta leve do resumo (badge + som em qualquer tela). Era 10 s: um alerta
// que chegava logo depois de uma consulta so tocava ~10 s depois. O backend
// aguenta 1,5 s (uma consulta indexada, site do conector em cache).
const ALERT_SUMMARY_MS = 1500;
const ALERT_CIRCULO_MAX_M = 100;   // acima disso nao desenha o circulo de erro do GPS
const ALERT_CAMS_MAX = 8;          // cameras da lotacao mostradas de cara (as mais proximas)
let _alertCamsTodas = '';          // id do alerta em que pediram "ver todas"
const ALERT_ESCALATION_S = 60; // igual a ESCALATION_AFTER_S em alert_store.py
// O app so manda posicao quando ela muda (watchPosition): parada ou sem sinal
// parecem iguais daqui. Acima disso o mapa avisa que a posicao esta velha.
const ALERT_POS_VELHA_S = 120;
let _alertTickTimer = null;
let _alertAba = '';       // aba aberta no painel do atendimento
let _alertAbaInc = '';    // alerta em que a aba foi escolhida

const ALERT_STATUS = {
  new: { label: 'sem atendimento', pill: 'danger' },
  acknowledged: { label: 'assumido', pill: 'amber' },
  dispatched: { label: 'equipe a caminho', pill: 'amber' },
  closed: { label: 'encerrado', pill: 'success' },
  cancelled: { label: 'cancelado pela pessoa', pill: 'neutral' },
};

function alertOpen(inc) {
  return ['new', 'acknowledged', 'dispatched'].includes(inc?.status);
}

// Som do alerta: cada computador da central escolhe o seu (localStorage).
const ALERT_SOUND_DEFAULTS = {
  enabled: true,
  siren: 'sweep',          // sweep | fast | beep | bell | none
  voice: '',               // '' = automatica pt-BR; 'off' = sem voz; senao voiceURI
  rate: 1,
  volume: 0.8,
  repeat: 15,              // segundos entre repeticoes da voz
  textPanic: 'Atenção! {nome} precisa de ajuda. {local}',
  textDuress: 'Atenção! Coação! {nome} está sob coação. {local}',
};

function alertSoundCfg() {
  let cfg = {};
  try { cfg = JSON.parse(localStorage.getItem('alert_sound_cfg') || '{}') || {}; } catch {}
  try { if (localStorage.getItem('alert_sound') === '0' && cfg.enabled === undefined) cfg.enabled = false; } catch {}
  return { ...ALERT_SOUND_DEFAULTS, ...cfg };
}

function alertSaveSoundCfg(cfg) {
  try { localStorage.setItem('alert_sound_cfg', JSON.stringify(cfg)); localStorage.removeItem('alert_sound'); } catch {}
}

function alertSoundOn() {
  return alertSoundCfg().enabled !== false;
}

function alertDate(v) {
  const d = v ? new Date(v) : null;
  return d && !Number.isNaN(d.getTime()) ? d : null;
}

function alertClock(v) {
  const d = alertDate(v);
  return d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '-';
}

// Cronometro mm:ss (h:mm:ss passando de 1 h): quanto tempo a pessoa espera.
function alertTimer(v, ate) {
  const d = alertDate(v);
  if (!d) return '-';
  const fim = alertDate(ate)?.getTime() ?? Date.now();
  const s = Math.max(0, Math.floor((fim - d.getTime()) / 1000));
  const h = Math.floor(s / 3600);
  const mm = String(Math.floor((s % 3600) / 60)).padStart(h ? 2 : 1, '0');
  const ss = String(s % 60).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

// Atualiza todo [data-alert-tick] a cada segundo, so com a tela visivel.
function alertTickStart() {
  if (_alertTickTimer) return;
  _alertTickTimer = setInterval(() => {
    if (!alertLiveVisible()) { clearInterval(_alertTickTimer); _alertTickTimer = null; return; }
    document.querySelectorAll('#viewAlertLive [data-alert-tick]').forEach((el) => {
      el.textContent = alertTimer(el.dataset.alertTick);
    });
    document.querySelectorAll('#viewAlertLive [data-alert-escala]').forEach((el) => {
      const falta = ALERT_ESCALATION_S - Math.floor((Date.now() - (alertDate(el.dataset.alertEscala)?.getTime() || 0)) / 1000);
      el.textContent = falta > 0 ? `Telegram do site avisa em ${alertTimer(new Date(Date.now() - falta * 1000).toISOString())}` : 'Aviso enviado ao Telegram do site';
    });
  }, 1000);
}

function alertAgo(v) {
  const d = alertDate(v);
  if (!d) return '-';
  const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h${String(m % 60).padStart(2, '0')}` : d.toLocaleDateString('pt-BR');
}

function alertCpf(v) {
  const d = String(v || '').replace(/\D/g, '');
  return d.length === 11 ? `${d.slice(0, 3)}.${d.slice(3, 6)}.${d.slice(6, 9)}-${d.slice(9)}` : d;
}

function alertPhone(v) {
  const d = String(v || '').replace(/\D/g, '');
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return String(v || '');
}

// Ponto do alerta no mapa: GPS do celular; sem GPS, a lotacao cadastrada.
function alertPoint(inc) {
  if (inc?.last_lat != null && inc?.last_lon != null) return { lat: inc.last_lat, lon: inc.last_lon, gps: true, acc: inc.last_accuracy };
  const m = inc?.member || {};
  if (m.unit_lat != null && m.unit_lon != null) return { lat: m.unit_lat, lon: m.unit_lon, gps: false };
  return null;
}

function alertStatusPill(inc) {
  if (inc.arrived_at && alertOpen(inc)) return '<span class="pill success">equipe no local</span>';
  const st = ALERT_STATUS[inc.status] || { label: inc.status, pill: 'neutral' };
  return `<span class="pill ${st.pill}">${esc(st.label)}</span>`;
}

function alertKindPill(inc) {
  return inc.kind === 'duress'
    ? '<span class="pill alert-duress-pill">COACAO</span>'
    : '<span class="pill danger">panico</span>';
}

async function alertLoadConnectors() {
  if (_alertConnectors) return _alertConnectors;
  try {
    const data = await alertApiJson('/api/connectors');
    _alertConnectors = (data.connectors || [])
      .map((c) => ({ id: String(c.id || c.connector_id || ''), name: String(c.name || c.site || c.id || '') }))
      .filter((c) => c.id)
      .sort((a, b) => a.name.localeCompare(b.name, 'pt-BR'));
  } catch {
    _alertConnectors = [];
  }
  return _alertConnectors;
}

function alertConnectorName(id) {
  if (!id) return '';
  return (_alertConnectors || []).find((c) => c.id === id)?.name || 'local monitorado';
}

function alertRenderScope(id, sites) {
  const box = document.getElementById(id);
  if (!box) return;
  const lista = Array.isArray(sites) ? sites : null;
  box.hidden = false;
  box.classList.toggle('is-restrito', !!lista);
  box.innerHTML = lista
    ? `<i data-lucide="map-pin"></i><span>${lista.length === 1 ? 'Seu site' : 'Seus sites'}: <b>${lista.map(esc).join('</b> · <b>')}</b></span>`
    : '<i data-lucide="globe"></i><span>Todos os sites do cliente</span>';
  if (window.lucide) lucide.createIcons();
}

function alertSiteTag(site) {
  return site ? `<span class="alert-site-tag">${esc(site)}</span>` : '';
}

async function alertApiJson(path, opts = {}) {
  const res = await api(path, opts);
  if (!res) throw new Error('Sessao expirada.');
  return jsonOrReadableError(res);
}

// ---------------------------------------------------------------- sirene

function alertAudioCtx() {
  if (!_alertAudio) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    _alertAudio = new Ctx();
  }
  if (_alertAudio.state === 'suspended') _alertAudio.resume().catch(() => {});
  return _alertAudio;
}

// O navegador so libera audio depois de um clique na pagina.
document.addEventListener('click', () => alertAudioCtx(), { passive: true, capture: true });

function alertTone(ctx, { type = 'sine', from = 880, to = null, start = 0, dur = 0.3, gain = 0.18 }) {
  const t = ctx.currentTime + start;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.setValueAtTime(from, t);
  if (to) osc.frequency.linearRampToValueAtTime(to, t + dur);
  g.gain.setValueAtTime(0.0001, t);
  g.gain.exponentialRampToValueAtTime(Math.max(gain, 0.0002), t + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(t);
  osc.stop(t + dur + 0.02);
}

const ALERT_SIRENS = {
  sweep: { label: 'Sirene (sobe e desce)', play: (c, v) => {
    alertTone(c, { type: 'square', from: 880, to: 1320, dur: 0.35, gain: 0.22 * v });
    alertTone(c, { type: 'square', from: 1320, to: 880, start: 0.35, dur: 0.35, gain: 0.22 * v });
  } },
  fast: { label: 'Alarme rapido', play: (c, v) => {
    [0, 0.2, 0.4].forEach((s) => alertTone(c, { type: 'square', from: 1050, start: s, dur: 0.14, gain: 0.22 * v }));
  } },
  beep: { label: 'Bipe', play: (c, v) => alertTone(c, { type: 'sine', from: 988, dur: 0.3, gain: 0.3 * v }) },
  bell: { label: 'Campainha', play: (c, v) => {
    alertTone(c, { type: 'triangle', from: 660, dur: 1.1, gain: 0.35 * v });
    alertTone(c, { type: 'sine', from: 1320, dur: 0.8, gain: 0.12 * v });
  } },
  none: { label: 'Sem sirene (so a voz)', play: () => {} },
};

function alertBeep(sirenKey) {
  const ctx = alertAudioCtx();
  if (!ctx || ctx.state !== 'running') return;
  const cfg = alertSoundCfg();
  (ALERT_SIRENS[sirenKey || cfg.siren] || ALERT_SIRENS.sweep).play(ctx, Math.max(0.05, Number(cfg.volume) || 0.8));
}

// ---- voz: "Atencao! Fulano precisa de ajuda." (sintese de voz do navegador)

let _alertNewList = [];              // alertas sem atendimento: sirene + voz repetindo
const _alertSpokenAt = new Map();    // id -> ultima vez que a voz falou dele
const _alertDuressSpoken = new Set(); // coacao: anuncia uma vez quando aparece
const ALERT_VOICE_REPEAT_MS = 15000;

function alertSpeechName(name) {
  // Nome em CAIXA ALTA a voz soletra; em "Titulo" ela le normal.
  return String(name || 'uma pessoa').toLowerCase().replace(/(^|\s)(\p{L})/gu, (m, sp, c) => sp + c.toUpperCase());
}

function alertVoices() {
  if (!('speechSynthesis' in window)) return [];
  const vs = speechSynthesis.getVoices() || [];
  const pt = vs.filter((v) => /^pt/i.test(v.lang));
  return pt.length ? pt : vs;
}

function alertVoice() {
  if (!('speechSynthesis' in window)) return null;
  const want = alertSoundCfg().voice;
  const vs = speechSynthesis.getVoices() || [];
  if (want && want !== 'off') {
    const chosen = vs.find((v) => v.voiceURI === want);
    if (chosen) return chosen;
  }
  return vs.find((v) => /pt-BR/i.test(v.lang) && /natural|online|francisca|thalita|antonio|google/i.test(v.name))
    || vs.find((v) => /pt-BR/i.test(v.lang))
    || vs.find((v) => /^pt/i.test(v.lang))
    || null;
}
if ('speechSynthesis' in window) speechSynthesis.onvoiceschanged = () => alertFillVoiceSelect();

function alertSpeak(text, force = false) {
  const cfg = alertSoundCfg();
  if (!('speechSynthesis' in window) || (!force && !cfg.enabled) || cfg.voice === 'off') return false;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'pt-BR';
  const v = alertVoice();
  if (v) u.voice = v;
  u.rate = Number(cfg.rate) || 1;
  u.volume = Math.min(1, Math.max(0.05, Number(cfg.volume) || 0.8));
  speechSynthesis.speak(u);
  return true;
}

function alertSpeechText(inc, cfg = alertSoundCfg()) {
  const tpl = inc.kind === 'duress' ? cfg.textDuress : cfg.textPanic;
  const unit = String(inc.member?.unit_name || '').trim();
  return String(tpl || '')
    .replace(/\{nome\}/gi, alertSpeechName(inc.member?.full_name))
    .replace(/\{local\}/gi, unit ? `${unit}.` : '')
    .replace(/\s+/g, ' ')
    .trim();
}

// Recebe a lista atual de alertas (tela ao vivo ou poll global) e decide o som.
function alertSetIncidentsForSound(incidents) {
  const list = incidents || [];
  _alertNewList = list.filter((i) => i.status === 'new');
  _alertNewList.forEach(alertNotify);
  list.filter((i) => i.kind === 'duress' && alertOpen(i)).forEach(alertNotify);
  const now = Date.now();
  _alertNewList.forEach((i) => {
    // Alerta novo: 2 toques de sirene e ja fala o nome.
    if (!_alertSpokenAt.has(i.id)) _alertSpokenAt.set(i.id, now - ALERT_VOICE_REPEAT_MS + 3000);
  });
  list.filter((i) => i.kind === 'duress' && alertOpen(i) && !_alertDuressSpoken.has(i.id)).forEach((i) => {
    _alertDuressSpoken.add(i.id);
    _alertSpokenAt.set(i.id, now);
    alertBeep();
    alertSpeak(alertSpeechText(i));
  });
  alertSetSiren(_alertNewList.length > 0);
  alertRenderSoundUnlock();
}

function alertSirenTick() {
  if ('speechSynthesis' in window && speechSynthesis.speaking) return; // nao atropela a voz
  const now = Date.now();
  const repeatMs = Math.max(5, Number(alertSoundCfg().repeat) || 15) * 1000;
  const due = _alertNewList.find((i) => now - (_alertSpokenAt.get(i.id) || 0) >= repeatMs);
  if (due && alertSoundOn()) {
    _alertSpokenAt.set(due.id, now);
    if (alertSpeak(alertSpeechText(due))) return;
  }
  alertBeep();
}

function alertSetSiren(on) {
  const want = on && alertSoundOn();
  if (want && !_alertSirenTimer) {
    _alertSirenTimer = true; // quem bate o compasso e o relogio de fundo (alertStartClock)
    alertSirenTick();
  } else if (!want) {
    _alertSirenTimer = null;
  }
}

// ---- aviso do Windows (Notification): aparece com o SightOps minimizado ou em outra aba
const _alertNotified = new Set();

function alertNotify(inc) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  const key = `${inc.id}:${inc.kind}`;
  if (_alertNotified.has(key)) return;
  _alertNotified.add(key);
  if (!document.hidden && _currentView === 'alert-live') return; // ja esta olhando
  const m = inc.member || {};
  const duress = inc.kind === 'duress';
  try {
    const n = new Notification(duress ? 'COACAO — SightOps Alerta' : 'ALERTA DE PANICO — SightOps', {
      body: `${alertSpeechName(m.full_name)} ${duress ? 'esta sob coacao' : 'precisa de ajuda'}${m.unit_name ? ` · ${m.unit_name}` : ''}`,
      tag: key,
      requireInteraction: true,
    });
    n.onclick = () => { window.focus(); navigateTo('alert-live'); n.close(); };
  } catch { /* navegador sem suporte */ }
}

function alertNotifyStatusText() {
  if (!('Notification' in window)) return 'Este navegador nao suporta avisos do Windows.';
  if (Notification.permission === 'granted') return 'Avisos do Windows ATIVOS neste computador.';
  if (Notification.permission === 'denied') return 'Avisos bloqueados. Libere no cadeado ao lado do endereco do site.';
  return 'Avisos do Windows desligados.';
}

async function alertAskNotifyPermission() {
  if (!('Notification' in window)) return;
  if (Notification.permission === 'default') {
    try { await Notification.requestPermission(); } catch {}
  }
  setText('alertNotifyStatus', alertNotifyStatusText());
}

// ---- som bloqueado pelo navegador: faixa "clique para ativar"

function alertSoundBlocked() {
  const noGesture = navigator.userActivation ? !navigator.userActivation.hasBeenActive : false;
  return noGesture || !_alertAudio || _alertAudio.state !== 'running';
}

function alertRenderSoundUnlock() {
  let el = document.getElementById('alertSoundUnlock');
  const show = alertSoundOn() && alertSoundBlocked() && (_currentView === 'alert-live' || _alertNewList.length > 0);
  if (!show) { if (el) el.hidden = true; return; }
  if (!el) {
    el = document.createElement('button');
    el.id = 'alertSoundUnlock';
    el.type = 'button';
    el.className = 'alert-sound-unlock';
    el.innerHTML = '<i data-lucide="volume-x"></i><span>O navegador bloqueou o som dos alertas. <b>Clique aqui para ativar.</b></span>';
    el.addEventListener('click', () => {
      alertAudioCtx();
      alertSpeak('Som dos alertas ativado.');
      setTimeout(alertRenderSoundUnlock, 400);
    });
    document.body.appendChild(el);
    if (window.lucide) lucide.createIcons();
  }
  el.hidden = false;
}

function alertTestSound(kind = 'panic', cfg = alertSoundCfg()) {
  alertAudioCtx();
  const fake = { kind, member: { full_name: _currentUser?.full_name || 'Maria da Silva', unit_name: 'Escola Presidente Dutra' } };
  const saved = alertSoundCfg();
  alertSaveSoundCfg(cfg); // testa exatamente o que esta na tela, mesmo antes de salvar
  alertBeep(cfg.siren);
  setTimeout(() => {
    if ('speechSynthesis' in window) speechSynthesis.cancel();
    const ok = cfg.voice === 'off' || alertSpeak(alertSpeechText(fake, cfg), true);
    alertSaveSoundCfg(saved);
    if (!ok) showToast('Este navegador nao tem voz. Use Chrome ou Edge atualizados.', true);
  }, cfg.siren === 'none' ? 0 : 900);
  setTimeout(alertRenderSoundUnlock, 500);
}

// ---- janela "Som do alerta"

function alertFillVoiceSelect() {
  const sel = document.getElementById('alertSoundVoice');
  if (!sel) return;
  const cur = sel.dataset.value ?? alertSoundCfg().voice;
  const opts = ['<option value="">Automatica (portugues)</option>', '<option value="off">Sem voz (so sirene)</option>']
    .concat(alertVoices().map((v) => `<option value="${esc(v.voiceURI)}">${esc(v.name)} (${esc(v.lang)})</option>`));
  sel.innerHTML = opts.join('');
  sel.value = [...sel.options].some((o) => o.value === cur) ? cur : '';
}

function alertSoundFormCfg() {
  const g = (id) => document.getElementById(id);
  return {
    enabled: g('alertSoundEnabled').checked,
    siren: g('alertSoundSiren').value,
    voice: g('alertSoundVoice').value,
    rate: Number(g('alertSoundRate').value),
    volume: Number(g('alertSoundVolume').value) / 100,
    repeat: Number(g('alertSoundRepeat').value),
    textPanic: g('alertSoundTextPanic').value.trim() || ALERT_SOUND_DEFAULTS.textPanic,
    textDuress: g('alertSoundTextDuress').value.trim() || ALERT_SOUND_DEFAULTS.textDuress,
  };
}

function alertOpenSoundModal() {
  const cfg = alertSoundCfg();
  const g = (id) => document.getElementById(id);
  g('alertSoundEnabled').checked = cfg.enabled !== false;
  g('alertSoundSiren').innerHTML = Object.entries(ALERT_SIRENS)
    .map(([k, s]) => `<option value="${k}">${esc(s.label)}</option>`).join('');
  g('alertSoundSiren').value = cfg.siren;
  g('alertSoundVoice').dataset.value = cfg.voice;
  alertFillVoiceSelect();
  delete g('alertSoundVoice').dataset.value;
  g('alertSoundRate').value = String(cfg.rate);
  g('alertSoundVolume').value = String(Math.round((Number(cfg.volume) || 0.8) * 100));
  g('alertSoundRepeat').value = String(cfg.repeat);
  g('alertSoundTextPanic').value = cfg.textPanic;
  g('alertSoundTextDuress').value = cfg.textDuress;
  setText('alertNotifyStatus', alertNotifyStatusText());
  g('modalAlertSound').classList.remove('hidden');
  alertAudioCtx();
}

function alertBindSoundModal() {
  const g = (id) => document.getElementById(id);
  g('btnAlertNotifyEnable')?.addEventListener('click', alertAskNotifyPermission);
  g('btnAlertSoundTestPanic')?.addEventListener('click', () => alertTestSound('panic', alertSoundFormCfg()));
  g('btnAlertSoundTestDuress')?.addEventListener('click', () => alertTestSound('duress', alertSoundFormCfg()));
  g('btnAlertSoundDefaults')?.addEventListener('click', () => {
    alertSaveSoundCfg({ ...ALERT_SOUND_DEFAULTS, enabled: g('alertSoundEnabled').checked });
    alertOpenSoundModal();
  });
  g('btnAlertSoundSave')?.addEventListener('click', () => {
    alertSaveSoundCfg(alertSoundFormCfg());
    if (!alertSoundOn() && 'speechSynthesis' in window) speechSynthesis.cancel();
    alertCloseModal('modalAlertSound');
    alertRenderSoundButton();
    alertSetSiren(false);
    alertSetIncidentsForSound(_alertIncidents);
    showToast('Som do alerta salvo neste computador.');
  });
}

function alertRenderSoundButton() {
  const btn = document.getElementById('btnAlertSound');
  if (!btn) return;
  const on = alertSoundOn();
  btn.querySelector('span').textContent = on ? 'Som do alerta' : 'Som desligado';
  btn.classList.toggle('alert-sound-off', !on);
}

// ---------------------------------------------------------------- badge global

async function alertPollSummary() {
  const btn = document.querySelector('.nav-item[data-view="alert-live"]');
  // Depois de F5 a sessao segue pelo cookie e _token fica null; por isso o
  // criterio e ter usuario carregado, nao ter token em memoria.
  if (!_currentUser || !btn || btn.classList.contains('nav-item-hidden')) return;
  try {
    const res = await api('/api/alert/summary', { skipLogout: true });
    if (!res || !res.ok) return;
    const s = await res.json();
    if (typeof s.postos_online === 'number') { _alertPostos = s.postos_online; if (alertLiveVisible()) alertRenderChips(); }
    const badge = document.getElementById('alertNavBadge');
    if (badge) {
      badge.hidden = !s.open;
      badge.textContent = String(s.open || 0);
      badge.classList.toggle('alert-nav-badge-hot', (s.new || 0) > 0);
    }
    // Fora da tela ao vivo o som depende deste poll; dentro dela, do refresh.
    if (_currentView !== 'alert-live') {
      if ((s.new || 0) > 0 || (s.duress || 0) > 0) {
        const live = await api('/api/alert/incidents?scope=live&limit=50', { skipLogout: true });
        const data = live && live.ok ? await live.json() : { incidents: [] };
        alertSetIncidentsForSound(data.incidents || []);
      } else {
        alertSetIncidentsForSound([]);
      }
    }
    if (s.latest_new_id && !_alertKnownIds.has(s.latest_new_id)) {
      if (_currentView === 'alert-live') {
        // Na Central ao vivo: nao espera o refresh de 3 s, atualiza (e toca) ja.
        alertRefresh(true);
      } else {
        _alertKnownIds.add(s.latest_new_id);
        showToast('ALERTA DE PANICO recebido. Abra a Central ao vivo.', true);
      }
    }
  } catch { /* silencioso: e so o badge */ }
}

// Relogio unico do alerta: sirene a cada 1,5s e consulta ao servidor a cada
// ~10s. Roda num Web Worker porque o Chrome segura setInterval de aba em
// segundo plano (ate 1x por minuto) -- e a central costuma deixar o SightOps
// minimizado ou atras de outra aba.
function alertStartClock() {
  if (_alertSummaryTimer) return;
  let n = 0;
  const everyPoll = Math.max(1, Math.round(ALERT_SUMMARY_MS / 1500));
  const onTick = () => {
    n += 1;
    if (_alertSirenTimer) alertSirenTick();
    if (n % everyPoll === 0) alertPollSummary();
  };
  try {
    const src = 'setInterval(function(){postMessage(1)},1500)';
    const w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
    w.onmessage = onTick;
    // Worker bloqueado (CSP) falha por evento, nao por excecao: cai pro setInterval.
    w.onerror = () => { try { w.terminate(); } catch {} _alertSummaryTimer = setInterval(onTick, 1500); };
    _alertSummaryTimer = w;
  } catch {
    _alertSummaryTimer = setInterval(onTick, 1500);
  }
  setTimeout(alertPollSummary, 3000);
}
alertStartClock();

// ---------------------------------------------------------------- tela ao vivo

function alertLiveVisible() {
  return !document.getElementById('viewAlertLive')?.classList.contains('hidden');
}

function alertInitMap() {
  if (_alertMap || typeof L === 'undefined') return;
  _alertMap = L.map('alertLiveMap', { zoomControl: true }).setView([-10.186, -36.825], 14);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', subdomains: 'abc', maxZoom: 19,
  }).addTo(_alertMap);
  _alertMarkers = L.layerGroup().addTo(_alertMap);
  _alertTrail = L.layerGroup().addTo(_alertMap);
  _alertUnits = L.layerGroup().addTo(_alertMap);
  // O mapa estica com a coluna: muda de altura quando a faixa ou as cameras
  // aparecem, sem a janela mudar. Sem isso o Leaflet deixa faixa cinza.
  if (window.ResizeObserver) new ResizeObserver(() => _alertMap?.invalidateSize()).observe(document.getElementById('alertLiveMap'));
}

function alertBind() {
  if (_alertBound) return;
  _alertBound = true;
  document.getElementById('btnAlertRefresh')?.addEventListener('click', () => alertRefresh(true));
  document.getElementById('btnAlertSound')?.addEventListener('click', alertOpenSoundModal);
  document.getElementById('btnAlertSoundTest')?.addEventListener('click', () => alertTestSound('panic'));
  alertBindSoundModal();
  document.getElementById('btnAlertHistory')?.addEventListener('click', () => {
    _alertScope = _alertScope === 'live' ? 'history' : 'live';
    const btn = document.getElementById('btnAlertHistory');
    btn.querySelector('span').textContent = _alertScope === 'live' ? 'Historico' : 'Voltar ao vivo';
    setText('alertListTitle', _alertScope === 'live' ? 'Alertas' : 'Historico');
    setText('alertListSub', _alertScope === 'live' ? 'Abertos e encerrados recentes.' : 'Todos os alertas, mais recentes primeiro.');
    _alertFittedOnce = false;
    alertRefresh(true);
  });
  document.getElementById('alertLiveList')?.addEventListener('click', (ev) => {
    const card = ev.target.closest('[data-alert-id]');
    if (card) alertSelect(card.dataset.alertId, true);
  });
  document.getElementById('alertLiveDetail')?.addEventListener('click', alertDetailClick);
  document.getElementById('alertLiveCams')?.addEventListener('click', (ev) => {
    const cam = ev.target.closest('[data-alert-cam]');
    if (cam) { alertOpenCamera(cam.dataset); return; }
    const mais = ev.target.closest('[data-cams]')?.dataset.cams;
    if (mais && _alertDetail) {
      _alertCamsTodas = mais === 'todas' ? _alertDetail.id : '';
      _alertNearbyKey = '';
      alertLoadNearby();
    }
  });
  document.getElementById('alertLiveDetail')?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && ev.target.id === 'alertNoteInput') { ev.preventDefault(); alertEnviarNota(); }
  });
  document.getElementById('alertBanner')?.addEventListener('click', async (ev) => {
    const ack = ev.target.closest('[data-banner-ack]');
    if (ack) {
      ack.disabled = true;
      alertSelect(ack.dataset.bannerAck, true);
      await alertAction('acknowledge', '', ack.dataset.bannerAck);
      return;
    }
    const ver = ev.target.closest('[data-banner-ver]');
    if (ver) alertSelect(ver.dataset.bannerVer, true);
  });
  document.getElementById('btnAlertProtocolos')?.addEventListener('click', () => alertOpenProtocolos(''));
  document.getElementById('btnAlertFull')?.addEventListener('click', alertTelaCheia);
  document.getElementById('alertChips')?.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-chip="som"]')) alertOpenSoundModal();
  });
  document.getElementById('alertMapTools')?.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-map="seguir"]')) { _alertSeguir = !_alertSeguir; alertRenderMapaInfo(); if (_alertSeguir) alertCentralizar(); }
  });
  document.getElementById('alertProtSite')?.addEventListener('change', alertProtocoloMostrarSite);
  document.getElementById('btnAlertProtSave')?.addEventListener('click', alertSalvarProtocolo);
  document.getElementById('alertCloseQuick')?.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-close-text]');
    if (!b) return;
    const ta = document.getElementById('alertCloseNote');
    ta.value = ta.value.trim() ? `${ta.value.trim()} ${b.dataset.closeText}` : b.dataset.closeText;
    ta.focus();
  });
  document.getElementById('btnAlertCloseConfirm')?.addEventListener('click', alertConfirmClose);
  alertBindModalClose();
}

let _alertModalCloseBound = false;
function alertBindModalClose() {
  if (_alertModalCloseBound) return;
  _alertModalCloseBound = true;
  document.querySelectorAll('[data-alert-close]').forEach((btn) => {
    btn.addEventListener('click', () => alertCloseModal(btn.dataset.alertClose));
  });
}

function alertCloseModal(id) {
  document.getElementById(id)?.classList.add('hidden');
  if (id === 'modalAlertCamera' && _alertCamHandle) { _alertCamHandle.stop(); _alertCamHandle = null; }
}

async function loadAlertLive() {
  alertBind();
  const btnProt = document.getElementById('btnAlertProtocolos');
  if (btnProt) btnProt.hidden = !alertPodeEditarPassos();
  alertInitMap();
  alertAudioCtx(); // abrir a tela e um clique: aproveita pra liberar o audio
  alertRenderSoundButton();
  setTimeout(alertRenderSoundUnlock, 300);
  setTimeout(() => _alertMap?.invalidateSize(), 150);
  alertPollSummary();
  await alertRefresh(true);
  alertTickStart();
  if (!_alertTimer) {
    _alertTimer = setInterval(() => {
      if (!alertLiveVisible()) { clearInterval(_alertTimer); _alertTimer = null; return; }
      alertRefresh(false);
    }, ALERT_REFRESH_MS);
  }
}

async function alertRefresh(force) {
  if (_alertLoading && !force) return;
  _alertLoading = true;
  try {
    const data = await alertApiJson(`/api/alert/incidents?scope=${_alertScope}&limit=200`);
    const incidents = data.incidents || [];
    const fresh = incidents.filter((i) => i.status === 'new' && !_alertKnownIds.has(i.id));
    incidents.forEach((i) => _alertKnownIds.add(i.id));
    _alertIncidents = incidents;
    _alertMeusSites = Array.isArray(data.meus_sites) ? data.meus_sites : null;
    alertRenderScope('alertScopeLive', _alertMeusSites);
    setText('alertLiveState', `atualizado ${alertClock(new Date().toISOString())}`);
    if (fresh.length) {
      // Alerta novo chegou: seleciona e centraliza nele.
      _alertSelectedId = fresh[0].id;
      _alertFittedOnce = false;
    } else if (!_alertSelectedId || !incidents.some((i) => i.id === _alertSelectedId)) {
      _alertSelectedId = (incidents.find(alertOpen) || {}).id || '';
    }
    alertRenderKpis();
    alertRenderChips();
    alertCarregarHoje();
    alertRenderBanner();
    alertRenderList();
    alertRenderMarkers();
    alertSetIncidentsForSound(incidents);
    await alertLoadDetail();
  } catch (err) {
    setText('alertLiveState', 'falha ao atualizar');
    if (force) showToast(err.message || 'Falha ao carregar alertas.', true);
  } finally {
    _alertLoading = false;
  }
}

function alertRenderKpis() {
  const open = _alertIncidents.filter(alertOpen);
  setText('alertKpiNew', open.filter((i) => i.status === 'new').length);
  setText('alertKpiOpen', open.filter((i) => i.status !== 'new').length);
  setText('alertKpiDuress', open.filter((i) => i.kind === 'duress').length);
  setText('alertKpiClosed', _alertIncidents.filter((i) => !alertOpen(i)).length);
  setText('alertKpiClosedSub', _alertScope === 'live' ? 'ultimos 30 minutos' : 'no historico carregado');
}

// ---------------------------------------------------------------- cabecalho
// Uma descricao so do som deste posto (chip e tela calma falam igual).
function alertSomDescricao() {
  const cfg = alertSoundCfg();
  const sirene = cfg.siren && cfg.siren !== 'none';
  const voz = cfg.voice !== 'off';
  if (sirene && voz) return 'Sirene e voz';
  if (sirene) return 'So sirene';
  if (voz) return 'So voz';
  return 'Sem sirene nem voz';
}

function alertRenderChips() {
  const box = document.getElementById('alertChipsMais');
  if (!box) return;
  const somOn = alertSoundOn();
  const aviso = !('Notification' in window) ? '' : (Notification.permission === 'granted' ? 'notificacao do computador ativa' : 'notificacao do computador desligada');
  const cfg = alertSoundCfg();
  const somTxt = somOn ? `Som: ${alertSomDescricao().toLowerCase()}` : 'Som desligado';
  const postos = typeof _alertPostos === 'number'
    ? `<span class="alert-chip is-ok"><span class="alert-chip-dot"></span>Voce esta de plantao · ${_alertPostos} posto${_alertPostos === 1 ? '' : 's'} online</span>` : '';
  box.innerHTML = `${postos}<button type="button" class="alert-chip${somOn ? '' : ' is-warn'}" data-chip="som"><i data-lucide="${somOn ? 'volume-2' : 'volume-x'}"></i>${esc(somTxt)}${aviso ? ` · ${esc(aviso)}` : ''}</button>`;
  if (window.lucide) lucide.createIcons();
}

// Alertas de hoje (contador da fila e tela calma). No maximo 1 busca por minuto.
async function alertCarregarHoje() {
  if (Date.now() - _alertHoje.at < 60000) { alertRenderContadores(); return; }
  _alertHoje.at = Date.now();
  try {
    const hist = await alertApiJson('/api/alert/incidents?scope=history&limit=100');
    const ini = new Date(); ini.setHours(0, 0, 0, 0);
    _alertHoje.lista = (hist.incidents || []).filter((i) => (alertDate(i.opened_at)?.getTime() || 0) >= ini.getTime());
  } catch { /* contador fica como estava */ }
  alertRenderContadores();
  alertRenderList();  // "Encerrados hoje" da fila sai desta lista
}

function alertRenderContadores() {
  const abertos = _alertIncidents.filter(alertOpen);
  const novos = abertos.filter((i) => i.status === 'new').length;
  const atend = abertos.length - novos;
  const n = document.getElementById('alertCntNovo');
  const a = document.getElementById('alertCntAtend');
  if (n) { n.querySelector('b').textContent = novos; n.classList.toggle('is-hot', novos > 0); }
  if (a) { a.querySelector('b').textContent = atend; a.classList.toggle('is-atend', atend > 0); }
  const dia = document.getElementById('alertFilaDia');
  if (dia) {
    const hoje = _alertHoje.lista || [];
    // Media do disparo ate alguem assumir, so de quem foi assumido hoje.
    const esperas = hoje
      .map((i) => (alertDate(i.acknowledged_at)?.getTime() || 0) - (alertDate(i.opened_at)?.getTime() || 0))
      .filter((ms) => ms > 0);
    const media = esperas.length
      ? alertTimer(new Date(0).toISOString(), new Date(esperas.reduce((s, x) => s + x, 0) / esperas.length).toISOString())
      : '-';
    dia.innerHTML = `<div><b>${hoje.length}</b><span>alerta${hoje.length === 1 ? '' : 's'} hoje</span></div>
      <div><b>${esc(media)}</b><span>media para assumir</span></div>`;
  }
  const foot = document.getElementById('alertFilaFoot');
  if (foot) {
    foot.hidden = !_alertMeusSites;
    foot.textContent = 'Alertas dos outros sites nao aparecem para voce — nem som, nem contador.';
  }
}

function alertTelaCheia() {
  const el = document.getElementById('viewAlertLive');
  if (!el) return;
  if (document.fullscreenElement) { document.exitFullscreen?.(); return; }
  el.requestFullscreen?.().then(() => setTimeout(() => _alertMap?.invalidateSize(), 300)).catch(() => showToast('O navegador nao liberou a tela cheia.', true));
}
document.addEventListener('fullscreenchange', () => setTimeout(() => _alertMap?.invalidateSize(), 300));

// ---------------------------------------------------------------- mapa
function alertCentralizar() {
  const p = alertPoint(_alertDetail);
  if (p && _alertMap) _alertMap.setView([p.lat, p.lon], Math.max(_alertMap.getZoom(), 17), { animate: true });
}

function alertDistM(a, b) {
  const R = 6371000, r = (x) => (x * Math.PI) / 180;
  const dLat = r(b[0] - a[0]), dLon = r(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(r(a[0])) * Math.cos(r(b[0])) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// Chips e ferramentas sobre o mapa. Com alerta: GPS, bateria, quanto andou.
// Sem alerta: as lotacoes das pessoas (onde um pedido pode nascer).
function alertRenderMapaInfo() {
  const chips = document.getElementById('alertMapChips');
  const tools = document.getElementById('alertMapTools');
  const legenda = document.getElementById('alertMapLegend');
  if (!chips || !tools) return;
  const inc = _alertDetail;
  if (inc) {
    _alertUnits?.clearLayers();
    _alertLotKey = '';
    const p = alertPoint(inc);
    const pos = inc.positions || [];
    let andou = 0;
    if (pos.length > 1) andou = alertDistM([pos[0].lat, pos[0].lon], [pos[pos.length - 1].lat, pos[pos.length - 1].lon]);
    const itens = [];
    const idadeS = inc.last_position_at ? (Date.now() - (alertDate(inc.last_position_at)?.getTime() || Date.now())) / 1000 : 0;
    if (p && p.gps && alertOpen(inc) && idadeS > ALERT_POS_VELHA_S) {
      itens.push(`<span class="alert-map-chip is-warn" title="O celular nao manda posicao nova: a pessoa pode estar parada ou sem sinal. Confira pelas cameras.">Posicao de ha ${esc(alertAgo(inc.last_position_at))} · parada ou sem sinal</span>`);
    } else if (p && p.gps) {
      const prec = inc.last_accuracy != null ? ` ~${Math.round(inc.last_accuracy)} m` : '';
      const quando = inc.last_position_at ? ` · atualizado ha ${esc(alertAgo(inc.last_position_at))}` : '';
      const ruim = inc.last_accuracy != null && inc.last_accuracy > ALERT_CIRCULO_MAX_M;
      itens.push(ruim
        ? `<span class="alert-map-chip is-warn">GPS impreciso${prec}${quando} — use as cameras da lotacao</span>`
        : `<span class="alert-map-chip"><span class="alert-chip-dot"></span>GPS${prec}${quando}</span>`);
    }
    else if (p) itens.push('<span class="alert-map-chip is-warn">Sem GPS: mostrando a lotacao</span>');
    else itens.push('<span class="alert-map-chip is-warn">Sem localizacao ainda</span>');
    if (inc.last_battery != null) itens.push(`<span class="alert-map-chip${inc.last_battery < 15 ? ' is-warn' : ''}">Bateria ${inc.last_battery}%</span>`);
    if (andou >= 15) itens.push(`<span class="alert-map-chip">Andou ${esc(alertDistLabel(andou))} desde o disparo</span>`);
    chips.innerHTML = itens.join('');
    const maps = p ? `<a class="alert-map-btn" href="https://www.google.com/maps?q=${p.lat},${p.lon}" target="_blank" rel="noopener"><i data-lucide="external-link"></i> Google Maps</a>` : '';
    tools.innerHTML = `${p ? `<button type="button" class="alert-map-btn${_alertSeguir ? ' is-on' : ''}" data-map="seguir"><i data-lucide="locate-fixed"></i> ${_alertSeguir ? 'Seguindo a pessoa' : 'Seguir a pessoa'}</button>` : ''}${maps}`;
    if (legenda) legenda.innerHTML = '<span><i class="lg-pessoa"></i> pessoa</span><span><i class="lg-disparo"></i> ponto do disparo</span><span><i class="lg-rastro"></i> trajeto</span>';
  } else {
    tools.innerHTML = '';
    alertDesenharLotacoes();
  }
  if (window.lucide) lucide.createIcons();
}

let _alertLotKey = '';
let _alertMapCams = { at: 0, lista: null };
async function alertDesenharLotacoes() {
  const chips = document.getElementById('alertMapChips');
  const legenda = document.getElementById('alertMapLegend');
  let membros = _alertCalm?.membros?.members;
  if (!membros) {
    try { membros = (await alertApiJson('/api/alert/members')).members || []; } catch { membros = []; }
  }
  // Cameras dos locais monitorados: 1 busca por minuto (o backend tambem guarda 60 s).
  if (!_alertMapCams.lista || Date.now() - _alertMapCams.at > 60000) {
    _alertMapCams.at = Date.now();
    try { _alertMapCams.lista = (await alertApiJson('/api/alert/map-cameras')).cameras || []; } catch { _alertMapCams.lista = _alertMapCams.lista || []; }
  }
  if (_alertDetail) return; // chegou alerta enquanto buscava
  const cams = _alertMapCams.lista || [];
  const locais = new Map();
  membros.filter((m) => m.active && m.ponto).forEach((m) => {
    const k = `${Number(m.ponto.lat).toFixed(4)},${Number(m.ponto.lon).toFixed(4)}`;
    const it = locais.get(k) || { lat: Number(m.ponto.lat), lon: Number(m.ponto.lon), nomes: [], site: m.site || m.unit_name || '', pend: 0, origem: m.ponto.origem };
    it.nomes.push(m.full_name);
    if (m.prontidao && !m.prontidao.pronta) it.pend += 1;
    locais.set(k, it);
  });
  const ativos = membros.filter((m) => m.active).length;
  if (chips) {
    const partes = [];
    if (locais.size) partes.push(`<span class="alert-map-chip"><span class="alert-chip-dot"></span>${locais.size} ${locais.size === 1 ? 'local monitorado' : 'locais monitorados'} · ${ativos} ${ativos === 1 ? 'pessoa' : 'pessoas'}</span>`);
    if (cams.length) partes.push(`<span class="alert-map-chip">${cams.length} cameras no mapa</span>`);
    if (!locais.size) partes.push(ativos ? '<span class="alert-map-chip is-warn">Sem coordenada da lotacao nem cameras com coordenada no local</span>' : '<span class="alert-map-chip is-warn">Nenhuma pessoa cadastrada no Alerta</span>');
    chips.innerHTML = partes.join('');
  }
  if (legenda) {
    const lg = [];
    if (locais.size) {
      lg.push('<span><i class="lg-local"></i> lotacao (todos prontos)</span>');
      if ([...locais.values()].some((x) => x.pend)) lg.push('<span><i class="lg-local-warn"></i> lotacao com pendencia</span>');
    }
    if (cams.length) lg.push('<span><i class="lg-camera"></i> camera do local</span>');
    legenda.innerHTML = lg.join('');
  }
  const key = `${[...locais.keys()].sort().join('|')}#${cams.length}`;
  if (!_alertUnits || key === _alertLotKey) return;
  _alertLotKey = key;
  _alertUnits.clearLayers();
  const pts = [];
  // Cameras primeiro (embaixo), em canvas: centenas de pontos sem travar o mapa.
  const render = L.canvas ? L.canvas({ padding: 0.3 }) : undefined;
  cams.forEach((c) => {
    L.circleMarker([c.lat, c.lon], { renderer: render, radius: 3.5, weight: 1, color: '#ffffff', fillColor: '#1971c2', fillOpacity: 0.9 })
      .bindTooltip(`${esc(c.titulo || '')}${c.site ? `<br><small>${esc(c.site)}</small>` : ''}`).addTo(_alertUnits);
    pts.push([c.lat, c.lon]);
  });
  locais.forEach((it) => {
    const icon = L.divIcon({ className: '', html: `<span class="alert-lot${it.pend ? ' warn' : ''}">${it.nomes.length}</span>`, iconSize: [26, 26], iconAnchor: [13, 13] });
    const onde = it.origem === 'cameras' ? '<br><small>posicao pelas cameras do local</small>' : '';
    L.marker([it.lat, it.lon], { icon, zIndexOffset: 500 })
      .bindTooltip(`${esc(it.site)}${onde}<br>${it.nomes.map(esc).slice(0, 6).join('<br>')}${it.nomes.length > 6 ? '<br>...' : ''}`).addTo(_alertUnits);
    pts.push([it.lat, it.lon]);
  });
  if (pts.length && _alertMap) _alertMap.fitBounds(pts, { padding: [50, 50], maxZoom: 16 });
}

// Faixa no topo: o alerta sem atendimento mais antigo, com cronometro e Assumir.
// So no ao vivo -- no historico ela atrapalharia a leitura.
function alertRenderBanner() {
  const box = document.getElementById('alertBanner');
  if (!box) return;
  const novos = _alertScope === 'live'
    ? _alertIncidents.filter((i) => i.status === 'new').sort((a, b) => String(a.opened_at).localeCompare(String(b.opened_at)))
    : [];
  if (!novos.length) { box.hidden = true; box.innerHTML = ''; return; }
  const inc = novos[0];
  const m = inc.member || {};
  const p = alertPoint(inc);
  const onde = [m.role_title, inc.site, m.unit_name].filter(Boolean).join(' · ');
  const gps = !p ? 'sem localizacao ainda' : (p.gps ? `GPS ~${Math.round(inc.last_accuracy || 0)} m` : 'sem GPS, usando a lotacao');
  const escala = inc.escalated_at
    ? '<span>Aviso enviado ao Telegram do site</span>'
    : `<span data-alert-escala="${esc(inc.opened_at)}"></span>`;
  // Chegou outro pedido enquanto a central atende um: deixa claro que o atual nao some.
  const atual = inc.id !== _alertSelectedId
    ? _alertIncidents.find((i) => i.id === _alertSelectedId && alertOpen(i) && i.status !== 'new') : null;
  box.hidden = false;
  box.classList.toggle('is-duress', inc.kind === 'duress');
  box.innerHTML = `
    <div class="alert-banner-icon"><i data-lucide="siren"></i></div>
    <div class="alert-banner-text">
      <small>${inc.kind === 'duress' ? 'COACAO · NINGUEM ASSUMIU' : 'PEDIDO DE AJUDA · NINGUEM ASSUMIU'}</small>
      <strong>${esc(m.full_name || '')}${onde ? ` <span>— ${esc(onde)}</span>` : ''}</strong>
      <p>${esc(gps)} · ${escala}${novos.length > 1 ? ` · <b>+${novos.length - 1} outro${novos.length > 2 ? 's' : ''} sem atendimento</b>` : ''}</p>
      ${atual ? `<p class="alert-banner-segue">O atendimento de ${esc(atual.member?.full_name || '')} continua aberto no painel. "Ver" so troca o que aparece, nao encerra nada.</p>` : ''}
    </div>
    <div class="alert-banner-timer" data-alert-tick="${esc(inc.opened_at)}">${esc(alertTimer(inc.opened_at))}</div>
    <div class="alert-banner-actions">
      <button type="button" class="alert-banner-ack" data-banner-ack="${esc(inc.id)}"><i data-lucide="hand"></i> Assumir agora</button>
      ${inc.id !== _alertSelectedId ? `<button type="button" class="alert-banner-ver" data-banner-ver="${esc(inc.id)}">Ver</button>` : ''}
    </div>`;
  // Preenche o texto do Telegram ja, sem esperar o primeiro tique.
  box.querySelectorAll('[data-alert-escala]').forEach((el) => {
    const falta = ALERT_ESCALATION_S - Math.floor((Date.now() - (alertDate(el.dataset.alertEscala)?.getTime() || 0)) / 1000);
    el.textContent = falta > 0 ? `Telegram do site avisa em ${alertTimer(new Date(Date.now() - falta * 1000).toISOString())}` : 'Aviso enviado ao Telegram do site';
  });
  if (window.lucide) lucide.createIcons();
}

// Etapas do atendimento com o tempo de cada uma desde o disparo.
function alertStepsHtml(inc) {
  const desde = (v) => (v ? `+${alertTimer(inc.opened_at, v)}` : '');
  const cancelado = inc.status === 'cancelled';
  const passos = [
    { t: 'Disparo', at: inc.opened_at, quem: '' },
    { t: 'Assumido', at: inc.acknowledged_at, quem: inc.acknowledged_by },
    { t: 'Equipe enviada', at: inc.dispatched_at, quem: inc.dispatched_by },
    { t: 'Chegou ao local', at: inc.arrived_at, quem: inc.arrived_by },
    cancelado
      ? { t: 'Cancelado pela pessoa', at: inc.closed_at || inc.updated_at, quem: '' }
      : { t: 'Encerrado', at: inc.closed_at, quem: inc.closed_by },
  ];
  const atual = passos.findIndex((x) => !x.at);
  return `<ol class="alert-steps">${passos.map((x, i) => {
    const cls = x.at ? 'done' : (i === atual && alertOpen(inc) ? 'current' : '');
    const tempo = i === 0 ? alertClock(x.at) : (x.at ? `${alertClock(x.at)} <em>${esc(desde(x.at))}</em>` : (cls === 'current' ? 'aguardando' : '—'));
    return `<li class="${cls}"><span class="alert-step-dot">${x.at ? '<i data-lucide="check"></i>' : i + 1}</span>
      <div><b>${esc(x.t)}</b>${x.quem ? `<small>${esc(x.quem)}</small>` : ''}</div><span class="alert-step-time">${tempo}</span></li>`;
  }).join('')}</ol>`;
}

// Passos do atendimento (lista do site, editada em "Passos por site").
function alertPodeEditarPassos() {
  return ['admin', 'owner'].includes(String(_currentUser?.role || '').toLowerCase()) || !!_currentUser?.is_platform_admin;
}

function alertProtocoloHtml(inc, open) {
  const passos = inc.protocolo || [];
  if (!passos.length) {
    return open && alertPodeEditarPassos()
      ? `<div class="alert-protocolo is-vazio"><span>Este site nao tem passos de atendimento definidos.</span><button type="button" class="link-action" data-alert-protocolo-edit>Definir passos</button></div>`
      : '';
  }
  const feitos = passos.filter((p) => p.feito).length;
  return `<div class="alert-protocolo">
    <div class="alert-protocolo-head"><b>Passos do atendimento</b><span>${feitos} de ${passos.length}${inc.site ? ` · ${esc(inc.site)}` : ''}</span></div>
    <div class="alert-protocolo-list">${passos.map((p) => `
      <label class="alert-protocolo-item${p.feito ? ' done' : ''}">
        <input type="checkbox" data-alert-passo="${esc(p.texto)}" ${p.feito ? 'checked' : ''} ${open ? '' : 'disabled'}>
        <span>${esc(p.texto)}</span>
        ${p.feito ? `<small>${esc(p.por)} · ${esc(alertClock(p.em))}</small>` : ''}
      </label>`).join('')}</div>
  </div>`;
}

let _alertProtocolos = null;

async function alertOpenProtocolos(siteInicial) {
  try {
    _alertProtocolos = await alertApiJson('/api/alert/protocols');
  } catch (err) {
    showToast(err.message || 'Falha ao carregar os passos.', true);
    return;
  }
  const sel = document.getElementById('alertProtSite');
  const opcoes = [];
  if (_alertProtocolos.pode_padrao) opcoes.push(['*', 'Padrao (site sem lista propria)']);
  (_alertProtocolos.sites || []).forEach((x) => opcoes.push([x.site, `${x.site}${x.passos.length ? ` (${x.passos.length})` : ''}`]));
  if (!opcoes.length) { showToast('Nenhum site disponivel.', true); return; }
  sel.innerHTML = opcoes.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join('');
  const alvo = opcoes.find(([v]) => v.toUpperCase() === String(siteInicial || '').toUpperCase());
  sel.value = alvo ? alvo[0] : opcoes[0][0];
  alertProtocoloMostrarSite();
  document.getElementById('modalAlertProtocolos').classList.remove('hidden');
  setTimeout(() => document.getElementById('alertProtPassos')?.focus(), 50);
}

function alertProtocoloMostrarSite() {
  const site = document.getElementById('alertProtSite').value;
  const passos = site === '*'
    ? (_alertProtocolos?.padrao || [])
    : ((_alertProtocolos?.sites || []).find((x) => x.site === site)?.passos || []);
  document.getElementById('alertProtPassos').value = passos.join('\n');
}

async function alertSalvarProtocolo() {
  const site = document.getElementById('alertProtSite').value;
  const passos = document.getElementById('alertProtPassos').value.split('\n').map((x) => x.trim()).filter(Boolean);
  const btn = document.getElementById('btnAlertProtSave');
  btn.disabled = true;
  try {
    await alertApiJson('/api/alert/protocols', { method: 'PUT', body: JSON.stringify({ site, passos }) });
    showToast(passos.length ? 'Passos salvos.' : 'Lista removida.');
    alertCloseModal('modalAlertProtocolos');
    if (_alertDetail) alertLoadDetail();
  } catch (err) {
    showToast(err.message || 'Falha ao salvar.', true);
  } finally {
    btn.disabled = false;
  }
}

const ALERT_QUICK_NOTES = ['Pessoa segura', 'Contato com a pessoa', 'Contato com a direcao', 'Possivel falso disparo'];

function alertQuickNotesHtml() {
  return `<div class="alert-quick"><span>Registrar rapido:</span>${ALERT_QUICK_NOTES.map((t) =>
    `<button type="button" class="alert-quick-chip" data-alert-quick="${esc(t)}">${esc(t)}</button>`).join('')}</div>`;
}

function alertRenderList() {
  const box = document.getElementById('alertLiveList');
  if (!box) return;
  const sub = _alertScope === 'live'
    ? (_alertMeusSites ? `So ${_alertMeusSites.length === 1 ? 'do seu site' : `dos seus ${_alertMeusSites.length} sites`}` : 'Todos os sites do cliente')
    : 'Todos os alertas, mais recentes primeiro.';
  setText('alertListSub', sub);
  if (!_alertIncidents.length) {
    box.innerHTML = `<div class="alert-live-empty alert-fila-vazia"><i data-lucide="shield-check"></i><span>${_alertScope === 'live'
      ? 'Nenhum pedido de ajuda aberto.'
      : 'Nenhum alerta registrado ainda.'}</span></div>`;
    if (window.lucide) lucide.createIcons();
    return;
  }
  const STATUS_CURTO = { acknowledged: 'assumido', dispatched: 'equipe a caminho' };
  const card = (inc) => {
    const m = inc.member || {};
    if (!alertOpen(inc)) {
      // Encerrado: uma linha so -- quem, como terminou, quanto durou.
      const como = inc.status === 'cancelled' ? 'cancelado pela pessoa' : (String(inc.close_note || '').trim() || 'encerrado');
      return `
      <button type="button" class="alert-card is-final${inc.id === _alertSelectedId ? ' selected' : ''}" data-alert-id="${esc(inc.id)}">
        <span class="alert-card-fim"><b>${esc(m.full_name)}</b><small>${esc(como.length > 34 ? `${como.slice(0, 33)}…` : como)} · ${esc(alertTimer(inc.opened_at, inc.closed_at))}</small></span>
        <span class="alert-card-hora">${esc(alertClock(inc.opened_at).slice(0, 5))}</span>
      </button>`;
    }
    const cls = ['alert-card', inc.id === _alertSelectedId ? 'selected' : '', inc.status === 'new' ? 'is-new' : '',
      inc.kind === 'duress' ? 'is-duress' : ''].filter(Boolean).join(' ');
    const p = alertPoint(inc);
    const gps = !p ? '' : (p.gps ? (inc.last_accuracy != null ? `GPS ~${Math.round(inc.last_accuracy)} m` : '') : 'sem GPS');
    const dono = inc.status === 'new' ? ''
      : `<span class="alert-card-dono">${inc.acknowledged_by ? `com ${esc(inc.acknowledged_by)} · ` : ''}${esc(STATUS_CURTO[inc.status] || '')}</span>`;
    return `
      <button type="button" class="${cls}" data-alert-id="${esc(inc.id)}">
        <span class="alert-card-top">
          <span class="alert-card-quem"><span class="alert-card-ava">${alertAvatarHtml(m)}</span><strong>${esc(m.full_name)}</strong></span>
          <span class="alert-card-age is-live${inc.status === 'new' ? ' is-new' : ''}" data-alert-tick="${esc(inc.opened_at)}">${esc(alertTimer(inc.opened_at))}</span>
        </span>
        <span class="alert-card-meta">${esc([m.role_title, inc.site || m.unit_name].filter(Boolean).join(' · ') || 'sem lotacao')}</span>
        <span class="alert-card-tags">
          <span class="alert-tag ${inc.kind === 'duress' ? 'is-coacao' : 'is-panico'}">${inc.kind === 'duress' ? 'COACAO' : 'PANICO'}</span>
          ${gps ? `<span class="alert-tag">${esc(gps)}</span>` : ''}${dono}
        </span>
      </button>`;
  };
  if (_alertScope !== 'live') { box.innerHTML = _alertIncidents.map(card).join(''); return; }
  // Sem atendimento em cima, depois em atendimento, depois os encerrados de hoje.
  const porIdade = (a, b) => String(a.opened_at).localeCompare(String(b.opened_at));
  const novos = _alertIncidents.filter((i) => i.status === 'new').sort(porIdade);
  const atend = _alertIncidents.filter((i) => alertOpen(i) && i.status !== 'new').sort(porIdade);
  const vistos = new Set(_alertIncidents.map((i) => i.id));
  const fechados = [..._alertIncidents.filter((i) => !alertOpen(i)),
    ...(_alertHoje.lista || []).filter((i) => !alertOpen(i) && !vistos.has(i.id))]
    .sort((a, b) => String(b.opened_at).localeCompare(String(a.opened_at)));
  const grupo = (titulo, lista) => (lista.length ? `<div class="alert-fila-sep">${titulo}</div>${lista.map(card).join('')}` : '');
  box.innerHTML = (novos.length || atend.length
    ? grupo('Sem atendimento', novos) + grupo('Em atendimento', atend)
    : '<div class="alert-live-empty alert-fila-vazia"><i data-lucide="shield-check"></i><span>Nenhum pedido aberto</span></div>')
    + grupo('Encerrados hoje', fechados);
  if (window.lucide) lucide.createIcons();
}

function alertMarkerIcon(inc, selected) {
  const cls = ['alert-marker', `st-${inc.status}`, inc.kind === 'duress' ? 'duress' : '', selected ? 'selected' : ''].join(' ');
  return L.divIcon({ className: '', html: `<span class="${cls}"></span>`, iconSize: [22, 22], iconAnchor: [11, 11] });
}

function alertRenderMarkers() {
  if (!_alertMap) return;
  _alertMarkers.clearLayers();
  const pts = [];
  _alertIncidents.forEach((inc) => {
    const p = alertPoint(inc);
    if (!p) return;
    // No ao vivo, encerrado so aparece se estiver selecionado (nao polui o mapa).
    if (!alertOpen(inc) && inc.id !== _alertSelectedId) return;
    const mk = L.marker([p.lat, p.lon], { icon: alertMarkerIcon(inc, inc.id === _alertSelectedId), zIndexOffset: inc.status === 'new' ? 1000 : 0 });
    mk.bindTooltip(`${esc(inc.member?.full_name || '')}${p.gps ? '' : ' (lotacao, sem GPS)'}`);
    mk.on('click', () => alertSelect(inc.id, true));
    mk.addTo(_alertMarkers);
    pts.push([p.lat, p.lon]);
    // Circulo de erro so quando o GPS e bom: com ~400 m ele cobre o mapa todo e
    // nao diz nada (o chip do mapa avisa "GPS impreciso").
    if (p.gps && inc.last_accuracy && inc.last_accuracy <= ALERT_CIRCULO_MAX_M && inc.id === _alertSelectedId) {
      L.circle([p.lat, p.lon], { radius: inc.last_accuracy, color: '#c92a2a', weight: 1, fillOpacity: 0.08 }).addTo(_alertMarkers);
    }
  });
  if (!_alertFittedOnce && pts.length) {
    const sel = alertPoint(_alertIncidents.find((i) => i.id === _alertSelectedId));
    if (sel) _alertMap.setView([sel.lat, sel.lon], 17);
    else _alertMap.fitBounds(pts, { padding: [40, 40], maxZoom: 17 });
    _alertFittedOnce = true;
  }
}

function alertSelect(id, center) {
  _alertSelectedId = id;
  alertRenderList();
  alertRenderMarkers();
  const p = alertPoint(_alertIncidents.find((i) => i.id === id));
  if (center && p && _alertMap) _alertMap.setView([p.lat, p.lon], Math.max(_alertMap.getZoom(), 16));
  alertLoadDetail();
}

async function alertLoadDetail() {
  const panel = document.getElementById('alertLiveDetail');
  if (!panel) return;
  if (!_alertSelectedId) {
    _alertTrail?.clearLayers();
    _alertDetail = null;
    alertMostrarCameras(false);
    alertRenderCalm();
    alertRenderMapaInfo();
    return;
  }
  try {
    const data = await alertApiJson(`/api/alert/incidents/${encodeURIComponent(_alertSelectedId)}`);
    _alertDetail = data.incident;
  } catch {
    return;
  }
  alertRenderTrail();
  alertRenderDetail();
  alertRenderMapaInfo();
  if (_alertSeguir) alertCentralizar();
  alertMostrarCameras(true);
  alertLoadNearby();
}

function alertRenderTrail() {
  if (!_alertTrail) return;
  _alertTrail.clearLayers();
  const pts = (_alertDetail?.positions || []).map((p) => [p.lat, p.lon]);
  if (pts.length > 1) L.polyline(pts, { color: '#c92a2a', weight: 3, opacity: 0.7, dashArray: '6 6' }).addTo(_alertTrail);
  if (pts.length) L.circleMarker(pts[0], { radius: 5, color: '#172026', weight: 2, fillColor: '#fff', fillOpacity: 1 })
    .bindTooltip('ponto do disparo').addTo(_alertTrail);
}

const ALERT_LOG_LABEL = {
  opened: 'Botao de panico acionado',
  retriggered: 'Botao acionado de novo',
  duress: 'SENHA DE COACAO digitada',
  cancelled_by_user: 'Cancelado pela pessoa (senha normal)',
  acknowledge: 'Assumido',
  dispatch: 'Equipe enviada',
  arrive: 'Equipe chegou ao local',
  step: 'Passo feito',
  step_undo: 'Passo desmarcado',
  note: 'Observacao',
  close: 'Encerrado',
  escalated: 'Aviso enviado ao Telegram',
};

function alertRenderDetail() {
  const panel = document.getElementById('alertLiveDetail');
  const inc = _alertDetail;
  if (!panel || !inc) return;
  const m = inc.member || {};
  const p = alertPoint(inc);
  const open = alertOpen(inc);
  // O painel se redesenha a cada 3 s: guarda o que a pessoa esta digitando.
  const notaAntes = document.getElementById('alertNoteInput');
  const nota = notaAntes && notaAntes.dataset.inc === inc.id ? notaAntes.value : '';
  const notaFoco = notaAntes && document.activeElement === notaAntes;
  const posAge = inc.last_position_at ? `${alertClock(inc.last_position_at)} (ha ${alertAgo(inc.last_position_at)})` : 'nenhuma';
  const mapsUrl = p ? `https://www.google.com/maps?q=${p.lat},${p.lon}` : '';
  const principal = !open ? ''
    : inc.status === 'new'
      ? '<button class="alert-case-main is-ack" data-alert-act="acknowledge" type="button"><i data-lucide="hand"></i> Assumir alerta</button>'
      : !inc.dispatched_at
        ? '<button class="alert-case-main" data-alert-act="dispatch" type="button"><i data-lucide="car"></i> Equipe enviada</button>'
        : !inc.arrived_at
          ? '<button class="alert-case-main" data-alert-act="arrive" type="button"><i data-lucide="map-pin-check"></i> Equipe chegou ao local</button>'
          : '<button class="alert-case-main is-close" data-alert-act="close" type="button"><i data-lucide="check-circle-2"></i> Encerrar com relato</button>';
  const duress = inc.kind === 'duress'
    ? `<div class="alert-case-duress"><i data-lucide="user-x"></i><div><b>Nao ligue para ela.</b> Digitou a senha de coacao as ${esc(alertClock(inc.duress_at))} —
       no celular aparece "cancelado", mas o GPS continua. Alguem pode estar junto.</div></div>` : '';
  const log = (inc.log || []).slice().reverse().map((l) => `
      <li><span>${esc(alertClock(l.created_at))}</span><div><b>${esc(ALERT_LOG_LABEL[l.action] || l.action)}</b>
      ${l.actor ? `<small>${esc(l.actor)}</small>` : ''}${l.note && l.action !== 'opened' ? `<p>${esc(l.note)}</p>` : ''}</div></li>`).join('');
  const fone = m.phone
    ? (inc.kind === 'duress' ? `<b class="is-riscado" title="Coacao: nao ligue">${esc(alertPhone(m.phone))}</b>` : `<b>${esc(alertPhone(m.phone))}</b>`)
    : '<b>sem telefone</b>';
  const sinal = [
    inc.last_battery != null ? `Bateria ${inc.last_battery}%` : '',
    inc.last_accuracy != null ? `GPS ~${Math.round(inc.last_accuracy)} m` : (p && !p.gps ? 'sem GPS (lotacao)' : ''),
    inc.last_position_at ? `ha ${alertAgo(inc.last_position_at)}` : '',
  ].filter(Boolean).join(' · ');
  // Coacao: sem botao de ligar -- alguem pode estar junto da pessoa.
  const ligar = m.phone && inc.kind !== 'duress'
    ? `<a class="alert-case-ligar" href="tel:${esc(m.phone)}"><i data-lucide="phone"></i> Ligar</a>` : '';
  const dica = !open ? ''
    : inc.status === 'new'
      ? (inc.escalated_at ? 'Aviso ja enviado ao Telegram do site' : `<span data-alert-escala="${esc(inc.opened_at)}"></span>`)
      : !inc.dispatched_at
        ? `Assumido${inc.acknowledged_by ? ` por ${esc(inc.acknowledged_by)}` : ''} as ${esc(alertClock(inc.acknowledged_at).slice(0, 5))}`
        : !inc.arrived_at
          ? `Equipe saiu as ${esc(alertClock(inc.dispatched_at).slice(0, 5))} · marque quando chegar`
          : `Equipe no local desde ${esc(alertClock(inc.arrived_at).slice(0, 5))}`;

  // Abas: o painel redesenha a cada 3 s, entao a aba escolhida fica guardada.
  const passos = inc.protocolo || [];
  const abas = [
    ['passos', passos.length ? `Passos ${passos.filter((x) => x.feito).length}/${passos.length}` : 'Passos'],
    ...(open ? [['nota', 'Observacao']] : []),
    ['tempo', 'Linha do tempo'],
    ['dados', 'Dados'],
  ];
  if (_alertAbaInc !== inc.id) {
    _alertAbaInc = inc.id;
    _alertAba = !open ? 'tempo' : (passos.length ? 'passos' : 'nota');
  }
  if (!abas.some(([k]) => k === _alertAba)) _alertAba = abas[0][0];
  const oculta = (k) => (k === _alertAba ? '' : ' hidden');

  panel.hidden = false;
  panel.classList.remove('is-calm');
  panel.innerHTML = `
    <div class="alert-case-head${inc.kind === 'duress' ? ' is-duress' : ''}${inc.status === 'new' ? ' is-new' : ''}${open ? '' : ' is-final'}">
      <div class="alert-case-kicker">${esc(alertKicker(inc))}</div>
      <div class="alert-case-who">
        <span class="alert-case-avatar">${alertAvatarHtml(m)}</span>
        <div class="alert-case-name">
          <strong>${esc(m.full_name)}</strong>
          <small>${esc([m.role_title, inc.site, m.unit_name].filter(Boolean).join(' · ') || 'sem lotacao cadastrada')}</small>
        </div>
        <div class="alert-case-timer">
          <b ${open ? `data-alert-tick="${esc(inc.opened_at)}"` : ''}>${esc(open ? alertTimer(inc.opened_at) : alertTimer(inc.opened_at, inc.closed_at))}</b>
          <small>${open ? 'desde o disparo' : 'duracao total'}</small>
        </div>
      </div>
      ${duress}
    </div>
    <div class="alert-case-body">
      ${principal ? `<div class="alert-case-actions">${principal}${dica ? `<small class="alert-case-dica">${dica}</small>` : ''}</div>` : ''}
      ${alertStepsHtml(inc)}
      <div class="alert-case-contato">
        <div>${fone}${sinal ? `<small>${esc(sinal)}</small>` : ''}</div>${ligar}
      </div>
      <nav class="alert-case-tabs" aria-label="Detalhes do atendimento">${abas.map(([k, t]) =>
        `<button type="button" data-alert-aba="${k}" aria-pressed="${k === _alertAba}">${esc(t)}</button>`).join('')}</nav>
      <div class="alert-case-tab"${oculta('passos')}>${alertProtocoloHtml(inc, open) || '<div class="alert-live-empty">Este site nao tem passos de atendimento definidos.</div>'}</div>
      ${open ? `<div class="alert-case-tab"${oculta('nota')}>
        ${alertQuickNotesHtml()}
        <div class="alert-case-note">
          <input id="alertNoteInput" data-inc="${esc(inc.id)}" maxlength="2000" placeholder="Escreva e tecle Enter — entra na linha do tempo" value="${esc(nota)}">
          <button class="secondary-action" data-alert-act="note-send" type="button" aria-label="Registrar observacao"><i data-lucide="send"></i></button>
        </div>
      </div>` : ''}
      <div class="alert-case-tab alert-timeline"${oculta('tempo')}><ul>${log || '<li><div>Sem registros.</div></li>'}</ul></div>
      <div class="alert-case-tab alert-case-facts"${oculta('dados')}>
        <span><small>CPF</small><b>${esc(alertCpf(m.document_id)) || '-'}</b></span>
        <span><small>Disparo</small><b>${esc(alertClock(inc.opened_at))}</b></span>
        <span><small>Ultima posicao</small><b>${esc(posAge)}</b></span>
        <span><small>Precisao GPS</small><b>${inc.last_accuracy != null ? `~${Math.round(inc.last_accuracy)} m` : (p && !p.gps ? 'sem GPS (lotacao)' : '-')}</b></span>
        ${m.notes ? `<span class="wide"><small>Observacoes do cadastro</small><b>${esc(m.notes)}</b></span>` : ''}
        ${inc.close_note ? `<span class="wide"><small>Encerramento</small><b>${esc(inc.close_note)}</b></span>` : ''}
        ${mapsUrl ? `<span class="wide"><a class="link-action" href="${esc(mapsUrl)}" target="_blank" rel="noopener"><i data-lucide="map-pin"></i> Abrir no Google Maps</a></span>` : ''}
      </div>
      ${open ? `<div class="alert-case-foot">
        ${inc.status !== 'new' && !inc.dispatched_at ? '<button class="secondary-action" data-alert-act="arrive" type="button"><i data-lucide="map-pin-check"></i> Equipe chegou</button>' : ''}
        ${inc.arrived_at ? '' : '<button class="secondary-action" data-alert-act="close" type="button"><i data-lucide="check-circle-2"></i> Encerrar</button>'}
      </div>` : ''}
    </div>`;
  const notaDepois = document.getElementById('alertNoteInput');
  if (notaDepois && notaFoco) { notaDepois.focus(); notaDepois.setSelectionRange(nota.length, nota.length); }
  panel.querySelectorAll('[data-alert-escala]').forEach((el) => {
    const falta = ALERT_ESCALATION_S - Math.floor((Date.now() - (alertDate(el.dataset.alertEscala)?.getTime() || 0)) / 1000);
    el.textContent = falta > 0 ? `Telegram do site avisa em ${alertTimer(new Date(Date.now() - falta * 1000).toISOString())}` : 'Aviso enviado ao Telegram do site';
  });
  if (window.lucide) lucide.createIcons();
}

// Uma linha que diz o estado do atendimento, no topo do painel.
function alertKicker(inc) {
  const coacao = inc.kind === 'duress' ? 'COACAO · ' : '';
  if (inc.status === 'cancelled') return 'CANCELADO PELA PESSOA';
  if (inc.status === 'closed') return `${coacao}ATENDIMENTO ENCERRADO`;
  if (inc.status === 'new') return `${coacao || 'PEDIDO DE AJUDA · '}NINGUEM ASSUMIU`;
  if (inc.arrived_at) return `${coacao}EQUIPE NO LOCAL`;
  if (inc.dispatched_at) return `${coacao}EQUIPE A CAMINHO`;
  return `${coacao}EM ATENDIMENTO${inc.acknowledged_by ? ` · COM ${String(inc.acknowledged_by).toUpperCase()}` : ''}`;
}

function alertIniciais(nome) {
  const partes = String(nome || '').trim().split(/\s+/).filter(Boolean);
  if (!partes.length) return '?';
  return (partes[0][0] + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase();
}

function alertMostrarCameras(on) {
  const box = document.getElementById('alertLiveCams');
  if (box) box.hidden = !on;
  if (!on) { const g = document.getElementById('alertNearbyGrid'); if (g) g.innerHTML = ''; _alertNearbyKey = ''; _alertNearbyHtml = ''; }
}

// Tela calma: o que a central quer saber quando nao ha alerta -- se o posto
// vai tocar, se as pessoas conseguem pedir ajuda, como foi o dia.
let _alertCalm = { at: 0, membros: null, hoje: null };

async function alertRenderCalm() {
  const panel = document.getElementById('alertLiveDetail');
  if (!panel) return;
  panel.hidden = false;
  panel.classList.add('is-calm');
  const agora = Date.now();
  if (agora - _alertCalm.at > 60000) {
    _alertCalm.at = agora;
    try {
      _alertCalm.membros = await alertApiJson('/api/alert/members').catch(() => null);
    } catch {}
  }
  if (_alertSelectedId) return; // um alerta chegou enquanto buscava
  const somOn = alertSoundOn();
  const aviso = !('Notification' in window) ? 'nao suportado' : (Notification.permission === 'granted' ? 'ativo' : (Notification.permission === 'denied' ? 'bloqueado' : 'desligado'));
  const pr = _alertCalm.membros?.prontidao;
  const pend = (_alertCalm.membros?.members || []).filter((x) => x.active && x.prontidao && !x.prontidao.pronta).length;
  const hoje = _alertHoje.lista || [];  // mesma contagem do "Hoje N" da fila
  const ult = hoje[0];
  const linha = (ok, icone, titulo, texto, acao = '') => `
    <div class="alert-calm-row ${ok ? 'ok' : 'warn'}">
      <span class="alert-calm-ico"><i data-lucide="${icone}"></i></span>
      <div><b>${titulo}</b><small>${texto}</small></div>${acao}
    </div>`;
  panel.innerHTML = `
    <div class="alert-calm-head">
      <span class="alert-calm-badge"><i data-lucide="shield-check"></i></span>
      <div><strong>Tudo calmo</strong><small>Nenhum pedido de ajuda aberto${_alertMeusSites ? ` nos seus ${_alertMeusSites.length === 1 ? 'site' : `${_alertMeusSites.length} sites`}` : ''}.</small></div>
    </div>
    <h3 class="alert-calm-titulo">Este posto esta pronto?</h3>
    <div class="alert-calm-list">
      ${linha(somOn, somOn ? 'volume-2' : 'volume-x', somOn ? 'Este posto vai tocar' : 'Som desligado neste posto',
        somOn ? `${alertSomDescricao()}.` : 'Ligue o som para nao perder alerta.',
        '<button type="button" class="alert-calm-btn" data-calm="som">Testar</button>')}
      ${linha(aviso === 'ativo', 'bell-ring', `Notificacao do computador: ${aviso}`,
        aviso === 'ativo' ? 'Balao aparece mesmo com o SightOps minimizado.' : 'Ative para ser avisado com o navegador em outra aba.',
        aviso === 'ativo' ? '' : '<button type="button" class="alert-calm-btn" data-calm="aviso">Ativar</button>')}
      ${pr ? linha(pend === 0, 'smartphone', `${pr.prontas} de ${pr.total} pessoas prontas`,
        pend ? `${pend} com pendencia (app, senha, GPS ou sem sinal).` : 'Todos os celulares conseguem pedir ajuda.',
        '<button type="button" class="alert-calm-btn" data-calm="pessoas">Ver</button>') : ''}
      ${linha(true, 'history', hoje.length ? `${hoje.length} alerta${hoje.length > 1 ? 's' : ''} hoje` : 'Nenhum alerta hoje',
        ult ? `Ultimo: ${esc(alertClock(ult.opened_at).slice(0, 5))} · ${esc(ult.member?.full_name || '')} · ${esc((ALERT_STATUS[ult.status] || {}).label || ult.status)}` : 'O historico completo fica em Historico.',
        hoje.length ? '<button type="button" class="alert-calm-btn" data-calm="historico">Historico</button>' : '')}
    </div>
    <div class="alert-calm-foot">Quando alguem apertar o botao, este painel vira o atendimento.</div>`;
  if (window.lucide) lucide.createIcons();
}

// Distancia legivel: metro ate 1 km, depois km com uma casa.
function alertDistLabel(m) {
  if (m == null) return '';
  const n = Number(m);
  if (!isFinite(n)) return '';
  return n >= 1000 ? `${(n / 1000).toFixed(1)} km` : `${Math.round(n)} m`;
}

function alertCameraCard(c) {
  // Quadro 16:9 como no videowall: a imagem e o que importa; um clique abre ao vivo.
  const d = alertDistLabel(c.distance_m);
  return `
      <button type="button" class="alert-cam-tile" data-alert-cam="${esc(c.ip)}" data-alert-cam-title="${esc(c.titulo || c.ip)}"
        data-alert-cam-vendor="${esc(c.fabricante)}" data-alert-cam-model="${esc(c.modelo)}"
        data-alert-cam-connector="${esc(c.remote_connector_id || '')}" title="Abrir ao vivo">
        ${c.snapshot_url ? `<img src="${esc(c.snapshot_url)}" alt="" loading="lazy">` : '<i data-lucide="cctv"></i>'}
        <span class="alert-cam-live"><i data-lucide="play"></i> AO VIVO</span>
        <span class="alert-cam-cap"><b>${esc(c.titulo || c.ip)}</b>${d ? `<em>${esc(d)}</em>` : ''}</span>
      </button>`;
}

// Agrupa por site. Numa ocorrencia a central precisa saber de ONDE e cada
// camera; uma grade solta mistura sites vizinhos sem dizer qual e qual.
// Com um site so, nao poe cabecalho -- nao ajuda em nada e rouba espaco.
function alertCamerasPorSite(cams) {
  const porSite = new Map();
  cams.forEach((c) => {
    const site = (c.site || c.local || '').trim() || 'Sem site';
    if (!porSite.has(site)) porSite.set(site, []);
    porSite.get(site).push(c);
  });
  if (porSite.size <= 1) {
    return `<div class="alert-nearby-grid">${cams.map(alertCameraCard).join('')}</div>`;
  }
  return [...porSite.entries()]
    .sort((a, b) => a[0].localeCompare(b[0], 'pt-BR'))
    .map(([site, lista]) => `<div class="alert-site-group" style="margin-bottom:10px">
        <h4 class="alert-site-title" style="font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:6px 0 4px">${esc(site)} <span class="alert-count">${lista.length}</span></h4>
        <div class="alert-nearby-grid">${lista.map(alertCameraCard).join('')}</div>
      </div>`)
    .join('');
}

// Duas fontes: TODAS as cameras do local monitorado da pessoa (a escola, mesmo
// sem coordenada) e as proximas pelo GPS (rua). Sem repetir camera.
async function alertLoadNearby() {
  const box = document.getElementById('alertNearbyGrid');
  if (!box || !_alertDetail) return;
  const p = alertPoint(_alertDetail);
  const cid = _alertDetail.member?.unit_connector_id || '';
  // So refaz a busca quando a pessoa andou ~50 m (3 casas decimais de lat/lon).
  const key = `${_alertDetail.id}:${cid}:${p ? `${p.lat.toFixed(3)}:${p.lon.toFixed(3)}` : '-'}`;
  if (key === _alertNearbyKey && _alertNearbyHtml) { box.innerHTML = _alertNearbyHtml; if (window.lucide) lucide.createIcons(); return; }
  const qs = p ? `lat=${p.lat}&lon=${p.lon}${p.acc != null ? `&accuracy_m=${encodeURIComponent(p.acc)}` : ''}` : '';
  try {
    await alertLoadConnectors();
    const [unit, near] = await Promise.all([
      cid ? alertApiJson(`/api/alert/unit-cameras?connector_id=${encodeURIComponent(cid)}${qs ? `&${qs}` : ''}`) : Promise.resolve({ cameras: [] }),
      // Raio escolhido no cadastro da pessoa (0 = padrao do servidor, 20 m).
      p ? alertApiJson(`/api/alert/nearby-cameras?${qs}&limit=6${_alertDetail.member?.camera_radius_m ? `&radius_m=${_alertDetail.member.camera_radius_m}` : ''}`) : Promise.resolve({ cameras: [] }),
    ]);
    const unitCams = unit.cameras || [];
    const seen = new Set(unitCams.map((c) => `${c.remote_connector_id}|${c.ip}`));
    const nearCams = (near.cameras || []).filter((c) => !seen.has(`${c.remote_connector_id}|${c.ip}`));
    let html = '';
    if (cid) {
      // Informacao demais atrapalha: de cara so as mais proximas da pessoa.
      const ordenadas = unitCams.slice().sort((a, b) => (a.distance_m ?? 1e12) - (b.distance_m ?? 1e12));
      const todas = _alertCamsTodas === _alertDetail.id;
      const mostrar = todas ? ordenadas : ordenadas.slice(0, ALERT_CAMS_MAX);
      const resto = ordenadas.length - mostrar.length;
      html += `<h3>Cameras da lotacao — ${esc(alertConnectorName(cid))} <span class="alert-count">${unitCams.length}</span>${p && !todas && resto > 0 ? '<small class="alert-cams-nota">as mais proximas da pessoa</small>' : ''}</h3>
        ${unitCams.length ? `<div class="alert-nearby-grid">${mostrar.map(alertCameraCard).join('')}</div>` : '<div class="alert-nearby-grid"><div class="alert-live-empty">Nenhuma camera cadastrada neste local.</div></div>'}
        ${resto > 0 ? `<button type="button" class="link-action alert-cams-mais" data-cams="todas">Ver todas as ${unitCams.length} cameras do local</button>`
          : (todas && ordenadas.length > ALERT_CAMS_MAX ? '<button type="button" class="link-action alert-cams-mais" data-cams="menos">Mostrar so as mais proximas</button>' : '')}`;
    }
    // Sem camera no raio, diz isso com todas as letras -- e informa a
    // distancia da mais proxima, que muda a decisao de quem atende.
    const raio = Math.round(near.radius_m || 20);
    let vazio;
    if (!p) {
      vazio = 'Sem localizacao para buscar cameras.';
    } else if (near.nearest && near.nearest.distance_m != null) {
      const d = Math.round(near.nearest.distance_m);
      const dist = d >= 1000 ? `${(d / 1000).toFixed(1)} km` : `${d} m`;
      vazio = `Nenhuma camera num raio de ${raio} m do ponto do alerta. A mais proxima (${esc(near.nearest.titulo || near.nearest.ip || '')}) esta a ${dist}.`;
    } else {
      vazio = `Nenhuma camera num raio de ${raio} m do ponto do alerta.`;
    }
    // Quando o raio foi ampliado, diz por que -- senao parece que o filtro
    // simplesmente nao funcionou.
    const nota = near.widened
      ? `<div class="alert-nearby-note" style="font-size:12px;color:var(--muted);margin:2px 0 8px">Raio ampliado para ${raio} m: o aparelho informou precisao de ~${Math.round(near.accuracy_m || 0)} m.</div>`
      : '';
    html += `<h3 class="${cid ? 'alert-nearby-second' : ''}">No local do alerta <span class="alert-count">${nearCams.length}</span></h3>${nota}
      ${nearCams.length ? alertCamerasPorSite(nearCams)
        : `<div class="alert-nearby-grid"><div class="alert-live-empty">${vazio}</div></div>`}`;
    _alertNearbyKey = key;
    _alertNearbyHtml = html;
    const target = document.getElementById('alertNearbyGrid');
    if (!target) return;
    target.innerHTML = html;
    if (window.lucide) lucide.createIcons();
  } catch {
    box.innerHTML = '<div class="alert-live-empty">Falha ao buscar cameras.</div>';
  }
}

async function alertDetailClick(ev) {
  const aba = ev.target.closest('[data-alert-aba]')?.dataset.alertAba;
  if (aba) {
    _alertAba = aba;
    alertRenderDetail();
    if (aba === 'nota') document.getElementById('alertNoteInput')?.focus();
    return;
  }
  const cam = ev.target.closest('[data-alert-cam]');
  if (cam) { alertOpenCamera(cam.dataset); return; }
  const calm = ev.target.closest('[data-calm]')?.dataset.calm;
  if (calm) {
    if (calm === 'som') alertTestSound('panic');
    else if (calm === 'aviso') { await alertAskNotifyPermission(); _alertCalm.at = 0; alertRenderCalm(); }
    else if (calm === 'pessoas') document.querySelector('.nav-item[data-view="alert-members"]')?.click();
    else if (calm === 'historico') document.getElementById('btnAlertHistory')?.click();
    return;
  }
  const passo = ev.target.closest('[data-alert-passo]');
  if (passo && _alertDetail) {
    passo.disabled = true;
    try {
      await alertApiJson(`/api/alert/incidents/${encodeURIComponent(_alertDetail.id)}/step`, {
        method: 'POST', body: JSON.stringify({ note: passo.dataset.alertPasso, feito: passo.checked }),
      });
      await alertRefresh(true);
    } catch (err) {
      passo.checked = !passo.checked;
      showToast(err.message || 'Falha ao registrar o passo.', true);
    } finally { passo.disabled = false; }
    return;
  }
  if (ev.target.closest('[data-alert-protocolo-edit]')) { alertOpenProtocolos(_alertDetail?.site || ''); return; }
  const quick = ev.target.closest('[data-alert-quick]');
  if (quick && _alertDetail) {
    quick.disabled = true;
    if (await alertAction('note', quick.dataset.alertQuick)) showToast('Registrado na linha do tempo.');
    quick.disabled = false;
    return;
  }
  const act = ev.target.closest('[data-alert-act]')?.dataset.alertAct;
  if (!act || !_alertDetail) return;
  if (act === 'close') {
    document.getElementById('alertCloseNote').value = '';
    document.getElementById('modalAlertClose').classList.remove('hidden');
    setTimeout(() => document.getElementById('alertCloseNote')?.focus(), 50);
    return;
  }
  if (act === 'note-send') { await alertEnviarNota(); return; }
  let note = '';
  if (act === 'note') {
    note = prompt('Observacao para o historico deste alerta:') || '';
    if (!note.trim()) return;
  }
  await alertAction(act, note);
}

async function alertEnviarNota() {
  const inp = document.getElementById('alertNoteInput');
  const txt = (inp?.value || '').trim();
  if (!txt || !_alertDetail) return;
  inp.disabled = true;
  inp.value = '';  // limpa antes: o redesenho do painel nao devolve o texto
  if (!(await alertAction('note', txt))) {
    const de = document.getElementById('alertNoteInput');
    if (de) de.value = txt;
  }
  const depois = document.getElementById('alertNoteInput');
  if (depois) { depois.disabled = false; depois.focus(); }
}

async function alertAction(action, note, id = _alertDetail?.id) {
  if (!id) return false;
  try {
    await alertApiJson(`/api/alert/incidents/${encodeURIComponent(id)}/${action}`, {
      method: 'POST', body: JSON.stringify({ note }),
    });
    await alertRefresh(true);
    return true;
  } catch (err) {
    showToast(err.message || 'Falha na acao.', true);
    return false;
  }
}

async function alertConfirmClose() {
  const note = document.getElementById('alertCloseNote').value.trim();
  if (note.length < 3) { showToast('Descreva o que foi feito antes de encerrar.', true); return; }
  if (await alertAction('close', note)) alertCloseModal('modalAlertClose');
}

function alertOpenCamera(ds) {
  const modal = document.getElementById('modalAlertCamera');
  const video = document.getElementById('alertCameraVideo');
  const status = document.getElementById('alertCameraStatus');
  if (!modal || !video || typeof mountLiveStream !== 'function') return;
  setText('alertCameraTitle', ds.alertCamTitle || ds.alertCam);
  setText('alertCameraSub', ds.alertCam);
  status.textContent = 'Conectando...';
  status.hidden = false;
  modal.classList.remove('hidden');
  if (_alertCamHandle) _alertCamHandle.stop();
  // Senha vazia: o servidor usa a credencial ja salva desta camera/site.
  _alertCamHandle = mountLiveStream(video, {
    ip: ds.alertCam, user: 'admin', pass: '', subtype: 1,
    vendor: ds.alertCamVendor || '', model: ds.alertCamModel || '', connectorId: ds.alertCamConnector || '',
    onStatus: (texto) => {
      if (texto === 'credential_required') {
        status.textContent = 'Camera sem senha salva no SightOps. Abra pelo inventario de cameras e informe a senha.';
        status.hidden = false;
        return;
      }
      status.textContent = texto || '';
      status.hidden = !texto;
    },
  });
}

// ---------------------------------------------------------------- pessoas

async function loadAlertMembers() {
  if (!_alertMembersBound) {
    _alertMembersBound = true;
    let t = null;
    document.getElementById('alertMembersSearch')?.addEventListener('input', () => {
      clearTimeout(t); t = setTimeout(alertLoadMembers, 250);
    });
    document.getElementById('btnAlertMemberNew')?.addEventListener('click', () => alertOpenMember(null));
    document.getElementById('btnAlertMemberSave')?.addEventListener('click', alertSaveMember);
    document.getElementById('alertMemberCpf')?.addEventListener('input', alertConferirCpf);
    ['alertMemberName', 'alertMemberRole', 'alertMemberUnit', 'alertMemberRaio'].forEach((id) =>
      document.getElementById(id)?.addEventListener('input', alertFichaPrevia));
    document.getElementById('alertMemberFotoArq')?.addEventListener('change', alertEscolherFoto);
    document.getElementById('alertMemberFotoCam')?.addEventListener('change', alertEscolherFoto);
    document.getElementById('btnAlertFotoTirar')?.addEventListener('click', () => { _alertFotoNova = ''; alertFichaFoto(); });
    document.getElementById('alertMemberRaioAtalhos')?.addEventListener('click', (ev) => {
      const b = ev.target.closest('[data-raio]');
      if (!b) return;
      document.getElementById('alertMemberRaio').value = b.dataset.raio === '20' ? '' : b.dataset.raio;
      alertFichaPrevia();
    });
    document.getElementById('alertMemberCpfDup')?.addEventListener('click', (ev) => {
      if (ev.target.closest('[data-cpf-abrir]') && _alertCpfDono) alertOpenMember(_alertCpfDono);
    });
    document.getElementById('btnAlertAppOpen')?.addEventListener('click', () => {
      window.open(new URL('alerta/', window.location.href).href, '_blank', 'noopener');
    });
    document.getElementById('btnAlertCodeCopy')?.addEventListener('click', () => {
      const code = document.getElementById('alertCodeValue')?.textContent || '';
      navigator.clipboard?.writeText(code).then(() => showToast('Codigo copiado.'), () => {});
    });
    document.getElementById('alertMemberLat')?.addEventListener('paste', (ev) => {
      // "-10.18, -36.82" colado do Google Maps: separa nos dois campos.
      const txt = (ev.clipboardData || window.clipboardData)?.getData('text') || '';
      const m = txt.match(/(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)/);
      if (!m) return;
      ev.preventDefault();
      document.getElementById('alertMemberLat').value = m[1];
      document.getElementById('alertMemberLon').value = m[2];
    });
    document.getElementById('alertMembersBody')?.addEventListener('click', alertMembersClick);
    document.getElementById('alertAtivacao')?.addEventListener('click', alertAtivacaoClick);
    document.getElementById('alertSoPendencia')?.addEventListener('change', (ev) => { _alertSoPendencia = ev.target.checked; alertLoadMembers(); });
    document.getElementById('btnAlertCoordCams')?.addEventListener('click', () => {
      const pt = _alertEditPonto;
      if (!pt) return;
      document.getElementById('alertMemberLat').value = Number(pt.lat).toFixed(6);
      document.getElementById('alertMemberLon').value = Number(pt.lon).toFixed(6);
      showToast('Posicao preenchida com o centro das cameras do local. Confira e salve.');
    });
    alertBindModalClose();
  }
  await alertLoadMembers();
}

async function alertLoadMembers() {
  const body = document.getElementById('alertMembersBody');
  await alertLoadConnectors();
  const q = document.getElementById('alertMembersSearch')?.value.trim() || '';
  try {
    const data = await alertApiJson(`/api/alert/members?search=${encodeURIComponent(q)}`);
    _alertMembers = data.members || [];
    _alertMeusSites = Array.isArray(data.meus_sites) ? data.meus_sites : null;
  } catch (err) {
    body.innerHTML = `<div class="alert-live-empty">${esc(err.message || 'Falha ao carregar.')}</div>`;
    return;
  }
  alertRenderScope('alertScopeMembers', _alertMeusSites);
  alertRenderMemberSites();
  const doSite = _alertMemberSite ? _alertMembers.filter((m) => (m.site || '') === _alertMemberSite) : _alertMembers;
  alertRenderReadiness(doSite);
  // Pendencia primeiro: e o que a central precisa resolver.
  const visiveis = (_alertSoPendencia ? doSite.filter((m) => !alertPronta(m)) : doSite)
    .slice().sort((a, b) => Number(alertPronta(a)) - Number(alertPronta(b)));
  alertRenderPplKpis(doSite);
  const foot = document.getElementById('alertPplFoot');
  if (foot) foot.textContent = doSite.length ? `Mostrando ${visiveis.length} de ${doSite.length} · pendencias primeiro` : '';
  if (!visiveis.length) {
    body.innerHTML = `<div class="alert-live-empty">${_alertSoPendencia ? 'Ninguem com pendencia. Tudo pronto.' : (q || _alertMemberSite ? 'Ninguem encontrado.' : 'Nenhuma pessoa cadastrada. Clique em "Nova pessoa".')}</div>`;
    return;
  }
  body.innerHTML = visiveis.map(alertMemberRow).join('');
  if (window.lucide) lucide.createIcons();
}

// Um card de Pessoas: os tres itens da prontidao, o que falta, e o botao
// principal e o que resolve a pendencia daquela pessoa.
function alertMemberRow(m) {
  const dev = m.device || {};
  const cod = new Set((m.prontidao?.pendencias || []).map((p) => p.codigo));
  // estado: ok | warn (ambar) | bad (vermelho) | off (cinza, ainda nao se aplica)
  const tick = (estado, rotulo, titulo) => `<span class="alert-chk is-${estado}" title="${esc(titulo)}">${
    { ok: '✓', warn: '!', bad: '✕', off: '–' }[estado]} ${esc(rotulo)}</span>`;
  const app = m.app_devices ? tick('ok', 'App', `${m.app_devices} aparelho(s) ativo(s)`)
    : tick(m.activation_pending ? 'warn' : 'bad', 'App', m.activation_pending ? 'Codigo gerado, ainda nao ativou' : 'Nunca ativou o app');
  const senhas = m.pins_configured ? tick('ok', 'Senhas', 'Senha normal e de coacao criadas')
    : tick(m.app_devices ? 'bad' : 'off', 'Senhas', m.app_devices ? 'Ativou, mas nao criou as senhas' : 'Cria as senhas ao ativar');
  const cams = m.unit_connector_id ? tick('ok', 'Cameras', `Local monitorado: ${alertConnectorName(m.unit_connector_id)}`)
    : tick('warn', 'Cameras', 'Lotacao sem local monitorado (cameras)');
  let sinal = '<span class="alert-sinal off">nunca</span>';
  if (dev.last_seen_at) {
    const ago = alertAgo(dev.last_seen_at);
    const velho = cod.has('sem_sinal');
    sinal = `<span class="alert-sinal${velho ? ' bad' : ''}">${esc(ago.includes('/') ? `em ${ago}` : `ha ${ago}`)}</span>`;
  } else if (!m.app_devices) {
    sinal = `<span class="alert-sinal warn">${m.activation_pending ? `codigo vence ${esc(alertDate(m.activation_expires_at)?.toLocaleDateString('pt-BR') || '')}` : 'nunca ativou'}</span>`;
  }
  const det = [];
  if (cod.has('gps_bloqueado')) det.push('<b class="bad">localizacao bloqueada</b>');
  else if (dev.gps_permission === 'granted') det.push('GPS liberado');
  if (dev.battery != null) det.push(cod.has('bateria') ? `<b class="warn">bateria ${dev.battery}%</b>` : `bateria ${dev.battery}%`);
  const plat = alertPlataforma(dev.platform);
  if (plat) det.push(plat);
  if (m.app_devices > 1) det.push(`${m.app_devices} aparelhos`);
  let principal;
  if (!m.active) principal = '<span class="pill neutral">inativo</span>';
  else if (!m.app_devices) principal = `<button class="primary-action" data-member-act="code" data-id="${esc(m.id)}" type="button"><i data-lucide="qr-code"></i> QR de ativacao</button>`;
  else if (!m.pins_configured) principal = `<button class="secondary-action" data-member-act="lembrar" data-id="${esc(m.id)}" type="button"><i data-lucide="message-circle"></i> Lembrar</button>`;
  else if (cod.has('gps_bloqueado') || cod.has('sem_sinal')) principal = `<button class="secondary-action" data-member-act="teste" data-id="${esc(m.id)}" type="button"><i data-lucide="message-circle"></i> Pedir teste</button>`;
  else if (cod.has('sem_cameras')) principal = `<button class="secondary-action" data-member-act="edit" data-id="${esc(m.id)}" type="button"><i data-lucide="cctv"></i> Ligar cameras</button>`;
  else principal = `<button class="secondary-action" data-member-act="code" data-id="${esc(m.id)}" type="button"><i data-lucide="key-round"></i> Codigo</button>`;
  const pronta = alertPronta(m);
  const pend = m.prontidao?.pendencias || [];
  const falta = !m.active ? 'Cadastro inativo' : (pronta ? 'Pronta' : (pend[0]?.texto || 'Com pendencia'));
  const tom = !m.active ? 'off' : (pronta ? 'ok' : (pend.some((p) => p.bloqueia) ? 'bad' : 'warn'));
  const quem = [m.role_title, m.unit_name].filter(Boolean).join(' · ');
  const meta = [alertCpf(m.document_id), alertPhone(m.phone)].filter(Boolean).join(' · ');
  return `
      <article class="alert-pcard is-${tom}${m.id === _alertAtivId ? ' is-sel' : ''}">
        <div class="alert-pcard-top">
          <span class="alert-pcard-foto${m.foto_v ? ' tem-foto' : ''}">${alertAvatarHtml(m)}<i></i></span>
          <div class="alert-pcard-quem">
            <b>${esc(m.full_name)}</b>
            <small>${esc(quem || 'sem lotacao')}</small>
            <span class="alert-pcard-site${m.site ? '' : ' is-vazio'}" title="${esc(alertConnectorName(m.unit_connector_id))}">${esc(m.site || 'sem site')}</span>
          </div>
          <div class="alert-pcard-icones">
            <button class="icon-button" data-member-act="edit" data-id="${esc(m.id)}" type="button" title="Editar" aria-label="Editar"><i data-lucide="pencil"></i></button>
            <button class="icon-button" data-member-act="revoke" data-id="${esc(m.id)}" type="button" title="Desconectar aparelhos" aria-label="Desconectar aparelhos" ${m.app_devices ? '' : 'disabled'}><i data-lucide="unplug"></i></button>
            <button class="icon-button" data-member-act="delete" data-id="${esc(m.id)}" type="button" title="Excluir" aria-label="Excluir"><i data-lucide="trash-2"></i></button>
          </div>
        </div>
        <div class="alert-pcard-chips">${app}${senhas}${cams}</div>
        <div class="alert-pcard-pe">
          <div class="alert-pcard-falta"><b>${esc(falta)}</b><small>${sinal}${det.length ? ` · ${det.join(' · ')}` : ''}</small>${meta ? `<small>${esc(meta)}</small>` : ''}</div>
          <div class="alert-row-actions">${principal}</div>
        </div>
      </article>`;
}

function alertPlataforma(p) {
  const v = String(p || '').toLowerCase();
  if (v === 'android') return 'Android (app)';
  if (v === 'ios') return 'iPhone (app)';
  if (v === 'android-web') return 'Android (navegador)';
  if (v === 'web') return 'navegador';
  return '';
}

function alertRenderPplKpis(lista) {
  const dv = document.getElementById('alertPplDevices');
  const sn = document.getElementById('alertPplSinal');
  if (!dv || !sn) return;
  const ativos = lista.filter((m) => m.active);
  if (!ativos.length) { dv.hidden = true; sn.hidden = true; return; }
  const comApp = ativos.filter((m) => m.app_devices);
  const aparelhos = comApp.reduce((n, m) => n + (m.app_devices || 0), 0);
  const plat = {};
  comApp.forEach((m) => { const k = alertPlataforma(m.device?.platform) || 'sem informacao'; plat[k] = (plat[k] || 0) + 1; });
  const bat = comApp.filter((m) => m.device?.battery != null && m.device.battery < 15).length;
  dv.hidden = false;
  dv.innerHTML = `<span class="lbl">Aparelhos ativos</span><b>${aparelhos}</b>
    <small>${Object.entries(plat).map(([k, n]) => `${n} ${esc(k)}`).join(' · ') || 'nenhum ainda'}${bat ? ` · <span class="warn">${bat} com bateria abaixo de 15%</span>` : ''}</small>`;
  const dia = Date.now() - 86400000;
  const recentes = comApp.filter((m) => (alertDate(m.device?.last_seen_at)?.getTime() || 0) >= dia).length;
  const gps = comApp.filter((m) => m.device?.gps_permission === 'granted').length;
  sn.hidden = false;
  sn.innerHTML = `<span class="lbl">Deram sinal nas ultimas 24 h</span><b>${recentes}<em>/${comApp.length}</em></b>
    <small>${gps} com localizacao liberada confirmada · o celular avisa quando o app e aberto</small>`;
}

// ---------------------------------------------------------------- ativacao (QR, WhatsApp, impressao)
let _alertAtivId = '';
let _alertAtiv = null;

function alertLinkAtivacao(code) {
  return new URL(`alerta/?codigo=${encodeURIComponent(code)}`, window.location.href).href;
}

function alertQrSvg(texto) {
  if (typeof qrcode !== 'function') return '<div class="alert-live-empty">QR indisponivel: use o codigo abaixo.</div>';
  const q = qrcode(0, 'M');
  q.addData(texto);
  q.make();
  return q.createSvgTag({ cellSize: 5, margin: 2, scalable: true, alt: 'QR code de ativacao' });
}

function alertWhatsappLink(phone, texto) {
  let d = String(phone || '').replace(/\D/g, '');
  if (!d) return '';
  if (d.length <= 11) d = `55${d}`;
  return `https://wa.me/${d}?text=${encodeURIComponent(texto)}`;
}

function alertRenderAtivacao() {
  const box = document.getElementById('alertAtivacao');
  if (!box) return;
  const a = _alertAtiv;
  if (!a) { box.hidden = true; box.innerHTML = ''; return; }
  const m = a.m;
  const codigo = `${a.code.slice(0, 4)}-${a.code.slice(4)}`;
  const link = alertLinkAtivacao(a.code);
  const vence = alertDate(a.expires_at)?.toLocaleDateString('pt-BR') || '';
  const zap = alertWhatsappLink(m.phone, `Ola, ${m.full_name.split(' ')[0]}! Este e o seu acesso ao botao de ajuda do SightOps.\n\n1. Abra no celular: ${link}\n2. Se pedir, digite o codigo: ${codigo}\n3. Crie a sua senha e a senha de coacao.\n\nO codigo vale uma vez, ate ${vence}.`);
  box.hidden = false;
  box.innerHTML = `
    <div class="alert-ativ-head">
      <div><span class="lbl">Ativar aparelho</span><strong>${esc(m.full_name)}</strong><small>${esc([m.role_title, m.site, m.unit_name].filter(Boolean).join(' · '))}</small></div>
      <button class="icon-button" type="button" data-ativ="fechar" aria-label="Fechar"><i data-lucide="x"></i></button>
    </div>
    <div class="alert-ativ-qr">${alertQrSvg(link)}</div>
    <div class="alert-ativ-code"><b>${esc(codigo)}</b><small>Aponte a camera do celular · vale uma vez, ate ${esc(vence)}. O codigo nao aparece de novo depois que este painel fechar.</small></div>
    <div class="alert-ativ-btns">
      ${zap ? `<a class="primary-action" href="${esc(zap)}" target="_blank" rel="noopener"><i data-lucide="message-circle"></i> Enviar por WhatsApp</a>` : '<span class="alert-ativ-nozap">Sem telefone cadastrado para enviar por WhatsApp.</span>'}
      <button class="secondary-action" type="button" data-ativ="copiar"><i data-lucide="copy"></i> Copiar link</button>
      <button class="secondary-action" type="button" data-ativ="imprimir"><i data-lucide="printer"></i> Imprimir</button>
    </div>
    <div class="alert-ativ-steps"><span class="lbl">Depois de ativar, o app</span>
      <ol><li>Pede as duas senhas (normal e coacao)</li><li>Pede permissao de localizacao</li><li>Avisa a central se o GPS esta liberado e a bateria</li><li>Da sinal toda vez que a pessoa abre o app</li></ol>
    </div>`;
  if (window.lucide) lucide.createIcons();
}

function alertImprimirAtivacao() {
  const a = _alertAtiv;
  if (!a) return;
  const codigo = `${a.code.slice(0, 4)}-${a.code.slice(4)}`;
  const w = window.open('', '_blank', 'width=520,height=720');
  if (!w) { showToast('O navegador bloqueou a janela de impressao.', true); return; }
  const vence = alertDate(a.expires_at)?.toLocaleDateString('pt-BR') || '';
  w.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Ativacao - ${esc(a.m.full_name)}</title>
    <style>body{font-family:Inter,Arial,sans-serif;color:#172026;text-align:center;padding:32px}svg{width:260px;height:260px}
    h1{font-size:20px;margin:0 0 4px}p{color:#66747e;margin:4px 0}b{display:block;font:700 30px ui-monospace,Consolas,monospace;letter-spacing:.18em;margin:16px 0 4px}
    ol{text-align:left;max-width:360px;margin:20px auto;line-height:1.7}</style></head><body>
    <h1>Botao de ajuda SightOps</h1><p>${esc(a.m.full_name)}${a.m.unit_name ? ` · ${esc(a.m.unit_name)}` : ''}</p>
    ${alertQrSvg(alertLinkAtivacao(a.code))}<b>${esc(codigo)}</b><p>Vale uma vez, ate ${esc(vence)}</p>
    <ol><li>Aponte a camera do celular para o QR.</li><li>Se pedir, digite o codigo acima.</li><li>Crie a sua senha e a senha de coacao.</li><li>Libere a localizacao quando o app pedir.</li></ol>
    <script>window.onload=function(){window.print()}<\/script></body></html>`);
  w.document.close();
}

async function alertAtivacaoClick(ev) {
  const act = ev.target.closest('[data-ativ]')?.dataset.ativ;
  if (!act) return;
  if (act === 'fechar') { _alertAtiv = null; _alertAtivId = ''; alertRenderAtivacao(); alertLoadMembers(); return; }
  if (act === 'copiar' && _alertAtiv) {
    navigator.clipboard?.writeText(alertLinkAtivacao(_alertAtiv.code)).then(() => showToast('Link copiado.'), () => showToast('Nao deu para copiar.', true));
  }
  if (act === 'imprimir') alertImprimirAtivacao();
}

function alertMandarLembrete(m, tipo) {
  const link = new URL('alerta/', window.location.href).href;
  const nome = m.full_name.split(' ')[0];
  const texto = tipo === 'lembrar'
    ? `Ola, ${nome}! O seu botao de ajuda do SightOps ja esta ativado, mas falta criar as senhas. Abra ${link} e crie a senha normal e a de coacao.`
    : `Ola, ${nome}! Pode abrir o app do botao de ajuda (${link}) e tocar em "Testar localizacao" no menu? Se pedir, libere a localizacao. Assim a central confirma que o seu celular esta pronto.`;
  const zap = alertWhatsappLink(m.phone, texto);
  if (!zap) { showToast('Sem telefone cadastrado: edite a pessoa para mandar por WhatsApp.', true); return; }
  window.open(zap, '_blank', 'noopener');
}

function alertRenderMemberSites() {
  const nav = document.getElementById('alertMemberSites');
  if (!nav) return;
  const contagem = new Map();
  _alertMembers.forEach((m) => { const k = m.site || ''; contagem.set(k, (contagem.get(k) || 0) + 1); });
  if (_alertMemberSite && !contagem.has(_alertMemberSite)) _alertMemberSite = '';
  // Um site so: aba nao ajuda, esconde.
  if (contagem.size < 2) { nav.hidden = true; nav.innerHTML = ''; return; }
  const sites = [...contagem.keys()].sort((a, b) => (a || '\uffff').localeCompare(b || '\uffff', 'pt-BR'));
  const aba = (valor, rotulo, n) => `<button type="button" class="alert-site-tab${_alertMemberSite === valor ? ' active' : ''}" data-site="${esc(valor)}">${esc(rotulo)} <span>${n}</span></button>`;
  nav.hidden = false;
  nav.innerHTML = aba('', 'Todos', _alertMembers.length) + sites.map((s) => aba(s, s || 'Sem site', contagem.get(s))).join('');
  if (!nav.dataset.bound) {
    nav.dataset.bound = '1';
    nav.addEventListener('click', (ev) => {
      const b = ev.target.closest('[data-site]');
      if (!b) return;
      _alertMemberSite = b.dataset.site;
      alertLoadMembers();
    });
  }
}

// Prontidao (vem do backend): a pessoa consegue pedir ajuda agora?
function alertPronta(m) {
  return m?.prontidao ? !!m.prontidao.pronta : true;
}

function alertReadinessCell(m) {
  const dev = m.device || {};
  const pend = m.prontidao?.pendencias || [];
  const pills = pend.map((p) => `<span class="pill ${p.bloqueia ? 'danger' : 'amber'}">${esc(p.texto)}</span>`).join(' ');
  const info = [];
  if (dev.last_seen_at) {
    const ago = alertAgo(dev.last_seen_at);
    info.push(ago.includes('/') ? `ultimo sinal em ${ago}` : `sinal ha ${ago}`);
  }
  if (dev.gps_permission === 'granted') info.push('GPS liberado');
  if (dev.battery != null) info.push(`bateria ${dev.battery}%`);
  if (m.app_devices > 1) info.push(`${m.app_devices} aparelhos`);
  const linha = info.length ? `<small class="alert-ready-info">${esc(info.join(' · '))}</small>` : '';
  if (alertPronta(m)) return `<div class="alert-ready-pills"><span class="pill success">pronta</span>${pills}</div>${linha}`;
  return `<div class="alert-ready-pills">${pills}</div>${linha}`;
}

function alertRenderReadiness(lista) {
  const box = document.getElementById('alertReadiness');
  const pend = document.getElementById('alertPendencias');
  if (!box) return;
  const ativos = lista.filter((m) => m.active);
  if (!ativos.length) { box.hidden = true; if (pend) pend.hidden = true; return; }
  const prontas = ativos.filter(alertPronta).length;
  const pct = Math.round((prontas / ativos.length) * 100);
  box.hidden = false;
  box.innerHTML = `
    <span class="lbl">Prontas para pedir ajuda</span>
    <div class="alert-ppl-ring-row">
      <div class="alert-ready-ring" style="--pct:${pct}"><span><b>${prontas}</b><small>/${ativos.length}</small></span></div>
      <small>${prontas === ativos.length ? 'Todas prontas.' : `${ativos.length - prontas} com pendencia.`} Pronta = app ativado, senhas, localizacao liberada e app aberto nos ultimos 7 dias.</small>
    </div>`;
  if (!pend) return;
  const conta = {};
  ativos.forEach((m) => (m.prontidao?.pendencias || []).forEach((p) => { conta[p.codigo] = (conta[p.codigo] || 0) + 1; }));
  const ROT = {
    sem_app: ['nao ativaram o app', 'danger'], sem_senha: ['sem senhas', 'danger'], gps_bloqueado: ['com GPS bloqueado', 'danger'],
    sem_sinal: ['sem sinal ha mais de 7 dias', 'danger'], bateria: ['com bateria baixa', 'amber'], sem_cameras: ['sem cameras na lotacao', 'amber'],
  };
  const itens = Object.keys(ROT).filter((k) => conta[k]);
  pend.hidden = false;
  pend.innerHTML = `<span class="lbl">Pendencias</span>${itens.length
    ? `<b>${itens.reduce((n, k) => n + conta[k], 0)}</b><div class="alert-ready-pills">${itens.map((k) => `<span class="pill ${ROT[k][1]}">${conta[k]} ${ROT[k][0]}</span>`).join('')}</div>`
    : '<b class="ok">0</b><small>Nenhuma pendencia: todos os celulares conseguem pedir ajuda.</small>'}`;
}

async function alertFillConnectorSelect(selected) {
  const sel = document.getElementById('alertMemberConnector');
  if (!sel) return;
  const list = await alertLoadConnectors();
  // Restrito a sites: sem local monitorado a pessoa nao teria site e o backend recusa.
  const vazio = _alertMeusSites ? 'Escolha o local monitorado' : 'Nenhum';
  sel.innerHTML = `<option value="">${vazio}</option>` + list.map((c) =>
    `<option value="${esc(c.id)}"${c.id === selected ? ' selected' : ''}>${esc(c.name)}</option>`).join('');
  if (selected && !list.some((c) => c.id === selected)) {
    sel.insertAdjacentHTML('beforeend', `<option value="${esc(selected)}" selected>(conector removido)</option>`);
  }
}

function alertOpenMember(m) {
  const v = (id, val) => { document.getElementById(id).value = val ?? ''; };
  setText('alertMemberModalTitle', m ? 'Editar pessoa' : 'Nova pessoa');
  v('alertMemberId', m?.id);
  v('alertMemberName', m?.full_name);
  v('alertMemberCpf', m ? alertCpf(m.document_id) : '');
  v('alertMemberRole', m?.role_title);
  v('alertMemberPhone', m ? alertPhone(m.phone) : '');
  v('alertMemberUnit', m?.unit_name);
  v('alertMemberLat', m?.unit_lat);
  v('alertMemberLon', m?.unit_lon);
  v('alertMemberNotes', m?.notes);
  v('alertMemberRaio', m?.camera_radius_m || '');
  _alertFotoNova = null;
  _alertFotoAtual = alertFotoUrl(m);
  alertFichaPrevia();
  document.getElementById('alertMemberActive').checked = m ? !!m.active : true;
  _alertCpfDono = null;
  const dup = document.getElementById('alertMemberCpfDup');
  if (dup) { dup.hidden = true; dup.innerHTML = ''; }
  alertFillConnectorSelect(m?.unit_connector_id || '');
  _alertEditPonto = m?.ponto && m.ponto.origem === 'cameras' ? m.ponto : null;
  const bc = document.getElementById('btnAlertCoordCams');
  if (bc) bc.hidden = !_alertEditPonto || m?.unit_lat != null;
  document.getElementById('modalAlertMember').classList.remove('hidden');
  setTimeout(() => document.getElementById('alertMemberName')?.focus(), 50);
}

// Foto da pessoa: URL com a versao (mtime) para o navegador poder guardar.
function alertFotoUrl(m) {
  return m?.id && m.foto_v ? `${API_BASE}/api/alert/members/${encodeURIComponent(m.id)}/foto?v=${m.foto_v}` : '';
}

// Conteudo de um avatar: a foto, ou as iniciais quando nao tem.
function alertAvatarHtml(m) {
  const url = alertFotoUrl(m);
  return url ? `<img src="${esc(url)}" alt="" loading="lazy">` : esc(alertIniciais(m?.full_name));
}

// Foto no cadastro: null = nao mexeu, '' = remover, data URL = nova.
let _alertFotoNova = null;
let _alertFotoAtual = '';

function alertFichaFoto() {
  const url = _alertFotoNova !== null ? _alertFotoNova : _alertFotoAtual;
  const nome = (document.getElementById('alertMemberName')?.value || '').trim();
  const ini = esc(nome ? alertIniciais(nome) : '?');
  const box = document.getElementById('alertMemberFotoBox');
  if (box) {
    box.classList.toggle('tem-foto', !!url);
    box.innerHTML = url ? `<img src="${esc(url)}" alt="Foto da pessoa">` : `<span>${ini}</span>`;
  }
  const prev = document.getElementById('alertMemberPrevIni');
  if (prev) prev.innerHTML = url ? `<img src="${esc(url)}" alt="">` : ini;
  const tira = document.getElementById('btnAlertFotoTirar');
  if (tira) tira.hidden = !url;
}

// Reduz no navegador antes de mandar (foto de celular tem 4-12 MB).
function alertReduzirFoto(arq) {
  return new Promise((ok, falha) => {
    const url = URL.createObjectURL(arq);
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1024 / Math.max(img.width, img.height));
      const cv = document.createElement('canvas');
      cv.width = Math.round(img.width * k);
      cv.height = Math.round(img.height * k);
      cv.getContext('2d').drawImage(img, 0, 0, cv.width, cv.height);
      URL.revokeObjectURL(url);
      ok(cv.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => { URL.revokeObjectURL(url); falha(new Error('Nao consegui abrir essa imagem. Use JPG ou PNG.')); };
    img.src = url;
  });
}

async function alertEscolherFoto(ev) {
  const arq = ev.target.files?.[0];
  ev.target.value = '';
  if (!arq) return;
  try {
    _alertFotoNova = await alertReduzirFoto(arq);
    alertFichaFoto();
  } catch (err) {
    showToast(err.message, true);
  }
}

// Previa do cadastro: o cartao como a central ve no alerta, enquanto digita.
function alertFichaPrevia() {
  const val = (id) => (document.getElementById(id)?.value || '').trim();
  const nome = val('alertMemberName');
  alertFichaFoto();
  setText('alertMemberPrevNome', nome || 'Nome da pessoa');
  setText('alertMemberPrevCargo', [val('alertMemberRole'), val('alertMemberUnit')].filter(Boolean).join(' · ') || 'Cargo · lotacao');
  const raio = val('alertMemberRaio');
  document.querySelectorAll('#alertMemberRaioAtalhos [data-raio]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.raio === (raio || '20'))));
}

// CPF ja cadastrado: avisa ao digitar, antes do Salvar (o backend recusa de
// qualquer jeito). A busca so devolve pessoas dos sites que o usuario ve.
let _alertCpfDono = null;
let _alertCpfSeq = 0;
async function alertConferirCpf() {
  const box = document.getElementById('alertMemberCpfDup');
  if (!box) return;
  const cpf = document.getElementById('alertMemberCpf').value.replace(/\D/g, '');
  const meuId = document.getElementById('alertMemberId').value;
  const seq = ++_alertCpfSeq;
  _alertCpfDono = null;
  box.hidden = true;
  if (cpf.length !== 11) return;
  let dono = null;
  try {
    const data = await alertApiJson(`/api/alert/members?search=${encodeURIComponent(cpf)}`);
    dono = (data.members || []).find((x) => String(x.document_id || '').replace(/\D/g, '') === cpf && x.id !== meuId) || null;
  } catch { return; }
  if (seq !== _alertCpfSeq || !dono) return;
  _alertCpfDono = dono;
  box.innerHTML = `<i data-lucide="alert-triangle"></i><div><b>Ja existe uma pessoa com este CPF</b>
    <span>${esc([dono.full_name, dono.role_title, dono.site || dono.unit_name].filter(Boolean).join(' · '))}</span></div>
    <button type="button" class="secondary-action" data-cpf-abrir>Abrir o cadastro</button>`;
  box.hidden = false;
  if (window.lucide) lucide.createIcons();
}

async function alertSaveMember() {
  const g = (id) => document.getElementById(id).value.trim();
  const payload = {
    id: g('alertMemberId'),
    full_name: g('alertMemberName'),
    document_id: g('alertMemberCpf'),
    role_title: g('alertMemberRole'),
    phone: g('alertMemberPhone'),
    unit_name: g('alertMemberUnit'),
    unit_connector_id: document.getElementById('alertMemberConnector').value,
    unit_lat: g('alertMemberLat') || null,
    unit_lon: g('alertMemberLon') || null,
    notes: g('alertMemberNotes'),
    active: document.getElementById('alertMemberActive').checked,
    camera_radius_m: g('alertMemberRaio') || null,
  };
  try {
    const out = await alertApiJson('/api/alert/members', { method: 'POST', body: JSON.stringify(payload) });
    // Foto depois do cadastro: pessoa nova so tem id depois de salvar.
    let fotoErro = '';
    if (_alertFotoNova !== null && out.member?.id) {
      try {
        await alertApiJson(`/api/alert/members/${encodeURIComponent(out.member.id)}/foto`, { method: 'POST', body: JSON.stringify({ foto: _alertFotoNova }) });
      } catch (err) { fotoErro = err.message || 'falha ao enviar'; }
    }
    alertCloseModal('modalAlertMember');
    showToast(fotoErro ? `Pessoa salva, mas a foto nao: ${fotoErro}` : 'Pessoa salva.', !!fotoErro);
    await alertLoadMembers();
  } catch (err) {
    showToast(err.message || 'Falha ao salvar.', true);
  }
}

async function alertMembersClick(ev) {
  const btn = ev.target.closest('[data-member-act]');
  if (!btn || btn.disabled) return;
  const m = _alertMembers.find((x) => x.id === btn.dataset.id);
  if (!m) return;
  const act = btn.dataset.memberAct;
  try {
    if (act === 'edit') { alertOpenMember(m); return; }
    if (act === 'code') {
      if (m.app_devices && !(await showConfirm({
        eyebrow: 'Codigo de ativacao', title: 'Pessoa ja tem aparelho', label: 'Gerar codigo', danger: false,
        msg: `${m.full_name} ja tem aparelho ativado. Gerar codigo para ativar mais um (ou um celular novo)? O aparelho atual continua funcionando.`,
      }))) return;
      const out = await alertApiJson(`/api/alert/members/${encodeURIComponent(m.id)}/activation-code`, { method: 'POST' });
      _alertAtiv = { m, code: out.code, expires_at: out.expires_at };
      _alertAtivId = m.id;
      alertRenderAtivacao();
      document.getElementById('alertAtivacao')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } else if (act === 'lembrar' || act === 'teste') {
      alertMandarLembrete(m, act);
      return;
    } else if (act === 'revoke') {
      if (!(await showConfirm({
        eyebrow: 'Aparelhos', title: 'Desconectar aparelhos?', label: 'Desconectar',
        msg: `Todos os aparelhos de ${m.full_name} param de funcionar ate ativar de novo com um codigo novo.`,
      }))) return;
      await alertApiJson(`/api/alert/members/${encodeURIComponent(m.id)}/revoke-devices`, { method: 'POST' });
      showToast('Aparelhos desconectados.');
    } else if (act === 'delete') {
      if (!(await showConfirm({
        eyebrow: 'Pessoas do Alerta', title: 'Excluir pessoa?', label: 'Excluir',
        msg: `${m.full_name} sai do Alerta e o app dela para de funcionar. O historico de alertas continua guardado.`,
      }))) return;
      await alertApiJson(`/api/alert/members/${encodeURIComponent(m.id)}`, { method: 'DELETE' });
      showToast('Pessoa excluida.');
    }
    await alertLoadMembers();
  } catch (err) {
    showToast(err.message || 'Falha na acao.', true);
  }
}
