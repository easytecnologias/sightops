// Switch Provedores (menu Redes): switches da rede neutra (MikroTik) lidas pela
// API, so leitura, pelo tunel do conector. A leitura de cada minuto alimenta
// esta tela, o Zabbix e os links dos provedores do rack (mapaRack.js).

let _swp = { lista: [], fechadas: new Set(), todas: new Set(), sel: null, bound: false, conectores: null, timer: null };

function swpBps(v) {
  if (v == null || v === '') return '—';
  const n = Number(v);
  if (n >= 1e9) return `${(n / 1e9).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} Gbps`;
  if (n >= 1e6) return `${(n / 1e6).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} Mbps`;
  return `${Math.round(n / 1e3).toLocaleString('pt-BR')} kbps`;
}

function swpEstado(sw) {
  if (!sw.ativo) return { cls: 'neutral', txt: 'leitura desligada' };
  if (!sw.tem_senha) return { cls: 'amber', txt: 'falta a senha' };
  if (sw.erro) return { cls: 'danger', txt: 'sem resposta' };
  if (sw.lido_em) return { cls: 'success', txt: 'no ar' };
  return { cls: 'neutral', txt: 'aguardando a 1ª leitura' };
}

function swpQuando(iso) {
  if (!iso) return 'nunca';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

async function loadSwitchProvedores() {
  if (!_swp.bound) {
    _swp.bound = true;
    document.getElementById('btnSwpNova')?.addEventListener('click', () => swpAbrir(null));
    document.getElementById('swpLista')?.addEventListener('click', (ev) => {
      const b = ev.target.closest('[data-swp]');
      if (!b) return;
      const id = b.dataset.id;
      if (b.dataset.swp === 'abrir') { _swp.fechadas.has(id) ? _swp.fechadas.delete(id) : _swp.fechadas.add(id); swpRender(); }
      if (b.dataset.swp === 'todas') { _swp.todas.has(id) ? _swp.todas.delete(id) : _swp.todas.add(id); swpRender(); }
      if (b.dataset.swp === 'porta') {
        // clicar na gaiola mostra so aquela porta; de novo (ou "Ver todas") volta
        const porta = b.dataset.porta;
        _swp.sel = _swp.sel?.sw === id && _swp.sel.porta === porta ? null : { sw: id, porta };
        swpRender();
      }
      if (b.dataset.swp === 'editar') swpAbrir(_swp.lista.find(s => s.id === id));
      if (b.dataset.swp === 'testar') swpTestar(id, b);
    });
    document.querySelectorAll('[data-swp-fechar]').forEach(b => b.addEventListener('click', swpFechar));
    document.getElementById('swpSalvar')?.addEventListener('click', swpSalvar);
    document.getElementById('swpExcluir')?.addEventListener('click', swpExcluir);
    // Fecha so por X, Cancelar ou Esc: clicar fora perdia o que foi digitado.
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && !document.getElementById('modalSwp')?.classList.contains('hidden')
          && document.getElementById('modalConfirm')?.classList.contains('hidden')) swpFechar();
    });
  }
  await swpCarregar();
  // a leitura e de minuto em minuto: a tela acompanha enquanto estiver aberta
  if (!_swp.timer) {
    _swp.timer = setInterval(() => {
      const v = document.getElementById('viewSwitchProvedores');
      if (v && !v.classList.contains('hidden') && document.getElementById('modalSwp')?.classList.contains('hidden')) swpCarregar();
    }, 60000);
  }
}

async function swpCarregar() {
  const box = document.getElementById('swpLista');
  try {
    const res = await api('/api/switch/provedores');
    if (!res) return;
    _swp.lista = (await jsonOrReadableError(res, 'Falha ao carregar as switches.')).switches || [];
  } catch (err) {
    box.innerHTML = `<div class="rotas-vazio"><p>${esc(err.message)}</p></div>`;
    return;
  }
  swpRender();
}

// ------------------------------------------------------------------ desenho
// Cada switch: indicadores, o painel frontal (as gaiolas SFP como na switch de
// verdade, coloridas pelo estado) e um cartao por porta em uso, com o grafico
// da ultima hora (historico guardado a cada leitura) e o sinal da fibra.

const SWP_RATE = { '10Gbps': 1e10, '25Gbps': 2.5e10, '40Gbps': 4e10, '1Gbps': 1e9, '2.5Gbps': 2.5e9, '5Gbps': 5e9, '100Mbps': 1e8, '10Mbps': 1e7 };

function swpUptime(u) {
  const m = String(u || '').match(/(?:(\d+)w)?(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?/);
  if (!m || !u) return '—';
  const dias = Number(m[1] || 0) * 7 + Number(m[2] || 0);
  const h = Number(m[3] || 0);
  return dias ? `${dias}d ${h}h` : `${h}h ${Number(m[4] || 0)}min`;
}

const swpDbm = v => (v == null ? '—' : `${Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} dBm`);

// faixa do sinal recebido: acima de -1 satura, ate -20 bom, ate -25 no limite
function swpSinal(rx) {
  if (rx == null) return { cls: 'nada', txt: 'sem medição' };
  if (rx > -1) return { cls: 'alerta', txt: 'forte demais' };
  if (rx >= -20) return { cls: 'bom', txt: 'bom' };
  if (rx >= -25) return { cls: 'alerta', txt: 'no limite' };
  return { cls: 'ruim', txt: 'fraco' };
}

// estado da porta no painel: em uso (link), caida (tem nome e nao tem link),
// modulo sem link, gaiola vazia
function swpPortaEstado(p) {
  if (p.disabled) return 'desligada';
  if (p.running) return 'link';
  if (p.comentario) return 'caida';
  return p.sfp_presente === 'true' ? 'modulo' : 'vazia';
}

function swpSpark(pts, rate) {
  const ok = (pts || []).filter(x => x[1] != null);
  if (ok.length < 2) return '<div class="swp-spark-vazio">o gráfico aparece a partir da 2ª leitura</div>';
  const W = 260, H = 54;
  const t0 = ok[0][0], t1 = ok[ok.length - 1][0] || t0 + 1;
  const max = Math.max(1, ...ok.map(x => Math.max(x[1] || 0, x[2] || 0)));
  const xy = (x, v) => `${(((x - t0) / Math.max(1, t1 - t0)) * W).toFixed(1)},${(H - 2 - (v / max) * (H - 6)).toFixed(1)}`;
  const linha = i => ok.map(x => xy(x[0], x[i] || 0)).join(' ');
  const area = `0,${H} ${linha(1)} ${W},${H}`;
  return `<svg class="swp-spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Tráfego da última hora">
    <polygon class="area" points="${area}"/><polyline class="in" points="${linha(1)}"/><polyline class="out" points="${linha(2)}"/></svg>
    <div class="swp-spark-eixo"><span>${Math.round((t1 - t0) / 60)} min</span><span>pico ${swpBps(max)}</span></div>`;
}

function swpPainel(sw, portas) {
  const sel = _swp.sel?.sw === sw.id ? _swp.sel.porta : '';
  const gaiola = (p, n) => {
    const est = swpPortaEstado(p);
    return `<button type="button" class="swp-gaiola ${est}${sel === p.nome ? ' sel' : ''}" data-swp="porta" data-id="${esc(sw.id)}" data-porta="${esc(p.nome)}"
      title="${esc(`${p.nome}${p.comentario ? ` — ${p.comentario}` : ''}${p.rate ? ` · ${p.rate}` : ''}`)}"><i class="led"></i><span>${esc(n)}</span></button>`;
  };
  const sfp = portas.filter(p => /sfp/i.test(p.nome));
  const num = p => Number((p.nome.match(/(\d+)$/) || [])[1] || 0);
  const cima = sfp.filter(p => num(p) % 2 === 1), baixo = sfp.filter(p => num(p) % 2 === 0);
  const ether = portas.filter(p => !/sfp/i.test(p.nome));
  return `<div class="swp-frente" aria-label="Painel frontal">
    <div class="swp-marca"><strong>MikroTik</strong><span>${esc(sw.leitura?.modelo || '')}</span></div>
    <div class="swp-ether">${ether.map(p => gaiola(p, p.nome.replace(/^ether/, 'E'))).join('')}</div>
    <div class="swp-gaiolas"><div>${cima.map(p => gaiola(p, num(p))).join('')}</div><div>${baixo.map(p => gaiola(p, num(p))).join('')}</div></div>
  </div>
  <div class="swp-legenda"><span><i class="link"></i>com link</span><span><i class="caida"></i>provedor sem link</span><span><i class="modulo"></i>módulo sem link</span><span><i class="vazia"></i>vazia</span></div>`;
}

function swpCartaoPorta(sw, p) {
  const est = swpPortaEstado(p);
  const pts = sw.leitura?.hist?.[p.nome] || [];
  const rate = SWP_RATE[p.rate] || 0;
  const uso = rate && p.in_bps != null ? Math.min(100, (Math.max(p.in_bps, p.out_bps || 0) / rate) * 100) : null;
  const s = swpSinal(p.sfp_rx_dbm);
  const pos = p.sfp_rx_dbm == null ? null : Math.max(0, Math.min(100, ((p.sfp_rx_dbm + 30) / 30) * 100));
  const rx0 = pts.find(x => x[3] != null)?.[3];
  const tend = p.sfp_rx_dbm != null && rx0 != null ? p.sfp_rx_dbm - rx0 : null;
  const sfpInfo = [p.sfp_fabricante, p.sfp_modelo, p.sfp_onda_nm ? `${p.sfp_onda_nm} nm` : '', p.sfp_temp_c != null ? `${p.sfp_temp_c} °C` : ''].filter(Boolean).join(' · ');
  const sel = _swp.sel?.sw === sw.id && _swp.sel.porta === p.nome;
  return `<article class="swp-porta ${est}${sel ? ' sel' : ''}" data-porta-card="${esc(sw.id)}:${esc(p.nome)}">
    <header><div><strong>${esc(p.comentario || p.nome)}</strong><small>${esc([p.comentario ? p.nome : '', p.rate].filter(Boolean).join(' · '))}</small></div>
      <span class="pill ${est === 'link' ? 'success' : est === 'caida' ? 'danger' : 'neutral'}">${{ link: 'com link', caida: 'sem link', modulo: 'sem link', vazia: 'vazia', desligada: 'desligada' }[est]}</span></header>
    ${p.running ? `<div class="swp-trafego"><span class="in">↓ ${swpBps(p.in_bps)}</span><span class="out">↑ ${swpBps(p.out_bps)}</span>
      ${uso != null ? `<span class="swp-uso" title="uso da porta">${uso < 1 ? '<1' : Math.round(uso)}% da porta</span>` : ''}</div>
      ${swpSpark(pts, rate)}
      ${uso != null ? `<div class="swp-barra"><i style="width:${Math.max(1, uso)}%"></i></div>` : ''}` : ''}
    ${!p.running ? `<p class="swp-porta-aviso">${est === 'caida' ? 'Tem nome, mas está sem link agora.' : est === 'modulo' ? 'Módulo encaixado, sem link.' : 'Sem módulo.'}${p.sfp_presente === 'false' && p.comentario ? ' Sem módulo SFP na gaiola.' : ''}</p>` : ''}
    ${p.sfp_rx_dbm != null ? `<div class="swp-sinal ${s.cls}">
      <div class="swp-sinal-topo"><span>Sinal da fibra</span><strong>${swpDbm(p.sfp_rx_dbm)}</strong><em>${s.txt}${tend != null && Math.abs(tend) >= 0.5 ? ` · ${tend > 0 ? '+' : ''}${tend.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} dB na última hora` : ''}</em></div>
      <div class="swp-regua"><i style="left:${pos}%"></i></div><div class="swp-regua-eixo"><span>-30</span><span>-25</span><span>-20</span><span>0 dBm</span></div>
      <small>tx ${swpDbm(p.sfp_tx_dbm)}</small></div>` : ''}
    <footer>${sfpInfo ? `<span title="módulo SFP">${esc(sfpInfo)}</span>` : '<span></span>'}
      <span class="${p.erros ? 'erro' : ''}">${p.erros ? `${p.erros} erros no último minuto` : 'sem erros'}</span></footer>
  </article>`;
}

function swpIndicadores(sw, portas) {
  const L = sw.leitura || {};
  const comLink = portas.filter(p => p.running);
  const comSinal = portas.filter(p => p.sfp_rx_dbm != null && p.running);
  const pior = comSinal.sort((a, b) => a.sfp_rx_dbm - b.sfp_rx_dbm)[0];
  const top = [...comLink].sort((a, b) => (b.in_bps || 0) + (b.out_bps || 0) - (a.in_bps || 0) - (a.out_bps || 0))[0];
  const caidas = portas.filter(p => swpPortaEstado(p) === 'caida');
  const mem = L.memoria_total ? Math.round((1 - (L.memoria_livre || 0) / L.memoria_total) * 100) : null;
  const tile = (rot, val, sub, cls = '') => `<div class="swp-kpi ${cls}"><span>${rot}</span><strong>${val}</strong><small>${sub || '&nbsp;'}</small></div>`;
  return `<div class="swp-kpis">
    ${tile('Portas com link', `${comLink.length}<em>/${portas.length}</em>`, caidas.length ? `${caidas.length} com nome e sem link` : 'nenhuma caída', caidas.length ? 'ruim' : 'bom')}
    ${tile('Pior sinal', pior ? swpDbm(pior.sfp_rx_dbm) : '—', pior ? esc(pior.comentario || pior.nome) : 'sem medição', pior ? swpSinal(pior.sfp_rx_dbm).cls : '')}
    ${tile('Maior tráfego', top && top.in_bps != null ? swpBps((top.in_bps || 0) + (top.out_bps || 0)) : '—', top ? esc(top.comentario || top.nome) : '')}
    ${tile('Ligada há', swpUptime(L.uptime), esc(L.versao || ''))}
    ${tile('CPU', L.cpu_pct != null ? `${L.cpu_pct}%` : '—', mem != null ? `memória ${mem}%` : '')}
    ${tile('Temperatura', L.temperatura_c != null ? `${L.temperatura_c} °C` : '—', L.tensao_v != null ? `${L.tensao_v.toLocaleString('pt-BR')} V` : '', L.temperatura_c >= 70 ? 'ruim' : '')}
  </div>`;
}

function swpRender() {
  const box = document.getElementById('swpLista');
  if (!box) return;
  if (!_swp.lista.length) {
    box.innerHTML = `<div class="rotas-vazio">
      <div class="rotas-vazio-icone"><i data-lucide="network"></i></div>
      <h2>Nenhuma switch de provedores</h2>
      <p>Cadastre as switches da rede neutra (ex.: CRS317) com o IP de gerência, o conector e um usuário só de leitura. A partir daí o SightOps lê as portas a cada minuto e leva ao Zabbix.</p>
      <button class="primary-action" type="button" onclick="swpAbrir(null)"><i data-lucide="plus"></i> Nova switch</button></div>`;
    lucide.createIcons();
    return;
  }
  box.innerHTML = _swp.lista.map((sw) => {
    const e = swpEstado(sw);
    const portas = sw.leitura?.portas || [];
    const aberta = !_swp.fechadas.has(sw.id);
    const todas = _swp.todas.has(sw.id);
    const visiveis = portas.filter(p => todas || p.running || p.comentario);
    const ocultas = portas.length - visiveis.length;
    const filtro = _swp.sel?.sw === sw.id ? _swp.sel.porta : '';
    return `<article class="swp-card${aberta ? ' aberta' : ''}">
      <div class="swp-topo">
        <button type="button" class="swp-titulo" data-swp="abrir" data-id="${esc(sw.id)}" aria-expanded="${aberta}">
          <i data-lucide="${aberta ? 'chevron-down' : 'chevron-right'}"></i>
          <span><strong>${esc(sw.nome)}</strong><small>${esc([sw.site, sw.ip, sw.leitura?.modelo].filter(Boolean).join(' · '))}</small></span>
        </button>
        <span class="pill ${e.cls}" title="${esc(sw.erro || '')}">${e.txt}</span>
        <span class="rkv-cinza swp-info">lida ${esc(swpQuando(sw.lido_em))}</span>
        <button type="button" class="secondary-action" data-swp="testar" data-id="${esc(sw.id)}"><i data-lucide="refresh-cw"></i> Ler agora</button>
        <button type="button" class="secondary-action" data-swp="editar" data-id="${esc(sw.id)}"><i data-lucide="pencil"></i> Editar</button>
      </div>
      ${sw.erro ? `<p class="swp-erro">${esc(sw.erro)}</p>` : ''}
      ${aberta ? (portas.length ? `
        ${swpIndicadores(sw, portas)}
        ${swpPainel(sw, portas)}
        <div class="swp-portas-topo"><strong>${filtro ? `Porta ${esc(filtro)}` : 'Portas em uso'}</strong>
          ${filtro ? `<button type="button" class="ghost-action" data-swp="porta" data-id="${esc(sw.id)}" data-porta="${esc(filtro)}">Ver todas</button>`
            : (ocultas || todas ? `<button type="button" class="ghost-action" data-swp="todas" data-id="${esc(sw.id)}">${todas ? 'Esconder as vazias' : `Mostrar as ${ocultas} vazias`}</button>` : '')}</div>
        <div class="swp-portas">${(filtro ? portas.filter(p => p.nome === filtro) : visiveis).map(p => swpCartaoPorta(sw, p)).join('')}</div>`
        : '<p class="rkv-cinza" style="margin:0">Ainda sem leitura das portas.</p>') : ''}
    </article>`;
  }).join('');
  lucide.createIcons();
}

async function swpConectores() {
  if (_swp.conectores) return _swp.conectores;
  try {
    const res = await api('/api/monitoring/entities?entity_type=connector&limit=500');
    const d = res?.ok ? await res.json() : null;
    _swp.conectores = (d?.entities || []).map(e => ({ id: e.entity_id, nome: e.display_name || e.entity_id, site: e.site || '' }));
  } catch (_) { _swp.conectores = []; }
  return _swp.conectores;
}

async function swpAbrir(sw) {
  const conectores = await swpConectores();
  const v = (id, val) => { const el = document.getElementById(id); if (el) el.value = val ?? ''; };
  document.getElementById('swpModalTitulo').textContent = sw ? `Editar ${sw.nome}` : 'Nova switch';
  v('swpId', sw?.id); v('swpNome', sw?.nome); v('swpSite', sw?.site); v('swpIp', sw?.ip);
  v('swpUsuario', sw?.usuario); v('swpSenha', ''); v('swpPorta', sw?.porta || 8728);
  document.getElementById('swpSenha').placeholder = sw?.tem_senha ? 'já guardada (digite só para trocar)' : '';
  document.getElementById('swpAtivo').checked = sw ? Boolean(sw.ativo) : true;
  document.getElementById('swpConector').innerHTML = `<option value="">Escolha o conector...</option>${conectores.map(c => `<option value="${esc(c.id)}" ${sw?.connector_id === c.id ? 'selected' : ''}>${esc(c.nome)}${c.site && c.site !== c.nome ? ` · ${esc(c.site)}` : ''}</option>`).join('')}`;
  document.getElementById('swpExcluir').hidden = !sw;
  document.getElementById('swpErro').hidden = true;
  document.getElementById('modalSwp').classList.remove('hidden');
  lucide.createIcons();
  document.getElementById('swpNome').focus();
}

function swpFechar() {
  document.getElementById('modalSwp')?.classList.add('hidden');
}

function swpFalha(msg) {
  const er = document.getElementById('swpErro');
  er.textContent = msg; er.hidden = false;
}

async function swpSalvar() {
  const g = id => (document.getElementById(id)?.value ?? '').trim();
  const payload = {
    id: g('swpId'), nome: g('swpNome'), site: g('swpSite'), ip: g('swpIp'), connector_id: g('swpConector'),
    usuario: g('swpUsuario'), senha: document.getElementById('swpSenha').value, porta: Number(g('swpPorta') || 8728),
    ativo: document.getElementById('swpAtivo').checked,
  };
  const btn = document.getElementById('swpSalvar');
  btn.disabled = true;
  try {
    const res = await api('/api/switch/provedores', { method: 'POST', body: JSON.stringify(payload) });
    if (!res) return;
    const out = await jsonOrReadableError(res, 'Falha ao salvar.');
    swpFechar();
    if (out.precisa_senha) showToast('Salvo, mas sem senha: IP, porta, conector ou usuário mudou. Digite a senha de novo.', true);
    else showToast('Switch salva. Testando a leitura...');
    _swp.fechadas.delete(out.id);
    await swpCarregar();
    if (!out.precisa_senha) await swpTestar(out.id);
  } catch (err) {
    swpFalha(err.message || 'Falha ao salvar.');
  } finally {
    btn.disabled = false;
  }
}

async function swpTestar(id, btn) {
  if (btn) btn.disabled = true;
  try {
    const res = await api(`/api/switch/provedores/${encodeURIComponent(id)}/testar`, { method: 'POST' });
    if (!res) return;
    // leitura que falhou vem com ok=false e o motivo em "erro" (nao e erro HTTP)
    const d = res.ok ? await res.json() : await jsonOrReadableError(res, 'Falha ao testar.');
    if (d.ok) showToast(`Leu ${d.identidade || 'a switch'}: ${(d.portas || []).filter(p => p.running).length}/${(d.portas || []).length} portas com link.`);
    else showToast(`Não leu: ${d.erro || 'falha'}`, true);
    await swpCarregar();
  } catch (err) {
    showToast(err.message || 'Falha ao testar.', true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function swpExcluir() {
  const id = (document.getElementById('swpId')?.value || '').trim();
  const sw = _swp.lista.find(s => s.id === id);
  if (!sw || !(await showConfirm({ eyebrow: 'Switch Provedores', title: `Excluir ${sw.nome}?`, label: 'Excluir',
    msg: 'A switch sai do monitoramento e do Zabbix. Se estiver em algum rack, tire de lá antes.' }))) return;
  try {
    const res = await api(`/api/switch/provedores/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res) return;
    await jsonOrReadableError(res, 'Falha ao excluir.');
    swpFechar();
    showToast('Switch excluída.');
    await swpCarregar();
  } catch (err) {
    swpFalha(err.message || 'Falha ao excluir.');
  }
}
