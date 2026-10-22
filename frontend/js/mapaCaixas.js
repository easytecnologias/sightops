// Mapa: caixas de CFTV e cabos (caixa -> camera).
// A caixa e um ponto da camada (pelo nome) com o que tem dentro e as portas
// do switch; o cabo e desenhado com curvas (clique no mapa = curva, clique na
// camera = fim) e a metragem sai do traçado. Tudo no meta da camada, pela
// mesma rota de edicao de camada (PATCH {caixa} / {cabo}). Excluir caixa ou
// cabo e so administrador (o servidor pede a senha dele para os demais).
// A ONU da caixa pode ser ligada numa CTO (cabo {cto:{ponto,porta}}, fibra drop):
// um por caixa, nao vai para o inventario de cameras.
// O painel lateral nao fecha ao clicar fora: so X, Cancelar ou Esc.
// Tipo da caixa: com switch (portas PoE), direto na ONU (porta LAN, camera com
// fonte ou injetor) ou so passagem/fonte (sem portas). Antiga sem tipo = switch.

const _cx = { painel: null, desenho: null, edicao: null };

const CX_ITENS = {
  switch_poe: 'Switch PoE', switch: 'Switch', onu: 'ONU', fonte: 'Fonte', nobreak: 'Nobreak',
  dio: 'DIO', roteador: 'Roteador', injetor_poe: 'Injetor PoE', outro: 'Outro',
};
const CX_UPLINK = { onu: 'ONU', fibra: 'Fibra / conversor', radio: 'Rádio', switch: 'Outro switch', outro: 'Outro' };
const CX_TIPOS = {
  switch: { nome: 'Com switch', ajuda: 'Câmeras nas portas PoE do switch da caixa' },
  onu: { nome: 'Direto na ONU', ajuda: 'Câmera na porta LAN da ONU, alimentada por fonte ou injetor' },
  passagem: { nome: 'Só passagem / fonte', ajuda: 'Sem portas: fonte, emenda ou passagem de cabo' },
};
const CX_ALIM = { fonte12: 'Fonte 12V', injetor_poe: 'Injetor PoE', poe_switch: 'PoE do switch', outro: 'Outra' };
const cxTipo = caixa => (CX_TIPOS[caixa?.tipo] ? caixa.tipo : 'switch');
const cxNomePorta = (caixa, n) => (cxTipo(caixa) === 'onu' ? `LAN${n}` : `P${n}`);
const CX_CABOS = {
  utp5e: { nome: 'UTP Cat5e', cor: '#1971c2', limite: 100 },
  utp6: { nome: 'UTP Cat6', cor: '#1864ab', limite: 100 },
  drop: { nome: 'Fibra drop', cor: '#0ea5e9', tracejado: '10 7' },
  coaxial: { nome: 'Coaxial', cor: '#7950f2' },
  outro: { nome: 'Outro', cor: '#64748b' },
};

// Ponto que tem cara de caixa pelo nome: "CAI", "CAI-01", "CX 3", "Caixa CFTV".
function cxPontoPareceCaixa(nome) {
  const n = String(nome || '').trim();
  return /^(cai|cx)(\s*[-_]?\s*\d+)?$/i.test(n) || /caixa\s*(cftv|herm)/i.test(n);
}

// O KMZ repete nome de ponto ("Caixa - S 4P" em 14 lugares): a caixa e o
// ponto pelo nome E pela posicao. Caixa antiga (sem lat/lng gravados) fica no
// inicio do primeiro cabo dela, senao no primeiro ponto com o nome.
const cxPerto = (a, b) => !!a && !!b && Math.abs(a[0] - b[0]) < 3e-5 && Math.abs(a[1] - b[1]) < 3e-5;

function cxPosDaCaixa(def, caixa) {
  if (caixa?.lat != null && caixa?.lng != null) return [+caixa.lat, +caixa.lng];
  const cabo = Object.values(def?.cabos || {}).find(c => c.caixa === caixa?.id && c.caminho?.length);
  if (cabo) return [+cabo.caminho[0][0], +cabo.caminho[0][1]];
  return cxLatLngDoPonto(def, caixa?.ponto);
}

function cxCaixaDoPonto(def, nome, latlng) {
  const chave = String(nome || '').trim().toLowerCase();
  const doNome = Object.values(def?.caixas || {}).filter(c => String(c.ponto || '').trim().toLowerCase() === chave);
  if (!latlng) return doNome.length === 1 ? doNome[0] : null;
  return doNome.find(c => cxPerto(cxPosDaCaixa(def, c), latlng)) || null;
}

function cxMetros(caminho) {
  let total = 0;
  for (let i = 1; i < caminho.length; i++) {
    const [la1, lo1] = caminho[i - 1], [la2, lo2] = caminho[i];
    const r = Math.PI / 180, dp = (la2 - la1) * r, dl = (lo2 - lo1) * r;
    const a = Math.sin(dp / 2) ** 2 + Math.cos(la1 * r) * Math.cos(la2 * r) * Math.sin(dl / 2) ** 2;
    total += 2 * 6371000 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  return total;
}

// Painel e barra ficam DENTRO do mapa, sem deixar o clique passar para ele
// (senao clicar num botao do painel virava curva do cabo).
function cxAnexar(el) {
  const alvo = _map?.getContainer?.() || document.body;
  alvo.appendChild(el);
  if (window.L?.DomEvent) {
    L.DomEvent.disableClickPropagation(el);
    L.DomEvent.disableScrollPropagation(el);
  }
}

function cxFmtMetros(m) { return `${Math.round(m).toLocaleString('pt-BR')} m`; }

// Camera de um cabo: pelo IP, senao pelo ponto da camada (mesmo casamento do mapa).
function cxCameraDoCabo(def, cabo) {
  const ip = String(cabo?.camera?.ip || '');
  if (ip && _mapCameraIndex?.byIp?.[ip]) return _mapCameraIndex.byIp[ip];
  const f = (def?.features || []).find(x => mapFeatureName(x).toLowerCase() === String(cabo?.camera?.ponto || '').toLowerCase());
  return f ? mapFindCamera(f, _mapCameraIndex) : null;
}

// 'on' | 'off' | 'sem': so "fora do ar" quem o inventario/monitoramento diz
// offline; status desconhecido nao vira alarme no mapa.
function cxEstadoCamera(cam) {
  const st = String(cam?.status || '').toLowerCase();
  if (st === 'online' || st === 'up') return 'on';
  if (st === 'offline' || st === 'down') return 'off';
  return 'sem';
}

function cxCabosDaCaixa(def, caixaId) {
  return Object.values(def?.cabos || {}).filter(c => c.caixa === caixaId && !c.cto);
}

function cxCaboDaCto(def, caixaId) {
  return Object.values(def?.cabos || {}).find(c => c.caixa === caixaId && c.cto) || null;
}

function cxDestinoDoCabo(c) {
  if (c?.cto) return `${c.cto.ponto}${c.cto.porta ? ` porta ${c.cto.porta}` : ''}`;
  return c?.camera?.ponto || c?.camera?.ip || '';
}

// ------------------------------------------------------------------ desenho no mapa

function cxMarcador(id, def, f, lat, lng) {
  const nome = mapFeatureName(f);
  const caixa = cxCaixaDoPonto(def, nome, [lat, lng]);
  const dela = caixa ? cxCabosDaCaixa(def, caixa.id) : [];
  const usadas = dela.filter(c => c.porta).length;
  const conta = !caixa ? '' : cxTipo(caixa) === 'passagem' ? (dela.length ? ` · ${dela.length} câm.` : '')
    : caixa.portas ? ` · ${usadas}/${caixa.portas}${cxTipo(caixa) === 'onu' ? ' LAN' : ''}` : '';
  const rotulo = caixa ? `${esc(caixa.nome)}${conta}` : esc(nome || 'Caixa');
  const icon = L.divIcon({
    className: '',
    html: `<div class="cx-pino${caixa ? '' : ' cx-pino-novo'}" title="${caixa ? 'Caixa de CFTV' : 'Parece uma caixa: clique para cadastrar'}">
      <span class="cx-pino-ico"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 11h18"/><path d="M8 15h2M14 15h2"/></svg></span>
      <span class="cx-pino-rot">${rotulo}</span></div>`,
    iconSize: [34, 34], iconAnchor: [17, 17],
  });
  const marker = L.marker([lat, lng], { icon, zIndexOffset: 500 });
  if (caixa) {
    _cx.marcadores = _cx.marcadores || {};
    _cx.marcadores[caixa.id] = { marker, de: [lat, lng] };
  }
  marker.on('click', () => {
    if (_cx.desenho || _cx.edicao) return; // desenhando/editando: clicar na caixa nao abre outra coisa
    cxAbrirPainel(id, def, nome, [lat, lng]);
  });
  return marker;
}

function cxDesenharCabos(id, def, group) {
  const ocultos = typeof mapOcultosDaCamada === 'function' ? mapOcultosDaCamada(id) : new Set();
  if (ocultos.has('cabos')) return;
  const filhos = typeof mapFilhosOcultos === 'function' ? mapFilhosOcultos(def) : { cabos: new Set() };
  Object.values(def?.cabos || {}).forEach(cabo => {
    if (ocultos.has(`cabo:${cabo.id}`) || filhos.cabos.has(cabo.id)) return;
    if (!Array.isArray(cabo.caminho) || cabo.caminho.length < 2) return;
    const t = CX_CABOS[cabo.tipo] || CX_CABOS.outro;
    const fora = !cabo.cto && cxEstadoCamera(cxCameraDoCabo(def, cabo)) === 'off';
    const linha = L.polyline(cabo.caminho, {
      color: fora ? '#c92a2a' : t.cor, weight: 4, opacity: 0.95, dashArray: t.tracejado || null,
    });
    const caixa = def.caixas?.[cabo.caixa];
    linha.bindTooltip(`${esc(t.nome)} · ${cxFmtMetros(cabo.metros || 0)}${cabo.porta ? ` · ${cxTipo(caixa) === 'onu' ? 'LAN' : 'porta '}${cabo.porta}` : ''} → ${cabo.cto ? 'CTO ' : ''}${esc(cxDestinoDoCabo(cabo))}${fora ? ' · câmera fora do ar' : ''}`, { sticky: true });
    linha.on('click', () => { if (!_cx.desenho && !_cx.edicao && caixa) cxAbrirPainel(id, def, caixa.ponto, cxPosDaCaixa(def, caixa)); });
    group.addLayer(linha);
  });
}

// Clique num ponto do mapa enquanto desenha: camera termina o cabo.
function cxCliqueNoPonto(def, f, cam, latlng, marker) {
  const d = _cx.desenho;
  if (!d) return false;
  setTimeout(() => marker?.closePopup?.(), 0);
  // Um clique num ponto (camera, poste...) e curva: o cabo passa por ali e
  // continua. Dois cliques na camera (ou CTO) terminam o cabo nela.
  const agora = Date.now();
  const chave = `${mapFeatureName(f)}|${latlng[0]},${latlng[1]}`;
  const duplo = d.ultimoClique?.chave === chave && agora - d.ultimoClique.t < 500;
  d.ultimoClique = { chave, t: agora };
  if (!duplo) {
    const ult = d.pontos[d.pontos.length - 1];
    if (!cxPerto(ult, latlng)) { d.pontos.push(latlng); cxAtualizarDesenho(); }
    return true;
  }
  const alvo = d.alvo === 'cto' ? 'CTO' : 'câmera';
  // a mesma camera pode estar desenhada em outra camada (a gerada do
  // inventario, por exemplo) por cima da desta: com IP ela e identificada
  // igual, entao vale; sem IP so a da mesma camada
  const outraCamada = d.def?.id !== def?.id;
  if (outraCamada && (d.alvo === 'cto' || !cam?.ip)) { showToast(`A ${alvo} precisa estar na mesma camada da caixa.`, true); return true; }
  const tipo = mapFeatureType(f, cam);
  if (d.alvo === 'cto') {
    if (tipo !== 'cto') { showToast('Dois cliques numa CTO terminam o cabo. Aqui ficou só uma curva.', true); return true; }
    if (!cxPerto(d.pontos[d.pontos.length - 1], latlng)) d.pontos.push(latlng);
    cxTerminarDesenho(null, { ponto: mapFeatureName(f), latlng });
    return true;
  }
  if (tipo !== 'camera') { showToast('Dois cliques numa câmera terminam o cabo. Aqui ficou só uma curva.', true); return true; }
  if (!cxPerto(d.pontos[d.pontos.length - 1], latlng)) d.pontos.push(latlng);
  cxTerminarDesenho({ ponto: mapFeatureName(f), ip: String(cam?.ip || '') });
  return true;
}

// ------------------------------------------------------------------ painel da caixa

function cxFecharPainel() {
  _cx.painel?.el?.remove();
  _cx.painel = null;
  document.removeEventListener('keydown', cxEsc, true);
}

function cxEsc(e) {
  if (e.key !== 'Escape') return;
  e.stopPropagation();
  if (_cx.edicao) cxFimEdicao(true);
  else if (_cx.desenho) cxCancelarDesenho(); else cxFecharPainel();
}

function cxPainelBase(titulo, corpo, rodape, eyebrow = 'Caixa de CFTV') {
  cxFecharPainel();
  const el = document.createElement('aside');
  el.className = 'cx-painel';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', titulo);
  el.innerHTML = `<header><div><p class="eyebrow">${esc(eyebrow)}</p><h2>${esc(titulo)}</h2></div>
      <button type="button" class="ghost-action" data-cx="fechar" aria-label="Fechar"><i data-lucide="x"></i></button></header>
    <div class="cx-corpo">${corpo}</div><footer>${rodape}</footer>`;
  cxAnexar(el);
  document.addEventListener('keydown', cxEsc, true);
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-cx]');
    if (b) cxAcao(b).catch(e => showToast(e?.message || 'Falha na ação.', true));
  });
  lucide.createIcons();
  return el;
}

// O switch tem a parte propria; aqui ficam os outros itens (ONU, fonte...).
const cxEItemSwitch = it => it?.tipo === 'switch_poe' || it?.tipo === 'switch';

function cxLinhaItem(it = {}) {
  const opcoes = Object.entries(CX_ITENS).filter(([k]) => !cxEItemSwitch({ tipo: k }));
  return `<div class="cx-item">
    <select data-cx-it="tipo" aria-label="Tipo">${opcoes.map(([k, v]) => `<option value="${k}" ${it.tipo === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select>
    <input data-cx-it="modelo" placeholder="Modelo (opcional)" maxlength="80" value="${esc(it.modelo || '')}" aria-label="Modelo">
    <input data-cx-it="qtd" type="number" min="1" max="99" value="${Number(it.qtd || 1)}" aria-label="Quantidade" title="Quantidade">
    <button type="button" class="cx-item-x" data-cx="tirar-item" aria-label="Tirar item" title="Tirar item"><i data-lucide="x"></i></button></div>`;
}

function cxAbrirPainel(id, def, nomePonto, latlng) {
  if (!def?.updateUrl || def.source !== 'imported') { showToast('Caixas só em camadas importadas (KMZ).', true); return; }
  latlng = latlng || cxLatLngDoPonto(def, nomePonto);
  const caixa = cxCaixaDoPonto(def, nomePonto, latlng);
  // caixa nova: o tipo e escolhido (nao presume switch); antiga sem tipo = switch
  const tipo = caixa ? cxTipo(caixa) : '';
  const itens = caixa?.itens?.length ? caixa.itens.filter(it => !cxEItemSwitch(it)) : [{ tipo: 'fonte', qtd: 1 }];
  const caboCto = caixa ? cxCaboDaCto(def, caixa.id) : null;
  const portas = caixa ? Number(caixa.portas || 0) : 0;
  const cabos = caixa ? cxCabosDaCaixa(def, caixa.id) : [];
  const porPorta = Object.fromEntries(cabos.filter(c => c.porta).map(c => [c.porta, c]));
  const statusCabo = c => cxEstadoCamera(cxCameraDoCabo(def, c));
  const uplinks = caixa ? Number(caixa.uplinks ?? 1) : 1;
  const uplinkPara = caixa?.uplink_para || 'onu';
  const portaCel = n => {
    const c = porPorta[n];
    const rot = cxNomePorta(caixa, n);
    return `<span class="cx-porta ${c ? `cx-p-${statusCabo(c)}` : 'cx-p-livre'}" title="${c ? esc(`${rot}: ${c.camera?.ponto || c.camera?.ip}${c.alimentacao ? ` · ${CX_ALIM[c.alimentacao] || c.alimentacao}` : ''}`) : `${rot} livre`}">${tipo === 'onu' ? rot : n}</span>`;
  };
  const grade = Array.from({ length: portas }, (_, i) => portaCel(i + 1)).join('') + (tipo === 'onu'
    ? `<span class="cx-porta cx-p-up" title="${esc(caboCto ? `PON → CTO ${cxDestinoDoCabo(caboCto)}` : 'PON (ligue à CTO)')}">PON</span>`
    : Array.from({ length: uplinks }, (_, i) =>
      `<span class="cx-porta cx-p-up" title="${esc(`Uplink ${uplinks > 1 ? i + 1 : ''} → ${CX_UPLINK[uplinkPara] || uplinkPara}${caixa?.uplink_obs ? ` (${caixa.uplink_obs})` : ''}`)}">UP${uplinks > 1 ? i + 1 : ''}</span>`).join(''));
  // modelo do switch: o salvo, senao o do item "Switch PoE" (caixas antigas)
  const itemSwitch = (caixa?.itens || []).find(it => it.tipo === 'switch_poe' || it.tipo === 'switch');
  const itemOnu = (caixa?.itens || []).find(it => it.tipo === 'onu');
  const swModelo = tipo === 'switch' ? (caixa?.switch_modelo || itemSwitch?.modelo || '') : '';
  const onuModelo = tipo === 'onu' ? (caixa?.switch_modelo || '') : (itemOnu?.modelo || '');
  const temOnu = (caixa?.itens || []).some(it => it.tipo === 'onu') || uplinkPara === 'onu';
  const blocoCto = sempre => !caixa ? '' : caboCto ? `<div class="cx-cto">
      <i data-lucide="git-commit-horizontal"></i>
      <div><strong>ONU → CTO ${esc(cxDestinoDoCabo(caboCto))}</strong>
        <small>${esc((CX_CABOS[caboCto.tipo] || CX_CABOS.outro).nome)} · ${cxFmtMetros(caboCto.metros || 0)} (${cxFmtMetros(caboCto.metros_com_folga || caboCto.metros || 0)} com folga)</small></div>
      <button type="button" class="ghost-action" data-cx="editar-cabo" data-id="${esc(caboCto.id)}" aria-label="Editar traçado" title="Editar traçado"><i data-lucide="pencil"></i></button>
      <button type="button" class="ghost-action" data-cx="excluir-cabo" data-id="${esc(caboCto.id)}" aria-label="Excluir cabo da CTO"><i data-lucide="trash-2"></i></button></div>`
    : (sempre || temOnu) ? `<div class="cx-cto cx-cto-vazio"><i data-lucide="git-commit-horizontal"></i>
      <div><strong>ONU sem CTO</strong><small>Se a ONU desta caixa vem de uma CTO, ligue com o cabo drop.</small></div>
      <button type="button" class="secondary-action" data-cx="ligar-cto">Ligar à CTO</button></div>` : '';
  const linhasCabo = cabos.sort((a, b) => (a.porta || 99) - (b.porta || 99)).map(c => {
    const t = CX_CABOS[c.tipo] || CX_CABOS.outro;
    const st = statusCabo(c);
    const cam = cxCameraDoCabo(def, c);
    const longe = t.limite && (c.metros_com_folga || c.metros) > t.limite;
    return `<tr class="${st === 'off' ? 'cx-tr-off' : ''}"><td>${c.porta ? cxNomePorta(caixa, c.porta) : '—'}</td>
      <td><strong>${esc(cam?.titulo || c.camera?.ponto || c.camera?.ip || '')}</strong>${cam?.ip ? ` <small>${esc(cam.ip)}</small>` : ''}${c.alimentacao ? ` <small>· ${esc(CX_ALIM[c.alimentacao] || c.alimentacao)}</small>` : ''}${st === 'off' ? ' <small class="cx-off">fora do ar</small>' : ''}</td>
      <td>${tipo === 'passagem' ? '' : `<input class="cx-vlan" data-cx-vlan="${esc(c.id)}" type="number" min="1" max="4094" value="${esc(c.vlan || '')}" placeholder="${esc(caixa?.switch_vlan || 'VLAN')}" title="VLAN desta porta (vazio = a da caixa)" aria-label="VLAN da porta">`}</td>
      <td>${esc(t.nome)} ${cxFmtMetros(c.metros || 0)}${longe ? ` <small class="cx-off" title="Acima de ${t.limite} m o PoE/UTP perde sinal">acima de ${t.limite} m</small>` : ''}</td>
      <td class="cx-acoes"><button type="button" class="ghost-action" data-cx="editar-cabo" data-id="${esc(c.id)}" aria-label="Editar traçado" title="Editar traçado"><i data-lucide="pencil"></i></button><button type="button" class="ghost-action" data-cx="excluir-cabo" data-id="${esc(c.id)}" aria-label="Excluir cabo" title="Excluir cabo"><i data-lucide="trash-2"></i></button></td></tr>`;
  }).join('');
  const tituloPortas = tipo === 'onu' ? `Portas LAN da ONU <small>${cabos.filter(c => c.porta).length} de ${portas} LAN em uso</small>`
    : tipo === 'passagem' ? `Câmeras desta caixa <small>${cabos.length} ligada(s), sem porta</small>`
    : `Portas do switch <small title="VLAN em branco na porta = a VLAN da caixa">${cabos.filter(c => c.porta).length} de ${portas} PoE em uso${uplinks ? ` · uplink → ${esc(CX_UPLINK[uplinkPara] || uplinkPara)}` : ''}</small>`;
  const corpo = `
    ${caixa ? '' : '<div class="so-note"><i data-lucide="info"></i><span>Este ponto vira uma caixa de CFTV. Escolha o tipo: com switch, câmera direto na ONU ou só passagem/fonte.</span></div>'}
    <div class="form-group" style="margin:0"><label for="cxNome">Nome da caixa</label><input id="cxNome" maxlength="80" value="${esc(caixa?.nome || nomePonto)}"></div>
    <fieldset class="cx-tipos"><legend>Tipo de caixa</legend>
      ${Object.entries(CX_TIPOS).map(([k, v]) => `<label class="nt-pill" title="${esc(v.ajuda)}"><input type="radio" name="cxTipoCaixa" value="${k}" ${tipo === k ? 'checked' : ''}><span>${esc(v.nome)}</span></label>`).join('')}
      <small class="text-muted" id="cxTipoAjuda" style="flex-basis:100%"></small></fieldset>
    <section class="cx-switch" data-cx-so="switch"><h3>Switch <small>nome e portas vão para o inventário das câmeras</small></h3>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxSwNome">Nome do switch</label><input id="cxSwNome" maxlength="60" value="${esc(tipo === 'switch' ? caixa?.switch_nome || '' : '')}" placeholder="ex.: SW-CFTV-01"></div>
        <div class="form-group" style="margin:0"><label for="cxSwModelo">Modelo</label><input id="cxSwModelo" maxlength="80" value="${esc(swModelo)}" placeholder="ex.: Hikvision 4+1 PoE"></div>
      </div>
      <div class="cx-sw-linha">
        <div class="form-group" style="margin:0"><label for="cxPortas">Portas PoE</label><input id="cxPortas" type="number" min="0" max="64" value="${tipo === 'switch' ? portas : 8}"></div>
        <div class="form-group" style="margin:0"><label for="cxUplinks">Uplink</label><input id="cxUplinks" type="number" min="0" max="8" value="${uplinks}"></div>
        <div class="form-group" style="margin:0"><label for="cxSwVlan" title="Vale para as portas sem VLAN própria">VLAN padrão</label><input id="cxSwVlan" type="number" min="1" max="4094" value="${esc(caixa?.switch_vlan || '')}" placeholder="ex.: 120"></div>
      </div>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxUplinkPara">Uplink liga em</label><select id="cxUplinkPara">${Object.entries(CX_UPLINK).map(([k, v]) => `<option value="${k}" ${uplinkPara === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
        <div class="form-group" style="margin:0"><label for="cxSwIp">IP do switch</label><input id="cxSwIp" maxlength="45" value="${esc(caixa?.switch_ip || '')}" placeholder="opcional"></div>
      </div>
      ${blocoCto(false)}
    </section>
    <section class="cx-switch" data-cx-so="onu"><h3>ONU <small>a câmera liga na porta LAN; nome e porta vão para o inventário</small></h3>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxOnuNome">Nome da ONU</label><input id="cxOnuNome" maxlength="60" value="${esc(tipo === 'onu' ? caixa?.switch_nome || '' : '')}" placeholder="vazio = ONU ${esc(caixa?.nome || nomePonto || '')}"></div>
        <div class="form-group" style="margin:0"><label for="cxOnuModelo">Modelo</label><input id="cxOnuModelo" maxlength="80" value="${esc(onuModelo)}" placeholder="ex.: FiberHome AN5506-04"></div>
      </div>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxLan">Portas LAN</label><input id="cxLan" type="number" min="1" max="8" value="${tipo === 'onu' ? portas : 4}"></div>
        <div class="form-group" style="margin:0"><label for="cxOnuVlan" title="Vale para as portas sem VLAN própria">VLAN padrão</label><input id="cxOnuVlan" type="number" min="1" max="4094" value="${esc(caixa?.switch_vlan || '')}" placeholder="opcional"></div>
      </div>
      ${blocoCto(true)}
    </section>
    <section class="cx-bloco"><h3>O que tem dentro <small>fonte, nobreak, DIO…</small></h3>
      <div class="cx-item-cab"><span>Item</span><span>Modelo</span><span>Qtd</span><span></span></div>
      <div id="cxItens">${itens.map(cxLinhaItem).join('')}</div>
      <button type="button" class="cx-mais" data-cx="mais-item"><i data-lucide="plus"></i> Adicionar item</button></section>
    ${caixa ? `<section data-cx-so="${tipo}"><h3>${tituloPortas}</h3>
      ${tipo === 'passagem' ? '' : `<div class="cx-portas">${grade || '<span class="text-muted">Sem portas informadas.</span>'}</div>`}
      ${cabos.length ? `<table class="cx-tabela"><tbody>${linhasCabo}</tbody></table>` : '<p class="text-muted" style="margin:6px 0 0">Nenhuma câmera ligada ainda. Use "Ligar câmera".</p>'}
    </section>` : ''}
    <div class="form-group" style="margin:0"><label for="cxObs">Observação</label><input id="cxObs" maxlength="300" value="${esc(caixa?.obs || '')}" placeholder="ex.: chave do cadeado com o síndico"></div>
    <p id="cxErro" class="login-error" hidden></p>`;
  const rodape = `${caixa ? `<button type="button" class="ghost-action cx-perigo cx-ico" data-cx="excluir-caixa" title="Excluir caixa" aria-label="Excluir caixa"><i data-lucide="trash-2"></i></button>
    <button type="button" class="ghost-action cx-ico" data-cx="mover" title="Mover a caixa (arrastar no mapa)" aria-label="Mover caixa"><i data-lucide="move"></i></button>` : ''}
    <span style="flex:1"></span>
    ${caixa ? '<button type="button" class="secondary-action" data-cx="ligar"><i data-lucide="cable"></i> Ligar câmera</button>' : ''}
    <button type="button" class="primary-action" data-cx="salvar"><i data-lucide="save"></i> ${caixa ? 'Salvar' : 'Cadastrar caixa'}</button>`;
  const el = cxPainelBase(caixa?.nome || nomePonto || 'Caixa', corpo, rodape);
  // so a parte do tipo escolhido aparece (as portas, so do tipo salvo)
  const aplicarTipo = () => {
    const t = el.querySelector('input[name="cxTipoCaixa"]:checked')?.value || '';
    el.querySelectorAll('[data-cx-so]').forEach(s => { s.style.display = s.dataset.cxSo === t ? '' : 'none'; });
    const aj = el.querySelector('#cxTipoAjuda');
    if (aj) aj.textContent = t ? CX_TIPOS[t].ajuda + (caixa && t !== tipo ? '. Salve para ver as portas.' : '') : 'Escolha como as câmeras desta caixa são ligadas.';
  };
  el.addEventListener('change', ev => { if (ev.target.name === 'cxTipoCaixa') aplicarTipo(); });
  aplicarTipo();
  const latlngCaixa = latlng || cxLatLngDoPonto(def, nomePonto);
  _cx.painel = { el, id, def, caixa, nomePonto, latlng: latlngCaixa };
}

function cxLatLngDoPonto(def, nome) {
  const f = (def?.features || []).find(x => mapFeatureName(x).toLowerCase() === String(nome || '').toLowerCase() && x.geometry?.type === 'Point');
  const c = f?.geometry?.coordinates;
  return c ? [+c[1], +c[0]] : null;
}

async function cxGravar(def, corpo) {
  const res = await api(def.updateUrl, { method: 'PATCH', body: JSON.stringify(corpo) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok) throw new Error(data?.detail || 'Não foi possível salvar.');
  def.caixas = data.caixas || {};
  def.cabos = data.cabos || {};
  if (data.ctos) def.ctos = data.ctos;
  return data;
}

function cxRedesenhar(id, def) {
  const st = _mapLayerGroups?.[id];
  if (st?.active) reRenderMapLayerGroup(id, def);
}

async function cxAcao(btn) {
  const p = _cx.painel;
  const acao = btn.dataset.cx;
  if (acao === 'fechar') return cxFecharPainel();
  if (acao === 'mais-item') {
    document.getElementById('cxItens')?.insertAdjacentHTML('beforeend', cxLinhaItem({ tipo: 'onu', qtd: 1 }));
    lucide.createIcons();
    return;
  }
  if (acao === 'tirar-item') { btn.closest('.cx-item')?.remove(); return; }
  if (!p) return;
  if (acao === 'salvar') {
    const sw = (p.caixa?.itens || []).filter(cxEItemSwitch); // nao aparecem na lista, mas ficam
    const itens = [...sw, ...[...p.el.querySelectorAll('.cx-item')].map(r => ({
      tipo: r.querySelector('[data-cx-it="tipo"]').value,
      modelo: r.querySelector('[data-cx-it="modelo"]').value.trim(),
      qtd: Number(r.querySelector('[data-cx-it="qtd"]').value || 1),
    }))];
    try {
      const v = idc => document.getElementById(idc)?.value ?? '';
      const tipo = p.el.querySelector('input[name="cxTipoCaixa"]:checked')?.value;
      if (!tipo) throw new Error('Escolha o tipo da caixa: com switch, direto na ONU ou só passagem.');
      const equip = tipo === 'switch'
        ? { portas: Number(v('cxPortas') || 0), switch_nome: v('cxSwNome').trim(), switch_modelo: v('cxSwModelo').trim(), switch_ip: v('cxSwIp').trim(),
            switch_vlan: v('cxSwVlan').trim(), uplinks: Number(v('cxUplinks') || 0), uplink_para: v('cxUplinkPara') || 'onu' }
        : tipo === 'onu'
          ? { portas: Number(v('cxLan') || 0), switch_nome: v('cxOnuNome').trim(), switch_modelo: v('cxOnuModelo').trim(), switch_ip: '',
              switch_vlan: v('cxOnuVlan').trim(), uplinks: 0, uplink_para: 'onu' }
          : { portas: 0, switch_nome: '', switch_modelo: '', switch_ip: '', switch_vlan: '', uplinks: 0, uplink_para: 'onu' };
      await cxGravar(p.def, { caixa: { id: p.caixa?.id || '', ponto: p.nomePonto, lat: p.latlng?.[0], lng: p.latlng?.[1], nome: v('cxNome').trim(),
        tipo, itens, obs: v('cxObs').trim(), ...equip } });
    } catch (e) {
      const er = document.getElementById('cxErro');
      if (er) { er.textContent = e.message; er.hidden = false; }
      return;
    }
    const mudaram = [...p.el.querySelectorAll('[data-cx-vlan]')]
      .map(i => ({ cabo: p.def.cabos?.[i.dataset.cxVlan], vlan: i.value.trim() }))
      .filter(x => x.cabo && String(x.cabo.vlan || '') !== x.vlan);
    for (const { cabo, vlan } of mudaram) {
      try {
        await cxGravar(p.def, { cabo: { id: cabo.id, caixa: cabo.caixa, camera: cabo.camera, caminho: cabo.caminho,
          tipo: cabo.tipo, porta: cabo.porta, folga_pct: cabo.folga_pct, vlan } });
      } catch (e) {
        const er = document.getElementById('cxErro');
        if (er) { er.textContent = `${cabo.porta ? cxNomePorta(p.def.caixas?.[cabo.caixa], cabo.porta) : 'Cabo'}: ${e.message}`; er.hidden = false; }
        return;
      }
    }
    showToast(p.caixa ? 'Caixa salva.' : 'Caixa cadastrada. Agora ligue as câmeras.');
    cxRedesenhar(p.id, p.def);
    cxAbrirPainel(p.id, p.def, p.nomePonto, p.latlng);
    return;
  }
  if (acao === 'excluir-cabo') {
    const cabo = p.def.cabos?.[btn.dataset.id];
    if (!cabo || !(await showConfirm({ title: 'Excluir cabo', msg: cabo.cto ? `Tirar do mapa o cabo da ONU até a CTO ${cxDestinoDoCabo(cabo)}?` : `Tirar do mapa o cabo da ${cabo.porta ? `porta ${cxNomePorta(p.caixa, cabo.porta)}` : 'caixa'} até ${cabo.camera?.ponto || cabo.camera?.ip}?`, label: 'Excluir' }))) return;
    await cxGravar(p.def, { cabo: { id: cabo.id, excluir: true } });
    showToast('Cabo excluído.');
    cxRedesenhar(p.id, p.def);
    cxAbrirPainel(p.id, p.def, p.nomePonto, p.latlng);
    return;
  }
  if (acao === 'excluir-caixa') {
    const n = cxCabosDaCaixa(p.def, p.caixa.id).length + (cxCaboDaCto(p.def, p.caixa.id) ? 1 : 0);
    if (!(await showConfirm({ title: 'Excluir caixa', msg: `Excluir a caixa "${p.caixa.nome}"${n ? ` e os ${n} cabo(s) dela` : ''}? O ponto continua no mapa.`, label: 'Excluir' }))) return;
    await cxGravar(p.def, { caixa: { id: p.caixa.id, excluir: true } });
    showToast('Caixa excluída.');
    cxFecharPainel();
    cxRedesenhar(p.id, p.def);
    return;
  }
  if (acao === 'ligar') return cxIniciarDesenho();
  if (acao === 'ligar-cto') return cxIniciarDesenho('cto');
  if (acao === 'editar-cabo') return cxEditarTracado(btn.dataset.id);
  if (acao === 'mover') return cxMoverCaixa();
  if (acao === 'salvar-cabo') return cxSalvarCabo();
  if (acao === 'cancelar-cabo') { cxCancelarDesenho(); return; }
}

// ------------------------------------------------------------------ editar o traçado de um cabo
// Pontas presas (caixa e camera/CTO). Arrastar uma curva move; arrastar a
// bolinha do meio de um trecho cria curva; dois cliques numa curva apaga.

function cxAlca(latlng, meio) {
  return L.marker(latlng, {
    draggable: true, zIndexOffset: 1000, bubblingMouseEvents: false,
    icon: L.divIcon({ className: '', html: `<span class="cx-alca${meio ? ' cx-alca-meio' : ''}"></span>`, iconSize: [16, 16], iconAnchor: [8, 8] }),
  });
}

function cxEditarTracado(caboId) {
  const p = _cx.painel;
  const cabo = p?.def?.cabos?.[caboId];
  if (!cabo || !Array.isArray(cabo.caminho) || cabo.caminho.length < 2) return;
  if (typeof mapEditIsActive === 'function' && Object.keys(_mapLayerGroups || {}).some(k => mapEditIsActive(k))) {
    showToast('Saia do modo de edição de pontos antes de editar um cabo.', true);
    return;
  }
  p.el.hidden = true;
  const t = CX_CABOS[cabo.tipo] || CX_CABOS.outro;
  const ed = {
    p, cabo, pontos: cabo.caminho.map(x => [+x[0], +x[1]]),
    linha: L.polyline(cabo.caminho, { color: '#f59f00', weight: 5, opacity: 0.95 }).addTo(_map),
    alcas: L.layerGroup().addTo(_map),
  };
  const barra = document.createElement('div');
  barra.className = 'cx-barra';
  barra.innerHTML = `<span class="cx-barra-dot"></span><strong>Editando ${esc(t.nome)} até ${cabo.cto ? 'CTO ' : ''}${esc(cxDestinoDoCabo(cabo))}</strong>
    <span class="cx-barra-txt">Arraste as curvas. A bolinha do meio cria curva nova. Dois cliques numa curva apaga.</span>
    <span class="cx-barra-m" id="cxBarraM">${cxFmtMetros(cxMetros(ed.pontos))}</span>
    <button type="button" data-cxb="cancelar">Cancelar</button><button type="button" data-cxb="salvar" class="cx-barra-ok">Salvar traçado</button>`;
  cxAnexar(barra);
  ed.barra = barra;
  barra.addEventListener('click', ev => {
    const b = ev.target.closest('[data-cxb]');
    if (b?.dataset.cxb === 'cancelar') cxFimEdicao(true);
    if (b?.dataset.cxb === 'salvar') cxSalvarTracado().catch(e => showToast(e?.message || 'Não foi possível salvar.', true));
  });
  ed.zoomDuplo = _map.doubleClickZoom.enabled();
  _map.doubleClickZoom.disable();
  _cx.edicao = ed;
  cxDesenharAlcas();
}

function cxAtualizarEdicao() {
  const ed = _cx.edicao;
  ed.linha.setLatLngs(ed.pontos);
  const m = document.getElementById('cxBarraM');
  if (m) m.textContent = cxFmtMetros(cxMetros(ed.pontos));
}

function cxDesenharAlcas() {
  const ed = _cx.edicao;
  if (!ed) return;
  ed.alcas.clearLayers();
  const ult = ed.pontos.length - 1;
  // curvas (as pontas ficam presas na caixa e na camera/CTO)
  for (let i = 1; i < ult; i++) {
    const mk = cxAlca(ed.pontos[i], false);
    mk.on('drag', e => { const ll = e.target.getLatLng(); ed.pontos[i] = [ll.lat, ll.lng]; cxAtualizarEdicao(); });
    mk.on('dragend', cxDesenharAlcas);
    mk.on('dblclick', e => {
      L.DomEvent.stop(e);
      ed.pontos.splice(i, 1);
      cxAtualizarEdicao();
      cxDesenharAlcas();
    });
    mk.bindTooltip('Arraste para mover · dois cliques apaga', { direction: 'top', offset: [0, -8] });
    ed.alcas.addLayer(mk);
  }
  // meio de cada trecho: arrastar cria uma curva ali
  for (let i = 0; i < ult; i++) {
    const a = ed.pontos[i], b = ed.pontos[i + 1];
    const mk = cxAlca([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], true);
    let novo = -1;
    mk.on('dragstart', () => { novo = i + 1; ed.pontos.splice(novo, 0, [a[0], a[1]]); });
    mk.on('drag', e => { const ll = e.target.getLatLng(); if (novo > 0) { ed.pontos[novo] = [ll.lat, ll.lng]; cxAtualizarEdicao(); } });
    mk.on('dragend', cxDesenharAlcas);
    mk.bindTooltip('Arraste para criar uma curva', { direction: 'top', offset: [0, -8] });
    ed.alcas.addLayer(mk);
  }
}

function cxFimEdicao(reabrir) {
  const ed = _cx.edicao;
  if (!ed) return;
  if (ed.mover) { ed.fim(reabrir); return; }
  ed.linha.remove();
  ed.alcas.remove();
  ed.barra.remove();
  if (ed.zoomDuplo) _map.doubleClickZoom.enable();
  _cx.edicao = null;
  if (reabrir && ed.p?.el) ed.p.el.hidden = false;
}

async function cxSalvarTracado() {
  const ed = _cx.edicao;
  if (!ed) return;
  const c = ed.cabo, p = ed.p;
  const base = { id: c.id, caixa: c.caixa, caminho: ed.pontos, tipo: c.tipo, folga_pct: c.folga_pct };
  await cxGravar(p.def, { cabo: c.cto ? { ...base, cto: c.cto } : { ...base, camera: c.camera, porta: c.porta, vlan: c.vlan || '' } });
  cxFimEdicao(false);
  const novo = p.def.cabos?.[c.id];
  showToast(`Traçado salvo: ${cxFmtMetros(novo?.metros || cxMetros(ed.pontos))}.`);
  cxRedesenhar(p.id, p.def);
  cxAbrirPainel(p.id, p.def, p.nomePonto, p.latlng);
}

// ------------------------------------------------------------------ mover a caixa
// A caixa vira arrastavel; ao soltar, o servidor move o ponto no KMZ (pelo
// nome + posicao antiga), a posicao da caixa e a ponta dos cabos dela.

function cxMoverCaixa() {
  const p = _cx.painel;
  const m = p?.caixa && _cx.marcadores?.[p.caixa.id];
  if (!m?.marker || _cx.desenho || _cx.edicao) return;
  if (typeof mapEditIsActive === 'function' && Object.keys(_mapLayerGroups || {}).some(k => mapEditIsActive(k))) {
    showToast('Saia do modo de edição de pontos antes de mover a caixa.', true);
    return;
  }
  p.el.hidden = true;
  const barra = document.createElement('div');
  barra.className = 'cx-barra';
  barra.innerHTML = `<span class="cx-barra-dot"></span><strong>Movendo ${esc(p.caixa.nome)}</strong>
    <span class="cx-barra-txt">Arraste a caixa para o lugar certo e solte. Os cabos dela acompanham.</span>
    <button type="button" data-cxb="cancelar">Cancelar</button>`;
  cxAnexar(barra);
  const fim = (reabrir) => {
    m.marker.dragging?.disable();
    m.marker.off('dragend', aoSoltar);
    barra.remove();
    _cx.edicao = null;
    if (reabrir) { m.marker.setLatLng(m.de); p.el.hidden = false; }
  };
  const aoSoltar = async () => {
    const ll = m.marker.getLatLng();
    try {
      await cxGravar(p.def, { caixa: { id: p.caixa.id, de: { lat: m.de[0], lng: m.de[1] }, mover: { lat: ll.lat, lng: ll.lng } } });
    } catch (e) {
      showToast(e.message, true);
      fim(true);
      return;
    }
    fim(false);
    showToast(`${p.caixa.nome} movida. Os cabos dela foram refeitos a partir do novo lugar.`);
    await loadMapLayers();
  };
  barra.addEventListener('click', ev => { if (ev.target.closest('[data-cxb="cancelar"]')) fim(true); });
  m.marker.dragging?.enable();
  m.marker.on('dragend', aoSoltar);
  // Esc cancela (cxEsc chama cxFimEdicao quando ha _cx.edicao)
  _cx.edicao = { mover: true, fim };
}

// ------------------------------------------------------------------ desenhar o cabo

function cxIniciarDesenho(alvo = 'camera') {
  const p = _cx.painel;
  if (!p?.caixa || !p.latlng || _cx.edicao) return;
  if (typeof mapEditIsActive === 'function' && Object.keys(_mapLayerGroups || {}).some(k => mapEditIsActive(k))) {
    showToast('Saia do modo de edição de pontos antes de ligar um cabo.', true);
    return;
  }
  p.el.hidden = true;
  const cor = alvo === 'cto' ? CX_CABOS.drop.cor : '#1971c2';
  const linha = L.polyline([p.latlng], { color: cor, weight: 4, dashArray: '10 8' }).addTo(_map);
  const fantasma = L.polyline([], { color: cor, weight: 2, dashArray: '4 6', opacity: 0.7 }).addTo(_map);
  const barra = document.createElement('div');
  barra.className = 'cx-barra';
  barra.innerHTML = `<span class="cx-barra-dot"></span><strong>${alvo === 'cto' ? `Ligando a ONU da ${esc(p.caixa.nome)} à CTO` : `Ligando câmera à ${esc(p.caixa.nome)}`}</strong>
    <span class="cx-barra-txt">Clique no mapa ou num ponto para fazer curva (poste, esquina, outra câmera). <b>Dois cliques ${alvo === 'cto' ? 'na CTO' : 'na câmera'}</b> terminam o cabo.</span>
    <span class="cx-barra-m" id="cxBarraM">0 m</span>
    <button type="button" data-cxb="desfazer">Desfazer ponto</button><button type="button" data-cxb="cancelar">Cancelar</button>`;
  cxAnexar(barra);
  barra.addEventListener('click', ev => {
    const b = ev.target.closest('[data-cxb]');
    if (!b) return;
    if (b.dataset.cxb === 'cancelar') cxCancelarDesenho();
    if (b.dataset.cxb === 'desfazer' && _cx.desenho.pontos.length > 1) { _cx.desenho.pontos.pop(); cxAtualizarDesenho(); }
  });
  const aoClicar = e => { _cx.desenho.pontos.push([e.latlng.lat, e.latlng.lng]); cxAtualizarDesenho(); };
  const aoMover = e => {
    const ult = _cx.desenho.pontos[_cx.desenho.pontos.length - 1];
    fantasma.setLatLngs([ult, [e.latlng.lat, e.latlng.lng]]);
  };
  _map.on('click', aoClicar);
  _map.on('mousemove', aoMover);
  _map.getContainer().classList.add('cx-desenhando');
  const zoomDuplo = _map.doubleClickZoom.enabled();
  _map.doubleClickZoom.disable();
  _cx.desenho = { alvo, def: p.def, id: p.id, caixa: p.caixa, pontos: [p.latlng], linha, fantasma, barra, aoClicar, aoMover, zoomDuplo };
}

function cxAtualizarDesenho() {
  const d = _cx.desenho;
  d.linha.setLatLngs(d.pontos);
  d.fantasma.setLatLngs([]);
  const m = document.getElementById('cxBarraM');
  if (m) m.textContent = cxFmtMetros(cxMetros(d.pontos));
}

function cxLimparDesenho() {
  const d = _cx.desenho;
  if (!d) return;
  _map.off('click', d.aoClicar);
  _map.off('mousemove', d.aoMover);
  _map.getContainer().classList.remove('cx-desenhando');
  d.linha.remove();
  d.fantasma.remove();
  d.barra.remove();
  if (d.zoomDuplo) _map.doubleClickZoom.enable();
  _cx.desenho = null;
}

function cxCancelarDesenho() {
  const p = _cx.painel;
  cxLimparDesenho();
  // do formulario do cabo volta ao painel da caixa; do desenho, reabre o painel
  if (p?.novoCabo) cxAbrirPainel(p.id, p.def, p.nomePonto, p.latlng);
  else if (p?.el) p.el.hidden = false;
}

function cxTerminarDesenho(camera, cto = null) {
  const d = _cx.desenho;
  const metros = cxMetros(d.pontos);
  const caixa = d.caixa;
  const ocupadas = new Set(cxCabosDaCaixa(d.def, caixa.id).map(c => c.porta).filter(Boolean));
  const livres = Array.from({ length: Number(caixa.portas || 0) }, (_, i) => i + 1).filter(n => !ocupadas.has(n));
  d.camera = camera;
  d.cto = cto;
  d.barra.hidden = true;
  // o traçado acabou: a linha-guia para de seguir o mouse e clique no mapa
  // nao vira mais curva enquanto o formulario esta aberto
  _map.off('click', d.aoClicar);
  _map.off('mousemove', d.aoMover);
  _map.getContainer().classList.remove('cx-desenhando');
  d.fantasma.setLatLngs([]);
  d.linha.setLatLngs(d.pontos);
  d.linha.setStyle({ dashArray: null });
  const padrao = cto ? 'drop' : 'utp5e';
  const tipoCx = cxTipo(caixa);
  const onu = tipoCx === 'onu';
  // na ONU e na passagem a camera nao tem PoE do switch: fonte ou injetor
  const campoAlim = tipoCx === 'switch' ? '' : `<div class="form-group" style="margin:0"><label for="cxAlim">Alimentação</label><select id="cxAlim">${Object.entries(CX_ALIM).filter(([k]) => k !== 'poe_switch').map(([k, v]) => `<option value="${k}" ${k === 'fonte12' ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>`;
  // CTO cadastrada: so as portas livres dela; sem cadastro, numero livre
  const ctoCad = cto ? ctDoPonto(d.def, cto.ponto, cto.latlng) : null;
  const livresCto = ctoCad ? ctPortasLivres(d.def, ctoCad) : [];
  const campoPorta = cto
    ? (ctoCad
      ? `<div class="form-group" style="margin:0"><label for="cxPortaCto">Porta da CTO</label><select id="cxPortaCto"><option value="">sem porta</option>${livresCto.map((n, i) => `<option value="${n}" ${i === 0 ? 'selected' : ''}>Porta ${n} (livre)</option>`).join('')}</select></div>`
      : '<div class="form-group" style="margin:0"><label for="cxPortaCto">Porta da CTO</label><input id="cxPortaCto" type="number" min="1" max="64" placeholder="ex.: 3"></div>')
    : tipoCx === 'passagem' ? campoAlim
    : `<div class="form-group" style="margin:0"><label for="cxPorta">${onu ? 'Porta LAN da ONU' : 'Porta do switch'}</label><select id="cxPorta"><option value="">sem porta</option>${livres.map((n, i) => `<option value="${n}" ${i === 0 ? 'selected' : ''}>${onu ? `LAN ${n}` : `Porta ${n}`} (livre)</option>`).join('')}</select></div>
      <div class="form-group" style="margin:0"><label for="cxVlanCabo">VLAN da porta</label><input id="cxVlanCabo" type="number" min="1" max="4094" placeholder="${esc(caixa.switch_vlan ? `${caixa.switch_vlan} (da caixa)` : 'a da caixa')}"></div>
      ${campoAlim}`;
  const corpo = `
    <p style="margin:0"><strong>${esc(caixa.nome)}</strong>${cto || onu ? ' (ONU)' : ''} → <strong>${cto ? `CTO ${esc(cto.ponto)}` : esc(camera.ponto || camera.ip)}</strong></p>
    <fieldset class="cx-tipos"><legend>Tipo de cabo</legend>${Object.entries(CX_CABOS).map(([k, v]) => `<label class="nt-pill"><input type="radio" name="cxTipo" value="${k}" ${k === padrao ? 'checked' : ''}><span>${esc(v.nome)}</span></label>`).join('')}</fieldset>
    <div class="form-row">
      ${campoPorta}
      <div class="form-group" style="margin:0"><label for="cxFolga">Folga (%)</label><input id="cxFolga" type="number" min="0" max="100" value="10"></div>
    </div>
    <div class="cx-conta" id="cxConta"></div>
    <p id="cxErro" class="login-error" hidden></p>`;
  const el = cxPainelBase(cto ? 'Cabo até a CTO' : 'Novo cabo', corpo, '<span style="flex:1"></span><button type="button" class="secondary-action" data-cx="cancelar-cabo">Cancelar</button><button type="button" class="primary-action" data-cx="salvar-cabo"><i data-lucide="save"></i> Salvar cabo</button>');
  _cx.painel = { el, id: d.id, def: d.def, caixa, nomePonto: caixa.ponto, latlng: d.pontos[0], novoCabo: true };
  const conta = () => {
    const tipo = el.querySelector('input[name="cxTipo"]:checked')?.value || padrao;
    const folga = Number(document.getElementById('cxFolga')?.value || 0);
    const comFolga = metros * (1 + folga / 100);
    const lim = CX_CABOS[tipo]?.limite;
    document.getElementById('cxConta').innerHTML = `<div><span>Traçado</span><strong>${cxFmtMetros(metros)}</strong></div>
      <div><span>Com ${folga}% de folga</span><strong>${cxFmtMetros(comFolga)}</strong></div>
      ${lim ? `<div><span>Limite do PoE (UTP)</span><strong class="${comFolga > lim ? 'cx-off' : 'cx-ok'}">${lim} m · ${comFolga > lim ? 'passou do limite' : 'ok'}</strong></div>` : ''}`;
  };
  el.addEventListener('change', conta);
  el.addEventListener('input', conta);
  conta();
}

async function cxSalvarCabo() {
  const d = _cx.desenho;
  const p = _cx.painel;
  if (!d || !p) return;
  try {
    const comum = {
      caixa: d.caixa.id, caminho: d.pontos,
      tipo: p.el.querySelector('input[name="cxTipo"]:checked')?.value || (d.cto ? 'drop' : 'utp5e'),
      folga_pct: Number(document.getElementById('cxFolga')?.value || 0),
    };
    await cxGravar(d.def, { cabo: d.cto
      ? { ...comum, cto: { ponto: d.cto.ponto, porta: document.getElementById('cxPortaCto')?.value || null } }
      : { ...comum, camera: d.camera, porta: document.getElementById('cxPorta')?.value || null,
          vlan: document.getElementById('cxVlanCabo')?.value.trim() || '',
          ...(document.getElementById('cxAlim') ? { alimentacao: document.getElementById('cxAlim').value } : {}) } });
  } catch (e) {
    const er = document.getElementById('cxErro');
    if (er) { er.textContent = e.message; er.hidden = false; }
    return;
  }
  const { id, def, caixa, camera, cto } = d;
  const porta = document.getElementById('cxPorta')?.value;
  cxLimparDesenho();
  const salva = def.caixas?.[caixa.id] || caixa;
  const onu = cxTipo(salva) === 'onu';
  const sw = salva.switch_nome || (onu ? `ONU ${salva.nome}` : salva.nome);
  if (cto) showToast(`ONU ligada à CTO ${cto.ponto}.`);
  else if (cxTipo(salva) === 'passagem' || !camera?.ip) showToast('Cabo salvo.');
  else showToast(`Cabo salvo. No inventário, ${camera.ponto || camera.ip}: ${onu ? '' : 'switch '}${sw}${porta ? `, porta ${onu ? `LAN${porta}` : porta}` : ''}.`);
  cxRedesenhar(id, def);
  cxAbrirPainel(id, def, caixa.ponto, cxPosDaCaixa(def, def.caixas?.[caixa.id] || caixa));
}

// ------------------------------------------------------------------ CTO
// Ponto da camada com "CTO" no nome. O cadastro (meta.ctos, pelo nome E
// posicao, como a caixa) guarda splitter, origem (OLT/PON, de qual CDO/CTO
// vem) e a ONU de cada porta, escolhida da lista do monitoramento: o painel
// mostra sinal e status dela. Caixa ligada por cabo drop ocupa a porta sozinha.
// CTO e passiva: nunca aparece como "offline".

const CT_SPLITTERS = ['1:2', '1:4', '1:8', '1:16', '1:32', '1:64'];
const CT_NIVEIS = { primario: 'Primário', secundario: 'Secundário' };

function ctPosDaCto(def, cto) {
  if (cto?.lat != null && cto?.lng != null) return [+cto.lat, +cto.lng];
  return cxLatLngDoPonto(def, cto?.ponto);
}

function ctDoPonto(def, nome, latlng) {
  const chave = String(nome || '').trim().toLowerCase();
  const doNome = Object.values(def?.ctos || {}).filter(c => String(c.ponto || '').trim().toLowerCase() === chave);
  if (!latlng) return doNome.length === 1 ? doNome[0] : null;
  return doNome.find(c => cxPerto(ctPosDaCto(def, c), latlng)) || null;
}

// Caixas ligadas nesta CTO (o cabo guarda so o nome do ponto da CTO).
function ctCabosDaCto(def, cto) {
  const chave = String(cto?.ponto || '').trim().toLowerCase();
  return Object.values(def?.cabos || {}).filter(c => c.cto && String(c.cto.ponto || '').trim().toLowerCase() === chave);
}

function ctPortasLivres(def, cto) {
  const usadas = new Set(ctCabosDaCto(def, cto).map(c => Number(c.cto.porta)).filter(Boolean));
  Object.entries(cto?.portas_info || {}).forEach(([n, i]) => { if (i?.onu_key) usadas.add(Number(n)); });
  return Array.from({ length: Number(cto?.portas || 0) }, (_, i) => i + 1).filter(n => !usadas.has(n));
}

function ctUsadas(def, cto) {
  return Number(cto?.portas || 0) - ctPortasLivres(def, cto).length;
}

function ctMarcador(id, def, f, lat, lng) {
  const nome = mapFeatureName(f);
  const cto = ctDoPonto(def, nome, [lat, lng]);
  const livres = cto ? ctPortasLivres(def, cto).length : 0;
  const conta = cto ? ` · ${ctUsadas(def, cto)}/${cto.portas}` : '';
  const dica = cto ? `CTO${cto.splitter ? ` ${cto.splitter}` : ''}: ${livres} porta(s) livre(s)` : 'CTO sem cadastro: clique para informar splitter, origem e portas';
  const icon = L.divIcon({
    className: '',
    html: `<div class="ct-pino${cto ? '' : ' ct-pino-novo'}${cto && !livres ? ' ct-pino-cheia' : ''}" title="${esc(dica)}"><b>CTO</b><span>${esc(cto?.nome || nome)}${conta}</span></div>`,
    iconSize: [40, 22], iconAnchor: [20, 11],
  });
  const marker = L.marker([lat, lng], { icon, zIndexOffset: 400 });
  marker.on('click', () => {
    // desenhando o cabo da caixa: dois cliques na CTO terminam o cabo nela
    if (_cx.desenho) { cxCliqueNoPonto(def, f, null, [lat, lng], marker); return; }
    if (_cx.edicao) return;
    ctAbrirPainel(id, def, nome, [lat, lng]).catch(e => showToast(e?.message || 'Falha ao abrir a CTO.', true));
  });
  return marker;
}

// ONUs e OLTs do monitoramento (ja filtradas pelos sites do usuario).
const _ct = { cache: {} };
async function ctEntidades(tipo) {
  const c = _ct.cache[tipo];
  if (c && Date.now() - c.t < 60000) return c.lista;
  let lista = [];
  try {
    const res = await api(`/api/monitoring/entities?entity_type=${tipo}&limit=2000`);
    const data = res?.ok ? await res.json() : null;
    lista = (data?.entities || []).map(e => {
      let det = e.detail_json;
      if (typeof det === 'string') { try { det = JSON.parse(det); } catch (_) { det = {}; } }
      return { ...e, det: det || {} };
    });
  } catch (_) { /* sem acesso ao monitoramento: o painel funciona sem sinal */ }
  _ct.cache[tipo] = { t: Date.now(), lista };
  return lista;
}

// Sinal GPON na ONU: ate -25 bom, ate -28 atencao, abaixo disso ruim.
function ctSinal(rx) {
  const v = parseFloat(rx);
  if (!Number.isFinite(v) || v === 0) return '';
  const cls = v >= -25 ? 'ct-ok' : v >= -28 ? 'ct-atencao' : 'ct-ruim';
  return `<span class="ct-sinal ${cls}" title="Sinal recebido na ONU">${v.toFixed(2)} dBm</span>`;
}

function ctEstadoOnu(e) {
  const st = String(e?.status || '').toLowerCase();
  if (st === 'up') return 'on';
  if (st === 'down') return 'off';
  return 'sem';
}

function ctNomeOnu(e) {
  const pon = e?.det?.pon != null && e.det.pon !== '' ? ` · PON ${e.det.pon}` : '';
  return `${e?.display_name || e?.entity_id || e?.entity_key}${pon}`;
}

async function ctAbrirPainel(id, def, nomePonto, latlng) {
  if (!def?.updateUrl || def.source !== 'imported') { showToast('CTO só em camadas importadas (KMZ).', true); return; }
  latlng = latlng || cxLatLngDoPonto(def, nomePonto);
  const cto = ctDoPonto(def, nomePonto, latlng);
  const [onus, olts] = await Promise.all([ctEntidades('onu'), ctEntidades('olt')]);
  const porKey = Object.fromEntries(onus.map(e => [e.entity_key, e]));
  const portas = Number(cto?.portas || 8);
  const info = cto?.portas_info || {};
  const caboNaPorta = {};
  const semPorta = [];
  ctCabosDaCto(def, cto || { ponto: nomePonto }).forEach(c => {
    if (c.cto.porta) caboNaPorta[Number(c.cto.porta)] = c; else semPorta.push(c);
  });
  const nomeCaixa = c => def.caixas?.[c.caixa]?.nome || 'Caixa';
  const estadoPorta = n => {
    const onu = porKey[info[n]?.onu_key];
    if (onu) return ctEstadoOnu(onu);
    if (caboNaPorta[n] || info[n]?.onu_key) return 'cx';
    return 'livre';
  };
  const grade = Array.from({ length: portas }, (_, i) => {
    const n = i + 1;
    const st = estadoPorta(n);
    const quem = [caboNaPorta[n] ? `caixa ${nomeCaixa(caboNaPorta[n])}` : '', info[n]?.onu_nome ? `ONU ${info[n].onu_nome}` : ''].filter(Boolean).join(' · ');
    const cls = st === 'livre' ? 'cx-p-livre' : st === 'cx' ? 'cx-p-cx' : `cx-p-${st}`;
    return `<span class="cx-porta ${cls}" title="Porta ${n}: ${esc(quem || 'livre')}">${n}</span>`;
  }).join('');
  const porSite = {};
  onus.forEach(e => { (porSite[e.site || 'Sem site'] = porSite[e.site || 'Sem site'] || []).push(e); });
  Object.values(porSite).forEach(l => l.sort((a, b) => ctNomeOnu(a).localeCompare(ctNomeOnu(b), 'pt-BR', { numeric: true })));
  const opcoesOnu = (sel, nomeSalvo) => '<option value="">—</option>'
    + Object.keys(porSite).sort().map(s => `<optgroup label="${esc(s)}">${porSite[s]
      .map(e => `<option value="${esc(e.entity_key)}" ${e.entity_key === sel ? 'selected' : ''}>${esc(ctNomeOnu(e))}</option>`).join('')}</optgroup>`).join('')
    + (sel && !porKey[sel] ? `<option value="${esc(sel)}" selected>${esc(nomeSalvo || sel)} (fora do monitoramento)</option>` : '');
  const linhas = Array.from({ length: portas }, (_, i) => {
    const n = i + 1;
    const cabo = caboNaPorta[n];
    const sel = info[n]?.onu_key || '';
    const onu = porKey[sel];
    const st = onu ? ctEstadoOnu(onu) : '';
    const estado = st === 'off' ? ' <small class="cx-off">fora do ar</small>' : st === 'on' ? ' <small class="cx-ok">no ar</small>' : '';
    return `<tr class="${st === 'off' ? 'cx-tr-off' : ''}"><td>${n}</td>
      <td>${cabo ? `<strong>${esc(nomeCaixa(cabo))}</strong> <small>${cxFmtMetros(cabo.metros || 0)} drop</small>` : '<span class="text-muted">—</span>'}</td>
      <td><select class="ct-onu" data-ct-onu="${n}" aria-label="ONU da porta ${n}">${opcoesOnu(sel, info[n]?.onu_nome)}</select></td>
      <td>${onu ? `${ctSinal(onu.det?.onu_rx)}${estado}` : ''}</td>
      <td><input class="ct-obs" data-ct-obs="${n}" maxlength="120" value="${esc(info[n]?.obs || '')}" placeholder="obs." aria-label="Observação da porta ${n}"></td></tr>`;
  }).join('');
  const usadas = cto ? ctUsadas(def, cto) : Object.keys(caboNaPorta).length;
  const pontosRede = [...new Set((def.features || [])
    .filter(x => x.geometry?.type === 'Point' && /\b(cto|cdo)\b|^(cto|cdo)|emenda/i.test(mapFeatureName(x)) && mapFeatureName(x) !== nomePonto)
    .map(x => mapFeatureName(x)))];
  const oltSalvaFora = cto?.olt_key && !olts.some(o => o.entity_key === cto.olt_key);
  const corpo = `
    ${cto ? '' : '<div class="so-note"><i data-lucide="info"></i><span>Cadastre a CTO para guardar splitter, origem e o que está em cada porta. As caixas já ligadas a ela por cabo drop entram sozinhas nas portas.</span></div>'}
    <div class="form-row">
      <div class="form-group" style="margin:0"><label for="ctNome">Nome</label><input id="ctNome" maxlength="80" value="${esc(cto?.nome || nomePonto)}"></div>
      <div class="form-group" style="margin:0"><label for="ctModelo">Modelo</label><input id="ctModelo" maxlength="80" value="${esc(cto?.modelo || '')}" placeholder="ex.: CTO 16 portas"></div>
    </div>
    <section class="cx-bloco"><h3>Splitter</h3>
      <div class="cx-sw-linha">
        <div class="form-group" style="margin:0"><label for="ctSplitter">Divisão</label><select id="ctSplitter"><option value="">—</option>${CT_SPLITTERS.map(s => `<option value="${s}" ${cto?.splitter === s ? 'selected' : ''}>${s}</option>`).join('')}</select></div>
        <div class="form-group" style="margin:0"><label for="ctNivel">Nível</label><select id="ctNivel"><option value="">—</option>${Object.entries(CT_NIVEIS).map(([k, v]) => `<option value="${k}" ${cto?.nivel === k ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="form-group" style="margin:0"><label for="ctPortas">Portas</label><input id="ctPortas" type="number" min="1" max="64" value="${portas}"></div>
      </div></section>
    <section class="cx-bloco"><h3>Origem <small>de onde vem o sinal</small></h3>
      <div class="cx-sw-linha">
        <div class="form-group" style="margin:0"><label for="ctOlt">OLT</label><select id="ctOlt"><option value="">—</option>${olts.map(o => `<option value="${esc(o.entity_key)}" ${cto?.olt_key === o.entity_key ? 'selected' : ''}>${esc(o.display_name || o.entity_id)}${o.site ? ` · ${esc(o.site)}` : ''}</option>`).join('')}${oltSalvaFora ? `<option value="${esc(cto.olt_key)}" selected>${esc(cto.olt_nome || cto.olt_key)}</option>` : ''}</select></div>
        <div class="form-group" style="margin:0"><label for="ctPon">PON</label><input id="ctPon" maxlength="20" value="${esc(cto?.pon || '')}" placeholder="ex.: 0/3"></div>
        <div class="form-group" style="margin:0"><label for="ctVemDe">Vem de (CDO/CTO)</label><input id="ctVemDe" maxlength="160" list="ctVemDeLista" value="${esc(cto?.vem_de || '')}" placeholder="ex.: CDO-01"><datalist id="ctVemDeLista">${pontosRede.map(n => `<option value="${esc(n)}">`).join('')}</datalist></div>
      </div></section>
    <section><h3>Portas <small>${usadas} de ${portas} em uso</small></h3>
      <div class="cx-portas">${grade}</div>
      <div class="ct-legenda"><span><i class="cx-p-livre"></i>livre</span><span><i class="cx-p-cx"></i>caixa / ONU</span><span><i class="cx-p-on"></i>ONU no ar</span><span><i class="cx-p-off"></i>ONU fora do ar</span></div>
      ${onus.length ? '' : '<p class="text-muted" style="margin:6px 0 0">Sem lista de ONUs do monitoramento: dá para anotar as portas, mas sem sinal.</p>'}
      <table class="cx-tabela ct-tabela"><thead><tr><th>Porta</th><th>Caixa</th><th>ONU</th><th>Sinal</th><th>Obs.</th></tr></thead><tbody>${linhas}</tbody></table>
      ${semPorta.length ? `<p class="text-muted" style="margin:6px 0 0">Ligada(s) sem porta: ${semPorta.map(c => esc(nomeCaixa(c))).join(', ')}. Edite o cabo na caixa para informar a porta.</p>` : ''}
    </section>
    <div class="form-group" style="margin:0"><label for="ctObs">Observação</label><input id="ctObs" maxlength="300" value="${esc(cto?.obs || '')}" placeholder="ex.: no poste em frente à escola"></div>
    <p id="cxErro" class="login-error" hidden></p>`;
  const rodape = `${cto ? '<button type="button" class="ghost-action cx-perigo cx-ico" data-ct="excluir" title="Excluir cadastro da CTO" aria-label="Excluir cadastro da CTO"><i data-lucide="trash-2"></i></button>' : ''}
    <span style="flex:1"></span>
    <button type="button" class="primary-action" data-ct="salvar"><i data-lucide="save"></i> ${cto ? 'Salvar' : 'Cadastrar CTO'}</button>`;
  const el = cxPainelBase(cto?.nome || nomePonto || 'CTO', corpo, rodape, `CTO${cto?.splitter ? ` ${cto.splitter}` : ''}`);
  el.classList.add('ct-painel');
  // trocar o splitter sugere o numero de portas
  el.querySelector('#ctSplitter')?.addEventListener('change', ev => {
    const n = Number(String(ev.target.value).split(':')[1] || 0);
    if (n) el.querySelector('#ctPortas').value = n;
  });
  el.addEventListener('click', ev => {
    const b = ev.target.closest('[data-ct]');
    if (b) ctAcao(b.dataset.ct).catch(e => showToast(e?.message || 'Falha na ação.', true));
  });
  _cx.painel = { el, id, def, cto, nomePonto, latlng, porKey };
}

async function ctAcao(acao) {
  const p = _cx.painel;
  if (!p?.el) return;
  const er = p.el.querySelector('#cxErro');
  if (acao === 'excluir') {
    if (!(await showConfirm({ title: 'Excluir CTO', msg: `Apagar o cadastro da CTO "${p.cto.nome}" (splitter, origem e ONUs das portas)? O ponto e os cabos das caixas continuam no mapa.`, label: 'Excluir' }))) return;
    try {
      await cxGravar(p.def, { cto: { id: p.cto.id, excluir: true } });
    } catch (e) {
      if (er) { er.textContent = e.message; er.hidden = false; }
      return;
    }
    showToast('Cadastro da CTO excluído.');
    cxFecharPainel();
    cxRedesenhar(p.id, p.def);
    return;
  }
  if (acao !== 'salvar') return;
  const v = idc => p.el.querySelector(`#${idc}`)?.value ?? '';
  const portas_info = {};
  p.el.querySelectorAll('[data-ct-onu]').forEach(s => {
    const n = s.dataset.ctOnu;
    const onu_key = s.value;
    const obs = (p.el.querySelector(`[data-ct-obs="${n}"]`)?.value || '').trim();
    const onu = p.porKey[onu_key];
    const nomeAntigo = p.cto?.portas_info?.[n]?.onu_key === onu_key ? p.cto.portas_info[n].onu_nome : '';
    if (onu_key || obs) portas_info[n] = { onu_key, onu_nome: onu ? ctNomeOnu(onu) : nomeAntigo, obs };
  });
  const olt = p.el.querySelector('#ctOlt');
  try {
    await cxGravar(p.def, { cto: {
      id: p.cto?.id || '', ponto: p.nomePonto, lat: p.latlng?.[0], lng: p.latlng?.[1],
      nome: v('ctNome').trim(), modelo: v('ctModelo').trim(), splitter: v('ctSplitter'), nivel: v('ctNivel'),
      portas: Number(v('ctPortas') || 0), olt_key: olt?.value || '',
      olt_nome: olt?.value ? (olt.selectedOptions[0]?.textContent || '').trim() : '',
      pon: v('ctPon').trim(), vem_de: v('ctVemDe').trim(), obs: v('ctObs').trim(), portas_info,
    } });
  } catch (e) {
    if (er) { er.textContent = e.message; er.hidden = false; }
    return;
  }
  showToast(p.cto ? 'CTO salva.' : 'CTO cadastrada.');
  cxRedesenhar(p.id, p.def);
  ctAbrirPainel(p.id, p.def, p.nomePonto, p.latlng);
}
