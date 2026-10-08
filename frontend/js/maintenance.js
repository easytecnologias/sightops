function _mntIpMatchTerm(ip, term) {
  // Range completo: 10.10.9.20-10.10.9.30
  const fullRange = term.match(/^(\d{1,3}(?:\.\d{1,3}){3})-(\d{1,3}(?:\.\d{1,3}){3})$/);
  if (fullRange) {
    const n = _ipToInt(ip), lo = _ipToInt(fullRange[1]), hi = _ipToInt(fullRange[2]);
    return n >= lo && n <= hi;
  }
  // Range curto (\u00faltimo octeto): 10.10.9.20-30
  const shortRange = term.match(/^(\d{1,3}\.\d{1,3}\.\d{1,3})\.(\d{1,3})-(\d{1,3})$/);
  if (shortRange) {
    const parts = ip.split('.');
    if (parts.slice(0, 3).join('.') === shortRange[1]) {
      const last = parseInt(parts[3], 10);
      return last >= parseInt(shortRange[2], 10) && last <= parseInt(shortRange[3], 10);
    }
    return false;
  }
  // CIDR: 10.10.9.0/24
  const cidr = term.match(/^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/);
  if (cidr) {
    const bits = parseInt(cidr[2], 10);
    const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
    return (_ipToInt(ip) & mask) === (_ipToInt(cidr[1]) & mask);
  }
  return null; // n\u00e3o \u00e9 padr\u00e3o de range/CIDR
}

let _mntCamView = (() => {
  try { return sessionStorage.getItem('so_mnt_cam_view') || 'basico'; } catch { return 'basico'; }
})();

async function setMntCamView(view) {
  if (!['basico', 'olt', 'switch'].includes(view)) view = 'basico';
  _mntCamView = view;
  try { sessionStorage.setItem('so_mnt_cam_view', view); } catch {}
  const sel = document.getElementById('mntCamView');
  if (sel && sel.value !== view) sel.value = view;
  await loadMntCam();
}

function atualizarAbasMntCam() {
  const sel = document.getElementById('mntCamView');
  if (sel && sel.value !== _mntCamView) sel.value = _mntCamView;
}

async function loadMntCam() {
  const grid = document.getElementById('mntCamGrid');
  if (!grid) return;
  grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Carregando</div>';
  // Cada cliente usa um modo de inventario: quem tem OLT nao tem switch e
  // vice-versa. Pedir 'olt' fixo deixava a tela vazia para cliente de switch --
  // foi o caso da San Marine, cujas 48 cameras nunca apareceram aqui.
  const data = await apiJson(`/api/cameras?mode=${encodeURIComponent(_mntCamView)}`);
  _mntCamAll = data?.cameras || data || [];

  // Escondido o modo sem nenhuma camera, para o usuario nao clicar em vazio.
  // Basico fica sempre visivel por ser o denominador comum.
  atualizarAbasMntCam();

  const sites = [...new Set(_mntCamAll.map(c => c.local).filter(Boolean))].sort();
  const sel = document.getElementById('mntCamSite');
  if (sel) {
    const cur = sel.value;
    sel.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
    sel.value = cur;
  }
  _mntCamRender();
}

function _mntCamRender() {
  const grid = document.getElementById('mntCamGrid');
  if (!grid) return;
  const checked = new Set([...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value));
  const { q, site, status } = _mntCamFilter;
  const ql = _mntSearchText(q);

  // Separa query em termos por vírgula (OR entre termos)
  const terms = ql ? ql.split(',').map(t => t.trim()).filter(Boolean) : [];

  // Lista sem o filtro de ESTADO: e sobre ela que as contagens sao feitas,
  // senao clicar em "Fora do ar" zera os outros numeros e o operador perde a
  // referencia de quantos existem.
  let semEstado = [];
  let filtered = _mntCamAll.filter(c => {
    if (site && (c.local || '') !== site) return false;
    if (status) {
      // Camera sem medicao tem status vazio, nunca a string "unknown": o
      // terceiro estado e tudo que NAO e online nem offline.
      const st = (c.status || '').toLowerCase();
      const grupo = st === 'online' ? 'online' : st === 'offline' ? 'offline' : 'unknown';
      if (grupo !== status) return false;
    }
    if (!terms.length) return true;
    const camIp   = (c.ip || '').trim();
    const haystack = [
      c.ip, c.host, c.camera_ip, c.ip_camera,
      c.titulo, c.title, c.nome, c.name,
      c.local, c.site,
      c.modelo, c.model, c.fabricante, c.brand,
      c.mac, c.onu_name, c.onu_serial,
    ].map(_mntSearchText).join(' ');
    // Basta UM termo bater (OR)
    return terms.some(term => {
      const ipMatch = _mntIpMatchTerm(camIp, term);
      if (ipMatch !== null) return ipMatch;      // era range/CIDR
      return haystack.includes(term);            // texto livre
    });
  });

  semEstado = _mntCamAll.filter(c => {
    if (site && (c.local || '') !== site) return false;
    if (!terms.length) return true;
    const camIp = (c.ip || '').trim();
    const haystack = [
      c.ip, c.host, c.camera_ip, c.ip_camera,
      c.titulo, c.title, c.nome, c.name,
      c.local, c.site,
      c.modelo, c.model, c.fabricante, c.brand,
      c.mac, c.onu_name, c.onu_serial,
    ].map(_mntSearchText).join(' ');
    return terms.some(term => {
      const ipMatch = _mntIpMatchTerm(camIp, term);
      if (ipMatch !== null) return ipMatch;
      return haystack.includes(term);
    });
  });

  filtered.sort((a, b) => (a.titulo || a.ip || '').localeCompare(b.titulo || b.ip || '', 'pt', { numeric: true }));

  if (!filtered.length) {
    grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--muted)">Nenhuma camera encontrada.</div>';
    _mntCamUpdateCount();
    _mntPintarContagens(semEstado);
    return;
  }

  grid.innerHTML = filtered.map(c => {
    const ip  = c.ip || '';
    const st  = (c.status || '').toLowerCase();
    const dot = st === 'online' ? 'online' : st === 'offline' ? 'offline' : 'unknown';
    const snap = c.snapshot_url || c.imgbb_url || '';
    const sel = checked.has(ip);
    return `
      <div class="mnt-cam-card${sel ? ' selected' : ''}" data-ip="${esc(ip)}" data-titulo="${esc(c.titulo||ip)}" data-modelo="${esc(c.modelo || c.model || '')}" data-site="${esc(c.site || c.site_name || c.local || '')}" data-connector="${esc(c.remote_connector_id || c.connector_id || '')}" onclick="_mntCamCardClick(this,event)">
        <input type="checkbox" class="mnt-cam-card-chk chk-mnt-cam" value="${esc(ip)}" ${sel ? 'checked' : ''} onclick="event.stopPropagation();_mntCamToggle(this)">
        <div class="mnt-cam-card-img">
          ${snap ? `<img src="${esc(snap)}" loading="lazy" onerror="this.style.display='none'">` : `<div class="mnt-cam-no-snap"><i data-lucide="camera-off" style="width:22px;height:22px"></i></div>`}
          <span class="mnt-cam-selo ${dot}">${dot === 'online' ? 'respondendo' : dot === 'offline' ? 'fora do ar' : 'sem leitura'}</span>
          <button class="mnt-stream-btn" onclick="event.stopPropagation();openMntStream('${esc(ip)}','${esc(c.titulo||ip)}','${esc(snap)}')" title="Ver stream / links">
            <i data-lucide="play-circle" style="width:16px;height:16px"></i>
          </button>
        </div>
        <div class="mnt-cam-card-info">
          <div class="mnt-cam-card-title">${esc(c.titulo || ip)}</div>
          <div class="mnt-cam-card-sub">${esc(ip)}  ${esc(c.local || '')}</div>
          <div class="mnt-cam-card-sub">${esc(c.modelo || c.model || '')}</div>
        </div>
        <div class="mnt-cam-card-result" id="mntRes_${ip.replace(/\./g,'_')}"></div>
      </div>`;
  }).join('');

  lucide.createIcons();
  _mntCamUpdateCount();
  _mntPintarContagens(semEstado);
}

// A tela ja sabia esses numeros -- eles so nao apareciam em lugar nenhum.
// Contar sobre o conjunto JA filtrado por busca/site e o que faz o numero
// bater com o que esta na frente do operador.
function _mntPintarContagens(lista) {
  const conta = { '': lista.length, online: 0, offline: 0, unknown: 0 };
  for (const c of lista) {
    const st = (c.status || '').toLowerCase();
    conta[st === 'online' ? 'online' : st === 'offline' ? 'offline' : 'unknown']++;
  }
  document.querySelectorAll('#viewMntCam .mnt-status-btn').forEach(b => {
    const chave = b.dataset.mntStatus ?? '';
    const alvo = b.querySelector('.mnt-status-n');
    if (alvo) alvo.textContent = String(conta[chave] ?? 0);
  });
  const most = document.getElementById('mntCamMostrando');
  if (most) most.textContent = `Mostrando ${lista.length} camera${lista.length !== 1 ? 's' : ''}`;
  const btnTodas = document.getElementById('btnMntSelTodas');
  if (btnTodas) btnTodas.textContent = `Selecionar as ${lista.length}`;
  const sub = document.getElementById('mntCamResumo');
  if (sub) {
    const site = document.getElementById('mntCamSite')?.value || '';
    sub.textContent = `${lista.length} camera${lista.length !== 1 ? 's' : ''}`
      + (site ? ` em ${site}` : '')
      + ` · ${conta.online} respondendo, ${conta.offline} fora do ar, ${conta.unknown} sem leitura`;
  }
}

function _mntCamCardClick(card, event) {
  if (event.target.classList.contains('chk-mnt-cam')) return;
  const chk = card.querySelector('.chk-mnt-cam');
  if (chk) { chk.checked = !chk.checked; _mntCamToggle(chk); }
}

function _mntCamToggle(chk) {
  chk.closest('.mnt-cam-card')?.classList.toggle('selected', chk.checked);
  _mntCamUpdateCount();
}

function _mntCamUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  const el = document.getElementById('mntCamSelectedCount');
  if (el) el.textContent = n === 0 ? '0 selecionadas' : `${n} selecionada${n !== 1 ? 's' : ''}`;
  _mntPintarBarraSelecao(n);
}

// A barra de acoes so existe quando ha selecao: antes, doze botoes ficavam
// ligados o tempo todo sem alvo, e "Reboot" tinha o mesmo peso de "Deslocar
// IPs". Mostrar os NOMES do que foi escolhido e o que evita executar em lote
// errado -- o numero sozinho nao diz em quem.
function _mntPintarBarraSelecao(n) {
  const barra = document.getElementById('mntSelBar');
  if (!barra) return;
  barra.classList.toggle('hidden', n === 0);
  const elN = document.getElementById('mntSelN');
  if (elN) elN.textContent = String(n);
  const nomes = document.getElementById('mntSelNomes');
  if (!nomes) return;
  const titulos = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => {
    const card = c.closest('.mnt-cam-card');
    return (card?.dataset.titulo || c.value || '').trim();
  }).filter(Boolean);
  const mostra = titulos.slice(0, 4).join(', ');
  nomes.textContent = titulos.length > 4
    ? `${mostra} e mais ${titulos.length - 4}`
    : mostra;
  nomes.title = titulos.join(', ');
  if (n === 0) _mntFecharGaveta();
}

function _mntAbrirGaveta() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  const sub = document.getElementById('mntGavetaSub');
  if (sub) sub.textContent = `Valem para as ${n} camera${n !== 1 ? 's' : ''} selecionada${n !== 1 ? 's' : ''}.`;
  document.getElementById('mntGaveta')?.classList.remove('hidden');
  document.getElementById('mntGavetaFundo')?.classList.remove('hidden');
  lucide.createIcons();
}

function _mntFecharGaveta() {
  document.getElementById('mntGaveta')?.classList.add('hidden');
  document.getElementById('mntGavetaFundo')?.classList.add('hidden');
}

// A gaveta fecha ao escolher: a acao abre o proprio modal dela, e duas
// camadas sobrepostas escondem o que o operador precisa ler.
function _mntLigarChromeManutencao() {
  document.getElementById('btnMntMaisAcoes')?.addEventListener('click', _mntAbrirGaveta);
  document.getElementById('btnMntGavetaFechar')?.addEventListener('click', _mntFecharGaveta);
  document.getElementById('mntGavetaFundo')?.addEventListener('click', _mntFecharGaveta);
  document.querySelectorAll('#mntGaveta .mnt-gaveta-item').forEach(b =>
    b.addEventListener('click', () => setTimeout(_mntFecharGaveta, 0)));

  // Seleciona o que esta VISIVEL, nao o inventario inteiro: o operador acabou
  // de filtrar, e selecionar o que ele nao esta vendo e como a acao em lote
  // acerta quem nao devia.
  document.getElementById('btnMntSelTodas')?.addEventListener('click', () => {
    document.querySelectorAll('.chk-mnt-cam').forEach(c => {
      c.checked = true;
      c.closest('.mnt-cam-card')?.classList.add('selected');
    });
    _mntCamUpdateCount();
  });

  document.getElementById('btnMntSelLimpar')?.addEventListener('click', () => {
    document.querySelectorAll('.chk-mnt-cam:checked').forEach(c => {
      c.checked = false;
      c.closest('.mnt-cam-card')?.classList.remove('selected');
    });
    _mntCamUpdateCount();
  });

  const chip = document.getElementById('btnMntCred');
  chip?.addEventListener('click', () => {
    const caixa = document.getElementById('mntCredBox');
    if (!caixa) return;
    const abrindo = caixa.classList.contains('hidden');
    caixa.classList.toggle('hidden', !abrindo);
    chip.setAttribute('aria-expanded', abrindo ? 'true' : 'false');
  });
  const usuario = document.getElementById('mntCamUser');
  const resumo = document.getElementById('mntCredResumo');
  const pintarResumo = () => { if (resumo) resumo.textContent = (usuario?.value || 'admin').trim() || 'admin'; };
  usuario?.addEventListener('input', pintarResumo);
  pintarResumo();
}

//  Ver ao vivo - a MESMA janela da implantacao de gravador (deploy.js):
//  as classes .rec-vivo* nao sao mais presas aquele container, entao as duas
//  telas compartilham a definicao em vez de cada uma ter a sua.
let _mntStreamIp = '';
let _mntVivoHandle = null;
let _mntVivoAlta = false;   // camera atras de tunel: comeca no leve
let _mntVivoMudo = true;

const _MNT_SVG = {
  foto: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3Z"/><circle cx="12" cy="13" r="3.2"/>',
  web: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  reiniciar: '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>',
  mudo: '<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="m23 9-6 6M17 9l6 6"/>',
  som: '<path d="M11 5 6 9H2v6h4l5 4V5Z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a9 9 0 0 1 0 14"/>',
  tela: '<path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3"/>',
  fechar: '<path d="M18 6 6 18M6 6l12 12"/>',
};

function _mntBotaoVivo(acao, titulo, caminho) {
  return `<button class="rec-vivo-bt" type="button" data-mnt-${acao} title="${titulo}" aria-label="${titulo}">`
    + `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${caminho}</svg></button>`;
}

function closeMntStream() {
  if (_mntVivoHandle) { try { _mntVivoHandle.stop(); } catch (_) {} _mntVivoHandle = null; }
  _mntStreamIp = '';
  const tampa = document.getElementById('mntTampa');
  if (tampa) tampa.innerHTML = '';
}

function openMntStream(ip, titulo) {
  const card = document.querySelector(`.mnt-cam-card[data-ip="${CSS.escape(ip)}"]`);
  const sub = [ip, card?.dataset.modelo || '', card?.dataset.site || ''].filter(Boolean).join(' · ');

  const tampa = document.getElementById('mntTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'mntTampa';
    document.body.appendChild(el);
    return el;
  })();

  _mntStreamIp = ip;
  _mntVivoMudo = true;

  tampa.innerHTML = `<div class="rec-tampa rec-tampa-vivo" role="dialog" aria-modal="true" aria-label="Ao vivo">
    <div class="rec-vivo">
      <div class="rec-vivo-topo">
        <div class="rec-vivo-id">
          <b>${esc(titulo || ip)}</b>
          <span>${esc(sub)}</span>
        </div>
        <div class="rec-vivo-acoes">
          <span class="rec-vivo-taxa" id="mntVivoTaxa"></span>
          <div class="seg rec-vivo-seg">
            <button type="button" data-mnt-q="1" aria-pressed="${_mntVivoAlta}">Alta</button>
            <button type="button" data-mnt-q="0" aria-pressed="${!_mntVivoAlta}">Leve</button>
          </div>
          ${_mntBotaoVivo('foto', 'Salvar frame', _MNT_SVG.foto)}
          ${_mntBotaoVivo('som', 'Som', _MNT_SVG.mudo)}
          ${_mntBotaoVivo('web', 'Interface web', _MNT_SVG.web)}
          ${_mntBotaoVivo('reiniciar', 'Reiniciar câmera', _MNT_SVG.reiniciar)}
          ${_mntBotaoVivo('tela', 'Tela cheia', _MNT_SVG.tela)}
          ${_mntBotaoVivo('fechar', 'Fechar', _MNT_SVG.fechar)}
        </div>
      </div>
      <div class="rec-vivo-palco" id="mntVivoPalco">
        <video id="mntVivoVideo" autoplay muted playsinline></video>
        <div class="rec-vivo-aviso" id="mntVivoAviso">Conectando...</div>
      </div>
    </div></div>`;

  const video = document.getElementById('mntVivoVideo');
  const aviso = document.getElementById('mntVivoAviso');
  const palco = document.getElementById('mntVivoPalco');
  const taxa  = document.getElementById('mntVivoTaxa');

  const ligar = () => {
    if (_mntVivoHandle) { try { _mntVivoHandle.stop(); } catch (_) {} _mntVivoHandle = null; }
    const hint = cameraStreamHint(ip);
    if (aviso) { aviso.hidden = false; aviso.textContent = 'Conectando...'; }
    if (taxa) taxa.textContent = '';
    video.muted = true;
    _mntVivoHandle = mountLiveStream(video, {
      ip,
      user: document.getElementById('mntCamUser')?.value || 'admin',
      pass: document.getElementById('mntCamPass')?.value || '',
      subtype: _mntVivoAlta ? 0 : 1,
      vendor: hint.vendor,
      model: hint.model,
      // Sem isto o servidor adivinha o conector pelo IP -- e IP privado se
      // repete entre clientes. Com ele, o IP virtual sai certo.
      connectorId: card?.dataset.connector || '',
      onStatus: (texto) => {
        if (!aviso) return;
        if (texto === 'credential_required') {
          // Antes isto aparecia cru na tela e nao dizia nada a quem opera.
          aviso.hidden = false;
          aviso.textContent = 'A senha guardada desta câmera não foi aceita. '
            + 'Abra "Credencial das câmeras" no topo da tela e informe a senha certa.';
          return;
        }
        if (texto) { aviso.hidden = false; aviso.textContent = texto; return; }
        aviso.hidden = true;
        video.muted = _mntVivoMudo;
        if (taxa) taxa.textContent = `${video.videoWidth || ''}×${video.videoHeight || ''}`;
      },
    });
  };

  video.addEventListener('loadedmetadata', () => {
    if (taxa) taxa.textContent = `${video.videoWidth}×${video.videoHeight}`;
  });

  tampa.querySelectorAll('[data-mnt-q]').forEach(b => b.addEventListener('click', () => {
    const alta = b.dataset.mntQ === '1';
    if (alta === _mntVivoAlta) return;
    _mntVivoAlta = alta;
    tampa.querySelectorAll('[data-mnt-q]').forEach(x =>
      x.setAttribute('aria-pressed', String((x.dataset.mntQ === '1') === _mntVivoAlta)));
    ligar();
  }));

  tampa.querySelector('[data-mnt-foto]')?.addEventListener('click', () => {
    if (!video || video.readyState < 2) { showToast('Sem vídeo para capturar', true); return; }
    const canvas = document.createElement('canvas');
    canvas.width  = video.videoWidth  || 1280;
    canvas.height = video.videoHeight || 720;
    canvas.getContext('2d').drawImage(video, 0, 0);
    const ts = new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-');
    const a = document.createElement('a');
    a.download = `snapshot_${ip}_${ts}.png`;
    a.href = canvas.toDataURL('image/png');
    a.click();
    showToast('Frame salvo');
  });

  const btSom = tampa.querySelector('[data-mnt-som]');
  btSom?.addEventListener('click', () => {
    _mntVivoMudo = !_mntVivoMudo;
    video.muted = _mntVivoMudo;
    btSom.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${_mntVivoMudo ? _MNT_SVG.mudo : _MNT_SVG.som}</svg>`;
  });

  // Pelo agente: a camera esta atras do tunel do conector, entao um link
  // http://IP/ cru so abriria para quem estivesse na rede do cliente.
  tampa.querySelector('[data-mnt-web]')?.addEventListener('click', () => openDeviceWeb(ip, 80));

  tampa.querySelector('[data-mnt-reiniciar]')?.addEventListener('click', async () => {
    if (!confirm(`Reiniciar câmera ${ip}?`)) return;
    try {
      await api('/api/cameras/reboot', { method: 'POST', body: JSON.stringify({ ips: [ip] }) });
      showToast('Reboot enviado');
    } catch (e) { showToast('Erro ao reiniciar', true); }
  });

  tampa.querySelector('[data-mnt-tela]')?.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else palco?.requestFullscreen?.().catch(() => showToast('O navegador nao permitiu tela cheia.', true));
  });

  tampa.querySelector('[data-mnt-fechar]')?.addEventListener('click', closeMntStream);
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) closeMntStream();
  });

  ligar();
}

//  Modals de configuracao
function openMntMirrorModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntMirror').classList.remove('hidden');
  lucide.createIcons();
}

function openMntDayNightModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntDayNight').classList.remove('hidden');
  lucide.createIcons();
}

function openMntQualityModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  document.getElementById('modalMntQuality').classList.remove('hidden');
  lucide.createIcons();
}

function openMntNtpModal() {
  const n = document.querySelectorAll('.chk-mnt-cam:checked').length;
  if (!n) { showToast('Selecione ao menos uma camera', true); return; }
  const input = document.getElementById('mntNtpAddress');
  if (input && !input.value.trim()) input.value = 'time.cloudflare.com';
  document.getElementById('modalMntNtp')?.classList.remove('hidden');
  setTimeout(() => input?.focus(), 80);
  lucide.createIcons();
}

function closeMntNtpModal() {
  document.getElementById('modalMntNtp')?.classList.add('hidden');
}

function runMntNtp() {
  const input = document.getElementById('mntNtpAddress');
  const address = input?.value.trim() || 'time.cloudflare.com';
  closeMntNtpModal();
  _mntCamRunAction('ntp', { address });
}

function openMntRenameModal() {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const grid = document.getElementById('mntRenameRows');
  grid.innerHTML = ips.map(ip => {
    const card = document.querySelector(`.mnt-cam-card[data-ip="${CSS.escape(ip)}"]`);
    const titulo = card?.dataset.titulo || ip;
    return `<div style="display:flex;gap:8px;align-items:center;margin-bottom:6px">
      <span style="font-size:11px;color:var(--muted);min-width:100px;flex-shrink:0;font-family:monospace">${esc(ip)}</span>
      <input type="text" data-rename-ip="${esc(ip)}" value="${esc(titulo)}" style="flex:1;border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:13px">
    </div>`;
  }).join('');
  document.getElementById('modalMntRename').classList.remove('hidden');
  lucide.createIcons();
}

async function runMntRename() {
  const user = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntCamPass')?.value || '';
  const targets = [...document.querySelectorAll('[data-rename-ip]')].map(inp => ({
    ip: inp.dataset.renameIp, title: inp.value.trim()
  })).filter(t => t.title);
  if (!targets.length) return;
  document.getElementById('modalMntRename').classList.add('hidden');
  const body = document.getElementById('mntCamConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntCamConsole', 'mntCamConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] RENOMEAR ${targets.length} camera(s)`, true);
  try {
    const res  = await api('/api/maintenance/batch/rename', { method:'POST', body: JSON.stringify({ user, pass, targets }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => _mntLog('mntCamConsole', 'mntCamConsoleBody', r.ip || '', r.title ? ` "${r.title}" ${r.ok ? '' : ' ' + (r.error||'erro')}` : (r.error||'erro'), r.ok));
    showToast(data.message || 'Renomear: concluido');
    _mntCamAll = [];
    loadMntCam();
  } catch (err) {
    _mntLog('mntCamConsole', 'mntCamConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function runMntMirror() {
  const mirror = document.getElementById('mntMirrorCheck')?.checked || false;
  const flip   = document.getElementById('mntFlipCheck')?.checked || false;
  document.getElementById('modalMntMirror').classList.add('hidden');
  await _mntCamRunAction('mirror', { mirror, flip });
}

async function runMntDayNight() {
  const selected = document.querySelector('input[name="mntDayNightMode"]:checked');
  const mode = parseInt(selected?.value || '0');
  document.getElementById('modalMntDayNight').classList.add('hidden');
  await _mntCamRunAction('day_night', { mode });
}

async function runMntQuality() {
  const bitrate = parseInt(document.getElementById('mntQualityBitrate')?.value || '0') || null;
  const fps     = parseInt(document.getElementById('mntQualityFps')?.value || '0') || null;
  const codec   = document.getElementById('mntQualityCodec')?.value || '';
  document.getElementById('modalMntQuality').classList.add('hidden');
  await _mntCamRunAction('video_quality', { bitrate, fps, codec: codec || undefined });
}

//  Configuracao de rede em lote
function openMntNetworkModal() {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const rows = document.getElementById('mntNetRows');
  rows.innerHTML = ips.sort((a, b) => {
    const pa = a.split('.').map(Number), pb = b.split('.').map(Number);
    for (let i = 0; i < 4; i++) if (pa[i] !== pb[i]) return pa[i] - pb[i];
    return 0;
  }).map(ip => `
    <div style="display:flex;gap:8px;align-items:center">
      <span style="font-size:11px;color:var(--muted);min-width:110px;font-family:monospace;flex-shrink:0">${esc(ip)}</span>
      <span style="color:var(--muted)"></span>
      <input type="text" data-net-old="${esc(ip)}" value="${esc(ip)}"
        style="flex:1;border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:13px;font-family:monospace;background:var(--surface)">
    </div>`).join('');
  const ini = document.getElementById('mntNetStart');
  if (ini) ini.value = '';
  document.getElementById('modalMntNetwork').classList.remove('hidden');
  lucide.createIcons();
}

function mntNetPreencher() {
  const inicio = document.getElementById('mntNetStart')?.value.trim() || '';
  const m = inicio.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) { showToast('Informe o IP inicial, ex.: 10.200.1.120', true); return; }
  let n = m.slice(1).reduce((a, o) => a * 256 + Number(o), 0);
  for (const c of [...document.querySelectorAll('[data-net-old]')]) {
    const o = [24, 16, 8, 0].map(sh => (n >>> sh) & 255);
    // .0 e .255 sao rede e broadcast num /24 -- nao sao endereco de camera.
    if (o[3] === 0 || o[3] === 255) { n++; }
    const o2 = [24, 16, 8, 0].map(sh => (n >>> sh) & 255);
    c.value = o2.join('.');
    n++;
  }
}

async function runMntNetwork() {
  const mask    = document.getElementById('mntNetMask')?.value || '';
  const gateway = document.getElementById('mntNetGateway')?.value?.trim() || '';
  const user    = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass    = document.getElementById('mntCamPass')?.value || '';
  const targets = [...document.querySelectorAll('[data-net-old]')].map(inp => ({
    old_ip: inp.dataset.netOld, new_ip: inp.value.trim()
  })).filter(t => t.new_ip);

  if (!targets.length) return;
  if (targets.every(t => t.old_ip === t.new_ip)) {
    showToast('Nenhum IP foi alterado.', true); return;
  }
  document.getElementById('modalMntNetwork').classList.add('hidden');
  const consoleId = 'mntCamConsole', bodyId = 'mntCamConsoleBody';
  document.getElementById(consoleId)?.classList.remove('hidden');
  document.getElementById(bodyId).innerHTML = '';
  _mntLog(consoleId, bodyId, null, `Aplicando configuracao de rede em ${targets.length} camera(s)`, true);
  try {
    // change_ips le a mascara/gateway DE CADA camera. mask/gateway aqui so
    // viajam quando o operador preencheu -- mudanca de faixa de rede.
    const r = await api('/api/maintenance/batch/change_ips', {
      method: 'POST',
      body: JSON.stringify({
        itens: targets.map(t => ({ ip: t.old_ip, new_ip: t.new_ip })),
        mask, gateway, user, pass,
        forcar_rede: Boolean(mask && gateway),
      })
    });
    const data = await r.json();
    (data.results || []).forEach(res => {
      const detail = res.new_ip !== res.ip ? ` -> ${res.new_ip}` : '';
      const rede = res.rede_lida ? ` (mascara ${res.rede_lida.mascara})` : '';
      _mntLog(consoleId, bodyId, res.ip,
              `${detail}${rede} ${res.ok ? (res.msg || 'ok') : (res.error || res.msg || 'erro')}`, res.ok);
    });
    _mntLog(consoleId, bodyId, null, 'Concluido. Cameras reiniciam em ~30s.', true);
  } catch (e) {
    _mntLog(consoleId, bodyId, null, `Erro: ${e.message}`, false);
  }
}

//  Deslocar IPs em lote
function openMntShiftIpModal() {
  const firstIp = document.querySelector('.chk-mnt-cam:checked')?.value || '';
  if (firstIp) {
    const parts = firstIp.split('.');
    if (parts.length === 4) {
      document.getElementById('mntShiftPrefix').value = parts.slice(0, 3).join('.') + '.';
    }
  }
  _mntShiftPreview();
  document.getElementById('modalMntShiftIp').classList.remove('hidden');
  lucide.createIcons();
}

function _mntShiftPreview() {
  const prefix = document.getElementById('mntShiftPrefix')?.value || '';
  const start  = parseInt(document.getElementById('mntShiftStart')?.value || '');
  const end    = parseInt(document.getElementById('mntShiftEnd')?.value || '');
  const delta  = parseInt(document.getElementById('mntShiftDelta')?.value || '0');
  const box    = document.getElementById('mntShiftPreviewBox');
  if (!box) return;
  if (!prefix || isNaN(start) || isNaN(end) || isNaN(delta) || delta === 0 || start > end) {
    box.innerHTML = '<em style="color:var(--muted)">Preencha os campos acima</em>';
    return;
  }
  let octets = [];
  for (let i = start; i <= end; i++) octets.push(i);
  if (delta > 0) octets = octets.slice().reverse();
  const sign = delta > 0 ? '+' : '';
  const lines = octets.map(o => {
    const n = o + delta;
    const ok = n >= 1 && n <= 254;
    const color = ok ? 'var(--primary)' : 'var(--danger)';
    const warn  = ok ? '' : '  invalido';
    return `<div style="display:flex;gap:12px;padding:2px 0"><span style="opacity:.6;min-width:120px">${prefix}${o}</span><span style="color:var(--muted)"></span><span style="color:${color};font-weight:600">${prefix}${n}${warn}</span></div>`;
  });
  box.innerHTML = `<div style="margin-bottom:6px;opacity:.6;font-size:11px">Ordem de execucao (delta ${sign}${delta})  ${octets.length} camera(s)</div>` + lines.join('');
}

async function runMntShiftIp() {
  const prefix  = document.getElementById('mntShiftPrefix')?.value?.trim() || '';
  const start   = parseInt(document.getElementById('mntShiftStart')?.value || '');
  const end     = parseInt(document.getElementById('mntShiftEnd')?.value || '');
  const delta   = parseInt(document.getElementById('mntShiftDelta')?.value || '0');
  const user    = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass    = document.getElementById('mntCamPass')?.value || '';
  const gateway0 = document.getElementById('mntShiftGateway')?.value?.trim() || '';
  const mask    = document.getElementById('mntShiftMask')?.value?.trim() || '255.255.255.0';
  // o backend exige mascara E gateway; sem os dois ele recusa antes de falar com
  // a camera. Gateway vazio vira prefixo + 1, que e o que o rotulo do campo diz.
  const gateway = gateway0 || `${prefix}1`;

  if (!prefix || isNaN(start) || isNaN(end) || isNaN(delta) || delta === 0 || start > end) {
    showToast('Preencha todos os campos corretamente', true); return;
  }
  document.getElementById('modalMntShiftIp').classList.add('hidden');
  const consoleId = 'mntCamConsole', bodyId = 'mntCamConsoleBody';
  document.getElementById(consoleId)?.classList.remove('hidden');
  document.getElementById(bodyId).innerHTML = '';
  _mntLog(consoleId, bodyId, null, `Deslocando ${prefix}${start} ate ${prefix}${end} por ${delta > 0 ? '+' : ''}${delta}`, true);
  try {
    const r = await api('/api/maintenance/batch/shift_ips', {
      method: 'POST',
      body: JSON.stringify({ prefix, start_octet: start, end_octet: end, delta, user, pass, gateway, mask })
    });
    const data = await r.json();
    (data.results || []).forEach(res => {
      // o backend devolve 'error' quando falha e nada quando da certo;
      // ler 'msg' fazia toda linha (sucesso ou erro) sair como undefined
      const detalhe = res.error || res.msg || (res.ok ? 'OK' : 'falha');
      _mntLog(consoleId, bodyId, res.ip, `-> ${res.new_ip}  ${detalhe}`, res.ok);
    });
    _mntLog(consoleId, bodyId, null, 'Concluido. Aguarde as cameras reiniciarem (~30s).', true);
  } catch (e) {
    _mntLog(consoleId, bodyId, null, `Erro: ${e.message}`, false);
  }
}

function _mntLog(consoleId, bodyId, ip, msg, ok) {
  document.getElementById(consoleId)?.classList.remove('hidden');
  const body = document.getElementById(bodyId);
  if (body) {
    const line = document.createElement('div');
    line.className = 'mnt-res-linha';
    // O nome vem junto do IP: numero sozinho nao diz em QUEM a acao caiu, e
    // e nisso que se confere um lote antes de repetir.
    const card = ip ? document.querySelector(`.mnt-cam-card[data-ip="${CSS.escape(ip)}"]`) : null;
    const nome = card?.dataset.titulo || '';
    line.innerHTML =
      `<span class="mnt-res-selo ${ok ? 'ok' : 'falha'}">${ok ? 'feito' : 'falhou'}</span>` +
      (ip ? `<span class="mnt-res-alvo"><strong>${esc(nome || ip)}</strong>` +
            (nome ? `<small>${esc(ip)}</small>` : '') + `</span>` : '') +
      `<span class="mnt-res-msg">${esc(msg)}</span>`;
    body.appendChild(line);
    body.scrollTop = body.scrollHeight;
    _mntResumoLog(bodyId);
  }
  if (ip) {
    const res = document.getElementById(`mntRes_${ip.replace(/\./g,'_')}`);
    if (res) res.innerHTML = `<span style="color:${ok ? 'var(--primary)' : 'var(--danger)'}">${ok ? '' : ''} ${esc(msg)}</span>`;
  }
}

// Contagem no cabecalho: numa lista de 37 linhas, rolar ate o fim para saber
// quantas falharam e trabalho que a tela pode fazer.
function _mntResumoLog(bodyId) {
  const body = document.getElementById(bodyId);
  const alvo = document.getElementById('mntCamConsoleResumo');
  if (!body || !alvo) return;
  const feitas = body.querySelectorAll('.mnt-res-selo.ok').length;
  const falhas = body.querySelectorAll('.mnt-res-selo.falha').length;
  alvo.textContent = falhas
    ? `${feitas} feito${feitas !== 1 ? 's' : ''} · ${falhas} com falha`
    : `${feitas} feito${feitas !== 1 ? 's' : ''}`;
  alvo.classList.toggle('tem-falha', falhas > 0);
}

async function _mntCamRunAction(endpoint, extra = {}) {
  const ips = [...document.querySelectorAll('.chk-mnt-cam:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos uma camera', true); return; }
  const user = document.getElementById('mntCamUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntCamPass')?.value || '';

  const body = document.getElementById('mntCamConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntCamConsole', 'mntCamConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} camera(s)`, true);

  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass, ...extra }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => _mntLog('mntCamConsole', 'mntCamConsoleBody', r.ip || '', r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok));
    if (!(data.results || []).length) _mntLog('mntCamConsole', 'mntCamConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntCamConsole', 'mntCamConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function loadMntDvr() {
  const data  = await apiJson('/api/dvr/inventory');
  const dvrs  = data?.dvrs || data || [];
  const tbody = document.getElementById('mntDvrTable');
  const uniq  = new Map();
  dvrs.forEach(d => { if (!uniq.has(d.host || d.ip)) uniq.set(d.host || d.ip, d); });
  const rows = [...uniq.values()];
  if (!rows.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Nenhum DVR.</td></tr>'; return; }
  tbody.innerHTML = rows.map(d => {
    const ip = d.host || d.ip || '';
    return `<tr>
      <td><input type="checkbox" class="chk-mnt-dvr" value="${esc(ip)}"></td>
      <td class="monospace">${esc(ip)}</td>
      <td>${esc(d.brand || d.fabricante || '')} ${esc(d.model || d.modelo || '')}</td>
      <td>${esc(d.local || d.site || '')}</td>
      <td>${statusBadge(d.status)}</td>
      <td class="text-muted" id="mntDvrRes_${ip.replace(/\./g,'_')}"></td>
    </tr>`;
  }).join('');

  document.getElementById('chkMntDvrAll').onchange = function() {
    document.querySelectorAll('.chk-mnt-dvr').forEach(c => c.checked = this.checked);
    _mntDvrUpdateCount();
  };
  document.querySelectorAll('.chk-mnt-dvr').forEach(c => c.addEventListener('change', _mntDvrUpdateCount));
  _mntDvrUpdateCount();
}

function _mntDvrUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-dvr:checked').length;
  const el = document.getElementById('mntDvrSelectedCount');
  if (el) el.textContent = `${n} selecionado${n !== 1 ? 's' : ''}`;
}

async function _mntDvrRunAction(endpoint) {
  const ips = [...document.querySelectorAll('.chk-mnt-dvr:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos um DVR', true); return; }
  const user = document.getElementById('mntDvrUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntDvrPass')?.value || '';
  const body = document.getElementById('mntDvrConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} DVR(s)`, true);
  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => {
      const ip = r.ip || r.host || '';
      _mntLog('mntDvrConsole', 'mntDvrConsoleBody', ip, r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok);
      const el = document.getElementById(`mntDvrRes_${ip.replace(/\./g,'_')}`);
      if (el) el.innerHTML = `<span style="color:${r.ok ? 'var(--primary)' : 'var(--danger)'}">${r.ok ? '' : ''} ${esc(r.message || (r.ok ? 'OK' : 'Erro'))}</span>`;
    });
    if (!(data.results || []).length) _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntDvrConsole', 'mntDvrConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

async function loadMntNvr() {
  const data  = await apiJson('/api/nvr/inventory');
  const nvrs  = data?.nvrs || data || [];
  const tbody = document.getElementById('mntNvrTable');
  const uniq  = new Map();
  nvrs.forEach(n => { if (!uniq.has(n.host || n.ip)) uniq.set(n.host || n.ip, n); });
  const rows = [...uniq.values()];
  if (!rows.length) { tbody.innerHTML = '<tr class="empty-row"><td colspan="6">Nenhum NVR.</td></tr>'; return; }
  tbody.innerHTML = rows.map(n => {
    const ip = n.host || n.ip || '';
    return `<tr>
      <td><input type="checkbox" class="chk-mnt-nvr" value="${esc(ip)}"></td>
      <td class="monospace">${esc(ip)}</td>
      <td>${esc(n.brand || n.fabricante || '')} ${esc(n.model || n.modelo || '')}</td>
      <td>${esc(n.local || n.site || '')}</td>
      <td>${statusBadge(n.status)}</td>
      <td class="text-muted" id="mntNvrRes_${ip.replace(/\./g,'_')}"></td>
    </tr>`;
  }).join('');

  document.getElementById('chkMntNvrAll').onchange = function() {
    document.querySelectorAll('.chk-mnt-nvr').forEach(c => c.checked = this.checked);
    _mntNvrUpdateCount();
  };
  document.querySelectorAll('.chk-mnt-nvr').forEach(c => c.addEventListener('change', _mntNvrUpdateCount));
  _mntNvrUpdateCount();
}

function _mntNvrUpdateCount() {
  const n = document.querySelectorAll('.chk-mnt-nvr:checked').length;
  const el = document.getElementById('mntNvrSelectedCount');
  if (el) el.textContent = `${n} selecionado${n !== 1 ? 's' : ''}`;
}

async function _mntNvrRunAction(endpoint) {
  const ips = [...document.querySelectorAll('.chk-mnt-nvr:checked')].map(c => c.value);
  if (!ips.length) { showToast('Selecione ao menos um NVR', true); return; }
  const user = document.getElementById('mntNvrUser')?.value?.trim() || 'admin';
  const pass = document.getElementById('mntNvrPass')?.value || '';
  const body = document.getElementById('mntNvrConsoleBody');
  if (body) body.innerHTML = '';
  _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', `[${new Date().toLocaleTimeString('pt-BR')}] ${endpoint.toUpperCase()} em ${ips.length} NVR(s)`, true);
  try {
    const res  = await api(`/api/maintenance/batch/${endpoint}`, { method:'POST', body: JSON.stringify({ ips, user, pass }) });
    const data = await res.json().catch(() => ({}));
    (data.results || []).forEach(r => {
      const ip = r.ip || r.host || '';
      _mntLog('mntNvrConsole', 'mntNvrConsoleBody', ip, r.message || (r.ok ? 'OK' : r.error || 'Erro'), r.ok);
      const el = document.getElementById(`mntNvrRes_${ip.replace(/\./g,'_')}`);
      if (el) el.innerHTML = `<span style="color:${r.ok ? 'var(--primary)' : 'var(--danger)'}">${r.ok ? '' : ''} ${esc(r.message || (r.ok ? 'OK' : 'Erro'))}</span>`;
    });
    if (!(data.results || []).length) _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', data.message || 'Concluido', data.ok !== false);
    showToast(data.message || `${endpoint}: concluido`);
  } catch (err) {
    _mntLog('mntNvrConsole', 'mntNvrConsoleBody', '', err.message, false);
    showToast(err.message, true);
  }
}

//  Reproducao DVR
let _playbackBound = false;
