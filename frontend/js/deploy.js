function deploySetResult(html, isError = false) {
  const box = document.getElementById('deployLookupResult');
  if (!box) return;
  box.innerHTML = html || 'Aguardando consulta no conector.';
  box.classList.toggle('error', !!isError);
}

function deploySetRecorderLoginResult(html, isError = false) {
  const box = document.getElementById('deployRecorderLoginResult');
  if (!box) return;
  box.innerHTML = html || 'Informe host, usuario e senha do gravador e clique em Entrar.';
  box.classList.toggle('error', !!isError);
}

let _deployTituloDaCamera = '';
let _deployCanais = [];
let _deployCanaisFiltro = 'livres';

function deployRenderRecorderChannels(channels = []) {
  const input = document.getElementById('deployRecorderChannel');
  const toggle = document.getElementById('deployRecorderChannelButton');
  const labelEl = document.getElementById('deployRecorderChannelLabel');
  if (!input || !toggle || !labelEl) return;
  const previous = input.value;
  _deployCanais = Array.isArray(channels) ? channels : [];

  if (!_deployCanais.length) {
    input.value = '';
    labelEl.textContent = 'Entre no gravador';
    toggle.disabled = true;
    deployFecharCanais();
    return;
  }
  toggle.disabled = false;

  const livres = _deployCanais.filter(item => !item.used);
  const mantem = livres.some(item => String(item.channel) === String(previous));
  input.value = mantem ? previous : (livres[0]?.channel ? String(livres[0].channel) : '');
  // Com o gravador cheio o filtro abre em "todos": mostrar uma lista vazia
  // seria esconder justamente a informacao que resolve o problema.
  _deployCanaisFiltro = livres.length ? 'livres' : 'todos';
  deployAtualizarRotuloCanal();
}

function deployAtualizarRotuloCanal() {
  const input = document.getElementById('deployRecorderChannel');
  const btn = document.getElementById('deployRecorderChannelButton');
  if (!input || !btn) return;
  const livres = _deployCanais.filter(item => !item.used).length;
  let texto;
  if (!_deployCanais.length) texto = 'Entre no gravador';
  else if (livres) texto = 'Escolher canal e adicionar';
  else texto = 'Sem canal livre - ver quem ocupa';
  btn.innerHTML = `<i data-lucide="layout-grid"></i> <span id="deployRecorderChannelLabel">${esc(texto)}</span>`;
  try { lucide.createIcons(); } catch {}
}

function deployAbrirCanais() {
  if (!_deployCanais.length) return;
  document.getElementById('modalDeployCanais')?.classList.remove('hidden');
  deployPintarCanais();
  document.getElementById('deployCanaisBusca')?.focus();
}

function deployFecharCanais() {
  document.getElementById('modalDeployCanais')?.classList.add('hidden');
}

function deployPintarCanais() {
  const grade = document.getElementById('deployCanaisGrade');
  const resumo = document.getElementById('deployCanaisResumo');
  if (!grade) return;
  const escolhido = document.getElementById('deployRecorderChannel')?.value || '';
  const busca = (document.getElementById('deployCanaisBusca')?.value || '').trim().toLowerCase();

  document.querySelectorAll('#deployCanaisFiltro button').forEach(b => {
    b.setAttribute('aria-pressed', b.dataset.filtro === _deployCanaisFiltro ? 'true' : 'false');
  });

  const aviso = document.getElementById('deployCanaisAviso');
  if (aviso) {
    const p = deployPayload();
    const quem = [p.camera_title, p.camera_ip].filter(Boolean).join(' - ');
    // O clique grava num equipamento vivo. Dizer o que vai acontecer ANTES
    // e o que torna o clique unico aceitavel.
    aviso.textContent = quem
      ? `Ao escolher um canal livre, ${quem} entra nele agora.`
      : 'Preencha titulo e IP da camera na etapa anterior antes de escolher o canal.';
  }

  const livres = _deployCanais.filter(item => !item.used).length;
  if (resumo) {
    resumo.textContent = livres
      ? `${livres} de ${_deployCanais.length} canais livres.`
      : `Nenhum canal livre: os ${_deployCanais.length} estao em uso. Veja o que ocupa cada um para decidir qual substituir.`;
  }

  const visiveis = _deployCanais.filter(item => {
    if (_deployCanaisFiltro === 'livres' && item.used) return false;
    if (!busca) return true;
    return [item.title, item.camera_ip, String(item.channel)]
      .filter(Boolean).some(v => String(v).toLowerCase().includes(busca));
  });

  if (!visiveis.length) {
    grade.innerHTML = '<div class="deploy-canais-vazio">Nenhum canal com esse filtro.</div>';
    return;
  }

  grade.innerHTML = visiveis.map(item => {
    const ch = Number(item.channel || 0);
    const usado = !!item.used;
    const rotulo = String(ch).padStart(2, '0');
    const quem = [item.title, item.camera_ip].filter(Boolean).join(' - ');
    return `<button type="button"
      class="deploy-canal-card ${usado ? 'ocupado' : 'livre'}"
      data-channel="${esc(ch)}" ${usado ? 'disabled' : ''}
      aria-pressed="${!usado && String(ch) === String(escolhido) ? 'true' : 'false'}">
      <span class="num">${esc(rotulo)}</span>
      <span class="est">${usado ? 'Ocupado' : 'Livre'}</span>
      <span class="quem">${esc(quem || (usado ? 'camera sem titulo' : 'disponivel'))}</span>
    </button>`;
  }).join('');
}

function deployResetRecorderLogin() {
  deployRenderRecorderChannels();
  deploySetRecorderLoginResult();
}

function deployRecorderRowConnectorId(row) {
  return String(row?.remote_connector_id || row?.connector_id || '').trim();
}

function deployRecorderRowSite(row) {
  return String(row?.site || row?.local || row?.site_name || '').trim();
}

async function deployLoadAvailableRecorders() {
  const select = document.getElementById('deployRecorderHost');
  if (!select) return;
  const type = document.getElementById('deployRecorderType')?.value || '';
  const connectorId = deploySelectedConnectorId();
  const site = document.getElementById('deploySite')?.value.trim() || '';
  const previous = select.value;
  if (!type || (!connectorId && !deployIsLocalOrigin())) {
    _deployAvailableRecorders = [];
    select.innerHTML = '<option value="">Escolha primeiro o tipo e a origem</option>';
    deployResetRecorderLogin();
    return;
  }
  const data = await apiJson(`/api/${encodeURIComponent(type)}/inventory?site=`).catch(() => null);
  const rows = Array.isArray(data?.inventory) ? data.inventory : [];
  const unique = new Map();
  rows.forEach(row => {
    const host = String(row.host || row.ip || '').trim();
    if (!host) return;
    const rowConnector = deployRecorderRowConnectorId(row);
    const rowSite = deployRecorderRowSite(row);
    const sameConnector = connectorId && rowConnector === connectorId;
    const legacySameSite = connectorId && !rowConnector && site && rowSite.toLowerCase() === site.toLowerCase();
    const localAllowed = deployIsLocalOrigin() && (!site || rowSite.toLowerCase() === site.toLowerCase());
    if (!sameConnector && !legacySameSite && !localAllowed) return;
    unique.set(host, { ...(unique.get(host) || {}), ...row, host });
  });
  _deployAvailableRecorders = [...unique.values()].sort((a, b) => a.host.localeCompare(b.host, undefined, { numeric: true }));
  select.innerHTML = '<option value="">Escolha um gravador do inventario</option>' + _deployAvailableRecorders.map(row => {
    const label = [row.name || row.recorder_name, row.host, deployRecorderRowSite(row)].filter(Boolean).join(' - ');
    return `<option value="${esc(row.host)}">${esc(label)}</option>`;
  }).join('');
  if (_deployAvailableRecorders.some(row => row.host === previous)) select.value = previous;
  if (!_deployAvailableRecorders.length) select.innerHTML = '<option value="">Nenhum gravador acessivel neste conector/site</option>';
  deployResetRecorderLogin();
}

function deployRecorderPortaSelecionada() {
  // A porta vem do INVENTARIO, nao de um campo: quem cadastrou o gravador ja
  // informou, e no poste o tecnico nao tem como saber que aquele NVR atende
  // em 8086.
  const host = document.getElementById('deployRecorderHost')?.value.trim() || '';
  if (!host) return null;
  const row = (_deployAvailableRecorders || []).find(item => item.host === host);
  const porta = Number(row?.http_port || row?.port || 0);
  return Number.isFinite(porta) && porta > 0 ? porta : null;
}

function deployErroGravadorLegivel(bruto, payload) {
  // O erro cru do requests ("HTTPConnectionPool(host=..., port=80): Max
  // retries exceeded ... [Errno 111] Connection refused") e verdadeiro e
  // inutil: diz o IP VIRTUAL, que o tecnico nunca viu, e nao sugere nada.
  const texto = String(bruto || '');
  const alvo = `${payload.recorder_host || '?'}${payload.recorder_http_port ? ':' + payload.recorder_http_port : ''}`;
  if (/Connection refused|Max retries|NewConnectionError|Errno 111/i.test(texto)) {
    return `O gravador nao atendeu em ${alvo}. Confira a porta HTTP cadastrada dele (a tela Gravadores mostra e corrige).`;
  }
  if (/timed out|Read timed out|ConnectTimeout/i.test(texto)) {
    return `Sem resposta de ${alvo} dentro do tempo. O equipamento pode estar fora do ar.`;
  }
  if (/401|403|credencial|senha|unauthor/i.test(texto)) {
    return `${alvo} recusou a credencial. Informe usuario e senha de novo.`;
  }
  return texto || 'Falha ao entrar no gravador.';
}

function deployApplySelectedRecorder() {
  const host = document.getElementById('deployRecorderHost')?.value || '';
  const row = _deployAvailableRecorders.find(item => item.host === host);
  const user = document.getElementById('deployRecorderUser');
  if (user) user.value = String(row?.recorder_user || row?.user || 'admin');
  deployResetRecorderLogin();
  deployRenderSummary();
  deployUpdateStepLocks({ autoAdvance: true });

  // Gravador escolhido da lista do inventario ja teve a senha digitada uma
  // vez e guardada cifrada no servidor (`recorder_credentials`). Pedi-la de
  // novo e pedir ao tecnico que prove algo que o sistema ja sabe -- e no
  // poste, de celular, ele frequentemente NAO sabe: quem cadastrou foi outra
  // pessoa, meses atras.
  //
  // Entao: com senha guardada, escolher ja entra. Sem ela, os campos aparecem
  // -- e so nesse caso, porque ai a pergunta e legitima.
  // Os campos ficam SEMPRE visiveis: o usuario pediu assim, e faz sentido --
  // sao a saida quando a senha guardada envelheceu. Esconder transformava um
  // caso comum em beco sem saida.
  const temSenha = !!host && recTemSenhaSalva(host);
  if (!host) return;
  if (temSenha) {
    deployRecorderLogin();
  } else {
    deploySetRecorderLoginResult('Este gravador ainda nao tem senha guardada. Informe usuario e senha uma vez: as proximas entradas serao diretas.');
  }
}

function deployScheduleAvailableRecorders() {
  clearTimeout(_deployRecorderListTimer);
  _deployRecorderListTimer = setTimeout(deployLoadAvailableRecorders, 250);
}

function deployStepState() {
  const p = deployPayload();
  const step1Done = Boolean(deployOriginReady() && p.site);
  // O portao tem que ser o MESMO que o registro cobra, senao o botao morre sem
  // dizer por que. `deployCommitCamera` exige titulo, IP e site -- nunca a
  // senha da camera. Mas aqui a senha entrava na conta, entao
  // `btnDeployCommitCamera.disabled` ficava ligado e o tecnico olhava um botao
  // apagado sem nenhuma mensagem explicando o que faltava.
  //
  // Senha da camera serve para TRAZER dados (fabricante, modelo, gravar o
  // titulo nela) -- e `deployPushTitleToCamera` ja trata a falta dela como
  // "skipped", sem erro. Camera com senha trocada, sem senha anotada ou fora do
  // ar segue sendo camera que precisa estar no inventario.
  //
  // De tabela, isso tambem destravava a etapa 3 cedo demais... na verdade
  // tarde demais: vincular no NVR usa a senha do GRAVADOR (etapa 3) e o IP da
  // camera, nunca a senha da camera. O tecnico ficava sem conseguir abrir a
  // etapa 3 por causa de uma credencial que aquela etapa nao usa.
  const step2Done = step1Done && Boolean(p.camera_ip && p.camera_title);
  const step3Done = step2Done && Boolean(p.recorder_type && p.recorder_host && p.recorder_channel);
  return {
    step1Done,
    step2Unlocked: step1Done,
    step2Done,
    step3Unlocked: step2Done,
    step3Done,
  };
}

function deployAbaDaEtapa(id) {
  return document.querySelector('#deployForm .cftv-nav [data-passo="' + id + '"]');
}

function deploySetStepState(id, { locked = false, complete = false, ready = false } = {}) {
  // O estado agora mora em DOIS lugares: o painel e a aba que o seleciona.
  // A aba e o unico sinal visivel quando o painel esta escondido -- se ela
  // nao refletisse o estado, o tecnico nao teria como saber que a etapa 3
  // destravou sem clicar nela para descobrir.
  const el = document.getElementById(id);
  const aba = deployAbaDaEtapa(id);
  [el, aba].forEach(n => {
    if (!n) return;
    n.classList.toggle('onu-step-locked', locked);
    n.classList.toggle('onu-step-complete', complete);
    n.classList.toggle('onu-step-ready', ready && !locked && !complete);
  });
  if (aba) aba.setAttribute('aria-disabled', locked ? 'true' : 'false');
}

function deployOpenStep(id, { forcar = false } = {}) {
  // `forcar` existe para um caso so: quando NADA esta liberado, alguma coisa
  // ainda precisa aparecer. Um acordeao podia ficar todo fechado; uma area de
  // conteudo em branco seria a tela quebrada. Entao a etapa 2 aparece travada,
  // com o recado da barra dizendo o que falta.
  const alvo = document.getElementById(id);
  if (!alvo) return;
  if (!forcar && alvo.classList.contains('onu-step-locked')) return;
  document.querySelectorAll('#deployForm .cftv-painel').forEach(p => { p.hidden = p !== alvo; });
  document.querySelectorAll('#deployForm .cftv-nav [data-passo]').forEach(b => {
    b.setAttribute('aria-current', b.dataset.passo === id ? 'true' : 'false');
  });
}

function deployUpdateStepLocks({ autoAdvance = false } = {}) {
  const state = deployStepState();
  const wasStep2Locked = document.getElementById('cftvStep2')?.classList.contains('onu-step-locked');
  const wasStep3Locked = document.getElementById('cftvStep3')?.classList.contains('onu-step-locked');

  deploySetStepState('cftvStep2', {
    locked: !state.step2Unlocked,
    complete: state.step2Done,
    ready: state.step2Unlocked && !state.step2Done,
  });
  deploySetStepState('cftvStep3', {
    locked: !state.step3Unlocked,
    complete: state.step3Done,
    ready: state.step3Unlocked && !state.step3Done,
  });

  // A etapa 1 saiu: virou a barra de contexto, sempre visivel. Sobrou decidir
  // qual painel mostrar, e ha sempre um -- diferente do acordeao, que podia
  // ficar inteiro fechado.
  const aberto = document.querySelector('#deployForm .cftv-painel:not([hidden])');
  if (!state.step2Unlocked) {
    deployOpenStep('cftvStep2', { forcar: true });
  } else if (!aberto || aberto.classList.contains('onu-step-locked')) {
    deployOpenStep('cftvStep2');
  } else if (autoAdvance && wasStep2Locked) {
    deployOpenStep('cftvStep2');
  } else if (autoAdvance && state.step3Unlocked && wasStep3Locked) {
    deployOpenStep('cftvStep3');
  }

  const commitBtn = document.getElementById('btnDeployCommitCamera');
  if (commitBtn) commitBtn.disabled = !state.step2Done;
}

function deployEnsureStepUnlocked(stepId, message) {
  deployUpdateStepLocks();
  const step = document.getElementById(stepId);
  if (step?.classList.contains('onu-step-locked')) {
    showToast(message || 'Conclua a etapa anterior primeiro.', true);
    return false;
  }
  return true;
}

function deployBindStepGuards() {
  document.querySelectorAll('#deployForm .cftv-nav [data-passo]').forEach(aba => {
    if (aba.dataset.deployGuardBound === '1') return;
    aba.dataset.deployGuardBound = '1';
    aba.addEventListener('click', () => {
      deployUpdateStepLocks();
      const id = aba.dataset.passo;
      const painel = document.getElementById(id);
      if (painel?.classList.contains('onu-step-locked')) {
        // A etapa 1 nao existe mais como etapa, entao a recusa nao pode mais
        // mandar "conclua a etapa 1": tem que apontar para onde a coisa esta.
        showToast(id === 'cftvStep2'
          ? 'Escolha o site na barra de cima para liberar a camera.'
          : 'Preencha titulo e IP da camera para liberar o gravador.', true);
        return;
      }
      deployOpenStep(id);
    });
  });
}

function deploySelectRecorderChannel(channel) {
  const input = document.getElementById('deployRecorderChannel');
  if (!input || !channel) return;
  const alvo = _deployCanais.find(item => String(item.channel) === String(channel));
  if (!alvo || alvo.used) return;
  input.value = String(channel);
  deployAtualizarRotuloCanal();
  deployFecharCanais();
  deployRenderSummary();
  // Escolher o canal E a ordem de adicionar. Guardar a escolha e esperar um
  // segundo clique num botao separado nao protegia de nada: o modal ja diz,
  // antes do clique, qual camera entra em qual canal.
  deployRecorderAddCamera();
}

async function deployLoadRecorderChannels() {
  const payload = deployPayload();
  if (!payload.recorder_type || !payload.recorder_host) {
    deployRenderRecorderChannels();
    return;
  }
  try {
    const res = await api('/api/deployments/recorder-channels', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (res?.ok && data?.ok !== false) {
      deployRenderRecorderChannels(Array.isArray(data.channels) ? data.channels : []);
      deployRenderSummary();
    }
  } catch (err) {
    console.warn('Falha ao carregar canais do gravador', err);
  }
}

function deployRenderSummary() {
  const p = deployPayload();
  const conn = deploySelectedConnector();
  const rows = [
    ['Conector', conn ? `${conn.name || conn.id} / ${conn.site || '-'}` : '-'],
    ['Camera', [p.camera_title, p.camera_ip].filter(Boolean).join(' - ') || '-'],
    ['MAC camera', p.camera_mac || '-'],
    ['Gravador', [p.recorder_type?.toUpperCase(), p.recorder_host, p.recorder_channel && `CH ${p.recorder_channel}`].filter(Boolean).join(' / ') || '-'],
    ['Site', p.site || '-'],
  ];
  const filled = [p.connector_id, p.site, p.camera_ip, p.camera_title].filter(Boolean).length;
  const summary = document.getElementById('deploySummary');
  const status = document.getElementById('deploySummaryStatus');
  if (status) status.textContent = filled >= 4 ? 'Pronto para registrar camera.' : 'Preencha conector, site, IP e titulo.';
  if (summary) {
    summary.innerHTML = rows.map(([k, v]) => `<div><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
  }
  deployUpdateStepLocks();
}

async function loadDeployHistory() {
  const box = document.getElementById('deployHistory');
  if (!box) return;
  const data = await apiJson('/api/deployments');
  const rows = Array.isArray(data?.deployments) ? data.deployments : [];
  if (!rows.length) {
    box.innerHTML = '<div class="deployment-history-empty">Nenhuma implantacao salva ainda.</div>';
    return;
  }
  box.innerHTML = rows.slice(0, 12).map(r => `
    <div class="deployment-history-item">
      <b>${esc(r.camera_title || r.title || 'Sem titulo')}</b>
      <span>${esc(r.camera_ip || '-')} ${r.site ? `- ${esc(r.site)}` : ''}</span>
      <small>${esc(r.status || 'rascunho')} ${r.updated_at ? `- ${esc(r.updated_at)}` : ''}</small>
    </div>
  `).join('');
}

async function loadDeploySites() {
  const list = document.getElementById('deploySiteList');
  if (!list) return;
  const modes = ['olt', 'basico', 'switch'];
  const results = await Promise.all(modes.map(mode => apiJson(`/api/cameras?mode=${encodeURIComponent(mode)}`).catch(() => null)));
  const sites = new Set();
  results.forEach(data => {
    const rows = Array.isArray(data?.cameras) ? data.cameras : (Array.isArray(data?.rows) ? data.rows : []);
    rows.forEach(row => {
      const site = String(row.site || row.site_name || row.local || '').trim();
      if (site) sites.add(site);
    });
  });
  _deploySites = [...sites].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  list.innerHTML = _deploySites.map(site => `<option value="${esc(site)}"></option>`).join('');
}

let _deployOltRows = [];

function deployOltMatchesOrigin(row, originValue) {
  const rowConnector = String(row?.connector_id || '').trim();
  const origin = String(originValue || '').trim();
  if (originValue === DEPLOY_LOCAL_ORIGIN || originValue === '__local__') return !rowConnector;
  if (!origin) return false;
  if (rowConnector === origin) return true;
  const connector = typeof _connectorById === 'function' ? _connectorById(origin) : null;
  if (!connector) return false;
  const rowTerms = [row?.site, row?.name, row?.host].map(_connectorNorm).filter(Boolean);
  const connectorTerms = [connector.site, connector.client, connector.name].map(_connectorNorm).filter(Boolean);
  return rowTerms.some(rowTerm =>
    connectorTerms.some(connTerm =>
      rowTerm === connTerm
      || rowTerm.includes(connTerm)
      || connTerm.includes(rowTerm)
    )
  );
}

function deployOltOptionsForOrigin(originValue) {
  return _deployOltRows.filter(row => deployOltMatchesOrigin(row, originValue));
}

function deployLoadOltContextOptions(data) {
  const select = document.getElementById('deployOltContext');
  if (!select) return;
  _deployOltRows = (Array.isArray(data?.items) ? data.items : []).filter(row => row?.active);
  deployRenderOltContextForOrigin();
}

function deployRenderOltContextForOrigin() {
  const select = document.getElementById('deployOltContext');
  if (!select) return;
  const origin = document.getElementById('deployConnector')?.value || '';
  const rows = deployOltOptionsForOrigin(origin);
  select.disabled = !origin;
  select.innerHTML = !origin
    ? '<option value="">Escolha primeiro o conector</option>'
    : '<option value="">Sem OLT vinculada / informar manualmente</option>'
      + rows.map(row => `<option value="${esc(row.id)}">${esc(row.name)} - ${esc(row.site || 'sem site')} - ${esc(row.host)}</option>`).join('');
}

function deployApplyOltContext() {
  const id = document.getElementById('deployOltContext')?.value || '';
  const olt = _deployOltRows.find(row => String(row.id) === String(id));
  if (!olt) return;
  const site = document.getElementById('deploySite');
  if (site) site.value = olt.site || '';
  deployRenderConnectorStatus();
  deployRenderSummary();
  deployUpdateStepLocks({ autoAdvance: true });
  deployLoadAvailableRecorders();
}

async function loadDeployNew() {
  const sel = document.getElementById('deployConnector');
  if (!sel) return;
  const [data, oltData] = await Promise.all([
    apiJson('/api/connectors'),
    apiJson('/api/olt/registry'),
    loadDeploySites(),
  ]);
  _deployConnectors = (Array.isArray(data?.connectors) ? data.connectors : [])
    .filter(c => _connectorNorm(c.type) === 'routeros');
  const connectorOptions = _deployConnectors
    .map(c => {
      const online = deployConnectorOnline(c);
      const tunnel = deployConnectorVpnReady(c);
      const disabled = online && tunnel ? '' : 'disabled';
      const suffix = !online ? ' (offline)' : (!tunnel ? ' (sem VPN)' : ' + VPN');
      return `<option value="${esc(deployConnectorKey(c))}" ${disabled}>${esc(deployConnectorLabel(c))}${suffix}</option>`;
    })
    .join('');
  sel.innerHTML = `<option value="">Escolha o site</option><option value="${DEPLOY_LOCAL_ORIGIN}">Local / VPN do servidor</option>${connectorOptions}`;
  sel.value = '';
  deployLoadOltContextOptions(oltData);
  deploymentApplyPreferredInventoryMode();
  deployApplyOriginFields();
  deploySetResult('Aguardando consulta no conector.');
  deployRenderConnectorStatus();
  deployRenderSummary();
  deployOpenStep('cftvStep2', { forcar: true });
  await recCarregarSenhasSalvas();
  await loadDeployHistory();
  bindAccordionExclusive('#viewDeployNew');
  deployBindStepGuards();
  await deployLoadAvailableRecorders();
  lucide.createIcons();
}

// Implantacao - Gravadores
let _deployStandaloneRecorderProbe = null;
let _deployStandaloneRecorderSaved = false;
let _deployRecorderSelectedChannel = 0;
let _deployStandaloneRecorderSavedItems = [];

// Gravadores com senha ja guardada no servidor (cifrada). So host/porta/usuario
// trafegam -- a senha nunca sai do backend. Serve para a tela saber quem entra
// com um clique e para quem ainda falta perguntar.
let _recSenhasSalvas = [];

async function recCarregarSenhasSalvas() {
  try {
    const dados = await apiJson('/api/deployments/recorder-credenciais');
    _recSenhasSalvas = Array.isArray(dados?.credenciais) ? dados.credenciais : [];
  } catch (_) {
    _recSenhasSalvas = [];
  }
}

function recTemSenhaSalva(host, porta) {
  const h = String(host || '').trim().toLowerCase();
  if (!h) return false;
  return _recSenhasSalvas.some(x => String(x.host || '').toLowerCase() === h);
}
let _deployStandaloneRecorderNetworkLoaded = false;
let _deployStandaloneRecorderModalMode = 'create';

function deployStandaloneRecorderPayload() {
  // Vazio de proposito: o backend pergunta ao gravador quantos canais ele tem.
  // Mandar 32 aqui fazia um gravador de 16 mostrar 16 canais que nao existem.
  const channels = Number(document.getElementById('deployStandaloneRecorderChannelTotal')?.value || 0);
  return {
    olt_id: Number(document.getElementById('deployStandaloneRecorderOlt')?.value || 0) || null,
    connector_id: deployStandaloneRecorderSelectedConnectorId(),
    inventory_mode: document.getElementById('deployStandaloneRecorderInventoryMode')?.value || 'basic',
    recorder_type: document.getElementById('deployStandaloneRecorderType')?.value || 'nvr',
    recorder_host: document.getElementById('deployStandaloneRecorderHost')?.value.trim() || '',
    recorder_http_port: Number(document.getElementById('deployStandaloneRecorderPort')?.value || 80),
    recorder_user: document.getElementById('deployStandaloneRecorderUser')?.value.trim() || 'admin',
    recorder_password: document.getElementById('deployStandaloneRecorderPassword')?.value || '',
    recorder_channel_total: Number.isFinite(channels) && channels > 0 ? channels : 32,
    channel_total: Number.isFinite(channels) && channels > 0 ? channels : 32,
    site: document.getElementById('deployStandaloneRecorderSite')?.value.trim() || '',
    name: document.getElementById('deployStandaloneRecorderName')?.value.trim() || '',
  };
}

function deployStandaloneRecorderConnectorValue() {
  return document.getElementById('deployStandaloneRecorderConnector')?.value || '';
}

function deployStandaloneRecorderSelectedConnectorId() {
  const value = deployStandaloneRecorderConnectorValue();
  return value && value !== DEPLOY_LOCAL_ORIGIN ? value : '';
}

function deployStandaloneRecorderSelectedConnector() {
  const id = deployStandaloneRecorderSelectedConnectorId();
  return _deployConnectors.find(c => deployConnectorKey(c) === id) || null;
}

function deployStandaloneRecorderOriginReady() {
  const value = deployStandaloneRecorderConnectorValue();
  if (value === DEPLOY_LOCAL_ORIGIN) return true;
  const connector = deployStandaloneRecorderSelectedConnector();
  return Boolean(connector && deployConnectorOnline(connector) && deployConnectorVpnReady(connector));
}

function deployStandaloneRecorderUpdateConnectorGate() {
  const ready = deployStandaloneRecorderOriginReady();
  const connector = deployStandaloneRecorderSelectedConnector();
  const site = document.getElementById('deployStandaloneRecorderSite');
  document.querySelectorAll('[data-recorder-needs-connector="1"]').forEach(el => {
    el.disabled = !ready;
    el.classList.toggle('is-disabled', !ready);
  });
  if (site) {
    site.readOnly = false;
    if (connector) site.value = deployConnectorSite(connector);
    if (!deployStandaloneRecorderConnectorValue()) site.value = '';
  }
}

function deployStandaloneRecorderRenderConnectorStatus() {
  const box = document.getElementById('deployStandaloneRecorderConnectorStatus');
  if (!box) return;
  const value = deployStandaloneRecorderConnectorValue();
  if (!value) {
    box.innerHTML = 'Escolha Local/VPN do servidor ou um conector online com VPN. Os dados do gravador ficam bloqueados ate definir a origem.';
    box.classList.add('error');
  } else if (value === DEPLOY_LOCAL_ORIGIN) {
    box.innerHTML = '<b style="color:var(--primary)">Modo local</b> -- usando o servidor/VPN ja roteada. Informe o site correto do gravador.';
    box.classList.remove('error');
  } else {
    const connector = deployStandaloneRecorderSelectedConnector();
    const online = deployConnectorOnline(connector);
    const tunnel = deployConnectorVpnReady(connector);
    box.innerHTML = online
      ? `<b style="color:var(--primary)">Conector online</b> -- ${esc(deployConnectorLabel(connector))}${tunnel ? ' -- VPN ativa para acessar o gravador.' : ' -- sem VPN configurada: o acesso fica bloqueado.'}`
      : `<b style="color:var(--danger)">Conector offline</b> -- ${esc(deployConnectorLabel(connector) || 'conector indisponivel')}.`;
    box.classList.toggle('error', !online || !tunnel);
  }
  deployStandaloneRecorderUpdateConnectorGate();
}

async function deployStandaloneRecorderLoadConnectors() {
  const select = document.getElementById('deployStandaloneRecorderConnector');
  if (!select) return;
  const data = await apiJson('/api/connectors');
  _deployConnectors = (Array.isArray(data?.connectors) ? data.connectors : [])
    .filter(c => _connectorNorm(c.type) === 'routeros');
  select.innerHTML = `<option value="">Escolha a origem de acesso</option><option value="${DEPLOY_LOCAL_ORIGIN}">Local / VPN do servidor</option>` + _deployConnectors.map(c => {
    const online = deployConnectorOnline(c);
    const tunnel = deployConnectorVpnReady(c);
    const disabled = online && tunnel ? '' : 'disabled';
    const suffix = !online ? ' (offline)' : (!tunnel ? ' (sem VPN)' : ' + VPN');
    return `<option value="${esc(deployConnectorKey(c))}" ${disabled}>${esc(deployConnectorLabel(c))}${suffix}</option>`;
  }).join('');
  select.value = '';
  deployStandaloneRecorderRenderConnectorStatus();
}

async function deployStandaloneRecorderLoadOlts() {
  const select = document.getElementById('deployStandaloneRecorderOlt');
  if (!select) return;
  const data = await apiJson('/api/olt/registry');
  const rows = (Array.isArray(data?.items) ? data.items : []).filter(row => row?.active);
  _deployOltRows = rows;
  deployStandaloneRecorderRenderOltsForOrigin();
}

function deployStandaloneRecorderRenderOltsForOrigin() {
  const select = document.getElementById('deployStandaloneRecorderOlt');
  if (!select) return;
  const origin = deployStandaloneRecorderConnectorValue();
  const rows = deployOltOptionsForOrigin(origin);
  select.disabled = !origin;
  select.innerHTML = !origin
    ? '<option value="">Escolha primeiro o conector</option>'
    : '<option value="">Sem OLT vinculada / informar manualmente</option>'
      + rows.map(row => `<option value="${esc(row.id)}">${esc(row.name)} - ${esc(row.site || 'sem site')} - ${esc(row.host)}</option>`).join('');
  deployStandaloneRecorderRenderSaved();
  deployRecorderPintarLista();
}

function deployStandaloneRecorderApplyOlt() {
  const id = document.getElementById('deployStandaloneRecorderOlt')?.value || '';
  const olt = _deployOltRows.find(row => String(row.id) === String(id));
  const site = document.getElementById('deployStandaloneRecorderSite');
  if (site) site.value = olt ? (olt.site || '') : '';
  deployStandaloneRecorderClearRecorderFields({ keepConnector: true, keepOlt: true, keepSite: true });
  deployStandaloneRecorderRenderSaved();
  deployStandaloneRecorderRenderProbe(_deployStandaloneRecorderProbe);
}

function deployStandaloneRecorderChannelsFromProbe(data = null) {
  const channels = Array.isArray(data?.channels) ? data.channels : [];
  return channels.map((item, idx) => {
    const channel = Number(item.channel || item.ch || idx + 1);
    const cameraIp = item.camera_ip || item.ip || item.remote_ip || '';
    const title = item.title || item.name || item.channel_name || '';
    const used = item.used !== undefined ? !!item.used : !!(cameraIp || title || item.enabled);
    return { ...item, channel, camera_ip: cameraIp, title, used };
  });
}

function deployRecorderChannelSnapshotUrl(item) {
  const raw = String(item?.snapshot_url || item?.imgbb_url || '').trim();
  if (!raw) return '';
  return /^https?:\/\//i.test(raw) ? raw : `${API_BASE}${raw}`;
}

function deployRenderRecorderChannelDetail(item = null) {
  const detail = document.getElementById('deployRecorderChannelDetail');
  const drawer = document.getElementById('deployRecorderChannelDrawer');
  const backdrop = document.getElementById('deployRecorderChannelDrawerBackdrop');
  if (!detail || !drawer || !backdrop) return;
  if (!item) {
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    backdrop.classList.remove('open');
    detail.innerHTML = '';
    return;
  }
  const snapshot = deployRecorderChannelSnapshotUrl(item);
  const channel = String(item.channel || '').padStart(2, '0');
  drawer.classList.add('open');
  drawer.setAttribute('aria-hidden', 'false');
  backdrop.classList.add('open');
  detail.innerHTML = `
    <div class="recorder-channel-detail-head"><div><span>CANAL ${esc(channel)}</span><h4>${esc(item.title || (item.used ? 'Canal ocupado' : 'Canal livre'))}</h4></div><button type="button" data-recorder-channel-action="close" aria-label="Fechar"><i data-lucide="x"></i></button></div>
    <div class="recorder-channel-preview">${snapshot ? `<img src="${esc(snapshot)}" alt="Snapshot do canal ${esc(channel)}">` : '<div><i data-lucide="image-off"></i><span>Sem snapshot</span></div>'}</div>
    <div class="recorder-channel-fields">
      <div><span>Status</span><b>${item.used ? 'Ocupado' : 'Livre'}</b></div>
      <div><span>IP da camera</span><b class="monospace">${esc(item.camera_ip || '-')}</b></div>
      <div><span>Modelo</span><b>${esc(item.camera_model || item.model || '-')}</b></div>
      <div><span>MAC</span><b class="monospace">${esc(item.camera_mac || item.mac || '-')}</b></div>
    </div>
    <div class="recorder-channel-detail-actions">
      ${item.used ? '<button type="button" class="secondary-action" data-recorder-channel-action="refresh"><i data-lucide="refresh-cw"></i> Atualizar</button><button type="button" class="secondary-action" data-recorder-channel-action="web"><i data-lucide="globe"></i> Web</button><button type="button" class="primary-action" data-recorder-channel-action="ping"><i data-lucide="activity"></i> Ping</button><button type="button" class="secondary-action danger-action" data-recorder-channel-action="delete"><i data-lucide="trash-2"></i> Excluir canal</button>' : '<button type="button" class="primary-action" data-recorder-channel-action="add"><i data-lucide="plus-circle"></i> Adicionar camera</button>'}
    </div>`;
  lucide.createIcons();
}

function deployRenderStandaloneRecorderChannels() {
  const grid = document.getElementById('deployStandaloneRecorderChannels');
  const counters = document.getElementById('deployRecorderChannelCounters');
  if (!grid || !counters) return;
  const channels = deployStandaloneRecorderChannelsFromProbe(_deployStandaloneRecorderProbe);
  const search = (document.getElementById('deployRecorderChannelSearch')?.value || '').trim().toLowerCase();
  const filter = document.getElementById('deployRecorderChannelFilter')?.value || 'all';
  const used = channels.filter(item => item.used).length;
  const free = channels.length - used;
  const missingModel = channels.filter(item => item.used && !(item.camera_model || item.model)).length;
  const missingSnapshot = channels.filter(item => item.used && !deployRecorderChannelSnapshotUrl(item)).length;
  counters.innerHTML = `<span><b>${esc(channels.length)}</b> total</span><span class="online"><b>${esc(used)}</b> ocupados</span><span class="free"><b>${esc(free)}</b> livres</span><span class="warning"><b>${esc(missingModel)}</b> sem modelo</span><span class="warning"><b>${esc(missingSnapshot)}</b> sem snapshot</span>`;
  const visible = channels.filter(item => {
    if (filter === 'used' && !item.used) return false;
    if (filter === 'free' && item.used) return false;
    if (filter === 'no_model' && (!item.used || item.camera_model || item.model)) return false;
    if (filter === 'no_snapshot' && (!item.used || deployRecorderChannelSnapshotUrl(item))) return false;
    if (search && ![item.channel, item.title, item.camera_ip, item.camera_model, item.model, item.camera_mac].some(value => String(value || '').toLowerCase().includes(search))) return false;
    return true;
  });
  if (!visible.length) {
    grid.innerHTML = '<div class="recorder-deploy-empty">Nenhum canal encontrado neste filtro.</div>';
  } else {
    // Mosaico: a imagem OCUPA o quadro, como na tela do proprio DVR. O cartao
    // claro com miniatura espremida ao lado do texto nao deixava ver nada --
    // num mosaico de cameras quem manda e a imagem, o resto e legenda.
    grid.innerHTML = visible.map(item => {
      const snapshot = deployRecorderChannelSnapshotUrl(item);
      const ch = String(item.channel || '').padStart(2, '0');
      const titulo = item.title || (item.used ? 'Sem titulo' : '');
      const sel = Number(item.channel) === _deployRecorderSelectedChannel ? ' selecionado' : '';
      if (!item.used) {
        return `<button type="button" class="recorder-quadro livre${sel}" data-recorder-channel="${esc(item.channel)}" title="Canal ${esc(ch)} livre">
          <span class="q-num">${esc(ch)}</span>
          <span class="q-vazio"><i data-lucide="plus"></i>livre</span>
        </button>`;
      }
      return `<button type="button" class="recorder-quadro${sel}" data-recorder-channel="${esc(item.channel)}" title="${esc([titulo, item.camera_ip].filter(Boolean).join(' - '))}">
        <span class="q-num">${esc(ch)}</span>
        ${snapshot ? `<img src="${esc(snapshot)}" alt="" loading="lazy">`
                   : `<span class="q-sem"><i data-lucide="image-off"></i>sem imagem</span>`}
        <span class="q-faixa">${esc(titulo || item.camera_ip || 'canal ' + ch)}</span>
      </button>`;
    }).join('');
  }
  const selected = channels.find(item => Number(item.channel) === _deployRecorderSelectedChannel) || null;
  deployRenderRecorderChannelDetail(selected);
  lucide.createIcons();
}

function deployStandaloneRecorderSetResult(html, isError = false) {
  const box = document.getElementById('deployStandaloneRecorderResult');
  if (!box) return;
  box.innerHTML = html || 'Entre no gravador para validar modelo, serial e canais.';
  box.classList.toggle('error', !!isError);
}

function deployStandaloneRecorderSetQuickResult(html, isError = false) {
  const box = document.getElementById('deployStandaloneRecorderQuickResult');
  if (!box) return;
  box.innerHTML = html || 'Entre no gravador para liberar as configuracoes rapidas.';
  box.classList.toggle('error', !!isError);
}

function deployStandaloneRecorderRenderLoginProgress(payload) {
  const summary = document.getElementById('deployStandaloneRecorderSummary');
  const headStatus = document.getElementById('deployRecorderDiscoveryStatus');
  if (headStatus) {
    headStatus.className = 'recorder-head-status loading';
    headStatus.innerHTML = '<i data-lucide="loader"></i><span>Conectando</span>';
  }
  if (summary) {
    summary.innerHTML = `
      <div class="recorder-discovery-empty recorder-discovery-loading">
        <i data-lucide="loader"></i>
        <div>
          <b>Entrando no gravador ${esc(payload.recorder_host)}</b>
          <span>Validando credenciais, coletando modelo, serial e canais. Isso pode levar alguns segundos pela VPN.</span>
        </div>
      </div>
      <div class="recorder-discovery-checklist">
        <div class="done"><i data-lucide="check"></i><span><b>1. Conector</b><small>Origem de acesso definida</small></span></div>
        <div class="done active"><i data-lucide="loader"></i><span><b>2. Login</b><small>Aguardando resposta do gravador</small></span></div>
        <div><i data-lucide="circle"></i><span><b>3. Canais</b><small>Proxima coleta</small></span></div>
        <div><i data-lucide="circle"></i><span><b>4. Inventario</b><small>Revisar e salvar</small></span></div>
      </div>
    `;
  }
  deployStandaloneRecorderSetQuickResult(`Aguardando resposta de ${esc(payload.recorder_host)} antes de liberar as acoes.`);
  lucide.createIcons();
}

function deployStandaloneRecorderSetModalMode(mode = 'create') {
  _deployStandaloneRecorderModalMode = mode === 'entry' ? 'entry' : 'create';
  const title = document.getElementById('deployStandaloneRecorderModalTitle');
  const subtitle = document.getElementById('deployStandaloneRecorderModalSubtitle');
  const action = document.getElementById('btnDeployStandaloneRecorderLoginModal');
  const isEntry = _deployStandaloneRecorderModalMode === 'entry';
  if (title) title.textContent = isEntry ? 'Entrar em gravador' : 'Cadastrar gravador';
  if (subtitle) {
    subtitle.textContent = isEntry
      ? 'Escolha um gravador cadastrado por site e use a credencial salva para abrir o console.'
      : 'So o acesso. Modelo, tipo e canais vem do proprio gravador.';
  }
  if (action) {
    action.innerHTML = isEntry ? '<i data-lucide="log-in"></i> Entrar' : '<i data-lucide="radar"></i> Validar gravador';
  }
  document.querySelectorAll('[data-recorder-modal-mode]').forEach(el => {
    const modes = String(el.dataset.recorderModalMode || '').split(/\s+/).filter(Boolean);
    el.classList.toggle('hidden', !modes.includes(_deployStandaloneRecorderModalMode));
  });
  lucide.createIcons();
}

function openDeployStandaloneRecorderModal(mode = 'create') {
  deployStandaloneRecorderSetModalMode(mode);
  document.getElementById('modalDeployStandaloneRecorder')?.classList.remove('hidden');
  document.body.classList.add('modal-open');
  deployStandaloneRecorderRenderSaved();
  lucide.createIcons();
}

function openDeployStandaloneRecorderEntryModal() {
  openDeployStandaloneRecorderModal('entry');
}

function closeDeployStandaloneRecorderModal() {
  document.getElementById('modalDeployStandaloneRecorder')?.classList.add('hidden');
  document.body.classList.remove('modal-open');
}

function deployStandaloneRecorderUpdateQuickActions() {
  const enabled = !!_deployStandaloneRecorderProbe;
  [
    'btnDeployStandaloneRecorderOpenWeb',
    'btnDeployStandaloneRecorderRefreshChannels',
    'btnDeployStandaloneRecorderPlayback',
    'btnDeployStandaloneRecorderSetNtp',
    'btnDeployStandaloneRecorderReboot',
    'btnDeployStandaloneRecorderFicha',
    'btnDeployStandaloneRecorderNetworkReload',
    'btnDeployStandaloneRecorderNetworkApply',
  ].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.disabled = !enabled;
  });
}

function deployStandaloneRecorderSelectConfigTab(tab = 'overview') {
  // A tela nova usa secoes; mantido para quem ainda chama pelo nome antigo.
  const mapa = { overview: 'equip', channels: 'canais', quick: 'acoes',
                 network: 'rede', recording: 'discos', storage: 'discos',
                 maintenance: 'achados' };
  if (document.querySelector('[data-recorder-sec]')) {
    deployRecorderAbrirSecao(mapa[tab] || 'achados');
    return;
  }
  const target = tab || 'overview';
  document.querySelectorAll('.recorder-config-tab').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.recorderConfigTab === target);
  });
  document.querySelectorAll('.recorder-config-panel').forEach(panel => {
    panel.classList.toggle('active', panel.dataset.recorderConfigPanel === target);
  });
  if (target === 'network' && _deployStandaloneRecorderProbe && !_deployStandaloneRecorderNetworkLoaded) {
    deployStandaloneRecorderLoadNetwork();
  }
}

function deployStandaloneRecorderSetNetworkResult(html, isError = false) {
  const box = document.getElementById('deployStandaloneRecorderNetworkResult');
  if (!box) return;
  box.classList.toggle('muted', !isError);
  box.classList.toggle('error', isError);
  box.innerHTML = html;
}

async function deployStandaloneRecorderLoadNetwork() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  const btn = document.getElementById('btnDeployStandaloneRecorderNetworkReload');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Consultando'; lucide.createIcons(); }
  deployStandaloneRecorderSetNetworkResult('Consultando rede atual do gravador...');
  try {
    const common = deployStandaloneRecorderCommonPayload(payload);
    const qs = new URLSearchParams({
      ip: common.ip || '', http_port: String(common.http_port || 80),
      user: common.user || '', password: common.password || '',
      timeout_sec: String(common.timeout_sec || 10),
    });
    const res = await api(`${deployStandaloneRecorderEndpointBase(payload)}/network?${qs.toString()}`);
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao consultar rede.';
      deployStandaloneRecorderSetNetworkResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ''; };
    setVal('deployStandaloneRecorderNetIp', data.ip);
    setVal('deployStandaloneRecorderNetMask', data.mask);
    setVal('deployStandaloneRecorderNetGateway', data.gateway);
    setVal('deployStandaloneRecorderNetDns1', data.dns1);
    setVal('deployStandaloneRecorderNetDns2', data.dns2);
    setVal('deployStandaloneRecorderNetTcpPort', data.tcp_port);
    setVal('deployStandaloneRecorderNetHttpPort', data.http_port);
    setVal('deployStandaloneRecorderNetRtspPort', data.rtsp_port);
    _deployStandaloneRecorderNetworkLoaded = true;
    deployStandaloneRecorderSetNetworkResult(`Rede consultada em ${esc(payload.recorder_host)}.`);
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao consultar rede.';
    deployStandaloneRecorderSetNetworkResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="refresh-cw"></i> Consultar'; lucide.createIcons(); }
    deployStandaloneRecorderUpdateQuickActions();
  }
}

async function deployStandaloneRecorderApplyNetwork() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  const getVal = id => document.getElementById(id)?.value.trim() || '';
  const newIp = getVal('deployStandaloneRecorderNetIp');
  const body = {
    ...deployStandaloneRecorderCommonPayload(payload),
    new_ip: newIp,
    mask: getVal('deployStandaloneRecorderNetMask'),
    gateway: getVal('deployStandaloneRecorderNetGateway'),
    dns1: getVal('deployStandaloneRecorderNetDns1'),
    dns2: getVal('deployStandaloneRecorderNetDns2'),
  };
  const tcpPort = getVal('deployStandaloneRecorderNetTcpPort');
  const httpPort = getVal('deployStandaloneRecorderNetHttpPort');
  const rtspPort = getVal('deployStandaloneRecorderNetRtspPort');
  if (tcpPort) body.new_tcp_port = Number(tcpPort);
  if (httpPort) body.new_http_port = Number(httpPort);
  if (rtspPort) body.new_rtsp_port = Number(rtspPort);

  if (!confirm(`Aplicar essas configuracoes de rede no gravador ${payload.recorder_host}?\n\nUma mudanca errada de IP/gateway/portas pode deixar o gravador inalcancavel.`)) return;

  const btn = document.getElementById('btnDeployStandaloneRecorderNetworkApply');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Aplicando'; lucide.createIcons(); }
  deployStandaloneRecorderSetNetworkResult(`Aplicando rede em ${esc(payload.recorder_host)}...`);
  try {
    const res = await api(`${deployStandaloneRecorderEndpointBase(payload)}/network`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao aplicar rede.';
      deployStandaloneRecorderSetNetworkResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    deployStandaloneRecorderSetNetworkResult(`Rede aplicada em ${esc(data.ip || payload.recorder_host)}.`);
    showToast('Configuracao de rede aplicada no gravador.');
    if (newIp && newIp !== payload.recorder_host) {
      const hostInput = document.getElementById('deployStandaloneRecorderHost');
      if (hostInput) hostInput.value = newIp;
    }
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao aplicar rede.';
    deployStandaloneRecorderSetNetworkResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="save"></i> Aplicar rede'; lucide.createIcons(); }
    deployStandaloneRecorderUpdateQuickActions();
  }
}

function deployStandaloneRecorderRenderProbe(data = null) {
  const summary = document.getElementById('deployStandaloneRecorderSummary');
  const channelsBox = document.getElementById('deployStandaloneRecorderChannels');
  const headStatus = document.getElementById('deployRecorderDiscoveryStatus');
  if (!summary || !channelsBox) return;
  if (!data) {
    const originReady = deployStandaloneRecorderOriginReady();
    summary.innerHTML = `
      <div class="recorder-discovery-empty">
        <i data-lucide="${originReady ? 'log-in' : 'plug-zap'}"></i>
        <div><b>${originReady ? 'Pronto para validar o gravador' : 'Escolha primeiro o conector'}</b><span>${originReady ? 'Abra Novo gravador, informe host e credenciais e clique em Entrar.' : 'Os dados e as acoes serao liberados quando a origem estiver definida.'}</span></div>
      </div>
      <div class="recorder-discovery-checklist">
        <div class="${originReady ? 'done' : ''}"><i data-lucide="${originReady ? 'check' : 'circle'}"></i><span><b>1. Conector</b><small>${originReady ? 'Origem de acesso definida' : 'Aguardando origem'}</small></span></div>
        <div><i data-lucide="circle"></i><span><b>2. Login</b><small>Validar modelo e serial</small></span></div>
        <div><i data-lucide="circle"></i><span><b>3. Canais</b><small>Identificar ocupados e livres</small></span></div>
        <div><i data-lucide="circle"></i><span><b>4. Inventario</b><small>Revisar e salvar</small></span></div>
      </div>
    `;
    _deployRecorderSelectedChannel = 0;
    deployRenderStandaloneRecorderChannels();
    if (headStatus) {
      headStatus.className = 'recorder-head-status waiting';
      headStatus.innerHTML = '<i data-lucide="circle"></i><span>Aguardando login</span>';
    }
    deployStandaloneRecorderUpdateQuickActions();
    lucide.createIcons();
    return;
  }
  const channels = deployStandaloneRecorderChannelsFromProbe(data);
  const used = channels.filter(ch => !!ch.used).length;
  const free = channels.length ? channels.length - used : 0;
  const total = Number(data.channel_total || channels.length || 0);
  const payload = deployStandaloneRecorderPayload();
  const brand = data.brand || 'Fabricante nao informado';
  const model = data.model || 'Modelo nao informado';
  const modeLabel = { basic: 'Basico', olt: 'Via OLT', switch: 'Via Switch' }[payload.inventory_mode] || 'Basico';
  if (headStatus) {
    headStatus.className = 'recorder-head-status online';
    headStatus.innerHTML = '<i data-lucide="circle-check"></i><span>Conectado</span>';
  }
  summary.innerHTML = `
    <div class="recorder-discovery-identity">
      <div><span>Fabricante</span><b>${esc(brand)}</b></div>
      <div><span>Modelo</span><b>${esc(model)}</b></div>
      <div class="identity-serial"><span>Serial</span><b class="monospace">${esc(data.serial || 'nao informado')}</b></div>
    </div>
    <div class="recorder-discovery-metrics">
      <div><span>Total</span><b>${esc(total)}</b><small>canais</small></div>
      <div class="metric-online"><span>Ocupados</span><b>${esc(used)}</b><small>com camera</small></div>
      <div class="metric-free"><span>Livres</span><b>${esc(free)}</b><small>disponiveis</small></div>
    </div>
    <div class="recorder-discovery-context">
      <div><span>Host</span><b class="monospace">${esc(payload.recorder_host)}</b></div>
      <div><span>Site / local</span><b>${esc(payload.site || '-')}</b></div>
      <div><span>Tipo</span><b>${esc(payload.recorder_type.toUpperCase())}</b></div>
      <div><span>Destino</span><b>${esc(modeLabel)}</b></div>
    </div>
    <div class="recorder-discovery-checklist compact">
      <div class="done"><i data-lucide="check"></i><span><b>Conector</b><small>Rota pronta</small></span></div>
      <div class="done"><i data-lucide="check"></i><span><b>Login</b><small>Credenciais OK</small></span></div>
      <div class="done"><i data-lucide="check"></i><span><b>Canais</b><small>${esc(used)} detectados</small></span></div>
      <div class="${_deployStandaloneRecorderSaved ? 'done' : ''}"><i data-lucide="${_deployStandaloneRecorderSaved ? 'check' : 'circle'}"></i><span><b>Inventario</b><small>${_deployStandaloneRecorderSaved ? 'Salvo' : 'Falta salvar'}</small></span></div>
    </div>
    <div class="recorder-discovery-actions">
      <button type="button" class="secondary-action" data-recorder-overview-action="refresh"><i data-lucide="refresh-cw"></i> Revalidar</button>
      <button type="button" class="secondary-action" data-recorder-overview-action="channels"><i data-lucide="layout-grid"></i> Ver canais</button>
      <button type="button" class="primary-action" id="btnDeployStandaloneRecorderSaveOverview" data-recorder-overview-action="save"><i data-lucide="${_deployStandaloneRecorderSaved ? 'check' : 'save'}"></i> ${_deployStandaloneRecorderSaved ? 'Salvo no inventario' : 'Salvar no inventario'}</button>
    </div>
  `;
  deployRenderStandaloneRecorderChannels();
  deployStandaloneRecorderSetQuickResult('Login confirmado. Escolha uma configuracao rapida para executar.');
  deployStandaloneRecorderUpdateQuickActions();
  lucide.createIcons();
}

async function loadDeployRecorderSites() {
  const list = document.getElementById('deployStandaloneRecorderSiteList');
  if (!list) return;
  const sites = new Set(_deploySites || []);
  const cameraModes = ['olt', 'basico', 'switch'];
  const cameraResults = await Promise.all(cameraModes.map(mode => apiJson(`/api/cameras?mode=${encodeURIComponent(mode)}`).catch(() => null)));
  cameraResults.forEach(data => {
    const rows = Array.isArray(data?.cameras) ? data.cameras : (Array.isArray(data?.rows) ? data.rows : []);
    rows.forEach(row => {
      const site = String(row.site || row.site_name || row.local || '').trim();
      if (site) sites.add(site);
    });
  });
  const recorderResults = await Promise.all([
    apiJson('/api/nvr/inventory?site=').catch(() => null),
    apiJson('/api/dvr/inventory?site=').catch(() => null),
  ]);
  recorderResults.forEach(data => {
    const rows = deployStandaloneRecorderInventoryRows(data);
    rows.forEach(row => {
      const site = String(row.site || row.site_name || row.local || '').trim();
      if (site) sites.add(site);
    });
  });
  _deploySites = [...sites].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  list.innerHTML = _deploySites.map(site => `<option value="${esc(site)}"></option>`).join('');
}

function deployStandaloneRecorderInventoryRows(data) {
  if (Array.isArray(data?.inventory)) return data.inventory;
  if (Array.isArray(data?.rows)) return data.rows;
  if (Array.isArray(data?.recorders)) return data.recorders;
  if (Array.isArray(data)) return data;
  return [];
}

function deployStandaloneRecorderRowHost(row) {
  return String(row?.host || row?.recorder_host || row?.nvr_host || row?.dvr_host || row?.ip || '').trim();
}

function deployStandaloneRecorderRowPort(row) {
  const value = Number(row?.http_port || row?.recorder_http_port || row?.port || 80);
  return value > 0 ? value : 80;
}

function deployStandaloneRecorderRowMode(row) {
  const raw = String(row?.inventory_mode || row?.mode || '').trim().toLowerCase();
  if (raw === 'basico' || raw === 'basic') return 'basic';
  if (raw === 'switch') return 'switch';
  if (raw === 'olt') return 'olt';
  return 'basic';
}

function deployStandaloneRecorderModeLabel(mode) {
  if (mode === 'olt') return 'Via OLT';
  if (mode === 'switch') return 'Via Switch';
  return 'Basico';
}

function deployStandaloneRecorderTypeLabel(type) {
  return type === 'dvr' ? 'DVR analogico' : 'NVR IP';
}

function deployStandaloneRecorderSortIp(value) {
  return String(value || '').split('.').map(part => Number(part) || 0);
}

function deployStandaloneRecorderCompareIp(a, b) {
  const pa = deployStandaloneRecorderSortIp(a);
  const pb = deployStandaloneRecorderSortIp(b);
  for (let i = 0; i < Math.max(pa.length, pb.length); i += 1) {
    const diff = (pa[i] || 0) - (pb[i] || 0);
    if (diff) return diff;
  }
  return String(a || '').localeCompare(String(b || ''), 'pt-BR', { numeric: true });
}

function deployStandaloneRecorderGroupRows(rows, type) {
  const groups = new Map();
  rows.forEach(row => {
    if (!row || typeof row !== 'object') return;
    const host = deployStandaloneRecorderRowHost(row);
    if (!host) return;
    const port = deployStandaloneRecorderRowPort(row);
    const mode = deployStandaloneRecorderRowMode(row);
    const connectorId = deployRecorderRowConnectorId(row);
    const site = deployRecorderRowSite(row);
    const key = [type, mode, connectorId, site.toLowerCase(), host, port].join('|');
    const item = groups.get(key) || {
      key,
      type,
      mode,
      connectorId,
      site,
      host,
      port,
      user: '',
      password: '',
      name: '',
      model: '',
      serial: '',
      totalChannels: 0,
      usedChannels: 0,
      rows: [],
    };
    item.user = item.user || String(row.recorder_user || row.user || 'admin').trim();
    item.password = item.password || String(row.recorder_password || row.password || '').trim();
    item.name = item.name || String(row.name || row.recorder_name || row.nvr_name || row.dvr_name || '').trim();
    item.model = item.model || String(row.nvr_model || row.dvr_model || row.modelo || row.model || '').trim();
    item.serial = item.serial || String(row.equip_serial || row.serial || row.nvr_serial || row.dvr_serial || '').trim();
    const channel = Number(row.channel || row.ch || 0);
    if (channel > item.totalChannels) item.totalChannels = channel;
    const status = String(row.status || '').trim().toLowerCase();
    if (status !== 'offline') item.usedChannels += 1;
    item.rows.push(row);
    groups.set(key, item);
  });
  return [...groups.values()].map(item => ({
    ...item,
    user: item.user || 'admin',
    totalChannels: item.totalChannels || item.rows.length || 32,
  }));
}

function deployStandaloneRecorderRenderSaved() {
  const select = document.getElementById('deployStandaloneRecorderSavedSelect');
  if (!select) return;
  const origin = deployStandaloneRecorderConnectorValue();
  const selectedOltId = document.getElementById('deployStandaloneRecorderOlt')?.value || '';
  const selectedOlt = _deployOltRows.find(row => String(row.id) === String(selectedOltId));
  const selectedSite = String(selectedOlt?.site || '').trim();
  const selectedConnectorId = deployStandaloneRecorderSelectedConnectorId();
  if (!origin) {
    select.innerHTML = '<option value="">Escolha primeiro o conector</option>';
    select.disabled = true;
    return;
  }
  // Sem OLT ("Sem OLT vinculada") a lista NAO trava: nem todo gravador entra
  // por OLT. Sem site pra filtrar, mostra os do conector inteiro, agrupados
  // por site. Com OLT escolhida, mantem o filtro pelo site dela.
  const items = _deployStandaloneRecorderSavedItems.filter(item => {
    if (selectedSite && String(item.site || '').trim().toLowerCase() !== selectedSite.toLowerCase()) return false;
    if (selectedConnectorId && item.connectorId) return String(item.connectorId) === String(selectedConnectorId);
    return true;
  });
  if (!items.length) {
    const onde = selectedSite ? `em ${esc(selectedSite)}` : 'neste conector';
    select.innerHTML = `<option value="">Nenhum gravador cadastrado ${onde}</option>`;
    select.disabled = true;
    return;
  }
  const bySite = new Map();
  items.forEach(item => {
    const site = item.site || 'Sem site';
    if (!bySite.has(site)) bySite.set(site, []);
    bySite.get(site).push(item);
  });
  select.disabled = false;
  select.innerHTML = '<option value="">Escolha um gravador cadastrado</option>' + [...bySite.entries()].map(([site, items]) => `
    <optgroup label="${esc(site)}">
      ${items.map(item => {
        const title = item.name || item.host;
        const label = [
          title,
          item.host,
          deployStandaloneRecorderTypeLabel(item.type),
          `${item.usedChannels}/${item.totalChannels} canais`,
          deployStandaloneRecorderModeLabel(item.mode),
        ].filter(Boolean).join(' - ');
        return `<option value="${esc(item.key)}">${esc(label)}</option>`;
      }).join('')}
    </optgroup>
  `).join('');
}

// Lista clicavel dos gravadores ja cadastrados. O select continua existindo
// (o formulario depende dele), mas no celular escolher num select de 60 itens
// agrupados e sofrido -- aqui e um toque.
function deployRecorderPintarLista() {
  const el = document.getElementById('deployRecorderLista');
  if (!el) return;
  const itens = _deployStandaloneRecorderSavedItems || [];
  if (!itens.length) {
    el.innerHTML = `<div class="recorder-lista-vazia">
      <i data-lucide="hard-drive"></i>
      <div><b>Nenhum gravador cadastrado ainda</b>
      <span>Use "Entrar em gravador" para ler um pela primeira vez.</span></div></div>`;
    lucide.createIcons();
    return;
  }
  el.innerHTML = itens.slice(0, 40).map(item => {
    const titulo = item.name || item.host;
    const canais = (item.usedChannels != null && item.totalChannels)
      ? `${item.usedChannels}/${item.totalChannels} canais` : '';
    return `<button class="recorder-card" type="button" data-grav="${esc(item.key)}">
      <i data-lucide="${item.type === 'dvr' ? 'tv' : 'hard-drive'}"></i>
      <span class="recorder-card-main">
        <b>${esc(titulo)}</b>
        <span>${esc(item.site || 'sem site')} · ${esc(item.host)}${canais ? ' · ' + esc(canais) : ''}</span>
      </span>
      <i data-lucide="chevron-right" class="recorder-card-seta"></i>
    </button>`;
  }).join('');
  el.querySelectorAll('[data-grav]').forEach(b => b.addEventListener('click', () => {
    const sel = document.getElementById('deployStandaloneRecorderSavedSelect');
    if (sel) { sel.value = b.dataset.grav; sel.dispatchEvent(new Event('change')); }
    // 'entry' = entrar num gravador que ja existe, nao cadastrar outro.
    openDeployStandaloneRecorderModal('entry');
  }));
  lucide.createIcons();
}

async function deployStandaloneRecorderLoadSaved() {
  const select = document.getElementById('deployStandaloneRecorderSavedSelect');
  if (select) {
    select.disabled = true;
    select.innerHTML = '<option value="">Carregando gravadores cadastrados...</option>';
  }
  const [nvrData, dvrData] = await Promise.all([
    apiJson('/api/nvr/inventory?site=').catch(() => null),
    apiJson('/api/dvr/inventory?site=').catch(() => null),
  ]);
  _deployStandaloneRecorderSavedItems = [
    ...deployStandaloneRecorderGroupRows(deployStandaloneRecorderInventoryRows(nvrData), 'nvr'),
    ...deployStandaloneRecorderGroupRows(deployStandaloneRecorderInventoryRows(dvrData), 'dvr'),
  ].sort((a, b) => {
    const siteDiff = String(a.site || '').localeCompare(String(b.site || ''), 'pt-BR', { numeric: true });
    if (siteDiff) return siteDiff;
    const hostDiff = deployStandaloneRecorderCompareIp(a.host, b.host);
    if (hostDiff) return hostDiff;
    return a.type.localeCompare(b.type);
  });
  deployStandaloneRecorderRenderSaved();
}

function deployStandaloneRecorderUseSaved(key) {
  const item = _deployStandaloneRecorderSavedItems.find(row => row.key === key);
  if (!item) return;
  const setValue = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  };
  const connector = document.getElementById('deployStandaloneRecorderConnector');
  if (connector) {
    const target = item.connectorId || DEPLOY_LOCAL_ORIGIN;
    connector.value = [...connector.options].some(opt => opt.value === target) ? target : DEPLOY_LOCAL_ORIGIN;
  }
  deployStandaloneRecorderRenderOltsForOrigin();
  deployStandaloneRecorderRenderConnectorStatus();
  setValue('deployStandaloneRecorderSite', item.site);
  setValue('deployStandaloneRecorderType', item.type);
  setValue('deployStandaloneRecorderInventoryMode', item.mode);
  setValue('deployStandaloneRecorderHost', item.host);
  setValue('deployStandaloneRecorderPort', item.port);
  setValue('deployStandaloneRecorderChannelTotal', item.totalChannels || 32);
  setValue('deployStandaloneRecorderUser', item.user || 'admin');
  setValue('deployStandaloneRecorderPassword', item.password || '');
  setValue('deployStandaloneRecorderName', item.name || item.site || '');
  _deployStandaloneRecorderProbe = null;
  _deployStandaloneRecorderSaved = false;
  _deployRecorderSelectedChannel = 0;
  deployStandaloneRecorderRenderProbe(null);
  deployStandaloneRecorderSetResult('Gravador carregado do inventario. Informe a senha e clique em Entrar para abrir o console.');
  deployStandaloneRecorderSetQuickResult('Entre no gravador para liberar as configuracoes rapidas.');
  const savedSelect = document.getElementById('deployStandaloneRecorderSavedSelect');
  if (savedSelect) savedSelect.value = '';
  deployStandaloneRecorderSelectConfigTab('overview');
  // Gravador conhecido entra direto. Quando nem o inventario nem o servidor
  // tem a senha, pergunta so usuario e senha num balao -- nao o formulario
  // inteiro, que so repetia o que o cadastro ja sabe.
  if (item.password || recTemSenhaSalva(item.host)) {
    closeDeployStandaloneRecorderModal();
    deployStandaloneRecorderSetResult(`Gravador ${esc(item.host)} carregado. Entrando com a credencial salva...`);
    deployStandaloneRecorderLogin();
    showToast(`Entrando em ${item.host}...`);
  } else {
    closeDeployStandaloneRecorderModal();
    recPedirSenha(item);
  }
  lucide.createIcons();
}

function deployStandaloneRecorderClearRecorderFields({ keepConnector = false, keepOlt = false, keepSite = false } = {}) {
  _deployStandaloneRecorderProbe = null;
  _deployStandaloneRecorderSaved = false;
  _deployRecorderSelectedChannel = 0;
  const ids = [
    'deployStandaloneRecorderHost',
    'deployStandaloneRecorderPassword',
    'deployStandaloneRecorderName',
  ];
  if (!keepSite) ids.unshift('deployStandaloneRecorderSite');
  ids.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  const port = document.getElementById('deployStandaloneRecorderPort');
  const channels = document.getElementById('deployStandaloneRecorderChannelTotal');
  const user = document.getElementById('deployStandaloneRecorderUser');
  if (port) port.value = '80';
  if (channels) channels.value = '32';
  if (user) user.value = 'admin';
  const connector = document.getElementById('deployStandaloneRecorderConnector');
  const olt = document.getElementById('deployStandaloneRecorderOlt');
  if (!keepConnector && connector) connector.value = '';
  if (!keepOlt && olt) olt.value = '';
  deployStandaloneRecorderRenderProbe(null);
  deployStandaloneRecorderSetResult('Entre no gravador para validar modelo, serial e canais.');
  deployStandaloneRecorderSetQuickResult('Entre no gravador para liberar as configuracoes rapidas.');
}

async function loadDeployRecorder() {
  // Entrar na tela sempre comeca do zero. Trocar de cliente nao passa por
  // navigateTo em alguns caminhos, e o gravador da conta anterior continuava
  // aberto -- dados de um cliente na tela de outro.
  if (_deployRecorderXray || _deployStandaloneRecorderProbe) {
    try { recSair(); } catch (_) {}
  }
  deploymentApplyPreferredInventoryMode();
  await Promise.all([loadDeployRecorderSites(), deployStandaloneRecorderLoadConnectors(), deployStandaloneRecorderLoadOlts(), deployStandaloneRecorderLoadSaved(), recCarregarSenhasSalvas()]);
  deployStandaloneRecorderRenderOltsForOrigin();
  deployStandaloneRecorderRenderProbe(_deployStandaloneRecorderProbe);
  recPintarApp();
  lucide.createIcons();
}

async function deployStandaloneRecorderLogin() {
  _deployStandaloneRecorderSaved = false;
  const payload = deployStandaloneRecorderPayload();
  if (!payload.site) {
    deployStandaloneRecorderSetResult('Informe o site/local antes de cadastrar o gravador.', true);
    showToast('Informe o site/local.', true);
    return;
  }
  if (!payload.recorder_host || !payload.recorder_user) {
    deployStandaloneRecorderSetResult('Informe host e usuario do gravador.', true);
    showToast('Informe host e usuario do gravador.', true);
    return;
  }
  // Senha em branco e normal em gravador conhecido: o servidor resolve a dele.
  if (!payload.recorder_password && !recTemSenhaSalva(payload.recorder_host)) {
    deployStandaloneRecorderSetResult('Informe a senha do gravador.', true);
    showToast('Informe a senha do gravador.', true);
    return;
  }
  const btn = document.getElementById('btnDeployStandaloneRecorderLoginModal');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Entrando'; lucide.createIcons(); }
  deployStandaloneRecorderSetResult(`<span class="inline-loading"><i data-lucide="loader"></i> Conectando em ${esc(payload.recorder_host)}...</span>`);
  deployStandaloneRecorderRenderLoginProgress(payload);
  recProgresso(payload.recorder_host, 0);
  showToast(`Conectando em ${payload.recorder_host}...`);
  try {
    const res = await api('/api/deployments/recorder-login', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao entrar no gravador.';
      // 428: o servidor nao tem senha guardada para este gravador. Pergunta
      // so usuario e senha, em vez de devolver o formulario inteiro.
      if (res?.status === 428) {
        deployStandaloneRecorderSetResult('Este gravador ainda nao tem senha guardada.');
        recProgressoFim();
        recPintarApp();
        recPedirSenha({ host: payload.recorder_host, user: payload.recorder_user, name: payload.name });
        return;
      }
      recProgressoErro(detail);
      _deployStandaloneRecorderProbe = null;
      deployStandaloneRecorderRenderProbe(null);
      deployStandaloneRecorderSetResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    _deployStandaloneRecorderProbe = data;
    _deployStandaloneRecorderNetworkLoaded = false;
    // O backend guarda a senha no login confirmado: da proxima vez este
    // gravador entra com um clique.
    recCarregarSenhasSalvas();
    deployStandaloneRecorderRenderProbe(data);
    // O gravador respondeu quantos canais tem: mostra no campo, que agora e
    // resultado e nao pergunta.
    const campoCanais = document.getElementById('deployStandaloneRecorderChannelTotal');
    if (campoCanais && data.channel_total) campoCanais.value = data.channel_total;
    const campoTipo = document.getElementById('deployStandaloneRecorderType');
    if (campoTipo && data.source) campoTipo.value = data.source;
    // O gravador acabou de dizer quem e: o nome do inventario sai daqui, nao
    // de um rotulo digitado a mao.
    const campoNome = document.getElementById('deployStandaloneRecorderName');
    const nomeReal = String(data.name || data.model || '').trim();
    if (campoNome && nomeReal) campoNome.value = nomeReal;
    // O login confirma acesso; o raio-x le o resto do equipamento (canais,
    // discos, deteccao, servicos). Vai sem await de proposito: no Intelbras
    // leva ~13s e nao pode segurar o retorno do login.
    deployRecorderCarregarXray();
    const label = [data.brand, data.model, data.serial].filter(Boolean).join(' / ');
    deployStandaloneRecorderSetResult(`Login confirmado em ${esc(payload.recorder_host)}${label ? ` - ${esc(label)}` : ''}. Agora pode salvar no inventario.`);
    closeDeployStandaloneRecorderModal();
    showToast('Login do gravador confirmado.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao entrar no gravador.';
    _deployStandaloneRecorderProbe = null;
    deployStandaloneRecorderRenderProbe(null);
    deployStandaloneRecorderSetResult(esc(detail), true);
    recProgressoErro(detail);
    showToast(detail, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = _deployStandaloneRecorderModalMode === 'entry'
        ? '<i data-lucide="log-in"></i> Entrar'
        : '<i data-lucide="radar"></i> Validar gravador';
      lucide.createIcons();
    }
  }
}

function deployStandaloneRecorderRows(payload, probe) {
  const channels = deployStandaloneRecorderChannelsFromProbe(probe);
  const byChannel = new Map(channels.map(item => [Number(item.channel || 0), item]));
  const total = Number(probe?.channel_total || payload.recorder_channel_total || channels.length || 32);
  // O login nem sempre traz o modelo; o raio-x traz. Sem isto a coluna
  // "Modelo NVR" do inventario ficava vazia num gravador que se identifica.
  const xray = _deployRecorderXray || {};
  const eqXray = xray.equipamento || {};
  const model = probe?.model || eqXray.modelo || '';
  const serial = probe?.serial || eqXray.serial || '';

  // Tudo abaixo o raio-x ja le do equipamento. Sem isso o relatorio saia com
  // "pendente de coleta" em HD, MAC, plataforma, e "n/c" na gravacao de todo
  // canal -- informacao que o sistema tinha em maos e nao gravava.
  const redeX = xray.rede || {};
  const discos = xray.discos || [];
  const capacidade = discos.reduce((t, x) => t + (Number(x.total_tb) || 0), 0);
  const comErro = discos.filter(x => x.erro).length;
  const plataforma = xray.plataforma || {};
  const porCanal = (xray.gravacao || {}).por_canal || {};
  const saude = discos.length ? {
    hdd_count: String(discos.length),
    hdd_total: capacidade ? `${capacidade.toFixed(1)} TB` : '',
    hdd_status: comErro ? `${comErro} disco(s) com erro` : 'todos ok',
    nvr_mac: redeX.mac || '',
    nvr_ip: redeX.ip || '',
    nvr_mask: redeX.mascara || '',
    nvr_gateway: redeX.gateway || '',
    nvr_dns: redeX.dns || '',
    platform_status: plataforma.ligada
      ? `ligada${plataforma.servidor ? ' - ' + plataforma.servidor : ''}`
      : (plataforma.servidor || Object.keys(plataforma).length ? 'desligada' : ''),
    recorder_health_collected: new Date().toISOString(),
  } : {};
  return Array.from({ length: total }, (_, idx) => {
    const channel = idx + 1;
    const live = byChannel.get(channel) || {};
    const used = !!live.used;
    const title = live.title || `${String(channel).padStart(2, '0')} - LIVRE`;
    const row = {
      remote: Boolean(payload.connector_id),
      remote_connector_id: payload.connector_id || '',
      inventory_mode: payload.inventory_mode || 'basic',
      host: payload.recorder_host,
      http_port: payload.recorder_http_port,
      recorder_user: payload.recorder_user,
      recorder_password: payload.recorder_password,
      name: payload.name,
      // A tela de inventario mostra `recorder_name` (ver computeDvrDisplayNames
      // em frontend/js/recorders.js); sem ele o gravador aparece como DVR-01
      // sequencial, por mais que `name` esteja preenchido.
      recorder_name: payload.name,
      channel,
      title,
      local: payload.site,
      site: payload.site,
      status: used ? 'online' : 'offline',
      video_loss: used ? 'nao' : 'sim',
      equip_serial: serial,
      // Modo de gravacao do canal: "desligado" e o unico que significa que o
      // canal nao grava; programado e manual gravam.
      recording: porCanal[channel] ? (porCanal[channel] !== 'desligado' ? 'sim' : 'nao') : '',
      recording_status: porCanal[channel] || '',
      ...saude,
      snapshot_url: live.snapshot_url || '',
      imgbb_url: live.imgbb_url || '',
      imgbb_thumb_url: live.imgbb_thumb_url || '',
    };
    if (payload.recorder_type === 'dvr') {
      row.modelo = model;
      row.model = model;
      row.mac = live.mac || '';
    } else {
      row.nvr_model = model;
      row.modelo = model;
      row.camera_ip = live.camera_ip || '';
      row.camera_model = live.camera_model || live.model || '';
      row.camera_mac = live.mac || live.camera_mac || '';
      row.mac = live.mac || live.camera_mac || '';
    }
    return row;
  }).filter(row => row.status === 'online');
}

async function deployStandaloneRecorderSave() {
  const payload = deployStandaloneRecorderPayload();
  if (!payload.site || !payload.recorder_host) {
    deployStandaloneRecorderSetResult('Site/local e host do gravador sao obrigatorios.', true);
    showToast('Informe site e host do gravador.', true);
    return;
  }
  if (!_deployStandaloneRecorderProbe) {
    deployStandaloneRecorderSetResult('Entre no gravador antes de salvar no inventario.', true);
    showToast('Entre no gravador antes de salvar.', true);
    return;
  }
  const rows = deployStandaloneRecorderRows(payload, _deployStandaloneRecorderProbe);
  if (!rows.length) {
    deployStandaloneRecorderSetResult('Nenhum canal encontrado para salvar.', true);
    showToast('Nenhum canal encontrado.', true);
    return;
  }
  const btn = document.getElementById('btnDeployStandaloneRecorderSaveOverview');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Salvando'; lucide.createIcons(); }
  try {
    const endpoint = payload.recorder_type === 'dvr' ? '/api/dvr/save' : '/api/nvr/save';
    const res = await api(endpoint, { method: 'POST', body: JSON.stringify({ recorders: rows }) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao salvar gravador no inventario.';
      deployStandaloneRecorderSetResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    deployStandaloneRecorderSetResult(`${rows.length} canal(is) salvos no inventario de ${payload.recorder_type.toUpperCase()} para ${esc(payload.site)}.`);
    _deployStandaloneRecorderSaved = true;
    await deployStandaloneRecorderLoadSaved();
    deployStandaloneRecorderRenderProbe(_deployStandaloneRecorderProbe);
    showToast('Gravador salvo no inventario.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao salvar gravador no inventario.';
    deployStandaloneRecorderSetResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="save"></i> Salvar no inventario'; lucide.createIcons(); }
  }
}

function deployStandaloneRecorderClear() {
  deployStandaloneRecorderClearRecorderFields();
  deployStandaloneRecorderRenderOltsForOrigin();
  deploymentApplyPreferredInventoryMode();
  deployStandaloneRecorderRenderConnectorStatus();
  lucide.createIcons();
}

function deployStandaloneRecorderEndpointBase(payload = deployStandaloneRecorderPayload()) {
  return payload.recorder_type === 'dvr' ? '/api/dvr' : '/api/nvr';
}

function deployStandaloneRecorderCommonPayload(payload = deployStandaloneRecorderPayload()) {
  return {
    ip: payload.recorder_host,
    http_port: payload.recorder_http_port,
    user: payload.recorder_user,
    password: payload.recorder_password,
    timeout_sec: 10,
  };
}

function deployStandaloneRecorderWebUrl(payload = deployStandaloneRecorderPayload()) {
  const port = Number(payload.recorder_http_port || 80);
  const suffix = port && port !== 80 ? `:${port}` : '';
  return `http://${payload.recorder_host}${suffix}`;
}

function deployStandaloneRecorderFirstUsedChannel() {
  const channels = deployStandaloneRecorderChannelsFromProbe(_deployStandaloneRecorderProbe);
  return channels.find(ch => ch.used)?.channel || 1;
}

function deployStandaloneRecorderRequireLogin() {
  if (_deployStandaloneRecorderProbe) return true;
  deployStandaloneRecorderSetQuickResult('Entre no gravador antes de executar esta acao.', true);
  showToast('Entre no gravador antes.', true);
  return false;
}

async function deployStandaloneRecorderDeleteChannel(item) {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  const channel = Number(item?.channel || 0);
  if (!channel) {
    showToast('Selecione um canal para excluir.', true);
    return;
  }
  const title = item?.title || item?.camera_ip || `Canal ${String(channel).padStart(2, '0')}`;
  const ok = await showConfirm({
    eyebrow: 'Gravador',
    title: `Excluir canal ${String(channel).padStart(2, '0')}`,
    msg: `Remover "${title}" do gravador ${payload.recorder_host}? Isso limpa a camera configurada neste canal e atualiza o inventario salvo.`,
    label: 'Excluir canal',
    danger: true,
  });
  if (!ok) return;

  deployStandaloneRecorderSetQuickResult(`Excluindo canal ${String(channel).padStart(2, '0')} de ${esc(payload.recorder_host)}...`);
  showToast(`Excluindo canal ${String(channel).padStart(2, '0')}...`);
  try {
    const res = await api('/api/deployments/recorder-remove-camera', {
      method: 'POST',
      body: JSON.stringify({ ...payload, recorder_channel: channel, channel }),
    });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao excluir canal.';
      deployStandaloneRecorderSetQuickResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    _deployStandaloneRecorderProbe = { ..._deployStandaloneRecorderProbe, ...data, channels: data.channels || [] };
    _deployRecorderSelectedChannel = 0;
    deployStandaloneRecorderRenderProbe(_deployStandaloneRecorderProbe);
    await deployStandaloneRecorderLoadSaved();
    deployStandaloneRecorderSetQuickResult(`Canal ${String(channel).padStart(2, '0')} excluido do gravador.`);
    showToast('Canal excluido.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao excluir canal.';
    deployStandaloneRecorderSetQuickResult(esc(detail), true);
    showToast(detail, true);
  }
}

function deployStandaloneRecorderOpenWeb() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  window.open(deployStandaloneRecorderWebUrl(), '_blank', 'noopener');
}

function deployStandaloneRecorderPlayback() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  navigateTo('playback');
  setTimeout(() => {
    const host = document.getElementById('playbackHost');
    const user = document.getElementById('playbackUser');
    const pass = document.getElementById('playbackPassword');
    const channel = document.getElementById('playbackChannel');
    if (host) host.value = `${payload.recorder_host}${payload.recorder_http_port && payload.recorder_http_port !== 80 ? `:${payload.recorder_http_port}` : ''}`;
    if (user) user.value = payload.recorder_user;
    if (pass) pass.value = payload.recorder_password;
    if (channel) channel.value = deployStandaloneRecorderFirstUsedChannel();
  }, 60);
}

function deployStandaloneRecorderFicha() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  const channels = deployStandaloneRecorderChannelsFromProbe(_deployStandaloneRecorderProbe);
  const data = {
    site: payload.site,
    type: payload.recorder_type,
    host: payload.recorder_host,
    http_port: payload.recorder_http_port,
    name: payload.name,
    brand: _deployStandaloneRecorderProbe?.brand || '',
    model: _deployStandaloneRecorderProbe?.model || '',
    serial: _deployStandaloneRecorderProbe?.serial || '',
    channel_total: channels.length || payload.recorder_channel_total,
    used_channels: channels.filter(ch => ch.used).length,
    free_channels: channels.filter(ch => !ch.used).length,
    channels,
  };
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `sightops-gravador-${payload.recorder_host || 'novo'}.json`;
  a.click();
  URL.revokeObjectURL(url);
  deployStandaloneRecorderSetQuickResult('Ficha tecnica gerada com os dados da descoberta.');
}

async function deployStandaloneRecorderSetNtp() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  const ntp = document.getElementById('deployStandaloneRecorderNtpServer')?.value.trim() || 'time.cloudflare.com';
  const btn = document.getElementById('btnDeployStandaloneRecorderSetNtp');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Ajustando'; lucide.createIcons(); }
  deployStandaloneRecorderSetQuickResult(`Enviando NTP ${esc(ntp)} para ${esc(payload.recorder_host)}...`);
  try {
    const res = await api(`${deployStandaloneRecorderEndpointBase(payload)}/ntp`, {
      method: 'POST',
      body: JSON.stringify({ ...deployStandaloneRecorderCommonPayload(payload), address: ntp }),
    });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao acertar NTP.';
      deployStandaloneRecorderSetQuickResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    deployStandaloneRecorderSetQuickResult(`NTP aplicado em ${esc(payload.recorder_host)}.`);
    showToast('NTP aplicado no gravador.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao acertar NTP.';
    deployStandaloneRecorderSetQuickResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="clock"></i> Acertar NTP'; lucide.createIcons(); }
    deployStandaloneRecorderUpdateQuickActions();
  }
}

async function deployStandaloneRecorderReboot() {
  if (!deployStandaloneRecorderRequireLogin()) return;
  const payload = deployStandaloneRecorderPayload();
  if (!confirm(`Reiniciar o gravador ${payload.recorder_host}?`)) return;
  const btn = document.getElementById('btnDeployStandaloneRecorderReboot');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Reiniciando'; lucide.createIcons(); }
  deployStandaloneRecorderSetQuickResult(`Enviando reboot para ${esc(payload.recorder_host)}...`);
  try {
    const res = await api(`${deployStandaloneRecorderEndpointBase(payload)}/reboot`, {
      method: 'POST',
      body: JSON.stringify(deployStandaloneRecorderCommonPayload(payload)),
    });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || data?.message || 'Falha ao reiniciar gravador.';
      deployStandaloneRecorderSetQuickResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    deployStandaloneRecorderSetQuickResult(`Comando de reboot enviado para ${esc(payload.recorder_host)}.`);
    showToast('Reboot enviado ao gravador.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao reiniciar gravador.';
    deployStandaloneRecorderSetQuickResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="power"></i> Reboot'; lucide.createIcons(); }
    deployStandaloneRecorderUpdateQuickActions();
  }
}

//  Implantacao - ONU (pagina dedicada: descobrir/autorizar/consultar/excluir)
let _onuSelectedDiscovered = null; // {pon, serno_id, serial, model, vendor}
let _onuLastAddContext = null; // {olt, pon, slot, services, tagMode, terminal} -- p/ "tentar bridge de novo"
let _oltInventoryRows = null; // cache: linhas de /api/olt/rows (IP/site/PON ja conhecidos)

function onuInferOltContext(oltIp) {
  const ip = (oltIp || '').trim();
  const rows = Array.isArray(_oltInventoryRows) ? _oltInventoryRows : [];
  const same = rows.filter(r => (r.olt_ip || '').trim() === ip);
  if (!same.length) return { site: '', olt_name: '' };
  const bySite = same.reduce((acc, r) => {
    const site = (r.site || r.local || '').trim();
    if (!site) return acc;
    acc[site] = (acc[site] || 0) + 1;
    return acc;
  }, {});
  const site = Object.entries(bySite).sort((a, b) => b[1] - a[1])[0]?.[0] || '';
  const oltName = same.map(r => (r.olt_name || '').trim()).find(Boolean) || '';
  return { site, olt_name: oltName };
}

async function populateOltIpDatalist(inputId, listId, ponInputId) {
  const listEl = document.getElementById(listId);
  if (!listEl) return;
  if (!_oltInventoryRows) {
    const data = await apiJson('/api/olt/rows').catch(() => null);
    _oltInventoryRows = data?.rows || (Array.isArray(data) ? data : []) || [];
  }
  const byIp = new Map();
  _oltInventoryRows.forEach(r => {
    const ip = (r.olt_ip || '').trim();
    if (!ip) return;
    if (!byIp.has(ip)) byIp.set(ip, { ip, name: r.olt_name || '', sites: new Set(), pons: new Set() });
    const entry = byIp.get(ip);
    if (r.site) entry.sites.add(r.site);
    if (r.pon) entry.pons.add(String(r.pon));
  });
  listEl.innerHTML = [...byIp.values()].map(e => {
    const label = [e.name, [...e.sites].join('/')].filter(Boolean).join(' - ');
    return `<option value="${esc(e.ip)}">${esc(label)}</option>`;
  }).join('');

  const inputEl = document.getElementById(inputId);
  const ponEl = ponInputId ? document.getElementById(ponInputId) : null;
  if (inputEl && ponEl && !inputEl.dataset.oltAutofillBound) {
    inputEl.dataset.oltAutofillBound = '1';
    inputEl.addEventListener('change', () => {
      const entry = byIp.get(inputEl.value.trim());
      if (entry && entry.pons.size === 1 && !ponEl.value) {
        ponEl.value = [...entry.pons][0];
      }
    });
  }
}

async function refreshOnuConnectors() {
  const sel = document.getElementById('onuConnector');
  if (!sel) return;
  try {
    const data = await apiJson('/api/connectors');
    _connectors = Array.isArray(data?.connectors) ? data.connectors : [];
  } catch {
    _connectors = _connectors || [];
  }
  const current = sel.value;
  // So faz sentido escolher um conector que tenha OLT cadastrada -- pelos
  // outros nao ha o que provisionar, e a lista cheia so atrapalha o tecnico.
  // Se nenhuma OLT tiver conector (tudo local), mostra todos em vez de deixar
  // a lista vazia.
  if (!_onuRegistryRows.length) {
    try {
      const reg = await apiJson('/api/olt/registry');
      _onuRegistryRows = (Array.isArray(reg?.items) ? reg.items : []).filter(row => row?.active);
    } catch { /* segue com a lista cheia */ }
  }
  const comOlt = new Set(_onuRegistryRows
    .map(row => String(row?.connector_id || row?.remote_connector_id || '').trim())
    .filter(Boolean));
  const todos = _routerConnectors();
  const rows = comOlt.size
    ? todos.filter(c => comOlt.has(String(c.id || c.connector_id || '').trim()))
    : todos;
  sel.innerHTML = '<option value="">Escolha a origem de acesso</option><option value="__local__">Local / VPN do servidor</option>' + rows.map(c => {
    const online = _connectorIsOnline(c);
    const tunnel = _connectorHasTunnel(c) ? ' + VPN' : '';
    const disabled = online && _connectorHasTunnel(c) ? '' : 'disabled';
    const suffix = !online ? ' (offline)' : (!_connectorHasTunnel(c) ? ' (sem VPN)' : '');
    return `<option value="${esc(c.id || c.connector_id || '')}" ${disabled}>${esc(_connectorLabel(c))}${tunnel}${suffix}</option>`;
  }).join('');
  if (current === '__local__' || (current && rows.some(c => String(c.id || c.connector_id || '') === current))) {
    sel.value = current;
  }
}

let _onuRegistryRows = [];

const ONU_CAPABILITY_BUTTONS = {
  discover_onus: ['btnOnuDiscover'],
  add_onu: ['btnOnuAdd', 'btnOnuAddVlanRow'],
  onu_signal: ['btnOnuQuery'],
  reboot_onu: ['btnOnuReboot'],
  delete_onu: ['btnOnuDelete', 'confirmOnuDelete'],
};

const ONU_CAPABILITY_STEPS = {
  discover_onus: 'onuStepDiscover',
  add_onu: 'onuStepAdd',
  onu_signal: 'onuStepQuery',
  reboot_onu: 'onuStepReboot',
  delete_onu: 'onuStepDelete',
};

function onuSelectedRegistryRow() {
  const value = document.getElementById('onuOltRegistry')?.value || '';
  return _onuRegistryRows.find(item => String(item.id) === String(value)) || null;
}

function onuCapabilityInfo() {
  const row = onuSelectedRegistryRow();
  if (!row) return null;
  return {
    row,
    caps: row.capabilities || {},
    label: row.capability_label || row.driver || [row.vendor, row.model].filter(Boolean).join(' ') || 'OLT',
    notes: row.capability_notes || '',
  };
}

function onuHasCapability(capability) {
  const info = onuCapabilityInfo();
  return !info || !!info.caps[capability];
}

function onuCapabilityMessage(capability) {
  const info = onuCapabilityInfo();
  if (!info) return '';
  return `${info.label} ainda nao suporta esta acao no SightOps. ${info.notes || ''}`.trim();
}

function onuPonCountForRow(row) {
  const model = String(row?.model || row?.olt_model || '').trim().toLowerCase();
  const driver = String(row?.driver || '').trim().toLowerCase();
  if (driver === 'intelbras_4840e' || model.includes('4840e') || model === '4840') return 4;
  return 8;
}

function onuRenderPonSelectOptions(select, count, includeAll = false) {
  if (!select) return;
  const previous = select.value;
  const total = Number.isInteger(Number(count)) && Number(count) > 0 ? Number(count) : 8;
  const options = [];
  if (includeAll) options.push(`<option value="all">Todas (1-${total})</option>`);
  else options.push('<option value="">Escolha</option>');
  for (let i = 1; i <= total; i += 1) {
    options.push(`<option value="${i}">PON ${i}</option>`);
  }
  select.innerHTML = options.join('');
  if ([...select.options].some(opt => opt.value === previous)) select.value = previous;
  else select.value = includeAll ? 'all' : '';
}

function onuUpdatePonSelectors() {
  const row = onuSelectedRegistryRow();
  const count = onuPonCountForRow(row);
  onuRenderPonSelectOptions(document.getElementById('onuOltPon'), count, true);
  // A PON de autorizar fica no proprio formulario: antes o tecnico tinha que
  // subir ate "Conexao com a OLT" so pra troca-la.
  onuRenderPonSelectOptions(document.getElementById('onuAddPonEpon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuQueryPon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuRebootPon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuDeletePon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuQueryPonEpon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuRebootPonEpon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuDeletePonEpon'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuAddPonVsol'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuQueryPonVsol'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuRebootPonVsol'), count, false);
  onuRenderPonSelectOptions(document.getElementById('onuDeletePonVsol'), count, false);
}

function onuUpdateCapabilities() {
  const status = document.getElementById('onuCapabilityStatus');
  const info = onuCapabilityInfo();
  if (status) {
    if (!info) {
      status.innerHTML = 'Escolha uma OLT cadastrada para ver quais acoes esse modelo suporta.';
      status.classList.remove('error');
    } else {
      const supported = [
        info.caps.discover_onus ? 'descobrir' : '',
        info.caps.add_onu ? 'autorizar' : '',
        info.caps.onu_signal ? 'consultar sinal/MACs' : '',
        info.caps.reboot_onu ? 'reiniciar' : '',
        info.caps.delete_onu ? 'excluir' : '',
        info.caps.collect_macs ? 'sincronizar inventario' : '',
      ].filter(Boolean).join(', ') || 'nenhuma acao operacional';
      const blocked = [
        !info.caps.discover_onus ? 'descoberta' : '',
        !info.caps.add_onu ? 'autorizacao' : '',
        !info.caps.onu_signal ? 'sinal/MACs' : '',
        !info.caps.reboot_onu ? 'reinicio' : '',
        !info.caps.delete_onu ? 'exclusao' : '',
      ].filter(Boolean).join(', ');
      status.innerHTML = `<b style="color:var(--primary)">${esc(info.label)}</b> -- suporta: ${esc(supported)}.${blocked ? ` Bloqueado: ${esc(blocked)}.` : ''} ${esc(info.notes || '')}`;
      status.classList.toggle('error', !!blocked && !info.caps.add_onu);
    }
  }
  Object.entries(ONU_CAPABILITY_BUTTONS).forEach(([capability, ids]) => {
    const allowed = onuHasCapability(capability);
    ids.forEach(id => {
      const el = document.getElementById(id);
      if (!el) return;
      el.disabled = !allowed;
      el.classList.toggle('is-disabled', !allowed);
      el.title = allowed ? '' : onuCapabilityMessage(capability);
    });
  });
  Object.entries(ONU_CAPABILITY_STEPS).forEach(([capability, id]) => {
    const el = document.getElementById(id);
    if (!el) return;
    const allowed = onuHasCapability(capability);
    el.classList.toggle('onu-step-unsupported', !allowed);
    if (!allowed) el.open = false;
  });
}

async function refreshOnuRegistry() {
  const sel = document.getElementById('onuOltRegistry');
  if (!sel) return;
  try {
    const data = await apiJson('/api/olt/registry');
    _onuRegistryRows = (Array.isArray(data?.items) ? data.items : []).filter(row => row?.active);
  } catch {
    _onuRegistryRows = [];
  }
  onuRenderRegistryForOrigin();
}

function onuRenderRegistryForOrigin() {
  const sel = document.getElementById('onuOltRegistry');
  if (!sel) return;
  const origin = document.getElementById('onuConnector')?.value || '';
  const rows = _onuRegistryRows.filter(row => deployOltMatchesOrigin(row, origin));
  sel.disabled = !onuConnectorGateOk();
  sel.innerHTML = !origin ? '<option value="">Escolha primeiro o conector</option>'
    : '<option value="">Escolha uma OLT cadastrada</option>'
    + rows.map(row => {
      const access = row.connector_id ? 'conector' : 'acesso direto';
      return `<option value="${esc(row.id)}">${esc(row.name)} - ${esc(row.site || 'sem site')} - ${esc(row.host)} (${access})</option>`;
    }).join('')
    + (origin === '__local__' ? '<option value="__manual__">Acesso manual / instalacao local</option>' : '');
}

function onuApplyRegisteredOlt() {
  const value = document.getElementById('onuOltRegistry')?.value || '';
  const row = onuSelectedRegistryRow();
  const manual = value === '__manual__';
  const setValue = (id, value) => { const el = document.getElementById(id); if (el) el.value = value || ''; };
  if (row) {
    setValue('onuOltIp', row.host);
    setValue('onuOltUser', row.username || 'admin');
    setValue('onuOltPassword', '');
  } else if (!manual) {
    setValue('onuOltIp', '');
    setValue('onuOltUser', '');
    setValue('onuOltPassword', '');
  }
  ['onuOltIp', 'onuOltUser', 'onuOltPassword'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!row;
  });
  const password = document.getElementById('onuOltPassword');
  if (password) password.placeholder = row ? 'Credencial salva no servidor' : 'Senha';
  onuAtualizarPassoDescoberta(row);
  onuUpdatePonSelectors();
  onuUpdateServiceOptions();
  onuToggleDriverFields('onuAddFieldsGpon', 'onuAddFieldsEpon', 'onuAddFieldsVsol');
  onuToggleDriverFields(null, 'onuAddHintEpon', null);
  onuPlaceInlineButton('btnOnuQuery', 'onuQueryBtnWrapGpon', 'onuQueryBtnSlotEpon', 'onuQueryBtnSlotVsol',
    onuToggleDriverFields('onuQueryFieldsGpon', 'onuQueryFieldsEpon', 'onuQueryFieldsVsol'));
  onuPlaceInlineButton('btnOnuReboot', 'onuRebootBtnWrapGpon', 'onuRebootBtnSlotEpon', 'onuRebootBtnSlotVsol',
    onuToggleDriverFields('onuRebootFieldsGpon', 'onuRebootFieldsEpon', 'onuRebootFieldsVsol'));
  onuPlaceInlineButton('btnOnuDelete', 'onuDeleteBtnWrapGpon', 'onuDeleteBtnSlotEpon', 'onuDeleteBtnSlotVsol',
    onuToggleDriverFields('onuDeleteFieldsGpon', 'onuDeleteFieldsEpon', 'onuDeleteFieldsVsol'));
  const _discoverKind = onuActiveOltKind(onuSelectedRegistryRow());
  document.getElementById('onuDiscoverResult')?.classList.toggle('hidden', _discoverKind === 'epon');
  document.getElementById('onuDiscoverResultEpon')?.classList.toggle('hidden', _discoverKind !== 'epon');
  updateOnuConnectorStatus();
  onuUpdateCapabilities();
  onuUpdateStepsLock();
}

function updateOnuConnectorStatus() {
  const status = document.getElementById('onuConnectorStatus');
  const connectorId = document.getElementById('onuConnector')?.value || '';
  const connector = connectorId ? _connectorById(connectorId) : null;
  if (!status) return;
  if (!connectorId) {
    status.innerHTML = 'Escolha Local/VPN do servidor ou um conector online com VPN. Os dados da OLT ficam bloqueados ate definir a origem.';
    status.classList.add('error');
    onuUpdateConnectorGate();
    return;
  }
  if (connectorId === '__local__') {
    status.innerHTML = '<b style="color:var(--primary)">Modo local</b> -- usando o servidor/VPN ja roteada. Confirme manualmente que a OLT pertence ao site correto.';
    status.classList.remove('error');
    onuUpdateConnectorGate();
    return;
  }
  const online = _connectorIsOnline(connector);
  const tunnel = _connectorHasTunnel(connector);
  status.innerHTML = online
    ? `<b style="color:var(--primary)">Conector online</b> -- ${esc(_connectorLabel(connector))}${tunnel ? ' -- VPN ativa para acessar a OLT.' : ' -- sem VPN configurada: a acao sera bloqueada.'}`
    : `<b style="color:var(--danger)">Conector offline</b> -- ${esc(_connectorLabel(connector) || 'conector indisponivel')}.`;
  status.classList.toggle('error', !online || !tunnel);
  onuUpdateConnectorGate();
}

function onuConnectorGateOk() {
  const connectorId = document.getElementById('onuConnector')?.value || '';
  if (!connectorId) return false;
  if (connectorId === '__local__') return true;
  const connector = _connectorById(connectorId);
  return _connectorIsOnline(connector) && _connectorHasTunnel(connector);
}

function onuUpdateConnectorGate() {
  const unlocked = onuConnectorGateOk();
  const registered = /^\d+$/.test(document.getElementById('onuOltRegistry')?.value || '');
  document.querySelectorAll('[data-onu-needs-connector="1"]').forEach(el => {
    const registeredCredential = registered && ['onuOltIp', 'onuOltUser', 'onuOltPassword'].includes(el.id);
    el.disabled = !unlocked || registeredCredential;
    el.classList.toggle('is-disabled', !unlocked);
  });
  const registry = document.getElementById('onuOltRegistry');
  if (registry) registry.disabled = !unlocked;
  onuUpdateCapabilities();
  onuUpdateStepsLock();
}

function onuConnectorReady(olt) {
  if (olt.access_mode === 'local') return true;
  if (!olt.connector_id) {
    showToast('Escolha Local/VPN do servidor ou um conector antes de acessar a OLT.', true);
    updateOnuConnectorStatus();
    return false;
  }
  const connector = _connectorById(olt.connector_id);
  if (!_connectorIsOnline(connector)) {
    showToast('O conector selecionado esta offline.', true);
    updateOnuConnectorStatus();
    return false;
  }
  if (!_connectorHasTunnel(connector)) {
    showToast('Esse conector ainda nao tem VPN ativa para acessar a OLT.', true);
    updateOnuConnectorStatus();
    return false;
  }
  return true;
}

// Acordeao generico ("sanfonado"): dentro de containerSelector, so um
// <details class="onu-step"> fica aberto por vez (fallback via JS para
// navegadores sem suporte nativo a details[name]).
function bindAccordionExclusive(containerSelector) {
  document.querySelectorAll(`${containerSelector} details.onu-step`).forEach(d => {
    if (d.dataset.accordionBound) return;
    d.dataset.accordionBound = '1';
    d.addEventListener('toggle', () => {
      if (!d.open) return;
      document.querySelectorAll(`${containerSelector} details.onu-step`).forEach(other => {
        if (other !== d) other.open = false;
      });
    });
  });
}

function onuResetTransientResults() {
  // A tela nunca e recriada ao navegar (navigateTo so esconde/mostra com
  // CSS) -- sem isso, resultado de consulta/exclusao/etc de uma sessao
  // anterior, e ate a sanfona aberta, ficavam grudados indefinidamente ate
  // dar F5. Roda toda vez que a tela e aberta, sem mexer na OLT/conector
  // selecionados (isso o usuario quer manter).
  _onuSelectedDiscovered = null;
  _onuLastAddContext = null;
  _onuDeleteTarget = null;
  onuSetResult('onuDiscoverResult', 'Informe IP/PON/usuario/senha da OLT e clique em Descobrir.');
  onuSetResult('onuAddResult', 'Nenhuma ONU autorizada ainda nesta sessao.');
  onuSetResult('onuQueryResult', 'Informe a posicao (PON + numero) ou o serial e clique em Consultar.');
  onuSetResult('onuRebootResult', 'Nenhum reinicio realizado nesta sessao.');
  onuSetResult('onuDeleteResult', 'Nenhuma exclusao realizada nesta sessao.');
  document.querySelectorAll('#viewDeployOnu details.onu-step').forEach(d => { d.open = false; });
  loadOnuHistory();
}

function loadDeployOnu() {
  onuResetTransientResults();
  deploymentApplyPreferredInventoryMode();
  populateOltIpDatalist('onuOltIp', 'onuOltIpList', 'onuOltPon');
  Promise.all([refreshOnuConnectors(), refreshOnuRegistry()]).finally(() => {
    onuRenderRegistryForOrigin();
    onuApplyRegisteredOlt();
    updateOnuConnectorStatus();
    onuUpdateConnectorGate();
    // Veio do painel de atencao do Dashboard apontando para uma ONU: so agora
    // os selects existem de verdade.
    onuAplicarAlvoPendente();
  });
  bindAccordionExclusive('#viewDeployOnu');
  bindOnuStepLockGuards();
  onuUpdateConnectorGate();
  ['onuOltIp', 'onuOltUser', 'onuOltPassword'].forEach(id => {
    const el = document.getElementById(id);
    if (el && !el.dataset.lockWatchBound) {
      el.dataset.lockWatchBound = '1';
      el.addEventListener('input', () => {
        onuUpdateStepsLock();
      });
    }
  });
  const connectorEl = document.getElementById('onuConnector');
  if (connectorEl && !connectorEl.dataset.onuConnectorBound) {
    connectorEl.dataset.onuConnectorBound = '1';
    connectorEl.addEventListener('change', () => {
      onuRenderRegistryForOrigin();
      onuApplyRegisteredOlt();
      updateOnuConnectorStatus();
      onuUpdateConnectorGate();
    });
  }
  const registryEl = document.getElementById('onuOltRegistry');
  if (registryEl && !registryEl.dataset.onuRegistryBound) {
    registryEl.dataset.onuRegistryBound = '1';
    registryEl.addEventListener('change', () => {
      onuApplyRegisteredOlt();
      loadOnuHistory();
    });
  }
  onuUpdateTerminalUI();
  loadOnuHistory();
  lucide.createIcons();
}

// Abre a tela de ONU ja apontada para uma ONU especifica. Quem chama e o painel
// de atencao do Dashboard: o tecnico ve "gpon 1 onu 11 / fora do ar" e quer ir
// direto consultar ou excluir, sem reescolher conector, OLT, PON e posicao a mao
// (30/09/2026).
//
// `acao` decide qual passo abre: 'consultar' (padrao) ou 'excluir'.
let _onuAlvoPendente = null;

function onuAbrirAlvo({ connectorId = '', oltIp = '', pon = '', onu = '', acao = 'consultar' } = {}) {
  // Guarda ANTES de navegar: loadDeployOnu() roda ao abrir a tela, e termina
  // depois daqui (as duas listas sao carregadas por Promise.all). Ele reescreve
  // os selects e limpa o formulario -- preencher agora e perder tudo, que foi
  // exatamente o que aconteceu na primeira versao (30/09/2026).
  _onuAlvoPendente = { connectorId, oltIp, pon, onu, acao };
  // navigateTo sempre chama loadDeployOnu (core.js), e e ele quem aplica o
  // alvo no fim -- quando os selects ja existem. Aplicar aqui consumiria o
  // pendente cedo demais e o reset da tela apagaria tudo em seguida.
  if (typeof navigateTo === 'function') navigateTo('deploy-onu');
}

async function onuAplicarAlvoPendente() {
  const alvoPendente = _onuAlvoPendente;
  if (!alvoPendente) return;
  _onuAlvoPendente = null;
  const { connectorId, oltIp, pon, onu, acao } = alvoPendente;

  // O seletor de conector so lista quem tem OLT, e a lista pode ainda nao ter
  // sido carregada se o tecnico entrou direto no Dashboard.
  try { await refreshOnuConnectors(); } catch { /* segue com o que ja tem */ }
  try { await refreshOnuRegistry(); } catch { /* idem */ }

  const selConector = document.getElementById('onuConnector');
  if (selConector && connectorId) {
    selConector.value = connectorId;
    selConector.dispatchEvent(new Event('change'));
  }

  // A OLT certa e a que casa host + conector: dois sites podem repetir o IP.
  const selOlt = document.getElementById('onuOltRegistry');
  const alvo = _onuRegistryRows.find(row =>
    String(row?.host || '').trim() === String(oltIp).trim() &&
    (!connectorId || String(row?.connector_id || '').trim() === String(connectorId).trim()));
  if (selOlt && alvo) {
    selOlt.value = String(alvo.id);
    selOlt.dispatchEvent(new Event('change'));
  }

  // Preenche os tres passos: o tecnico costuma consultar antes de excluir, e
  // ter que redigitar a posicao no meio do caminho e onde o erro acontece.
  // Os tres drivers tem campos proprios, e os nomes NAO seguem um padrao so:
  // no GPON a posicao e "onuDeleteOnuNum" (sem sufixo) e a da consulta e
  // "onuTargetNum"; no EPON/VSOL vem com sufixo. Preencher so os sufixados
  // deixava a 8820i com a PON certa e a posicao vazia (30/09/2026).
  ['onuQuery', 'onuReboot', 'onuDelete'].forEach(prefixo => {
    ['', 'Epon', 'Vsol'].forEach(sufixo => {
      const elPon = document.getElementById(`${prefixo}Pon${sufixo}`);
      if (elPon && pon) elPon.value = String(pon);
      const elOnu = document.getElementById(`${prefixo}OnuNum${sufixo}`);
      if (elOnu && onu) elOnu.value = String(onu);
    });
  });
  // Consulta no GPON usa um campo de nome proprio.
  const alvoGpon = document.getElementById('onuTargetNum');
  if (alvoGpon && onu) alvoGpon.value = String(onu);

  onuUpdateStepsLock();
  const passoId = { excluir: 'onuStepDelete', reiniciar: 'onuStepReboot' }[acao] || 'onuStepQuery';
  const passo = document.getElementById(passoId);
  if (passo) {
    passo.open = true;
    passo.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}
window.onuAbrirAlvo = onuAbrirAlvo;

function onuAccordionOpen(stepId) {
  const el = document.getElementById(stepId);
  if (el && !el.open) el.open = true;
}

// Etapas abaixo da conexao ficam travadas ate IP + senha da OLT serem preenchidos.
function onuLockedStepIds() {
  return ['onuStepDiscover', 'onuStepAdd', 'onuStepQuery', 'onuStepReboot', 'onuStepDelete'];
}

function onuUpdateStepsLock() {
  const registryValue = document.getElementById('onuOltRegistry')?.value || '';
  const registered = /^\d+$/.test(registryValue);
  const ip = document.getElementById('onuOltIp')?.value.trim();
  const pass = document.getElementById('onuOltPassword')?.value;
  const connectorOk = onuConnectorGateOk();
  const locked = !connectorOk || (registered ? !ip : (!ip || !pass));
  onuLockedStepIds().forEach(id => {
    const details = document.getElementById(id);
    if (!details) return;
    details.classList.toggle('onu-step-locked', locked);
    if (locked) details.open = false;
  });
}

function bindOnuStepLockGuards() {
  onuLockedStepIds().forEach(id => {
    const details = document.getElementById(id);
    const summary = details?.querySelector('summary');
    if (!summary || summary.dataset.lockGuardBound) return;
    summary.dataset.lockGuardBound = '1';
    summary.addEventListener('click', (e) => {
      if (details.classList.contains('onu-step-locked')) {
        e.preventDefault();
        showToast(onuConnectorGateOk() ? 'Informe o IP e a senha da OLT primeiro.' : 'Escolha Local/VPN do servidor ou um conector online com VPN primeiro.', true);
      } else if (details.classList.contains('onu-step-unsupported')) {
        e.preventDefault();
        const cap = Object.entries(ONU_CAPABILITY_STEPS).find(([, stepId]) => stepId === id)?.[0] || '';
        showToast(onuCapabilityMessage(cap) || 'Esta OLT ainda nao suporta essa acao.', true);
      }
    });
  });
}

// Etapa "Autorizar" -- ONT permite mais de uma VLAN, ONU fica com uma so.
const ONU_SERVICE_OPTIONS_DEFAULT = `
  <option value="downlink">Internet / dados</option>
  <option value="iptv">IPTV / multicast</option>
  <option value="tls">TLS / transparente</option>
  <option value="management">Gerencia</option>
  <option value="voice">Voz</option>
  <option value="other">Outro servico</option>
`;

// A 8820i so aceita 'downlink' ou 'tls' no 'bridge add' (confirmado contra
// OLT real com 'bridge add gpon <pon> onu <onu> ?') -- as outras opcoes do
// dropdown generico (iptv/management/voice/other) nem existem nesse CLI.
const ONU_SERVICE_OPTIONS_8820I = `
  <option value="downlink">Downlink</option>
  <option value="tls">TLS / transparente</option>
`;

function onuIsEpon(row) {
  return String(row?.driver || '').trim().toLowerCase() === 'intelbras_4840e';
}

function onuIsVsol(row) {
  return String(row?.driver || '').trim().toLowerCase() === 'vsol_epon';
}

// "Descobrir ONUs nao autorizadas" e util na 8820i e nao funciona na 4840E,
// que nao devolve a lista de nao autorizadas de forma confiavel. Antes isso
// estava fixo no HTML (display:none) e tirou o passo das DUAS -- a 8820i ficou
// sem uma etapa que ela precisa (30/09/2026).
//
// Nao da para usar a capability discover_onus: a 4840E declara true.
function onuAtualizarPassoDescoberta(row) {
  const passo = document.getElementById('onuStepDiscover');
  if (!passo) return;
  const esconder = onuIsEpon(row);
  passo.classList.toggle('hidden', esconder);
  if (esconder) passo.open = false;
}

function onuActiveOltKind(row) {
  if (onuIsEpon(row)) return 'epon';
  if (onuIsVsol(row)) return 'vsol';
  return 'gpon';
}

function onuToggleDriverFields(gponId, eponId, vsolId) {
  const kind = onuActiveOltKind(onuSelectedRegistryRow());
  const gponEl = gponId ? document.getElementById(gponId) : null;
  const eponEl = eponId ? document.getElementById(eponId) : null;
  const vsolEl = vsolId ? document.getElementById(vsolId) : null;
  if (gponEl) gponEl.classList.toggle('hidden', kind !== 'gpon');
  if (eponEl) eponEl.classList.toggle('hidden', kind !== 'epon');
  if (vsolEl) vsolEl.classList.toggle('hidden', kind !== 'vsol');
  return kind;
}

function onuPlaceInlineButton(buttonId, gponWrapId, eponRowId, vsolRowId, kind) {
  const btn = document.getElementById(buttonId);
  // No GPON o botao tambem tem um slot DENTRO da linha, como no EPON/VSOL:
  // antes ele ia para um wrapper abaixo dos campos e a etapa ocupava tres
  // alturas para dois campos (30/09/2026). O wrapper continua existindo como
  // destino de reserva -- se o slot nao estiver no HTML, o botao nao some.
  const gponSlotId = gponWrapId.replace('BtnWrapGpon', 'BtnSlotGpon');
  const gponAlvo = document.getElementById(gponSlotId) ? gponSlotId : gponWrapId;
  const targetId = kind === 'epon' ? eponRowId : (kind === 'vsol' ? vsolRowId : gponAlvo);
  const target = document.getElementById(targetId);
  if (btn && target && btn.parentElement !== target) target.appendChild(btn);
  // O wrapper so aparece quando ainda e ele quem segura o botao.
  document.getElementById(gponWrapId)?.classList.toggle(
    'hidden', kind !== 'gpon' || gponAlvo !== gponWrapId);
}

function onuServiceOptionsHtmlForDriver(driver) {
  return String(driver || '').trim().toLowerCase() === 'intelbras_8820i'
    ? ONU_SERVICE_OPTIONS_8820I
    : ONU_SERVICE_OPTIONS_DEFAULT;
}

function onuUpdateServiceOptions() {
  const row = onuSelectedRegistryRow();
  const optionsHtml = onuServiceOptionsHtmlForDriver(row?.driver);
  document.querySelectorAll('#onuAddServiceRows .onuAddServiceSel').forEach(sel => {
    const previous = sel.value;
    sel.innerHTML = optionsHtml;
    if ([...sel.options].some(opt => opt.value === previous)) sel.value = previous;
  });
}

function onuServiceRowHtml() {
  const row = onuSelectedRegistryRow();
  return `
    <div class="form-row onu-service-row">
      <div class="form-group">
        <label>Servico</label>
        <select class="onuAddServiceSel">
          ${onuServiceOptionsHtmlForDriver(row?.driver)}
        </select>
      </div>
      <div class="form-group">
        <label>VLAN</label>
        <div style="display:flex;gap:6px;align-items:center">
          <input class="onuAddVlanInput" type="number" placeholder="Ex: 3000" style="flex:1">
          <button type="button" class="icon-button onu-service-row-remove" title="Remover VLAN"><i data-lucide="x"></i></button>
        </div>
      </div>
    </div>`;
}

function onuAddVlanRow() {
  const container = document.getElementById('onuAddServiceRows');
  if (!container) return;
  container.insertAdjacentHTML('beforeend', onuServiceRowHtml());
  lucide.createIcons();
  container.querySelectorAll('.onu-service-row-remove').forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => btn.closest('.onu-service-row')?.remove());
  });
}

function onuPortRowEponHtml() {
  return `
    <div class="onu-service-row-epon form-row">
      <div class="form-group">
        <label>Porta ethernet
          <input type="number" min="1" value="1" class="onu-eth-port-epon">
        </label>
      </div>
      <div class="form-group">
        <label>VLAN
          <div style="display:flex;gap:6px;align-items:center">
            <input type="number" min="1" class="onu-eth-vlan-epon" style="flex:1">
            <button type="button" class="icon-button onu-service-row-epon-remove" title="Remover porta"><i data-lucide="x"></i></button>
          </div>
        </label>
      </div>
    </div>`;
}

function onuAddPortRowEpon() {
  const container = document.getElementById('onuAddPortRowsEpon');
  if (!container) return;
  container.insertAdjacentHTML('beforeend', onuPortRowEponHtml());
  lucide.createIcons();
  container.querySelectorAll('.onu-service-row-epon-remove').forEach(btn => {
    if (btn.dataset.bound) return;
    btn.dataset.bound = '1';
    btn.addEventListener('click', () => btn.closest('.onu-service-row-epon')?.remove());
  });
}

function onuUpdateTerminalUI() {
  const wrap = document.getElementById('onuAddVlanAddWrap');
  if (wrap) wrap.style.display = '';
}

function onuOltPayload() {
  const registryValue = document.getElementById('onuOltRegistry')?.value || '';
  const registered = _onuRegistryRows.find(item => String(item.id) === String(registryValue));
  const oltIp = document.getElementById('onuOltIp')?.value.trim() || '';
  const ctx = onuInferOltContext(oltIp);
  const selectedOrigin = document.getElementById('onuConnector')?.value || '';
  const localMode = selectedOrigin === '__local__';
  const connectorId = localMode ? '' : selectedOrigin;
  const connector = connectorId ? _connectorById(connectorId) : null;
  const site = connector ? (connector.site || connector.client || ctx.site || '') : ctx.site;
  return {
    olt_id: registered ? Number(registered.id) : null,
    access_mode: localMode ? 'local' : 'connector',
    olt_ip: oltIp,
    user: document.getElementById('onuOltUser')?.value.trim() || 'admin',
    password: document.getElementById('onuOltPassword')?.value || '',
    pon: document.getElementById('onuOltPon')?.value.trim() || 'all',
    site: registered?.site || site,
    olt_name: registered?.name || ctx.olt_name,
    connector_id: connectorId,
    remote_connector_id: connectorId,
    connector_name: connector ? (connector.name || connector.client || '') : '',
    inventory_mode: document.getElementById('onuInventoryMode')?.value || 'basic',
  };
}

// PON especifica (1-8) escolhida na conexao, ou 0 se estiver em "Todas".
function onuOltPonNumber(olt) {
  const n = Number(olt.pon);
  return Number.isInteger(n) && n >= 1 && n <= 8 ? n : 0;
}

function onuSetResult(boxId, html, isError = false) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.innerHTML = html;
  box.classList.toggle('error', !!isError);
}

// Contador de segundos "ainda trabalhando" para as chamadas na OLT (7-20s+
// cada, sem log em tempo real possivel) -- mesma ideia ja usada no Coletar
// MACs do Inventario > OLT: nao inventa progresso falso, so mostra que o
// pedido continua vivo enquanto espera.
function onuStartTicker(boxId, baseText) {
  let tick = 0;
  const paint = () => {
    const el = document.getElementById(boxId);
    if (el) el.textContent = `${baseText}... (${tick}s)`;
  };
  paint();
  return setInterval(() => { tick += 1; paint(); }, 1000);
}

function onuStopTicker(timer) {
  if (timer) clearInterval(timer);
}

function onuMacLine(m) {
  const ip = m?.ip ? ` - <b>${esc(m.ip)}</b>` : '';
  return `<li><code>${esc(m?.mac || '')}</code>${ip} - ${esc(m?.interface || '')}</li>`;
}

function onuVlanSummaryFromMacs(macs) {
  const vlans = [];
  (macs || []).forEach(m => {
    const text = String(m?.interface || m?.vlan || '');
    const match = text.match(/vlan\s+(\d+)/i);
    if (match && !vlans.includes(match[1])) vlans.push(match[1]);
  });
  return vlans.join(',');
}

function onuHistoryDate(value) {
  if (!value) return 'data nao informada';
  try { return new Date(value).toLocaleString('pt-BR'); } catch { return String(value); }
}

const ONU_ACTION_DONE = {
  add_onu: 'autorizada',
  add_onu_bridge: 'com o servico/VLAN reaplicado',
  reboot_onu: 'reiniciada',
  delete_onu: 'excluida',
  onu_signal: 'consultada',
};
const ONU_ACTION_VERB = {
  add_onu: 'autorizar',
  add_onu_bridge: 'aplicar o servico/VLAN',
  reboot_onu: 'reiniciar',
  delete_onu: 'excluir',
  onu_signal: 'consultar',
};

async function loadOnuHistory() {
  const box = document.getElementById('onuHistory');
  if (!box) return;
  const selectedRegistryId = document.getElementById('onuOltRegistry')?.value || '';
  const selectedOlt = _onuRegistryRows.find(item => String(item.id) === String(selectedRegistryId));
  const manualMode = selectedRegistryId === '__manual__';
  const manualIp = manualMode ? (document.getElementById('onuOltIp')?.value.trim() || '') : '';
  if (!selectedOlt && !manualIp) {
    box.innerHTML = '<div class="deployment-history-empty">Escolha uma OLT para ver o historico dela.</div>';
    return;
  }
  box.innerHTML = '<div class="deployment-history-empty">Atualizando historico...</div>';
  try {
    const selectedIp = String(selectedOlt?.host || manualIp).trim();
    const data = await apiJson(`/api/olt/onu-actions?olt_ip=${encodeURIComponent(selectedIp)}&limit=30`);
    const actions = Array.isArray(data?.actions) ? data.actions : [];
    if (!actions.length) {
      box.innerHTML = '<div class="deployment-history-empty">Nenhuma acao registrada ainda nesta OLT.</div>';
      return;
    }
    box.innerHTML = actions.map(a => {
      const ok = a.ok !== 0 && a.ok !== false;
      const serial = a.serial ? ` (${esc(a.serial)})` : '';
      const vlan = a.vlan ? ` - VLAN ${esc(a.vlan)}` : '';
      const detail = a.detail ? ` -- ${esc(a.detail)}` : '';
      const text = ok
        ? `foi ${ONU_ACTION_DONE[a.action] || esc(a.action)}`
        : `FALHOU ao ${ONU_ACTION_VERB[a.action] || esc(a.action)}`;
      return `<div class="deployment-history-item${ok ? '' : ' error'}">
        <b>PON ${esc(a.pon)} / ONU ${esc(a.onu)}${serial}</b>
        <span>${text}${vlan}${detail}</span>
        <small>${esc(a.site || a.olt_name || 'sem site')} - ${esc(onuHistoryDate(a.created_at))}</small>
      </div>`;
    }).join('');
  } catch (err) {
    box.innerHTML = `<div class="deployment-history-empty">Falha ao carregar: ${esc(err?.message || err)}</div>`;
  }
}

function onuClear() {
  document.querySelectorAll('#viewDeployOnu .onu-accordion input').forEach(input => { input.value = ''; });
  document.querySelectorAll('#viewDeployOnu .onu-accordion select').forEach(select => { select.selectedIndex = 0; });
  document.querySelectorAll('#onuAddServiceRows .onu-service-row').forEach((row, index) => { if (index > 0) row.remove(); });
  const connector = document.getElementById('onuConnector');
  if (connector) connector.value = '';
  onuRenderRegistryForOrigin();
  onuApplyRegisteredOlt();
  deploymentApplyPreferredInventoryMode();
  onuUpdateTerminalUI();
  onuResetTransientResults();
  updateOnuConnectorStatus();
  onuUpdateConnectorGate();
  onuAccordionOpen('onuStepConn');
  showToast('Campos da implantacao ONU limpos. O historico foi mantido.');
}

async function onuDiscoverEpon(olt) {
  const ticker = onuStartTicker('onuDiscoverResultEpon', 'Consultando OLT');
  const res = await api('/api/olt/discover-onus', { method: 'POST', body: JSON.stringify(olt) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuDiscoverResultEpon', esc(data?.detail || 'Falha ao consultar a OLT.'), true);
    return;
  }
  const pons = data.pons || {};
  const allDiscovered = [];
  Object.keys(pons).forEach(k => (pons[k]?.discovered || []).forEach(d => allDiscovered.push(d)));
  if (!allDiscovered.length) {
    onuSetResult('onuDiscoverResultEpon', 'Nenhuma ONU nao autorizada encontrada.');
    return;
  }
  onuSetResult('onuDiscoverResultEpon', allDiscovered.map(d => `
    <div class="deploy-match deploy-onu-pick-epon" data-mac="${esc(d.mac)}" data-pon="${esc(d.pon)}" style="cursor:pointer">
      <b>${esc(d.mac)}</b>
      <span>PON ${esc(d.pon)}</span>
      <small>clique para selecionar</small>
    </div>
  `).join(''));
  document.querySelectorAll('#onuDiscoverResultEpon .deploy-onu-pick-epon').forEach(el => {
    el.addEventListener('click', () => {
      const macEl = document.getElementById('onuAddMacEpon');
      const ponEl = document.getElementById('onuOltPon');
      if (macEl) macEl.value = el.dataset.mac;
      if (ponEl) ponEl.value = el.dataset.pon || '';
      showToast(`ONU ${el.dataset.mac} selecionada (PON ${el.dataset.pon}).`);
      onuAccordionOpen('onuStepAdd');
    });
  });
}

async function onuDiscover() {
  if (!onuHasCapability('discover_onus')) { showToast(onuCapabilityMessage('discover_onus'), true); return; }
  const olt = onuOltPayload();
  if (!olt.olt_ip) { showToast('Informe o IP da OLT.', true); return; }
  if (!olt.olt_id && !olt.password) { showToast('Informe a senha da OLT.', true); return; }
  if (!onuConnectorReady(olt)) return;
  if (onuIsEpon(onuSelectedRegistryRow())) { return onuDiscoverEpon(olt); }
  const ticker = onuStartTicker('onuDiscoverResult', 'Consultando OLT');
  const res = await api('/api/olt/discover-onus', { method: 'POST', body: JSON.stringify(olt) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuDiscoverResult', esc(data?.detail || 'Falha ao consultar a OLT.'), true);
    return;
  }
  const pons = data.pons || {};
  const ponKeys = Object.keys(pons).sort((a, b) => Number(a) - Number(b));
  const allDiscovered = [];
  const freeSummary = [];
  ponKeys.forEach(k => {
    const p = pons[k] || {};
    (p.discovered || []).forEach(d => allDiscovered.push(d));
    freeSummary.push(`PON ${k}: ${(p.free_slots || []).length} livres`);
  });
  if (!allDiscovered.length) {
    onuSetResult('onuDiscoverResult', `Nenhuma ONU nao autorizada encontrada. ${freeSummary.join(' | ')}`);
    return;
  }
  onuSetResult('onuDiscoverResult', allDiscovered.map(d => {
    const display = d.serial || d.onu_serial || d.onu_mac || '';
    const macValue = d.onu_mac || d.serial || '';
    const vendorModel = (d.vendor || d.model) ? ` - ${esc(d.vendor || '')} ${esc(d.model || '')}`.trim() : '';
    return `
    <div class="deploy-match deploy-onu-pick" data-pon="${esc(d.pon)}" data-serno="${esc(d.serno_id)}" data-serial="${esc(display)}" data-serial-raw="${esc(d.serial_raw || display)}" data-model="${esc(d.model)}" data-vendor="${esc(d.vendor)}" data-mac="${esc(macValue)}" style="cursor:pointer">
      <b>${esc(display)}</b>
      <span>PON ${esc(d.pon)}${vendorModel}</span>
      <small>descoberta ${esc(d.time_discovered || '')} - clique para selecionar</small>
    </div>
  `;
  }).join(''));
  document.querySelectorAll('#onuDiscoverResult .deploy-onu-pick').forEach(el => {
    el.addEventListener('click', () => {
      _onuSelectedDiscovered = {
        pon: Number(el.dataset.pon),
        serno_id: Number(el.dataset.serno),
        serial: el.dataset.serial,
        serialRaw: el.dataset.serialRaw || el.dataset.serial,
        model: el.dataset.model,
        vendor: el.dataset.vendor,
        mac: el.dataset.mac,
      };
      if (onuIsVsol(onuSelectedRegistryRow())) {
        const macVsolEl = document.getElementById('onuAddMacVsol');
        const ponVsolEl = document.getElementById('onuAddPonVsol');
        if (macVsolEl) macVsolEl.value = el.dataset.mac || el.dataset.serial || '';
        if (ponVsolEl) ponVsolEl.value = el.dataset.pon || '';
        showToast(`ONU ${el.dataset.mac || el.dataset.serial} selecionada (PON ${el.dataset.pon}).`);
        onuAccordionOpen('onuStepAdd');
        return;
      }
      const sernoEl = document.getElementById('onuAddSernoId');
      const modelEl = document.getElementById('onuAddModel');
      const queryPonEl = document.getElementById('onuQueryPon');
      if (sernoEl) sernoEl.value = el.dataset.serno;
      if (modelEl) modelEl.value = `${el.dataset.vendor} ${el.dataset.model}`;
      if (queryPonEl) queryPonEl.value = el.dataset.pon || '';
      showToast(`ONU ${el.dataset.serial} selecionada (PON ${el.dataset.pon}).`);
      onuAccordionOpen('onuStepAdd');
    });
  });
}

async function onuAddEpon(olt) {
  const mac = document.getElementById('onuAddMacEpon')?.value.trim() || '';
  if (!mac) { showToast('Informe o MAC da ONU.', true); return; }
  const description = document.getElementById('onuAddDescriptionEpon')?.value.trim() || '';
  const rows = [...document.querySelectorAll('#onuAddPortRowsEpon .onu-service-row-epon')];
  const services = rows.map(row => ({
    port: Number(row.querySelector('.onu-eth-port-epon')?.value || 1),
    vlan: Number(row.querySelector('.onu-eth-vlan-epon')?.value || 0),
  })).filter(s => s.vlan > 0);
  // PON do proprio formulario; o seletor do topo fica so como padrao inicial.
  const pon = Number(document.getElementById('onuAddPonEpon')?.value
    || document.getElementById('onuOltPon')?.value || '0');
  if (!pon) { showToast('Escolha a PON.', true); return; }
  const vlanMode = document.getElementById('onuAddVlanModeEpon')?.value || 'tag';
  if (vlanMode === 'tag' && !services.length) {
    showToast('No modo Tag e preciso informar a VLAN.', true); return;
  }

  const ticker = onuStartTicker('onuAddResult', 'Autorizando ONU na OLT');
  const res = await api('/api/olt/add-onu', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, serno_id: 0, serial: mac, description,
      vlan: services[0]?.vlan || 0, vlan_mode: vlanMode,
      services: services.map(s => ({ service: 'downlink', vlan: s.vlan, port: s.port })),
      site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuAddResult', esc(data?.error || data?.detail || 'Falha ao autorizar ONU.'), true);
    return;
  }
  // A OLT aceita a VLAN e as vezes demora a refletir. Isso e aviso, nao falha:
  // o cadastro foi ate o fim (p2p e save inclusive).
  const avisos = (data.avisos || []).filter(Boolean);
  const extra = avisos.length ? ` Atencao: ${avisos.map(esc).join(' ')}` : '';
  onuSetResult('onuAddResult', `ONU autorizada: PON ${esc(pon)} / posicao ${esc(data.onu)} (MAC ${esc(mac)}).${extra}`);
  showToast('ONU autorizada na OLT.');
  loadOnuHistory();
}

async function onuAddVsol(olt) {
  const pon = Number(document.getElementById('onuAddPonVsol')?.value || '0');
  const mac = document.getElementById('onuAddMacVsol')?.value.trim() || '';
  if (!pon || !mac) { showToast('Informe PON e MAC da ONU.', true); return; }

  const ticker = onuStartTicker('onuAddResult', 'Autorizando ONU na OLT');
  const res = await api('/api/olt/add-onu', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, serno_id: 0, vlan: 0, serial: mac, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuAddResult', esc(data?.error || 'Falha ao autorizar ONU.'), true);
    return;
  }
  loadOnuHistory();
  const posicao = data.pending
    ? 'aguardando a OLT registrar a posicao (atualize o historico em alguns segundos)'
    : `posicao atribuida: ONU ${esc(data.onu_id)}`;
  onuSetResult('onuAddResult', `
    <div><b>PON ${esc(pon)}</b> - MAC ${esc(mac)} autorizado</div>
    <div style="margin-top:4px">${posicao}</div>
  `);
}

async function onuAdd() {
  if (!onuHasCapability('add_onu')) { showToast(onuCapabilityMessage('add_onu'), true); return; }
  const olt = onuOltPayload();
  if (onuIsVsol(onuSelectedRegistryRow())) { return onuAddVsol(olt); }
  if (onuIsEpon(onuSelectedRegistryRow())) { return onuAddEpon(olt); }
  if (!olt.olt_ip || (!olt.olt_id && !olt.password)) { showToast('Escolha uma OLT cadastrada ou informe IP e senha.', true); return; }
  if (!onuConnectorReady(olt)) return;
  const sernoId = Number(document.getElementById('onuAddSernoId')?.value.trim() || '0');
  if (!sernoId) { showToast('Descubra e selecione uma ONU primeiro (ou digite o serno_id).', true); return; }

  let pon = 0;
  let model = '';
  if (_onuSelectedDiscovered && _onuSelectedDiscovered.serno_id === sernoId) {
    pon = _onuSelectedDiscovered.pon;
    model = _onuSelectedDiscovered.model;
  } else {
    pon = onuOltPonNumber(olt);
  }
  if (!pon) { showToast('Escolha uma PON especifica (nao "Todas") na conexao, ou descubra e selecione uma ONU.', true); return; }

  const tagMode = document.getElementById('onuAddTagMode')?.value || 'tagged';
  const terminal = document.getElementById('onuAddTerminal')?.value || 'onu';

  const rows = [...document.querySelectorAll('#onuAddServiceRows .onu-service-row')];
  const services = rows.map(row => ({
    service: row.querySelector('.onuAddServiceSel')?.value || 'downlink',
    vlan: Number(row.querySelector('.onuAddVlanInput')?.value.trim() || '0'),
  })).filter(e => e.vlan > 0);
  if (!services.length) { showToast('Informe pelo menos uma VLAN.', true); return; }

  const payload = {
    olt_id: olt.olt_id || null,
    olt_ip: olt.olt_ip,
    user: olt.user,
    password: olt.password,
    pon,
    serno_id: sernoId,
    onu_model: model,
    serial: _onuSelectedDiscovered?.serial || '',
    serial_raw: _onuSelectedDiscovered?.serialRaw || _onuSelectedDiscovered?.serial || '',
    vendor: _onuSelectedDiscovered?.vendor || '',
    site: olt.site || '',
    olt_name: olt.olt_name || '',
    description: document.getElementById('onuAddDescription')?.value.trim() || '',
    service: services[0].service,
    vlan: services[0].vlan,
    services,
    tag_mode: tagMode,
    terminal,
    connector_id: olt.connector_id || '',
    remote_connector_id: olt.remote_connector_id || '',
    connector_name: olt.connector_name || '',
  };
  const ticker = onuStartTicker('onuAddResult', 'Autorizando ONU na OLT (equipamento vivo)');
  const res = await api('/api/olt/add-onu', { method: 'POST', body: JSON.stringify(payload) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok) {
    onuSetResult('onuAddResult', esc(data?.detail || 'Falha ao autorizar ONU.'), true);
    return;
  }
  if (data.ok === false) {
    // A ONU pode ja ter sido autorizada na OLT mesmo com o resto falhando
    // (o 'onu set' e o primeiro passo) -- se `slot` veio preenchido, so o
    // servico/VLAN falhou, e da pra tentar de novo SO essa parte (sem
    // reautorizar) em vez de o tecnico ter que ir na OLT direto.
    const canRetryBridge = Number.isInteger(data.slot);
    _onuLastAddContext = canRetryBridge
      ? { olt, pon: data.pon || pon, slot: data.slot, services, tagMode, terminal }
      : null;
    const retryNote = canRetryBridge
      ? '<br><small>A ONU ja foi autorizada na OLT -- so falta o servico/VLAN.</small>'
      : '';
    const retryBtn = canRetryBridge
      ? '<div class="deploy-inline-button" style="margin-top:8px"><button class="secondary-action" id="btnOnuRetryBridge" type="button"><i data-lucide="refresh-cw"></i> Tentar aplicar servico/VLAN de novo</button></div>'
      : '';
    onuSetResult('onuAddResult', `Falhou em: <code>${esc(data.failed_at || '-')}</code><br>${esc(data.error || '')}<br>Comandos ja aplicados: ${data.commands_run?.length || 0}${retryNote}${retryBtn}`, true);
    if (canRetryBridge) {
      lucide.createIcons();
      document.getElementById('btnOnuRetryBridge')?.addEventListener('click', onuRetryBridge);
    }
    showToast('Falha ao autorizar ONU -- confira o detalhe.', true);
    return;
  }
  _oltInventoryRows = null;
  const syncedMacs = Number(data.device_sync?.macs || 0);
  const invMsg = syncedMacs > 0
    ? ` Inventario atualizado com ${syncedMacs} dispositivo${syncedMacs !== 1 ? 's' : ''} encontrado${syncedMacs !== 1 ? 's' : ''} atras da ONU.`
    : (data.inventory?.updated ? ' ONU adicionada ao inventario; nenhum dispositivo foi aprendido ainda.' : ' Inventario OLT nao foi alterado.');
  onuSetResult('onuAddResult', `ONU autorizada na PON ${esc(data.pon)}, posicao ${esc(data.slot)}.${esc(invMsg)}`);
  showToast(syncedMacs > 0
    ? `ONU autorizada e ${syncedMacs} dispositivo${syncedMacs !== 1 ? 's' : ''} sincronizado${syncedMacs !== 1 ? 's' : ''}.`
    : 'ONU autorizada. Ainda nao havia MAC aprendido; use Consultar sinal / MACs para atualizar.');
  const targetEl = document.getElementById('onuTargetNum');
  if (targetEl) targetEl.value = data.slot;
  const queryPonEl = document.getElementById('onuQueryPon');
  if (queryPonEl) queryPonEl.value = String(data.pon || pon || '');
  loadOnuHistory();
  onuAccordionOpen('onuStepQuery');
}

async function onuRetryBridge() {
  if (!_onuLastAddContext) return;
  const { olt, pon, slot, services, tagMode, terminal } = _onuLastAddContext;
  const payload = {
    olt_id: olt.olt_id || null,
    olt_ip: olt.olt_ip,
    user: olt.user,
    password: olt.password,
    pon,
    onu: slot,
    site: olt.site || '',
    olt_name: olt.olt_name || '',
    service: services[0].service,
    vlan: services[0].vlan,
    services,
    tag_mode: tagMode,
    terminal,
    connector_id: olt.connector_id || '',
    remote_connector_id: olt.remote_connector_id || '',
    connector_name: olt.connector_name || '',
  };
  const ticker = onuStartTicker('onuAddResult', 'Tentando aplicar servico/VLAN de novo (equipamento vivo)');
  const res = await api('/api/olt/add-onu-bridge', { method: 'POST', body: JSON.stringify(payload) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuAddResult', `Falhou de novo em: <code>${esc(data?.failed_at || '-')}</code><br>${esc(data?.detail || data?.error || 'Falha ao aplicar servico/VLAN.')}`, true);
    showToast('Ainda nao consegui aplicar o servico/VLAN.', true);
    return;
  }
  _onuLastAddContext = null;
  _oltInventoryRows = null;
  onuSetResult('onuAddResult', `Servico/VLAN aplicado na PON ${esc(data.pon)}, posicao ${esc(data.slot)}.`);
  showToast('Servico/VLAN aplicado -- ONU deve voltar a passar trafego.');
  const targetEl = document.getElementById('onuTargetNum');
  if (targetEl) targetEl.value = data.slot;
  const queryPonEl = document.getElementById('onuQueryPon');
  if (queryPonEl) queryPonEl.value = String(data.pon || pon || '');
  loadOnuHistory();
  onuAccordionOpen('onuStepQuery');
}

// Junta so os campos que a OLT entregou. OLT EPON (4840E/VSOL) nao tem OMCI
// nem RX por ONU medido na OLT -- mostrar "OMCI -" e "OLT RX -" fixos fazia
// parecer defeito onde o modelo simplesmente nao tem a medida.
function onuLinhaTelemetria(data) {
  const partes = [];
  if (data.oper_status) partes.push(`Status: ${esc(data.oper_status)}`);
  if (data.omci_status) partes.push(`OMCI ${esc(data.omci_status)}`);
  if (data.olt_rx) partes.push(`OLT RX ${esc(data.olt_rx)} dBm`);
  if (data.onu_rx) partes.push(`ONU RX ${esc(data.onu_rx)} dBm`);
  if (data.onu_tx) partes.push(`TX ${esc(data.onu_tx)} dBm`);
  if (data.temperatura) partes.push(`${esc(data.temperatura)} C`);
  if (data.distance_km) partes.push(`${esc(data.distance_km)} km`);
  return partes.join(' &nbsp;&middot;&nbsp; ') || 'sem telemetria';
}

// Nem sempre o tecnico sabe a posicao da ONU -- em campo ele tem o MAC na
// etiqueta. Quando o MAC vem preenchido, pergunta a posicao para a propria OLT
// ('show onu-status mac <mac>') antes de consultar/reiniciar/excluir.
async function onuPosicaoPorMac(olt, mac) {
  const res = await api('/api/olt/find-onu', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model, serial: mac,
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    return { erro: data?.error || data?.detail || 'MAC nao encontrado nesta OLT.' };
  }
  return { pon: Number(data.pon || 0), onu: Number(data.onu || 0) };
}

// Resolve o alvo dos passos EPON: posicao digitada tem prioridade; senao usa o
// MAC. Devolve {pon, onu} ou null (ja avisando o tecnico).
async function onuAlvoEpon(olt, prefixo, caixaResultado) {
  const pon = Number(document.getElementById(`${prefixo}PonEpon`)?.value || '0');
  const onuNum = Number(document.getElementById(`${prefixo}OnuNumEpon`)?.value || '0');
  const mac = (document.getElementById(`${prefixo}MacEpon`)?.value || '').trim();
  if (pon && onuNum) return { pon, onu: onuNum };
  if (!mac) { showToast('Informe PON e numero da ONU, ou o MAC.', true); return null; }
  const ticker = onuStartTicker(caixaResultado, 'Procurando a ONU pelo MAC na OLT');
  const achado = await onuPosicaoPorMac(olt, mac);
  onuStopTicker(ticker);
  if (achado.erro || !achado.pon || !achado.onu) {
    onuSetResult(caixaResultado, esc(achado.erro || 'MAC nao encontrado nesta OLT.'), true);
    return null;
  }
  const ponEl = document.getElementById(`${prefixo}PonEpon`);
  const onuEl = document.getElementById(`${prefixo}OnuNumEpon`);
  if (ponEl) ponEl.value = String(achado.pon);
  if (onuEl) onuEl.value = String(achado.onu);
  showToast(`MAC ${mac} esta na PON ${achado.pon} / posicao ${achado.onu}.`);
  return achado;
}

async function onuQueryEpon(olt) {
  const alvo = await onuAlvoEpon(olt, 'onuQuery', 'onuQueryResult');
  if (!alvo) return;
  const { pon, onu: onuNum } = alvo;

  const ticker = onuStartTicker('onuQueryResult', 'Consultando sinal da ONU');
  const res = await api('/api/olt/onu-signal', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuQueryResult', esc(data?.error || 'Falha ao consultar sinal.'), true);
    return;
  }
  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU ainda.</p>';

  onuSetResult('onuQueryResult', `
    <div><b>PON ${esc(data.pon)} / ONU ${esc(data.onu)}</b> - MAC ${esc(data.mac)}</div>
    <div>Estado: ${esc(data.state || '-')} / Distancia: ${esc(data.distance_m ?? '-')} m</div>
    <div>RX: ${esc(data.rx_power_dbm ?? '-')} dBm / TX: ${esc(data.tx_power_dbm ?? '-')} dBm</div>
    <div>Temperatura: ${esc(data.temperature_c ?? '-')} C / Tensao: ${esc(data.voltage_v ?? '-')} V</div>
    <div style="margin-top:6px"><b>MACs aprendidos:</b>${macsHtml}</div>
  `);
}

async function onuQueryVsol(olt) {
  const pon = Number(document.getElementById('onuQueryPonVsol')?.value || '0');
  const onuNum = Number(document.getElementById('onuQueryOnuNumVsol')?.value || '0');
  if (!pon || !onuNum) { showToast('Informe PON e numero da ONU.', true); return; }

  const ticker = onuStartTicker('onuQueryResult', 'Consultando sinal da ONU');
  const res = await api('/api/olt/onu-signal', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuQueryResult', esc(data?.error || 'Falha ao consultar sinal.'), true);
    return;
  }
  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU ainda.</p>';

  onuSetResult('onuQueryResult', `
    <div><b>PON ${esc(data.pon)} / ONU ${esc(data.onu_id)}</b> - MAC ${esc(data.onu_mac || '-')}</div>
    <div>Estado: ${esc(data.oper_status || '-')} / Distancia: ${esc(data.distance_km ?? '-')} km</div>
    <div>RX: ${esc(data.onu_rx ?? '-')} dBm</div>
    <div style="margin-top:6px"><b>MACs aprendidos:</b>${macsHtml}</div>
  `);
}

async function onuQuery() {
  if (!onuHasCapability('onu_signal')) { showToast(onuCapabilityMessage('onu_signal'), true); return; }
  const olt = onuOltPayload();
  if (!olt.olt_ip || (!olt.olt_id && !olt.password)) { showToast('Escolha uma OLT cadastrada ou informe IP e senha.', true); return; }
  if (!onuConnectorReady(olt)) return;
  if (onuIsVsol(onuSelectedRegistryRow())) { return onuQueryVsol(olt); }
  if (onuIsEpon(onuSelectedRegistryRow())) { return onuQueryEpon(olt); }
  const onuNum = Number(document.getElementById('onuTargetNum')?.value.trim() || '0');
  const serial = document.getElementById('onuQuerySerial')?.value.trim() || '';
  if (!onuNum && !serial) { showToast('Informe o numero da ONU ou o serial.', true); return; }
  const queryPon = Number(document.getElementById('onuQueryPon')?.value || 0);
  const ponNum = queryPon || onuOltPonNumber(olt);
  if (onuNum && !ponNum) { showToast('Informe a PON para consultar pelo numero da ONU, ou use o serial.', true); return; }

  const payload = {
    olt_id: olt.olt_id || null,
    olt_ip: olt.olt_ip,
    user: olt.user,
    password: olt.password,
    pon: ponNum,
    onu: onuNum || 0,
    serial,
    site: olt.site || '',
    olt_name: olt.olt_name || '',
    connector_id: olt.connector_id || '',
    remote_connector_id: olt.remote_connector_id || '',
    connector_name: olt.connector_name || '',
  };
  const ticker = onuStartTicker('onuQueryResult', 'Consultando sinal e MACs na OLT');
  const res = await api('/api/olt/onu-signal', { method: 'POST', body: JSON.stringify(payload) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuQueryResult', esc(data?.detail || data?.error || 'Falha ao consultar a ONU.'), true);
    return;
  }

  const targetEl = document.getElementById('onuTargetNum');
  if (targetEl) targetEl.value = data.onu;
  const queryPonEl = document.getElementById('onuQueryPon');
  if (queryPonEl && data.pon) queryPonEl.value = String(data.pon);
  loadOnuHistory();

  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU ainda.</p>';
  _oltInventoryRows = null;
  const invSync = data.inventory?.updated
    ? `<div style="margin-top:6px;color:var(--primary)">Inventario OLT atualizado com ${esc(String(data.inventory.macs || 0))} MAC(s).</div>`
    : '';

  onuSetResult('onuQueryResult', `
    <div><b>PON ${esc(data.pon)} / ONU ${esc(data.onu)}</b> - ${esc(data.serial)} (${esc(data.model)})</div>
    <div style="margin-top:4px">${onuLinhaTelemetria(data)}</div>
    <div style="margin-top:6px"><b>MACs aprendidos:</b>${macsHtml}</div>
    ${invSync}
  `);
}

async function onuRebootEpon(olt) {
  const alvo = await onuAlvoEpon(olt, 'onuReboot', 'onuRebootResult');
  if (!alvo) return;
  const { pon, onu: onuNum } = alvo;

  const ticker = onuStartTicker('onuRebootResult', 'Reiniciando ONU na OLT');
  const res = await api('/api/olt/reboot-onu', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuRebootResult', esc(data?.error || data?.detail || 'Falha ao reiniciar ONU.'), true);
    return;
  }
  onuSetResult('onuRebootResult', `ONU da PON ${esc(pon)} / posicao ${esc(onuNum)} reiniciada.`);
  showToast('Comando de reinicio enviado a ONU.');
  loadOnuHistory();
}

async function onuRebootVsol(olt) {
  const pon = Number(document.getElementById('onuRebootPonVsol')?.value || '0');
  const onuNum = Number(document.getElementById('onuRebootOnuNumVsol')?.value || '0');
  if (!pon || !onuNum) { showToast('Informe PON e numero da ONU.', true); return; }

  const ticker = onuStartTicker('onuRebootResult', 'Reiniciando ONU na OLT (equipamento vivo)');
  const res = await api('/api/olt/reboot-onu', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  loadOnuHistory();
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuRebootResult', esc(data?.error || 'Falha ao reiniciar ONU.'), true);
    return;
  }
  onuSetResult('onuRebootResult', `<div><b>PON ${esc(pon)} / ONU ${esc(onuNum)}</b> reiniciada.</div>`);
}

async function onuReboot() {
  if (!onuHasCapability('reboot_onu')) { showToast(onuCapabilityMessage('reboot_onu'), true); return; }
  const olt = onuOltPayload();
  if (onuIsVsol(onuSelectedRegistryRow())) { return onuRebootVsol(olt); }
  if (onuIsEpon(onuSelectedRegistryRow())) { return onuRebootEpon(olt); }
  if (!olt.olt_ip || (!olt.olt_id && !olt.password)) { showToast('Escolha uma OLT cadastrada ou informe IP e senha.', true); return; }
  if (!onuConnectorReady(olt)) return;
  const ponNum = Number(document.getElementById('onuRebootPon')?.value.trim() || '0');
  if (!ponNum) { showToast('Escolha a PON da ONU a reiniciar.', true); return; }
  const onuNum = Number(document.getElementById('onuRebootOnuNum')?.value.trim() || '0');
  if (!onuNum) { showToast('Informe o numero da ONU (posicao) a reiniciar.', true); return; }

  const payload = {
    olt_id: olt.olt_id || null,
    olt_ip: olt.olt_ip,
    user: olt.user,
    password: olt.password,
    pon: ponNum,
    onu: onuNum,
    site: olt.site || '',
    olt_name: olt.olt_name || '',
    connector_id: olt.connector_id || '',
    remote_connector_id: olt.remote_connector_id || '',
    connector_name: olt.connector_name || '',
  };
  const ticker = onuStartTicker('onuRebootResult', 'Reiniciando ONU na OLT (equipamento vivo)');
  const res = await api('/api/olt/reboot-onu', { method: 'POST', body: JSON.stringify(payload) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    onuSetResult('onuRebootResult', esc(data?.detail || data?.error || 'Falha ao reiniciar ONU (confira se a posicao esta correta).'), true);
    return;
  }
  onuSetResult('onuRebootResult', `ONU da PON ${esc(data.pon)} / posicao ${esc(data.onu)} reiniciada. Aguarde alguns instantes para ela voltar a responder.`);
  showToast('Comando de reinicio enviado a ONU.');
  loadOnuHistory();
}

let _onuDeleteTarget = null; // {olt, pon, onu}

function openOnuDeleteModal() { document.getElementById('modalOnuDelete')?.classList.remove('hidden'); }
function closeOnuDeleteModal() { document.getElementById('modalOnuDelete')?.classList.add('hidden'); }

async function onuDeleteEpon(olt) {
  const alvo = await onuAlvoEpon(olt, 'onuDelete', 'onuDeleteResult');
  if (!alvo) return;
  const { pon, onu: onuNum } = alvo;

  _onuDeleteTarget = { olt, pon, onu: onuNum, vlanHint: '' };
  const panoramaEl = document.getElementById('onuDeletePanorama');
  const confirmBtn = document.getElementById('confirmOnuDelete');
  if (confirmBtn) confirmBtn.disabled = true;
  openOnuDeleteModal();

  const ticker = onuStartTicker('onuDeletePanorama', 'Consultando dados da ONU na OLT');
  const res = await api('/api/olt/onu-signal', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!panoramaEl) return;
  if (!res?.ok || data?.ok === false) {
    // Consulta previa falhou -- o MAC alvo continua desconhecido. NAO
    // reabilita o botao de confirmar: clicar sem MAC manda `serial: ''`
    // pro backend, que desvincula a posicao mas falha em tirar da
    // whitelist (comando incompleto) -- exatamente o meio-estado que
    // este fluxo de dois passos existe pra evitar.
    panoramaEl.innerHTML = `<p>Sem informacoes para essa ONU (PON ${esc(pon)} / posicao ${esc(onuNum)}) -- ${esc(data?.error || 'nao respondeu')}.</p>`;
    return;
  }
  _onuDeleteTarget.mac = data.mac || '';
  _onuDeleteTarget.vlanHint = onuVlanSummaryFromMacs(data.macs);
  if (confirmBtn) confirmBtn.disabled = false;
  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU.</p>';
  panoramaEl.innerHTML = `
    <p>Voce esta prestes a excluir:</p>
    <div style="margin:8px 0;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface-soft)">
      <div><b>PON ${esc(pon)} / ONU ${esc(onuNum)}</b> - MAC ${esc(data.mac || '-')}</div>
      <div style="margin-top:4px">Estado: ${esc(data.state || '-')}</div>
      <div style="margin-top:6px"><b>${(data.macs || []).length} MAC(s) que vao perder conexao:</b>${macsHtml}</div>
    </div>
    <p style="color:var(--danger);font-size:13px;margin:0">Isso remove o cadastro e desliga o servico dela AGORA na OLT.</p>
  `;
}

async function onuDeleteVsol(olt) {
  const pon = Number(document.getElementById('onuDeletePonVsol')?.value || '0');
  const onuNum = Number(document.getElementById('onuDeleteOnuNumVsol')?.value || '0');
  if (!pon || !onuNum) { showToast('Informe PON e numero da ONU.', true); return; }

  _onuDeleteTarget = { olt, pon, onu: onuNum, vlanHint: '' };
  const panoramaEl = document.getElementById('onuDeletePanorama');
  const confirmBtn = document.getElementById('confirmOnuDelete');
  if (confirmBtn) confirmBtn.disabled = true;
  openOnuDeleteModal();

  const ticker = onuStartTicker('onuDeletePanorama', 'Consultando dados da ONU na OLT');
  const res = await api('/api/olt/onu-signal', {
    method: 'POST',
    body: JSON.stringify({
      olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
      olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
      pon, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '',
      connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '',
    }),
  });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (!panoramaEl) return;
  if (!res?.ok || data?.ok === false) {
    panoramaEl.innerHTML = `<p>Sem informacoes para essa ONU (PON ${esc(pon)} / posicao ${esc(onuNum)}) -- ${esc(data?.error || 'nao respondeu')}.</p>`;
    return;
  }
  _onuDeleteTarget.mac = data.onu_mac || '';
  _onuDeleteTarget.vlanHint = onuVlanSummaryFromMacs(data.macs);
  if (confirmBtn) confirmBtn.disabled = false;
  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU.</p>';
  panoramaEl.innerHTML = `
    <p>Voce esta prestes a excluir:</p>
    <div style="margin:8px 0;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface-soft)">
      <div><b>PON ${esc(pon)} / ONU ${esc(onuNum)}</b> - MAC ${esc(data.onu_mac || '-')}</div>
      <div style="margin-top:4px">Estado: ${esc(data.oper_status || '-')}</div>
      <div style="margin-top:6px"><b>MACs aprendidos:</b>${macsHtml}</div>
    </div>
    <p style="color:var(--danger);font-size:13px;margin:0">Isso remove a autorizacao e desliga o servico dela AGORA na OLT.</p>
  `;
}

async function onuDelete() {
  if (!onuHasCapability('delete_onu')) { showToast(onuCapabilityMessage('delete_onu'), true); return; }
  const olt = onuOltPayload();
  if (onuIsVsol(onuSelectedRegistryRow())) { return onuDeleteVsol(olt); }
  if (onuIsEpon(onuSelectedRegistryRow())) { return onuDeleteEpon(olt); }
  if (!olt.olt_ip || (!olt.olt_id && !olt.password)) { showToast('Escolha uma OLT cadastrada ou informe IP e senha.', true); return; }
  if (!onuConnectorReady(olt)) return;
  const ponNum = Number(document.getElementById('onuDeletePon')?.value.trim() || '0');
  if (!ponNum) { showToast('Escolha a PON da ONU a excluir.', true); return; }
  const onuNum = Number(document.getElementById('onuDeleteOnuNum')?.value.trim() || '0');
  if (!onuNum) { showToast('Informe o numero da ONU (posicao) a excluir.', true); return; }

  _onuDeleteTarget = { olt, pon: ponNum, onu: onuNum };
  const panoramaEl = document.getElementById('onuDeletePanorama');
  const confirmBtn = document.getElementById('confirmOnuDelete');
  if (confirmBtn) confirmBtn.disabled = true;
  openOnuDeleteModal();

  const ticker = onuStartTicker('onuDeletePanorama', 'Consultando dados da ONU na OLT');
  const res = await api('/api/olt/onu-signal', { method: 'POST', body: JSON.stringify({ olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password, pon: ponNum, onu: onuNum, site: olt.site || '', olt_name: olt.olt_name || '', connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '' }) });
  onuStopTicker(ticker);
  const data = await res?.json().catch(() => ({}));
  if (confirmBtn) confirmBtn.disabled = false;
  if (!panoramaEl) return;
  if (!res?.ok || data?.ok === false) {
    panoramaEl.innerHTML = `<p>Sem informacoes para essa ONU (PON ${esc(ponNum)} / posicao ${esc(onuNum)}) -- ${esc(data?.detail || data?.error || 'nao respondeu')}.</p>`;
    return;
  }
  const macsHtml = (data.macs || []).length
    ? `<ul style="margin:6px 0 0;padding-left:18px">${data.macs.map(onuMacLine).join('')}</ul>`
    : '<p style="margin:6px 0 0">Nenhum MAC aprendido atras dessa ONU.</p>';
  if (_onuDeleteTarget) _onuDeleteTarget.vlanHint = onuVlanSummaryFromMacs(data.macs);
  panoramaEl.innerHTML = `
    <p>Voce esta prestes a excluir:</p>
    <div style="margin:8px 0;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface-soft)">
      <div><b>PON ${esc(data.pon)} / ONU ${esc(data.onu)}</b> - ${esc(data.serial)} (${esc(data.model)})</div>
      <div style="margin-top:4px">${onuLinhaTelemetria(data)}</div>
      <div style="margin-top:6px"><b>${(data.macs || []).length} MAC(s) que vao perder conexao:</b>${macsHtml}</div>
    </div>
    <p style="color:var(--danger);font-size:13px;margin:0">Isso remove o cadastro e desliga o servico dela AGORA na OLT.</p>
  `;
}

async function onuConfirmDelete() {
  if (!_onuDeleteTarget) { closeOnuDeleteModal(); return; }
  const { olt, pon, onu, vlanHint, mac } = _onuDeleteTarget;
  const panoramaEl = document.getElementById('onuDeletePanorama');
  const confirmBtn = document.getElementById('confirmOnuDelete');
  if (confirmBtn) confirmBtn.disabled = true;
  if (panoramaEl) panoramaEl.insertAdjacentHTML('beforeend', '<p id="onuDeleteTickerLine" style="margin-top:10px">Excluindo ONU na OLT (equipamento vivo)... (0s)</p>');
  let onuDeleteTick = 0;
  const onuDeleteTicker = setInterval(() => {
    onuDeleteTick += 1;
    const line = document.getElementById('onuDeleteTickerLine');
    if (line) line.textContent = `Excluindo ONU na OLT (equipamento vivo)... (${onuDeleteTick}s)`;
  }, 1000);

  const isEpon = onuIsEpon(onuSelectedRegistryRow());
  const payload = isEpon
    ? { olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password,
        olt_vendor: olt.olt_vendor, olt_model: olt.olt_model,
        pon, onu, serial: mac || '', vlan_hint: vlanHint || '', site: olt.site || '',
        connector_id: olt.connector_id || '', remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '' }
    : { olt_id: olt.olt_id || null, olt_ip: olt.olt_ip, user: olt.user, password: olt.password, pon, onu,
        vlan_hint: vlanHint || '', site: olt.site || '', connector_id: olt.connector_id || '',
        remote_connector_id: olt.remote_connector_id || '', connector_name: olt.connector_name || '' };
  const res = await api('/api/olt/delete-onu', { method: 'POST', body: JSON.stringify(payload) });
  clearInterval(onuDeleteTicker);
  const data = await res?.json().catch(() => ({}));
    closeOnuDeleteModal();
    _onuDeleteTarget = null;
    if (!res?.ok || data?.ok === false) {
      onuSetResult('onuDeleteResult', esc(data?.detail || data?.error || 'Falha ao excluir ONU (confira se a posicao esta correta).'), true);
      return;
    }
  _oltInventoryRows = null;
  const removed = Number(data.inventory?.removed || 0);
  const invMsg = removed > 0 ? ` Removida do inventario OLT (${removed} registro${removed !== 1 ? 's' : ''}).` : ' Nenhum registro correspondente no inventario OLT.';
  onuSetResult('onuDeleteResult', `ONU excluida da PON ${esc(data.pon)} / posicao ${esc(data.onu)}.${esc(invMsg)}`);
  showToast(removed > 0 ? 'ONU excluida e removida do inventario.' : 'ONU excluida; nao havia registro no inventario.');
  loadOnuHistory();
}


async function deployLookupMac() {
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de procurar a camera.')) return;
  const p = deployPayload();
  if (!p.connector_id) {
    deploySetResult('Busca por MAC exige um conector MikroTik. No modo Local, preencha o IP da camera e clique em Entrar.', true);
    showToast('Busca por MAC exige conector MikroTik.', true);
    return;
  }
  if (!p.camera_mac) { showToast('Digite o MAC ou IP da camera.', true); return; }
  deploySetResult('Consultando DHCP, ARP e neighbors do MikroTik...');
  const data = await apiJson(`/api/deployments/lookup?connector_id=${encodeURIComponent(p.connector_id)}&query=${encodeURIComponent(p.camera_mac)}`);
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  if (!matches.length) {
    deploySetResult('Nenhum dispositivo encontrado no conector para esse MAC/IP.', true);
    return;
  }
  const first = matches[0];
  if (first.mac && !document.getElementById('deployCameraMac')?.value) document.getElementById('deployCameraMac').value = first.mac;
  const temConflito = matches.some(m => m.conflito_ip);
  const aviso = temConflito
    ? '<div style="margin-bottom:8px;font-size:12.5px;color:var(--amber)"><b>Atencao:</b> o mesmo IP aparece com MACs diferentes. '
      + 'Ou ha conflito de endereco na rede, ou a reserva de DHCP ficou velha. Confira o MAC na etiqueta antes de escolher.</div>'
    : '';
  deploySetResult(aviso + matches.slice(0, 8).map(m => `
    <div class="deploy-match deploy-cam-pick${m.conflito_ip ? ' conflito' : ''}" data-ip="${esc(m.ip || '')}" data-mac="${esc(m.mac || '')}" role="button" tabindex="0" aria-label="Selecionar IP ${esc(m.ip || '')}">
      <b>${esc(m.ip || '-')}${m.conflito_ip ? '<span class="marca-conflito">!</span>' : ''}</b>
      <span>${esc(m.mac || '-')}</span>
      <small><span class="deploy-pick-source">${esc(m.source || '-')} ${m.host ? `- ${esc(m.host)}` : ''}</span><strong class="deploy-pick-action">Clique para selecionar</strong></small>
    </div>
  `).join(''));
  document.querySelectorAll('#deployLookupResult .deploy-cam-pick').forEach(el => {
    const selectMatch = () => {
      document.querySelectorAll('#deployLookupResult .deploy-cam-pick').forEach(row => row.classList.remove('selected'));
      el.classList.add('selected');
      const action = el.querySelector('.deploy-pick-action');
      if (action) action.textContent = 'Selecionado';
      // So guarda o IP encontrado no Mikrotik pra usar na conexao de "puxar
      // dados" -- o campo visivel "IP da camera" so preenche com o que vier
      // da propria camera (pull), nao com o achado aqui no MAC/ARP.
      _deployPullTargetIp = el.dataset.ip || '';
      if (el.dataset.mac) document.getElementById('deployCameraMac').value = el.dataset.mac;
      showToast(`Selecionado: ${el.dataset.ip || el.dataset.mac}`);
      deployRenderSummary();
      // Escolher a camera E dizer "quero esta": nao existe motivo para um
      // segundo clique num botao separado so para confirmar o que o clique
      // anterior ja disse. Com a senha ja digitada entra direto; sem ela, o
      // modal pergunta na hora.
      const userEl = document.getElementById('deployCameraUser');
      const passEl = document.getElementById('deployCameraPassword');
      if (userEl?.value && passEl?.value) {
        deployPullCameraInfo();
      } else {
        deployAbrirLoginCamera();
      }
    };
    el.addEventListener('click', selectMatch);
    el.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectMatch();
      }
    });
  });
  deployRenderSummary();
}

async function deployPullCameraInfo() {
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de entrar na camera.')) return;
  // IP pra conectar vem do que foi selecionado na busca de MAC (Mikrotik),
  // ou do valor ja confirmado no campo (de um pull anterior) -- nunca de
  // digitacao manual, ja que o campo visivel fica travado.
  const ip = _deployPullTargetIp || document.getElementById('deployCameraIp')?.value.trim() || '';
  const user = document.getElementById('deployCameraUser')?.value.trim() || '';
  const pass = document.getElementById('deployCameraPassword')?.value || '';
  const box = document.getElementById('deployPullCameraResult');
  if (!ip) { showToast('Descubra o IP da camera pelo MAC primeiro (etapa acima).', true); return; }
  if (!user || !pass) { showToast('Informe usuario e senha da camera primeiro.', true); return; }
  if (box) box.innerHTML = 'Conectando na camera e trazendo os dados (pode levar alguns segundos)...';
  // Era /api/rescan-single-ip, que dispara um script inexistente e nao recebe
  // o conector -- ver o comentario do endpoint. Agora usa o mesmo raio-X que
  // a tela de gravador usa, in-process e com traducao vnat.
  const res = await api('/api/deployments/camera-xray', {
    method: 'POST',
    body: JSON.stringify({
      ip,
      usuario: user,
      senha: pass,
      connector_id: deploySelectedConnectorId(),
    }),
  });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    // A recusa vem da propria camera ("recusou a credencial", "nao respondeu
    // em http://..."). Repetir isso e mais util que um palpite generico.
    if (box) box.innerHTML = esc(data?.detail || 'Nao consegui ler a camera.');
    box?.classList.add('error');
    return;
  }
  box?.classList.remove('error');
  const eq = data.equipamento || {};
  const rede = data.rede || {};
  // O titulo que a propria camera carrega. Serve de origem para o canal do
  // gravador quando o tecnico nao digitou nada -- o que ele digitou tem
  // precedencia, senao um nome de fabrica ("IP CAMERA") sobrescreveria o
  // nome correto que ele acabou de escolher.
  _deployTituloDaCamera = data.titulo || '';
  const fabEl = document.getElementById('deployCameraManufacturer');
  const modEl = document.getElementById('deployCameraModel');
  const titleEl = document.getElementById('deployCameraTitle');
  const ipEl = document.getElementById('deployCameraIp');
  const macEl = document.getElementById('deployCameraMac');
  if (fabEl && eq.fabricante) fabEl.value = eq.fabricante;
  if (modEl && eq.modelo) modEl.value = eq.modelo;
  // O titulo que ja esta na camera so entra se o tecnico nao digitou nada --
  // sobrescrever o que ele acabou de escrever seria perder trabalho dele.
  if (titleEl && !titleEl.value.trim() && data.titulo) titleEl.value = data.titulo;
  if (ipEl) ipEl.value = rede.ip || ip;
  if (macEl && !macEl.value.trim() && (rede.mac || eq.mac)) macEl.value = rede.mac || eq.mac;
  _deployConfirmedCameraIp = rede.ip || ip;

  const achados = Array.isArray(data.achados) ? data.achados : [];
  const ficha = [
    eq.modelo ? `<b>${esc(eq.modelo)}</b>` : '',
    eq.serial ? `serial ${esc(eq.serial)}` : '',
    eq.firmware ? `firmware ${esc(eq.firmware)}` : '',
    rede.mascara ? `mascara ${esc(rede.mascara)}` : '',
    rede.gateway ? `gateway ${esc(rede.gateway)}` : '',
  ].filter(Boolean).join(' &middot; ');
  const avisos = achados.map(a => `<div style="margin-top:6px">&#9888; <b>${esc(a[1])}</b> ${esc(a[2])}</div>`).join('');
  if (box) box.innerHTML = ficha + avisos;
  showToast(`Camera lida: ${eq.fabricante || ''} ${eq.modelo || ''}`.trim());
  deployRenderSummary();
  deployUpdateStepLocks({ autoAdvance: true });
}

// Grava o titulo direto na camera (best-effort). Chamado como parte do
// "Registrar camera" no rodape -- se a camera nao responder, so avisa via
// toast e segue com o registro no inventario mesmo assim.
async function deployPushTitleToCamera(title) {
  const ip = _deployConfirmedCameraIp || document.getElementById('deployCameraIp')?.value.trim() || '';
  const user = document.getElementById('deployCameraUser')?.value.trim() || '';
  const pass = document.getElementById('deployCameraPassword')?.value || '';
  if (!ip || !user || !pass) return { ok: false, skipped: true };
  const res = await api('/api/deployments/save-camera-title', {
    method: 'POST',
    body: JSON.stringify({ ip, usuario: user, senha: pass, title, connector_id: deploySelectedConnectorId() }),
  });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    return { ok: false, detail: data?.detail || 'Falha ao gravar titulo na camera.' };
  }
  return { ok: true };
}

function deploySetCheckIpResult(html, isError = false) {
  const box = document.getElementById('deployCheckIpResult');
  if (!box) return;
  box.innerHTML = html || 'Se trocar o IP e clicar em "Checar novo IP", confiro disponibilidade e pergunto se quer aplicar na camera.';
  box.classList.toggle('error', !!isError);
}

async function deployCheckNewIp() {
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de checar IP.')) return;
  const p = deployPayload();
  const newIp = document.getElementById('deployCameraIp')?.value.trim() || '';
  if (!newIp) { showToast('Informe o IP a checar.', true); return; }
  deploySetCheckIpResult('Checando disponibilidade do IP...');
  const data = await apiJson(`/api/deployments/ip-check?ip=${encodeURIComponent(newIp)}&connector_id=${encodeURIComponent(p.connector_id)}&site=${encodeURIComponent(p.site)}`);
  if (!data) { showToast('Nao foi possivel checar o IP.', true); return; }
  if (data.in_use) {
    const places = (data.matches || []).map(m => `${m.source || 'inventario'}: ${m.title || m.mac || m.host || '-'}`).join('<br>');
    deploySetCheckIpResult(`IP ${esc(newIp)} ja aparece em uso.<br>${places}`, true);
    return;
  }
  if (!_deployConfirmedCameraIp || newIp === _deployConfirmedCameraIp) {
    deploySetCheckIpResult(`IP ${esc(newIp)} livre no inventario.`);
    return;
  }
  const user = document.getElementById('deployCameraUser')?.value.trim() || '';
  const pass = document.getElementById('deployCameraPassword')?.value || '';
  if (!user || !pass) {
    deploySetCheckIpResult(`IP ${esc(newIp)} livre. Preencha usuario/senha da camera pra eu poder aplicar direto nela.`);
    return;
  }
  if (!confirm(`IP ${newIp} esta livre.\n\nTrocar o IP da camera (atualmente em ${_deployConfirmedCameraIp}) pra esse novo IP agora?\n\nIsso muda a rede real do equipamento -- se a mascara/gateway herdados estiverem errados, a camera pode ficar inalcancavel.`)) {
    deploySetCheckIpResult(`IP ${esc(newIp)} livre no inventario. Troca cancelada.`);
    return;
  }
  deploySetCheckIpResult('Aplicando novo IP na camera (equipamento vivo, aguarde)...');
  const res = await api('/api/deployments/apply-camera-ip', {
    method: 'POST',
    body: JSON.stringify({ ip: _deployConfirmedCameraIp, usuario: user, senha: pass, new_ip: newIp, connector_id: deploySelectedConnectorId() }),
  });
  const result = await res?.json().catch(() => ({}));
  if (!res?.ok || result?.ok === false) {
    deploySetCheckIpResult(esc(result?.detail || 'Falha ao aplicar o novo IP na camera.'), true);
    return;
  }
  deploySetCheckIpResult(`IP aplicado na camera: ${esc(result.new_ip)} (mascara ${esc(result.subnet_mask || '-')}${result.gateway ? `, gateway ${esc(result.gateway)}` : ''}).`);
  showToast(`Novo IP aplicado na camera: ${result.new_ip}`);
  _deployConfirmedCameraIp = newIp;
  deployRenderSummary();
}

async function deploySaveDraft() {
  const payload = deployPayload();
  const res = await api('/api/deployments', { method: 'POST', body: JSON.stringify(payload) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    showToast(data?.detail || 'Falha ao salvar rascunho.', true);
    return;
  }
  _deployCurrentId = data.deployment?.id || _deployCurrentId;
  showToast('Rascunho de implantacao salvo.');
  await loadDeployHistory();
  deployRenderSummary();
}

async function deploySaveCameraInventory() {
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de salvar a camera.')) return;
  const payload = deployPayload();
  if (!payload.camera_title || !payload.camera_ip) {
    showToast('IP e titulo da camera sao obrigatorios para salvar no inventario.', true);
    return;
  }
  if (!payload.site) {
    showToast('Site/local e obrigatorio. Escolha do inventario ou digite um novo.', true);
    return;
  }
  const btn = document.getElementById('btnDeploySaveCameraInventory');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Salvando'; lucide.createIcons(); }
  try {
    const res = await api('/api/deployments/commit-camera', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      showToast(data?.detail || 'Falha ao salvar camera no inventario.', true);
      return;
    }
    _deployCurrentId = data.deployment?.id || _deployCurrentId;
    const rec = data.recorder_link || {};
    const recMsg = rec.ok ? ` Gravador ${rec.source?.toUpperCase() || ''} ${rec.host} canal ${rec.channel} -> ${rec.camera_ip}.` : '';
    showToast(`Camera salva no inventario: ${payload.camera_title}`);
    deploySetResult(`Camera salva no inventario (${esc(data.inventory_mode || payload.inventory_mode)}). Coordenada: ${esc(payload.location || '-')}.${esc(recMsg)}`);
    const savedMode = data.inventory_mode || payload.inventory_mode || 'basic';
    const camMode = savedMode === 'basic' ? 'basico' : savedMode;
    if (_invCam[camMode]) {
      await _loadCamForMode(camMode);
      updateCamTabs();
      populateCamSiteFilter();
      if (_currentView === 'inv-olt' && _invOltView === camMode) applyInvOltFilters();
    }
    await loadDeployHistory();
    deployRenderSummary();
    deployUpdateStepLocks({ autoAdvance: true });
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="save"></i> Salvar'; lucide.createIcons(); }
  }
}

async function deployRecorderLogin() {
  if (!deployEnsureStepUnlocked('cftvStep3', 'Preencha titulo e IP da camera antes de entrar no gravador.')) return;
  const payload = deployPayload();
  if (!payload.recorder_type) {
    deploySetRecorderLoginResult('Escolha o tipo do gravador antes de entrar.', true);
    showToast('Escolha NVR IP ou DVR analogico.', true);
    return;
  }
  // Senha em branco NAO e erro: o backend resolve pela credencial guardada
  // (`_credencial_gravador`), e sempre resolveu. Era esta checagem no
  // frontend -- e so ela -- que obrigava a redigitar.
  if (!payload.recorder_host) {
    deploySetRecorderLoginResult('Escolha o gravador antes de entrar.', true);
    showToast('Escolha o gravador.', true);
    return;
  }
  if (!payload.recorder_password && !recTemSenhaSalva(payload.recorder_host)) {
    deploySetRecorderLoginResult('Este gravador ainda nao tem senha guardada. Informe usuario e senha ao lado.', true);
    return;
  }
  const btn = document.getElementById('btnDeployRecorderLogin');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Entrando'; lucide.createIcons(); }
  deploySetRecorderLoginResult(`Conectando em ${esc(payload.recorder_host)}...`);
  try {
    const res = await api('/api/deployments/recorder-login', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      // Recusa pode ser senha trocada no proprio equipamento depois de salva.
      // Reabrir os campos da ao tecnico como resolver sem sair da tela.
      const detail = deployErroGravadorLegivel(data?.detail || data?.message, payload);
      deploySetRecorderLoginResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    const label = [data.brand, data.model, data.name].filter(Boolean).join(' / ');
    const msg = `Login confirmado em ${esc(payload.recorder_host)}${label ? ` - ${esc(label)}` : ''}.`;
    deployRenderRecorderChannels(Array.isArray(data.channels) ? data.channels : []);
    deploySetRecorderLoginResult(msg);
    showToast('Login do gravador confirmado.');
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao entrar no gravador.';
    deploySetRecorderLoginResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '<i data-lucide="log-in"></i> Entrar'; lucide.createIcons(); }
  }
}

async function deployRecorderAddCamera() {
  if (!deployEnsureStepUnlocked('cftvStep3', 'Preencha titulo e IP da camera antes de adicionar no gravador.')) return;
  const payload = deployPayload();
  // Mesma armadilha da entrada: senha vazia NAO e erro quando o servidor ja
  // guarda a credencial. Sem este ajuste, o login automatico passava e a
  // adicao morria aqui, dizendo "entre no gravador" para quem ja estava
  // dentro.
  if (!payload.recorder_type || !payload.recorder_host) {
    deploySetRecorderLoginResult('Escolha o gravador antes de adicionar a camera.', true);
    showToast('Escolha o gravador.', true);
    return;
  }
  if (!payload.recorder_password && !recTemSenhaSalva(payload.recorder_host)) {
    deploySetRecorderLoginResult('Entre no gravador antes de adicionar a camera.', true);
    showToast('Entre no gravador antes de adicionar a camera.', true);
    return;
  }
  if (!payload.recorder_channel) {
    deploySetRecorderLoginResult('Selecione um canal livre antes de adicionar.', true);
    showToast('Selecione um canal livre.', true);
    return;
  }
  if (!payload.recorder_camera_ip || !payload.recorder_title) {
    deploySetRecorderLoginResult('IP da camera e titulo no gravador sao obrigatorios.', true);
    showToast('IP da camera e titulo no gravador sao obrigatorios.', true);
    return;
  }
  if (!payload.camera_user || !payload.camera_password) {
    deploySetRecorderLoginResult('Usuario e senha da camera sao obrigatorios para adicionar no NVR.', true);
    showToast('Informe usuario e senha da camera.', true);
    return;
  }
  const btn = document.getElementById('deployRecorderChannelButton');
  const rotuloAntes = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader"></i> Adicionando'; lucide.createIcons(); }
  deploySetRecorderLoginResult(`Adicionando ${esc(payload.recorder_camera_ip)} no canal ${esc(payload.recorder_channel)}...`);
  try {
    const res = await api('/api/deployments/recorder-add-camera', { method: 'POST', body: JSON.stringify(payload) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      const detail = data?.detail || 'Falha ao adicionar camera no gravador.';
      deploySetRecorderLoginResult(esc(detail), true);
      showToast(detail, true);
      return;
    }
    deployRenderRecorderChannels(Array.isArray(data.channels) ? data.channels : []);
    deploySetRecorderLoginResult(`Camera adicionada no ${esc(payload.recorder_type.toUpperCase())} ${esc(payload.recorder_host)} canal ${String(data.channel || payload.recorder_channel).padStart(2, '0')}.`);
    showToast('Camera adicionada no gravador.');
    await loadDeployHistory();
    deployRenderSummary();
  } catch (err) {
    const detail = err?.detail || err?.message || 'Falha ao adicionar camera no gravador.';
    deploySetRecorderLoginResult(esc(detail), true);
    showToast(detail, true);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = rotuloAntes;
      // `deployRenderRecorderChannels` ja reescreveu o rotulo com o estado
      // novo quando a adicao deu certo; aqui so devolve o que havia antes
      // para o caso de falha.
      deployAtualizarRotuloCanal();
      lucide.createIcons();
    }
  }
}

async function deployCommitCamera(e) {
  e?.preventDefault();
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de registrar a camera.')) return;
  const payload = deployPayload();
  if (!payload.camera_title || !payload.camera_ip) {
    showToast('IP e titulo da camera sao obrigatorios.', true);
    return;
  }
  if (!payload.site) {
    showToast('Site/local e obrigatorio. Escolha do inventario ou digite um novo.', true);
    return;
  }

  const titlePush = await deployPushTitleToCamera(payload.camera_title);
  if (titlePush.ok) {
    showToast('Titulo gravado na camera.');
  } else if (!titlePush.skipped) {
    showToast(`Titulo NAO gravado na camera: ${titlePush.detail}`, true);
  }

  const res = await api('/api/deployments/commit-camera', { method: 'POST', body: JSON.stringify(payload) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) {
    showToast(data?.detail || 'Falha ao registrar camera.', true);
    return;
  }
  _deployCurrentId = data.deployment?.id || _deployCurrentId;
  const rec = data.recorder_link || {};
  const recMsg = rec.ok ? ` Gravador ${rec.source?.toUpperCase() || ''} ${rec.host} canal ${rec.channel} -> ${rec.camera_ip}.` : '';
  showToast(`Camera registrada: ${payload.camera_title}`);
  deploySetResult(`Camera registrada no inventario (${esc(data.inventory_mode || payload.inventory_mode)}). Chave: ${esc(data.inventory_key || '-')}.${esc(recMsg)}`);
  await loadDeployHistory();
  deployRenderSummary();
  deployUpdateStepLocks({ autoAdvance: true });
}

function deployClear() {
  _deployCurrentId = '';
  _deployPullTargetIp = '';
  _deployConfirmedCameraIp = '';
  document.getElementById('deployForm')?.reset();
  const connEl = document.getElementById('deployConnector');
  if (connEl) connEl.value = '';
  deployRenderOltContextForOrigin();
  deployApplyOriginFields();
  deploySetResult('Aguardando consulta no conector.');
  deployRenderConnectorStatus();
  const pullBox = document.getElementById('deployPullCameraResult');
  if (pullBox) {
    pullBox.innerHTML = 'Descubra o IP pelo MAC (acima), preencha usuario/senha, depois clique para trazer os dados reais da camera.';
    pullBox.classList.remove('error');
  }
  deploySetCheckIpResult();
  deploySetRecorderLoginResult();
  deployRenderRecorderChannels();
  deployRenderSummary();
  deployOpenStep('cftvStep2', { forcar: true });
}

//  Conectores SaaS 
let _connectors = [];
let _lastCreatedConnectorId = '';
let _lastCreatedConnectorType = '';

function formatDateTimeShort(value) {
  if (!value) return '-';
  try {
    return new Date(value).toLocaleString('pt-BR');
  } catch {
    return value;
  }
}

function connectorHostLabel(host) {
  if (!host || typeof host !== 'object') return '-';
  const name = host.hostname || host.identity || '';
  const model = host.model || '';
  const ips = Array.isArray(host.ips) ? host.ips.filter(Boolean).slice(0, 2).join(', ') : '';
  return [name, model, ips].filter(Boolean).join(' / ') || '-';
}

function connectorInventoryLabel(row) {
  const inv = row?.inventory || {};
  const items = [];
  if (String(row?.type || '').toLowerCase() === 'ruijie') {
    if (inv.count) items.push(`${inv.count} dispositivos`);
    return items.join(' / ');
  }
  if (inv.dhcp_leases) items.push(`DHCP ${inv.dhcp_leases}`);
  if (inv.arp_entries) items.push(`ARP ${inv.arp_entries}`);
  if (inv.neighbors) items.push(`Neighbors ${inv.neighbors}`);
  return items.join(' / ');
}

function connectorTypeLabel(type) {
  const t = String(type || 'routeros').toLowerCase();
  if (t === 'routeros') return 'MikroTik';
  return 'Windows';
}

function connectorById(connectorId) {
  return _connectors.find(row => String(row.id || '') === String(connectorId || '')) || null;
}

function private24FromIp(value) {
  const parts = String(value || '').trim().split('.');
  if (parts.length !== 4) return '';
  const nums = parts.map(part => Number(part));
  if (nums.some(num => !Number.isInteger(num) || num < 0 || num > 255)) return '';
  const [a, b, c] = nums;
  const isPrivate = a === 10
    || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 168)
    || (a === 100 && b >= 64 && b <= 127);
  if (!isPrivate) return '';
  return `${a}.${b}.${c}.0/24`;
}

function ipToNumber(ip) {
  const nums = String(ip || '').split('.').map(part => Number(part));
  if (nums.length !== 4 || nums.some(num => !Number.isInteger(num) || num < 0 || num > 255)) return null;
  return nums.reduce((acc, num) => ((acc << 8) + num) >>> 0, 0);
}

function numberToIp(num) {
  return [24, 16, 8, 0].map(shift => ((num >>> shift) & 255)).join('.');
}

function normalizePrivateCidr(value) {
  const raw = String(value || '').trim();
  const match = raw.match(/^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/);
  if (!match) return '';
  const ipNum = ipToNumber(match[1]);
  const prefix = Number(match[2]);
  if (ipNum === null || !Number.isInteger(prefix) || prefix < 1 || prefix >= 32) return '';
  const parts = match[1].split('.').map(part => Number(part));
  const [a, b] = parts;
  const privateLan = a === 10
    || (a === 172 && b >= 16 && b <= 31)
    || (a === 192 && b === 168)
    || (a === 100 && b >= 64 && b <= 127);
  if (!privateLan) return '';
  const mask = prefix === 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0;
  const network = numberToIp((ipNum & mask) >>> 0);
  const cidr = `${network}/${prefix}`;
  if (cidr === '10.250.0.0/24') return '';
  return cidr;
}

function parseCidrInfo(cidr) {
  const raw = normalizePrivateCidr(cidr);
  if (!raw) return null;
  const [ip, prefixRaw] = raw.split('/');
  const networkNum = ipToNumber(ip);
  const prefix = Number(prefixRaw);
  if (networkNum === null || !Number.isInteger(prefix)) return null;
  const size = 2 ** (32 - prefix);
  return { cidr: raw, networkNum, prefix, start: networkNum, end: networkNum + size - 1 };
}

// ===================== RAIO-X DO GRAVADOR =====================
// A tela mostrava modelo, serial e uma grade de canais adivinhada. O
// equipamento responde muito mais: foi lendo tudo que apareceu, no NVD 7132 de
// Perucaba, que o NTP estava desligado (e e ele que carimba a hora da gravacao)
// e que a perda de video so valia em 10 dos 32 canais -- 22 cameras podiam cair
// sem gerar evento. Nada disso aparecia em lugar nenhum do sistema.
let _deployRecorderXray = null;

// ---- navegacao por secoes da tela de gravador (substitui as abas antigas) ----
function deployRecorderAbrirSecao(nome) {
  document.querySelectorAll('[data-recorder-sec]').forEach(b =>
    b.classList.toggle('active', b.dataset.recorderSec === nome));
  document.querySelectorAll('[data-recorder-painel]').forEach(p =>
    p.classList.toggle('active', p.dataset.recorderPainel === nome));
  if (nome === 'rede' && _deployStandaloneRecorderProbe && !_deployStandaloneRecorderNetworkLoaded) {
    deployStandaloneRecorderLoadNetwork();
  }
}

function deployRecorderLigarSecoes() {
  document.querySelectorAll('[data-recorder-sec]').forEach(b => {
    if (b.dataset.secBound) return;
    b.dataset.secBound = '1';
    b.addEventListener('click', () => deployRecorderAbrirSecao(b.dataset.recorderSec));
  });
}

// KPIs do topo: os numeros que o tecnico quer de relance.
// A secao Equipamento mostrava cartoes enormes, um por linha, repetindo os KPIs
// do topo e dizendo "Modelo nao informado" -- o probe do login nao traz modelo,
// mas o raio-x traz (NVD 7132). Aqui e so identidade, em pares compactos.
function deployRecorderPintarEquipamento(d) {
  const box = document.getElementById('deployStandaloneRecorderSummary');
  if (!box || !d) return;
  const eq = d.equipamento || {};
  const rede = d.rede || {};
  const pares = [
    ['Fabricante', d.marca],
    ['Modelo', eq.modelo],
    ['Serial', eq.serial],
    ['Firmware', eq.firmware],
    ['Compilacao', eq.compilacao],
    ['Processador', eq.processador],
    ['Plataforma', eq.plataforma],
    ['Nome no equipamento', eq.nome],
    ['MAC', eq.mac || rede.mac],
    ['Host', d.host],
    ['Tipo', eq.tipo],
    ['Ligado ha', d.uptime_s ? Math.floor(Number(d.uptime_s) / 86400) + ' dias' : ''],
  ].filter(([, v]) => String(v || '').trim());
  box.innerHTML = `<dl class="recorder-pares">${pares.map(([k, v]) =>
    `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>`;
}

function deployRecorderPintarKpis(d) {
  const el = document.getElementById('deployRecorderKpis');
  if (!el) return;
  if (!d) { el.innerHTML = ''; return; }
  const r = d.resumo || {};
  const capacidade = (d.discos || []).reduce((s, x) => s + (Number(x.total_tb) || 0), 0);
  const itens = [
    [r.canais_total, 'canais', ''],
    [r.canais_usados, 'em uso', ''],
    [r.canais_livres, 'livres', ''],
    [r.offline, 'offline', r.offline ? 'erro' : ''],
    [r.discos, 'discos', r.discos_com_erro ? 'erro' : ''],
    [capacidade ? capacidade.toFixed(1) + ' TB' : '-', 'capacidade', ''],
  ];
  el.innerHTML = itens.map(([v, rot, cls]) =>
    `<div class="recorder-kpi ${cls}"><b>${esc(String(v ?? '-'))}</b><span>${esc(rot)}</span></div>`).join('');
}

async function deployRecorderCarregarXray() {
  const p = deployStandaloneRecorderPayload();
  // Senha vazia nao e impedimento: em gravador conhecido quem tem a senha e o
  // servidor. Sem esta excecao o raio-x saia calado e a tela ficava parada.
  if (!p.recorder_host || !p.recorder_user) return;
  if (!p.recorder_password && !recTemSenhaSalva(p.recorder_host)) return;
  deployRecorderPintarCarregando();
  recProgresso(p.recorder_host, 1);
  try {
    const res = await api('/api/deployments/recorder-xray', {
      method: 'POST',
      body: JSON.stringify({
        recorder_host: p.recorder_host,
        recorder_user: p.recorder_user,
        recorder_password: p.recorder_password,
        recorder_http_port: p.recorder_http_port,
        connector_id: p.connector_id || '',
      }),
    });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) {
      deployRecorderPintarErro(data?.detail || data?.error || 'nao consegui ler o gravador');
      recProgressoErro(data?.detail || data?.error);
      return;
    }
    recProgresso(p.recorder_host, 2);
    _deployRecorderXray = data;
    deployRecorderPintarXray(data);
    recProgressoFim();
    recPintarApp();
  } catch (e) {
    deployRecorderPintarErro(String(e?.message || e));
    recProgressoErro(e?.message || e);
  }
}

function _dx(id) { return document.getElementById(id); }

function deployRecorderPintarCarregando() {
  const msg = `<div class="recorder-discovery-empty"><i data-lucide="loader"></i>
    <div><b>Lendo o gravador</b><span>No Intelbras sao 23 secoes de configuracao; leva alguns segundos.</span></div></div>`;
  ['deployRecorderAchados', 'deployRecorderCanaisTabela'].forEach(id => { const el = _dx(id); if (el) el.innerHTML = msg; });
  lucide.createIcons();
}

function deployRecorderPintarErro(detalhe) {
  const el = _dx('deployRecorderAchados');
  if (el) el.innerHTML = `<div class="recorder-discovery-empty"><i data-lucide="alert-triangle"></i>
    <div><b>Nao consegui ler o gravador</b><span>${esc(detalhe)}</span></div></div>`;
  lucide.createIcons();
}

// Achados: cada um e um problema real, dito em linguagem de operacao, com o
// porque importa -- nao o nome do campo que veio errado.
function deployRecorderAchados(d) {
  const out = [];
  const s = d.servicos || {};
  const det = d.deteccao || {};
  const rede = d.rede || {};

  if (s.ntp_ligado === false) out.push(['erro', 'NTP desligado',
    'O relogio do gravador anda sozinho, e e ele que carimba a hora da gravacao. Com o tempo, procurar um evento pelo horario devolve o trecho errado.']);
  if (rede.dns === '') out.push(['aviso', 'DNS nao configurado',
    'Sem DNS o gravador nao resolve nome nenhum: NTP por nome, e-mail e nuvem nao funcionam.']);
  if (s.https_ligado === false) out.push(['info', 'HTTPS desligado',
    'O acesso ao gravador trafega em texto claro na rede do cliente.']);
  if (s.email_ligado === false) out.push(['info', 'E-mail de alerta desligado',
    'Nenhum aviso sai do gravador quando um alarme dispara.']);

  const perda = det.perda_video || det.videoloss;
  if (perda && perda.total && perda.ligados < perda.total) {
    const faltam = perda.total - perda.ligados;
    out.push(['erro', `${faltam} canais nao avisam se a camera cair`,
      `Perda de video esta ligada em ${perda.ligados} de ${perda.total}. Nos outros, a camera pode sumir sem gerar evento nenhum.`]);
  }
  const movida = det.movida;
  if (movida && movida.total && movida.ligados === 0) {
    out.push(['aviso', `${movida.total} canais sem deteccao de camera movida`,
      'Ninguem e avisado se alguem girar a camera para o outro lado.']);
  }
  (d.discos || []).forEach(disco => {
    if (disco.erro) out.push(['erro', `Disco ${disco.id} com falha`,
      'Um disco saiu do conjunto. A retencao cai e o risco de perder imagem sobe.']);
  });
  if ((d.resumo || {}).offline) out.push(['erro', `${d.resumo.offline} canal(is) sem imagem`,
    'A camera esta cadastrada no canal mas nao responde.']);
  if (d.usuarios === 1) out.push(['erro', 'Um unico usuario no equipamento',
    'Todo mundo entra como admin: nao da para saber quem mexeu nem revogar acesso de uma pessoa so.']);
  if (rede.mtu && String(rede.mtu) !== '1500') out.push(['aviso', `MTU em ${esc(rede.mtu)}`,
    'MTU fora de 1500 em tunel costuma derrubar pacote cheio e travar video sem derrubar o ping.']);

  if (!out.length) out.push(['ok', 'Nada fora do lugar', 'Servicos, deteccao e discos conferidos, sem achado.']);
  return out;
}

function deployRecorderPintarXray(d) {
  const r = d.resumo || {};
  deployRecorderPintarKpis(d);
  deployRecorderPintarEquipamento(d);
  const nome = document.getElementById('deployRecorderEquipNome');
  const sub = document.getElementById('deployRecorderEquipSub');
  const eq = d.equipamento || {};
  if (nome) nome.textContent = [eq.modelo, eq.nome].filter(Boolean).join(' · ') || d.host || 'Gravador';
  if (sub) sub.textContent = [d.marca, d.host, eq.firmware ? 'firmware ' + eq.firmware : '']
    .filter(Boolean).join(' · ');

  // --- achados
  const achados = deployRecorderAchados(d);
  const elA = _dx('deployRecorderAchados');
  if (elA) elA.innerHTML = achados.map(([nivel, tit, txt]) => `
    <div class="recorder-achado ${esc(nivel)}">
      <i data-lucide="${nivel === 'erro' ? 'alert-circle' : nivel === 'aviso' ? 'alert-triangle' : nivel === 'ok' ? 'check-circle' : 'info'}"></i>
      <div><b>${esc(tit)}</b><span>${esc(txt)}</span></div>
    </div>`).join('');

  // --- canais
  const elC = _dx('deployRecorderCanaisTabela');
  if (elC) {
    const linhas = (d.canais || []).map(c => `<tr>
      <td>${esc(String(c.canal).padStart(2, '0'))}</td>
      <td><b>${esc(c.nome || '-')}</b></td>
      <td>${esc(c.ip || '-')}</td>
      <td>${esc(c.modelo || '-')}</td>
      <td>${esc(c.resolucao || '-')}</td>
      <td>${esc(c.fps || '-')}</td>
      <td>${esc(c.taxa_kbps ? c.taxa_kbps + ' kbps' : '-')}</td>
      <td>${esc(c.codec || '-')}</td>
      <td>${esc(c.protocolo || '-')}</td>
      <td>${c.online === false ? '<span class="recorder-pill erro">offline</span>'
          : c.ip ? '<span class="recorder-pill ok">ok</span>' : '<span class="recorder-pill neutro">livre</span>'}</td>
    </tr>`).join('');
    elC.innerHTML = `<div class="recorder-tabela-rolo"><table class="recorder-tabela">
      <thead><tr><th>#</th><th>Nome</th><th>IP</th><th>Modelo</th><th>Resolucao</th><th>FPS</th>
      <th>Taxa</th><th>Codec</th><th>Protocolo</th><th>Estado</th></tr></thead>
      <tbody>${linhas}</tbody></table></div>`;
  }

  // --- discos
  const elD = _dx('deployRecorderStorage');
  if (elD) {
    elD.innerHTML = (d.discos || []).length
      ? (d.discos || []).map(x => `<div${x.erro ? ' class="erro"' : ''}>
          <span>Disco ${esc(x.id)}${x.tipo ? ' · ' + esc(x.tipo) : ''}</span>
          <b>${x.total_tb ? esc(x.total_tb) + ' TB' : esc(x.situacao || '-')}</b>
          <small>${x.erro ? 'com falha' : (x.livre_tb !== undefined ? esc(x.livre_tb) + ' TB livres' : 'em uso')}</small>
        </div>`).join('')
      : `<div><span>Discos</span><b>nenhum</b><small>O gravador nao reportou disco: sem gravacao.</small></div>`;
  }

  // --- gravacao / deteccao
  const elG = _dx('deployRecorderRecording');
  if (elG) {
    const det = d.deteccao || {};
    elG.innerHTML = Object.entries(det).map(([nome, v]) => {
      const pct = v.total ? Math.round((v.ligados / v.total) * 100) : 0;
      const cls = pct === 0 ? ' class="erro"' : pct < 60 ? ' class="aviso"' : '';
      return `<div${cls}><span>${esc(deployRecorderRotulo(nome))}</span>
        <b>${v.ligados} de ${v.total}</b><small>canais com a analise ligada</small></div>`;
    }).join('') || '<div><span>Deteccao</span><b>nao informada</b><small>Este modelo nao expoe as analises.</small></div>';
  }

  // --- servicos (aba rede)
  const elS = _dx('deployRecorderServicos');
  if (elS) {
    const s = d.servicos || {};
    const itens = [
      ['NTP', s.ntp_ligado, s.ntp_servidor || ''],
      ['HTTPS', s.https_ligado, ''],
      ['E-mail', s.email_ligado, ''],
      ['SNMP', s.snmp_ligado, ''],
      ['NAS', s.nas_ligado, ''],
    ].filter(([, v]) => v !== undefined);
    elS.innerHTML = itens.map(([rot, lig, extra]) =>
      `<div${lig ? '' : ' class="aviso"'}><span>${esc(rot)}</span><b>${lig ? 'ligado' : 'desligado'}</b>
       <small>${esc(extra || (lig ? 'ativo no equipamento' : 'nao esta em uso'))}</small></div>`).join('');
  }

  // --- cabecalho de descoberta ganha os numeros reais
  const elR = _dx('deployRecorderDiscoveryStatus');
  if (elR) {
    elR.className = 'recorder-head-status ' + (r.offline || r.discos_com_erro ? 'error' : 'ok');
    elR.innerHTML = `<i data-lucide="circle-check"></i><span>${esc(d.marca)} · ${r.canais_usados}/${r.canais_total} canais · ${r.discos} disco(s)</span>`;
  }
  lucide.createIcons();
}

function deployRecorderRotulo(chave) {
  return ({
    movimento: 'Movimento', perda_video: 'Perda de video', encoberta: 'Camera encoberta',
    movida: 'Camera movida', audio: 'Audio', VMD: 'Movimento', videoloss: 'Perda de video',
    fielddetection: 'Invasao de area', linedetection: 'Cruzamento de linha',
    facedetection: 'Face', faceSnap: 'Captura de face', regionEntrance: 'Entrada em regiao',
    regionExiting: 'Saida de regiao', personDensityDetection: 'Densidade de pessoas',
    objectsThrownDetection: 'Objeto abandonado', channelOccupy: 'Canal ocupado',
  })[chave] || chave;
}

// ===================== CONSOLE DO GRAVADOR =====================
// Redesenho aprovado em 01/10/2026. O que mudou e densidade:
//   - uma barra de contexto de uma linha no lugar de tres blocos repetindo
//     nome, IP e marca;
//   - os seis cartoes de numero viraram texto na barra (numero so merece
//     cartao quando e o assunto da tela; aqui e identificacao);
//   - navegacao vertical com contador por secao, em vez de pilulas grandes;
//   - o mosaico ocupa a tela, imagens coladas e sem moldura, como mural de
//     CFTV.
let _recSec = 'vivo';
let _recCols = '4';
let _recEdit = null;   // canal em edicao

const _REC_SECOES = [
  ['vivo', 'Ao vivo'], ['achados', 'Achados'], ['canais', 'Canais'],
  ['discos', 'Discos'], ['deteccao', 'Deteccao'], ['rede', 'Rede'], ['equip', 'Equipamento'],
];

function recRot(k) {
  return ({ movimento:'Movimento', perda_video:'Perda de video', encoberta:'Camera encoberta',
    movida:'Camera movida', audio:'Audio', VMD:'Movimento', videoloss:'Perda de video',
    fielddetection:'Invasao de area', linedetection:'Cruzamento de linha', facedetection:'Face',
    faceSnap:'Captura de face', regionEntrance:'Entrada em regiao', regionExiting:'Saida de regiao',
    personDensityDetection:'Densidade de pessoas', objectsThrownDetection:'Objeto abandonado',
    channelOccupy:'Canal ocupado', ChannelPassingEvent:'Passagem no canal',
    disco_cheio:'Disco cheio', disco_falhou:'Disco falhou', sem_disco:'Sem disco',
    ip_duplicado:'IP duplicado', mac_duplicado:'MAC duplicado', rede_caiu:'Rede caiu',
    login_falho:'Login falhou', ventoinha:'Ventoinha', diskfull:'Disco cheio',
    diskerror:'Erro de disco', nicbroken:'Placa de rede', ipconflict:'IP duplicado',
    illaccess:'Acesso ilegal', recordingfailure:'Falha ao gravar', IO:'Entrada de alarme',
  })[k] || k;
}

function recAchadosLista(d) {
  const out = [], s = d.servicos || {}, det = d.deteccao || {}, r = d.rede || {}, z = d.resumo || {};
  if (s.ntp_ligado === false) out.push(['erro', 'NTP desligado',
    'O relogio do gravador anda sozinho, e e ele que carimba a hora da gravacao. Com o tempo, procurar um evento pelo horario devolve o trecho errado.', 'ntp']);
  const pv = det.perda_video || det.videoloss;
  if (pv && pv.total && pv.ligados < pv.total) out.push(['erro',
    `${pv.total - pv.ligados} canais nao avisam se a camera cair`,
    `Perda de video esta ligada em ${pv.ligados} de ${pv.total}. Nos outros, a camera pode sumir sem gerar evento nenhum.`, '']);
  if (z.offline) out.push(['erro', `${z.offline} canal(is) sem imagem`,
    'A camera esta no canal mas nao responde.', '']);
  (d.discos || []).forEach(x => { if (x.erro) out.push(['erro', `Disco ${x.id} com falha`,
    'Um disco saiu do conjunto. A retencao cai e o risco de perder imagem sobe.', '']); });
  if (d.usuarios === 1) out.push(['erro', 'Um unico usuario no equipamento',
    'Todo mundo entra como admin: nao da para saber quem mexeu nem revogar acesso de uma pessoa so.', '']);
  const mv = det.movida;
  if (mv && mv.total && mv.ligados === 0) out.push(['aviso', `${mv.total} canais sem deteccao de camera movida`,
    'Ninguem e avisado se alguem girar a camera para o outro lado.', '']);
  if (r.dns === '') out.push(['aviso', 'DNS nao configurado',
    'Sem DNS o gravador nao resolve nome nenhum: NTP por nome, e-mail e nuvem nao funcionam.', '']);
  if (r.mtu && String(r.mtu) !== '1500') out.push(['aviso', `MTU em ${r.mtu}`,
    'MTU fora de 1500 em tunel costuma derrubar pacote cheio e travar video sem derrubar o ping.', '']);
  if (s.https_ligado === false) out.push(['info', 'HTTPS desligado',
    'O acesso ao gravador trafega em texto claro na rede do cliente.', '']);
  if (s.email_ligado === false) out.push(['info', 'E-mail de alerta desligado',
    'Nenhum aviso sai do gravador quando um alarme dispara.', '']);
  return out;
}

// miniatura do canal, vinda do inventario de gravadores (host + canal)
function recFoto(c, host, deduzir = true) {
  // Tres fontes, nesta ordem, porque a primeira sozinha ja falhou: a tela lia
  // SO o inventario, entao apagar o gravador do inventario deixava o mosaico
  // inteiro sem foto -- mesmo com os JPGs em disco, recem-capturados no login.
  //
  // 1) o que o login acabou de capturar (sempre o mais novo)
  // 2) o que esta gravado no inventario
  // 3) o caminho que o backend usa para escrever o arquivo, deduzido do IP
  //    (ver _capture_recorder_snapshots em app/api/endpoints/deployments.py)
  const canal = Number(c.canal);
  const doProbe = (deployStandaloneRecorderChannelsFromProbe(_deployStandaloneRecorderProbe) || [])
    .find(x => Number(x.channel) === canal);
  const linha = (_deployStandaloneRecorderSavedItems || [])
    .flatMap(x => x.rows || [])
    .find(r => String(r.host || '') === String(host) && Number(r.channel) === canal);

  let bruto = String(doProbe?.snapshot_url || doProbe?.imgbb_url || '').trim();
  if (!bruto) bruto = String(linha?.snapshot_url || linha?.imgbb_url || '').trim();
  if (!bruto && deduzir && host && canal > 0) {
    const seguro = String(host).replace(/[^0-9A-Za-z_-]+/g, '_').replace(/^_+|_+$/g, '') || 'nvr';
    bruto = `/data/nvr_snapshot/deploy_${seguro}_ch${String(canal).padStart(3, '0')}.jpg`;
  }
  if (!bruto) return '';
  return /^https?:\/\//i.test(bruto) ? bruto : `${API_BASE}${bruto}`;
}

function recSecVivo(d) {
  const canais = d.canais || [], host = d.host;
  // Conta so foto de origem conhecida: o caminho deduzido pode nao existir
  // em disco, e dizer "32 com imagem" sem ter seria mentir no cabecalho.
  const comImagem = canais.filter(c => recFoto(c, host, false)).length;
  const caidos = canais.filter(c => c.online === false).length;
  return `<div class="bloco">
    <div class="bloco-cab">
      <div><h2>Ao vivo</h2><p>${comImagem} com imagem${caidos ? ' · ' + caidos + ' sem resposta' : ''}</p></div>
      <div class="bloco-dir"><div class="seg">
        <button type="button" data-rec-col="2" aria-pressed="${_recCols === '2'}">Grande</button>
        <button type="button" data-rec-col="4" aria-pressed="${_recCols === '4'}">Medio</button>
        <button type="button" data-rec-col="6" aria-pressed="${_recCols === '6'}">Pequeno</button>
      </div></div>
    </div>
    <div class="mosaico" data-col="${_recCols}">${canais.map(c => {
      const foto = recFoto(c, host), n = String(c.canal).padStart(2, '0');
      if (!c.ip) return `<div class="cam livre"><div class="vazio">canal ${n} livre</div></div>`;
      const caiu = c.online === false;
      return `<div class="cam ${caiu ? 'caiu' : ''}" data-rec-vivo="${esc(c.canal)}"
        title="${esc([c.nome, c.ip, 'clique para ver ao vivo'].filter(Boolean).join(' · '))}">
        ${foto ? `<img src="${esc(foto)}" alt="" loading="lazy" onerror="this.remove()">`
               : `<div class="vazio">${caiu ? 'sem sinal' : 'sem imagem'}</div>`}
        <div class="marca"><span class="n">${n}</span>${caiu ? '' : '<span class="rec"><i></i>REC</span>'}</div>
        <div class="rotulo">${esc(c.nome || c.ip)}</div>
      </div>`;
    }).join('')}</div>
  </div>`;
}

function recSecAchados(d) {
  const itens = recAchadosLista(d);
  if (!itens.length) return `<div class="bloco"><div class="bloco-cab">
    <div><h2>Nada fora do lugar</h2><p>Servicos, deteccao e discos conferidos, sem achado.</p></div></div></div>`;
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>O que precisa de voce</h2><p>Em ordem de impacto</p></div></div>
    ${itens.map(([sev, tit, txt]) => `<div class="achado ${esc(sev)}">
      <span class="sev"></span>
      <div class="achado-txt"><b>${esc(tit)}</b><span>${esc(txt)}</span></div>
    </div>`).join('')}
  </div>`;
}

function recSecCanais(d) {
  const canais = d.canais || [];
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Canais</h2><p>Editar troca os dados sem soltar o canal</p></div>
      <div class="bloco-dir">
        <button class="acao" type="button" data-rec-buscar="1">Buscar cameras</button>
        <button class="acao forte" type="button" data-rec-add="1">+ Adicionar camera</button></div></div>
    <div class="rolo"><table>
      <thead><tr><th>#</th><th>Nome</th><th>IP</th><th>Modelo</th><th>Resolucao</th><th>Codec</th><th>Estado</th><th></th></tr></thead>
      <tbody>${canais.map(c => `<tr>
        <td class="n">${String(c.canal).padStart(2, '0')}</td>
        <td><b>${esc(c.nome || '-')}</b></td>
        <td class="n">${esc(c.ip || '-')}</td>
        <td>${esc(c.modelo || '-')}</td>
        <td class="n">${esc(c.resolucao || '-')}</td>
        <td>${esc(c.codec || '-')}</td>
        <td>${!c.ip ? '<span class="tag neutro">livre</span>'
            : c.online === false ? '<span class="tag erro">offline</span>'
            : '<span class="tag ok">normal</span>'}</td>
        <td><span class="linha-acoes">
          ${c.ip ? `<button class="mini" type="button" data-rec-editar="${c.canal}">Editar</button>
                    <button class="mini perigo" type="button" data-rec-soltar="${c.canal}">Soltar</button>`
                 : `<button class="mini" type="button" data-rec-add="${c.canal}">Usar</button>`}
        </span></td>
      </tr>`).join('')}</tbody>
    </table></div>
  </div>`;
}

function recSecDiscos(d) {
  const ds = d.discos || [];
  const cap = ds.reduce((s, x) => s + (Number(x.total_tb) || 0), 0);
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Discos</h2>
      <p>${ds.length} disco${ds.length === 1 ? '' : 's'}${cap ? ' · ' + cap.toFixed(1) + ' TB' : ''}${
        ds.some(x => x.particoes > 1) ? ' · particionados' : ''}</p></div></div>
    <div class="rolo"><table>
      <thead><tr><th>#</th><th>Disco</th><th>Capacidade</th><th>Particoes</th><th>Tipo</th><th>Estado</th></tr></thead>
      <tbody>${ds.length ? ds.map(x => `<tr>
        <td class="n">${esc(String(x.id).padStart(2, '0'))}</td>
        <td>${esc(x.caminho || '-')}</td>
        <td class="n">${x.total_tb ? esc(x.total_tb) + ' TB' : '-'}</td>
        <td class="n">${x.particoes ? esc(x.particoes) : '-'}</td>
        <td>${esc(x.tipo || '-')}</td>
        <td>${x.erro ? '<span class="tag erro">com falha</span>' : '<span class="tag ok">ok</span>'}</td>
      </tr>`).join('') : '<tr><td colspan="6">O gravador nao reportou disco: sem gravacao.</td></tr>'}</tbody>
    </table></div>
  </div>`;
}

function recSecDeteccao(d) {
  const det = Object.entries(d.deteccao || {}), al = Object.entries(d.alarmes || {});
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Deteccao por canal</h2><p>Quantos canais tem cada analise ligada</p></div></div>
    <div class="rolo"><table>
      <thead><tr><th>Analise</th><th>Cobertura</th><th>Canais</th></tr></thead>
      <tbody>${det.length ? det.map(([k, v]) => {
        const pct = v.total ? Math.round(v.ligados / v.total * 100) : 0;
        return `<tr><td><b>${esc(recRot(k))}</b></td>
          <td>${pct === 0 ? '<span class="tag erro">nenhum canal</span>'
              : pct < 60 ? `<span class="tag" style="background:var(--amber-soft);color:var(--amber)">${pct}%</span>`
              : `<span class="tag ok">${pct}%</span>`}</td>
          <td class="n">${v.ligados} de ${v.total}</td></tr>`;
      }).join('') : '<tr><td colspan="3">Este modelo nao expoe as analises.</td></tr>'}</tbody>
    </table></div>
    ${al.length ? `<div class="bloco-cab" style="border-top:1px solid var(--border)">
      <div><h2>Alarmes do equipamento</h2><p>Falhas que o gravador vigia sozinho</p></div></div>
    <div class="rolo"><table><tbody>${al.map(([k, on]) => `<tr><td><b>${esc(recRot(k))}</b></td>
      <td>${on ? '<span class="tag ok">ligado</span>' : '<span class="tag erro">desligado</span>'}</td></tr>`).join('')}</tbody></table></div>` : ''}
  </div>`;
}

function recPares(titulo, sub, pares) {
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>${esc(titulo)}</h2><p>${esc(sub)}</p></div></div>
    <div class="rolo"><table><tbody>${pares.map(([k, v, cls]) =>
      `<tr><td style="color:var(--muted);width:40%">${esc(k)}</td>
       <td><b${cls === 'ruim' ? ' style="color:var(--danger)"' : cls === 'bom' ? ' style="color:var(--primary)"' : ''}>${esc(v)}</b></td></tr>`
    ).join('')}</tbody></table></div>
  </div>`;
}

function recSecRede(d) {
  const r = d.rede || {}, s = d.servicos || {};
  const linhas = [
    ['IP', r.ip, ''], ['Mascara', r.mascara, ''], ['Gateway', r.gateway, ''],
    ['MAC', r.mac, ''], ['MTU', r.mtu, (r.mtu && String(r.mtu) !== '1500') ? 'ruim' : ''],
    ['DNS', r.dns || 'nao configurado', r.dns ? '' : 'ruim'],
    ['Enderecamento', r.enderecamento, ''],
  ].filter(([, v]) => String(v || '').trim());
  const serv = [['NTP', s.ntp_ligado], ['HTTPS', s.https_ligado], ['E-mail', s.email_ligado],
                ['SNMP', s.snmp_ligado], ['NAS', s.nas_ligado]].filter(([, v]) => v !== undefined)
    .map(([k, v]) => [k, v ? 'ligado' : 'desligado', v ? 'bom' : 'ruim']);
  return recPares('Rede', 'Em vermelho, o que esta faltando ou fora do padrao', linhas)
       + (serv.length ? recPares('Servicos', 'Lido do equipamento', serv) : '');
}

function recSecEquip(d) {
  const eq = d.equipamento || {}, r = d.rede || {};
  return recPares('Equipamento', 'Identidade e versao', [
    ['Fabricante', d.marca], ['Modelo', eq.modelo], ['Serial', eq.serial],
    ['Firmware', eq.firmware], ['Compilacao', eq.compilacao], ['Processador', eq.processador],
    ['Plataforma', eq.plataforma], ['MAC', eq.mac || r.mac], ['Host', d.host],
    ['Ligado ha', d.uptime_s ? Math.floor(Number(d.uptime_s) / 86400) + ' dias' : ''],
    ['Usuarios', d.usuarios],
  ].filter(([, v]) => String(v || '').trim()).map(([k, v]) => [k, v, '']));
}

const _REC_SEC_RENDER = { vivo: recSecVivo, achados: recSecAchados, canais: recSecCanais,
  discos: recSecDiscos, deteccao: recSecDeteccao, rede: recSecRede, equip: recSecEquip };

function recContagem(d, id) {
  const z = d.resumo || {};
  if (id === 'achados') { const n = recAchadosLista(d).filter(x => x[0] === 'erro').length; return n || null; }
  if (id === 'canais') return z.canais_total || null;
  if (id === 'discos') return z.discos || null;
  return null;
}

// Entrar num gravador demora -- no Intelbras sao 23 secoes de configuracao, uns
// 13 segundos. Sem nada na tela parecia travado, entao o passo corrente fica
// visivel aqui o tempo todo.
let _recProgresso = null;

const _REC_PASSOS = [
  ['Conectando no gravador', 'confere o acesso e a credencial'],
  ['Lendo a configuracao', 'canais, discos, deteccao, rede e servicos'],
  ['Montando a tela', 'quase la'],
];

function recProgresso(host, passo) {
  _recProgresso = { host: host || '', passo: Number(passo) || 0, erro: '' };
  recPintarApp();
}

function recProgressoErro(detalhe) {
  if (_recProgresso) _recProgresso.erro = String(detalhe || 'nao consegui ler o gravador');
  recPintarApp();
}

function recProgressoFim() {
  _recProgresso = null;
}

function recPintarProgresso() {
  const g = _recProgresso || {};
  if (g.erro) {
    return `<div class="bloco rec-progresso"><div class="bloco-cab">
      <div><h2>Nao consegui entrar em ${esc(g.host)}</h2><p>${esc(g.erro)}</p></div>
      <div class="bloco-dir"><button class="acao" type="button" data-rec-fechar-erro>Fechar</button></div>
      </div></div>`;
  }
  return `<div class="bloco rec-progresso">
    <div class="rec-prog-cab">
      <span class="rec-prog-giro" aria-hidden="true"></span>
      <div><h2>Entrando em ${esc(g.host)}</h2>
      <p>O gravador responde devagar; isso leva alguns segundos.</p></div>
    </div>
    <ol class="rec-prog-passos">${_REC_PASSOS.map(([rot, det], i) => {
      const estado = i < g.passo ? 'feito' : (i === g.passo ? 'agora' : 'espera');
      return `<li class="${estado}"><span class="rec-prog-pino"></span>
        <b>${esc(rot)}</b><span>${esc(det)}</span></li>`;
    }).join('')}</ol>
    <div class="rec-prog-esqueleto">
      <div class="rec-prog-barra"></div><div class="rec-prog-barra"></div>
      <div class="rec-prog-barra"></div><div class="rec-prog-barra"></div>
    </div>
  </div>`;
}

function recSair() {
  // Sem isto so o F5 tirava o operador daqui: a tela do gravador aberta nao
  // tinha nenhuma saida.
  recFecharVivo();
  _deployRecorderXray = null;
  _deployStandaloneRecorderProbe = null;
  _deployStandaloneRecorderNetworkLoaded = false;
  _recProgresso = null;
  _recSec = 'vivo';
  deployStandaloneRecorderRenderProbe(null);
  deployStandaloneRecorderClearRecorderFields();
  recPintarApp();
  lucide.createIcons();
}

let _recVivoHandle = null;
let _recVivoAlvo = null;

function recFecharVivo() {
  if (_recVivoHandle) { try { _recVivoHandle.stop(); } catch (_) {} _recVivoHandle = null; }
  // Avisa o servidor para tirar o canal do go2rtc: a fonte guardada la tem a
  // senha RTSP do gravador, e stream esquecido ja foi causa de vazamento de
  // credencial neste sistema.
  if (_recVivoAlvo) {
    const alvo = _recVivoAlvo;
    _recVivoAlvo = null;
    api('/api/deployments/recorder-live-stop', { method: 'POST', body: JSON.stringify(alvo) })
      .catch(() => {});
  }
}

let _recVivoAlta = true;

function recAbrirVivo(canal) {
  // Video ao vivo pelo RTSP do PROPRIO gravador, servido ao navegador pelo
  // go2rtc (o mesmo player das cameras). O gravador vive atras do tunel do
  // conector, entao quem fala com ele e o backend -- a senha nunca chega aqui.
  const d = _deployRecorderXray;
  if (!d) return;
  const dados = (d.canais || []).find(c => Number(c.canal) === Number(canal));
  if (!dados || !dados.ip) { showToast('Canal livre: nao ha camera para ver.', true); return; }

  const p = deployStandaloneRecorderPayload();
  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  const nome = dados.nome || dados.ip;
  const n = String(canal).padStart(2, '0');

  tampa.innerHTML = `<div class="rec-tampa rec-tampa-vivo" role="dialog" aria-modal="true" aria-label="Ao vivo">
    <div class="rec-vivo">
      <div class="rec-vivo-topo">
        <div class="rec-vivo-id">
          <b>${esc(n)} · ${esc(nome)}</b>
          <span>${esc(dados.ip)}${dados.modelo ? ' · ' + esc(dados.modelo) : ''} · ${esc(d.host)}</span>
        </div>
        <div class="rec-vivo-acoes">
          <span class="rec-vivo-taxa" id="recVivoTaxa"></span>
          <div class="seg rec-vivo-seg">
            <button type="button" data-rec-q="1" aria-pressed="${_recVivoAlta}">Alta</button>
            <button type="button" data-rec-q="0" aria-pressed="${!_recVivoAlta}">Leve</button>
          </div>
          <button class="rec-vivo-bt" type="button" data-rec-tela title="Tela cheia" aria-label="Tela cheia">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3m18 0V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3m13-5v3a2 2 0 0 1-2 2h-3"/></svg>
          </button>
          <button class="rec-vivo-bt" type="button" data-rec-fechar title="Fechar" aria-label="Fechar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
          </button>
        </div>
      </div>
      <div class="rec-vivo-palco" id="recVivoPalco">
        <video id="recVivoVideo" autoplay muted playsinline></video>
        <div class="rec-vivo-aviso" id="recVivoAviso">Conectando...</div>
      </div>
    </div></div>`;

  const video = document.getElementById('recVivoVideo');
  const aviso = document.getElementById('recVivoAviso');
  const palco = document.getElementById('recVivoPalco');
  const taxa = document.getElementById('recVivoTaxa');

  const ligar = () => {
    recFecharVivo();
    const alvo = {
      recorder_host: d.host || p.recorder_host,
      canal: Number(canal),
      http_port: p.recorder_http_port || '',
      connector_id: p.connector_id || '',
      marca: d.marca || '',
      alta: _recVivoAlta ? 1 : 0,
    };
    _recVivoAlvo = alvo;
    if (aviso) { aviso.hidden = false; aviso.textContent = 'Conectando...'; }
    if (taxa) taxa.textContent = '';
    _recVivoHandle = mountLiveStream(video, {
      ip: alvo.recorder_host, user: 'admin', pass: '', subtype: _recVivoAlta ? 0 : 1,
      // O backend e quem sabe a senha do gravador e o caminho RTSP de cada
      // marca; daqui so pedimos o stream pronto.
      registrar: async () => {
        const res = await api('/api/deployments/recorder-live-stream', {
          method: 'POST', body: JSON.stringify(alvo),
        });
        const r = await res?.json().catch(() => ({}));
        if (res?.status === 428) throw new Error('Este gravador nao tem senha guardada.');
        if (!res?.ok || !r?.stream_name) throw new Error(r?.detail || 'nao consegui preparar o video');
        return r.stream_name;
      },
      onStatus: texto => {
        if (!aviso) return;
        if (texto) { aviso.hidden = false; aviso.textContent = texto; }
        else {
          aviso.hidden = true;
          if (taxa) taxa.textContent = `${video.videoWidth || ''}×${video.videoHeight || ''}`;
        }
      },
    });
  };

  video.addEventListener('loadedmetadata', () => {
    if (taxa) taxa.textContent = `${video.videoWidth}×${video.videoHeight}`;
  });

  tampa.querySelectorAll('[data-rec-q]').forEach(b => b.addEventListener('click', () => {
    const alta = b.dataset.recQ === '1';
    if (alta === _recVivoAlta) return;
    _recVivoAlta = alta;
    tampa.querySelectorAll('[data-rec-q]').forEach(x =>
      x.setAttribute('aria-pressed', String((x.dataset.recQ === '1') === _recVivoAlta)));
    ligar();
  }));

  tampa.querySelector('[data-rec-tela]')?.addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen?.();
    else palco?.requestFullscreen?.().catch(() => showToast('O navegador nao permitiu tela cheia.', true));
  });

  const fechar = () => { recFecharVivo(); tampa.innerHTML = ''; };
  tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) fechar();
  });
  ligar();
}

function recNomeDoGravador(d) {
  // O nome que vai pro inventario tem que ser o do EQUIPAMENTO. Antes vinha do
  // campo do formulario, que nascia com o site ou com o que tivesse sobrado da
  // tela anterior -- dai "DVR-01" virar o nome de um NVD 7132 e ninguem mais
  // reconhecer o gravador na lista.
  const eq = (d && d.equipamento) || {};
  const p = _deployStandaloneRecorderProbe || {};
  return String(eq.nome || p.name || eq.modelo || p.model || (d && d.host) || '').trim();
}

async function recSalvarInventario(botao) {
  const d = _deployRecorderXray;
  if (!d) { showToast('Entre num gravador antes de salvar.', true); return; }

  // O nome e escolhido por quem salva, nao inventado pelo sistema. O campo ja
  // vem com o nome que este gravador tem hoje no inventario; so quando ele
  // ainda nao existe la e que o equipamento serve de sugestao.
  const host = d.host || '';
  const noInventario = (_deployStandaloneRecorderSavedItems || [])
    .find(x => String(x.host || '') === String(host) && String(x.name || '').trim());
  const sugestao = (noInventario && noInventario.name) || recNomeDoGravador(d);

  recPedirNome(sugestao, d, async nome => {
    const campo = document.getElementById('deployStandaloneRecorderName');
    if (campo) campo.value = nome;
    if (botao) { botao.disabled = true; botao.textContent = 'Salvando...'; }
    try {
      await deployStandaloneRecorderSave();
    } finally {
      if (botao) {
        botao.disabled = false;
        botao.textContent = _deployStandaloneRecorderSaved ? 'Salvo no inventario' : 'Salvar no inventario';
      }
    }
  });
}

function recPedirNome(sugestao, d, aoConfirmar) {
  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  const fechar = () => { tampa.innerHTML = ''; };
  const p = deployStandaloneRecorderPayload();
  const tipo = (p.recorder_type || 'nvr').toUpperCase();
  const site = p.site || '';

  tampa.innerHTML = `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="Nome do gravador">
    <div class="rec-caixa rec-caixa-estreita">
      <div class="rec-caixa-cab">
        <h3>Nome deste gravador</h3>
        <p>E assim que ele aparece no inventario, em relatorio e na busca.</p>
      </div>
      <div class="rec-caixa-corpo">
        <label class="rec-campo"><span>Nome</span>
          <input id="recNomeCampo" autocomplete="off" value="${esc(sugestao)}"></label>
        <p class="rec-dica">${esc(tipo)}${site ? ' · ' + esc(site) : ''} · ${esc(d.host || '')}
        · ${esc((d.equipamento || {}).modelo || '')}</p>
        <p class="rec-erro" id="recNomeErro" hidden></p>
      </div>
      <div class="rec-caixa-pe">
        <button class="acao" type="button" data-rec-fechar>Cancelar</button>
        <button class="acao forte" type="button" data-rec-ok>Salvar</button>
      </div>
    </div></div>`;

  const campo = document.getElementById('recNomeCampo');
  const erro = document.getElementById('recNomeErro');
  campo?.focus();
  campo?.select();

  const confirmar = () => {
    const nome = (campo?.value || '').trim();
    if (!nome) {
      if (erro) { erro.hidden = false; erro.textContent = 'Da um nome ao gravador.'; }
      campo?.focus();
      return;
    }
    fechar();
    aoConfirmar(nome);
  };
  tampa.querySelector('[data-rec-ok]')?.addEventListener('click', confirmar);
  tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  campo?.addEventListener('keydown', ev => { if (ev.key === 'Enter') confirmar(); });
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) fechar();
  });
}

function recPintarApp() {
  const app = document.getElementById('deployRecorderApp');
  if (!app) return;
  const d = _deployRecorderXray;
  // Com um gravador aberto, a lista some: a barra ja tem o seletor, e manter
  // os dois empurrava o conteudo para fora da primeira tela.
  // A lista de cartoes saiu: nao escala (ha clientes com 64 gravadores).
  // Quem troca de gravador e o seletor com busca, pelo nome na barra.
  const lista = document.getElementById('deployRecorderLista');
  if (lista) lista.hidden = true;
  // "Entrar em gravador" vive no cabecalho, ao lado de "Cadastrar gravador":
  // e a acao da pagina inteira, nao do bloco de aviso.
  const topo = document.getElementById('btnRecEntrarSeletor');
  if (topo && !topo.dataset.ligado) {
    topo.dataset.ligado = '1';
    topo.addEventListener('click', () => recAbrirSeletor());
  }
  if (!d && _recProgresso) {
    app.innerHTML = recPintarProgresso();
    app.querySelector('[data-rec-fechar-erro]')?.addEventListener('click', () => {
      _recProgresso = null;
      recPintarApp();
    });
    return;
  }
  if (!d) {
    app.innerHTML = `<div class="bloco"><div class="bloco-cab">
      <div><h2>Nenhum gravador aberto</h2>
      <p>Use "Entrar em gravador" ali em cima. A leitura traz canais, discos, deteccao e rede.</p></div>
      </div></div>`;
    return;
  }
  const eq = d.equipamento || {}, z = d.resumo || {};
  const cap = (d.discos || []).reduce((s, x) => s + (Number(x.total_tb) || 0), 0);
  const criticos = recAchadosLista(d).filter(x => x[0] === 'erro').length;

  app.innerHTML = `
    <div class="barra">
      <div class="barra-id"><button class="barra-sel" type="button" data-rec-trocar="1">
        <b>${esc(eq.modelo || d.host)}</b><span>· ${esc(d.host)}</span>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="m6 9 6 6 6-6"/></svg>
      </button></div>
      <div class="barra-meta">
        <span><b>${esc(z.canais_total)}</b> canais</span>
        ${z.canais_livres ? `<span><b>${esc(z.canais_livres)}</b> livres</span>` : ''}
        <span><b>${esc(z.discos)}</b> discos</span>
        ${cap ? `<span><b>${cap.toFixed(1)} TB</b></span>` : ''}
        <span>${esc([d.marca, eq.firmware].filter(Boolean).join(' · '))}</span>
      </div>
      <div class="barra-dir">
        ${criticos ? `<span class="sinal erro"><i></i>${criticos} achados</span>`
                   : '<span class="sinal ok"><i></i>sem achado</span>'}
        <button class="acao forte" type="button" data-rec-salvar="1">Salvar no inventario</button>
        <button class="acao" type="button" data-rec-reler="1">Reler</button>
        <button class="acao" type="button" data-rec-sair="1" title="Fechar o gravador e voltar">Sair</button>
      </div>
    </div>
    <div class="corpo">
      <nav class="nav" aria-label="Secoes">${_REC_SECOES.map(([id, rot]) => {
        const n = recContagem(d, id);
        return `<button type="button" data-rec-sec="${id}" aria-current="${id === _recSec}">
          <span class="pino"></span>${esc(rot)}
          ${n != null ? `<span class="conta ${id === 'achados' ? 'alerta' : ''}">${n}</span>` : ''}
        </button>`;
      }).join('')}</nav>
      <div class="conteudo">${(_REC_SEC_RENDER[_recSec] || recSecVivo)(d)}</div>
    </div>`;

  app.querySelectorAll('[data-rec-sec]').forEach(b =>
    b.addEventListener('click', () => { _recSec = b.dataset.recSec; recPintarApp(); }));
  app.querySelectorAll('[data-rec-col]').forEach(b =>
    b.addEventListener('click', () => { _recCols = b.dataset.recCol; recPintarApp(); }));
  app.querySelector('[data-rec-reler]')?.addEventListener('click', () => deployRecorderCarregarXray());
  app.querySelector('[data-rec-sair]')?.addEventListener('click', () => recSair());
  app.querySelector('[data-rec-salvar]')?.addEventListener('click', ev => recSalvarInventario(ev.target));
  app.querySelectorAll('[data-rec-vivo]').forEach(el =>
    el.addEventListener('click', () => recAbrirVivo(Number(el.dataset.recVivo))));
  app.querySelector('[data-rec-trocar]')?.addEventListener('click', () => recAbrirSeletor());
  app.querySelectorAll('[data-rec-editar]').forEach(b =>
    b.addEventListener('click', () => recAbrirEdicao('editar', Number(b.dataset.recEditar))));
  app.querySelector('[data-rec-buscar]')?.addEventListener('click', () => recBuscarCameras());
  app.querySelectorAll('[data-rec-add]').forEach(b =>
    b.addEventListener('click', () => recAbrirEdicao('adicionar', Number(b.dataset.recAdd) || 0)));
  app.querySelectorAll('[data-rec-soltar]').forEach(b =>
    b.addEventListener('click', () => recAbrirEdicao('excluir', Number(b.dataset.recSoltar))));
}

// ---- adicionar / editar / soltar canal ----
// Equipamento vivo: a caixa diz o que vai acontecer ANTES de mandar, e o aviso
// de impacto aparece em vermelho quando a acao tira algo do ar.
// Ordenacao das listas de busca. IP nao e texto: ordenar "100.65.10.9" como
// string poe ele depois de "100.65.10.10". Compara octeto a octeto.
function _recChaveIp(valor) {
  const partes = String(valor || '').split('.');
  if (partes.length === 4 && partes.every(x => /^\d+$/.test(x))) {
    return partes.reduce((n, x) => n * 256 + Number(x), 0);
  }
  return null;
}

function _recOrdenar(linhas, campo, desc) {
  const copia = [...linhas];
  copia.sort((a, b) => {
    const va = a[campo], vb = b[campo];
    const ia = _recChaveIp(va), ib = _recChaveIp(vb);
    let r;
    if (ia != null && ib != null) r = ia - ib;
    else if (typeof va === 'boolean' || typeof vb === 'boolean') r = (va ? 1 : 0) - (vb ? 1 : 0);
    else r = String(va ?? '').localeCompare(String(vb ?? ''), 'pt', { numeric: true, sensitivity: 'base' });
    return desc ? -r : r;
  });
  return copia;
}

function _recCabecalhoOrd(colunas, ord) {
  return `<thead><tr>${colunas.map(c => {
    const ativa = ord.campo === c.campo;
    const seta = ativa ? (ord.desc ? ' ▾' : ' ▴') : '';
    return `<th data-rec-ord="${esc(c.campo)}" class="${ativa ? 'ord' : ''}"
      title="Ordenar por ${esc(c.rotulo)}">${esc(c.rotulo)}${seta}</th>`;
  }).join('')}</tr></thead>`;
}

let _recCamerasAchadas = null;
let _recOrdCam = { campo: 'ip', desc: false };

function recProtocoloPorFabricante(cam) {
  const proto = document.getElementById('recProto');
  if (!proto) return;
  const fab = String(cam.fabricante || '').toLowerCase();
  proto.value = fab.includes('hik') ? 'HIKVISION'
    : (fab.includes('intelbras') || fab.includes('dahua') || fab.includes('aebell') || fab.includes('itb'))
      ? 'Private' : 'Onvif';
}

async function recBuscarCameras(aoEscolher, marcaBusca) {
  // Quem varre a rede e o PROPRIO gravador: ele esta na LAN das cameras, nos
  // nao alcancamos. No NVD de Perucaba isso devolveu 261 cameras, das quais 32
  // ja estavam nos canais.
  const d = _deployRecorderXray;
  if (!d) return;
  const p = deployStandaloneRecorderPayload();

  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  const fechar = () => { tampa.innerHTML = ''; };

  // Mesma escolha da busca de gravador, e pela mesma razao: o ISAPI da
  // Hikvision devolve so parte da rede. Na TELHA foram 7 cameras onde a rede
  // tem 31. Trocar a marca refaz a busca por outro caminho.
  const marca = marcaBusca || 'auto';
  const MARCAS = [
    { id: 'intelbras', rotulo: 'Intelbras/Dahua' },
    { id: 'hikvision', rotulo: 'Hikvision' },
    { id: 'outros', rotulo: 'Outros' },
  ];
  const seletorCam = (atual) => `<div class="rec-marcas" role="group" aria-label="Marca da camera">
    <span class="rec-marcas-rot">Procurar</span>
    ${MARCAS.map(m => `<button type="button" class="rec-marca${m.id === atual ? ' on' : ''}"
      data-rec-marca="${m.id}" aria-pressed="${m.id === atual}">${esc(m.rotulo)}</button>`).join('')}
  </div>`;
  const ligarMarcasCam = (atual) => {
    tampa.querySelectorAll('[data-rec-marca]').forEach(b => b.addEventListener('click', () => {
      if (b.dataset.recMarca !== atual) recBuscarCameras(aoEscolher, b.dataset.recMarca);
    }));
  };

  const moldura = (miolo, rodape, sub) => `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="Buscar cameras">
    <div class="rec-caixa rec-caixa-larga">
      <div class="rec-caixa-cab">
        <h3>Cameras na rede</h3>
        <p>${esc(sub || `Quem procura e o gravador ${d.host}, que esta na mesma rede das cameras.`)}</p>
      </div>
      <div class="rec-caixa-corpo">${miolo}</div>
      <div class="rec-caixa-pe">${rodape}</div>
    </div></div>`;

  const ligarFechar = () => {
    tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  };

  tampa.innerHTML = moldura(
    `${seletorCam(marca === 'auto' ? '' : marca)}
     <p class="rec-vazio">${marca === 'intelbras' || marca === 'auto'
      ? 'Procurando na rede do gravador... leva alguns segundos.'
      : 'Perguntando endereco por endereco na rede do site... leva ate um minuto.'}</p>`,
    '<button class="acao" type="button" data-rec-fechar>Cancelar</button>');
  ligarFechar();
  ligarMarcasCam(marca);

  let dados;
  try {
    const res = await api('/api/deployments/recorder-buscar-cameras', {
      method: 'POST',
      body: JSON.stringify({
        recorder_host: d.host || p.recorder_host,
        recorder_http_port: p.recorder_http_port,
        connector_id: p.connector_id || '',
        marca,
      }),
    });
    dados = await res?.json().catch(() => ({}));
    if (!res?.ok || dados?.ok === false) throw new Error(dados?.detail || 'o gravador nao respondeu a busca');
  } catch (err) {
    tampa.innerHTML = moldura(
      `${seletorCam(marca === 'auto' ? '' : marca)}
       <p class="rec-vazio">${esc(err?.message || err)}</p>`,
      '<button class="acao" type="button" data-rec-fechar>Fechar</button>', 'Nao deu');
    ligarFechar();
    ligarMarcasCam(marca);
    return;
  }

  _recCamerasAchadas = Array.isArray(dados.cameras) ? dados.cameras : [];
  const novas = _recCamerasAchadas.filter(c => !c.no_gravador).length;

  const desenhar = (filtro, soNovas) => {
    const alvo = String(filtro || '').trim().toLowerCase();
    let vistas = _recCamerasAchadas.filter(c =>
      (!soNovas || !c.no_gravador)
      && (!alvo || [c.ip, c.modelo, c.fabricante, c.mac, c.serial]
        .some(v => String(v || '').toLowerCase().includes(alvo))));
    const lista = document.getElementById('recCamLista');
    if (!lista) return;
    vistas = _recOrdenar(vistas, _recOrdCam.campo, _recOrdCam.desc);
    const colunas = [
      { campo: 'ip', rotulo: 'IP' }, { campo: 'modelo', rotulo: 'Modelo' },
      { campo: 'fabricante', rotulo: 'Fabricante' },
      { campo: 'porta_add', rotulo: 'Porta' }, { campo: 'mac', rotulo: 'MAC' },
      { campo: 'no_gravador', rotulo: 'Estado' },
    ];
    lista.innerHTML = vistas.length
      ? `<table class="rec-tabela">${_recCabecalhoOrd(colunas, _recOrdCam)}<tbody>${vistas.map(c => `
          <tr data-rec-cam="${esc(c.ip)}">
            <td class="n">${esc(c.ip)}</td>
            <td><b>${esc(c.modelo || '-')}</b></td>
            <td>${esc(c.fabricante || '-')}</td>
            <td class="n" title="porta de gerencia, que o gravador usa para falar com a camera - a web da camera e ${esc(c.porta_http || '80')}">${esc(c.porta_add || c.porta_http || '-')}</td>
            <td class="n fraco">${esc(c.mac || '-')}</td>
            <td>${c.no_gravador ? '<em class="rec-tag">ja no gravador</em>'
              : (c.inicializada ? '<em class="rec-tag novo">livre</em>'
                                : '<em class="rec-tag alerta">sem senha</em>')}</td>
          </tr>`).join('')}</tbody></table>`
      : `<p class="rec-vazio">Nenhuma camera com "${esc(filtro)}".</p>`;
    lista.querySelectorAll('[data-rec-ord]').forEach(th => th.addEventListener('click', () => {
      const campo = th.dataset.recOrd;
      if (_recOrdCam.campo === campo) _recOrdCam.desc = !_recOrdCam.desc;
      else { _recOrdCam.campo = campo; _recOrdCam.desc = false; }
      desenhar(filtro, soNovas);
    }));
    lista.querySelectorAll('[data-rec-cam]').forEach(b => b.addEventListener('click', () => {
      const cam = _recCamerasAchadas.find(x => x.ip === b.dataset.recCam);
      if (!cam) return;
      fechar();
      if (typeof aoEscolher === 'function') { aoEscolher(cam); return; }
      recAbrirEdicao('adicionar', 0);
      const ip = document.getElementById('recIp');
      if (ip) ip.value = cam.ip;
      recProtocoloPorFabricante(cam);
    }));
  };

  // Qual caminho o servidor acabou usando -- com "auto" quem decide e ele.
  const usada = dados.origem === 'gravador' ? 'intelbras'
    : (dados.marca === 'hikvision' ? 'hikvision' : 'outros');
  const recados = [];
  if (dados.aviso) recados.push(`<p class="rec-recado">${esc(dados.aviso)}</p>`);
  if (dados.sem_senha) {
    recados.push(`<p class="rec-dica">${esc(dados.sem_senha)} equipamento(s) responderam mas recusaram esta senha.</p>`);
  }
  const sub = dados.origem === 'rede'
    ? `Procurei endereco por endereco na rede do site (${esc(dados.enderecos_testados || 0)} testados).`
    : `Quem procura e o gravador ${esc(d.host)}, que esta na mesma rede das cameras.`;

  tampa.innerHTML = moldura(`
    ${seletorCam(usada)}
    ${recados.join('')}
    <div class="rec-busca-linha">
      <input id="recCamBusca" class="rec-busca" placeholder="Buscar por IP, modelo, fabricante ou MAC" autocomplete="off">
      <label class="rec-check"><input type="checkbox" id="recCamSoNovas" checked> So as que faltam</label>
    </div>
    <p class="rec-dica">${esc(_recCamerasAchadas.length)} na rede - ${esc(novas)} fora do gravador</p>
    <div id="recCamLista" class="rec-lista rec-lista-alta"></div>`,
    '<button class="acao" type="button" data-rec-fechar>Fechar</button>', sub);

  const campo = document.getElementById('recCamBusca');
  const soNovas = document.getElementById('recCamSoNovas');
  const repintar = () => desenhar(campo && campo.value, !!(soNovas && soNovas.checked));
  if (campo) campo.addEventListener('input', repintar);
  if (soNovas) soNovas.addEventListener('change', repintar);
  ligarFechar();
  ligarMarcasCam(usada);
  repintar();
  if (campo) campo.focus();
}

async function recBuscarGravadores() {
  // Cadastrar um gravador exigia saber o IP de cor. Quem conhece os IPs da rede
  // do cliente ja esta nela -- mas o CAMINHO depende da marca, e por isso a
  // marca e escolhida aqui em vez de adivinhada:
  //
  //   Intelbras/Dahua  o proprio gravador varre e entrega modelo, serial,
  //                    canais e firmware de uma vez.
  //   Hikvision        nao lista gravador vizinho: o InputProxy/search so
  //                    devolve o que pode virar canal, ou seja camera. Medido
  //                    na TELHA: o DS-7632NXI devolveu as 7 cameras e NAO
  //                    devolveu o DS-7616NI do IP ao lado. Entao a busca passa
  //                    a ser pela tabela ARP do roteador do site.
  //   Outros           mesma varredura pela rede, testando os dois protocolos.
  const p = deployStandaloneRecorderPayload();
  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  const fechar = () => { tampa.innerHTML = ''; };
  const moldura = (miolo, rodape, sub) => `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="Buscar gravadores">
    <div class="rec-caixa rec-caixa-larga">
      <div class="rec-caixa-cab">
        <h3>Gravadores na rede</h3>
        <p>${esc(sub || 'Procurando...')}</p>
      </div>
      <div class="rec-caixa-corpo">${miolo}</div>
      <div class="rec-caixa-pe">${rodape}</div>
    </div></div>`;
  const ligarFechar = () => {
    tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  };

  const MARCAS = [
    { id: 'intelbras', rotulo: 'Intelbras/Dahua' },
    { id: 'hikvision', rotulo: 'Hikvision' },
    { id: 'outros', rotulo: 'Outros' },
  ];
  const seletor = (atual) => `<div class="rec-marcas" role="group" aria-label="Marca do gravador">
    <span class="rec-marcas-rot">Procurar</span>
    ${MARCAS.map(m => `<button type="button" class="rec-marca${m.id === atual ? ' on' : ''}"
      data-rec-marca="${m.id}" aria-pressed="${m.id === atual}">${esc(m.rotulo)}</button>`).join('')}
  </div>`;
  const ligarMarcas = (atual) => {
    tampa.querySelectorAll('[data-rec-marca]').forEach(b => b.addEventListener('click', () => {
      if (b.dataset.recMarca !== atual) rodar(b.dataset.recMarca);
    }));
  };

  const colunas = [
    { campo: 'ip', rotulo: 'IP' }, { campo: 'modelo', rotulo: 'Modelo' },
    { campo: 'fabricante', rotulo: 'Fabricante' },
    { campo: 'porta_http', rotulo: 'Porta' }, { campo: 'mac', rotulo: 'MAC' },
    { campo: 'cadastrado', rotulo: 'Estado' },
  ];

  async function rodar(marca) {
    tampa.innerHTML = moldura(
      `${seletor(marca === 'auto' ? '' : marca)}
       <p class="rec-vazio">${marca === 'intelbras' || marca === 'auto'
        ? 'Pedindo a varredura a um gravador deste conector... leva alguns segundos.'
        : 'Perguntando endereco por endereco na rede do site... leva ate um minuto.'}</p>`,
      '<button class="acao" type="button" data-rec-fechar>Cancelar</button>');
    ligarFechar();
    ligarMarcas(marca);

    let dados;
    try {
      const res = await api('/api/deployments/buscar-gravadores', {
        method: 'POST',
        body: JSON.stringify({ connector_id: p.connector_id || '', site: p.site || '', marca }),
      });
      dados = await res?.json().catch(() => ({}));
      if (!res?.ok || dados?.ok === false) throw new Error(dados?.detail || 'nao consegui varrer a rede');
    } catch (err) {
      tampa.innerHTML = moldura(
        `${seletor(marca === 'auto' ? '' : marca)}
         <p class="rec-vazio">${esc(err?.message || err)}</p>`,
        '<button class="acao" type="button" data-rec-fechar>Fechar</button>', 'Nao deu');
      ligarFechar();
      ligarMarcas(marca);
      return;
    }

    // Qual caminho o servidor acabou usando -- com "auto" quem decide e ele.
    const usada = dados.origem === 'gravador' ? 'intelbras'
      : (dados.marca === 'hikvision' ? 'hikvision' : 'outros');
    const lista = Array.isArray(dados.gravadores) ? dados.gravadores : [];
    const novos = lista.filter(g => !g.cadastrado && !g.ele_mesmo).length;
    const ord = { campo: 'ip', desc: false };

    const desenhar = (filtro, soNovos) => {
      const alvo = String(filtro || '').trim().toLowerCase();
      let vistos = lista.filter(g =>
        (!soNovos || (!g.cadastrado && !g.ele_mesmo))
        && (!alvo || [g.ip, g.modelo, g.fabricante, g.mac, g.serial]
          .some(v => String(v || '').toLowerCase().includes(alvo))));
      vistos = _recOrdenar(vistos, ord.campo, ord.desc);
      const el = document.getElementById('recGravLista');
      if (!el) return;
      el.innerHTML = vistos.length
        ? `<table class="rec-tabela">${_recCabecalhoOrd(colunas, ord)}<tbody>${vistos.map(g => `
            <tr data-rec-grav="${esc(g.ip)}">
              <td class="n">${esc(g.ip)}</td>
              <td><b>${esc(g.modelo || '-')}</b></td>
              <td>${esc(g.fabricante || '-')}</td>
              <td class="n" title="HTTP ${esc(g.porta_http || '')} - midia ${esc(g.porta || '')}">${esc(g.porta_http || '-')}</td>
              <td class="n fraco">${esc(g.mac || '-')}</td>
              <td>${g.ele_mesmo ? '<em class="rec-tag">quem varreu</em>'
                : (g.cadastrado ? '<em class="rec-tag">ja cadastrado</em>'
                                : '<em class="rec-tag novo">novo</em>')}</td>
            </tr>`).join('')}</tbody></table>`
        : `<p class="rec-vazio">Nenhum gravador${alvo ? ` com "${esc(filtro)}"` : ' nesta busca'}.</p>`;
      el.querySelectorAll('[data-rec-ord]').forEach(th => th.addEventListener('click', () => {
        const campo = th.dataset.recOrd;
        // Mesma coluna inverte; coluna nova comeca crescente.
        if (ord.campo === campo) ord.desc = !ord.desc;
        else { ord.campo = campo; ord.desc = false; }
        desenhar(filtro, soNovos);
      }));
      el.querySelectorAll('[data-rec-grav]').forEach(b => b.addEventListener('click', () => {
        const g = lista.find(x => x.ip === b.dataset.recGrav);
        if (!g) return;
        fechar();
        const host = document.getElementById('deployStandaloneRecorderHost');
        const porta = document.getElementById('deployStandaloneRecorderPort');
        const nome = document.getElementById('deployStandaloneRecorderName');
        if (host) host.value = g.ip;
        if (porta && g.porta_http) porta.value = g.porta_http;
        if (nome && !nome.value && g.modelo) nome.value = g.modelo;
        const senha = document.getElementById('deployStandaloneRecorderPassword');
        if (senha) senha.focus();
        showToast(`${g.ip} - ${g.modelo || 'gravador'}. Informe a senha e valide.`);
      }));
    };

    // O aviso do servidor era engolido: a tela mostrava "0 na rede" e deixava o
    // usuario achando que nao existe gravador nenhum.
    const recados = [];
    if (dados.aviso) recados.push(`<p class="rec-recado">${esc(dados.aviso)}</p>`);
    if (dados.sem_senha) {
      recados.push(`<p class="rec-dica">${esc(dados.sem_senha)} equipamento(s) responderam mas recusaram esta senha -- `
        + 'se o gravador que voce procura esta entre eles, cadastre pelo IP.</p>');
    }

    const sub = dados.origem === 'rede'
      ? `Procurei endereco por endereco na rede do site (${esc(dados.enderecos_testados || 0)} testados).`
      : `Quem procurou foi o gravador ${esc(dados.varrido_por || '')}, que esta na mesma rede.`;

    tampa.innerHTML = moldura(`
      ${seletor(usada)}
      ${recados.join('')}
      <div class="rec-busca-linha">
        <input id="recGravBusca" class="rec-busca" placeholder="Buscar por IP, modelo, fabricante ou MAC" autocomplete="off">
        <label class="rec-check"><input type="checkbox" id="recGravSoNovos" checked> So os que faltam</label>
      </div>
      <p class="rec-dica">${esc(lista.length)} na rede - ${esc(novos)} fora do inventario</p>
      <div id="recGravLista" class="rec-lista rec-lista-alta"></div>`,
      '<button class="acao" type="button" data-rec-fechar>Fechar</button>', sub);

    const campo = document.getElementById('recGravBusca');
    const soNovos = document.getElementById('recGravSoNovos');
    const repintar = () => desenhar(campo && campo.value, !!(soNovos && soNovos.checked));
    if (campo) campo.addEventListener('input', repintar);
    if (soNovos) soNovos.addEventListener('change', repintar);
    ligarFechar();
    ligarMarcas(usada);
    repintar();
    if (campo) campo.focus();
  }

  await rodar('auto');
}
function recAbrirEdicao(acao, canal) {
  const d = _deployRecorderXray;
  if (!d) return;
  const c = (d.canais || []).find(x => Number(x.canal) === Number(canal)) || { canal };
  const livres = (d.canais || []).filter(x => !x.ip).map(x => x.canal);
  const titulos = { adicionar: 'Adicionar camera', editar: 'Editar camera', excluir: 'Soltar canal' };
  const ehExcluir = acao === 'excluir';

  const corpo = ehExcluir
    ? `<p style="margin:0 0 10px;font-size:13px">Canal <b>${esc(String(canal).padStart(2, '0'))}</b>${c.nome ? ' · ' + esc(c.nome) : ''}${c.ip ? ' · ' + esc(c.ip) : ''}</p>
       <div class="rec-perigo">A camera sai do canal na hora e o canal para de gravar. O equipamento nao pergunta de novo.</div>`
    : `<div class="rec-form">
        ${acao === 'adicionar' && !canal ? `<label>Canal
          <select id="recCanal">${livres.map(n => `<option value="${n}">Canal ${String(n).padStart(2, '0')}</option>`).join('')}</select></label>`
          : `<input type="hidden" id="recCanal" value="${esc(canal)}">`}
        <label>Nome do canal<input id="recNome" value="${esc(c.nome || '')}" placeholder="Ex: PORTARIA"></label>
        <label>IP da camera
          <span class="rec-com-botao">
            <input id="recIp" value="${esc(c.ip || '')}" placeholder="10.10.9.40">
            <button class="acao" type="button" data-rec-escolher-cam>Buscar</button>
          </span></label>
        <label>Usuario<input id="recUser" value="admin"></label>
        <label>Senha<input id="recSenha" type="password" placeholder="senha da camera"></label>
        <label>Protocolo<select id="recProto">
          <option value="">Automatico</option>
          <option value="Private">Private (Intelbras/Dahua)</option>
          <option value="Onvif">ONVIF (outras marcas)</option>
          <option value="HIKVISION">Hikvision</option>
        </select></label>
      </div>`;

  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  tampa.innerHTML = `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="${esc(titulos[acao])}">
    <div class="rec-caixa">
      <div class="rec-caixa-cab"><h3>${esc(titulos[acao])}</h3>
        <p>${esc(d.marca)} · ${esc(d.host)} · canal ${esc(String(canal || '').padStart(2, '0') || 'livre')}</p></div>
      <div class="rec-caixa-corpo">${corpo}
        <div id="recResultado" class="rec-resultado" hidden></div>
      </div>
      <div class="rec-caixa-pe">
        <button class="acao" type="button" data-rec-fechar>Cancelar</button>
        <button class="acao ${ehExcluir ? 'perigo' : 'forte'}" type="button" data-rec-aplicar>
          ${ehExcluir ? 'Soltar canal' : 'Aplicar no gravador'}</button>
      </div>
    </div></div>`;

  const fechar = () => { tampa.innerHTML = ''; };
  tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) fechar();
  });
  // Buscar de dentro do formulario: escolher na lista preenche IP e protocolo
  // e volta para ca sem perder o que ja foi digitado.
  tampa.querySelector('[data-rec-escolher-cam]')?.addEventListener('click', () => {
    const estado = {
      nome: document.getElementById('recNome')?.value || '',
      user: document.getElementById('recUser')?.value || 'admin',
      canal: document.getElementById('recCanal')?.value || canal,
    };
    recBuscarCameras(cam => {
      recAbrirEdicao(acao, Number(estado.canal) || canal);
      const ip = document.getElementById('recIp');
      const nome = document.getElementById('recNome');
      const user = document.getElementById('recUser');
      if (ip) ip.value = cam.ip || '';
      if (nome && estado.nome) nome.value = estado.nome;
      if (user) user.value = estado.user;
      recProtocoloPorFabricante(cam);
    });
  });
  tampa.querySelector('[data-rec-aplicar]').addEventListener('click', async ev => {
    const botao = ev.currentTarget;
    const caixa = document.getElementById('recResultado');
    botao.disabled = true;
    botao.textContent = 'Enviando...';
    const p = deployStandaloneRecorderPayload();
    const corpoReq = {
      acao,
      recorder_host: p.recorder_host, recorder_user: p.recorder_user,
      recorder_password: p.recorder_password, recorder_http_port: p.recorder_http_port,
      connector_id: p.connector_id || '', site: p.site || '',
      canal: Number(document.getElementById('recCanal')?.value || canal),
      nome: document.getElementById('recNome')?.value || '',
      camera_ip: document.getElementById('recIp')?.value || '',
      camera_user: document.getElementById('recUser')?.value || 'admin',
      camera_password: document.getElementById('recSenha')?.value || '',
      protocolo: document.getElementById('recProto')?.value || '',
    };
    try {
      const res = await api('/api/deployments/recorder-edit', {
        method: 'POST', body: JSON.stringify(corpoReq),
      });
      const data = await res?.json().catch(() => ({}));
      if (!res?.ok || data?.ok === false) {
        caixa.hidden = false;
        caixa.className = 'rec-resultado erro';
        caixa.textContent = data?.detail || data?.error || 'o gravador recusou';
        botao.disabled = false;
        botao.textContent = ehExcluir ? 'Soltar canal' : 'Aplicar no gravador';
        return;
      }
      caixa.hidden = false;
      caixa.className = 'rec-resultado ok';
      caixa.textContent = `Feito no gravador (${data.comando}). Relendo...`;
      showToast('Gravador atualizado.');
      setTimeout(() => { fechar(); deployRecorderCarregarXray(); }, 900);
    } catch (e) {
      caixa.hidden = false;
      caixa.className = 'rec-resultado erro';
      caixa.textContent = String(e?.message || e);
      botao.disabled = false;
      botao.textContent = ehExcluir ? 'Soltar canal' : 'Aplicar no gravador';
    }
  });
}

// ---- seletor de gravador: busca em vez de lista de cartoes ----
// Cartao empilhado nao escala: ha clientes com 41 e 64 gravadores, e a lista
// empurrava a tela inteira para baixo. Aqui e uma caixa com busca, que funciona
// igual com 1 ou com 100.
function recAbrirSeletor() {
  const itens = (_deployStandaloneRecorderSavedItems || []);
  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();

  const desenhar = (filtro = '') => {
    const alvo = filtro.trim().toLowerCase();
    const vistos = itens.filter(x => !alvo ||
      [x.name, x.host, x.site].some(v => String(v || '').toLowerCase().includes(alvo)));
    const porSite = new Map();
    vistos.forEach(x => {
      const site = x.site || 'Sem site';
      if (!porSite.has(site)) porSite.set(site, []);
      porSite.get(site).push(x);
    });
    const lista = document.getElementById('recSeletorLista');
    if (!lista) return;
    lista.innerHTML = vistos.length
      ? [...porSite.entries()].map(([site, linhas]) => `
          <div class="rec-grupo">${esc(site)}</div>
          ${linhas.map(x => `<button class="rec-item" type="button" data-rec-escolher="${esc(x.key)}">
            <b>${esc(x.name || x.host)}</b>
            <span>${esc(x.host)}${x.totalChannels ? ' · ' + esc(x.usedChannels) + '/' + esc(x.totalChannels) + ' canais' : ''}</span>
          </button>`).join('')}`).join('')
      : `<p class="rec-vazio">Nenhum gravador com "${esc(filtro)}".</p>`;
    // Gravador ja cadastrado entra DIRETO: conector, OLT, porta e senha estao no
    // cadastro. Abrir o formulario aqui era pedir de novo o que ja se sabe.
    lista.querySelectorAll('[data-rec-escolher]').forEach(b => b.addEventListener('click', () => {
      tampa.innerHTML = '';
      deployStandaloneRecorderUseSaved(b.dataset.recEscolher);
    }));
  };

  tampa.innerHTML = `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="Escolher gravador">
    <div class="rec-caixa">
      <div class="rec-caixa-cab">
        <h3>Escolher gravador</h3>
        <p>${itens.length} cadastrado${itens.length === 1 ? '' : 's'}</p>
      </div>
      <div class="rec-caixa-corpo">
        <input id="recSeletorBusca" class="rec-busca" placeholder="Buscar por nome, IP ou site" autocomplete="off">
        <div id="recSeletorLista" class="rec-lista"></div>
      </div>
      <div class="rec-caixa-pe">
        <button class="acao" type="button" data-rec-fechar>Cancelar</button>
        <button class="acao" type="button" data-rec-novo>Gravador nao cadastrado</button>
      </div>
    </div></div>`;
  desenhar();
  const busca = document.getElementById('recSeletorBusca');
  busca?.addEventListener('input', () => desenhar(busca.value));
  busca?.focus();
  tampa.querySelectorAll('[data-rec-fechar]').forEach(b =>
    b.addEventListener('click', () => { tampa.innerHTML = ''; }));
  tampa.querySelector('[data-rec-novo]')?.addEventListener('click', () => {
    tampa.innerHTML = '';
    openDeployStandaloneRecorderModal('entry');
  });
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) tampa.innerHTML = '';
  });
}

function recPedirSenha(item) {
  // Ultimo caso: o gravador esta cadastrado, mas ninguem nunca salvou a senha
  // dele. Pergunta so usuario e senha -- conector, OLT, host e porta ja vieram
  // do cadastro. Depois do login o servidor guarda, e esta tela some pra sempre
  // neste gravador.
  const tampa = document.getElementById('recTampa') || (() => {
    const el = document.createElement('div');
    el.id = 'recTampa';
    document.body.appendChild(el);
    return el;
  })();
  const fechar = () => { tampa.innerHTML = ''; };

  tampa.innerHTML = `<div class="rec-tampa" role="dialog" aria-modal="true" aria-label="Senha do gravador">
    <div class="rec-caixa rec-caixa-estreita">
      <div class="rec-caixa-cab">
        <h3>Senha de ${esc(item.name || item.host)}</h3>
        <p>${esc(item.host)} · a senha fica guardada; so e pedida desta vez.</p>
      </div>
      <div class="rec-caixa-corpo">
        <label class="rec-campo"><span>Usuario</span>
          <input id="recSenhaUser" autocomplete="off" value="${esc(item.user || 'admin')}"></label>
        <label class="rec-campo"><span>Senha</span>
          <input id="recSenhaPass" type="password" autocomplete="new-password"></label>
        <p class="rec-erro" id="recSenhaErro" hidden></p>
      </div>
      <div class="rec-caixa-pe">
        <button class="acao" type="button" data-rec-fechar>Cancelar</button>
        <button class="acao forte" type="button" data-rec-ok>Entrar</button>
      </div>
    </div></div>`;

  const campoUser = document.getElementById('recSenhaUser');
  const campoPass = document.getElementById('recSenhaPass');
  const erro = document.getElementById('recSenhaErro');
  campoPass?.focus();

  const entrar = () => {
    const senha = campoPass?.value || '';
    if (!senha) {
      if (erro) { erro.hidden = false; erro.textContent = 'Informe a senha do gravador.'; }
      campoPass?.focus();
      return;
    }
    const u = document.getElementById('deployStandaloneRecorderUser');
    const p = document.getElementById('deployStandaloneRecorderPassword');
    if (u) u.value = (campoUser?.value || 'admin').trim() || 'admin';
    if (p) p.value = senha;
    fechar();
    deployStandaloneRecorderSetResult(`Entrando em ${esc(item.host)}...`);
    deployStandaloneRecorderLogin();
  };

  tampa.querySelector('[data-rec-ok]')?.addEventListener('click', entrar);
  tampa.querySelectorAll('[data-rec-fechar]').forEach(b => b.addEventListener('click', fechar));
  campoPass?.addEventListener('keydown', ev => { if (ev.key === 'Enter') entrar(); });
  tampa.querySelector('.rec-tampa').addEventListener('click', ev => {
    if (ev.target === ev.currentTarget) fechar();
  });
}


// ─────────────────────────────────────────────────────────────────────────
// Ler a etiqueta da camera (codigo de barras / QR)
//
// Digitar MAC a mao no poste, de luva, e onde nasce erro de cadastro: um
// digito trocado e a camera entra no inventario com identidade de outra.
// A etiqueta ja traz o dado; so faltava deixar a camera do celular le-la.
//
// Prefere o BarcodeDetector NATIVO: e o que existe no Chrome do Android, que
// e onde o tecnico esta, e nao baixa nada. So cai para a biblioteca quando o
// navegador nao tem -- e ai carrega sob demanda, no clique, para nao pesar o
// carregamento de quem nunca vai usar.
// ─────────────────────────────────────────────────────────────────────────

let _scanParar = null;

function deployFecharScanner() {
  try { _scanParar?.(); } catch {}
  _scanParar = null;
  document.getElementById('scanTampa')?.remove();
}

function _macDoTexto(texto) {
  // A etiqueta pode trazer so o MAC, ou um QR com varios campos
  // (SN=..., MAC=..., P/N=...). Vale o primeiro que PARECE MAC; se nao
  // houver nenhum, devolve o texto cru para a busca tentar por serial.
  const t = String(texto || '').trim();
  const comSeparador = t.match(/\b([0-9A-Fa-f]{2}([:-])(?:[0-9A-Fa-f]{2}\2){4}[0-9A-Fa-f]{2})\b/);
  if (comSeparador) return comSeparador[1].toUpperCase().replace(/-/g, ':');
  const cru = t.match(/\b([0-9A-Fa-f]{12})\b/);
  if (cru) return cru[1].toUpperCase().match(/../g).join(':');
  return t;
}

async function _lerComBiblioteca(video, aoLer) {
  // ZXing pelo unpkg -- a mesma origem de onde o app ja traz Leaflet e Lucide.
  if (!window.ZXing) {
    await new Promise((ok, erro) => {
      const tag = document.createElement('script');
      tag.src = 'https://unpkg.com/@zxing/library@0.21.3/umd/index.min.js';
      tag.onload = ok;
      tag.onerror = () => erro(new Error('nao consegui carregar o leitor'));
      document.head.appendChild(tag);
    });
  }
  const leitor = new window.ZXing.BrowserMultiFormatReader();
  await leitor.decodeFromVideoElement(video, (resultado) => {
    if (resultado) aoLer(resultado.getText());
  });
  return () => { try { leitor.reset(); } catch {} };
}

async function deployAbrirScanner() {
  if (!navigator.mediaDevices?.getUserMedia) {
    showToast('Este navegador nao da acesso a camera. Digite o MAC a mao.', true);
    return;
  }
  deployFecharScanner();

  const tampa = document.createElement('div');
  tampa.id = 'scanTampa';
  tampa.innerHTML = `
    <div class="scan-topo">
      <div><b>Ler etiqueta da camera</b><p>Aponte para o codigo de barras ou QR</p></div>
      <button type="button" class="scan-fechar" data-scan-fechar>Cancelar</button>
    </div>
    <video playsinline muted autoplay></video>
    <div class="scan-mira"></div>
    <div class="scan-pe" id="scanRecado">Procurando a camera do aparelho...</div>`;
  document.body.appendChild(tampa);
  tampa.querySelector('[data-scan-fechar]')?.addEventListener('click', deployFecharScanner);

  const video = tampa.querySelector('video');
  const recado = tampa.querySelector('#scanRecado');
  let stream = null;

  const aoLer = (texto) => {
    if (!texto) return;
    const mac = _macDoTexto(texto);
    const campo = document.getElementById('deployCameraMac');
    if (campo) campo.value = mac;
    deployFecharScanner();
    showToast(`Etiqueta lida: ${mac}`);
    // Ler so serve se buscar em seguida -- e o que o tecnico faria agora.
    deployLookupMac();
  };

  try {
    // `environment` = camera de tras. Sem isso o celular abre a frontal e o
    // tecnico fica se filmando em vez de ler a etiqueta.
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: 'environment' } }, audio: false,
    });
    video.srcObject = stream;
    await video.play().catch(() => {});
  } catch (e) {
    deployFecharScanner();
    showToast('Nao consegui abrir a camera do aparelho. Permita o acesso ou digite o MAC.', true);
    return;
  }

  const pararCamera = () => { try { stream?.getTracks().forEach(t => t.stop()); } catch {} };

  const Detector = window.BarcodeDetector;
  if (Detector) {
    let formatos = ['qr_code', 'code_128', 'code_39', 'ean_13', 'data_matrix'];
    try {
      const aceitos = await Detector.getSupportedFormats();
      formatos = formatos.filter(f => aceitos.includes(f));
    } catch {}
    const detector = new Detector(formatos.length ? { formats: formatos } : undefined);
    if (recado) recado.textContent = 'Aponte o codigo dentro da moldura.';
    let vivo = true;
    const laco = async () => {
      if (!vivo || !document.getElementById('scanTampa')) return;
      try {
        const achados = await detector.detect(video);
        if (achados && achados.length) { aoLer(achados[0].rawValue); return; }
      } catch {}
      requestAnimationFrame(laco);
    };
    _scanParar = () => { vivo = false; pararCamera(); };
    requestAnimationFrame(laco);
    return;
  }

  if (recado) recado.textContent = 'Carregando o leitor...';
  try {
    const parar = await _lerComBiblioteca(video, aoLer);
    _scanParar = () => { parar(); pararCamera(); };
    if (recado) recado.textContent = 'Aponte o codigo dentro da moldura.';
  } catch (e) {
    _scanParar = pararCamera;
    deployFecharScanner();
    showToast('Nao consegui carregar o leitor de codigo. Digite o MAC a mao.', true);
  }
}


// ─────────────────────────────────────────────────────────────────────────
// Acesso da camera em modal
//
// Usuario e senha ficavam ocupando uma linha da etapa o tempo todo, mesmo
// antes de existir uma camera escolhida -- e o tecnico ainda tinha que
// descobrir sozinho que o "Entrar" ali embaixo dependia da escolha la em
// cima. Pedir credencial no momento em que ela e usada deixa a etapa com
// menos campos e torna a ordem obvia: escolhe a camera, clica Entrar,
// informa o acesso.
//
// Os campos vivem no modal mas NAO sao recriados a cada abertura: o titulo
// gravado na camera e a troca de IP releem a senha depois, e um modal
// destruido levaria a senha junto.
// ─────────────────────────────────────────────────────────────────────────

function deployAbrirLoginCamera() {
  if (!deployEnsureStepUnlocked('cftvStep2', 'Escolha o site na barra de cima antes de entrar na camera.')) return;
  const ip = _deployPullTargetIp || document.getElementById('deployCameraIp')?.value.trim() || '';
  if (!ip) {
    showToast('Escolha a camera na lista (ou informe o IP) antes de entrar.', true);
    return;
  }
  const alvo = document.getElementById('deployLoginAlvo');
  if (alvo) alvo.textContent = `Acesso da camera em ${ip}.`;
  deploySetLoginModalResult('A senha so sai daqui para a propria camera -- nao fica salva na tela.');
  document.getElementById('modalDeployCameraLogin')?.classList.remove('hidden');
  const senha = document.getElementById('deployCameraPassword');
  senha?.focus();
  senha?.select();
}

function deployFecharLoginCamera() {
  document.getElementById('modalDeployCameraLogin')?.classList.add('hidden');
}

function deploySetLoginModalResult(html, erro = false) {
  const box = document.getElementById('deployLoginModalResult');
  if (!box) return;
  box.innerHTML = html;
  box.classList.toggle('error', !!erro);
}

async function deployEntrarNaCamera() {
  const user = document.getElementById('deployCameraUser')?.value.trim() || '';
  const pass = document.getElementById('deployCameraPassword')?.value || '';
  if (!user || !pass) {
    deploySetLoginModalResult('Informe usuario e senha da camera.', true);
    return;
  }
  deploySetLoginModalResult('Conectando na camera...');
  await deployPullCameraInfo();
  // Quem sabe se deu certo e a propria caixa de resultado da etapa: ela ja
  // recebe `.error` na falha. Repetir a decisao aqui criaria duas verdades.
  const caixa = document.getElementById('deployPullCameraResult');
  if (caixa && caixa.classList.contains('error')) {
    deploySetLoginModalResult(caixa.innerHTML, true);
    return;
  }
  deployFecharLoginCamera();
}
