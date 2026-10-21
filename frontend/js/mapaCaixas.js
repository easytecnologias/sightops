// Mapa: caixas de CFTV e cabos (caixa -> camera).
// A caixa e um ponto da camada (pelo nome) com o que tem dentro e as portas
// do switch; o cabo e desenhado com curvas (clique no mapa = curva, clique na
// camera = fim) e a metragem sai do traçado. Tudo no meta da camada, pela
// mesma rota de edicao de camada (PATCH {caixa} / {cabo}). Excluir caixa ou
// cabo e so administrador (o servidor pede a senha dele para os demais).
// A ONU da caixa pode ser ligada numa CTO (cabo {cto:{ponto,porta}}, fibra drop):
// um por caixa, nao vai para o inventario de cameras.
// O painel lateral nao fecha ao clicar fora: so X, Cancelar ou Esc.

const _cx = { painel: null, desenho: null };

const CX_ITENS = {
  switch_poe: 'Switch PoE', switch: 'Switch', onu: 'ONU', fonte: 'Fonte', nobreak: 'Nobreak',
  dio: 'DIO', roteador: 'Roteador', injetor_poe: 'Injetor PoE', outro: 'Outro',
};
const CX_UPLINK = { onu: 'ONU', fibra: 'Fibra / conversor', radio: 'Rádio', switch: 'Outro switch', outro: 'Outro' };
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
  const usadas = caixa ? cxCabosDaCaixa(def, caixa.id).filter(c => c.porta).length : 0;
  const rotulo = caixa ? `${esc(caixa.nome)}${caixa.portas ? ` · ${usadas}/${caixa.portas}` : ''}` : esc(nome || 'Caixa');
  const icon = L.divIcon({
    className: '',
    html: `<div class="cx-pino${caixa ? '' : ' cx-pino-novo'}" title="${caixa ? 'Caixa de CFTV' : 'Parece uma caixa: clique para cadastrar'}">
      <span class="cx-pino-ico"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="14" rx="2"/><path d="M3 11h18"/><path d="M8 15h2M14 15h2"/></svg></span>
      <span class="cx-pino-rot">${rotulo}</span></div>`,
    iconSize: [34, 34], iconAnchor: [17, 17],
  });
  const marker = L.marker([lat, lng], { icon, zIndexOffset: 500 });
  marker.on('click', () => {
    if (_cx.desenho) return; // desenhando: clicar na caixa nao abre outra coisa
    cxAbrirPainel(id, def, nome, [lat, lng]);
  });
  return marker;
}

function cxDesenharCabos(id, def, group) {
  Object.values(def?.cabos || {}).forEach(cabo => {
    if (!Array.isArray(cabo.caminho) || cabo.caminho.length < 2) return;
    const t = CX_CABOS[cabo.tipo] || CX_CABOS.outro;
    const fora = !cabo.cto && cxEstadoCamera(cxCameraDoCabo(def, cabo)) === 'off';
    const linha = L.polyline(cabo.caminho, {
      color: fora ? '#c92a2a' : t.cor, weight: 4, opacity: 0.95, dashArray: t.tracejado || null,
    });
    const caixa = def.caixas?.[cabo.caixa];
    linha.bindTooltip(`${esc(t.nome)} · ${cxFmtMetros(cabo.metros || 0)}${cabo.porta ? ` · porta ${cabo.porta}` : ''} → ${cabo.cto ? 'CTO ' : ''}${esc(cxDestinoDoCabo(cabo))}${fora ? ' · câmera fora do ar' : ''}`, { sticky: true });
    linha.on('click', () => { if (!_cx.desenho && caixa) cxAbrirPainel(id, def, caixa.ponto, cxPosDaCaixa(def, caixa)); });
    group.addLayer(linha);
  });
}

// Clique num ponto do mapa enquanto desenha: camera termina o cabo.
function cxCliqueNoPonto(def, f, cam, latlng, marker) {
  const d = _cx.desenho;
  if (!d) return false;
  setTimeout(() => marker?.closePopup?.(), 0);
  const alvo = d.alvo === 'cto' ? 'CTO' : 'câmera';
  // a mesma camera pode estar desenhada em outra camada (a gerada do
  // inventario, por exemplo) por cima da desta: com IP ela e identificada
  // igual, entao vale; sem IP so a da mesma camada
  const outraCamada = d.def?.id !== def?.id;
  if (outraCamada && (d.alvo === 'cto' || !cam?.ip)) { showToast(`A ${alvo} precisa estar na mesma camada da caixa.`, true); return true; }
  const tipo = mapFeatureType(f, cam);
  if (d.alvo === 'cto') {
    if (tipo !== 'cto') { showToast('Clique numa CTO para terminar o cabo (ou no mapa para fazer uma curva).', true); return true; }
    d.pontos.push(latlng);
    cxTerminarDesenho(null, { ponto: mapFeatureName(f) });
    return true;
  }
  if (tipo !== 'camera') { showToast('Clique numa câmera para terminar o cabo (ou no mapa para fazer uma curva).', true); return true; }
  d.pontos.push(latlng);
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
  if (_cx.desenho) cxCancelarDesenho(); else cxFecharPainel();
}

function cxPainelBase(titulo, corpo, rodape) {
  cxFecharPainel();
  const el = document.createElement('aside');
  el.className = 'cx-painel';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-label', titulo);
  el.innerHTML = `<header><div><p class="eyebrow">Caixa de CFTV</p><h2>${esc(titulo)}</h2></div>
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
  const itens = caixa?.itens?.length ? caixa.itens.filter(it => !cxEItemSwitch(it)) : [{ tipo: 'onu', qtd: 1 }, { tipo: 'fonte', qtd: 1 }];
  const caboCto = caixa ? cxCaboDaCto(def, caixa.id) : null;
  const portas = caixa ? Number(caixa.portas || 0) : 8;
  const cabos = caixa ? cxCabosDaCaixa(def, caixa.id) : [];
  const porPorta = Object.fromEntries(cabos.filter(c => c.porta).map(c => [c.porta, c]));
  const statusCabo = c => cxEstadoCamera(cxCameraDoCabo(def, c));
  const uplinks = caixa ? Number(caixa.uplinks ?? 1) : 1;
  const uplinkPara = caixa?.uplink_para || 'onu';
  const grade = Array.from({ length: portas }, (_, i) => {
    const c = porPorta[i + 1];
    return `<span class="cx-porta ${c ? `cx-p-${statusCabo(c)}` : 'cx-p-livre'}" title="${c ? esc(`Porta ${i + 1}: ${c.camera?.ponto || c.camera?.ip}`) : `Porta ${i + 1} livre`}">${i + 1}</span>`;
  }).join('') + Array.from({ length: uplinks }, (_, i) =>
    `<span class="cx-porta cx-p-up" title="${esc(`Uplink ${uplinks > 1 ? i + 1 : ''} → ${CX_UPLINK[uplinkPara] || uplinkPara}${caixa?.uplink_obs ? ` (${caixa.uplink_obs})` : ''}`)}">UP${uplinks > 1 ? i + 1 : ''}</span>`).join('');
  // modelo do switch: o salvo, senao o do item "Switch PoE" (caixas antigas)
  const itemSwitch = (caixa?.itens || []).find(it => it.tipo === 'switch_poe' || it.tipo === 'switch');
  const swModelo = caixa?.switch_modelo || itemSwitch?.modelo || '';
  const temOnu = (caixa?.itens || []).some(it => it.tipo === 'onu') || uplinkPara === 'onu';
  const blocoCto = !caixa ? '' : caboCto ? `<div class="cx-cto">
      <i data-lucide="git-commit-horizontal"></i>
      <div><strong>ONU → CTO ${esc(cxDestinoDoCabo(caboCto))}</strong>
        <small>${esc((CX_CABOS[caboCto.tipo] || CX_CABOS.outro).nome)} · ${cxFmtMetros(caboCto.metros || 0)} (${cxFmtMetros(caboCto.metros_com_folga || caboCto.metros || 0)} com folga)</small></div>
      <button type="button" class="ghost-action" data-cx="excluir-cabo" data-id="${esc(caboCto.id)}" aria-label="Excluir cabo da CTO"><i data-lucide="trash-2"></i></button></div>`
    : temOnu ? `<div class="cx-cto cx-cto-vazio"><i data-lucide="git-commit-horizontal"></i>
      <div><strong>ONU sem CTO</strong><small>Se a ONU desta caixa vem de uma CTO, ligue com o cabo drop.</small></div>
      <button type="button" class="secondary-action" data-cx="ligar-cto">Ligar à CTO</button></div>` : '';
  const linhasCabo = cabos.sort((a, b) => (a.porta || 99) - (b.porta || 99)).map(c => {
    const t = CX_CABOS[c.tipo] || CX_CABOS.outro;
    const st = statusCabo(c);
    const cam = cxCameraDoCabo(def, c);
    const longe = t.limite && (c.metros_com_folga || c.metros) > t.limite;
    return `<tr class="${st === 'off' ? 'cx-tr-off' : ''}"><td>${c.porta ? `P${c.porta}` : '—'}</td>
      <td><strong>${esc(cam?.titulo || c.camera?.ponto || c.camera?.ip || '')}</strong>${cam?.ip ? ` <small>${esc(cam.ip)}</small>` : ''}${st === 'off' ? ' <small class="cx-off">fora do ar</small>' : ''}</td>
      <td><input class="cx-vlan" data-cx-vlan="${esc(c.id)}" type="number" min="1" max="4094" value="${esc(c.vlan || '')}" placeholder="${esc(caixa?.switch_vlan || 'VLAN')}" title="VLAN desta porta (vazio = a da caixa)" aria-label="VLAN da porta"></td>
      <td>${esc(t.nome)} ${cxFmtMetros(c.metros || 0)}${longe ? ` <small class="cx-off" title="Acima de ${t.limite} m o PoE/UTP perde sinal">acima de ${t.limite} m</small>` : ''}</td>
      <td><button type="button" class="ghost-action" data-cx="excluir-cabo" data-id="${esc(c.id)}" aria-label="Excluir cabo"><i data-lucide="trash-2"></i></button></td></tr>`;
  }).join('');
  const corpo = `
    ${caixa ? '' : '<div class="so-note"><i data-lucide="info"></i><span>Este ponto vira uma caixa de CFTV. Diga o que tem dentro e quantas portas tem o switch.</span></div>'}
    <div class="form-group" style="margin:0"><label for="cxNome">Nome da caixa</label><input id="cxNome" maxlength="80" value="${esc(caixa?.nome || nomePonto)}"></div>
    <section class="cx-switch"><h3>Switch <small>nome e portas vão para o inventário das câmeras</small></h3>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxSwNome">Nome do switch</label><input id="cxSwNome" maxlength="60" value="${esc(caixa?.switch_nome || '')}" placeholder="ex.: SW-CFTV-01"></div>
        <div class="form-group" style="margin:0"><label for="cxSwModelo">Modelo</label><input id="cxSwModelo" maxlength="80" value="${esc(swModelo)}" placeholder="ex.: Hikvision 4+1 PoE"></div>
      </div>
      <div class="cx-sw-linha">
        <div class="form-group" style="margin:0"><label for="cxPortas">Portas PoE</label><input id="cxPortas" type="number" min="0" max="64" value="${portas}"></div>
        <div class="form-group" style="margin:0"><label for="cxUplinks">Uplink</label><input id="cxUplinks" type="number" min="0" max="8" value="${uplinks}"></div>
        <div class="form-group" style="margin:0"><label for="cxSwVlan" title="Vale para as portas sem VLAN própria">VLAN padrão</label><input id="cxSwVlan" type="number" min="1" max="4094" value="${esc(caixa?.switch_vlan || '')}" placeholder="ex.: 120"></div>
      </div>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="cxUplinkPara">Uplink liga em</label><select id="cxUplinkPara">${Object.entries(CX_UPLINK).map(([k, v]) => `<option value="${k}" ${uplinkPara === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
        <div class="form-group" style="margin:0"><label for="cxSwIp">IP do switch</label><input id="cxSwIp" maxlength="45" value="${esc(caixa?.switch_ip || '')}" placeholder="opcional"></div>
      </div>
      ${blocoCto}
    </section>
    <section class="cx-bloco"><h3>O que tem dentro <small>além do switch</small></h3>
      <div class="cx-item-cab"><span>Item</span><span>Modelo</span><span>Qtd</span><span></span></div>
      <div id="cxItens">${itens.map(cxLinhaItem).join('')}</div>
      <button type="button" class="cx-mais" data-cx="mais-item"><i data-lucide="plus"></i> Adicionar item</button></section>
    ${caixa ? `<section><h3>Portas do switch <small title="VLAN em branco na porta = a VLAN da caixa">${cabos.filter(c => c.porta).length} de ${portas} PoE em uso${uplinks ? ` · uplink → ${esc(CX_UPLINK[uplinkPara] || uplinkPara)}` : ''}</small></h3>
      <div class="cx-portas">${grade || '<span class="text-muted">Sem switch informado.</span>'}</div>
      ${cabos.length ? `<table class="cx-tabela"><tbody>${linhasCabo}</tbody></table>` : '<p class="text-muted" style="margin:6px 0 0">Nenhuma câmera ligada ainda. Use "Ligar câmera".</p>'}
    </section>` : ''}
    <div class="form-group" style="margin:0"><label for="cxObs">Observação</label><input id="cxObs" maxlength="300" value="${esc(caixa?.obs || '')}" placeholder="ex.: chave do cadeado com o síndico"></div>
    <p id="cxErro" class="login-error" hidden></p>`;
  const rodape = `${caixa ? `<button type="button" class="ghost-action cx-perigo" data-cx="excluir-caixa"><i data-lucide="trash-2"></i> Excluir caixa</button>` : ''}
    <span style="flex:1"></span>
    ${caixa ? '<button type="button" class="secondary-action" data-cx="ligar"><i data-lucide="cable"></i> Ligar câmera</button>' : ''}
    <button type="button" class="primary-action" data-cx="salvar"><i data-lucide="save"></i> ${caixa ? 'Salvar' : 'Cadastrar caixa'}</button>`;
  const el = cxPainelBase(caixa?.nome || nomePonto || 'Caixa', corpo, rodape);
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
      await cxGravar(p.def, { caixa: { id: p.caixa?.id || '', ponto: p.nomePonto, lat: p.latlng?.[0], lng: p.latlng?.[1], nome: v('cxNome').trim(),
        portas: Number(v('cxPortas') || 0), itens, obs: v('cxObs').trim(),
        switch_nome: v('cxSwNome').trim(), switch_modelo: v('cxSwModelo').trim(), switch_ip: v('cxSwIp').trim(), switch_vlan: v('cxSwVlan').trim(),
        uplinks: Number(v('cxUplinks') || 0), uplink_para: v('cxUplinkPara') || 'onu' } });
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
        if (er) { er.textContent = `Porta ${cabo.porta || '—'}: ${e.message}`; er.hidden = false; }
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
    if (!cabo || !(await showConfirm({ title: 'Excluir cabo', msg: cabo.cto ? `Tirar do mapa o cabo da ONU até a CTO ${cxDestinoDoCabo(cabo)}?` : `Tirar do mapa o cabo da ${cabo.porta ? `porta ${cabo.porta}` : 'caixa'} até ${cabo.camera?.ponto || cabo.camera?.ip}?`, label: 'Excluir' }))) return;
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
  if (acao === 'salvar-cabo') return cxSalvarCabo();
  if (acao === 'cancelar-cabo') { cxCancelarDesenho(); return; }
}

// ------------------------------------------------------------------ desenhar o cabo

function cxIniciarDesenho(alvo = 'camera') {
  const p = _cx.painel;
  if (!p?.caixa || !p.latlng) return;
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
    <span class="cx-barra-txt">Clique no mapa para fazer as curvas (poste, esquina). Clique ${alvo === 'cto' ? 'na CTO' : 'na câmera'} para terminar.</span>
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
  _cx.desenho = { alvo, def: p.def, id: p.id, caixa: p.caixa, pontos: [p.latlng], linha, fantasma, barra, aoClicar, aoMover };
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
  const campoPorta = cto
    ? '<div class="form-group" style="margin:0"><label for="cxPortaCto">Porta da CTO</label><input id="cxPortaCto" type="number" min="1" max="64" placeholder="ex.: 3"></div>'
    : `<div class="form-group" style="margin:0"><label for="cxPorta">Porta do switch</label><select id="cxPorta"><option value="">sem porta</option>${livres.map((n, i) => `<option value="${n}" ${i === 0 ? 'selected' : ''}>Porta ${n} (livre)</option>`).join('')}</select></div>
      <div class="form-group" style="margin:0"><label for="cxVlanCabo">VLAN da porta</label><input id="cxVlanCabo" type="number" min="1" max="4094" placeholder="${esc(caixa.switch_vlan ? `${caixa.switch_vlan} (da caixa)` : 'a da caixa')}"></div>`;
  const corpo = `
    <p style="margin:0"><strong>${esc(caixa.nome)}</strong>${cto ? ' (ONU)' : ''} → <strong>${cto ? `CTO ${esc(cto.ponto)}` : esc(camera.ponto || camera.ip)}</strong></p>
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
          vlan: document.getElementById('cxVlanCabo')?.value.trim() || '' } });
  } catch (e) {
    const er = document.getElementById('cxErro');
    if (er) { er.textContent = e.message; er.hidden = false; }
    return;
  }
  const { id, def, caixa, camera, cto } = d;
  const porta = document.getElementById('cxPorta')?.value;
  cxLimparDesenho();
  const sw = def.caixas?.[caixa.id]?.switch_nome || caixa.nome;
  if (cto) showToast(`ONU ligada à CTO ${cto.ponto}.`);
  else showToast(camera?.ip ? `Cabo salvo. No inventário, ${camera.ponto || camera.ip}: switch ${sw}${porta ? `, porta ${porta}` : ''}.` : 'Cabo salvo.');
  cxRedesenhar(id, def);
  cxAbrirPainel(id, def, caixa.ponto, cxPosDaCaixa(def, def.caixas?.[caixa.id] || caixa));
}
