// Implantacao > Ativacao de Cameras.
//
// Camera Intelbras de fabrica nao tem senha e por isso e invisivel pro resto
// do sistema (snapshot, CGI, gravador -- tudo 401). Esta tela acha essas
// cameras pelo conector do site e cria a senha nelas, uma ou em lote.
//
// O backend faz o trabalho pesado com o NetSDK (app/services/intelbras_netsdk.py);
// aqui e so escolher o site, conferir a lista e confirmar.

let _activationDevices = [];
let _activationSelected = new Set();   // chaves = MAC
let _activationPendingTargets = [];    // o que o modal vai ativar ao confirmar
let _activationFilter = 'todas';       // todas | fabrica | ativas

function activationKey(dev) {
  return String(dev?.mac || '').toLowerCase();
}

function activationEstado(dev) {
  if (dev.needs_activation) return { classe: 'badge-amber', texto: 'De fabrica' };
  if (dev.init_status === 2) return { classe: 'badge-green', texto: 'Ja ativada' };
  return { classe: 'badge-gray', texto: 'Modelo antigo' };
}

function activationRecuperacao(dev) {
  const vias = [];
  if (dev.needs_phone) vias.push('celular');
  if (dev.needs_email) vias.push('e-mail');
  return vias.join(' / ') || '-';
}

function activationVisiveis() {
  if (_activationFilter === 'fabrica') return _activationDevices.filter(d => d.needs_activation);
  if (_activationFilter === 'ativas') return _activationDevices.filter(d => !d.needs_activation);
  return _activationDevices;
}

async function loadDeployActivation() {
  const select = document.getElementById('activationConnector');
  if (!select) return;

  // Sem a lib do NetSDK no servidor nada aqui funciona -- avisa antes de o
  // usuario escolher site e senha pra so entao descobrir.
  const status = await apiJson('/api/deployments/activation/status').catch(() => null);
  const aviso = document.getElementById('activationSdkWarning');
  if (aviso) {
    const quebrado = status && status.ok === false;
    aviso.style.display = quebrado ? '' : 'none';
    if (quebrado) {
      document.getElementById('activationSdkWarningText').textContent =
        `A biblioteca do NetSDK nao carregou (${status.error || 'motivo nao informado'}). ` +
        `Esperada em ${status.lib_dir || '?'}. Ativar camera de fabrica depende dela.`;
    }
  }

  const data = await apiJson('/api/connectors');
  const conectores = (Array.isArray(data?.connectors) ? data.connectors : [])
    .filter(c => String(c.type || '').toLowerCase() === 'routeros');
  select.innerHTML = '<option value="">Escolha o site</option>' + conectores.map(c => {
    const online = String(c.status || '').toLowerCase() === 'online';
    const nome = c.name || c.client || c.site || c.id;
    return `<option value="${esc(c.id)}" ${online ? '' : 'disabled'}>${esc(nome)}${online ? '' : ' (offline)'}</option>`;
  }).join('');

  // Site do inventario costuma ter o mesmo nome do conector -- preenche sozinho
  // pra senha cair no cofre do site certo, mas deixa editavel.
  select.onchange = () => {
    const c = conectores.find(x => String(x.id) === select.value);
    const campo = document.getElementById('activationSite');
    if (c && campo && !campo.value.trim()) campo.value = c.site || c.client || c.name || '';
  };
  activationRender();
}

function activationExpandRange(texto) {
  // "172.28.1.200-172.28.1.254" ou "172.28.1.200-254"
  const t = String(texto || '').trim();
  if (!t) return [];
  const m = t.match(/^(\d+\.\d+\.\d+)\.(\d+)\s*-\s*(?:\d+\.\d+\.\d+\.)?(\d+)$/);
  if (!m) return [];
  const [, base, ini, fim] = m;
  const a = parseInt(ini, 10), b = parseInt(fim, 10);
  if (isNaN(a) || isNaN(b) || b < a || b - a > 254) return [];
  const out = [];
  for (let i = a; i <= b; i++) out.push(`${base}.${i}`);
  return out;
}

async function activationScan() {
  const connectorId = document.getElementById('activationConnector')?.value || '';
  if (!connectorId) { showToast('Escolha o site primeiro.', true); return; }

  const botoes = ['btnActivationScan', 'btnActivationRescan']
    .map(id => document.getElementById(id)).filter(Boolean);
  const original = botoes.map(b => b.innerHTML);
  botoes.forEach(b => { b.disabled = true; });
  if (botoes[0]) botoes[0].innerHTML = 'Varrendo o site...';

  try {
    const ips = activationExpandRange(document.getElementById('activationRange')?.value);
    const res = await api('/api/deployments/activation/scan', {
      method: 'POST',
      body: JSON.stringify({ connector_id: connectorId, ips }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'falha na varredura');

    _activationDevices = Array.isArray(data.devices) ? data.devices : [];
    _activationSelected = new Set();
    // Quem abre a tela quer ver o que falta ativar; se nao ha nada de fabrica,
    // mostrar a lista vazia seria confuso, entao cai pra "todas".
    _activationFilter = _activationDevices.some(d => d.needs_activation) ? 'fabrica' : 'todas';
    activationRender(data);
    if (!_activationDevices.length) {
      showToast(data.detail || 'Nenhuma camera respondeu nos enderecos sondados.', true);
    }
  } catch (err) {
    showToast(`Nao consegui varrer: ${err.message}`, true);
  } finally {
    botoes.forEach((b, i) => { b.disabled = false; b.innerHTML = original[i]; });
    if (window.lucide) lucide.createIcons();
  }
}

function activationRender(data) {
  const corpo = document.getElementById('activationTableBody');
  const vazio = document.getElementById('activationEmpty');
  if (!corpo) return;

  const pendentes = _activationDevices.filter(d => d.needs_activation).length;
  const total = _activationDevices.length;
  document.getElementById('activationCountAll').textContent = total;
  document.getElementById('activationCountPending').textContent = pendentes;
  document.getElementById('activationCountDone').textContent = total - pendentes;

  const resumo = document.getElementById('activationSummary');
  if (resumo) {
    resumo.textContent = total
      ? `${total} equipamentos responderam de ${data?.scanned ?? '?'} enderecos sondados -- ` +
        `${pendentes} de fabrica, ${total - pendentes} ja ativados. ` +
        `Origem: ${data?.source === 'manual' ? 'faixa informada' : 'ARP/DHCP do MikroTik'}.`
      : 'Escolha o site e clique em Varrer site.';
  }

  document.querySelectorAll('[data-activation-filter]').forEach(el => {
    el.classList.toggle('active', el.dataset.activationFilter === _activationFilter);
  });

  const visiveis = activationVisiveis();
  if (vazio) {
    vazio.style.display = visiveis.length ? 'none' : '';
    if (!visiveis.length && total) {
      vazio.innerHTML = '<i data-lucide="filter"></i><strong>Nada neste filtro</strong>' +
        'As cameras varridas estao em outra aba acima.';
    }
  }

  corpo.innerHTML = visiveis.map(dev => {
    const k = activationKey(dev);
    const pode = !!dev.needs_activation;
    const est = activationEstado(dev);
    return `<tr class="${pode ? '' : 'activation-row-done'}">
      <td><input type="checkbox" class="activation-check" data-mac="${esc(k)}" ${pode ? '' : 'disabled'} ${_activationSelected.has(k) ? 'checked' : ''}></td>
      <td><span class="badge ${est.classe}">${est.texto}</span></td>
      <td class="activation-mono">${esc(dev.ip || '')}</td>
      <td class="activation-mono">${esc(dev.mac || '')}</td>
      <td>${esc(dev.model || '')}</td>
      <td class="activation-mono">${esc(dev.firmware || '')}</td>
      <td>${activationRecuperacao(dev)}</td>
      <td>${pode
        ? `<button class="secondary-action activation-run-one" data-mac="${esc(k)}" type="button">Ativar</button>`
        : '<span class="muted">-</span>'}</td>
    </tr>`;
  }).join('');

  corpo.querySelectorAll('.activation-check').forEach(el => {
    el.onchange = () => {
      if (el.checked) _activationSelected.add(el.dataset.mac);
      else _activationSelected.delete(el.dataset.mac);
      activationUpdateBatchButton();
    };
  });
  corpo.querySelectorAll('.activation-run-one').forEach(el => {
    el.onclick = () => activationOpenModal([el.dataset.mac]);
  });
  activationUpdateBatchButton();
  if (window.lucide) lucide.createIcons();
}

function activationUpdateBatchButton() {
  const botao = document.getElementById('btnActivationRunBatch');
  if (!botao) return;
  const n = _activationSelected.size;
  botao.disabled = n === 0;
  botao.innerHTML = `<i data-lucide="key-round"></i> Ativar selecionadas${n ? ` (${n})` : ''}`;
  if (window.lucide) lucide.createIcons();
}

function activationOpenModal(macs) {
  const alvos = _activationDevices.filter(d => macs.includes(activationKey(d)) && d.needs_activation);
  if (!alvos.length) { showToast('Nenhuma camera de fabrica selecionada.', true); return; }
  _activationPendingTargets = alvos;

  document.getElementById('activationModalTitle').textContent =
    alvos.length === 1 ? 'Ativar 1 camera' : `Ativar ${alvos.length} cameras`;
  document.getElementById('activationTargetsHint').textContent =
    alvos.map(d => `${d.ip} (${d.model || 'modelo ?'})`).join(', ');

  // Modelo que so aceita e-mail de recuperacao torna o campo obrigatorio -- o
  // SDK recusa o init sem ele, entao e melhor exigir aqui.
  const exigeEmail = alvos.some(d => d.needs_email);
  const campoEmail = document.getElementById('activationEmail');
  if (campoEmail) campoEmail.placeholder = exigeEmail ? 'obrigatorio nestes modelos' : 'opcional';

  document.getElementById('modalActivationCredentials')?.classList.remove('hidden');
  if (window.lucide) lucide.createIcons();
}

function closeActivationModal() {
  document.getElementById('modalActivationCredentials')?.classList.add('hidden');
  _activationPendingTargets = [];
}

async function activationConfirm() {
  const senha = document.getElementById('activationPassword')?.value || '';
  const senha2 = document.getElementById('activationPassword2')?.value || '';
  const email = document.getElementById('activationEmail')?.value?.trim() || '';
  const usuario = document.getElementById('activationUser')?.value?.trim() || 'admin';
  const site = document.getElementById('activationSite')?.value?.trim() || '';
  const connectorId = document.getElementById('activationConnector')?.value || '';

  if (!senha) { showToast('Defina a senha.', true); return; }
  if (senha !== senha2) { showToast('As duas senhas nao batem.', true); return; }
  if (_activationPendingTargets.some(d => d.needs_email) && !email) {
    showToast('Estes modelos exigem e-mail de recuperacao.', true); return;
  }

  const botao = document.getElementById('btnActivationConfirm');
  if (botao) { botao.disabled = true; botao.textContent = 'Ativando...'; }

  try {
    const res = await api('/api/deployments/activation/run', {
      method: 'POST',
      body: JSON.stringify({
        connector_id: connectorId,
        usuario, senha, email, site,
        targets: _activationPendingTargets.map(d => ({
          ip: d.ip, mac: d.mac, model: d.model, pwd_reset_way: d.pwd_reset_way,
        })),
      }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'falha na ativacao');

    activationRenderLog(data);
    closeActivationModal();
    showToast(`${data.activated} ativada(s), ${data.failed} com erro.`, data.failed > 0);
    // Revarre pra lista refletir o estado real das cameras, nao o que a gente
    // torce pra ter acontecido.
    await activationScan();
  } catch (err) {
    showToast(`Nao consegui ativar: ${err.message}`, true);
  } finally {
    if (botao) { botao.disabled = false; botao.innerHTML = '<i data-lucide="key-round"></i> Ativar'; }
    if (window.lucide) lucide.createIcons();
  }
}

function activationRenderLog(data) {
  const painel = document.getElementById('activationLogPanel');
  const caixa = document.getElementById('activationLog');
  if (!painel || !caixa) return;
  painel.style.display = '';
  caixa.innerHTML = (data?.results || []).map(r => {
    const detalhe = r.ok ? (r.warning || 'ativada e senha guardada no cofre do site') : (r.error || 'falhou');
    return `<div class="activation-log-item ${r.ok ? 'activation-log-ok' : 'activation-log-fail'}">
      <i data-lucide="${r.ok ? 'check-circle' : 'alert-circle'}"></i>
      <div><strong class="activation-mono">${esc(r.ip || '')}</strong> ${esc(r.model || '')}<br><span class="muted">${esc(detalhe)}</span></div>
    </div>`;
  }).join('');
  if (window.lucide) lucide.createIcons();
}

function activationCopyIps() {
  const lista = activationVisiveis().map(d => d.ip).filter(Boolean);
  if (!lista.length) { showToast('Nada para copiar.', true); return; }
  const texto = lista.join('\n');
  // clipboard.writeText exige contexto seguro (https); sem ele, o fallback do
  // textarea ainda funciona.
  const falhou = () => {
    const ta = document.createElement('textarea');
    ta.value = texto;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* sem clipboard */ }
    document.body.removeChild(ta);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(texto).catch(falhou);
  } else {
    falhou();
  }
  showToast(`${lista.length} IP(s) copiados.`);
}

function bindCameraActivation() {
  document.getElementById('btnActivationScan')?.addEventListener('click', activationScan);
  document.getElementById('btnActivationRescan')?.addEventListener('click', activationScan);
  document.getElementById('btnActivationCopyIps')?.addEventListener('click', activationCopyIps);
  document.getElementById('btnActivationRunBatch')?.addEventListener('click', () => {
    activationOpenModal(Array.from(_activationSelected));
  });
  document.getElementById('btnActivationSelectPending')?.addEventListener('click', () => {
    _activationSelected = new Set(_activationDevices.filter(d => d.needs_activation).map(activationKey));
    if (!_activationSelected.size) { showToast('Nenhuma camera de fabrica nesta lista.', true); return; }
    _activationFilter = 'fabrica';
    activationRender();
  });
  document.querySelectorAll('[data-activation-filter]').forEach(el => {
    el.addEventListener('click', () => {
      _activationFilter = el.dataset.activationFilter;
      activationRender();
    });
  });
  document.getElementById('activationCheckAll')?.addEventListener('change', (e) => {
    document.querySelectorAll('.activation-check').forEach(el => {
      if (el.disabled) return;
      el.checked = e.target.checked;
      if (e.target.checked) _activationSelected.add(el.dataset.mac);
      else _activationSelected.delete(el.dataset.mac);
    });
    activationUpdateBatchButton();
  });
  document.getElementById('btnActivationConfirm')?.addEventListener('click', activationConfirm);
  document.getElementById('btnActivationCancel')?.addEventListener('click', closeActivationModal);
  document.getElementById('btnActivationCloseModal')?.addEventListener('click', closeActivationModal);
}
