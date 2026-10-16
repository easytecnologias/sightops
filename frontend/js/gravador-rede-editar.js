// Gravador aberto > Rede > "Editar rede", "Reiniciar gravador" e o rodape
// "Correcoes de rede". Registrado no esqueleto (gravador-rede.js); as abas de
// leitura moram em gravador-rede-leitura.js (outra sessao).
//
// Trocar IP/porta de um gravador em producao e a unica mudanca sem volta pelo
// SightOps. O servidor (app/services/recorder_rede.py) confere de novo, exige
// o IP novo digitado, grava, procura o gravador no endereco novo pelo conector
// e so entao atualiza inventario, porta e senha salva. Esta tela so mostra.

let _re = null;   // {chave, carregando, erro, atual, novo, checks, mud, etapa, confirma, job, reinicio}

function reEstado() {
  const chave = recChave();
  if (!_re || _re.chave !== chave) {
    _re = { chave, carregando: false, erro: '', atual: null, novo: {}, checks: [], mud: [], etapa: 1,
      confirma: '', job: null, conferindo: false, reinicio: null, confirmaReinicio: '' };
  }
  return _re;
}

const RE_CAMPOS_IP = [['ip', 'IP'], ['mascara', 'Máscara'], ['gateway', 'Gateway'], ['dns1', 'DNS 1'], ['dns2', 'DNS 2']];
const RE_CAMPOS_PORTA = [['http', 'Web (HTTP)'], ['rtsp', 'Vídeo (RTSP)'], ['tcp', 'SDK (TCP)'], ['https', 'HTTPS']];

async function reCarregar() {
  const e = reEstado();
  if (e.carregando) return;
  e.carregando = true; e.erro = '';
  const alvo = recAvAlvo();
  try {
    const res = await api(`/api/nvr/driver/rede?${new URLSearchParams({ host: alvo.host, http_port: alvo.http_port, connector_id: alvo.connector_id })}`);
    const j = await res.json().catch(() => ({}));
    if (_re !== e) return;
    if (!res.ok) e.erro = j.detail === 'SEM_CREDENCIAL' ? 'Sem senha salva deste gravador.' : (j.detail || `HTTP ${res.status}`);
    else {
      e.atual = j.rede; e.info = j;
      e.novo = Object.fromEntries([...RE_CAMPOS_IP, ...RE_CAMPOS_PORTA].map(([k]) => [k, String(j.rede[k] || '')]));
    }
  } catch (err) { if (_re === e) e.erro = err.message; }
  if (_re === e) e.carregando = false;
  if (_recSec === 'rede') recPintarApp();
}

let _reTimer = null;
function reConferirDepois() {
  clearTimeout(_reTimer);
  _reTimer = setTimeout(reConferir, 450);
}

async function reConferir() {
  const e = _re;
  if (!e?.atual) return;
  e.conferindo = true;
  reAtualizarConferencias();
  try {
    const res = await api('/api/nvr/driver/rede/conferir', { method: 'POST', body: JSON.stringify({ ...recAvAlvo(), novo: e.novo }) });
    const j = await res.json().catch(() => ({}));
    if (_re !== e) return;
    if (res.ok) { e.checks = j.conferencias || []; e.mud = j.mudancas || []; e.atual = j.atual || e.atual; }
    else { e.checks = [{ ok: false, grave: true, titulo: 'Não consegui conferir', texto: j.detail || `HTTP ${res.status}` }]; e.mud = []; }
  } catch (err) { if (_re === e) e.checks = [{ ok: false, grave: true, titulo: 'Não consegui conferir', texto: err.message }]; }
  if (_re !== e) return;
  e.conferindo = false;
  reAtualizarConferencias();
}

function reBloqueado(e) {
  return e.conferindo || !e.mud.length || e.checks.some(c => c.grave);
}

// Atualiza so a lista de conferencias e o botao: redesenhar a tela inteira
// tiraria o foco do campo que a pessoa esta digitando.
function reAtualizarConferencias() {
  const e = _re, box = document.getElementById('reChecks'), bt = document.querySelector('[data-re-revisar]');
  if (box) box.innerHTML = reHtmlChecks(e);
  if (bt) bt.disabled = reBloqueado(e);
  document.querySelectorAll('[data-re-campo]').forEach(i => {
    const k = i.dataset.reCampo;
    i.classList.toggle('mudou', String(e.novo[k] || '') !== String(e.atual?.[k] || ''));
  });
}

function reHtmlChecks(e) {
  if (e.conferindo) return '<div class="re-check espera">Conferindo…</div>';
  if (!e.checks.length) return '<div class="re-check espera">Altere um campo para o SightOps conferir.</div>';
  return e.checks.map(c => `<div class="re-check ${c.ok ? 'ok' : (c.grave ? 'grave' : 'aviso')}">
    <b>${c.ok ? '✓' : (c.grave ? '✕' : '!')}</b><span><b>${esc(c.titulo)}</b> — ${esc(c.texto)}</span></div>`).join('');
}

function reCampo(e, k, rot, numerico) {
  const mudou = String(e.novo[k] || '') !== String(e.atual?.[k] || '');
  return `<label class="re-campo">${esc(rot)}
    <input type="text" ${numerico ? 'inputmode="numeric"' : ''} data-re-campo="${k}" value="${esc(e.novo[k] || '')}" class="${mudou ? 'mudou' : ''}" autocomplete="off">
  </label>`;
}

function reSecEditar(d) {
  const e = reEstado();
  if (!e.atual && !e.carregando && !e.erro) setTimeout(reCarregar, 0);
  // O raio-x devolve "Intelbras" (maiusculo); o driver, "intelbras".
  const marca = String(e.info?.marca || d.marca || '').toLowerCase();
  if (marca && !marca.includes('intelbras')) {
    return `<div class="bloco"><div class="bloco-cab"><div><h2>Editar rede</h2>
      <p>Trocar a rede pelo SightOps ainda só em Intelbras (em ${esc(d.marca)} a escrita não foi provada em equipamento).</p></div></div></div>`;
  }
  if (e.carregando || (!e.atual && !e.erro)) return '<div class="bloco"><p class="rec-muted" style="padding:14px 16px">Lendo a rede do gravador…</p></div>';
  if (e.erro) return `<div class="bloco"><p class="rec-muted" style="padding:14px 16px">Não consegui ler a rede: ${esc(e.erro)}</p></div>`;

  const etapas = ['Editar', 'Revisar e confirmar', 'Aplicando'].map((r, i) =>
    `<span class="re-etapa ${e.etapa === i + 1 ? 'on' : (e.etapa > i + 1 ? 'feita' : '')}"><b>${i + 1}</b> ${r}</span>`).join('');
  let corpo = '';
  if (e.etapa === 1) {
    corpo = `<div class="re-grade">
        <fieldset class="re-grupo"><legend>Endereço</legend>${RE_CAMPOS_IP.map(([k, r]) => reCampo(e, k, r)).join('')}
          ${e.atual.dhcp ? '<p class="re-nota aviso">O gravador está em DHCP: o IP pode mudar sozinho e o SightOps perder o gravador. Salvar aqui fixa o endereço.</p>' : ''}
        </fieldset>
        <fieldset class="re-grupo"><legend>Portas</legend>${RE_CAMPOS_PORTA.map(([k, r]) => reCampo(e, k, r, true)).join('')}
          <p class="re-nota">Trocar porta atualiza também o que o SightOps guarda deste gravador (inventário, senha salva e ao vivo).</p>
        </fieldset>
      </div>
      <div class="re-conf"><b>Conferido antes de deixar seguir</b><div id="reChecks">${reHtmlChecks(e)}</div></div>
      <div class="re-botoes"><button type="button" class="acao" data-re-desfazer-edicao>Desfazer edição</button>
        <button type="button" class="acao forte" data-re-revisar ${reBloqueado(e) ? 'disabled' : ''}>Revisar a mudança</button></div>`;
  } else if (e.etapa === 2) {
    const ipNovo = e.novo.ip || e.atual.ip;
    corpo = `<b>O que vai mudar no gravador</b>
      ${e.mud.map(m => `<div class="av-mud"><span>${esc(m.o)}</span><span class="de">${esc(m.de || '(vazio)')}</span><span class="para">→ ${esc(m.para || '(vazio)')}</span></div>`).join('')}
      <div class="re-como"><b>Como o SightOps faz, para não perder o gravador</b>
        <span>1. Guarda a configuração de rede atual.</span>
        <span>2. Grava a mudança. O gravador pode sumir por uns segundos.</span>
        <span>3. Procura o gravador no endereço novo, pelo mesmo conector, por até 2 min.</span>
        <span>4. Achou: atualiza inventário, porta e senha salva. Não achou: tenta o endereço antigo e avisa na hora.</span></div>
      <label class="re-campo largo">Para confirmar, digite o IP ${ipNovo === e.atual.ip ? 'do gravador' : 'novo'} (${esc(ipNovo)})
        <input type="text" data-re-confirma value="${esc(e.confirma)}" autocomplete="off" placeholder="${esc(ipNovo)}"></label>
      <div class="re-botoes"><button type="button" class="acao" data-re-voltar>Voltar</button>
        <button type="button" class="acao perigo" data-re-aplicar ${e.confirma.trim() === ipNovo ? '' : 'disabled'}>Aplicar no gravador</button></div>`;
  } else {
    const j = e.job || {};
    const fim = { pronto: ['ok', `Gravador respondendo em ${j.host}:${j.http_port}. Inventário, ao vivo e Investigação já usam o endereço novo.`],
      parcial: ['aviso', `O gravador voltou em ${j.host}:${j.http_port}, mas não pegou: ${(j.nao_pegaram || []).join(', ')}.`],
      nao_aplicou: ['aviso', j.erro], perdido: ['grave', j.erro], erro: ['grave', j.erro] }[j.estado];
    corpo = `<div class="re-passos">${(j.passos || []).map(p => `<div><b>✓</b><span>${esc(p.t)}</span><span class="n">${esc(p.s || '')}</span></div>`).join('')}
        ${j.estado === 'rodando' ? '<div class="espera"><b>…</b><span>Esperando o gravador responder no endereço novo</span></div>' : ''}</div>
      ${fim ? `<div class="re-check ${fim[0]}"><span>${esc(fim[1] || '')}</span></div>` : ''}
      <div class="re-botoes">${j.estado === 'pronto' || j.estado === 'parcial'
        ? '<button type="button" class="acao forte" data-re-reabrir>Abrir o gravador no endereço novo</button>'
        : (j.estado === 'rodando' ? '' : '<button type="button" class="acao" data-re-recomecar>Voltar para a edição</button>')}</div>`;
  }

  const r = e.reinicio;
  const reinicio = r?.job
    ? `<div class="re-check ${r.job.estado === 'pronto' ? 'ok' : (r.job.estado === 'rodando' ? 'espera' : 'grave')}"><span>${
        r.job.estado === 'pronto' ? 'Gravador reiniciado e de volta.' : (r.job.estado === 'rodando' ? 'Reiniciando… o gravador some por 1 a 3 min.' : esc(r.job.erro || 'não voltou'))}</span></div>`
    : `<div class="re-reiniciar">
        <span>Reiniciar desliga a gravação de todos os canais por 1 a 3 minutos.</span>
        <label class="re-campo">Digite REINICIAR<input type="text" data-re-confirma-reinicio value="${esc(e.confirmaReinicio)}" autocomplete="off"></label>
        <button type="button" class="acao perigo" data-re-reiniciar ${e.confirmaReinicio.trim().toLowerCase() === 'reiniciar' ? '' : 'disabled'}>Reiniciar gravador</button></div>`;

  return `<div class="bloco re">
    <div class="bloco-cab"><div><h2>Editar rede</h2>
      <p>Hoje: ${esc(e.atual.ip)} / ${esc(e.atual.mascara)} · gw ${esc(e.atual.gateway)} · porta ${esc(e.atual.http)}${e.info?.conector ? ' · pelo conector' : ''}</p></div>
      <div class="bloco-dir"><div class="re-etapas">${etapas}</div></div></div>
    <div class="re-corpo">${corpo}</div>
  </div>
  <div class="bloco re"><div class="bloco-cab"><div><h2>Reiniciar gravador</h2><p>Para gravador travado. O SightOps espera ele voltar e avisa.</p></div></div>
    <div class="re-corpo">${reinicio}</div></div>`;
}

async function reAcompanhar(job, aoMudar) {
  for (;;) {
    await new Promise(r => setTimeout(r, 2500));
    const res = await api(`/api/nvr/driver/rede/situacao?job_id=${encodeURIComponent(job.id)}`);
    const j = await res.json().catch(() => ({}));
    if (!res.ok) { aoMudar({ ...job, estado: 'erro', erro: j.detail || 'perdi o andamento' }); return; }
    aoMudar(j);
    if (j.estado !== 'rodando') return;
  }
}

function reLigarEditar(app) {
  const e = _re;
  if (!e) return;
  app.querySelectorAll('[data-re-campo]').forEach(i => i.addEventListener('input', () => {
    e.novo[i.dataset.reCampo] = i.value.trim();
    reConferirDepois();
  }));
  app.querySelector('[data-re-desfazer-edicao]')?.addEventListener('click', () => {
    e.novo = Object.fromEntries([...RE_CAMPOS_IP, ...RE_CAMPOS_PORTA].map(([k]) => [k, String(e.atual[k] || '')]));
    e.checks = []; e.mud = []; recPintarApp();
  });
  app.querySelector('[data-re-revisar]')?.addEventListener('click', () => { if (!reBloqueado(e)) { e.etapa = 2; e.confirma = ''; recPintarApp(); } });
  app.querySelector('[data-re-voltar]')?.addEventListener('click', () => { e.etapa = 1; recPintarApp(); });
  app.querySelector('[data-re-confirma]')?.addEventListener('input', ev => {
    e.confirma = ev.target.value;
    const bt = app.querySelector('[data-re-aplicar]');
    if (bt) bt.disabled = e.confirma.trim() !== (e.novo.ip || e.atual.ip);
  });
  app.querySelector('[data-re-aplicar]')?.addEventListener('click', async ev => {
    ev.currentTarget.disabled = true;
    try {
      const res = await api('/api/nvr/driver/rede/aplicar', { method: 'POST', body: JSON.stringify({ ...recAvAlvo(), novo: e.novo, confirmar: e.confirma.trim() }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
      e.etapa = 3; e.job = j; recPintarApp();
      reAcompanhar(j, novo => { if (_re === e) { e.job = novo; if (_recSec === 'rede') recPintarApp(); } });
    } catch (err) { showToast(`Não apliquei: ${err.message}`, true); recPintarApp(); }
  });
  app.querySelector('[data-re-recomecar]')?.addEventListener('click', () => { e.etapa = 1; e.job = null; e.atual = null; reCarregar(); });
  app.querySelector('[data-re-reabrir]')?.addEventListener('click', () => {
    // A sessao do gravador passa a apontar para o endereco novo e o raio-x
    // e lido de novo de la.
    const h = document.getElementById('deployStandaloneRecorderHost');
    const pt = document.getElementById('deployStandaloneRecorderPort');
    if (h) h.value = e.job.host;
    if (pt) pt.value = e.job.http_port;
    _re = null; _recAv = null; _recRes = null;
    deployRecorderCarregarXray();
  });
  app.querySelector('[data-re-confirma-reinicio]')?.addEventListener('input', ev => {
    e.confirmaReinicio = ev.target.value;
    const bt = app.querySelector('[data-re-reiniciar]');
    if (bt) bt.disabled = e.confirmaReinicio.trim().toLowerCase() !== 'reiniciar';
  });
  app.querySelector('[data-re-reiniciar]')?.addEventListener('click', async ev => {
    ev.currentTarget.disabled = true;
    try {
      const res = await api('/api/nvr/driver/reiniciar', { method: 'POST', body: JSON.stringify({ ...recAvAlvo(), confirmar: 'REINICIAR' }) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.detail || `HTTP ${res.status}`);
      e.reinicio = { job: j }; recPintarApp();
      reAcompanhar(j, novo => { if (_re === e) { e.reinicio = { job: novo }; if (_recSec === 'rede') recPintarApp(); } });
    } catch (err) { showToast(`Não reiniciei: ${err.message}`, true); recPintarApp(); }
  });
}

// ---- rodape: correcoes de rede (avisos 'dns' e 'alarme_rede' do servidor) ----
function reRodape(d) {
  if (!_recAv || _recAv.host !== d.host) { setTimeout(() => recAvCarregar(), 0); return ''; }
  const av = _recAv;
  const lista = (av.dados?.avisos || []).filter(a => a.grupo === 'rede');
  if (!lista.length) return av.carregando ? '' : `<div class="bloco re"><div class="bloco-cab"><div><h2>Correções de rede</h2>
    <p>DNS e alarmes de rede conferidos: nada a corrigir.</p></div></div></div>`;
  return `<div class="bloco re"><div class="bloco-cab"><div><h2>Correções de rede</h2>
    <p>Não mexem no endereço do gravador. Pedem confirmação e têm Desfazer.</p></div></div>
    ${lista.map(a => {
      const f = av.feitos[a.id];
      return `<div class="achado ${esc(a.nivel)} av"><span class="sev"></span>
        <div class="achado-txt"><b>${esc(a.titulo)}</b><span>${esc(a.causa)}</span>
          ${f ? `<div class="av-feito ${f.ok ? 'ok' : 'erro'}">${f.ok ? 'Corrigido e conferido no gravador' : esc(f.erro || 'não pegou')}
            ${f.ok && f.registro ? ` <button class="acao" type="button" data-av-desfazer="${esc(f.registro)}">Desfazer</button>` : ''}</div>` : ''}</div>
        ${f ? '' : `<button class="acao forte" type="button" data-re-corrigir="${esc(a.id)}" ${av.trabalhando ? 'disabled' : ''}>${esc(a.confirmar)}</button>`}
      </div>`;
    }).join('')}</div>`;
}

function reLigarRodape(app) {
  app.querySelectorAll('[data-re-corrigir]').forEach(b => b.addEventListener('click', () =>
    recAvAplicar(b.dataset.reCorrigir).then(() => recAvCarregar(true))));
  app.querySelectorAll('.re [data-av-desfazer]').forEach(b => b.addEventListener('click', ev =>
    recAvDesfazer(b.dataset.avDesfazer, ev.currentTarget)));
}

recRegistrarAbaRede('editar', 'Editar rede', reSecEditar, reLigarEditar, 90);
recRegistrarRodapeRede('correcoes', reRodape, reLigarRodape, 50);
