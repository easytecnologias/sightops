// =============================================================================
// Cameras termicas (Automacoes > Cameras termicas) -- o "Alerta Termico"
//
// Pessoa detectada pelo CALOR nas cameras termicas radiometricas (HikMicro).
// O servidor le as cameras ativas a cada 2 s (app/services/termico_vigia.py) e
// grava o alerta com foto termica + colorida. Aqui:
//   - Alarmes: lista com filtro, o alarme aberto com as fotos, Ciente e
//     Falso alarme (com motivo);
//   - Ao vivo: parede de videos; configurar e vigiar acontece na propria camera;
//   - Automacoes: quando detectar, leva a speed ao preset ou liga saida de
//     alarme. Nasce em Simular (ver app/services/automacao_store.py).
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
    ['dif_min', 'Dif. do fundo (°C)', 0.5], ['contraste_min', 'Contraste c/ entorno (°C)', 0.5], ['movimento_min', 'Precisa andar (pontos, 0 = não)', 1], ['corpo_min', 'Corpo mín. (°C)', 0.5], ['corpo_max', 'Corpo máx. (°C)', 0.5],
    ['pontos_min', 'Tamanho mín. (pontos)', 1], ['quadros_seguidos', 'Leituras seguidas', 1], ['intervalo_alertas_s', 'Entre alertas (s)', 5],
  ];

  let aba = 'vivo', carregando = false, geral = null;
  let alertas = { alertas: [], total: 0, por_situacao: {}, por_site: {} };
  let cams = { cameras: [], no_inventario: [] };
  let filtro = { q: '', site: '', situacao: '' };
  let aberto = null, poll = null;
  const fotos = {};   // url da api -> blob local
  let auto = { automacoes: [], execucoes: [], equipamentos: [] };
  let autoAberta = null;

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
  .tm-vazio-util{align-items:center;padding:40px 20px;gap:12px;text-align:center}
  .tm-ic-ok{width:44px;height:44px;border-radius:50%;background:var(--primary-soft);color:var(--primary);display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700}
  .tm-teste-linha{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin-top:8px}
  .tm-teste-linha select{max-width:100%}
  .tm-sugestoes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,320px));justify-content:center;gap:12px;width:100%;margin-top:8px}
  .tm-sugestao{display:flex;flex-direction:column;gap:4px;padding:14px;border:1px solid var(--border);border-radius:10px;background:var(--surface);text-align:left;cursor:pointer;font:inherit;color:var(--text)}
  .tm-sugestao:hover{border-color:var(--primary)}
  .tm-sugestao span{font-size:12px;color:var(--muted)}
  .tm-faixa{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:12px 16px;border-radius:10px;background:var(--primary-soft);color:#06573f;font-weight:600;margin-bottom:14px}
  .tm-faixa small{font-weight:400;font-size:12px}
  .tm-faixa.alarme{background:var(--danger);color:#fff;animation:tmFaixa 2s ease-in-out infinite}
  .tm-ponto{width:9px;height:9px;border-radius:50%;background:currentColor;box-shadow:0 0 0 4px rgba(8,127,91,.18)}
  .tm-ferr{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:14px}
  .tm-seg{display:inline-flex;border:1px solid var(--border);border-radius:6px;overflow:hidden;background:var(--surface)}
  .tm-seg button{height:34px;padding:0 12px;border:0;background:none;color:var(--muted);cursor:pointer}
  .tm-seg button.on{background:var(--blue-soft);color:var(--blue);font-weight:600}
  .tm-sel{height:36px;border:1px solid var(--border);border-radius:6px;padding:0 8px;background:var(--surface);color:var(--text);font:inherit}
  .tm-parede-grade{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:20px;align-items:start;margin-bottom:10px}
  .tm-parede{display:flex;flex-direction:column;gap:18px;min-width:0}
  .tm-usina{display:flex;flex-direction:column;gap:10px}
  .tm-usina h2{margin:0;font-size:15px}
  .tm-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}
  .tm-abrir{border:0;padding:0;width:100%;display:block;cursor:pointer}
  .tm-tile-pe{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:40px;padding:0 12px;font-size:12px;color:var(--muted)}
  .tm-alarme{box-shadow:0 0 0 2px var(--danger),0 0 0 6px rgba(201,42,42,.14)!important;animation:tmPulsa 1.6s ease-in-out infinite}
  .tm-l-vivo{bottom:10px;left:10px;font-size:11px}
  .tm-l-temp{bottom:10px;right:10px}
  .tm-vivo{width:7px;height:7px;border-radius:50%;background:#ff5a5a;animation:tmVivo 1.4s ease-in-out infinite}
  .pdv-v-sit.tm-sit-ok{background:var(--primary)}.pdv-v-sit.tm-sit-alarme{background:var(--danger)}.pdv-v-sit.tm-sit-aviso{background:var(--amber)}.pdv-v-sit.tm-sit-fora{background:#4b5961}
  .tm-lado{background:var(--surface);border-radius:10px;box-shadow:0 0 0 1px var(--border);padding:14px;display:flex;flex-direction:column;gap:8px}
  .tm-lado h2{margin:0 0 4px;font-size:15px}
  .tm-ev{display:grid;grid-template-columns:44px 1fr;gap:8px;padding:8px 0;border:0;border-top:1px solid var(--border);background:none;font-size:12px;text-align:left;cursor:pointer;color:var(--muted)}
  .tm-ev b{display:block;color:var(--text);font-weight:600}
  .tm-fundo{position:fixed;inset:0;background:rgba(19,37,45,.45);z-index:900}
  .tm-gaveta{position:fixed;top:0;right:0;bottom:0;width:min(680px,100vw);background:var(--surface);z-index:901;box-shadow:-16px 0 42px rgba(23,32,38,.2);display:flex;flex-direction:column}
  .tm-gaveta h2{margin:0;font-size:15px}
  .tm-gav-cab{display:flex;align-items:center;gap:10px;padding:14px 18px;border-bottom:1px solid var(--border)}
  .tm-gav-corpo{flex:1;overflow:auto;padding:16px 18px;display:flex;flex-direction:column;gap:14px}
  .tm-gav-pe{display:flex;flex-wrap:wrap;gap:8px;padding:12px 18px;border-top:1px solid var(--border);background:var(--surface-soft)}
  .tm-foto video{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
  .tm-desenho{cursor:crosshair;touch-action:none;user-select:none;border-radius:8px}
  .tm-camada{position:absolute;inset:0;pointer-events:none}
  .tm-area,.tm-ignorar,.tm-mancha{position:absolute;border-radius:6px;box-sizing:border-box}
  .tm-area{border:2px solid #3ddc97;background:rgba(61,220,151,.16)}
  .tm-ignorar{border:2px dashed #ffb44d;background:rgba(19,37,45,.5)}
  .tm-mancha{border:2px solid #ff5a5a}
  .tm-cego{position:absolute;background:rgba(255,90,90,.28)}
  .tm-perfil{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr) minmax(0,1.2fr) minmax(0,.9fr) 32px;gap:8px;align-items:end}
  .tm-perfil input,.tm-perfil select{min-width:0;width:100%;box-sizing:border-box}
  @media (max-width:560px){.tm-perfil{grid-template-columns:repeat(2,minmax(0,1fr))}}
  .tm-tirar-reg{position:absolute;right:3px;top:3px;width:20px;height:20px;padding:0;border:0;border-radius:4px;background:rgba(19,37,45,.82);color:#fff;font-size:11px;cursor:pointer;pointer-events:auto}
  .tm-marco{position:absolute;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:var(--primary);color:#fff;font-size:12px;font-weight:700;display:flex;align-items:center;justify-content:center}
  .tm-mira{position:absolute;left:50%;top:50%;width:26px;height:26px;margin:-13px 0 0 -13px;border:2px solid #fff;border-radius:50%;pointer-events:none}
  .tm-geral{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:20px}
  .tm-grav{width:100%;aspect-ratio:4/3;background:#000;border-radius:6px;display:block}
  .tm-mancha span{left:0;top:-22px;white-space:nowrap}
  .tm-area span,.tm-ignorar span,.tm-mancha span{position:absolute;left:4px;top:4px;padding:1px 6px;border-radius:4px;background:rgba(19,37,45,.82);color:#fff;font-size:11px;font-weight:600}
  .tm-dica{position:absolute;left:50%;top:10px;transform:translateX(-50%);padding:4px 12px;border-radius:14px;background:rgba(19,37,45,.82);color:#fff;font-size:12px;white-space:nowrap;pointer-events:none}
  .tm-perg{display:flex;flex-direction:column;gap:8px}
  .tm-chips{display:flex;flex-wrap:wrap;gap:8px}
  .tm-chips button{min-height:36px;padding:0 14px;border:1px solid var(--border);border-radius:18px;background:var(--surface);cursor:pointer}
  .tm-chips button.on{background:var(--primary-soft);border-color:var(--primary);color:#06573f;font-weight:600}
  .tm-avancado summary{cursor:pointer;color:var(--blue);font-weight:600;font-size:12px}
  .tm-alerta-msg{padding:8px 10px;border-radius:6px;background:var(--amber-soft);color:#8a5100;font-size:12px}
  @keyframes tmVivo{50%{opacity:.25}}
  @keyframes tmPulsa{50%{box-shadow:0 0 0 2px var(--danger),0 0 0 10px rgba(201,42,42,.05)}}
  @keyframes tmFaixa{50%{background:#a51f1f}}
  @media (prefers-reduced-motion:reduce){.tm-vivo,.tm-alarme,.tm-faixa.alarme{animation:none}}
  @media (max-width:1180px){.tm-parede-grade{grid-template-columns:minmax(0,1fr)}.tm-tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}
  @media (max-width:640px){.tm-tiles{grid-template-columns:minmax(0,1fr)}}
  .tm-acao{border:1px solid var(--border);border-radius:8px;padding:12px;display:flex;flex-direction:column;gap:10px}
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
    carregando = true;      // sem isso cada carga monta os videos e eles conectam duas vezes
    await Promise.all([carregarAlertas(true), carregarCameras(), carregarAutomacoes()]);
    carregando = false;
    render();
    agendar();
  };

  function agendar() {
    clearTimeout(poll);
    poll = setTimeout(async () => {
      const sec = secao();
      if (!sec || sec.classList.contains('hidden')) { pararPlayers(); pararGaveta(); return; }    // saiu da tela: para
      await Promise.all([carregarAlertas(true), carregarCameras()]);
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
    atualizar();
  }

  // Na parede ao vivo so repinta; refaz a tela se mudou o conjunto de cameras.
  function atualizar() {
    if (carregando) return;
    if (aba === 'vivo' && paredeChave && paredeChave === todasCams().map(idCam).join(',') + vista + filtroUsina) { pintarVivo(); return; }
    render();
  }

  async function carregarCameras() {
    const r = await api('/api/termico/cameras');
    if (!r || !r.ok) return;
    cams = await r.json();
    atualizar();
  }

  // -------------------------------------------------------------- render --
  function render() {
    const sec = secao(); if (!sec) return;
    pararPlayers();
    const pend = alertas.por_situacao?.novo || 0;
    const ativas = cams.cameras.filter(c => c.ativo);
    const lendo = ativas.filter(c => c.leitura === 'ok').length;
    sec.innerHTML = `
      <div class="page-heading">
        <div><p class="eyebrow">Automações</p><h1>Câmeras térmicas</h1>
          <p>${ativas.length} de ${cams.cameras.length + (cams.no_inventario || []).length} câmera(s) vigiando pelo calor · ${lendo} medindo agora.</p></div>
      </div>
      <div class="tm-tabs" role="tablist">
        <button type="button" role="tab" data-tm-aba="vivo" class="${aba === 'vivo' ? 'on' : ''}">Ao vivo</button>
        <button type="button" role="tab" data-tm-aba="geral" class="${aba === 'geral' ? 'on' : ''}">Visão geral</button>
        <button type="button" role="tab" data-tm-aba="alarmes" class="${aba === 'alarmes' ? 'on' : ''}">Alarmes ${pend ? `<span class="pill danger">${pend}</span>` : ''}</button>
        <button type="button" role="tab" data-tm-aba="automacoes" class="${aba === 'automacoes' ? 'on' : ''}">Automações</button>
      </div>
      ${aba === 'vivo' ? htmlVivo() : aba === 'geral' ? htmlGeral() : aba === 'alarmes' ? htmlAlarmes() : htmlAutomacoes()}`;
    ligar(sec);
    icones();
    if (aba === 'alarmes' && aberto) carregarFotos(aberto);
    if (aba === 'vivo') { ligarVivo(sec); montarParede(); }
  }

  function alertasFiltrados() {
    const q = filtro.q.trim().toLowerCase();
    return alertas.alertas.filter(a => (!filtro.site || a.site === filtro.site)
      && (!filtro.situacao || a.situacao === filtro.situacao)
      && (!q || `${a.camera_nome} ${a.site}`.toLowerCase().includes(q)));
  }

  // ------------------------------------------------------------ visao geral --
  async function carregarGeral() {
    const r = await api('/api/termico/visao-geral?dias=30');
    if (!r?.ok) return;
    geral = await r.json();
    if (aba === 'geral') render();
  }

  const tempoCurto = s => s == null ? '—' : s < 60 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`;

  function htmlGeral() {
    if (!geral) return '<section class="tm-card"><div class="tm-vazio-card">Carregando…</div></section>';
    const hoje = new Date(); const dia = d => d.toISOString().slice(0, 10);
    const ini = new Date(hoje - 29 * 864e5);
    const kpi = (rot, v, cor) => `<div><span>${rot}</span><strong${cor ? ` style="color:var(--${cor})"` : ''}>${v}</strong></div>`;
    const cards = geral.usinas.map(u => `<section class="tm-card">
        <div class="tm-linha"><h2>${h(u.site || '(sem local)')}</h2><button class="secondary-action" type="button" data-tm-ver-usina="${h(u.site)}">Ver ao vivo</button></div>
        <div class="tm-medidas">${kpi('Lendo agora', `${u.lendo} de ${u.cameras}`, u.sem_leitura ? 'danger' : '')}${kpi('Sem resposta', u.pendentes, u.pendentes ? 'danger' : '')}${kpi('Alarmes 30 d', u.alarmes)}${kpi('Resposta', tempoCurto(u.resposta_s))}</div>
        ${u.sem_leitura ? `<div class="tm-sub" style="color:var(--danger)">${u.sem_leitura} câmera(s) sem leitura: nessas, não há alerta de pessoa.</div>` : ''}
      </section>`).join('') || '<section class="tm-card"><div class="tm-vazio-card">Nenhuma câmera vigiando ainda.</div></section>';
    const c = geral.config;
    const opt = (lista, atual, rot) => lista.map(([v, t]) => `<option value="${v}" ${Number(v) === Number(atual) ? 'selected' : ''}>${t}</option>`).join('');
    const sites = geral.usinas.map(u => u.site).sort(natural);
    return `<div class="tm-geral">${cards}</div>
      <div class="tm-geral" style="margin-top:20px">
        <section class="tm-card"><h2>Se ninguém responder</h2>
          <p class="tm-sub" style="margin:0">O alarme sem Ciente avisa os celulares de novo, com a sirene.</p>
          <div class="tm-regra"><label class="tm-campo">Avisar de novo depois de<select id="tmEscMin">${opt([[0, 'Nunca'], [5, '5 min'], [10, '10 min'], [15, '15 min'], [30, '30 min']], c.escalar_min)}</select></label>
            <label class="tm-campo">Quantas vezes<select id="tmEscVezes">${opt([[1, '1 vez'], [2, '2 vezes'], [3, '3 vezes'], [5, '5 vezes']], c.escalar_vezes)}</select></label></div>
          <div><button class="primary-action" type="button" data-tm-esc-salvar>Salvar</button></div>
        </section>
        <section class="tm-card"><h2>Relatório</h2>
          <p class="tm-sub" style="margin:0">Alarmes, respostas e falsos alarmes do período, em PDF.</p>
          <div class="tm-regra"><label class="tm-campo">De<input type="date" id="tmRelDe" value="${dia(ini)}"></label>
            <label class="tm-campo">Até<input type="date" id="tmRelAte" value="${dia(hoje)}"></label>
            <label class="tm-campo">Usina<select id="tmRelSite"><option value="">Todas</option>${sites.map(s => `<option value="${h(s)}">${h(s)}</option>`).join('')}</select></label></div>
          <div><button class="primary-action" type="button" data-tm-pdf>Baixar PDF</button></div>
        </section>
      </div>`;
  }

  async function salvarEscala() {
    const corpo = { escalar_min: Number($('tmEscMin').value), escalar_vezes: Number($('tmEscVezes').value) };
    const r = await api('/api/termico/config', { method: 'PUT', body: JSON.stringify(corpo) });
    if (!r?.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Só administrador muda isso.', true); return; }
    geral.config = await r.json();
    toast('Salvo.');
  }

  async function baixarPdf() {
    const q = new URLSearchParams({ de: $('tmRelDe').value, ate: $('tmRelAte').value, site: $('tmRelSite').value });
    const r = await api(`/api/termico/relatorio/pdf?${q}`);
    if (!r?.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para gerar o PDF.', true); return; }
    const nome = (r.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'cameras-termicas.pdf';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob());
    a.download = nome;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // Pagina vazia nao pode parecer quebrada: diz o que esta acontecendo e o que fazer.
  function htmlSemAlarmes() {
    const ativas = cams.cameras.filter(c => c.ativo);
    const lendo = ativas.filter(c => c.leitura === 'ok').length;
    const usinas = [...new Set(ativas.map(c => c.site))].sort(natural);
    const txt = !ativas.length ? 'Nenhuma câmera vigiando ainda. Vá em Ao vivo e clique em Vigiar.'
      : `${lendo} de ${ativas.length} câmera(s) lendo a temperatura agora${usinas.length ? ` em ${usinas.map(h).join(' e ')}` : ''}. Quando alguém passar, o alarme aparece aqui com as fotos e o vídeo.`;
    return `<section class="tm-card tm-vazio-util">
      <div class="tm-ic-ok">✓</div>
      <h2>Nenhum alarme até agora</h2>
      <p class="tm-sub" style="margin:0;max-width:560px;text-align:center">${txt}</p>
      ${ativas.length ? `${htmlTeste('primary-action')}
      <p class="tm-sub" style="margin:0">Cria um alarme marcado TESTE com a imagem de agora: avisa os celulares, abre problema no Zabbix até dar Ciente e roda as automações (para operador, só simula).</p>` : ''}
    </section>`;
  }

  function htmlTeste(botao) {
    const ativas = cams.cameras.filter(c => c.ativo).sort((a, b) => natural(a.site, b.site) || natural(a.nome, b.nome));
    if (!ativas.length) return '';
    return `<div class="tm-teste-linha"><select id="tmTesteCam" class="tm-sel" aria-label="Câmera do teste">${ativas.map(c => `<option value="${h(c.id)}">${h(c.site)} · ${h(c.nome)}</option>`).join('')}</select>
      <button class="${botao}" type="button" data-tm-teste-alarme>Gerar alarme de teste</button></div>`;
  }

  async function gerarTeste(id) {
    if (!id) return;
    const r = await api(`/api/termico/cameras/${encodeURIComponent(id)}/teste-alarme`, { method: 'POST', body: '{}' });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para gerar o teste.', true); return; }
    const { id: novo } = await r.json();
    toast('Alarme de teste criado.');
    await Promise.all([carregarAlertas(true), carregarCameras()]);
    aba = 'alarmes';
    aberto = alertas.alertas.find(a => a.id === novo) || null;
    render();
  }

  function htmlAlarmes() {
    if (!alertas.total) return htmlSemAlarmes();
    const lista = alertasFiltrados();
    const sites = Object.keys(alertas.por_site || {}).sort(natural);
    const ps = alertas.por_situacao || {};
    const linhas = lista.map(a => {
      const [rot, cls] = SIT[a.situacao] || SIT.novo;
      return `<tr data-tm-alerta="${h(a.id)}" class="${aberto && aberto.id === a.id ? 'on' : ''}">
        <td>${h(hora(a.criado_at))}</td><td title="${h(a.camera_nome)}" style="font-weight:${a.situacao === 'novo' ? 600 : 400}">${h(a.camera_nome)}${a.mancha?.teste ? ' <span class="pill neutral">TESTE</span>' : ''}</td>
        <td title="${h(a.site)}">${h(a.site)}</td><td class="tm-num">${a.dif_c == null ? '—' : `${num(a.dif_c)} °C`}</td><td><span class="pill ${cls}">${rot}</span></td></tr>`;
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
        ${htmlTeste('secondary-action')}
      </section>
      <section class="tm-card">${aberto ? htmlDetalhe(aberto) : '<div class="tm-vazio-card">Clique num alarme para ver as fotos e responder.</div>'}</section>
    </div>`;
  }

  function caixaCss(a) {
    const c = a.mancha?.caixa; if (!c) return 'display:none';
    const m = 0.02;   // folga para a caixa nao esconder a pessoa
    return `left:${(Math.max(0, c[0] - m) * 100).toFixed(1)}%;top:${(Math.max(0, c[1] - m) * 100).toFixed(1)}%;width:${((c[2] + 2 * m) * 100).toFixed(1)}%;height:${((c[3] + 2 * m) * 100).toFixed(1)}%`;
  }

  // Os segundos depois do alarme, gravados pelo servidor. So some se a camera nao respondeu.
  function htmlVideos(a) {
    const v = a.videos || {};
    if (!v.termico && !v.visivel) return '';
    const um = (src, rot) => src ? `<figure style="margin:0"><video class="tm-grav" src="${h(src)}" controls muted playsinline preload="metadata"></video><figcaption class="tm-legenda">${rot}</figcaption></figure>` : '';
    return `<div><div class="tm-sub" style="margin-bottom:6px">Vídeo depois do alarme</div><div class="tm-fotos">${um(v.termico, 'Térmica')}${um(v.visivel, 'Colorida')}</div></div>`;
  }

  function htmlDetalhe(a) {
    const [rot, cls] = SIT[a.situacao] || SIT.novo;
    const resp = a.situacao === 'novo' ? '' : `<div class="tm-sub">${a.situacao === 'falso' ? 'Falso alarme' : 'Ciente'} por ${h(a.visto_por || '—')} em ${h(dataHora(a.visto_at))}${a.motivo_falso ? ` · ${h((MOTIVOS.find(m => m[0] === a.motivo_falso) || ['', a.motivo_falso])[1])}` : ''}${a.comentario ? ` · “${h(a.comentario)}”` : ''}</div>`;
    return `
      <div class="tm-linha"><div style="min-width:0"><h2 style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${h(a.camera_nome)} · ${h(a.site)}</h2>
        <div class="tm-sub">${a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada pelo calor'} · ${h(dataHora(a.criado_at))}</div></div><span class="pill ${cls}">${rot}</span></div>
      <div class="tm-fotos">
        <figure style="margin:0"><div class="tm-foto" id="tmFotoT"><div class="tm-vazio">Carregando…</div><div class="tm-caixa" style="${caixaCss(a)}"></div></div><figcaption class="tm-legenda">Térmica</figcaption></figure>
        <figure style="margin:0"><div class="tm-foto" id="tmFotoV"><div class="tm-vazio">${a.fotos.visivel ? 'Carregando…' : 'Sem foto colorida'}</div></div><figcaption class="tm-legenda">Colorida, mesmo instante</figcaption></figure>
      </div>
      ${htmlVideos(a)}
      ${a.mancha?.teste ? `<div class="tm-sub">Gerado na tela para testar os avisos. Não houve detecção: as fotos são da câmera naquele momento.</div>` : `<div class="tm-medidas">
        <div><span>Mancha</span><strong style="color:var(--danger)">${num(a.temp_c)} °C</strong></div>
        <div><span>Fundo</span><strong>${num(a.fundo_c)} °C</strong></div>
        <div><span>Diferença</span><strong>${num(a.dif_c)} °C</strong></div>
        <div><span>Tamanho</span><strong>${a.mancha?.pontos || '—'} pts</strong></div>
      </div>`}
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

  // -------------------------------------------------------------- eventos --
  function ligar(sec) {
    sec.querySelectorAll('[data-tm-aba]').forEach(b => b.onclick = () => { aba = b.dataset.tmAba; if (aba === 'geral') carregarGeral(); render(); });
    sec.querySelectorAll('[data-tm-ver-usina]').forEach(b => b.onclick = () => { filtroUsina = b.dataset.tmVerUsina; aba = 'vivo'; render(); });
    sec.querySelector('[data-tm-esc-salvar]')?.addEventListener('click', salvarEscala);
    sec.querySelector('[data-tm-pdf]')?.addEventListener('click', baixarPdf);
    const busca = $('tmBusca');
    if (busca) busca.oninput = () => { filtro.q = busca.value; const pos = busca.selectionStart; render(); const b = $('tmBusca'); b.focus(); b.setSelectionRange(pos, pos); };
    if ($('tmSite')) $('tmSite').onchange = e => { filtro.site = e.target.value; render(); };
    if ($('tmSit')) $('tmSit').onchange = e => { filtro.situacao = e.target.value; render(); };
    sec.querySelectorAll('[data-tm-alerta]').forEach(tr => tr.onclick = () => { aberto = alertas.alertas.find(a => a.id === tr.dataset.tmAlerta) || null; render(); });
    sec.querySelector('[data-tm-teste-alarme]')?.addEventListener('click', () => gerarTeste($('tmTesteCam')?.value));
    sec.querySelector('[data-tm-ciente]')?.addEventListener('click', () => responder('ciente', {}));
    sec.querySelector('[data-tm-falso]')?.addEventListener('click', pedirMotivo);
    sec.querySelector('[data-tm-fechar]')?.addEventListener('click', () => { aberto = null; render(); });
    ligarAuto(sec);
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

  // ----------------------------------------------------------- automacoes --
  async function carregarAutomacoes() {
    const r = await api('/api/automacoes');
    if (!r || !r.ok) return;
    auto = await r.json();
    if (aba === 'automacoes') render();
  }

  const nomeOrigem = id => (id ? (cams.cameras.find(c => c.id === id)?.nome || 'câmera removida') : 'Todas as térmicas');
  const novaRegra = () => ({ nome: '', ativo: true, modo: 'simular', origem_camera_id: '', intervalo_s: 120, acoes: [] });

  function descrever(a) {
    return a.tipo === 'saida' ? `${a.nome}: saída ${a.saida} por ${a.segundos} s`
      : `${a.nome}: preset ${a.preset}${a.voltar_s ? `, volta em ${a.voltar_s} s` : ''}`;
  }

  function htmlSemAutomacao() {
    const speeds = auto.equipamentos.filter(e => e.speed);
    return `<section class="tm-card tm-vazio-util">
      <h2>O que deve acontecer quando alguém for detectado?</h2>
      <p class="tm-sub" style="margin:0;max-width:560px;text-align:center">As automações agem sozinhas no alarme. Toda automação começa em Simular: registra o que faria, sem mexer em nada.</p>
      <div class="tm-sugestoes">
        ${speeds.map(e => `<button type="button" class="tm-sugestao" data-tm-sug="${h(e.ip)}|${h(e.connector_id)}"><b>Apontar a ${h(e.nome)}</b><span>${h(e.site)} · vai ao preset e volta depois de 60 s</span></button>`).join('')}
        <button type="button" class="tm-sugestao" data-tm-nova><b>Ligar refletor ou sirene</b><span>pela saída de alarme da câmera</span></button>
      </div>
    </section>`;
  }

  function htmlAutomacoes() {
    const linhas = auto.automacoes.map(r => `<tr data-tm-regra="${h(r.id)}" class="${autoAberta && autoAberta.id === r.id ? 'on' : ''}">
        <td title="${h(r.nome)}" style="font-weight:600">${h(r.nome)}</td><td title="${h(nomeOrigem(r.origem_camera_id))}">${h(nomeOrigem(r.origem_camera_id))}</td>
        <td class="tm-num">${r.acoes.length}</td><td><span class="pill ${r.modo === 'valer' ? 'danger' : 'neutral'}">${r.modo === 'valer' ? 'Valendo' : 'Simulando'}</span></td>
        <td>${r.ativo ? 'Ligada' : 'Desligada'}</td></tr>`).join('')
      || '<tr><td colspan="5" style="text-align:center;color:var(--muted);height:80px">Nenhuma automação ainda.</td></tr>';
    const nomes = Object.fromEntries(auto.automacoes.map(r => [r.id, r.nome]));
    const hist = auto.execucoes.slice(0, 15).map(e => {
      let a = {}; try { a = JSON.parse(e.acao); } catch (_) { /* linha antiga */ }
      return `<tr><td>${h(hora(e.criado_at))}</td><td title="${h(nomes[e.automacao_id] || '')}">${h(nomes[e.automacao_id] || '—')}</td>
        <td title="${h(e.resposta)}">${h(a.nome ? descrever(a) : e.resposta)}</td>
        <td><span class="pill ${!e.ok ? 'danger' : e.modo === 'valer' ? 'success' : 'neutral'}">${!e.ok ? 'Falhou' : e.modo === 'valer' ? 'Feito' : 'Simulado'}</span></td></tr>`;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--muted);height:60px">Nada executado ainda.</td></tr>';
    if (!auto.automacoes.length && !autoAberta) return htmlSemAutomacao();
    return `<div class="tm-grid">
      <div style="display:flex;flex-direction:column;gap:20px;min-width:0">
        <section class="tm-card">
          <div class="tm-linha"><h2>Automações</h2><button class="primary-action" type="button" data-tm-nova>Nova automação</button></div>
          <div class="table-wrap"><table class="tm-tab">
            <colgroup><col><col style="width:170px"><col style="width:64px"><col style="width:104px"><col style="width:84px"></colgroup>
            <thead><tr><th>Nome</th><th>Quando detectar em</th><th class="tm-num">Ações</th><th>Modo</th><th>Situação</th></tr></thead>
            <tbody>${linhas}</tbody></table></div>
        </section>
        <section class="tm-card">
          <div class="tm-linha"><h2>Histórico</h2><span class="tm-sub">últimas 15 ações</span></div>
          <div class="table-wrap"><table class="tm-tab">
            <colgroup><col style="width:56px"><col style="width:150px"><col><col style="width:96px"></colgroup>
            <thead><tr><th>Hora</th><th>Automação</th><th>Ação</th><th>Resultado</th></tr></thead>
            <tbody>${hist}</tbody></table></div>
        </section>
      </div>
      <section class="tm-card">${autoAberta ? htmlFormRegra(autoAberta) : '<div class="tm-vazio-card">Clique numa automação ou crie uma nova.</div>'}</section>
    </div>`;
  }

  function htmlAcao(a, i) {
    const lista = auto.equipamentos.filter(e => (a.tipo.startsWith('speed') ? e.speed : true));
    const valor = `${a.ip || ''}|${a.connector_id || ''}`;
    const opcoes = lista.map(e => `<option value="${h(e.ip)}|${h(e.connector_id)}" ${`${e.ip}|${e.connector_id}` === valor ? 'selected' : ''}>${h(e.site)} · ${h(e.nome)}</option>`).join('');
    const num = (k, rot, v, min, max) => `<label class="tm-campo">${rot}<input type="number" min="${min}" max="${max}" data-tm-a="${k}" value="${h(v)}"></label>`;
    return `<div class="tm-acao" data-tm-acao="${i}">
      <div class="tm-linha"><strong style="font-size:13px">Ação ${i + 1}</strong><button class="ghost-action" type="button" data-tm-tirar="${i}" aria-label="Tirar ação ${i + 1}">✕</button></div>
      <div class="tm-regra" style="grid-template-columns:minmax(0,1fr) minmax(0,2fr)">
        <label class="tm-campo">Tipo<select data-tm-a="tipo"><option value="speed_preset" ${a.tipo === 'speed_preset' ? 'selected' : ''}>Speed: preset</option><option value="speed_seguir" ${a.tipo === 'speed_seguir' ? 'selected' : ''}>Speed: seguir o alarme</option><option value="saida" ${a.tipo === 'saida' ? 'selected' : ''}>Saída de alarme</option></select></label>
        <label class="tm-campo">Equipamento<select data-tm-a="alvo"><option value="|">Escolha…</option>${opcoes}</select></label>
      </div>
      <div class="tm-regra" style="grid-template-columns:repeat(2,minmax(0,1fr))">
        ${a.tipo === 'saida'
          ? num('saida', 'Saída', a.saida ?? 1, 1, 16) + num('segundos', 'Ligada por (s)', a.segundos ?? 30, 1, 600)
          : a.tipo === 'speed_seguir'
          ? `<div class="tm-campo">Pontaria<button class="secondary-action" type="button" data-tm-calib="${i}" ${a.ip ? '' : 'disabled title="Escolha a speed"'}>${(a.pontos || []).length === 4 ? 'Calibrada: refazer' : 'Calibrar 4 pontos'}</button></div>` + num('voltar_s', 'Voltar depois de (s, 0 = fica)', a.voltar_s ?? 60, 0, 3600)
          : num('preset', 'Preset', a.preset ?? 1, 1, 300) + num('voltar_s', 'Voltar depois de (s, 0 = fica)', a.voltar_s ?? 60, 0, 3600)}
      </div></div>`;
  }

  function htmlFormRegra(r) {
    return `<div class="tm-linha"><h2>${r.id ? 'Automação' : 'Nova automação'}</h2>
        <label class="tm-linha" style="gap:8px;font-size:13px"><input type="checkbox" id="tmRAtivo" ${r.ativo ? 'checked' : ''}> Ligada</label></div>
      <label class="tm-campo">Nome<input id="tmRNome" maxlength="120" value="${h(r.nome)}" placeholder="Ex.: Speed olha a cerca"></label>
      <div class="tm-regra" style="grid-template-columns:minmax(0,2fr) minmax(0,1fr)">
        <label class="tm-campo">Quando detectar em<select id="tmROrigem"><option value="">Todas as térmicas</option>${cams.cameras.map(c => `<option value="${h(c.id)}" ${c.id === r.origem_camera_id ? 'selected' : ''}>${h(c.site)} · ${h(c.nome)}</option>`).join('')}</select></label>
        <label class="tm-campo">Intervalo (s)<input type="number" min="10" max="3600" id="tmRIntervalo" value="${h(r.intervalo_s)}"></label>
      </div>
      ${r.acoes.map(htmlAcao).join('')}
      <button class="secondary-action" type="button" data-tm-mais>Adicionar ação</button>
      <label class="tm-campo">Modo<select id="tmRModo"><option value="simular" ${r.modo !== 'valer' ? 'selected' : ''}>Simular: só registra, não aciona nada</option><option value="valer" ${r.modo === 'valer' ? 'selected' : ''}>Valendo: aciona o equipamento do cliente</option></select></label>
      ${r.modo === 'valer' ? '<div class="pill danger" style="white-space:normal;line-height:1.4;padding:8px 10px">Valendo: a cada alerta o equipamento é acionado de verdade.</div>' : ''}
      <div class="tm-acoes">
        <button class="primary-action" type="button" data-tm-rsalvar>Salvar</button>
        <button class="secondary-action" type="button" data-tm-rtestar ${r.id ? '' : 'disabled title="Salve antes de testar"'}>Testar agora</button>
        <button class="secondary-action danger-action" type="button" data-tm-rexcluir ${r.id ? '' : 'disabled'}>Excluir</button>
      </div>`;
  }

  // Le o formulario para autoAberta antes de redesenhar: nao perde o digitado.
  function lerForm() {
    if (!autoAberta || !$('tmRNome')) return;
    autoAberta.nome = $('tmRNome').value;
    autoAberta.ativo = $('tmRAtivo').checked;
    autoAberta.modo = $('tmRModo').value;
    autoAberta.origem_camera_id = $('tmROrigem').value;
    autoAberta.intervalo_s = Number($('tmRIntervalo').value || 120);
    secao().querySelectorAll('[data-tm-acao]').forEach(box => {
      const a = autoAberta.acoes[Number(box.dataset.tmAcao)];
      box.querySelectorAll('[data-tm-a]').forEach(i => {
        const k = i.dataset.tmA;
        if (k === 'alvo') {
          const [ip, cid] = i.value.split('|');
          const e = auto.equipamentos.find(x => x.ip === ip && x.connector_id === cid);
          a.ip = ip; a.connector_id = cid; a.nome = e ? e.nome : '';
        } else if (k === 'tipo') a.tipo = i.value;
        else a[k] = Number(i.value);
      });
    });
  }

  function ligarAuto(sec) {
    sec.querySelector('[data-tm-nova]')?.addEventListener('click', () => { autoAberta = novaRegra(); render(); });
    sec.querySelectorAll('[data-tm-sug]').forEach(b => b.onclick = () => {
      const e = auto.equipamentos.find(x => `${x.ip}|${x.connector_id}` === b.dataset.tmSug);
      if (!e) return;
      const cam = cams.cameras.find(c => c.site === e.site && c.ativo);
      autoAberta = { ...novaRegra(), nome: `Apontar ${e.nome}`, origem_camera_id: cam?.id || '',
        acoes: [{ tipo: 'speed_preset', ip: e.ip, connector_id: e.connector_id, nome: e.nome, preset: 1, voltar_s: 60 }] };
      render();
    });
    sec.querySelectorAll('[data-tm-regra]').forEach(tr => tr.onclick = () => {
      const r = auto.automacoes.find(x => x.id === tr.dataset.tmRegra);
      autoAberta = r ? JSON.parse(JSON.stringify(r)) : null; render();
    });
    sec.querySelector('[data-tm-mais]')?.addEventListener('click', () => { lerForm(); autoAberta.acoes.push({ tipo: 'speed_preset', ip: '', connector_id: '' }); render(); });
    sec.querySelectorAll('[data-tm-calib]').forEach(b => b.onclick = () => { lerForm(); abrirCalibracao(Number(b.dataset.tmCalib)); });
    sec.querySelectorAll('[data-tm-tirar]').forEach(b => b.onclick = () => { lerForm(); autoAberta.acoes.splice(Number(b.dataset.tmTirar), 1); render(); });
    sec.querySelectorAll('[data-tm-a="tipo"]').forEach(s => s.onchange = () => { lerForm(); render(); });
    if ($('tmRModo')) $('tmRModo').onchange = () => { lerForm(); render(); };
    sec.querySelector('[data-tm-rsalvar]')?.addEventListener('click', salvarAutomacao);
    sec.querySelector('[data-tm-rtestar]')?.addEventListener('click', testarAutomacao);
    sec.querySelector('[data-tm-rexcluir]')?.addEventListener('click', excluirAutomacao);
  }

  async function salvarAutomacao() {
    lerForm();
    const r = await api(autoAberta.id ? `/api/automacoes/${encodeURIComponent(autoAberta.id)}` : '/api/automacoes',
      { method: autoAberta.id ? 'PUT' : 'POST', body: JSON.stringify(autoAberta) });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para salvar.', true); return; }
    autoAberta = await r.json();
    toast('Automação salva.');
    await carregarAutomacoes();
  }

  async function testarAutomacao() {
    if (!autoAberta?.id) return;
    if (autoAberta.modo === 'valer' && !confirm('Esta automação está valendo: o equipamento do cliente será acionado agora. Continuar?')) return;
    const r = await api(`/api/automacoes/${encodeURIComponent(autoAberta.id)}/testar`, { method: 'POST', body: '{}' });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para testar.', true); return; }
    auto = await r.json();
    toast('Teste feito: veja o histórico.');
    render();
  }

  async function excluirAutomacao() {
    if (!autoAberta?.id || !confirm(`Excluir a automação ${autoAberta.nome}?`)) return;
    const r = await api(`/api/automacoes/${encodeURIComponent(autoAberta.id)}`, { method: 'DELETE', body: '' });
    if (!r || !r.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'Não deu para excluir.', true); return; }
    autoAberta = null;
    await carregarAutomacoes();
  }

  // -------------------------------------------------------------- ao vivo --
  // Parede no padrao do PDV (.pdv-v-*), com o player do sistema. O laco de 10 s
  // so troca textos e classes (pintarVivo): recriar a tela derrubaria os videos.
  const SENS = {
    Pouca: { dif_min: 8, pontos_min: 30, quadros_seguidos: 3, dica: 'Só avisa com pessoa bem visível. Menos alarme falso, pode perder quem passa longe.' },
    Normal: { dif_min: 5, pontos_min: 12, quadros_seguidos: 2, dica: 'Pessoa inteira na área. Serve para quase todas as câmeras.' },
    Muita: { dif_min: 3, pontos_min: 6, quadros_seguidos: 2, dica: 'Avisa também com pessoa pequena ou longe. Pode disparar com animal.' },
  };
  const NOITE = ['18:00', '06:00'];
  const PAREDE_MAX_VIDEOS = 12;   // mais que isso pesa no link: os outros abrem ao clicar
  const players = new Map();
  let gavPlayers = [], testeTimer = null, escGaveta = null;
  let vista = 'termica', filtroUsina = '', paredeChave = '';
  let gaveta = null;   // { tipo: 'alarme'|'config', cam, alerta }
  let cfg = null;      // formulario da gaveta de configurar

  const idCam = c => `${c.ip}|${c.connector_id || ''}`;
  const domId = c => idCam(c).replace(/[^a-zA-Z0-9]/g, '_');

  function todasCams() {
    const fora = (cams.no_inventario || []).map(n => ({ ...n, fora: true, ativo: false, pendentes: 0, leitura: '', fundo_c: null }));
    return [...cams.cameras, ...fora]
      .filter(c => !filtroUsina || c.site === filtroUsina)
      .sort((a, b) => natural(a.site, b.site) || natural(a.nome, b.nome));
  }

  function situacao(c) {
    if (c.pendentes) return ['PESSOA', 'tm-sit-alarme'];
    if (!c.ativo) return ['Sem vigiar', 'tm-sit-fora'];
    if (c.leitura === 'erro') return ['Sem medição', 'tm-sit-aviso'];
    return c.armado_agora ? ['Vigiando', 'tm-sit-ok'] : ['Fora do horário', 'tm-sit-fora'];
  }

  const quandoDe = c => (!c.armado_de ? 'Sempre' : (c.armado_de === NOITE[0] && c.armado_ate === NOITE[1] ? 'Só à noite' : 'Escolher horário'));
  function sensDe(r) {
    const n = Object.keys(SENS).find(k => ['dif_min', 'pontos_min', 'quadros_seguidos'].every(f => Number(r?.[f]) === SENS[k][f]));
    return n || 'Personalizada';
  }

  const rotuloSens = r => (r?.perfis?.length ? 'Por horário' : sensDe(r));

  function pararPlayers() { players.forEach(p => { try { p.stop(); } catch (_) { /* ja parado */ } }); players.clear(); paredeChave = ''; }
  function pararGaveta() {
    gavPlayers.forEach(p => { try { p.stop(); } catch (_) { /* ja parado */ } });
    gavPlayers = [];
    clearInterval(testeTimer); testeTimer = null;
    if (escGaveta) document.removeEventListener('keydown', escGaveta);
    escGaveta = null;
    $('tmGaveta')?.remove();
  }

  function tocar(video, c, tipo, alta, aviso) {
    if (!video || typeof mountLiveStream !== 'function') return null;
    return mountLiveStream(video, {
      ip: c.ip, user: 'admin', pass: '', subtype: alta ? 0 : 1, connectorId: c.connector_id,
      registrar: async () => {
        const r = await api('/api/termico/vivo', { method: 'POST', body: JSON.stringify({ ip: c.ip, connector_id: c.connector_id, tipo, alta }) });
        const j = await r?.json().catch(() => ({}));
        if (!r?.ok || !j?.stream_name) throw new Error(j?.detail || 'não consegui abrir o vídeo');
        return j.stream_name;
      },
      onStatus: t => { if (aviso) { aviso.hidden = !t; if (t) aviso.textContent = textoVideo(t); } },
    });
  }

  // Erro cru do go2rtc tem endereco e senha de stream: nao vai para a tela.
  const textoVideo = t => (String(t).length > 60 || /go2rtc|rtsp|dial tcp|error/i.test(t) ? 'Câmera sem resposta. Tentando de novo…' : t);

  function htmlFaixa() {
    const a = alertas.alertas.find(x => x.situacao === 'novo');
    const ativas = cams.cameras.filter(c => c.ativo).length;
    if (a) return `<div class="tm-faixa alarme"><span class="tm-ponto"></span>${a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada'}: ${h(a.camera_nome)} · ${h(a.site)} <small>${h(hora(a.criado_at))}${a.mancha?.teste ? '' : `, ${num(a.temp_c, 0)} °C num fundo de ${num(a.fundo_c, 0)} °C`}</small>
      <button class="secondary-action" type="button" data-tm-ver-alarme="${h(a.id)}" style="margin-left:auto">Ver ao vivo</button></div>`;
    const ult = alertas.alertas[0];
    return `<div class="tm-faixa"><span class="tm-ponto"></span>${ativas ? 'Tudo tranquilo' : 'Nenhuma câmera vigiando'} <small>${ativas} térmica(s) vigiando · nenhum alarme sem resposta${ult ? ` · último alarme ${h(dataHora(ult.criado_at))}` : ''}</small></div>`;
  }

  function htmlLado() {
    const itens = alertas.alertas.slice(0, 6).map(a => `<button type="button" class="tm-ev" data-tm-ver-alarme="${h(a.id)}"><span>${h(hora(a.criado_at))}</span>
      <span><b>${h((SIT[a.situacao] || SIT.novo)[0])}: ${h(a.camera_nome)}</b>${h(a.site)}</span></button>`).join('');
    return `<h2>Acontecendo agora</h2>${itens || '<p class="tm-sub" style="margin:0">Nenhum alarme ainda. Quando a câmera detectar alguém, aparece aqui.</p>'}`;
  }

  function htmlTile(c, i) {
    const [sit, cls] = situacao(c);
    const id = domId(c);
    return `<article class="pdv-v-tile ${c.pendentes ? 'tm-alarme' : ''}" id="tmT-${id}">
      <button type="button" class="pdv-v-video tm-abrir" data-tm-abrir="${h(idCam(c))}" aria-label="Abrir ${h(c.nome)} ao vivo">
        ${i < PAREDE_MAX_VIDEOS ? `<video id="tmV-${id}" autoplay muted playsinline></video>` : ''}
        <span class="pdv-v-aviso" id="tmA-${id}">${i < PAREDE_MAX_VIDEOS ? 'Conectando...' : 'clique para ver ao vivo'}</span>
        <span class="pdv-v-lbl pdv-v-nome">${h(c.nome)}</span>
        <span class="pdv-v-lbl pdv-v-sit ${cls}" data-sit>${h(sit)}</span>
        <span class="pdv-v-lbl tm-l-vivo"><i class="tm-vivo"></i>AO VIVO</span>
        <span class="pdv-v-lbl tm-l-temp" data-temp ${c.fundo_c == null ? 'hidden' : ''}>${c.fundo_c == null ? '' : `${num(c.fundo_c, 0)} °C`}</span>
      </button>
      <div class="tm-tile-pe"><span data-pe>${c.ativo ? `${h(quandoDe(c))} · ${h(rotuloSens(c.regra))}` : 'Só vídeo'}</span>
        <button type="button" class="pdv-l-link" data-tm-config="${h(idCam(c))}">${c.ativo || c.id ? 'Configurar' : 'Vigiar'}</button></div>
    </article>`;
  }

  function htmlVivo() {
    const lista = todasCams();
    const sites = [...new Set([...cams.cameras, ...(cams.no_inventario || [])].map(c => c.site))].sort(natural);
    const grupos = sites.filter(s => !filtroUsina || s === filtroUsina).map(s => {
      const dela = lista.filter(c => c.site === s);
      const paradas = dela.filter(c => !c.ativo);
      return { s, dela, paradas };
    });
    let n = 0;
    const blocos = grupos.map(g => `<section class="tm-usina">
      <div class="tm-linha"><h2>${h(g.s || '(sem local)')} <span class="tm-sub" style="font-weight:400">· ${g.dela.length - g.paradas.length} vigiando${g.paradas.length ? ` · ${g.paradas.length} sem vigiar` : ''}</span></h2>
        ${g.paradas.length ? `<button class="secondary-action pdv-mini" type="button" data-tm-vigiar-usina="${h(g.s)}">Vigiar as ${g.paradas.length} desta usina</button>` : ''}</div>
      <div class="tm-tiles">${g.dela.map(c => htmlTile(c, n++)).join('')}</div></section>`).join('');
    return `<div id="tmFaixa">${htmlFaixa()}</div>
      <div class="tm-ferr">
        <div class="tm-seg" role="tablist" aria-label="Imagem">
          <button type="button" class="${vista === 'termica' ? 'on' : ''}" data-tm-vista="termica">Térmica</button>
          <button type="button" class="${vista === 'colorida' ? 'on' : ''}" data-tm-vista="colorida">Colorida</button>
        </div>
        <select id="tmUsina" class="tm-sel" aria-label="Usina"><option value="">Todas as usinas (${sites.length})</option>${sites.map(s => `<option value="${h(s)}" ${s === filtroUsina ? 'selected' : ''}>${h(s)}</option>`).join('')}</select>
      </div>
      <div class="tm-parede-grade">
        <div class="tm-parede">${blocos || '<div class="tm-vazio-card">Nenhuma câmera térmica no inventário deste cliente.</div>'}</div>
        <aside class="tm-lado" id="tmLado" aria-label="Acontecendo agora">${htmlLado()}</aside>
      </div>
      <p class="tm-sub">Na parede o vídeo vai leve para poupar o link da usina. Clique numa câmera para ver grande.</p>`;
  }

  function montarParede() {
    const lista = todasCams();
    paredeChave = lista.map(idCam).join(',') + vista + filtroUsina;
    lista.slice(0, PAREDE_MAX_VIDEOS).forEach(c => {
      const id = domId(c);
      const p = tocar($(`tmV-${id}`), c, vista, false, $(`tmA-${id}`));
      if (p) players.set(id, p);
    });
  }

  // so troca textos e classes: os videos continuam tocando
  function pintarVivo() {
    const faixa = $('tmFaixa');
    if (faixa) { faixa.innerHTML = htmlFaixa(); ligarAlarmes(faixa); }
    const lado = $('tmLado');
    if (lado) { lado.innerHTML = htmlLado(); ligarAlarmes(lado); }
    todasCams().forEach(c => {
      const t = $(`tmT-${domId(c)}`);
      if (!t) return;
      const [sit, cls] = situacao(c);
      t.classList.toggle('tm-alarme', !!c.pendentes);
      const s = t.querySelector('[data-sit]');
      if (s) { s.textContent = sit; s.className = `pdv-v-lbl pdv-v-sit ${cls}`; }
      const temp = t.querySelector('[data-temp]');
      if (temp) { temp.hidden = c.fundo_c == null; temp.textContent = c.fundo_c == null ? '' : `${num(c.fundo_c, 0)} °C`; }
      const pe = t.querySelector('[data-pe]');
      if (pe) pe.textContent = c.ativo ? `${quandoDe(c)} · ${rotuloSens(c.regra)}` : 'Só vídeo';
    });
  }

  function ligarAlarmes(raiz) {
    raiz.querySelectorAll('[data-tm-ver-alarme]').forEach(b => b.onclick = () => {
      const a = alertas.alertas.find(x => x.id === b.dataset.tmVerAlarme);
      if (a) abrirAlarme(a);
    });
  }

  function ligarVivo(sec) {
    ligarAlarmes(sec);
    sec.querySelectorAll('[data-tm-vista]').forEach(b => b.onclick = () => { vista = b.dataset.tmVista; render(); });
    if ($('tmUsina')) $('tmUsina').onchange = e => { filtroUsina = e.target.value; render(); };
    const achar = k => [...cams.cameras, ...(cams.no_inventario || [])].find(c => idCam(c) === k);
    sec.querySelectorAll('[data-tm-abrir]').forEach(b => b.onclick = () => {
      const c = achar(b.dataset.tmAbrir);
      if (!c) return;
      const a = c.id && alertas.alertas.find(x => x.camera_id === c.id && x.situacao === 'novo');
      if (a) abrirAlarme(a); else abrirConfig(c);
    });
    sec.querySelectorAll('[data-tm-config]').forEach(b => b.onclick = () => { const c = achar(b.dataset.tmConfig); if (c) abrirConfig(c); });
    sec.querySelectorAll('[data-tm-vigiar-usina]').forEach(b => b.onclick = () => vigiarUsina(b.dataset.tmVigiarUsina));
  }

  function montarGaveta(html) {
    pararGaveta();
    const g = document.createElement('div');
    g.id = 'tmGaveta';
    g.innerHTML = `<div class="tm-fundo"></div><section class="tm-gaveta" role="dialog">${html}</section>`;
    document.body.appendChild(g);
    // Fecha so por X, Fechar ou Esc: clicar fora perderia o que foi feito.
    escGaveta = e => { if (e.key === 'Escape') pararGaveta(); };
    document.addEventListener('keydown', escGaveta);
    g.querySelectorAll('[data-tm-gfechar]').forEach(b => b.onclick = pararGaveta);
    return g;
  }

  // ------------------------------------------------------- gaveta do alarme
  function abrirAlarme(a) {
    const cam = cams.cameras.find(c => c.id === a.camera_id);
    const speed = auto.automacoes.flatMap(r => (r.origem_camera_id === a.camera_id || !r.origem_camera_id) ? r.acoes : []).find(x => x.tipo.startsWith('speed'));
    const novo = a.situacao === 'novo';
    const g = montarGaveta(`
      <div class="tm-gav-cab"><div style="min-width:0;flex:1"><h2 style="color:var(--danger)">${a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada pelo calor'}</h2>
        <div class="tm-sub">${h(a.camera_nome)} · ${h(a.site)} · ${h(dataHora(a.criado_at))}</div></div>
        <button class="ghost-action" type="button" data-tm-gfechar aria-label="Fechar">✕</button></div>
      <div class="tm-gav-corpo">
        <div class="tm-fotos">
          <div class="tm-foto"><video id="tmGvT" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmGaT">Conectando...</span><span class="pdv-v-lbl pdv-v-nome">Térmica</span><span class="pdv-v-lbl tm-l-vivo"><i class="tm-vivo"></i>AO VIVO</span></div>
          <div class="tm-foto"><video id="tmGvC" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmGaC">Conectando...</span><span class="pdv-v-lbl pdv-v-nome">Colorida</span><span class="pdv-v-lbl tm-l-vivo"><i class="tm-vivo"></i>AO VIVO</span></div>
        </div>
        ${speed ? `<div class="tm-foto"><video id="tmGvS" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmGaS">Conectando...</span><span class="pdv-v-lbl pdv-v-nome">${h(speed.nome)}</span><span class="pdv-v-lbl tm-l-vivo"><i class="tm-vivo"></i>AO VIVO</span></div>` : ''}
        ${a.mancha?.teste ? `<div class="tm-sub">Gerado na tela para testar os avisos. Não houve detecção.</div>` : `<div class="tm-medidas">
          <div><span>Pessoa</span><strong style="color:var(--danger)">${num(a.temp_c)} °C</strong></div>
          <div><span>Fundo</span><strong>${num(a.fundo_c)} °C</strong></div>
          <div><span>Diferença</span><strong>${num(Math.abs(a.dif_c || 0))} °C</strong></div>
          <div><span>Tamanho</span><strong>${a.mancha?.pontos || '—'} pts</strong></div>
        </div>`}
        <div><div class="tm-sub" style="margin-bottom:6px">Momento do disparo</div>
          <div class="tm-fotos"><div class="tm-foto" id="tmFotoT"><div class="tm-vazio">Carregando…</div><div class="tm-caixa" style="${caixaCss(a)}"></div></div>
            <div class="tm-foto" id="tmFotoV"><div class="tm-vazio">${a.fotos.visivel ? 'Carregando…' : 'Sem foto colorida'}</div></div></div></div>
        ${htmlVideos(a)}
        ${novo ? '' : `<div class="tm-sub">${a.situacao === 'falso' ? 'Falso alarme' : 'Ciente'} por ${h(a.visto_por || '—')} em ${h(dataHora(a.visto_at))}</div>`}
      </div>
      <div class="tm-gav-pe">${novo ? `<button class="primary-action" type="button" data-tm-gciente style="flex:1;justify-content:center">Ciente</button>
        <button class="secondary-action" type="button" data-tm-gfalso style="color:var(--amber)">Falso alarme</button>` : ''}
        <button class="secondary-action" type="button" data-tm-gfechar>Fechar</button></div>`);
    aberto = a;
    if (cam) {
      gavPlayers.push(tocar($('tmGvT'), cam, 'termica', true, $('tmGaT')));
      gavPlayers.push(tocar($('tmGvC'), cam, 'colorida', false, $('tmGaC')));
    } else { $('tmGaT').textContent = 'câmera removida'; $('tmGaC').textContent = 'câmera removida'; }
    if (speed) gavPlayers.push(tocar($('tmGvS'), speed, 'colorida', true, $('tmGaS')));
    gavPlayers = gavPlayers.filter(Boolean);
    carregarFotos(a);
    g.querySelector('[data-tm-gciente]')?.addEventListener('click', async () => { await responder('ciente', {}); pararGaveta(); });
    g.querySelector('[data-tm-gfalso]')?.addEventListener('click', pedirMotivo);
  }

  // ----------------------------------------------------- gaveta de configurar
  const ret = p => {
    const xs = p.map(q => q[0]), ys = p.map(q => q[1]);
    return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
  };
  const pol = r => [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1]];
  const estilo = r => `left:${r.x0 * 100}%;top:${r.y0 * 100}%;width:${(r.x1 - r.x0) * 100}%;height:${(r.y1 - r.y0) * 100}%`;

  function desenhoHtml() {
    const tirar = (tipo, i) => `<button type="button" class="tm-tirar-reg" data-tm-tira="${tipo}:${i}" aria-label="Tirar">✕</button>`;
    return `${cfg.areas.map((r, i) => `<div class="tm-area" style="${estilo(r)}"><span>Área ${i + 1}</span>${tirar('areas', i)}</div>`).join('')}
      ${cfg.ignorar.map((r, i) => `<div class="tm-ignorar" style="${estilo(r)}"><span>Ignorar</span>${tirar('ignorar', i)}</div>`).join('')}`;
  }

  // Faixa de horario: Variacao e o quanto a mancha precisa fugir do fundo, em graus.
  const PERFIS_PADRAO = [['18:00', '06:00', 'Muita'], ['06:00', '10:00', 'Pouca'], ['10:00', '18:00', 'Normal']];
  const perfilDe = (de, ate, nome) => ({ de, ate, dif_min: SENS[nome].dif_min, pontos_min: SENS[nome].pontos_min, quadros_seguidos: SENS[nome].quadros_seguidos });

  function htmlPerfis() {
    const linhas = cfg.perfis.map((p, i) => {
      const s = sensDe(p);
      return `<div class="tm-perfil" data-tm-p="${i}">
        <label class="tm-campo">Das<input type="time" data-tm-pc="de" value="${h(p.de)}"></label>
        <label class="tm-campo">Até<input type="time" data-tm-pc="ate" value="${h(p.ate)}"></label>
        <label class="tm-campo">Sensibilidade<select data-tm-ps>${['Pouca', 'Normal', 'Muita'].map(n => `<option ${n === s ? 'selected' : ''}>${n}</option>`).join('')}${s === 'Personalizada' ? '<option selected>Personalizada</option>' : ''}</select></label>
        <label class="tm-campo">Variação (°C)<input type="number" min="1" max="40" step="0.5" data-tm-pc="dif_min" value="${h(p.dif_min ?? 5)}"></label>
        <button class="ghost-action" type="button" data-tm-ptira="${i}" aria-label="Tirar faixa">✕</button>
      </div>`;
    }).join('');
    return `${linhas}<div><button class="secondary-action" type="button" data-tm-pmais>Adicionar faixa</button></div>
      <span class="tm-sub">Variação é quanto a mancha precisa fugir do fundo. Fora das faixas vale ${h(cfg.sens === 'Personalizada' ? 'o ajuste avançado' : cfg.sens)}.</span>`;
  }

  function perguntas() {
    const chips = (lista, atual, attr) => lista.map(n => `<button type="button" class="${n === atual ? 'on' : ''}" ${attr}="${h(n)}">${h(n)}</button>`).join('');
    return `<div class="tm-perg"><b>2. Quando vigiar?</b><div class="tm-chips">${chips(['Sempre', 'Só à noite', 'Escolher horário'], cfg.quando, 'data-tm-q')}</div>
        ${cfg.quando === 'Escolher horário' ? `<div class="tm-regra"><label class="tm-campo">Das<input type="time" id="tmDe" value="${h(cfg.de)}"></label><label class="tm-campo">até<input type="time" id="tmAte" value="${h(cfg.ate)}"></label><span></span></div>` : ''}</div>
      <div class="tm-perg"><b>3. Com que sensibilidade?</b><div class="tm-chips">${chips(['Igual o dia todo', 'Muda por horário'], cfg.porHorario ? 'Muda por horário' : 'Igual o dia todo', 'data-tm-h')}</div>
        ${cfg.porHorario ? htmlPerfis() : `<div class="tm-chips">${chips(['Pouca', 'Normal', 'Muita'], cfg.sens, 'data-tm-s')}</div>
        <span class="tm-sub">${h(SENS[cfg.sens]?.dica || 'Ajustada à mão em Ajustes avançados.')}</span>`}</div>
      <details class="tm-avancado"><summary>Ajustes avançados</summary>
        <div class="tm-regra" style="margin-top:10px">${CAMPOS.map(([k, rot, passo]) => `<label class="tm-campo">${rot}<input type="number" step="${passo}" data-tm-campo="${k}" value="${h(cfg.regra[k])}"></label>`).join('')}</div></details>`;
  }

  function ligarPerguntas(g) {
    const box = g.querySelector('#tmPerguntas');
    box.querySelectorAll('[data-tm-q]').forEach(b => b.onclick = () => { lerAvancado(); cfg.quando = b.dataset.tmQ; pintarPerguntas(g); });
    box.querySelectorAll('[data-tm-h]').forEach(b => b.onclick = () => {
      lerAvancado();
      cfg.porHorario = b.dataset.tmH === 'Muda por horário';
      if (cfg.porHorario && !cfg.perfis.length) cfg.perfis = PERFIS_PADRAO.map(([de, ate, n]) => perfilDe(de, ate, n));
      pintarPerguntas(g);
    });
    box.querySelectorAll('[data-tm-ps]').forEach(s => s.onchange = () => {
      lerAvancado();
      const i = Number(s.closest('[data-tm-p]').dataset.tmP);
      if (SENS[s.value]) { const p = cfg.perfis[i]; cfg.perfis[i] = { ...p, ...perfilDe(p.de, p.ate, s.value) }; }
      pintarPerguntas(g);
    });
    box.querySelectorAll('[data-tm-pc="dif_min"]').forEach(i => i.onchange = () => { lerAvancado(); pintarPerguntas(g); });
    box.querySelectorAll('[data-tm-ptira]').forEach(b => b.onclick = () => { lerAvancado(); cfg.perfis.splice(Number(b.dataset.tmPtira), 1); if (!cfg.perfis.length) cfg.porHorario = false; pintarPerguntas(g); });
    box.querySelector('[data-tm-pmais]')?.addEventListener('click', () => { lerAvancado(); cfg.perfis.push(perfilDe('', '', 'Normal')); pintarPerguntas(g); });
    box.querySelectorAll('[data-tm-s]').forEach(b => b.onclick = () => {
      cfg.sens = b.dataset.tmS;
      Object.assign(cfg.regra, { dif_min: SENS[cfg.sens].dif_min, pontos_min: SENS[cfg.sens].pontos_min, quadros_seguidos: SENS[cfg.sens].quadros_seguidos });
      pintarPerguntas(g);
    });
  }
  function pintarPerguntas(g) { g.querySelector('#tmPerguntas').innerHTML = perguntas(); ligarPerguntas(g); }
  function lerAvancado() {
    if ($('tmDe')) { cfg.de = $('tmDe').value; cfg.ate = $('tmAte').value; }
    $('tmGaveta')?.querySelectorAll('[data-tm-campo]').forEach(i => { if (i.value !== '') cfg.regra[i.dataset.tmCampo] = Number(i.value); });
    $('tmGaveta')?.querySelectorAll('[data-tm-pc]').forEach(i => {
      const p = cfg.perfis[Number(i.closest('[data-tm-p]').dataset.tmP)];
      if (p) p[i.dataset.tmPc] = i.type === 'number' ? Number(i.value) : i.value;
    });
    cfg.sens = sensDe(cfg.regra);
  }

  function ligarDesenho(g) {
    const pl = g.querySelector('#tmDesenho');
    const camada = g.querySelector('#tmCamada');
    let ini = null;
    const ponto = e => {
      const b = pl.getBoundingClientRect();
      return { x: Math.min(1, Math.max(0, (e.clientX - b.left) / b.width)), y: Math.min(1, Math.max(0, (e.clientY - b.top) / b.height)) };
    };
    const atual = (e) => { const p = ponto(e); return { x0: Math.min(ini.x, p.x), y0: Math.min(ini.y, p.y), x1: Math.max(ini.x, p.x), y1: Math.max(ini.y, p.y) }; };
    pl.onpointerdown = e => {
      const x = e.target.closest('[data-tm-tira]');
      if (x) { const [tipo, i] = x.dataset.tmTira.split(':'); cfg[tipo].splice(Number(i), 1); camada.innerHTML = desenhoHtml(); return; }
      ini = ponto(e); pl.setPointerCapture(e.pointerId);
    };
    pl.onpointermove = e => {
      if (!ini) return;
      camada.innerHTML = desenhoHtml() + `<div class="${cfg.modo === 'area' ? 'tm-area' : 'tm-ignorar'}" style="${estilo(atual(e))}"></div>`;
    };
    pl.onpointerup = e => {
      if (!ini) return;
      const r = atual(e);
      ini = null;
      if (r.x1 - r.x0 > 0.03 && r.y1 - r.y0 > 0.03) {
        (cfg.modo === 'area' ? cfg.areas : cfg.ignorar).push(r);
      }
      camada.innerHTML = desenhoHtml();
    };
    g.querySelectorAll('[data-tm-modo]').forEach(b => b.onclick = () => {
      cfg.modo = b.dataset.tmModo;
      g.querySelectorAll('[data-tm-modo]').forEach(x => x.classList.toggle('on', x === b));
    });
    g.querySelector('[data-tm-limpar]').onclick = () => { cfg.areas = []; cfg.ignorar = []; camada.innerHTML = desenhoHtml(); };
  }

  function abrirConfig(c) {
    const r = c.regra || {};
    cfg = {
      cam: c, modo: 'area', regra: { ...r }, sens: c.id ? sensDe(r) : 'Normal',
      perfis: (r.perfis || []).map(p => ({ ...p })), porHorario: !!r.perfis?.length,
      areas: (r.areas || []).map(ret), ignorar: (r.ignorar || []).map(ret),
      quando: c.id ? quandoDe(c) : 'Só à noite', de: c.armado_de || '', ate: c.armado_ate || '',
    };
    if (!c.id) Object.assign(cfg.regra, { dif_min: 5, pontos_min: 12, quadros_seguidos: 2, corpo_min: 25, corpo_max: 40, intervalo_alertas_s: 60 });
    const g = montarGaveta(`
      <div class="tm-gav-cab"><div style="min-width:0;flex:1"><h2>${c.ativo ? 'Configurar' : 'Vigiar'} ${h(c.nome)}</h2>
        <div class="tm-sub">${h(c.site)} · ${h(c.modelo || '')}</div></div>
        <button class="ghost-action" type="button" data-tm-gfechar aria-label="Fechar">✕</button></div>
      <div class="tm-gav-corpo">
        ${c.leitura === 'erro' ? `<div class="tm-alerta-msg">Sem medição: ${h(c.leitura_erro)}</div>` : ''}
        <div class="tm-perg"><b>1. Onde vigiar?</b>
          <div class="tm-foto tm-desenho" id="tmDesenho"><video id="tmGvT" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmGaT">Conectando...</span>
            <div id="tmCamada" class="tm-camada">${desenhoHtml()}</div><div id="tmManchas" class="tm-camada"></div>
            <span class="pdv-v-lbl tm-l-vivo"><i class="tm-vivo"></i>AO VIVO</span><span class="tm-dica">Arraste no vídeo. Pode marcar várias áreas</span></div>
          <div class="tm-chips"><button type="button" class="on" data-tm-modo="area">Marcar área</button><button type="button" data-tm-modo="ignorar">Marcar o que ignorar</button><button type="button" data-tm-limpar>Imagem inteira</button></div>
        </div>
        <div id="tmPerguntas" style="display:flex;flex-direction:column;gap:14px">${perguntas()}</div>
        <div class="tm-sub" id="tmTesteTxt" hidden></div>
      </div>
      <div class="tm-gav-pe">
        <button class="primary-action" type="button" data-tm-gsalvar style="flex:1;justify-content:center">${c.ativo ? 'Salvar' : 'Vigiar esta câmera'}</button>
        ${c.ativo ? '<button class="secondary-action" type="button" data-tm-gteste>Testar agora</button><button class="secondary-action" type="button" data-tm-gsim>Simular pessoa</button><button class="secondary-action" type="button" data-tm-gcopiar>Copiar para a usina</button>' : ''}
        ${c.id ? `<button class="secondary-action danger-action" type="button" data-tm-gparar>${c.ativo ? 'Parar de vigiar' : 'Remover'}</button>` : ''}
      </div>`);
    const p = tocar($('tmGvT'), c, 'termica', true, $('tmGaT'));
    if (p) gavPlayers.push(p);
    ligarDesenho(g);
    ligarPerguntas(g);
    g.querySelector('[data-tm-gsalvar]').onclick = salvarConfig;
    g.querySelector('[data-tm-gteste]')?.addEventListener('click', e => alternarTeste(e.currentTarget));
    g.querySelector('[data-tm-gsim]')?.addEventListener('click', simularPessoa);
    g.querySelector('[data-tm-gcopiar]')?.addEventListener('click', copiarUsina);
    g.querySelector('[data-tm-gparar]')?.addEventListener('click', pararDeVigiar);
  }

  function corpoRegra() {
    lerAvancado();
    const q = cfg.quando;
    const [de, ate] = q === 'Sempre' ? ['', ''] : q === 'Só à noite' ? NOITE : [cfg.de, cfg.ate];
    const regra = {};
    CAMPOS.forEach(([k]) => { if (cfg.regra[k] !== undefined && cfg.regra[k] !== '') regra[k] = Number(cfg.regra[k]); });
    regra.perfis = cfg.porHorario ? cfg.perfis : [];
    regra.areas = cfg.areas.map(pol);
    regra.ignorar = cfg.ignorar.map(pol);
    return { armado_de: de, armado_ate: ate, regra };
  }

  async function erroDe(r, padrao) {
    const d = r ? await r.json().catch(() => ({})) : {};
    toast(d.detail || padrao, true);
  }

  // Incluir (se preciso), salvar e, ao ligar agora, preparar a camera.
  async function ligarCamera(c, corpo) {
    let id = c.id;
    if (!id) {
      const r = await api('/api/termico/cameras', { method: 'POST', body: JSON.stringify({ ip: c.ip, connector_id: c.connector_id }) });
      if (!r || !r.ok) { await erroDe(r, `Não deu para incluir ${c.nome}.`); return false; }
      id = (await r.json()).id;
    }
    const r2 = await api(`/api/termico/cameras/${encodeURIComponent(id)}`, { method: 'PUT', body: JSON.stringify({ ...corpo, ativo: true }) });
    if (!r2 || !r2.ok) { await erroDe(r2, `Não deu para salvar ${c.nome}.`); return false; }
    if (!c.ativo) {
      const r3 = await api(`/api/termico/cameras/${encodeURIComponent(id)}/preparar`, { method: 'POST', body: '{}' });
      if (!r3 || !r3.ok) { await erroDe(r3, `${c.nome}: a câmera não aceitou ligar a medição.`); return false; }
    }
    return true;
  }

  async function salvarConfig() {
    const ok = await ligarCamera(cfg.cam, corpoRegra());
    if (!ok) return;
    toast(cfg.cam.ativo ? 'Regra salva. Vale na próxima leitura.' : `${cfg.cam.nome} vigiando.`);
    pararGaveta();
    await carregarCameras();
  }

  async function vigiarUsina(site) {
    const paradas = todasCams().filter(c => c.site === site && !c.ativo);
    if (!paradas.length) return;
    if (!confirm(`Vigiar ${paradas.length} câmera(s) de ${site}? Isso liga a medição de temperatura em cada câmera. Padrão: só à noite, sensibilidade Normal.`)) return;
    let certas = 0;
    for (const c of paradas) {
      const ok = await ligarCamera(c, { armado_de: NOITE[0], armado_ate: NOITE[1], regra: { dif_min: 5, pontos_min: 12, quadros_seguidos: 2 } });
      if (ok) certas += 1;
    }
    toast(`${certas} de ${paradas.length} câmera(s) vigiando.`, certas < paradas.length);
    await carregarCameras();
  }

  async function copiarUsina() {
    const corpo = corpoRegra();
    delete corpo.regra.areas; delete corpo.regra.ignorar;   // a area e de cada imagem
    const outras = cams.cameras.filter(c => c.site === cfg.cam.site && c.id !== cfg.cam.id && c.ativo);
    if (!outras.length) { toast('Nenhuma outra câmera vigiando nesta usina.'); return; }
    if (!confirm(`Copiar horário e sensibilidade para ${outras.length} câmera(s) de ${cfg.cam.site}? A área de cada uma não muda.`)) return;
    let certas = 0;
    for (const c of outras) {
      const r = await api(`/api/termico/cameras/${encodeURIComponent(c.id)}`, { method: 'PUT', body: JSON.stringify(corpo) });
      if (r?.ok) certas += 1;
    }
    toast(`Copiado para ${certas} câmera(s).`, certas < outras.length);
    await carregarCameras();
  }

  async function pararDeVigiar() {
    const c = cfg.cam;
    if (c.ativo) {
      const r = await api(`/api/termico/cameras/${encodeURIComponent(c.id)}`, { method: 'PUT', body: JSON.stringify({ ativo: false }) });
      if (!r || !r.ok) { await erroDe(r, 'Não deu para parar.'); return; }
      toast(`${c.nome} parou de ser vigiada.`);
    } else {
      if (!confirm(`Tirar ${c.nome} das Câmeras térmicas? Os alarmes antigos continuam guardados.`)) return;
      const r = await api(`/api/termico/cameras/${encodeURIComponent(c.id)}`, { method: 'DELETE', body: '' });
      if (!r || !r.ok) { await erroDe(r, 'Não deu para remover.'); return; }
    }
    pararGaveta();
    await carregarCameras();
  }

  // Calibrar a speed: 4 marcos vistos pelas duas cameras. Clique no marco na
  // termica, aponte a speed para ele e marque.
  function abrirCalibracao(i) {
    const a = autoAberta.acoes[i];
    const cam = cams.cameras.find(c => c.id === autoAberta.origem_camera_id);
    if (!cam) { toast('Escolha a câmera em Quando detectar em.', true); return; }
    const pontos = [];
    let alvo = null;
    const g = montarGaveta(`
      <div class="tm-gav-cab"><div style="min-width:0;flex:1"><h2>Calibrar ${h(a.nome)}</h2>
        <div class="tm-sub">Escolha 4 marcos espalhados pelo chão, como postes e cantos de cerca.</div></div>
        <button class="ghost-action" type="button" data-tm-gfechar aria-label="Fechar">✕</button></div>
      <div class="tm-gav-corpo">
        <div class="tm-perg"><b id="tmCalPasso"></b>
          <div class="tm-foto tm-desenho" id="tmCalT"><video id="tmCvT" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmCaT">Conectando...</span><div id="tmCalMarcas" class="tm-camada"></div><span class="pdv-v-lbl pdv-v-nome">${h(cam.nome)}</span></div>
          <div class="tm-foto"><video id="tmCvS" autoplay muted playsinline></video><span class="pdv-v-aviso" id="tmCaS">Conectando...</span><span class="tm-mira"></span><span class="pdv-v-lbl pdv-v-nome">${h(a.nome)}</span></div>
          <div class="tm-chips" aria-label="Mover a speed"><button type="button" data-tm-mv="-40,0,0" aria-label="Esquerda">◀</button><button type="button" data-tm-mv="0,40,0" aria-label="Cima">▲</button><button type="button" data-tm-mv="0,-40,0" aria-label="Baixo">▼</button><button type="button" data-tm-mv="40,0,0" aria-label="Direita">▶</button><button type="button" data-tm-mv="0,0,40" aria-label="Aproximar">+</button><button type="button" data-tm-mv="0,0,-40" aria-label="Afastar">−</button></div>
        </div>
      </div>
      <div class="tm-gav-pe"><button class="primary-action" type="button" data-tm-cmarcar style="flex:1;justify-content:center">Marcar este ponto</button><button class="secondary-action" type="button" data-tm-czerar>Recomeçar</button></div>`);
    const p1 = tocar($('tmCvT'), cam, 'termica', true, $('tmCaT'));
    if (p1) gavPlayers.push(p1);
    if (typeof mountLiveStream === 'function') {
      const aviso = $('tmCaS');
      gavPlayers.push(mountLiveStream($('tmCvS'), { ip: a.ip, user: 'admin', pass: '', subtype: 1, connectorId: a.connector_id,
        registrar: async () => {
          const r = await api('/api/automacoes/speed/vivo', { method: 'POST', body: JSON.stringify({ ip: a.ip, connector_id: a.connector_id }) });
          const j = await r?.json().catch(() => ({}));
          if (!r?.ok || !j?.stream_name) throw new Error(j?.detail || 'não consegui abrir o vídeo');
          return j.stream_name;
        },
        onStatus: t => { aviso.hidden = !t; if (t) aviso.textContent = t; } }));
    }
    const pintar = () => {
      $('tmCalPasso').textContent = pontos.length < 4
        ? `Ponto ${pontos.length + 1} de 4: ${alvo ? 'aponte a speed para o mesmo marco, com ele no centro, e marque' : 'clique no marco na imagem térmica'}`
        : 'Pontos marcados.';
      const m = (p, n) => `<div class="tm-marco" style="left:${p.x * 100}%;top:${p.y * 100}%">${n}</div>`;
      $('tmCalMarcas').innerHTML = pontos.map((p, n) => m(p, n + 1)).join('') + (alvo ? m(alvo, pontos.length + 1) : '');
    };
    $('tmCalT').onclick = e => {
      if (pontos.length >= 4) return;
      const r = $('tmCalT').getBoundingClientRect();
      alvo = { x: (e.clientX - r.left) / r.width, y: (e.clientY - r.top) / r.height };
      pintar();
    };
    g.querySelectorAll('[data-tm-mv]').forEach(b => b.onclick = async () => {
      const [pan, tilt, zoom] = b.dataset.tmMv.split(',').map(Number);
      const r = await api('/api/automacoes/speed/mover', { method: 'POST', body: JSON.stringify({ ip: a.ip, connector_id: a.connector_id, pan, tilt, zoom }) });
      if (!r?.ok) { const d = r ? await r.json().catch(() => ({})) : {}; toast(d.detail || 'A speed não respondeu.', true); }
    });
    g.querySelector('[data-tm-czerar]').onclick = () => { pontos.length = 0; alvo = null; pintar(); };
    g.querySelector('[data-tm-cmarcar]').onclick = async () => {
      if (!alvo) { toast('Clique primeiro no marco na imagem térmica.', true); return; }
      const r = await api(`/api/automacoes/speed/posicao?ip=${encodeURIComponent(a.ip)}&connector_id=${encodeURIComponent(a.connector_id)}`);
      const d = r?.ok ? await r.json() : null;
      if (!d) { toast('A speed não informou a posição.', true); return; }
      pontos.push({ ...alvo, az: d.az, el: d.el });
      a.zoom = d.zoom;
      alvo = null;
      pintar();
      if (pontos.length === 4) {
        a.pontos = [...pontos];
        toast('Calibrada. Salve a automação e use Testar agora.');
        pararGaveta();
        render();
      }
    };
    pintar();
  }

  // Simular pessoa: desenha uma pessoa em cada ponto da ultima leitura, com a regra salva.
  async function simularPessoa() {
    const txt = $('tmTesteTxt'), box = $('tmManchas');
    txt.hidden = false; txt.textContent = 'Simulando…';
    const r = await api(`/api/termico/cameras/${encodeURIComponent(cfg.cam.id)}/simular-pessoa`, { method: 'POST', body: '{}' });
    const d = r?.ok ? await r.json() : null;
    if (!d) { const e = r ? await r.json().catch(() => ({})) : {}; txt.textContent = e.detail || 'Não deu para simular agora.'; return; }
    if (box) box.innerHTML = d.cegos.map(c => `<div class="tm-cego" style="left:${c[0] * 100}%;top:${c[1] * 100}%;width:${c[2] * 100}%;height:${c[3] * 100}%"></div>`).join('');
    txt.textContent = `Pessoa simulada a ${num(d.temp, 0)} °C, com a regra salva${d.faixa ? ` da faixa ${h(d.faixa.replace('-', ' às '))}` : ''} e o chão de agora (${num(d.cena.min, 0)} a ${num(d.cena.max, 0)} °C). Encontrada em: ${d.tamanhos.map(t => `${t.pct}% (${t.nome})`).join(', ')}. Em vermelho, onde a pessoa média não seria vista. É uma estimativa: só uma pessoa real confirma.`;
  }

  // Testar agora: mostra sobre o video o que a deteccao ve, a cada 2 s.
  function alternarTeste(bt) {
    const txt = $('tmTesteTxt');
    if (testeTimer) {
      clearInterval(testeTimer); testeTimer = null;
      bt.textContent = 'Testar agora'; txt.hidden = true; $('tmManchas').innerHTML = '';
      return;
    }
    bt.textContent = 'Parar teste'; txt.hidden = false;
    txt.textContent = 'Testando: peça para alguém passar na frente da câmera.';
    const id = cfg.cam.id;
    const ler = async () => {
      const r = await api(`/api/termico/cameras/${encodeURIComponent(id)}/manchas`);
      const d = r?.ok ? await r.json() : null;
      const box = $('tmManchas');
      if (!box || !d) return;
      box.innerHTML = d.manchas.map(m => `<div class="tm-mancha" style="left:${m.caixa[0] * 100}%;top:${m.caixa[1] * 100}%;width:${m.caixa[2] * 100}%;height:${m.caixa[3] * 100}%"><span>${num(m.temp_media, 0)} °C</span></div>`).join('');
      txt.textContent = !d.lendo ? 'A câmera não está sendo lida agora (fora do horário lê só 1 vez por minuto).'
        : d.manchas.length ? `Detectando ${d.manchas.length} mancha(s) com temperatura de corpo.` : 'Lendo a câmera: nenhuma mancha com temperatura de corpo agora.';
    };
    ler();
    testeTimer = setInterval(ler, 2000);
  }
})();
