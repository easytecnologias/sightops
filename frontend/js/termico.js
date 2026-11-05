// =============================================================================
// Alerta Termico (Alerta > Alerta Termico)
//
// Pessoa detectada pelo CALOR nas cameras termicas radiometricas (HikMicro).
// O servidor le as cameras ativas a cada 2 s (app/services/termico_vigia.py) e
// grava o alerta com foto termica + colorida. Aqui:
//   - Alarmes: lista com filtro, o alarme aberto com as fotos, Ciente e
//     Falso alarme (com motivo);
//   - Cameras e regras: incluir camera do inventario, ligar, horario armado e
//     a regra de deteccao.
// Fotos vem com o token (api) e viram blob local. CSS aqui, prefixo tm-.
// =============================================================================
(function () {
  'use strict';

  const $ = id => document.getElementById(id);
  const h = s => (typeof esc === 'function' ? esc(s) : String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])));
  const toast = (m, erro) => (typeof showToast === 'function' ? showToast(m, erro) : console.log(m));
  const natural = (a, b) => String(a || '').localeCompare(String(b || ''), 'pt', { numeric: true, sensitivity: 'base' });
  const num = (v, d = 1) => (v === null || v === undefined || v === '' ? '—' : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }));
  const hora = s => { try { return new Date(s).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); } catch (_) { return s || ''; } };
  const dataHora = s => { try { return new Date(s).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'medium' }); } catch (_) { return s || ''; } };
  const icones = () => { try { window.lucide && window.lucide.createIcons(); } catch (_) { /* sem icones */ } };

  const SIT = { novo: ['Novo', 'danger'], visto: ['Visto', 'success'], falso: ['Falso alarme', 'amber'] };
  const MOTIVOS = [['animal', 'Animal'], ['sol', 'Reflexo do sol'], ['equipe', 'Equipe da usina'], ['mato', 'Vento ou mato'], ['veiculo', 'Veículo'], ['outro', 'Outro']];
  const CAMPOS = [
    ['dif_min', 'Dif. do fundo (°C)', 0.5], ['corpo_min', 'Corpo mín. (°C)', 0.5], ['corpo_max', 'Corpo máx. (°C)', 0.5],
    ['pontos_min', 'Tamanho mín. (pontos)', 1], ['quadros_seguidos', 'Leituras seguidas', 1], ['intervalo_alertas_s', 'Entre alertas (s)', 5],
  ];

  let aba = 'alarmes';
  let alertas = { alertas: [], total: 0, por_situacao: {}, por_site: {} };
  let cams = { cameras: [], no_inventario: [] };
  let filtro = { q: '', site: '', situacao: '' };
  let aberto = null, camAberta = null, poll = null;
  const fotos = {};   // url da api -> blob local

  // ---------------------------------------------------------------- CSS --
  const CSS = `
  .tm-tabs{display:flex;gap:4px;border-bottom:1px solid var(--border);margin-bottom:16px}
  .tm-tabs button{height:38px;padding:0 14px;border:0;background:none;color:var(--muted);font-size:13px;border-bottom:2px solid transparent;cursor:pointer}
  .tm-tabs button.on{color:var(--primary);border-bottom-color:var(--primary);font-weight:600}
  .tm-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:20px;align-items:start}
  @media (max-width:1100px){.tm-grid{grid-template-columns:1fr}}
  .tm-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:20px;display:flex;flex-direction:column;gap:14px;min-width:0}
  .tm-card h2{margin:0;font-size:15px}
  .tm-filtros{display:grid;grid-template-columns:2fr 1fr 1fr;gap:8px}
  .tm-filtros label,.tm-campo{display:flex;flex-direction:column;gap:4px;font-size:11px;color:var(--muted);white-space:nowrap}
  .tm-filtros input,.tm-filtros select,.tm-campo input,.tm-campo select{height:34px;border:1px solid var(--border);border-radius:6px;padding:0 10px;font-size:13px;background:var(--surface);color:var(--text);box-sizing:border-box;width:100%}
  .tm-tab{width:100%;border-collapse:collapse;table-layout:fixed;font-size:12px}
  .tm-tab th{height:36px;white-space:nowrap;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;border-bottom:1px solid var(--border);padding:0 10px}
  .tm-tab td{height:40px;border-bottom:1px solid var(--border);padding:0 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .tm-tab tbody tr{cursor:pointer}.tm-tab tbody tr:hover{background:var(--surface-soft)}.tm-tab tr.on{background:var(--blue-soft)}
  .tm-num{text-align:right;font-variant-numeric:tabular-nums}
  .tm-fotos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
  .tm-foto{position:relative;aspect-ratio:16/9;border-radius:6px;overflow:hidden;background:var(--sidebar)}
  .tm-foto img{width:100%;height:100%;object-fit:cover;display:block}
  .tm-foto .tm-caixa{position:absolute;border:2px solid var(--danger);box-sizing:border-box}
  .tm-foto .tm-vazio{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#b8c6cc;font-size:12px}
  .tm-legenda{font-size:12px;color:var(--muted);margin-top:6px}
  .tm-medidas{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}
  .tm-medidas div{background:var(--surface-soft);border:1px solid var(--border);border-radius:6px;padding:10px 12px}
  .tm-medidas span{display:block;font-size:11px;color:var(--muted)}.tm-medidas strong{font-size:15px;white-space:nowrap}
  .tm-acoes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
  .tm-vazio-card{color:var(--muted);font-size:13px;padding:30px 0;text-align:center}
  .tm-regra{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
  .tm-linha{display:flex;align-items:center;justify-content:space-between;gap:12px}
  .tm-sub{font-size:12px;color:var(--muted)}
  .tm-modal-fundo{position:fixed;inset:0;background:rgba(19,37,45,.45);z-index:1000;display:flex;align-items:center;justify-content:center}
  .tm-modal{background:var(--surface);border-radius:10px;padding:20px;width:min(460px,92vw);display:flex;flex-direction:column;gap:14px;box-shadow:var(--shadow)}
  .tm-motivos{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .tm-motivos button{height:42px;border:1px solid var(--border);border-radius:8px;background:var(--surface);font-size:13px;cursor:pointer}
  .tm-motivos button.on{border:2px solid var(--primary);background:var(--primary-soft);font-weight:600}
  `;
  function injetarCss() {
    if ($('tmCss')) return;
    const s = document.createElement('style'); s.id = 'tmCss'; s.textContent = CSS; document.head.appendChild(s);
  }
  const secao = () => $('viewTermico');

  // ------------------------------------------------------------ carregar --
  window.loadTermico = async function () {
    injetarCss();
    render();
    await Promise.all([carregarAlertas(), carregarCameras()]);
    agendar();
  };

  function agendar() {
    clearTimeout(poll);
    poll = setTimeout(async () => {
      const sec = secao();
      if (!sec || sec.classList.contains('hidden')) return;    // saiu da tela: para
      await carregarAlertas(true);
      agendar();
    }, 10000);
  }

  async function carregarAlertas(silencioso) {
    const r = await api('/api/termico/alertas?limite=300');
    if (!r || !r.ok) { if (!silencioso) toast('Não deu para carregar os alarmes.', true); return; }
    const antes = alertas.por_situacao?.novo || 0;
    alertas = await r.json();
    if (silencioso && (alertas.por_situacao?.novo || 0) > antes) toast('Novo alerta térmico.');
    if (aberto) aberto = alertas.alertas.find(a => a.id === aberto.id) || aberto;
    render();
  }

  async function carregarCameras() {
    const r = await api('/api/termico/cameras');
    if (!r || !r.ok) return;
    cams = await r.json();
    if (camAberta) camAberta = cams.cameras.find(c => c.id === camAberta.id) || null;
    render();
  }

  // -------------------------------------------------------------- render --
  function render() {
    const sec = secao(); if (!sec) return;
    const pend = alertas.por_situacao?.novo || 0;
    const ativas = cams.cameras.filter(c => c.ativo);
    const lendo = ativas.filter(c => c.leitura === 'ok').length;
    sec.innerHTML = `
      <div class="page-heading">
        <div><p class="eyebrow">Alerta</p><h1>Alerta Térmico</h1>
          <p>Pessoa detectada pelo calor nas câmeras térmicas. ${ativas.length} câmera(s) vigiando · leitura a cada 2 s.</p></div>
      </div>
      <div class="rotas-kpis">
        <article class="rotas-kpi"><span>Alarmes listados</span><strong>${alertas.total || 0}</strong></article>
        <article class="rotas-kpi${pend ? ' is-danger' : ''}"><span>Sem resposta</span><strong style="color:${pend ? 'var(--danger)' : 'inherit'}">${pend}</strong></article>
        <article class="rotas-kpi"><span>Câmeras ativas</span><strong>${ativas.length} <small>de ${cams.cameras.length}</small></strong></article>
        <article class="rotas-kpi${ativas.length && lendo < ativas.length ? ' is-amber' : ''}"><span>Medindo temperatura</span><strong>${lendo} <small>de ${ativas.length}</small></strong></article>
      </div>
      <div class="tm-tabs" role="tablist">
        <button type="button" role="tab" data-tm-aba="alarmes" class="${aba === 'alarmes' ? 'on' : ''}">Alarmes ${pend ? `<span class="pill danger">${pend}</span>` : ''}</button>
        <button type="button" role="tab" data-tm-aba="cameras" class="${aba === 'cameras' ? 'on' : ''}">Câmeras e regras</button>
      </div>
      ${aba === 'alarmes' ? htmlAlarmes() : htmlCameras()}`;
    ligar(sec);
    icones();
    if (aba === 'alarmes' && aberto) carregarFotos(aberto);
  }

  function alertasFiltrados() {
    const q = filtro.q.trim().toLowerCase();
    return alertas.alertas.filter(a => (!filtro.site || a.site === filtro.site)
      && (!filtro.situacao || a.situacao === filtro.situacao)
      && (!q || `${a.camera_nome} ${a.site}`.toLowerCase().includes(q)));
  }

  function htmlAlarmes() {
    const lista = alertasFiltrados();
    const sites = Object.keys(alertas.por_site || {}).sort(natural);
    const ps = alertas.por_situacao || {};
    const linhas = lista.map(a => {
      const [rot, cls] = SIT[a.situacao] || SIT.novo;
      return `<tr data-tm-alerta="${h(a.id)}" class="${aberto && aberto.id === a.id ? 'on' : ''}">
        <td>${h(hora(a.criado_at))}</td><td title="${h(a.camera_nome)}" style="font-weight:${a.situacao === 'novo' ? 600 : 400}">${h(a.camera_nome)}</td>
        <td title="${h(a.site)}">${h(a.site)}</td><td class="tm-num">${num(a.dif_c)} °C</td><td><span class="pill ${cls}">${rot}</span></td></tr>`;
    }).join('') || `<tr><td colspan="5" style="text-align:center;color:var(--muted);height:80px">Nenhum alarme ${filtro.situacao || filtro.site || filtro.q ? 'com esse filtro' : 'ainda'}.</td></tr>`;
    return `<div class="tm-grid">
      <section class="tm-card">
        <div class="tm-linha"><h2>Alarmes</h2><span class="tm-sub">mais recentes primeiro</span></div>
        <div class="tm-filtros">
          <label>Buscar<input type="search" id="tmBusca" placeholder="Câmera ou usina" value="${h(filtro.q)}"></label>
          <label>Usina<select id="tmSite"><option value="">Todas (${alertas.total || 0})</option>${sites.map(s => `<option value="${h(s)}" ${s === filtro.site ? 'selected' : ''}>${h(s || '(sem local)')} (${alertas.por_site[s]})</option>`).join('')}</select></label>
          <label>Situação<select id="tmSit"><option value="">Todas</option>${Object.entries(SIT).map(([k, [rot]]) => `<option value="${k}" ${k === filtro.situacao ? 'selected' : ''}>${rot} (${ps[k] || 0})</option>`).join('')}</select></label>
        </div>
        <div class="table-wrap"><table class="tm-tab">
          <colgroup><col style="width:56px"><col><col style="width:140px"><col style="width:96px"><col style="width:122px"></colgroup>
          <thead><tr><th>Hora</th><th>Câmera</th><th>Usina</th><th class="tm-num">Dif. fundo</th><th>Situação</th></tr></thead>
          <tbody>${linhas}</tbody></table></div>
      </section>
      <section class="tm-card">${aberto ? htmlDetalhe(aberto) : '<div class="tm-vazio-card">Clique num alarme para ver as fotos e responder.</div>'}</section>
    </div>`;
  }

  function caixaCss(a) {
    const c = a.mancha?.caixa; if (!c) return '';
    const m = 0.02;   // folga para a caixa nao esconder a pessoa
    return `left:${(Math.max(0, c[0] - m) * 100).toFixed(1)}%;top:${(Math.max(0, c[1] - m) * 100).toFixed(1)}%;width:${((c[2] + 2 * m) * 100).toFixed(1)}%;height:${((c[3] + 2 * m) * 100).toFixed(1)}%`;
  }

  function htmlDetalhe(a) {
    const [rot, cls] = SIT[a.situacao] || SIT.novo;
    const resp = a.situacao === 'novo' ? '' : `<div class="tm-sub">${a.situacao === 'falso' ? 'Falso alarme' : 'Ciente'} por ${h(a.visto_por || '—')} em ${h(dataHora(a.visto_at))}${a.motivo_falso ? ` · ${h((MOTIVOS.find(m => m[0] === a.motivo_falso) || ['', a.motivo_falso])[1])}` : ''}${a.comentario ? ` · “${h(a.comentario)}”` : ''}</div>`;
    return `
      <div class="tm-linha"><div style="min-width:0"><h2 style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${h(a.camera_nome)} · ${h(a.site)}</h2>
        <div class="tm-sub">Pessoa detectada pelo calor · ${h(dataHora(a.criado_at))}</div></div><span class="pill ${cls}">${rot}</span></div>
      <div class="tm-fotos">
        <figure style="margin:0"><div class="tm-foto" id="tmFotoT"><div class="tm-vazio">Carregando…</div><div class="tm-caixa" style="${caixaCss(a)}"></div></div><figcaption class="tm-legenda">Térmica</figcaption></figure>
        <figure style="margin:0"><div class="tm-foto" id="tmFotoV"><div class="tm-vazio">${a.fotos.visivel ? 'Carregando…' : 'Sem foto colorida'}</div></div><figcaption class="tm-legenda">Colorida, mesmo instante</figcaption></figure>
      </div>
      <div class="tm-medidas">
        <div><span>Mancha</span><strong style="color:var(--danger)">${num(a.temp_c)} °C</strong></div>
        <div><span>Fundo</span><strong>${num(a.fundo_c)} °C</strong></div>
        <div><span>Diferença</span><strong>${num(a.dif_c)} °C</strong></div>
        <div><span>Tamanho</span><strong>${a.mancha?.pontos || '—'} pts</strong></div>
      </div>
      ${a.situacao === 'novo' ? `<div class="tm-acoes">
        <button class="primary-action" type="button" data-tm-ciente>Ciente</button>
        <button class="secondary-action" type="button" data-tm-falso style="color:var(--amber)">Falso alarme</button>
        <button class="secondary-action" type="button" data-tm-fechar>Fechar</button></div>` : resp}`;
  }

  async function blobUrl(url) {
    if (!url) return '';
    if (fotos[url]) return fotos[url];
    const r = await api(url);
    if (!r || !r.ok) return '';
    fotos[url] = URL.createObjectURL(await r.blob());
    return fotos[url];
  }

  async function carregarFotos(a) {
    const [t, v] = await Promise.all([blobUrl(a.fotos.termico), blobUrl(a.fotos.visivel)]);
    if (!aberto || aberto.id !== a.id) return;
    const pT = $('tmFotoT'), pV = $('tmFotoV');
    if (pT) { const vz = pT.querySelector('.tm-vazio'); if (t) { vz?.remove(); pT.insertAdjacentHTML('afterbegin', `<img src="${t}" alt="Imagem térmica do alarme">`); } else if (vz) vz.textContent = 'Sem foto térmica'; }
    if (pV) { const vz = pV.querySelector('.tm-vazio'); if (v) { vz?.remove(); pV.insertAdjacentHTML('afterbegin', `<img src="${v}" alt="Imagem colorida do alarme"><div class="tm-caixa" style="${caixaCss(a)}"></div>`); } else if (vz) vz.textContent = 'Sem foto colorida'; }
  }

  // ------------------------------------------------------------ cameras --
  function htmlCameras() {
    const linhas = cams.cameras.map(c => {
      const st = !c.ativo ? ['Desligada', 'neutral'] : c.leitura === 'erro' ? ['Sem medição', 'amber'] : c.leitura === 'ok' ? [c.armado_agora ? 'Vigiando' : 'Fora do horário', c.armado_agora ? 'success' : 'neutral'] : ['Aguardando', 'neutral'];
      return `<tr data-tm-cam="${h(c.id)}" class="${camAberta && camAberta.id === c.id ? 'on' : ''}">
        <td title="${h(c.nome)} · ${h(c.ip)}" style="font-weight:${c.pendentes ? 600 : 400}">${h(c.nome)} <span class="tm-sub">· ${h(c.ip)}</span></td>
        <td title="${h(c.site)}">${h(c.site)}</td><td class="tm-num">${c.fundo_c == null ? '—' : num(c.fundo_c) + ' °C'}</td>
        <td>${c.armado_de ? `${h(c.armado_de)}–${h(c.armado_ate)}` : '24 h'}</td><td><span class="pill ${st[1]}" title="${h(c.leitura_erro)}">${st[0]}</span></td></tr>`;
    }).join('') || '<tr><td colspan="5" style="text-align:center;color:var(--muted);height:80px">Nenhuma câmera no Alerta Térmico ainda.</td></tr>';
    const novas = cams.no_inventario.map(n => `<div class="tm-linha" style="border-top:1px solid var(--border);padding-top:10px">
        <div style="min-width:0"><strong style="font-size:13px">${h(n.nome)}</strong><div class="tm-sub">${h(n.site)} · ${h(n.ip)} · ${h(n.modelo)}</div></div>
        <button class="secondary-action" type="button" data-tm-incluir="${h(n.ip)}" data-tm-cid="${h(n.connector_id)}">Incluir</button></div>`).join('');
    return `<div class="tm-grid">
      <section class="tm-card">
        <div class="tm-linha"><h2>Câmeras térmicas</h2><span class="tm-sub">ordem: usina, câmera</span></div>
        <div class="table-wrap"><table class="tm-tab">
          <colgroup><col><col style="width:150px"><col style="width:76px"><col style="width:96px"><col style="width:116px"></colgroup>
          <thead><tr><th>Câmera</th><th>Usina</th><th class="tm-num">Fundo</th><th>Horário</th><th>Situação</th></tr></thead>
          <tbody>${linhas}</tbody></table></div>
        ${novas ? `<div><div class="tm-sub" style="margin-bottom:6px">Térmicas no inventário que ainda não estão aqui</div>${novas}</div>` : ''}
      </section>
      <section class="tm-card">${camAberta ? htmlRegra(camAberta) : '<div class="tm-vazio-card">Clique numa câmera para ligar e ajustar a regra.</div>'}</section>
    </div>`;
  }

  function htmlRegra(c) {
    const r = c.regra || {};
    const area = (r.areas && r.areas[0]) || null;
    const bx = area ? [Math.min(...area.map(p => p[0])), Math.max(...area.map(p => p[0])), Math.min(...area.map(p => p[1])), Math.max(...area.map(p => p[1]))] : [0, 1, 0, 1];
    const pct = v => Math.round(v * 100);
    return `
      <div class="tm-linha"><div style="min-width:0"><h2>Regra · ${h(c.nome)}</h2><div class="tm-sub">${h(c.modelo)} · ${h(c.ip)} · ${h(c.site)}</div></div>
        <label class="tm-linha" style="gap:8px;font-size:13px"><input type="checkbox" id="tmAtivo" ${c.ativo ? 'checked' : ''}> Ligada</label></div>
      ${c.leitura === 'erro' ? `<div class="pill amber" style="white-space:normal;line-height:1.4;padding:8px 10px">Sem medição: ${h(c.leitura_erro)}</div>` : ''}
      <div class="tm-regra">
        ${CAMPOS.map(([k, rot, passo]) => `<label class="tm-campo">${rot}<input type="number" step="${passo}" data-tm-campo="${k}" value="${h(r[k])}"></label>`).join('')}
        <label class="tm-campo">Armada das<input type="time" id="tmDe" value="${h(c.armado_de)}"></label>
        <label class="tm-campo">até<input type="time" id="tmAte" value="${h(c.armado_ate)}"></label>
        <div class="tm-campo">Horário<span style="height:34px;display:flex;align-items:center;color:var(--text);font-size:13px">${c.armado_de ? 'parcial' : '24 horas (vazio)'}</span></div>
      </div>
      <div>
        <div class="tm-sub" style="margin-bottom:6px">Área vigiada (retângulo, % da imagem; 0–100 = imagem inteira)</div>
        <div class="tm-regra">
          <label class="tm-campo">Da esquerda (%)<input type="number" min="0" max="100" id="tmX0" value="${pct(bx[0])}"></label>
          <label class="tm-campo">Até (%)<input type="number" min="0" max="100" id="tmX1" value="${pct(bx[1])}"></label>
          <span></span>
          <label class="tm-campo">Do topo (%)<input type="number" min="0" max="100" id="tmY0" value="${pct(bx[2])}"></label>
          <label class="tm-campo">Até (%)<input type="number" min="0" max="100" id="tmY1" value="${pct(bx[3])}"></label>
          <span class="tm-sub" style="align-self:end">${(r.ignorar || []).length} área(s) ignorada(s)</span>
        </div>
      </div>
      <div class="tm-acoes">
        <button class="primary-action" type="button" data-tm-salvar>Salvar</button>
        <button class="secondary-action" type="button" data-tm-fechar-cam>Fechar</button>
        <button class="secondary-action danger-action" type="button" data-tm-remover>Remover</button>
      </div>`;
  }

  // -------------------------------------------------------------- eventos --
  function ligar(sec) {
    sec.querySelectorAll('[data-tm-aba]').forEach(b => b.onclick = () => { aba = b.dataset.tmAba; render(); });
    const busca = $('tmBusca');
    if (busca) busca.oninput = () => { filtro.q = busca.value; const pos = busca.selectionStart; render(); const b = $('tmBusca'); b.focus(); b.setSelectionRange(pos, pos); };
    if ($('tmSite')) $('tmSite').onchange = e => { filtro.site = e.target.value; render(); };
    if ($('tmSit')) $('tmSit').onchange = e => { filtro.situacao = e.target.value; render(); };
    sec.querySelectorAll('[data-tm-alerta]').forEach(tr => tr.onclick = () => { aberto = alertas.alertas.find(a => a.id === tr.dataset.tmAlerta) || null; render(); });
    sec.querySelector('[data-tm-ciente]')?.addEventListener('click', () => responder('ciente', {}));
    sec.querySelector('[data-tm-falso]')?.addEventListener('click', pedirMotivo);
    sec.querySelector('[data-tm-fechar]')?.addEventListener('click', () => { aberto = null; render(); });
    sec.querySelectorAll('[data-tm-cam]').forEach(tr => tr.onclick = () => { camAberta = cams.cameras.find(c => c.id === tr.dataset.tmCam) || null; render(); });
    sec.querySelectorAll('[data-tm-incluir]').forEach(b => b.onclick = () => incluir(b.dataset.tmIncluir, b.dataset.tmCid));
    sec.querySelector('[data-tm-salvar]')?.addEventListener('click', salvarRegra);
    sec.querySelector('[data-tm-fechar-cam]')?.addEventListener('click', () => { camAberta = null; render(); });
    sec.querySelector('[data-tm-remover]')?.addEventListener('click', removerCamera);
  }

  async function responder(tipo, corpo) {
    if (!aberto) return;
    const r = await api(`/api/termico/alertas/${encodeURIComponent(aberto.id)}/${tipo}`, { method: 'POST', body: JSON.stringify(corpo) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para salvar a resposta.', true); return; }
    aberto = await r.json();
    toast(tipo === 'ciente' ? 'Marcado como Ciente.' : 'Marcado como falso alarme.');
    await carregarAlertas(true);
  }

  // Modal: fecha so por X, Cancelar ou Esc (nunca clicando fora).
  function pedirMotivo() {
    let motivo = '';
    const fundo = document.createElement('div');
    fundo.className = 'tm-modal-fundo';
    fundo.innerHTML = `<div class="tm-modal" role="dialog" aria-label="Por que foi falso alarme?">
      <div class="tm-linha"><h2 style="margin:0;font-size:16px">Por que foi falso alarme?</h2><button class="ghost-action" type="button" data-x aria-label="Fechar">✕</button></div>
      <div class="tm-motivos">${MOTIVOS.map(([k, rot]) => `<button type="button" data-m="${k}">${rot}</button>`).join('')}</div>
      <label class="tm-campo">Comentário (opcional)<input id="tmComent" maxlength="500"></label>
      <div class="tm-linha" style="justify-content:flex-end"><button class="secondary-action" type="button" data-x>Cancelar</button>
        <button class="primary-action" type="button" data-ok disabled>Confirmar falso alarme</button></div></div>`;
    document.body.appendChild(fundo);
    const fechar = () => { fundo.remove(); document.removeEventListener('keydown', esc); };
    const esc = e => { if (e.key === 'Escape') fechar(); };
    document.addEventListener('keydown', esc);
    fundo.querySelectorAll('[data-x]').forEach(b => b.onclick = fechar);
    fundo.querySelectorAll('[data-m]').forEach(b => b.onclick = () => {
      motivo = b.dataset.m;
      fundo.querySelectorAll('[data-m]').forEach(x => x.classList.toggle('on', x === b));
      fundo.querySelector('[data-ok]').disabled = false;
    });
    fundo.querySelector('[data-ok]').onclick = async () => {
      const comentario = fundo.querySelector('#tmComent').value;
      fechar();
      await responder('falso', { motivo, comentario });
    };
  }

  async function incluir(ip, cid) {
    const n = cams.no_inventario.find(x => x.ip === ip && (x.connector_id || "") === (cid || ""));
    const r = await api("/api/termico/cameras", { method: "POST", body: JSON.stringify({ ip, connector_id: n ? n.connector_id : cid }) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para incluir.', true); return; }
    camAberta = await r.json();
    toast('Câmera incluída. Ajuste a regra e ligue.');
    await carregarCameras();
  }

  async function salvarRegra() {
    if (!camAberta) return;
    const regra = {};
    secao().querySelectorAll('[data-tm-campo]').forEach(i => { if (i.value !== '') regra[i.dataset.tmCampo] = Number(i.value); });
    const v = id => Math.min(100, Math.max(0, Number($(id).value || 0))) / 100;
    const [x0, x1, y0, y1] = [v('tmX0'), v('tmX1'), v('tmY0'), v('tmY1')];
    if (x1 <= x0 || y1 <= y0) { toast('A área vigiada precisa ter largura e altura.', true); return; }
    regra.areas = (x0 === 0 && x1 === 1 && y0 === 0 && y1 === 1) ? [] : [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]];
    const corpo = { ativo: $('tmAtivo').checked, armado_de: $('tmDe').value, armado_ate: $('tmAte').value, regra };
    const r = await api(`/api/termico/cameras/${encodeURIComponent(camAberta.id)}`, { method: 'PUT', body: JSON.stringify(corpo) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para salvar.', true); return; }
    camAberta = await r.json();
    toast('Regra salva. Vale na próxima leitura.');
    await carregarCameras();
  }

  async function removerCamera() {
    if (!camAberta || !confirm(`Tirar ${camAberta.nome} do Alerta Térmico? Os alarmes antigos continuam guardados.`)) return;
    const r = await api(`/api/termico/cameras/${encodeURIComponent(camAberta.id)}`, { method: 'DELETE', body: '' });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para remover.', true); return; }
    camAberta = null;
    toast('Câmera removida do Alerta Térmico.');
    await carregarCameras();
  }
})();
