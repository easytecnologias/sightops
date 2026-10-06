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
// Ultima ativacao: o botao Reiniciar do resultado usa a mesma senha e o
// mesmo conector (so na memoria da pagina, nunca em storage).
let _activationUltima = null;          // {connectorId, senha, porIp: {ip: alvo}}
let _activationTimerRevarrer = null;
let _activationReiniciadas = new Set(); // IPs antigos que mandamos reiniciar

function activationKey(dev) {
  // Cai no IP quando nao ha MAC: camera Hikvision JA ativada nao entrega o MAC
  // sem senha, e com a chave vazia todas as linhas viravam a mesma -- marcar
  // uma marcava o site inteiro.
  return String(dev?.mac || dev?.ip || '').toLowerCase();
}

function activationEstado(dev) {
  // 403 sem desafio Digest tambem acontece em equipamento BLOQUEADO por
  // tentativa de senha errada -- e ai ativar vai falhar ate o bloqueio cair
  // (uns 30 min) ou alguem tirar e por a energia. Melhor avisar do que deixar
  // o tecnico tentando.
  if (dev.travada) {
    return { classe: 'badge-gray', texto: 'Travada',
             dica: 'A camera esta recusando tudo (403), entao nao da para saber se e nova ou nao. Costuma ser bloqueio por tentativa de senha errada: espere uns 30 min ou tire e ponha a energia dela.' };
  }
  if (dev.needs_activation) return { classe: 'badge-amber', texto: 'De fabrica' };
  // Hikvision nao conta pelo HTTP se esta ativada ou nao -- de fabrica ela
  // responde igual a uma ativada. Em vez de chutar "ja ativada" e esconder a
  // camera nova, a tela assume a duvida e deixa tentar.
  if (dev.estado_indefinido) return { classe: 'badge-gray', texto: 'Indefinido' };
  if (dev.init_status === 2) return { classe: 'badge-green', texto: 'Ja ativada' };
  return { classe: 'badge-gray', texto: 'Modelo antigo' };
}

// Quem pode ser oferecida para ativar: a de fabrica confirmada e a indefinida.
function podeAtivar(dev) {
  return !!(dev?.needs_activation || dev?.pode_tentar);
}

function activationRecuperacao(dev) {
  const vias = [];
  if (dev.needs_phone) vias.push('celular');
  if (dev.needs_email) vias.push('e-mail');
  return vias.join(' / ') || '-';
}

function activationVisiveis() {
  if (_activationFilter === 'fabrica') return _activationDevices.filter(d => podeAtivar(d));
  if (_activationFilter === 'ativas') return _activationDevices.filter(d => !podeAtivar(d));
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
  // IP unico (ex.: o 192.168.1.64 de fabrica da Hikvision). Antes ele nao
  // casava com a faixa, virava lista vazia e a varredura caia calada no
  // ARP/DHCP -- justamente o endereco que nao esta la.
  if (/^\d+\.\d+\.\d+\.\d+$/.test(t)) return [t];
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
      body: JSON.stringify({
        connector_id: connectorId, ips,
        // Qual pilha sondar. "todas" faz as duas; escolher uma corta o tempo
        // pela metade e nao encosta no equipamento da outra marca.
        marca: document.getElementById('activationMarca')?.value || 'todas',
      }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'falha na varredura');

    _activationDevices = Array.isArray(data.devices) ? data.devices : [];
    _activationSelected = new Set();
    // Quem abre a tela quer ver o que falta ativar; se nao ha nada de fabrica,
    // mostrar a lista vazia seria confuso, entao cai pra "todas".
    _activationFilter = _activationDevices.some(d => podeAtivar(d)) ? 'fabrica' : 'todas';
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

  const pendentes = _activationDevices.filter(d => podeAtivar(d)).length;
  const indefinidos = _activationDevices.filter(d => d.estado_indefinido).length;
  const total = _activationDevices.length;
  document.getElementById('activationCountAll').textContent = total;
  document.getElementById('activationCountPending').textContent = pendentes;
  document.getElementById('activationCountDone').textContent = total - pendentes;

  const resumo = document.getElementById('activationSummary');
  if (resumo) {
    resumo.textContent = total
      ? `${total} equipamentos responderam de ${data?.scanned ?? '?'} enderecos sondados -- ` +
        `${pendentes - indefinidos} de fabrica, ${total - pendentes} ja ativados` +
        (indefinidos ? `, ${indefinidos} Hikvision sem como saber (tente ativar: se ja tiver senha, ela recusa)` : '') +
        `. Origem: ${data?.source === 'manual' ? 'faixa informada' : 'ARP/DHCP do MikroTik'}.`
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
    const pode = podeAtivar(dev);
    const est = activationEstado(dev);
    return `<tr class="${pode ? '' : 'activation-row-done'}">
      <td><input type="checkbox" class="activation-check" data-mac="${esc(k)}" ${pode ? '' : 'disabled'} ${_activationSelected.has(k) ? 'checked' : ''}></td>
      <td><span class="badge ${est.classe}"${est.dica ? ` title="${esc(est.dica)}"` : ''}>${est.texto}</span></td>
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
  const alvos = _activationDevices.filter(d => macs.includes(activationKey(d)) && podeAtivar(d));
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

  // Perguntas de recuperacao e DHCP so existem no caminho Hikvision: a
  // Intelbras usa celular/e-mail, que ja tem campo proprio acima.
  const temHik = alvos.some(d => String(d.vendor || '').toLowerCase() === 'hikvision');
  document.getElementById('activationHikExtras')?.classList.toggle('hidden', !temHik);

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

  const temHik = _activationPendingTargets.some(
    d => String(d.vendor || '').toLowerCase() === 'hikvision');

  // Limite do proprio SDK da Hikvision (PASSWD_LEN = 16, com o terminador).
  if (temHik && senha.length > 15) {
    showToast('Para Hikvision a senha vai ate 15 caracteres.', true); return;
  }

  const perguntas = [];
  if (temHik) {
    for (const i of [1, 2, 3]) {
      const id = document.getElementById(`activationQ${i}`)?.value;
      const resposta = document.getElementById(`activationA${i}`)?.value?.trim() || '';
      if (!resposta) {
        showToast('A Hikvision exige as 3 respostas de recuperacao.', true); return;
      }
      perguntas.push({ id: Number(id), resposta });
    }
    if (new Set(perguntas.map(q => q.id)).size !== perguntas.length) {
      showToast('As 3 perguntas tem que ser diferentes.', true); return;
    }
  }
  const dhcp = temHik && !!document.getElementById('activationDhcp')?.checked;
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
        // `vendor` precisa ir junto: e ele que escolhe o caminho no servidor
        // (NetSDK da Intelbras x ISAPI da Hikvision). Sem ele a camera
        // Hikvision caia na regra do SDK e era recusada por nao ter MAC.
        perguntas, dhcp,
        targets: _activationPendingTargets.map(d => ({
          ip: d.ip, mac: d.mac, model: d.model, vendor: d.vendor,
          pwd_reset_way: d.pwd_reset_way,
        })),
      }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'falha na ativacao');

    _activationUltima = {
      connectorId, senha,
      porIp: Object.fromEntries(_activationPendingTargets.map(d => [d.ip, d])),
      // A ativacao Hikvision devolve o MAC que a varredura sem senha nao via;
      // e por ele que a camera e achada depois de trocar de IP.
      macPorIp: Object.fromEntries((data.results || []).filter(r => r.mac).map(r => [r.ip, r.mac])),
    };
    _activationReiniciadas = new Set(
      (data.results || []).filter(r => r.pos_ativacao?.reinicio?.ok).map(r => r.ip));
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

function activationEhHikvision(ip) {
  return String(_activationUltima?.porIp?.[ip]?.vendor || '').toLowerCase() === 'hikvision';
}

// Hikvision de fabrica so sai do 192.168.1.64 depois de reiniciar com DHCP
// ligado. Cada linha conta o que aconteceu com perguntas, DHCP e reinicio.
function activationPassos(r) {
  const pos = r.pos_ativacao || {};
  const passos = [];
  if (pos.perguntas) passos.push(pos.perguntas.ok ? 'perguntas de recuperacao gravadas'
                                                  : `perguntas: ${pos.perguntas.error || 'falharam'}`);
  if (pos.dhcp) passos.push(pos.dhcp.ok ? 'DHCP ligado' : `DHCP: ${pos.dhcp.error || 'falhou'}`);
  if (pos.reinicio) passos.push(pos.reinicio.ok ? 'reiniciando para pegar IP da faixa do site'
                                                : `reinicio: ${pos.reinicio.error || 'falhou'}`);
  return passos;
}

function activationPrecisaReiniciar(r) {
  return r.ok && activationEhHikvision(r.ip) && !r.pos_ativacao?.reinicio?.ok;
}

function activationRenderLog(data) {
  const painel = document.getElementById('activationLogPanel');
  const caixa = document.getElementById('activationLog');
  if (!painel || !caixa) return;
  painel.style.display = '';
  const resultados = data?.results || [];
  const pendentes = resultados.filter(activationPrecisaReiniciar);
  const linhas = resultados.map(r => {
    const base = r.ok ? (r.warning || 'ativada e senha guardada no cofre do site') : (r.error || 'falhou');
    const detalhe = [base, ...activationPassos(r)].join(' · ');
    const botao = activationPrecisaReiniciar(r)
      ? `<button type="button" class="secondary-action activation-reboot" data-ip="${esc(r.ip)}"><i data-lucide="rotate-ccw"></i> Reiniciar</button>`
      : '';
    return `<div class="activation-log-item ${r.ok ? 'activation-log-ok' : 'activation-log-fail'}" data-ip="${esc(r.ip || '')}">
      <i data-lucide="${r.ok ? 'check-circle' : 'alert-circle'}"></i>
      <div style="flex:1"><strong class="activation-mono">${esc(r.ip || '')}</strong> ${esc(r.model || '')}<br><span class="muted activation-log-detalhe">${esc(detalhe)}</span></div>
      ${botao}
    </div>`;
  });
  const topo = pendentes.length > 1
    ? `<div class="activation-log-item"><div style="flex:1" class="muted">${pendentes.length} cameras so assumem o IP novo depois de reiniciar.</div>
        <button type="button" class="primary-action" id="btnActivationRebootAll"><i data-lucide="rotate-ccw"></i> Reiniciar todas</button></div>`
    : '';
  caixa.innerHTML = topo + linhas.join('');
  caixa.querySelectorAll('.activation-reboot').forEach(b =>
    b.addEventListener('click', () => activationReiniciar([b.dataset.ip])));
  document.getElementById('btnActivationRebootAll')?.addEventListener('click', () =>
    activationReiniciar(pendentes.map(r => r.ip)));
  if (window.lucide) lucide.createIcons();
  // Reinicio automatico (DHCP marcado) ja disparou: so falta esperar e revarrer.
  if (resultados.some(r => r.pos_ativacao?.reinicio?.ok)) activationEsperarERevarrer();
}

function activationLinha(ip) {
  return [...document.querySelectorAll('#activationLog .activation-log-item')]
    .find(el => el.dataset.ip === ip);
}

async function activationReiniciar(ips) {
  const ult = _activationUltima;
  if (!ult || !ips.length) return;
  ips.forEach(ip => {
    const el = activationLinha(ip);
    el?.querySelector('.activation-reboot')?.setAttribute('disabled', 'disabled');
  });
  try {
    const res = await api('/api/deployments/activation/reboot', {
      method: 'POST',
      body: JSON.stringify({
        connector_id: ult.connectorId, senha: ult.senha,
        targets: ips.map(ip => ({ ip, vendor: ult.porIp[ip]?.vendor || '' })),
      }),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) throw new Error(data?.detail || 'falha ao reiniciar');
    (data.results || []).forEach(r => {
      const el = activationLinha(r.ip);
      if (!el) return;
      const det = el.querySelector('.activation-log-detalhe');
      if (det) det.textContent += r.ok ? ' · reiniciando para pegar IP da faixa do site' : ` · reinicio: ${r.error || 'falhou'}`;
      if (r.ok) { el.querySelector('.activation-reboot')?.remove(); _activationReiniciadas.add(r.ip); }
      else el.querySelector('.activation-reboot')?.removeAttribute('disabled');
    });
    document.getElementById('btnActivationRebootAll')?.closest('.activation-log-item')?.remove();
    showToast(`${data.rebooted} reiniciando, ${data.failed} com erro.`, data.failed > 0);
    if (data.rebooted) activationEsperarERevarrer();
  } catch (err) {
    showToast(`Nao consegui reiniciar: ${err.message}`, true);
    ips.forEach(ip => activationLinha(ip)?.querySelector('.activation-reboot')?.removeAttribute('disabled'));
  }
}

// A camera leva ~1 min para voltar. Contagem visivel e revarredura no fim,
// para a lista mostrar o IP novo sem o tecnico ficar adivinhando.
function activationEsperarERevarrer(segundos = 75) {
  const caixa = document.getElementById('activationLog');
  if (!caixa) return;
  clearInterval(_activationTimerRevarrer);
  let aviso = document.getElementById('activationRebootCountdown');
  if (!aviso) {
    aviso = document.createElement('div');
    aviso.id = 'activationRebootCountdown';
    aviso.className = 'activation-log-item';
    caixa.prepend(aviso);
  }
  let resta = segundos;
  const pinta = () => {
    aviso.innerHTML = `<i data-lucide="loader"></i><div class="muted">Reiniciando... revarro o site em <b>${resta}s</b>.</div>`;
    if (window.lucide) lucide.createIcons();
  };
  pinta();
  _activationTimerRevarrer = setInterval(async () => {
    resta -= 1;
    if (resta > 0) { pinta(); return; }
    clearInterval(_activationTimerRevarrer);
    aviso.innerHTML = '<i data-lucide="search"></i><div class="muted">Procurando o IP novo pelo MAC no DHCP/ARP do site...</div>';
    if (window.lucide) lucide.createIcons();
    await activationScan();
    activationLocalizar(aviso);
  }, 1000);
}

// O conector reporta ARP/DHCP de tempos em tempos: o IP novo pode demorar
// alguns minutos para aparecer. Pergunta a cada 15s, por ate 4 min.
async function activationLocalizar(aviso, tentativa = 0) {
  const ult = _activationUltima;
  if (!ult) return;
  const faltam = [..._activationReiniciadas].filter(ip => ult.macPorIp?.[ip]);
  if (!faltam.length) {
    aviso.innerHTML = '<i data-lucide="check-circle"></i><div class="muted">Pronto: lista revarrida depois do reinicio.</div>';
    if (window.lucide) lucide.createIcons();
    return;
  }
  try {
    const res = await api('/api/deployments/activation/locate', {
      method: 'POST',
      body: JSON.stringify({
        connector_id: ult.connectorId,
        targets: faltam.map(ip => ({ mac: ult.macPorIp[ip], old_ip: ip })),
      }),
    });
    const data = await res.json().catch(() => null);
    const achados = (res.ok && data?.found) || {};
    faltam.forEach(ip => {
      const novo = achados[String(ult.macPorIp[ip]).toLowerCase().replace(/-/g, ':')];
      if (!novo) return;
      _activationReiniciadas.delete(ip);
      const det = activationLinha(ip)?.querySelector('.activation-log-detalhe');
      if (det) det.innerHTML = `${esc(det.textContent)} · <b>assumiu o IP ${esc(novo.ip)}</b>`;
    });
  } catch (err) { /* tenta de novo abaixo */ }
  const sobram = [..._activationReiniciadas].filter(ip => ult.macPorIp?.[ip]);
  if (!sobram.length) {
    aviso.innerHTML = '<i data-lucide="check-circle"></i><div class="muted">Pronto: IP novo de cada camera na linha dela.</div>';
  } else if (tentativa >= 16) {
    aviso.innerHTML = `<i data-lucide="alert-circle"></i><div class="muted">${sobram.length} camera(s) ainda nao apareceram no DHCP/ARP do site. Confira no MikroTik pelo MAC.</div>`;
  } else {
    aviso.innerHTML = `<i data-lucide="search"></i><div class="muted">Procurando o IP novo de ${sobram.length} camera(s) pelo MAC... (o conector atualiza o DHCP/ARP a cada poucos minutos)</div>`;
    setTimeout(() => activationLocalizar(aviso, tentativa + 1), 15000);
  }
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
    // "Selecionar de fabrica" nunca marca as indefinidas: sao dezenas num site
    // ja implantado, e marcar todas tentaria ativar o parque inteiro.
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
