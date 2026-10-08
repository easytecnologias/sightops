//  Rede — a antiga tela de "Operacoes".
//
//  A de antes perguntava o que voce queria testar. A pergunta que o operador
//  faz de verdade e outra: o que esta quebrado AGORA e onde. Entao esta
//  responde primeiro (tuneis medidos, com quantos equipamentos dependem de
//  cada um) e so depois oferece ferramenta.
//
//  Nada aqui repete campo guardado: latencia, perda e MTU vem de
//  /api/network/tunnels, medidos na hora por um equipamento real do site.

let _redeTuneis = [];
let _redeEstado = '';
let _redeFerrLinhas = [];

function _redeEscapar(v) { return esc(String(v == null ? '' : v)); }

function _redeClasse(t) {
  if (String(t.status).toLowerCase() !== 'online') return 'caiu';
  return (t.avisos && t.avisos.length) ? 'instavel' : 'pe';
}

function _redeAba(nome) {
  document.querySelectorAll('[data-rede-aba]').forEach(b => {
    const ativa = b.dataset.redeAba === nome;
    b.classList.toggle('ativa', ativa);
    b.setAttribute('aria-selected', ativa ? 'true' : 'false');
  });
  document.getElementById('redePaneTuneis')?.classList.toggle('hidden', nome !== 'tuneis');
  document.getElementById('redePaneCaminho')?.classList.toggle('hidden', nome !== 'caminho');
  document.getElementById('redePaneFerramentas')?.classList.toggle('hidden', nome !== 'ferramentas');
  const medir = document.getElementById('btnRedeMedir');
  if (medir) medir.classList.toggle('hidden', nome !== 'tuneis');
}

//  ── Aba 1: tuneis ──────────────────────────────────────────────────────────

async function carregarRedeTuneis(medindo) {
  const corpo = document.getElementById('redeTuneisCorpo');
  if (medindo && corpo) corpo.innerHTML = '<tr><td colspan="8" class="rede-vazio">Medindo os túneis...</td></tr>';
  const btn = document.getElementById('btnRedeMedir');
  const txt = document.getElementById('btnRedeMedirTexto');
  if (btn) btn.disabled = true;
  if (txt) txt.textContent = 'Medindo...';
  try {
    const d = await apiJson('/api/network/tunnels', { cacheTtl: 0, forceRefresh: true });
    _redeTuneis = (d && d.items) || [];
    const resumo = document.getElementById('redeResumo');
    if (resumo) {
      const caiu = d.caiu
        ? ` · <strong class="rede-ruim">${d.caiu} fora do ar</strong>`
        : '';
      resumo.innerHTML = `${d.total} ${d.total === 1 ? 'túnel' : 'túneis'}${caiu} · `
        + `${d.equipamentos} equipamentos dependem deles`;
    }
    const t = document.getElementById('btnRedeMedirTexto');
    if (t) t.textContent = `Medir ${d.total === 1 ? 'o túnel' : 'os ' + d.total} agora`;
    pintarRedeFiltros();
    pintarRedeAtencao();
    pintarRedeTuneis();
    pintarRedeAlvosCaminho();
  } catch (e) {
    if (corpo) corpo.innerHTML = `<tr><td colspan="8" class="rede-vazio">Não consegui medir: ${_redeEscapar(e.message || e)}</td></tr>`;
  } finally {
    if (btn) btn.disabled = false;
    lucide.createIcons();
  }
}

function pintarRedeFiltros() {
  const sel = document.getElementById('redeCliente');
  if (sel) {
    const atual = sel.value;
    const clientes = [...new Set(_redeTuneis.map(t => t.client).filter(Boolean))].sort();
    sel.innerHTML = '<option value="">Todos os clientes</option>'
      + clientes.map(c => `<option value="${_redeEscapar(c)}">${_redeEscapar(c)}</option>`).join('');
    sel.value = atual;
  }
  const conta = { '': _redeTuneis.length, pe: 0, caiu: 0, instavel: 0 };
  _redeTuneis.forEach(t => { conta[_redeClasse(t)] += 1; });
  document.querySelectorAll('[data-rede-estado]').forEach(b => {
    const n = b.querySelector('.mnt-status-n');
    if (n) n.textContent = conta[b.dataset.redeEstado] ?? 0;
    b.classList.toggle('active', b.dataset.redeEstado === _redeEstado);
  });
}

function _redeVisiveis() {
  const busca = (document.getElementById('redeBusca')?.value || '').trim().toLowerCase();
  const cliente = document.getElementById('redeCliente')?.value || '';
  return _redeTuneis.filter(t => {
    if (_redeEstado && _redeClasse(t) !== _redeEstado) return false;
    if (cliente && t.client !== cliente) return false;
    if (busca) {
      const palheiro = [t.name, t.site, t.client, t.medido_em_ip, t.modelo].join(' ').toLowerCase();
      if (!palheiro.includes(busca)) return false;
    }
    return true;
  });
}

//  "O que precisa de voce hoje": so o que tem aviso. Sem aviso, a faixa some
//  inteira -- um cabecalho sobre uma lista vazia e ruido.
function pintarRedeAtencao() {
  const caixa = document.getElementById('redeAtencao');
  const titulo = document.getElementById('redeAtencaoTitulo');
  if (!caixa) return;
  const comAviso = _redeTuneis.filter(t => t.avisos && t.avisos.length);
  caixa.classList.toggle('hidden', !comAviso.length);
  if (titulo) titulo.classList.toggle('hidden', !comAviso.length);
  caixa.innerHTML = comAviso.map(t => {
    const grave = String(t.status).toLowerCase() !== 'online';
    const atras = t.atras.cameras + t.atras.olts;
    return `<article class="rede-card ${grave ? 'grave' : 'atencao'}">
      <span class="rede-card-selo">
        <i data-lucide="${grave ? 'alert-triangle' : 'activity'}"></i>
      </span>
      <div class="rede-card-corpo">
        <h3>${_redeEscapar(t.name)}</h3>
        <p>${_redeEscapar(t.avisos[0])}${atras ? ` · <strong>${atras}</strong> equipamento${atras === 1 ? '' : 's'} atrás` : ''}</p>
        <button type="button" class="rede-link" data-rede-diagnosticar="${_redeEscapar(t.id)}">Ver o caminho →</button>
      </div>
    </article>`;
  }).join('');
}

function pintarRedeTuneis() {
  const corpo = document.getElementById('redeTuneisCorpo');
  const titulo = document.getElementById('redeTabelaTitulo');
  if (!corpo) return;
  const lista = _redeVisiveis();
  if (titulo) titulo.textContent = `Túneis · ${lista.length} de ${_redeTuneis.length}`;
  if (!lista.length) {
    corpo.innerHTML = '<tr><td colspan="8" class="rede-vazio">Nenhum túnel com esse filtro.</td></tr>';
    return;
  }
  corpo.innerHTML = lista.map(t => {
    const classe = _redeClasse(t);
    const atras = [];
    if (t.atras.cameras) atras.push(`${t.atras.cameras} câmera${t.atras.cameras === 1 ? '' : 's'}`);
    if (t.atras.olts) atras.push(`${t.atras.olts} OLT`);
    const nada = (v, suf) => (v === null || v === undefined) ? '<span class="rede-sem">—</span>' : `${v}${suf || ''}`;
    const mtuRuim = t.mtu !== null && t.mtu !== undefined && t.mtu < 1400;
    return `<tr class="rede-linha-${classe}">
      <th scope="row">
        <span class="rede-site"><span class="rede-bolinha ${classe}"></span>${_redeEscapar(t.name)}</span>
        <span class="rede-site-sub mono">${_redeEscapar(t.medido_em_ip || '—')}${t.medido_em ? ' · ' + _redeEscapar(t.medido_em) : ''}</span>
      </th>
      <td class="rede-suave">${_redeEscapar(t.client || '—')}</td>
      <td><span class="rede-chip ${classe === 'caiu' ? 'ruim' : 'bom'}">${_redeEscapar(t.handshake_texto)}</span></td>
      <td class="num mono">${nada(t.latencia_ms, ' ms')}</td>
      <td class="num mono ${t.perda_pct ? 'rede-alerta' : ''}">${nada(t.perda_pct, '%')}</td>
      <td class="num mono ${mtuRuim ? 'rede-alerta' : ''}">${nada(t.mtu)}</td>
      <td class="rede-suave">${atras.length ? _redeEscapar(atras.join(' · ')) : '<span class="rede-sem">nada cadastrado</span>'}</td>
      <td><button type="button" class="rede-link" data-rede-diagnosticar="${_redeEscapar(t.id)}">Diagnosticar</button></td>
    </tr>`;
  }).join('');
}

//  ── Aba 2: onde quebrou ────────────────────────────────────────────────────

function pintarRedeAlvosCaminho() {
  const sel = document.getElementById('redeCamConector');
  if (!sel) return;
  const atual = sel.value;
  sel.innerHTML = _redeTuneis.map(t => `<option value="${_redeEscapar(t.id)}">${_redeEscapar(t.name)}</option>`).join('');
  if (atual) sel.value = atual;
  pintarRedeAlvosEquipamento();
}

//  Os alvos vem do INVENTARIO, nunca digitados: IP privado se repete entre
//  clientes, e digitar o errado diagnostica o site de outro cliente.
async function pintarRedeAlvosEquipamento() {
  const sel = document.getElementById('redeCamAlvo');
  const cid = document.getElementById('redeCamConector')?.value || '';
  if (!sel) return;
  sel.innerHTML = '<option value="">o túnel inteiro</option>';
  if (!cid) return;
  try {
    const d = await apiJson('/api/cameras?mode=olt', { cacheTtl: 20000 });
    const linhas = ((d && d.cameras) || [])
      .filter(c => String(c.remote_connector_id || c.connector_id || '') === cid && c.ip)
      .slice(0, 200);
    sel.innerHTML += linhas.map(c =>
      `<option value="${_redeEscapar(c.ip)}">${_redeEscapar(c.titulo || c.ip)} — ${_redeEscapar(c.ip)}</option>`).join('');
  } catch (e) { /* sem inventario, fica so o tunel inteiro */ }
}

const _REDE_ICONE = {
  ok: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m4 12 5.5 5.5L20 7"/></svg>',
  falhou: '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  nao_medido: '–',
};

async function tracarRedeCaminho(connectorId, ip) {
  _redeAba('caminho');
  const escada = document.getElementById('redeEscada');
  const veredito = document.getElementById('redeVeredito');
  const lateral = document.getElementById('redeLateral');
  const cid = connectorId || document.getElementById('redeCamConector')?.value || '';
  const alvo = ip !== undefined ? ip : (document.getElementById('redeCamAlvo')?.value || '');
  if (connectorId) {
    const sel = document.getElementById('redeCamConector');
    if (sel) { sel.value = connectorId; pintarRedeAlvosEquipamento(); }
  }
  if (!cid) return;

  if (escada) escada.innerHTML = '<li class="rede-vazio-bloco">Traçando o caminho...</li>';
  if (veredito) veredito.classList.add('hidden');
  if (lateral) lateral.innerHTML = '';

  try {
    const q = `connector_id=${encodeURIComponent(cid)}&ip=${encodeURIComponent(alvo || '')}`;
    const d = await apiJson(`/api/network/path?${q}`, { cacheTtl: 0, forceRefresh: true });
    if (!d || d.ok === false) throw new Error((d && d.error) || 'não consegui traçar');

    escada.innerHTML = (d.saltos || []).map(s => `
      <li class="rede-salto ${s.estado}">
        <span class="rede-salto-selo">${_REDE_ICONE[s.estado] || ''}</span>
        <span class="rede-salto-corpo">
          <strong>${_redeEscapar(s.nome)}</strong>
          <span class="mono">${_redeEscapar(s.detalhe)}</span>
        </span>
        <span class="rede-salto-fim mono">${s.ms !== null && s.ms !== undefined ? `${s.ms} ms`
          : (s.estado === 'falhou' ? '<span class="rede-chip ruim">sem resposta</span>' : 'não medido')}</span>
      </li>`).join('');

    const quebrou = (d.saltos || []).find(s => s.estado === 'falhou' && s.nota);
    if (veredito) {
      if (quebrou) {
        veredito.classList.remove('hidden');
        veredito.innerHTML = `<h2>O que isso quer dizer</h2><p>${_redeEscapar(quebrou.nota)}</p>`;
      } else {
        veredito.classList.remove('hidden');
        veredito.classList.add('rede-veredito-bom');
        veredito.innerHTML = '<h2>O caminho inteiro está de pé</h2>'
          + '<p>Todos os saltos responderam. Se o equipamento ainda não aparece no sistema, '
          + 'o problema não é a rede — é credencial, porta ou o próprio aparelho.</p>';
      }
    }

    const painéis = [];
    const mtuRuim = d.mtu && d.mtu < 1400;
    if (d.mtu) {
      painéis.push(`<section class="rede-painel">
        <h2>Pacote cheio</h2>
        <p class="rede-painel-num mono ${mtuRuim ? 'rede-alerta' : ''}">MTU ${d.mtu}</p>
        <p>${mtuRuim
          ? 'Abaixo de 1400 o vídeo trava sem o túnel cair — o ping comum passa e engana. Baixe o MTU nas duas pontas.'
          : 'O pacote cheio passa. Esse não é o problema.'}</p>
      </section>`);
    }
    if (d.ip_virtual) {
      painéis.push(`<section class="rede-painel">
        <h2>Endereço que alcança</h2>
        <div class="rede-par"><span>real, do site</span><span class="mono rede-riscado">${_redeEscapar(d.ip_real)}</span></div>
        <div class="rede-par"><span>virtual, deste conector</span><span class="mono"><strong>${_redeEscapar(d.ip_virtual)}</strong></span></div>
        <p>Conector isolado: testar o IP real devolve <em>No route to host</em> e parece queda. Não é.</p>
      </section>`);
    }
    if (lateral) lateral.innerHTML = painéis.join('');
  } catch (e) {
    if (escada) escada.innerHTML = `<li class="rede-vazio-bloco">Não consegui traçar: ${_redeEscapar(e.message || e)}</li>`;
  } finally {
    lucide.createIcons();
  }
}

//  ── Aba 3: teste pontual ───────────────────────────────────────────────────

//  O resultado vira TABELA, nao terminal preto: o terminal obrigava a ler
//  linha por linha para achar o que nao respondeu.
// Cada teste devolve um formato proprio. Em vez de a tabela adivinhar, cada
// um e traduzido para a mesma linha: endereco, respondeu, portas, leitura.
function _redeNormalizar(teste, r) {
  const itens = (r && r.items) || [];
  if (teste === 'tcp' || teste === 'port_scan') {
    // Uma linha por host, nao por porta: o operador olha o equipamento.
    const porHost = new Map();
    itens.forEach(i => {
      const h = i.host || i.target || '';
      if (!porHost.has(h)) porHost.set(h, { target: h, online: false, portas: [], rtt_ms: null });
      const linha = porHost.get(h);
      if (i.open) {
        linha.online = true;
        linha.portas.push(i.port);
        if (linha.rtt_ms === null) linha.rtt_ms = i.rtt_ms ?? null;
      }
    });
    return [...porHost.values()];
  }
  if (teste === 'http') {
    return itens.map(i => ({
      target: i.target, online: !!i.ok, rtt_ms: i.elapsed_ms ?? null,
      portas: [], leitura: i.ok ? `HTTP ${i.status_code}${i.server ? ' · ' + i.server : ''}` : (i.error || ''),
    }));
  }
  if (teste === 'dns') {
    return itens.map(i => ({
      target: i.target, online: !!i.ok, rtt_ms: null, portas: [],
      leitura: i.ok ? (i.addresses || []).join(', ') : (i.error || 'não resolveu'),
    }));
  }
  if (teste === 'traceroute') {
    // Rota nao devolve lista: e texto corrido. Vira UMA linha, com o caminho.
    return [{
      target: r.target || '', online: !!r.ok, rtt_ms: null, portas: [],
      leitura: (r.stdout || r.stderr || r.error || '').split('\n').slice(0, 20).join(' | '),
    }];
  }
  return itens.map(i => ({
    target: i.target, online: !!i.online, rtt_ms: i.rtt_ms ?? null,
    portas: (i.tcp_results || []).filter(p => p && p.open).map(p => p.port),
    leitura: i.method === 'tcp-fallback' ? 'respondeu só em TCP' : (i.error || ''),
  }));
}

function pintarRedeFerramentas(body) {
  const corpo = document.getElementById('redeFerrCorpo');
  const resumo = document.getElementById('redeFerrResumo');
  const achados = document.getElementById('redeAchados');
  if (!corpo) return;

  // O endpoint devolve {ok, test, count, result:{items}}. Ler body.items
  // (que nao existe) fazia toda execucao terminar em "Nada respondeu".
  const r = (body && body.result) || body || {};
  const itens = _redeNormalizar(body && body.test, r);
  _redeFerrLinhas = itens;
  const responderam = itens.filter(i => i.online).length;
  if (resumo) resumo.textContent = `${itens.length} endereço${itens.length === 1 ? '' : 's'} testado${itens.length === 1 ? '' : 's'} · ${responderam} respondeu${responderam === 1 ? '' : 'ram'}`;

  if (!itens.length) {
    corpo.innerHTML = '<tr><td colspan="5" class="rede-vazio">Nada respondeu.</td></tr>';
    if (achados) achados.classList.add('hidden');
    return;
  }

  corpo.innerHTML = itens.map(i => {
    const ip = i.target || i.host || '';
    const vivo = !!i.online;
    const conhecido = _redeConhecido(ip);
    const portas = (i.portas || []).join(' · ');
    return `<tr class="${conhecido ? '' : 'rede-linha-instavel'}">
      <th scope="row" class="mono">${_redeEscapar(ip)}</th>
      <td>${conhecido
        ? _redeEscapar(conhecido)
        : '<span class="rede-alerta"><strong>não está no inventário</strong></span>'}</td>
      <td class="num mono">${vivo ? (i.rtt_ms !== null && i.rtt_ms !== undefined ? i.rtt_ms + ' ms' : 'respondeu')
        : '<span class="rede-ruim">sem resposta</span>'}</td>
      <td class="mono">${portas ? _redeEscapar(portas) : '<span class="rede-sem">—</span>'}</td>
      <td class="rede-suave">${_redeEscapar(i.leitura || '')}</td>
    </tr>`;
  }).join('');

  const fora = itens.filter(i => i.online && !_redeConhecido(i.target || ''));
  if (achados) {
    achados.classList.toggle('hidden', !fora.length);
    achados.innerHTML = fora.length ? `
      <span class="rede-achados-n mono">${fora.length}</span>
      <span class="rede-achados-txt">
        <strong>achado${fora.length === 1 ? '' : 's'} fora do inventário</strong>
        <span class="mono">${_redeEscapar(fora.map(i => i.target || i.host).slice(0, 6).join(', '))}</span>
      </span>` : '';
  }
}

let _redeInventarioIps = null;
function _redeConhecido(ip) {
  if (!ip || !_redeInventarioIps) return '';
  return _redeInventarioIps.get(String(ip)) || '';
}

// As tres visoes, nao so a OLT (que e o padrao do endpoint): cliente de
// switch teria o inventario inteiro marcado como "fora do inventario".
async function carregarRedeInventario() {
  const mapa = new Map();
  for (const modo of ['olt', 'basico', 'switch']) {
    try {
      const d = await apiJson(`/api/cameras?mode=${modo}`, { cacheTtl: 30000 });
      ((d && d.cameras) || []).forEach(c => { if (c.ip) mapa.set(String(c.ip), c.titulo || c.ip); });
    } catch (e) { /* visao sem inventario e normal */ }
  }
  _redeInventarioIps = mapa;
}

//  ── Entrada da tela ────────────────────────────────────────────────────────

async function loadNetOperate() {
  const data = await apiJson('/api/connectors');
  _connectors = (data && data.connectors) || _connectors || [];
  const sel = document.getElementById('netToolConnector');
  if (sel) {
    sel.innerHTML = _connectors.map(row =>
      `<option value="${_redeEscapar(row.id)}">${_redeEscapar(row.name || row.id)}</option>`).join('');
  }
  carregarRedeInventario();
  await carregarRedeTuneis(true);
  lucide.createIcons();
}

function ligarRede() {
  document.querySelectorAll('[data-rede-aba]').forEach(b =>
    b.addEventListener('click', () => _redeAba(b.dataset.redeAba)));

  document.getElementById('btnRedeAtualizar')?.addEventListener('click', () => carregarRedeTuneis(true));
  document.getElementById('btnRedeMedir')?.addEventListener('click', () => carregarRedeTuneis(true));
  document.getElementById('redeBusca')?.addEventListener('input', pintarRedeTuneis);
  document.getElementById('redeCliente')?.addEventListener('change', pintarRedeTuneis);

  document.querySelectorAll('[data-rede-estado]').forEach(b => b.addEventListener('click', () => {
    _redeEstado = b.dataset.redeEstado;
    pintarRedeFiltros();
    pintarRedeTuneis();
  }));

  // Delegado: as linhas e os cards sao repintados a cada medicao.
  document.getElementById('viewNetOperate')?.addEventListener('click', ev => {
    const alvo = ev.target.closest('[data-rede-diagnosticar]');
    if (alvo) tracarRedeCaminho(alvo.dataset.redeDiagnosticar, '');
  });

  document.getElementById('redeCamConector')?.addEventListener('change', pintarRedeAlvosEquipamento);
  document.getElementById('btnRedeCaminho')?.addEventListener('click', () => tracarRedeCaminho());

  document.querySelectorAll('[data-rede-teste]').forEach(b => b.addEventListener('click', () => {
    document.querySelectorAll('[data-rede-teste]').forEach(x => x.classList.toggle('ativa', x === b));
    const campo = document.getElementById('netToolTest');
    if (campo) campo.value = b.dataset.redeTeste;
    // A coleta de ARP/MAC nao existe no teste local -- ela le as tabelas do
    // proprio MikroTik. Mandar para o local respondia "teste invalido" e o
    // operador nao tinha como adivinhar por que.
    const origem = document.getElementById('netToolOrigin');
    if (origem) {
      if (b.dataset.redeTeste === 'lan_inventory') origem.value = 'connector';
      else if (origem.value === 'connector' && b.dataset.redeTeste !== 'ping') origem.value = 'local';
    }
    updateNetToolFormState();
  }));

  document.getElementById('btnRedeLimpar')?.addEventListener('click',
    () => pintarRedeFerramentas({ result: { items: [] } }));

  // "Do inventário": preenche com as faixas /24 onde o cliente realmente tem
  // equipamento. Varrer a faixa inteira digitada a mao e como se descobre
  // equipamento que ninguem cadastrou -- e era o que o botao prometia.
  document.getElementById('btnRedeDoInventario')?.addEventListener('click', async () => {
    const campo = document.getElementById('netToolTargets');
    if (!campo) return;
    if (!_redeInventarioIps) await carregarRedeInventario();
    const faixas = [...new Set([..._redeInventarioIps.keys()]
      .map(ip => { const p = String(ip).split('.'); return p.length === 4 ? `${p[0]}.${p[1]}.${p[2]}.0/24` : ''; })
      .filter(Boolean))];
    if (!faixas.length) { showToast('Nenhum equipamento no inventário deste cliente.', true); return; }
    campo.value = faixas.join(', ');
    showToast(`${faixas.length} faixa${faixas.length === 1 ? '' : 's'} do inventário`);
  });

  document.getElementById('btnRedeCsv')?.addEventListener('click', () => {
    if (!_redeFerrLinhas.length) { showToast('Nada para baixar ainda.', true); return; }
    const linhas = [['endereco', 'quem_e', 'respondeu', 'ms', 'portas', 'leitura']];
    _redeFerrLinhas.forEach(i => linhas.push([
      i.target || '', _redeConhecido(i.target || '') || 'fora do inventario',
      i.online ? 'sim' : 'nao', i.rtt_ms ?? '', (i.portas || []).join(' '), (i.leitura || '').replace(/[\r\n;]+/g, ' '),
    ]));
    const csv = linhas.map(l => l.map(c => `"${String(c).replace(/"/g, '""')}"`).join(';')).join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `rede_${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  });
}
