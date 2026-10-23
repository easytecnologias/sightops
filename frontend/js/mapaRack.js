// Rack da rede neutra no mapa: ponto com os equipamentos dentro (DIO, OLT,
// borda, switch, NVR, DVR, servidor, computador), as portas de cada um, as
// ligacoes porta-a-porta e os provedores que entram. O usuario monta e liga
// ponto a ponto, como no FTTH; o monitoramento dos links vem depois e le daqui
// qual porta e de qual provedor.
//
// Usa a moldura e a gravacao dos paineis do mapa (mapaCaixas.js: cxPainelBase,
// cxGravar, cxRedesenhar). O backend valida tudo em app/services/mapa_rack.py.

const RK_TIPOS = {
  dio: 'DIO', olt: 'OLT', borda: 'Borda (roteador)', switch: 'Switch', nvr: 'Gravador (NVR)',
  dvr: 'DVR', servidor: 'Servidor', computador: 'Computador', outro: 'Outro',
};
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

// Estado de cada porta: ligacao (para onde vai) e provedor que entra nela
function rkUsoDasPortas(rack) {
  const eqs = Object.fromEntries((rack?.equipamentos || []).map(e => [e.id, e]));
  const uso = {};
  const chave = (eq, porta) => `${eq}|${String(porta).toLowerCase()}`;
  (rack?.ligacoes || []).forEach(lg => {
    uso[chave(lg.a.eq, lg.a.porta)] = { ...(uso[chave(lg.a.eq, lg.a.porta)] || {}), lig: lg, para: lg.b, nomePara: eqs[lg.b.eq]?.nome || '?' };
    uso[chave(lg.b.eq, lg.b.porta)] = { ...(uso[chave(lg.b.eq, lg.b.porta)] || {}), lig: lg, para: lg.a, nomePara: eqs[lg.a.eq]?.nome || '?' };
  });
  (rack?.provedores || []).forEach(pv => {
    const k = chave(pv.entrada.eq, pv.entrada.porta);
    uso[k] = { ...(uso[k] || {}), provedor: pv };
  });
  return { uso, chave };
}

async function rkEntidades(rack) {
  const tipos = [...new Set((rack?.equipamentos || []).map(e => RK_ENTIDADE[e.tipo]).filter(Boolean).concat(Object.values(RK_ENTIDADE)))];
  const listas = await Promise.all(tipos.map(t => ctEntidades(t)));
  const porTipo = {};
  tipos.forEach((t, i) => { porTipo[t] = listas[i] || []; });
  return porTipo;
}

function rkStatusPill(ent) {
  if (!ent) return '';
  const st = String(ent.status || '').toLowerCase();
  const cls = st === 'up' || st === 'online' ? 'rk-on' : st === 'down' || st === 'offline' ? 'rk-off' : 'rk-sem';
  const txt = cls === 'rk-on' ? 'no ar' : cls === 'rk-off' ? 'fora do ar' : 'sem leitura';
  return `<span class="rk-status ${cls}">${txt}</span>`;
}

async function rkAbrirPainel(id, def, nomePonto, latlng) {
  if (!def?.updateUrl || def.source !== 'imported') { showToast('Rack só em camadas importadas (KMZ).', true); return; }
  latlng = latlng || cxLatLngDoPonto(def, nomePonto);
  const rack = rkDoPonto(def, nomePonto, latlng);
  const ents = rack ? await rkEntidades(rack) : {};
  const entPorChave = {};
  Object.values(ents).flat().forEach(e => { entPorChave[e.entity_key] = e; });
  const { uso, chave } = rkUsoDasPortas(rack);
  const eqs = rack?.equipamentos || [];

  const cardEq = (e) => {
    const ent = e.entidade ? entPorChave[e.entidade] : null;
    const grade = e.portas.map(p => {
      const u = uso[chave(e.id, p.id)] || {};
      const cls = u.provedor ? 'rk-p-prov' : u.lig ? 'rk-p-lig' : 'rk-p-livre';
      const dica = [p.id, p.rotulo, u.provedor ? `provedor ${u.provedor.nome}` : '', u.lig ? `→ ${u.nomePara} ${u.para.porta}` : 'livre'].filter(Boolean).join(' · ');
      return `<button type="button" class="rk-porta ${cls}" data-rk="porta" data-eq="${esc(e.id)}" data-porta="${esc(p.id)}" title="${esc(dica)}">${esc(p.id.replace(/^sfp-sfpplus/, 'sfp').replace(/^ether/, 'e'))}</button>`;
    }).join('');
    const ligadas = e.portas.filter(p => uso[chave(e.id, p.id)]?.lig).length;
    return `<article class="rk-eq">
      <div class="rk-eq-topo">
        <span class="rk-tipo">${esc(RK_TIPOS[e.tipo] || e.tipo)}</span>
        <strong>${esc(e.nome)}</strong>${e.modelo ? `<small>${esc(e.modelo)}</small>` : ''}
        ${rkStatusPill(ent)}
        <span style="flex:1"></span>
        <small>${ligadas}/${e.portas.length} ligadas</small>
        <button type="button" class="ghost-action cx-ico" data-rk="editar-eq" data-eq="${esc(e.id)}" title="Editar equipamento" aria-label="Editar ${esc(e.nome)}"><i data-lucide="pencil"></i></button>
      </div>
      <div class="rk-portas">${grade}</div>
    </article>`;
  };

  const opEq = (sel) => eqs.map(e => `<option value="${esc(e.id)}" ${sel === e.id ? 'selected' : ''}>${esc(e.nome)}</option>`).join('');
  const linhasLig = (rack?.ligacoes || []).map(lg => {
    const a = eqs.find(e => e.id === lg.a.eq);
    const b = eqs.find(e => e.id === lg.b.eq);
    return `<tr><td><strong>${esc(a?.nome || '?')}</strong> <small>${esc(lg.a.porta)}</small></td><td>→</td>
      <td><strong>${esc(b?.nome || '?')}</strong> <small>${esc(lg.b.porta)}</small></td><td><small>${esc(RK_LIGACOES[lg.tipo] || lg.tipo)}</small></td>
      <td><button type="button" class="ghost-action cx-ico" data-rk="desligar" data-lig="${esc(lg.id)}" title="Desfazer ligação" aria-label="Desfazer ligação"><i data-lucide="unlink"></i></button></td></tr>`;
  }).join('');
  const linhasProv = (rack?.provedores || []).map(pv => {
    const e = eqs.find(x => x.id === pv.entrada.eq);
    return `<tr><td><strong>${esc(pv.nome)}</strong></td><td>${esc(e?.nome || '?')} <small>${esc(pv.entrada.porta)}</small></td>
      <td><small>${pv.vlans.length ? `VLAN ${esc(pv.vlans.join(', '))}` : '—'}</small></td>
      <td><button type="button" class="ghost-action cx-ico" data-rk="tirar-prov" data-prov="${esc(pv.id)}" title="Tirar provedor" aria-label="Tirar provedor ${esc(pv.nome)}"><i data-lucide="x"></i></button></td></tr>`;
  }).join('');

  const corpo = rack ? `
    <div class="form-row">
      <div class="form-group" style="margin:0"><label for="rkNome">Nome</label><input id="rkNome" maxlength="80" value="${esc(rack.nome)}"></div>
      <div class="form-group" style="margin:0"><label for="rkObs">Observação</label><input id="rkObs" maxlength="300" value="${esc(rack.obs || '')}" placeholder="ex.: sala do datacenter"></div>
    </div>
    <section><h3>Equipamentos <small>${eqs.length} · clique numa porta para ligar</small></h3>
      ${eqs.map(cardEq).join('') || '<p class="text-muted" style="margin:0;font-size:12.5px">Nenhum equipamento ainda.</p>'}
      <div id="rkFormEq" class="rk-form" hidden></div>
      <button type="button" class="secondary-action" data-rk="novo-eq" style="margin-top:8px"><i data-lucide="plus"></i> Adicionar equipamento</button>
    </section>
    <section><h3>Ligações <small>${rack.ligacoes?.length || 0}</small></h3>
      ${linhasLig ? `<table class="cx-tabela rk-tabela"><tbody>${linhasLig}</tbody></table>` : ''}
      ${eqs.length >= 2 ? `<div class="rk-form rk-ligar">
        <div class="rk-ponta"><select id="rkDeEq" aria-label="Equipamento de origem">${opEq('')}</select><select id="rkDePorta" aria-label="Porta de origem"></select></div>
        <span class="rk-seta">→</span>
        <div class="rk-ponta"><select id="rkParaEq" aria-label="Equipamento de destino">${opEq(eqs[1]?.id)}</select><select id="rkParaPorta" aria-label="Porta de destino"></select></div>
        <select id="rkLigTipo" aria-label="Tipo de ligação">${Object.entries(RK_LIGACOES).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join('')}</select>
        <button type="button" class="primary-action" data-rk="ligar"><i data-lucide="spline"></i> Ligar</button>
      </div>` : '<p class="text-muted" style="margin:0;font-size:12.5px">Com dois equipamentos você liga uma porta na outra.</p>'}
    </section>
    <section><h3>Provedores <small>entrada de cada link</small></h3>
      ${linhasProv ? `<table class="cx-tabela rk-tabela"><tbody>${linhasProv}</tbody></table>` : ''}
      ${eqs.length ? `<div class="rk-form rk-prov">
        <input id="rkProvNome" maxlength="80" placeholder="Provedor (ex.: VOE TELECOM)" aria-label="Nome do provedor">
        <div class="rk-ponta"><select id="rkProvEq" aria-label="Equipamento de entrada">${opEq('')}</select><select id="rkProvPorta" aria-label="Porta de entrada"></select></div>
        <input id="rkProvVlans" maxlength="200" placeholder="VLANs (ex.: 3030, 3031)" aria-label="VLANs do provedor">
        <button type="button" class="secondary-action" data-rk="prov"><i data-lucide="plus"></i> Adicionar</button>
      </div>` : ''}
    </section>
    <p id="cxErro" class="login-error" hidden></p>` : `
    <div class="so-note"><i data-lucide="info"></i><span>Monte o rack: DIOs, OLT, borda, switch, gravadores, servidores e computadores. Depois ligue porta a porta e marque por onde entra cada provedor.</span></div>
    <div class="form-row">
      <div class="form-group" style="margin:0"><label for="rkNome">Nome</label><input id="rkNome" maxlength="80" value="${esc(nomePonto)}"></div>
      <div class="form-group" style="margin:0"><label for="rkObs">Observação</label><input id="rkObs" maxlength="300" placeholder="ex.: sala do datacenter"></div>
    </div>
    <p id="cxErro" class="login-error" hidden></p>`;
  const rodape = `${rack ? '<button type="button" class="ghost-action cx-perigo cx-ico" data-rk="excluir" title="Excluir o rack" aria-label="Excluir o rack"><i data-lucide="trash-2"></i></button>' : ''}
    <span style="flex:1"></span>
    <button type="button" class="primary-action" data-rk="salvar"><i data-lucide="save"></i> ${rack ? 'Salvar' : 'Criar rack'}</button>`;
  const el = cxPainelBase(rack?.nome || nomePonto || 'Rack', corpo, rodape, 'Rack · rede neutra');
  el.classList.add('rk-painel');
  _cx.painel = { el, id, def, rack, nomePonto, latlng, tipo: 'rack', ents };

  const portasDe = (eqSel, portaSel, soLivres) => {
    const e = eqs.find(x => x.id === eqSel?.value);
    if (!e || !portaSel) return;
    portaSel.innerHTML = e.portas.map(p => {
      const u = uso[chave(e.id, p.id)];
      const ocupada = soLivres && u?.lig;
      return `<option value="${esc(p.id)}" ${ocupada ? 'disabled' : ''}>${esc(p.id)}${u?.lig ? ` → ${esc(u.nomePara)}` : ''}${u?.provedor ? ` (${esc(u.provedor.nome)})` : ''}</option>`;
    }).join('');
    const livre = [...portaSel.options].find(o => !o.disabled);
    if (livre) portaSel.value = livre.value;
  };
  const liga = (eqId, portaId) => {
    const s = el.querySelector(`#${eqId}`);
    const p = el.querySelector(`#${portaId}`);
    s?.addEventListener('change', () => portasDe(s, p, eqId !== 'rkProvEq'));
    portasDe(s, p, eqId !== 'rkProvEq');
  };
  liga('rkDeEq', 'rkDePorta'); liga('rkParaEq', 'rkParaPorta'); liga('rkProvEq', 'rkProvPorta');
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-rk]');
    if (b) rkAcao(b).catch(e => showToast(e?.message || 'Falha na ação.', true));
  });
  el.addEventListener('change', ev => {
    if (ev.target.id === 'rkEqTipo' || ev.target.id === 'rkEqModelo') rkFormEqAjustar(el, ev.target.id);
  });
}

function rkFormEq(el, eq) {
  const box = el.querySelector('#rkFormEq');
  if (!box) return;
  const p = _cx.painel;
  const tipo = eq?.tipo || 'switch';
  const modelos = Object.keys(RK_MODELOS);
  const modeloAtual = eq ? (Object.entries(RK_MODELOS).find(([, v]) => v.join() === eq.portas.map(x => x.id).join())?.[0] || '') : RK_MODELO_PADRAO[tipo];
  const ents = p?.ents || {};
  box.innerHTML = `
    <h4>${eq ? `Editar ${esc(eq.nome)}` : 'Novo equipamento'}</h4>
    <div class="form-row">
      <div class="form-group" style="margin:0"><label for="rkEqTipo">Tipo</label><select id="rkEqTipo">${Object.entries(RK_TIPOS).map(([k, v]) => `<option value="${k}" ${tipo === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
      <div class="form-group" style="margin:0"><label for="rkEqNome">Nome</label><input id="rkEqNome" maxlength="80" value="${esc(eq?.nome || '')}" placeholder="ex.: SWITCH JARDINS"></div>
    </div>
    <div class="form-row">
      <div class="form-group" style="margin:0"><label for="rkEqModelo">Portas</label><select id="rkEqModelo">${modelos.map(m => `<option value="${esc(m)}" ${modeloAtual === m ? 'selected' : ''}>${esc(m)}</option>`).join('')}<option value="" ${modeloAtual ? '' : 'selected'}>Outro: digitar as portas</option></select></div>
      <div class="form-group" style="margin:0"><label for="rkEqModeloTxt">Modelo</label><input id="rkEqModeloTxt" maxlength="60" value="${esc(eq?.modelo || '')}" placeholder="ex.: CRS317-1G-16S+"></div>
    </div>
    <div class="form-group" style="margin:0" id="rkEqPortasLivre" ${modeloAtual ? 'hidden' : ''}>
      <label for="rkEqPortas">Nomes das portas (separados por vírgula)</label>
      <input id="rkEqPortas" maxlength="4000" value="${esc(eq ? eq.portas.map(x => x.id).join(', ') : '')}" placeholder="ex.: ether1, ether2, sfp1">
    </div>
    <div class="form-group" style="margin:0"><label for="rkEqEnt">É um equipamento já monitorado?</label>
      <select id="rkEqEnt">${rkOpcoesEntidade(ents, tipo, eq?.entidade)}</select></div>
    <div class="rk-form-acoes">
      ${eq ? `<button type="button" class="ghost-action cx-perigo" data-rk="tirar-eq" data-eq="${esc(eq.id)}"><i data-lucide="trash-2"></i> Tirar do rack</button>` : ''}
      <span style="flex:1"></span>
      <button type="button" class="secondary-action" data-rk="cancelar-eq">Cancelar</button>
      <button type="button" class="primary-action" data-rk="salvar-eq" data-eq="${esc(eq?.id || '')}"><i data-lucide="save"></i> ${eq ? 'Salvar' : 'Adicionar'}</button>
    </div>`;
  box.hidden = false;
  lucide.createIcons();
  box.scrollIntoView({ block: 'nearest' });
  box.querySelector('#rkEqNome')?.focus();
}

function rkOpcoesEntidade(ents, tipo, atual) {
  const t = RK_ENTIDADE[tipo];
  const lista = (t && ents[t]) || [];
  const tem = lista.some(e => e.entity_key === atual);
  return `<option value="">Não</option>${lista.map(e => `<option value="${esc(e.entity_key)}" ${atual === e.entity_key ? 'selected' : ''}>${esc(e.display_name || e.entity_id)}${e.site ? ` · ${esc(e.site)}` : ''}</option>`).join('')}${atual && !tem ? `<option value="${esc(atual)}" selected>${esc(atual)}</option>` : ''}`;
}

function rkFormEqAjustar(el, origem) {
  const tipo = el.querySelector('#rkEqTipo')?.value;
  if (origem === 'rkEqTipo') {
    const m = el.querySelector('#rkEqModelo');
    if (m) m.value = RK_MODELO_PADRAO[tipo] || '';
    el.querySelector('#rkEqEnt').innerHTML = rkOpcoesEntidade(_cx.painel?.ents || {}, tipo, '');
  }
  const modelo = el.querySelector('#rkEqModelo')?.value;
  el.querySelector('#rkEqPortasLivre').hidden = Boolean(modelo);
  const txt = el.querySelector('#rkEqModeloTxt');
  if (modelo && txt && !txt.value && !/^(DIO|OLT|\d)/.test(modelo)) txt.value = modelo;
}

async function rkGravarRack(p, mudancas, msg) {
  const r = p.rack;
  await cxGravar(p.def, { rack: { id: r?.id || '', ponto: p.nomePonto, lat: p.latlng?.[0], lng: p.latlng?.[1], ...mudancas } });
  if (msg) showToast(msg);
  cxRedesenhar(p.id, p.def);
  const novo = rkDoPonto(p.def, p.nomePonto, p.latlng) || Object.values(p.def.racks || {}).find(x => x.nome === mudancas.nome);
  await rkAbrirPainel(p.id, p.def, novo?.ponto || p.nomePonto, p.latlng);
}

async function rkAcao(btn) {
  const p = _cx.painel;
  if (!p?.el || p.tipo !== 'rack') return;
  const el = p.el;
  const er = el.querySelector('#cxErro');
  const falha = e => { if (er) { er.textContent = e.message; er.hidden = false; er.scrollIntoView({ block: 'nearest' }); } };
  const v = idc => (el.querySelector(`#${idc}`)?.value ?? '').trim();
  const rack = p.rack;
  const acao = btn.dataset.rk;
  try {
    if (acao === 'salvar') {
      await rkGravarRack(p, { nome: v('rkNome'), obs: v('rkObs') }, rack ? 'Rack salvo.' : 'Rack criado. Agora adicione os equipamentos.');
    } else if (acao === 'novo-eq') {
      rkFormEq(el, null);
    } else if (acao === 'editar-eq') {
      rkFormEq(el, rack.equipamentos.find(e => e.id === btn.dataset.eq));
    } else if (acao === 'cancelar-eq') {
      el.querySelector('#rkFormEq').hidden = true;
    } else if (acao === 'salvar-eq') {
      const modelo = v('rkEqModelo');
      const nomes = modelo ? RK_MODELOS[modelo] : v('rkEqPortas').split(/[,;\n]+/).map(x => x.trim()).filter(Boolean);
      const atual = rack.equipamentos.find(e => e.id === btn.dataset.eq);
      const rotulos = Object.fromEntries((atual?.portas || []).map(x => [x.id.toLowerCase(), x.rotulo || '']));
      const eq = {
        id: atual?.id || '', tipo: v('rkEqTipo'), nome: v('rkEqNome'), modelo: v('rkEqModeloTxt'), entidade: v('rkEqEnt'),
        portas: nomes.map(n => ({ id: n, rotulo: rotulos[n.toLowerCase()] || '' })), obs: atual?.obs || '',
      };
      const lista = atual ? rack.equipamentos.map(e => (e.id === atual.id ? eq : e)) : [...rack.equipamentos, eq];
      await rkGravarRack(p, { equipamentos: lista }, atual ? 'Equipamento salvo.' : 'Equipamento adicionado.');
    } else if (acao === 'tirar-eq') {
      const eq = rack.equipamentos.find(e => e.id === btn.dataset.eq);
      if (!eq || !(await showConfirm({ title: 'Tirar equipamento', msg: `Tirar "${eq.nome}" do rack? As ligações e os provedores das portas dele saem junto.`, label: 'Tirar' }))) return;
      await rkGravarRack(p, {
        equipamentos: rack.equipamentos.filter(e => e.id !== eq.id),
        ligacoes: rack.ligacoes.filter(lg => lg.a.eq !== eq.id && lg.b.eq !== eq.id),
        provedores: rack.provedores.filter(pv => pv.entrada.eq !== eq.id),
      }, 'Equipamento retirado.');
    } else if (acao === 'porta') {
      // clique na porta: vira a origem da ligacao
      const de = el.querySelector('#rkDeEq');
      if (!de) return;
      de.value = btn.dataset.eq;
      de.dispatchEvent(new Event('change'));
      const dp = el.querySelector('#rkDePorta');
      if (dp && ![...dp.options].find(o => o.value === btn.dataset.porta && !o.disabled)) {
        showToast(`${btn.dataset.porta} já está ligada. Desfaça a ligação para trocar.`, true);
        return;
      }
      dp.value = btn.dataset.porta;
      el.querySelector('.rk-ligar')?.scrollIntoView({ block: 'nearest' });
      el.querySelector('#rkParaEq')?.focus();
    } else if (acao === 'ligar') {
      const a = { eq: v('rkDeEq'), porta: v('rkDePorta') };
      const b = { eq: v('rkParaEq'), porta: v('rkParaPorta') };
      if (!a.porta || !b.porta) { falha(new Error('Escolha as duas portas.')); return; }
      await rkGravarRack(p, { ligacoes: [...rack.ligacoes, { a, b, tipo: v('rkLigTipo') }] }, 'Portas ligadas.');
    } else if (acao === 'desligar') {
      const lg = rack.ligacoes.find(x => x.id === btn.dataset.lig);
      if (!lg || !(await showConfirm({ title: 'Desfazer ligação', msg: `Desfazer a ligação ${lg.a.porta} → ${lg.b.porta}?`, label: 'Desfazer' }))) return;
      await rkGravarRack(p, { ligacoes: rack.ligacoes.filter(x => x.id !== lg.id) }, 'Ligação desfeita.');
    } else if (acao === 'prov') {
      const pv = { nome: v('rkProvNome'), entrada: { eq: v('rkProvEq'), porta: v('rkProvPorta') }, vlans: v('rkProvVlans') };
      if (!pv.nome) { falha(new Error('Informe o nome do provedor.')); return; }
      await rkGravarRack(p, { provedores: [...rack.provedores, pv] }, 'Provedor adicionado.');
    } else if (acao === 'tirar-prov') {
      const pv = rack.provedores.find(x => x.id === btn.dataset.prov);
      if (!pv || !(await showConfirm({ title: 'Tirar provedor', msg: `Tirar o provedor ${pv.nome} deste rack?`, label: 'Tirar' }))) return;
      await rkGravarRack(p, { provedores: rack.provedores.filter(x => x.id !== pv.id) }, 'Provedor retirado.');
    } else if (acao === 'excluir') {
      if (!(await showConfirm({ title: 'Excluir rack', msg: `Apagar o rack "${rack.nome}" com todos os equipamentos, ligações e provedores? O ponto continua no mapa.`, label: 'Excluir' }))) return;
      await cxGravar(p.def, { rack: { id: rack.id, excluir: true } });
      showToast('Rack excluído.');
      cxFecharPainel(); cxRedesenhar(p.id, p.def);
    }
  } catch (e) { falha(e); }
}
