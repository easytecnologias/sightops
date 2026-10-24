// Switch Provedores (menu Redes): switches da rede neutra (MikroTik) lidas pela
// API, so leitura, pelo tunel do conector. A leitura de cada minuto alimenta
// esta tela, o Zabbix e os links dos provedores do rack (mapaRack.js).

let _swp = { lista: [], aberta: '', bound: false, conectores: null };

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
      if (b.dataset.swp === 'abrir') { _swp.aberta = _swp.aberta === id ? '' : id; swpRender(); }
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
    const comLink = portas.filter(p => p.running).length;
    const aberta = _swp.aberta === sw.id;
    const linhas = portas.map((p) => `<tr>
        <td><strong>${esc(p.nome)}</strong></td>
        <td>${esc(p.comentario || '')}</td>
        <td>${p.disabled ? '<span class="pill neutral">desligada</span>' : p.running ? '<span class="pill success">com link</span>' : '<span class="pill danger">sem link</span>'}</td>
        <td>${esc(p.rate || '—')}</td>
        <td>${p.in_bps != null ? `↓ ${swpBps(p.in_bps)} <small class="rkv-cinza">↑ ${swpBps(p.out_bps)}</small>` : '—'}</td>
        <td>${p.sfp_rx_dbm != null ? `<strong>${Number(p.sfp_rx_dbm).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} dBm</strong> <small class="rkv-cinza">tx ${p.sfp_tx_dbm != null ? Number(p.sfp_tx_dbm).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) : '—'}</small>` : '<span class="rkv-cinza">—</span>'}</td>
        <td>${p.erros ? `<span class="pill danger">${p.erros}</span>` : '<span class="rkv-cinza">0</span>'}</td></tr>`).join('');
    return `<article class="swp-card${aberta ? ' aberta' : ''}">
      <div class="swp-topo">
        <button type="button" class="swp-titulo" data-swp="abrir" data-id="${esc(sw.id)}" aria-expanded="${aberta}">
          <i data-lucide="${aberta ? 'chevron-down' : 'chevron-right'}"></i>
          <span><strong>${esc(sw.nome)}</strong><small>${esc([sw.site, sw.ip, sw.leitura?.modelo, sw.leitura?.versao].filter(Boolean).join(' · '))}</small></span>
        </button>
        <span class="pill ${e.cls}" title="${esc(sw.erro || '')}">${e.txt}</span>
        <span class="rkv-cinza swp-info">${portas.length ? `${comLink}/${portas.length} portas com link` : ''}</span>
        <span class="rkv-cinza swp-info">lida ${esc(swpQuando(sw.lido_em))}</span>
        <button type="button" class="secondary-action" data-swp="testar" data-id="${esc(sw.id)}"><i data-lucide="activity"></i> Testar</button>
        <button type="button" class="secondary-action" data-swp="editar" data-id="${esc(sw.id)}"><i data-lucide="pencil"></i> Editar</button>
      </div>
      ${sw.erro ? `<p class="swp-erro">${esc(sw.erro)}</p>` : ''}
      ${aberta ? (portas.length
        ? `<div class="rkv-tabela-box"><table class="rkv-tabela"><thead><tr><th>Porta</th><th>Comentário</th><th>Link</th><th>Velocidade</th><th>Tráfego</th><th>Sinal da fibra (rx)</th><th>Erros</th></tr></thead><tbody>${linhas}</tbody></table></div>`
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
    _swp.aberta = out.id;
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
