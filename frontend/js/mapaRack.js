// Rack da rede neutra no mapa: ponto com os equipamentos dentro (DIO, OLT,
// borda, switch, NVR, DVR, servidor, computador), as portas de cada um, as
// ligacoes porta-a-porta e os provedores que entram. O usuario monta e liga
// ponto a ponto, como no FTTH; o monitoramento dos links vem depois e le daqui
// qual porta e de qual provedor.
//
// Duas telas: clicar no rack abre um RESUMO no painel lateral do mapa
// (mapaCaixas.js: cxPainelBase); "Abrir rack" abre a TELA GRANDE, com o
// destino escrito embaixo de cada porta e um painel a direita que mostra so a
// porta escolhida. Ligar = clicar na porta livre e depois no destino.
// O backend valida tudo em app/services/mapa_rack.py.

const RK_TIPOS = {
  dio: 'DIO', olt: 'OLT', borda: 'Borda (roteador)', switch: 'Switch', nvr: 'Gravador (NVR)',
  dvr: 'DVR', servidor: 'Servidor', computador: 'Computador', outro: 'Outro',
};
const RK_TIPOS_CURTO = { dio: 'DIO', olt: 'OLT', borda: 'Borda', switch: 'Switch', nvr: 'NVR', dvr: 'DVR', servidor: 'Servidor', computador: 'PC', outro: 'Outro' };
const RK_LIGACOES = { patch: 'Cordão óptico', dac: 'Cabo DAC', utp: 'Cabo de rede', fibra: 'Fibra' };
// Tipo do equipamento no rack -> tipo no monitoramento (para mostrar se esta no ar)
const RK_ENTIDADE = { olt: 'olt', borda: 'connector', switch: 'switch', nvr: 'nvr', dvr: 'dvr', servidor: 'windows', computador: 'windows' };

const rkSeq = (prefixo, n, inicio = 1) => Array.from({ length: n }, (_, i) => `${prefixo}${i + inicio}`);
// Modelos com as portas prontas (nomes como aparecem no equipamento)
const RK_MODELOS = {
  'CRS317-1G-16S+': ['ether1', ...rkSeq('sfp-sfpplus', 16)],
  'CRS326-24S+2Q+': ['ether1', ...rkSeq('sfp-sfpplus', 24), 'qsfpplus1-1', 'qsfpplus2-1'],
  'CRS328-24P-4S+': [...rkSeq('ether', 24), ...rkSeq('sfp-sfpplus', 4)],
  'CCR1036-8G-2S+': [...rkSeq('ether', 8), ...rkSeq('sfp-sfpplus', 2)],
  'CCR2004-16G-2S+': [...rkSeq('ether', 16), ...rkSeq('sfp-sfpplus', 2)],
  'CCR2116-12G-4S+': [...rkSeq('ether', 13), ...rkSeq('sfp-sfpplus', 4)],
  'DIO 12': rkSeq('P', 12), 'DIO 24': rkSeq('P', 24), 'DIO 48': rkSeq('P', 48),
  'DIO 72': rkSeq('P', 72), 'DIO 144': rkSeq('P', 144),
  'OLT 8 PON + 4 uplinks': [...rkSeq('PON', 8), ...rkSeq('UP', 4)],
  'OLT 16 PON + 4 uplinks': [...rkSeq('PON', 16), ...rkSeq('UP', 4)],
  '1 porta de rede': ['LAN1'],
  '2 portas de rede': ['LAN1', 'LAN2'],
};
const RK_MODELO_PADRAO = {
  dio: 'DIO 24', olt: 'OLT 16 PON + 4 uplinks', borda: 'CCR1036-8G-2S+', switch: 'CRS317-1G-16S+',
  nvr: '1 porta de rede', dvr: '1 porta de rede', servidor: '2 portas de rede', computador: '1 porta de rede', outro: '1 porta de rede',
};

// Tela grande aberta: { el, id, def, rackId, nomePonto, latlng, aba, sel, modo, origem, cabo, editEq, editProv, ents }
let _rk = null;

function rkPos(def, rack) {
  if (rack?.lat != null) return [Number(rack.lat), Number(rack.lng)];
  return cxLatLngDoPonto(def, rack?.ponto);
}

function rkDoPonto(def, nome, latlng) {
  const chave = String(nome || '').trim().toLowerCase();
  const doNome = Object.values(def?.racks || {}).filter(r => String(r.ponto || '').trim().toLowerCase() === chave);
  if (!latlng) return doNome.length === 1 ? doNome[0] : null;
  return doNome.find(r => cxPerto(rkPos(def, r), latlng)) || null;
}

function rkMarcador(id, def, f, lat, lng) {
  const nome = mapFeatureName(f);
  const rack = rkDoPonto(def, nome, [lat, lng]);
  const n = rack?.equipamentos?.length || 0;
  const dica = rack ? `Rack: ${n} equipamento(s), ${rack.ligacoes?.length || 0} ligação(ões)` : 'Rack sem cadastro: clique para montar';
  const icon = L.divIcon({
    className: '',
    html: `<div class="rk-pino${rack ? '' : ' rk-pino-novo'}" title="${esc(dica)}"><b>RACK</b><span>${esc(rack?.nome || nome)}${rack ? ` · ${n}` : ''}</span></div>`,
    iconSize: [44, 22], iconAnchor: [22, 11],
  });
  const marker = L.marker([lat, lng], { icon, zIndexOffset: 460 });
  marker.on('click', () => {
    if (_cx.desenho || _cx.edicao) return;
    rkAbrirPainel(id, def, nome, [lat, lng]).catch(e => showToast(e?.message || 'Falha ao abrir o rack.', true));
  });
  return marker;
}

// ------------------------------------------------------------------ apoio

const rkChave = (eq, porta) => `${eq}|${String(porta).toLowerCase()}`;
// Nome curto da porta para caber no botao: sfp-sfpplus7 -> sfp7, ether3 -> e3
const rkPortaCurta = p => String(p).replace(/^sfp-sfpplus/, 'sfp').replace(/^ether/, 'e').replace(/^qsfpplus/, 'q');
// Nome curto do equipamento: a primeira palavra quando e curta (OLT, SWITCH, CCR, DIO), senao o tipo
function rkEqCurto(e) {
  const w = String(e?.nome || '').trim().split(/[\s-]+/)[0] || '';
  return w && w.length <= 8 ? w : (RK_TIPOS_CURTO[e?.tipo] || 'Eq');
}

// Estado de cada porta: ligacao (para onde vai) e provedor que entra nela
function rkUsoDasPortas(rack) {
  const eqs = Object.fromEntries((rack?.equipamentos || []).map(e => [e.id, e]));
  const uso = {};
  (rack?.ligacoes || []).forEach(lg => {
    uso[rkChave(lg.a.eq, lg.a.porta)] = { ...(uso[rkChave(lg.a.eq, lg.a.porta)] || {}), lig: lg, para: lg.b, eqPara: eqs[lg.b.eq] };
    uso[rkChave(lg.b.eq, lg.b.porta)] = { ...(uso[rkChave(lg.b.eq, lg.b.porta)] || {}), lig: lg, para: lg.a, eqPara: eqs[lg.a.eq] };
  });
  (rack?.provedores || []).forEach(pv => {
    const k = rkChave(pv.entrada.eq, pv.entrada.porta);
    uso[k] = { ...(uso[k] || {}), provedor: pv };
  });
  return uso;
}

async function rkEntidades() {
  const tipos = [...new Set(Object.values(RK_ENTIDADE))];
  const listas = await Promise.all(tipos.map(t => ctEntidades(t)));
  const porTipo = {};
  tipos.forEach((t, i) => { porTipo[t] = listas[i] || []; });
  return porTipo;
}

function rkStatus(ents, chave) {
  if (!chave) return null;
  const e = Object.values(ents || {}).flat().find(x => x.entity_key === chave);
  if (!e) return { cls: 'rk-sem', txt: 'sem leitura' };
  const st = String(e.status || '').toLowerCase();
  if (st === 'up' || st === 'online') return { cls: 'rk-on', txt: 'no ar' };
  if (st === 'down' || st === 'offline') return { cls: 'rk-off', txt: 'fora do ar' };
  return { cls: 'rk-sem', txt: 'sem leitura' };
}

function rkOpcoesEntidade(ents, tipo, atual) {
  const t = RK_ENTIDADE[tipo];
  const lista = (t && ents?.[t]) || [];
  const tem = lista.some(e => e.entity_key === atual);
  return `<option value="">Não</option>${lista.map(e => `<option value="${esc(e.entity_key)}" ${atual === e.entity_key ? 'selected' : ''}>${esc(e.display_name || e.entity_id)}${e.site ? ` · ${esc(e.site)}` : ''}</option>`).join('')}${atual && !tem ? `<option value="${esc(atual)}" selected>${esc(atual)}</option>` : ''}`;
}

const rkLigadas = (e, uso) => e.portas.filter(p => uso[rkChave(e.id, p.id)]?.lig).length;

// ------------------------------------------------------------------ resumo no mapa

async function rkAbrirPainel(id, def, nomePonto, latlng) {
  if (!def?.updateUrl || def.source !== 'imported') { showToast('Rack só em camadas importadas (KMZ).', true); return; }
  latlng = latlng || cxLatLngDoPonto(def, nomePonto);
  const rack = rkDoPonto(def, nomePonto, latlng);
  if (!rack) {
    const corpo = `
      <div class="so-note"><i data-lucide="info"></i><span>Monte o rack: DIOs, OLT, borda, switch, gravadores, servidores e computadores. Depois ligue porta a porta e marque por onde entra cada provedor.</span></div>
      <div class="form-group" style="margin:0"><label for="rkNome">Nome</label><input id="rkNome" maxlength="80" value="${esc(nomePonto)}"></div>
      <div class="form-group" style="margin:0"><label for="rkObs">Observação</label><input id="rkObs" maxlength="300" placeholder="ex.: sala do datacenter"></div>
      <p id="cxErro" class="login-error" hidden></p>`;
    const el = cxPainelBase(nomePonto || 'Rack', corpo, '<span style="flex:1"></span><button type="button" class="primary-action" data-rk="criar"><i data-lucide="plus"></i> Criar rack</button>', 'Rack · rede neutra');
    el.classList.add('rk-painel');
    // registrado: sem isso cxFecharPainel (e o Esc) nao fecham este painel
    _cx.painel = { el, id, def, nomePonto, latlng, tipo: 'rack' };
    el.addEventListener('click', ev => {
      if (!ev.target.closest('[data-rk="criar"]')) return;
      const v = idc => (el.querySelector(`#${idc}`)?.value ?? '').trim();
      cxGravar(def, { rack: { ponto: nomePonto, lat: latlng?.[0], lng: latlng?.[1], nome: v('rkNome'), obs: v('rkObs') } })
        .then(() => {
          cxFecharPainel(); cxRedesenhar(id, def);
          const novo = rkDoPonto(def, nomePonto, latlng);
          if (novo) rkAbrirTela(id, def, novo, nomePonto, latlng);
        })
        .catch(e => { const er = el.querySelector('#cxErro'); if (er) { er.textContent = e.message; er.hidden = false; } });
    });
    return;
  }
  const ents = await rkEntidades();
  const uso = rkUsoDasPortas(rack);
  const eqs = rack.equipamentos || [];
  const noAr = eqs.filter(e => rkStatus(ents, e.entidade)?.cls === 'rk-on').length;
  const linhas = eqs.map(e => {
    const lig = rkLigadas(e, uso);
    const pct = e.portas.length ? Math.round((lig / e.portas.length) * 100) : 0;
    const st = rkStatus(ents, e.entidade);
    return `<div class="rk-res-eq"><span class="rk-tipo">${esc(RK_TIPOS_CURTO[e.tipo] || e.tipo)}</span>
      <span class="rk-res-nome"><strong>${esc(e.nome)}</strong><small>${esc(e.modelo || '')}${st ? ` · <span class="${st.cls}-txt">${st.txt}</span>` : ''}</small></span>
      <span class="rk-barra" aria-hidden="true"><i style="width:${pct}%"></i></span><small class="rk-res-uso">${lig}/${e.portas.length}</small></div>`;
  }).join('') || '<p class="text-muted" style="margin:0;font-size:12.5px">Nenhum equipamento ainda.</p>';
  const provs = (rack.provedores || []).map(pv => `<span class="rk-chip">${esc(pv.nome)}</span>`).join('');
  const corpo = `
    <div class="rk-res-pills">
      <span class="rk-pill">${eqs.length} equipamento(s)${noAr ? ` · ${noAr} no ar` : ''}</span>
      <span class="rk-pill">${rack.ligacoes?.length || 0} ligação(ões)</span>
      <span class="rk-pill">${rack.provedores?.length || 0} provedor(es)</span>
    </div>
    <section><h3>O que tem dentro</h3>${linhas}</section>
    ${provs ? `<section><h3>Provedores <small>ficam verdes ou vermelhos quando a leitura da CRS for ligada</small></h3><div class="rk-chips">${provs}</div></section>` : ''}`;
  const el = cxPainelBase(rack.nome, corpo, '<span style="flex:1"></span><button type="button" class="primary-action" data-rk="abrir"><i data-lucide="maximize-2"></i> Abrir rack</button>', 'Rack · rede neutra');
  el.classList.add('rk-painel');
  _cx.painel = { el, id, def, nomePonto, latlng, tipo: 'rack' };
  el.addEventListener('click', ev => {
    if (!ev.target.closest('[data-rk="abrir"]')) return;
    cxFecharPainel();
    rkAbrirTela(id, def, rack, nomePonto, latlng, ents);
  });
}

// ------------------------------------------------------------------ tela grande

async function rkAbrirTela(id, def, rack, nomePonto, latlng, ents) {
  rkFecharTela();
  const el = document.createElement('div');
  el.className = 'rkv';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  document.body.appendChild(el);
  _rk = { el, id, def, rackId: rack.id, nomePonto, latlng, aba: 'rack', sel: null, modo: null, origem: null, cabo: 'patch', editEq: null, editProv: null, ents: ents || {} };
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-rk]');
    if (b) rkAcao(b).catch(e => rkErro(e));
  });
  el.addEventListener('change', ev => {
    if (ev.target.id === 'rkEqTipo' || ev.target.id === 'rkEqModelo') rkFormEqAjustar(ev.target.id);
    if (ev.target.id === 'rkPvEq') rkPortasDoProvedor();
  });
  document.addEventListener('keydown', rkEsc, true);
  rkRender();
  if (!ents) { _rk.ents = await rkEntidades(); rkRender(); }
}

function rkFecharTela() {
  _rk?.el?.remove();
  _rk = null;
  document.removeEventListener('keydown', rkEsc, true);
}

// Esc: primeiro cancela o que esta em andamento (ligar, formulario); depois fecha
function rkEsc(e) {
  if (e.key !== 'Escape' || !_rk) return;
  if (!document.getElementById('modalConfirm')?.classList.contains('hidden')) return;
  e.stopPropagation();
  if (_rk.modo || _rk.sel) { _rk.modo = null; _rk.sel = null; _rk.origem = null; rkRender(); return; }
  rkFecharTela();
}

function rkRack() {
  return _rk?.def?.racks?.[_rk.rackId] || null;
}

function rkErro(e) {
  const er = _rk?.el?.querySelector('#rkErro');
  if (er) { er.textContent = e?.message || 'Falha.'; er.hidden = false; } else showToast(e?.message || 'Falha.', true);
}

function rkRender() {
  const rack = rkRack();
  if (!_rk || !rack) { rkFecharTela(); return; }
  const uso = rkUsoDasPortas(rack);
  _rk.el.setAttribute('aria-label', `Rack ${rack.nome}`);
  _rk.el.innerHTML = `
    <header class="rkv-topo">
      <button type="button" class="secondary-action" data-rk="fechar"><i data-lucide="arrow-left"></i> Mapa</button>
      <div class="rkv-titulo"><p class="eyebrow">Rack · rede neutra</p><h2>${esc(rack.nome)}</h2></div>
      <nav class="rkv-abas" aria-label="Abas do rack">
        <button type="button" class="${_rk.aba === 'rack' ? 'on' : ''}" data-rk="aba" data-aba="rack">Rack</button>
        <button type="button" class="${_rk.aba === 'prov' ? 'on' : ''}" data-rk="aba" data-aba="prov">Provedores (${rack.provedores?.length || 0})</button>
      </nav>
      <span style="flex:1"></span>
      ${_rk.aba === 'prov'
        ? '<button type="button" class="primary-action" data-rk="novo-prov"><i data-lucide="plus"></i> Provedor</button>'
        : '<button type="button" class="secondary-action" data-rk="novo-eq"><i data-lucide="plus"></i> Equipamento</button>'}
      <button type="button" class="ghost-action cx-ico" data-rk="config" title="Nome e opções do rack" aria-label="Nome e opções do rack"><i data-lucide="settings"></i></button>
    </header>
    <div class="rkv-corpo">
      <main class="rkv-main">${_rk.aba === 'prov' ? rkHtmlProvedores(rack) : rkHtmlRack(rack, uso)}</main>
      <aside class="rkv-lado">${rkHtmlLado(rack, uso)}<p id="rkErro" class="login-error" hidden></p></aside>
    </div>`;
  lucide.createIcons();
  if (_rk.modo === 'eq') rkFormEqAjustar('');
  if (_rk.modo === 'prov') rkPortasDoProvedor(true);
}

function rkHtmlRack(rack, uso) {
  const eqs = rack.equipamentos || [];
  if (!eqs.length) {
    return `<div class="rkv-vazio"><h3>Rack vazio</h3><p>Comece pelos equipamentos: DIO, OLT, borda, switch, gravadores, servidores e computadores.</p>
      <button type="button" class="primary-action" data-rk="novo-eq"><i data-lucide="plus"></i> Adicionar equipamento</button></div>`;
  }
  const ligando = _rk.modo === 'ligar' && _rk.origem;
  const banner = ligando
    ? `<div class="rkv-banner"><strong>${esc(eqs.find(e => e.id === _rk.origem.eq)?.nome || '')} · ${esc(rkPortaCurta(_rk.origem.porta))}</strong>
        <span>está livre. Clique na porta de destino; as livres estão com borda verde.</span><span style="flex:1"></span>
        <button type="button" class="secondary-action" data-rk="cancelar">Cancelar</button></div>`
    : `<div class="rkv-legenda"><span><b class="rkv-l-livre"></b>livre</span><span><b class="rkv-l-lig"></b>ligada (embaixo diz para onde)</span>
        <span><b class="rkv-l-prov"></b>entrada de provedor</span><span><b class="rkv-l-sel"></b>selecionada e o outro lado</span></div>`;
  const sel = _rk.sel;
  const par = sel ? uso[rkChave(sel.eq, sel.porta)]?.para : null;
  const cards = eqs.map(e => {
    const st = rkStatus(_rk.ents, e.entidade);
    const portas = e.portas.map(p => {
      const u = uso[rkChave(e.id, p.id)] || {};
      const destino = u.lig ? `${rkEqCurto(u.eqPara)} ${rkPortaCurta(u.para.porta)}` : u.provedor ? u.provedor.nome.split(/\s+/)[0] : 'livre';
      let cls = u.provedor ? 'prov' : u.lig ? 'lig' : 'livre';
      if (ligando) {
        if (_rk.origem.eq === e.id && _rk.origem.porta.toLowerCase() === p.id.toLowerCase()) cls = 'origem';
        else if (!u.lig) cls = 'alvo';
        else cls += ' apagada';
      } else if (sel && sel.eq === e.id && sel.porta.toLowerCase() === p.id.toLowerCase()) cls += ' sel';
      else if (par && par.eq === e.id && par.porta.toLowerCase() === p.id.toLowerCase()) cls += ' par';
      const dica = [p.id, p.rotulo, u.provedor ? `provedor ${u.provedor.nome}` : '', u.lig ? `→ ${u.eqPara?.nome} ${u.para.porta}` : 'livre'].filter(Boolean).join(' · ');
      return `<button type="button" class="rkv-p ${cls}" data-rk="porta" data-eq="${esc(e.id)}" data-porta="${esc(p.id)}" title="${esc(dica)}">${esc(rkPortaCurta(p.id))}<small>${esc(destino)}</small></button>`;
    }).join('');
    return `<section class="rkv-eq${ligando && _rk.origem.eq === e.id ? ' apagado' : ''}" aria-label="${esc(e.nome)}">
      <div class="rkv-eq-topo"><span class="rk-tipo">${esc(RK_TIPOS_CURTO[e.tipo] || e.tipo)}</span><strong>${esc(e.nome)}</strong>
        ${e.modelo ? `<span class="rkv-cinza">${esc(e.modelo)}</span>` : ''}${st ? `<span class="rk-status ${st.cls}">${st.txt}</span>` : ''}
        <span style="flex:1"></span><span class="rkv-cinza">${rkLigadas(e, uso)}/${e.portas.length} ligadas</span>
        <button type="button" class="ghost-action cx-ico" data-rk="editar-eq" data-eq="${esc(e.id)}" title="Editar equipamento" aria-label="Editar ${esc(e.nome)}"><i data-lucide="more-horizontal"></i></button></div>
      <div class="rkv-portas">${portas}</div></section>`;
  }).join('');
  return banner + cards;
}

function rkHtmlProvedores(rack) {
  const eqs = Object.fromEntries((rack.equipamentos || []).map(e => [e.id, e]));
  const linhas = (rack.provedores || []).map(pv => `<tr>
      <td><strong>${esc(pv.nome)}</strong></td>
      <td>${esc(eqs[pv.entrada.eq]?.nome || '?')} <span class="rkv-porta-tag">${esc(rkPortaCurta(pv.entrada.porta))}</span></td>
      <td>${pv.vlans.length ? esc(pv.vlans.join(', ')) : '—'}</td>
      <td><span class="rk-status rk-sem">sem leitura</span></td>
      <td class="rkv-cinza">—</td><td class="rkv-cinza">—</td>
      <td>${pv.banda_mbps ? `${pv.banda_mbps} Mbps` : '—'}</td>
      <td><button type="button" class="ghost-action cx-ico" data-rk="editar-prov" data-prov="${esc(pv.id)}" title="Editar provedor" aria-label="Editar ${esc(pv.nome)}"><i data-lucide="pencil"></i></button></td></tr>`).join('');
  return `<div class="rkv-aviso"><strong>Leitura dos links ainda desligada.</strong> Quando a API só de leitura for liberada nas CRS, link, tráfego e sinal da fibra passam a atualizar sozinhos e vão para o Zabbix.</div>
    ${linhas ? `<div class="rkv-tabela-box"><table class="rkv-tabela"><thead><tr><th>Provedor</th><th>Entra em</th><th>VLANs</th><th>Link</th><th>Tráfego</th><th>Sinal da fibra</th><th>Banda</th><th></th></tr></thead><tbody>${linhas}</tbody></table></div>`
      : '<div class="rkv-vazio"><h3>Nenhum provedor</h3><p>Marque por qual porta entra cada provedor e as VLANs dele.</p><button type="button" class="primary-action" data-rk="novo-prov"><i data-lucide="plus"></i> Adicionar provedor</button></div>'}`;
}

// Painel da direita: so o que importa agora
function rkHtmlLado(rack, uso) {
  const eqs = rack.equipamentos || [];
  const nomeEq = id => eqs.find(e => e.id === id)?.nome || '?';
  if (_rk.modo === 'config') {
    return `<p class="rkv-rotulo">RACK</p>
      <div class="form-group" style="margin:0"><label for="rkCfgNome">Nome</label><input id="rkCfgNome" maxlength="80" value="${esc(rack.nome)}"></div>
      <div class="form-group" style="margin:0"><label for="rkCfgObs">Observação</label><input id="rkCfgObs" maxlength="300" value="${esc(rack.obs || '')}" placeholder="ex.: sala do datacenter"></div>
      <div class="rkv-acoes"><button type="button" class="ghost-action cx-perigo" data-rk="excluir-rack"><i data-lucide="trash-2"></i> Excluir rack</button><span style="flex:1"></span>
        <button type="button" class="secondary-action" data-rk="cancelar">Cancelar</button><button type="button" class="primary-action" data-rk="salvar-config">Salvar</button></div>`;
  }
  if (_rk.modo === 'eq') return rkHtmlFormEq(rack);
  if (_rk.modo === 'prov') return rkHtmlFormProv(rack);
  if (_rk.modo === 'ligar' && _rk.origem) {
    return `<p class="rkv-rotulo">LIGAR</p><h3 class="rkv-h">${esc(nomeEq(_rk.origem.eq))} · ${esc(_rk.origem.porta)}</h3>
      <div class="rkv-ponte"><span class="rkv-ponte-a">${esc(rkPortaCurta(_rk.origem.porta))}</span><span aria-hidden="true">→</span><span class="rkv-ponte-b">clique no destino</span></div>
      <p class="rkv-rotulo">TIPO DE CABO</p>
      <div class="rk-chips">${Object.entries(RK_LIGACOES).map(([k, v]) => `<button type="button" class="rk-chip${_rk.cabo === k ? ' on' : ''}" data-rk="cabo" data-cabo="${k}">${esc(v)}</button>`).join('')}</div>
      <p class="rkv-rotulo" style="margin-top:6px">OU ESTA PORTA É…</p>
      <button type="button" class="secondary-action rkv-largo" data-rk="porta-provedor">a entrada de um provedor</button>
      <button type="button" class="secondary-action rkv-largo" disabled title="Em breve">a saída de um cabo no mapa (em breve)</button>
      <span style="flex:1"></span>
      <button type="button" class="secondary-action" data-rk="cancelar">Cancelar</button>`;
  }
  if (_rk.sel) {
    const eq = eqs.find(e => e.id === _rk.sel.eq);
    const porta = eq?.portas.find(p => p.id.toLowerCase() === _rk.sel.porta.toLowerCase());
    if (!eq || !porta) { _rk.sel = null; return rkHtmlLado(rack, uso); }
    const u = uso[rkChave(eq.id, porta.id)] || {};
    const ligBox = u.lig ? `<div class="rkv-box ok"><p class="rkv-rotulo">LIGADA EM</p><strong>${esc(u.eqPara?.nome || '?')} · ${esc(u.para.porta)}</strong>
        <span>${esc(RK_LIGACOES[u.lig.tipo] || u.lig.tipo)}</span></div>` : '<div class="rkv-box"><p class="rkv-rotulo">SEM LIGAÇÃO</p><span>Esta porta não está ligada em nada do rack.</span></div>';
    const provBox = u.provedor ? `<div class="rkv-box prov"><p class="rkv-rotulo">ENTRADA DO PROVEDOR</p><strong>${esc(u.provedor.nome)}</strong>
        <span>${u.provedor.vlans.length ? `VLAN ${esc(u.provedor.vlans.join(', '))}` : 'sem VLAN informada'}</span>
        <button type="button" class="secondary-action" data-rk="editar-prov" data-prov="${esc(u.provedor.id)}">Editar provedor</button></div>` : '';
    const parRot = u.lig ? u.eqPara?.portas.find(p => p.id.toLowerCase() === u.para.porta.toLowerCase())?.rotulo : '';
    return `<p class="rkv-rotulo">PORTA SELECIONADA</p><h3 class="rkv-h">${esc(eq.nome)} · ${esc(porta.id)}</h3>
      ${ligBox}${provBox}
      ${u.lig ? `<div class="rkv-caminho"><p class="rkv-rotulo">CAMINHO</p>
        <div class="rkv-passo"><b>1</b>${esc(rkEqCurto(eq))} ${esc(rkPortaCurta(porta.id))}${porta.rotulo ? ` <small>${esc(porta.rotulo)}</small>` : ''}</div>
        <div class="rkv-passo"><b>2</b>${esc(rkEqCurto(u.eqPara))} ${esc(rkPortaCurta(u.para.porta))}${parRot ? ` <small>${esc(parRot)}</small>` : ''}</div></div>` : ''}
      <div class="form-group" style="margin:0"><label for="rkRotulo">Comentário da porta</label>
        <input id="rkRotulo" maxlength="120" value="${esc(porta.rotulo || '')}" placeholder="ex.: OLT JARDINS I (a sfp1 queimou)"></div>
      <span style="flex:1"></span>
      <div class="rkv-acoes">${u.lig ? '<button type="button" class="ghost-action cx-perigo" data-rk="desligar">Desfazer ligação</button>' : '<button type="button" class="secondary-action" data-rk="ligar-daqui">Ligar esta porta</button>'}
        <span style="flex:1"></span><button type="button" class="primary-action" data-rk="salvar-rotulo">Salvar comentário</button></div>`;
  }
  const total = eqs.reduce((n, e) => n + e.portas.length, 0);
  return `<p class="rkv-rotulo">COMO USAR</p>
    <div class="rkv-dica"><b>1</b><span>Clique numa porta <strong>livre</strong> e depois na porta de destino para ligar.</span></div>
    <div class="rkv-dica"><b>2</b><span>Clique numa porta <strong>ligada</strong> para ver para onde vai, comentar ou desfazer.</span></div>
    <div class="rkv-dica"><b>3</b><span>Na aba <strong>Provedores</strong>, marque por onde entra cada link.</span></div>
    <div class="rkv-resumo"><span><strong>${eqs.length}</strong> equipamentos</span><span><strong>${rack.ligacoes?.length || 0}</strong> ligações</span><span><strong>${total}</strong> portas</span></div>`;
}

// ------------------------------------------------------------------ formularios no painel

function rkHtmlFormEq(rack) {
  const eq = _rk.editEq ? rack.equipamentos.find(e => e.id === _rk.editEq) : null;
  const tipo = eq?.tipo || 'switch';
  const modeloAtual = eq ? (Object.entries(RK_MODELOS).find(([, v]) => v.join() === eq.portas.map(x => x.id).join())?.[0] || '') : RK_MODELO_PADRAO[tipo];
  return `<p class="rkv-rotulo">${eq ? 'EDITAR EQUIPAMENTO' : 'NOVO EQUIPAMENTO'}</p>
    <div class="form-group" style="margin:0"><label for="rkEqTipo">Tipo</label><select id="rkEqTipo">${Object.entries(RK_TIPOS).map(([k, v]) => `<option value="${k}" ${tipo === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
    <div class="form-group" style="margin:0"><label for="rkEqNome">Nome</label><input id="rkEqNome" maxlength="80" value="${esc(eq?.nome || '')}" placeholder="ex.: SWITCH JARDINS"></div>
    <div class="form-group" style="margin:0"><label for="rkEqModelo">Portas</label><select id="rkEqModelo">${Object.keys(RK_MODELOS).map(m => `<option value="${esc(m)}" ${modeloAtual === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}<option value="" ${modeloAtual ? '' : 'selected'}>Outro: digitar as portas</option></select></div>
    <div class="form-group" style="margin:0" id="rkEqPortasLivre" ${modeloAtual ? 'hidden' : ''}><label for="rkEqPortas">Nomes das portas (separados por vírgula)</label>
      <input id="rkEqPortas" maxlength="4000" value="${esc(eq ? eq.portas.map(x => x.id).join(', ') : '')}" placeholder="ex.: ether1, ether2, sfp1"></div>
    <div class="form-group" style="margin:0"><label for="rkEqModeloTxt">Modelo</label><input id="rkEqModeloTxt" maxlength="60" value="${esc(eq?.modelo || '')}" placeholder="ex.: CRS317-1G-16S+"></div>
    <div class="form-group" style="margin:0"><label for="rkEqEnt">É um equipamento já monitorado?</label><select id="rkEqEnt">${rkOpcoesEntidade(_rk.ents, tipo, eq?.entidade)}</select></div>
    <span style="flex:1"></span>
    <div class="rkv-acoes">${eq ? '<button type="button" class="ghost-action cx-perigo" data-rk="tirar-eq">Tirar do rack</button>' : ''}<span style="flex:1"></span>
      <button type="button" class="secondary-action" data-rk="cancelar">Cancelar</button><button type="button" class="primary-action" data-rk="salvar-eq">${eq ? 'Salvar' : 'Adicionar'}</button></div>`;
}

function rkFormEqAjustar(origem) {
  const el = _rk?.el;
  if (!el) return;
  const tipo = el.querySelector('#rkEqTipo')?.value;
  if (origem === 'rkEqTipo') {
    const m = el.querySelector('#rkEqModelo');
    if (m) m.value = RK_MODELO_PADRAO[tipo] || '';
    const ent = el.querySelector('#rkEqEnt');
    if (ent) ent.innerHTML = rkOpcoesEntidade(_rk.ents, tipo, '');
  }
  const modelo = el.querySelector('#rkEqModelo')?.value;
  const livre = el.querySelector('#rkEqPortasLivre');
  if (livre) livre.hidden = Boolean(modelo);
}

function rkHtmlFormProv(rack) {
  const pv = _rk.editProv ? rack.provedores.find(p => p.id === _rk.editProv) : null;
  const entrada = pv?.entrada || _rk.origem || { eq: rack.equipamentos[0]?.id || '', porta: '' };
  return `<p class="rkv-rotulo">${pv ? 'EDITAR PROVEDOR' : 'NOVO PROVEDOR'}</p>
    <div class="form-group" style="margin:0"><label for="rkPvNome">Provedor</label><input id="rkPvNome" maxlength="80" value="${esc(pv?.nome || '')}" placeholder="ex.: VOE TELECOM"></div>
    <div class="form-group" style="margin:0"><label for="rkPvEq">Entra no equipamento</label><select id="rkPvEq">${rack.equipamentos.map(e => `<option value="${esc(e.id)}" ${entrada.eq === e.id ? 'selected' : ''}>${esc(e.nome)}</option>`).join('')}</select></div>
    <div class="form-group" style="margin:0"><label for="rkPvPorta">Pela porta</label><select id="rkPvPorta" data-atual="${esc(entrada.porta)}"></select></div>
    <div class="form-group" style="margin:0"><label for="rkPvVlans">VLANs</label><input id="rkPvVlans" maxlength="200" value="${esc(pv ? pv.vlans.join(', ') : '')}" placeholder="ex.: 3030, 3031"></div>
    <div class="form-group" style="margin:0"><label for="rkPvBanda">Banda contratada (Mbps)</label><input id="rkPvBanda" type="number" min="0" max="400000" value="${pv?.banda_mbps || ''}" placeholder="ex.: 1000"></div>
    <span style="flex:1"></span>
    <div class="rkv-acoes">${pv ? '<button type="button" class="ghost-action cx-perigo" data-rk="tirar-prov">Tirar provedor</button>' : ''}<span style="flex:1"></span>
      <button type="button" class="secondary-action" data-rk="cancelar">Cancelar</button><button type="button" class="primary-action" data-rk="salvar-prov">${pv ? 'Salvar' : 'Adicionar'}</button></div>`;
}

function rkPortasDoProvedor(inicial) {
  const el = _rk?.el;
  const rack = rkRack();
  const sel = el?.querySelector('#rkPvPorta');
  const eq = rack?.equipamentos.find(e => e.id === el?.querySelector('#rkPvEq')?.value);
  if (!sel || !eq) return;
  const uso = rkUsoDasPortas(rack);
  const meu = _rk.editProv;
  sel.innerHTML = eq.portas.map(p => {
    const u = uso[rkChave(eq.id, p.id)] || {};
    const deOutro = u.provedor && u.provedor.id !== meu;
    return `<option value="${esc(p.id)}" ${deOutro ? 'disabled' : ''}>${esc(p.id)}${u.lig ? ` → ${esc(rkEqCurto(u.eqPara))} ${esc(rkPortaCurta(u.para.porta))}` : ''}${deOutro ? ` (${esc(u.provedor.nome)})` : ''}</option>`;
  }).join('');
  const atual = inicial ? sel.dataset.atual : '';
  if (atual && [...sel.options].some(o => o.value.toLowerCase() === atual.toLowerCase() && !o.disabled)) {
    sel.value = [...sel.options].find(o => o.value.toLowerCase() === atual.toLowerCase()).value;
  } else {
    const livre = [...sel.options].find(o => !o.disabled);
    if (livre) sel.value = livre.value;
  }
}

// ------------------------------------------------------------------ acoes

async function rkGravar(mudancas, msg) {
  const rack = rkRack();
  await cxGravar(_rk.def, { rack: { id: rack.id, ponto: rack.ponto, ...mudancas } });
  if (msg) showToast(msg);
  cxRedesenhar(_rk.id, _rk.def);
}

async function rkAcao(btn) {
  if (!_rk) return;
  const rack = rkRack();
  const el = _rk.el;
  const v = idc => (el.querySelector(`#${idc}`)?.value ?? '').trim();
  const acao = btn.dataset.rk;
  const limpar = () => { _rk.modo = null; _rk.origem = null; _rk.editEq = null; _rk.editProv = null; };

  if (acao === 'fechar') { rkFecharTela(); return; }
  if (acao === 'aba') { _rk.aba = btn.dataset.aba; _rk.sel = null; limpar(); rkRender(); return; }
  if (acao === 'cancelar') { limpar(); rkRender(); return; }
  if (acao === 'config') { limpar(); _rk.sel = null; _rk.modo = 'config'; rkRender(); return; }
  if (acao === 'novo-eq') { limpar(); _rk.sel = null; _rk.aba = 'rack'; _rk.modo = 'eq'; rkRender(); el.querySelector('#rkEqNome')?.focus(); return; }
  if (acao === 'editar-eq') { limpar(); _rk.sel = null; _rk.modo = 'eq'; _rk.editEq = btn.dataset.eq; rkRender(); return; }
  if (acao === 'novo-prov') { limpar(); _rk.sel = null; _rk.modo = 'prov'; rkRender(); el.querySelector('#rkPvNome')?.focus(); return; }
  if (acao === 'editar-prov') { limpar(); _rk.sel = null; _rk.modo = 'prov'; _rk.editProv = btn.dataset.prov; rkRender(); return; }
  if (acao === 'cabo') { _rk.cabo = btn.dataset.cabo; rkRender(); return; }
  if (acao === 'porta-provedor') { const o = _rk.origem; limpar(); _rk.origem = o; _rk.modo = 'prov'; _rk.aba = 'rack'; rkRender(); el.querySelector('#rkPvNome')?.focus(); return; }
  if (acao === 'ligar-daqui') { _rk.origem = { ..._rk.sel }; _rk.sel = null; _rk.modo = 'ligar'; rkRender(); return; }

  if (acao === 'porta') {
    const alvo = { eq: btn.dataset.eq, porta: btn.dataset.porta };
    const uso = rkUsoDasPortas(rack);
    const u = uso[rkChave(alvo.eq, alvo.porta)] || {};
    if (_rk.modo === 'ligar' && _rk.origem) {
      if (_rk.origem.eq === alvo.eq && _rk.origem.porta.toLowerCase() === alvo.porta.toLowerCase()) { limpar(); rkRender(); return; }
      if (u.lig) { showToast(`${rkPortaCurta(alvo.porta)} já está ligada. Escolha uma porta com borda verde.`, true); return; }
      const nova = { a: _rk.origem, b: alvo, tipo: _rk.cabo };
      await rkGravar({ ligacoes: [...rack.ligacoes, nova] }, 'Portas ligadas.');
      limpar(); _rk.sel = { ...nova.a }; rkRender();
      return;
    }
    if (_rk.modo === 'eq' || _rk.modo === 'prov' || _rk.modo === 'config') limpar();
    if (!u.lig && !u.provedor) { _rk.sel = null; _rk.origem = alvo; _rk.modo = 'ligar'; rkRender(); return; }
    _rk.sel = alvo; rkRender();
    return;
  }

  if (acao === 'salvar-rotulo' && _rk.sel) {
    const rotulo = v('rkRotulo');
    const eqs = rack.equipamentos.map(e => (e.id !== _rk.sel.eq ? e : {
      ...e, portas: e.portas.map(p => (p.id.toLowerCase() === _rk.sel.porta.toLowerCase() ? { ...p, rotulo } : p)),
    }));
    await rkGravar({ equipamentos: eqs }, 'Comentário salvo.');
    rkRender();
    return;
  }
  if (acao === 'desligar' && _rk.sel) {
    const u = rkUsoDasPortas(rack)[rkChave(_rk.sel.eq, _rk.sel.porta)];
    if (!u?.lig || !(await showConfirm({ title: 'Desfazer ligação', msg: `Desfazer a ligação ${u.lig.a.porta} → ${u.lig.b.porta}?`, label: 'Desfazer' }))) return;
    await rkGravar({ ligacoes: rack.ligacoes.filter(x => x.id !== u.lig.id) }, 'Ligação desfeita.');
    rkRender();
    return;
  }
  if (acao === 'salvar-eq') {
    const modelo = v('rkEqModelo');
    const nomes = modelo ? RK_MODELOS[modelo] : v('rkEqPortas').split(/[,;\n]+/).map(x => x.trim()).filter(Boolean);
    const atual = rack.equipamentos.find(e => e.id === _rk.editEq);
    const rotulos = Object.fromEntries((atual?.portas || []).map(x => [x.id.toLowerCase(), x.rotulo || '']));
    const eq = {
      id: atual?.id || '', tipo: v('rkEqTipo'), nome: v('rkEqNome'), entidade: v('rkEqEnt'),
      // modelo vazio: o da lista de portas quando e equipamento de verdade (CRS/CCR), nao DIO/OLT generico
      modelo: v('rkEqModeloTxt') || (modelo && !/^(DIO|OLT|\d)/.test(modelo) ? modelo : ''),
      portas: nomes.map(n => ({ id: n, rotulo: rotulos[n.toLowerCase()] || '' })), obs: atual?.obs || '',
    };
    if (!eq.nome) { rkErro(new Error('Informe o nome do equipamento.')); return; }
    const lista = atual ? rack.equipamentos.map(e => (e.id === atual.id ? eq : e)) : [...rack.equipamentos, eq];
    await rkGravar({ equipamentos: lista }, atual ? 'Equipamento salvo.' : 'Equipamento adicionado.');
    limpar(); rkRender();
    return;
  }
  if (acao === 'tirar-eq') {
    const eq = rack.equipamentos.find(e => e.id === _rk.editEq);
    if (!eq || !(await showConfirm({ title: 'Tirar equipamento', msg: `Tirar "${eq.nome}" do rack? As ligações e os provedores das portas dele saem junto.`, label: 'Tirar' }))) return;
    await rkGravar({
      equipamentos: rack.equipamentos.filter(e => e.id !== eq.id),
      ligacoes: rack.ligacoes.filter(lg => lg.a.eq !== eq.id && lg.b.eq !== eq.id),
      provedores: rack.provedores.filter(pv => pv.entrada.eq !== eq.id),
    }, 'Equipamento retirado.');
    limpar(); rkRender();
    return;
  }
  if (acao === 'salvar-prov') {
    const atual = rack.provedores.find(p => p.id === _rk.editProv);
    const pv = { id: atual?.id || '', nome: v('rkPvNome'), entrada: { eq: v('rkPvEq'), porta: v('rkPvPorta') }, vlans: v('rkPvVlans'), banda_mbps: Number(v('rkPvBanda') || 0), contato: atual?.contato || '', obs: atual?.obs || '' };
    if (!pv.nome) { rkErro(new Error('Informe o nome do provedor.')); return; }
    const lista = atual ? rack.provedores.map(p => (p.id === atual.id ? pv : p)) : [...rack.provedores, pv];
    await rkGravar({ provedores: lista }, atual ? 'Provedor salvo.' : 'Provedor adicionado.');
    const volta = _rk.aba === 'rack' ? pv.entrada : null;
    limpar(); _rk.sel = volta; rkRender();
    return;
  }
  if (acao === 'tirar-prov') {
    const pv = rack.provedores.find(p => p.id === _rk.editProv);
    if (!pv || !(await showConfirm({ title: 'Tirar provedor', msg: `Tirar o provedor ${pv.nome} deste rack?`, label: 'Tirar' }))) return;
    await rkGravar({ provedores: rack.provedores.filter(p => p.id !== pv.id) }, 'Provedor retirado.');
    limpar(); rkRender();
    return;
  }
  if (acao === 'salvar-config') {
    await rkGravar({ nome: v('rkCfgNome'), obs: v('rkCfgObs') }, 'Rack salvo.');
    limpar(); rkRender();
    return;
  }
  if (acao === 'excluir-rack') {
    if (!(await showConfirm({ title: 'Excluir rack', msg: `Apagar o rack "${rack.nome}" com todos os equipamentos, ligações e provedores? O ponto continua no mapa.`, label: 'Excluir' }))) return;
    await cxGravar(_rk.def, { rack: { id: rack.id, excluir: true } });
    showToast('Rack excluído.');
    cxRedesenhar(_rk.id, _rk.def);
    rkFecharTela();
  }
}
