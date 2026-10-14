// ── Computadores (inventario Windows) ──
// Redesenho de 14/10/2026: resumo do parque, "precisa de atencao", saude por
// item, tabela enxuta e detalhe do computador. Tudo sai do que o agente envia
// (a cada 15 min, pela tarefa agendada).
function winText(v) { return String(v ?? '').trim(); }
function winKey(row) { return winText(row.ip) || winText(row.hostname) || winText(row.serial); }

// O agente reporta a cada 15 min; tres envios perdidos = sem contato. Mesmo
// limite do monitoramento (LIMITE_WINDOWS_MIN), para a tela e o Zabbix nao
// discordarem.
const WIN_LIMITE_MIN = 45;
function winData(v) {
  // PowerShell 5 manda data como "/Date(1791472034453)/".
  const raw = winText(v);
  if (!raw) return null;
  const ms = raw.match(/\/Date\((-?\d+)/);
  const d = ms ? new Date(Number(ms[1])) : new Date(raw);
  return Number.isNaN(d.getTime()) ? null : d;
}
function winIdadeMin(row) {
  const d = winData(row.last_seen || row.updated_at);
  return d ? (Date.now() - d.getTime()) / 60000 : Infinity;
}
function winIsOnline(row) {
  const s = winText(row.status).toLowerCase();
  return (s === 'online' || s === 'agent_reported') && winIdadeMin(row) <= WIN_LIMITE_MIN;
}
function winQuando(v) {
  const d = v instanceof Date ? v : winData(v);
  if (!d) return 'nunca';
  const min = Math.round((Date.now() - d.getTime()) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `ha ${min} min`;
  if (min < 48 * 60) return `ha ${Math.round(min / 60)} h`;
  return `ha ${Math.round(min / 1440)} dias`;
}
function winOsNome(row) {
  const os = row.os && typeof row.os === 'object' ? row.os : {};
  return winText(os.name || row.os_name).replace(/^Microsoft\s+/i, '');
}
function winOsLabel(row) {
  const os = row.os && typeof row.os === 'object' ? row.os : {};
  return [winOsNome(row), os.build].filter(Boolean).join(' / ') || '-';
}
function winSemSuporte(row) { return /windows (10|8|7)\b/i.test(winOsNome(row)); }
function winUserLabel(row) {
  return winText(row.logged_user || row.user || row.username).replace(/^.*\\/, '') || '-';
}
function winModelLabel(row) {
  return [row.manufacturer, row.model].map(winText).filter(Boolean).join(' ') || '-';
}
function winCpuLabel(row) {
  const cpu = row.cpu && typeof row.cpu === 'object' ? row.cpu : {};
  const name = winText(cpu.name || row.cpu_name || row.cpu);
  if (!name) return '-';
  return name.replace(/\s+/g, ' ').replace(/\d+th Gen |Intel\(R\)|Core\(TM\)|\(R\)|\(TM\)|CPU|Processor|@.*$/gi, '')
    .replace(/\s+/g, ' ').trim() || name;
}
function winRamGb(row) { return Number(row.ram_gb || row.total_ram_gb || 0); }
function winRamLabel(row) {
  const ram = winRamGb(row);
  return ram ? `${Math.round(ram)} GB` : '-';
}
function winDiscoLabel(row) {
  const kind = winText(row.disk_kind).toLowerCase();
  const tipo = kind === 'ssd' || kind === 'mixed' ? 'SSD' : kind === 'hdd' ? 'HD' : '';
  const gb = Number(row.disk_total_gb || 0);
  const tam = gb ? (gb >= 1000 ? `${(gb / 1024).toFixed(1).replace('.0', '')} TB` : `${Math.round(gb)} GB`) : '';
  return [tipo, tam].filter(Boolean).join(' ') || winText(row.disk_summary) || '-';
}
function winVolumeC(row) {
  return (row.volumes || []).find(v => v && /^c/i.test(winText(v.drive))) || null;
}
function winSeg(row) { return row.security && typeof row.security === 'object' ? row.security : {}; }
function winBitlockerC(row) {
  const v = (row.bitlocker || []).find(b => b && /^c/i.test(winText(b.mount_point)));
  if (!v) return null;
  return ['1', 'on', 'true'].includes(winText(v.protection_status).toLowerCase());
}
function winPhysical(row) {
  return row.physical && typeof row.physical === 'object' ? row.physical : {};
}
function winPhysicalLabel(row) {
  const p = winPhysical(row);
  const parts = [p.switch_name, p.switch_port, p.patch_panel, p.patch_port, p.outlet, p.rack, p.asset_tag].map(winText).filter(Boolean);
  return parts.length ? parts.join(' / ') : '-';
}

// Problemas de um computador, do mais grave para o menos. `grupo` alimenta os
// filtros; `peso` ordena a lista de atencao.
function winProblemas(row) {
  const p = [];
  const seg = winSeg(row);
  const nome = winText(row.hostname) || winText(row.ip);
  const onde = [row.sector || row.setor, row.site].map(winText).filter(Boolean).join(' · ');
  if (seg.defender_realtime === false || seg.defender_enabled === false) {
    p.push({ grupo: 'seguranca', peso: 0, tipo: 'Seguranca',
      titulo: `${nome} · Defender ${seg.defender_enabled === false ? 'desativado' : 'em tempo real desligado'}`, det: onde });
  }
  const c = winVolumeC(row);
  const livre = c ? Number(c.free_percent) : NaN;
  if (Number.isFinite(livre) && livre < 10) {
    p.push({ grupo: 'hardware', peso: 1, tipo: 'Disco',
      titulo: `${nome} · C: com ${livre.toFixed(0)}% livre${c.free_gb != null ? ` (${Math.round(c.free_gb)} GB)` : ''}`, det: onde });
  }
  if (!winIsOnline(row)) {
    p.push({ grupo: 'contato', peso: 2, tipo: 'Sem contato',
      titulo: `${nome} · ultimo contato ${winQuando(row.last_seen || row.updated_at)}`,
      det: row.agent_scheduled === false ? 'Agente sem tarefa agendada: rode o instalador (.exe) neste computador' : onde });
  }
  if (winBitlockerC(row) === false) {
    p.push({ grupo: 'seguranca', peso: 3, tipo: 'Seguranca', titulo: `${nome} · BitLocker desligado no C:`, det: onde });
  }
  if (seg.tpm_ready === false) {
    p.push({ grupo: 'seguranca', peso: 4, tipo: 'Seguranca', titulo: `${nome} · TPM nao esta pronto`, det: onde });
  }
  if (winSemSuporte(row)) {
    p.push({ grupo: 'windows', peso: 5, tipo: 'Windows', titulo: `${nome} · ${winOsNome(row)} sem atualizacao de seguranca`, det: onde });
  }
  const ram = winRamGb(row);
  if (row.has_ssd === false || (ram && ram < 7.5)) {
    const o = [row.has_ssd === false ? 'HD mecanico' : '', ram && ram < 7.5 ? `${Math.round(ram)} GB de RAM` : ''].filter(Boolean).join(' e ');
    p.push({ grupo: 'hardware', peso: 6, tipo: 'Hardware', titulo: `${nome} · ${o}`, det: onde });
  }
  return p;
}

const WIN_FILTROS = [
  ['todos', 'Todos'], ['online', 'Online'], ['contato', 'Sem contato'],
  ['seguranca', 'Seguranca'], ['windows', 'Windows sem suporte'], ['hardware', 'Hardware'],
];
let _winFiltro = 'todos';

function winNoFiltro(row, filtro) {
  if (filtro === 'todos') return true;
  if (filtro === 'online') return winIsOnline(row);
  return winProblemas(row).some(x => x.grupo === filtro);
}
function winMatchesFilter(row) {
  const site = document.getElementById('filterWinSite')?.value || '';
  const sector = document.getElementById('filterWinSector')?.value || '';
  const q = (document.getElementById('searchInvWindows')?.value || '').toLowerCase().trim();
  if (site && winText(row.site) !== site) return false;
  if (sector && winText(row.sector || row.setor) !== sector) return false;
  if (!winNoFiltro(row, _winFiltro)) return false;
  if (!q) return true;
  return [row.ip, row.mac, row.hostname, winUserLabel(row), winOsLabel(row), winModelLabel(row), winCpuLabel(row),
    row.anydesk_id, row.site, row.sector, row.serial, winPhysicalLabel(row)]
    .some(v => winText(v).toLowerCase().includes(q));
}
function populateWinFilters() {
  const fill = (id, values, label) => {
    const el = document.getElementById(id);
    if (!el) return;
    const cur = el.value;
    const unique = [...new Set(values.map(winText).filter(Boolean))].sort((a, b) => a.localeCompare(b));
    el.innerHTML = `<option value="">${label}</option>` + unique.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join('');
    if (unique.includes(cur)) el.value = cur;
  };
  fill('filterWinSite', _winRows.map(r => r.site), 'Todos os sites');
  fill('filterWinSector', _winRows.map(r => r.sector || r.setor), 'Todos os setores');
  const caixa = document.getElementById('winFiltros');
  if (caixa) {
    caixa.innerHTML = WIN_FILTROS.map(([id, rot]) => {
      const n = _winRows.filter(r => winNoFiltro(r, id)).length;
      return `<button type="button" data-win-filtro="${id}" aria-pressed="${id === _winFiltro}">${esc(rot)} · ${n}</button>`;
    }).join('');
    caixa.querySelectorAll('[data-win-filtro]').forEach(b => b.addEventListener('click', () => {
      _winFiltro = b.dataset.winFiltro;
      populateWinFilters();
      applyWindowsFilters();
    }));
  }
}

function winPintarResumo() {
  const el = document.getElementById('winResumo');
  const guia = document.getElementById('winPrimeiroUso');
  const tabela = document.getElementById('winTabela');
  const vazio = !_winRows.length;
  if (guia) { guia.hidden = !vazio; if (vazio) guia.innerHTML = winPrimeiroUsoHtml(); }
  if (tabela) tabela.hidden = vazio;
  if (!el) return;
  if (vazio) { el.innerHTML = ''; winLigarPrimeiroUso(guia); return; }

  const rows = _winRows;
  const total = rows.length;
  const on = rows.filter(winIsOnline).length;
  const conta = g => rows.filter(r => winProblemas(r).some(x => x.grupo === g)).length;
  const sites = new Set(rows.map(r => winText(r.site)).filter(Boolean));
  const longe = rows.filter(r => !winIsOnline(r) && winIdadeMin(r) > 7 * 1440).length;
  const semSup = conta('windows');
  const kpis = [
    ['Computadores', total, `${sites.size || 'nenhum'} site${sites.size === 1 ? '' : 's'}`, ''],
    ['Online agora', on, `agente respondeu ha menos de ${WIN_LIMITE_MIN} min`, 'ok'],
    ['Sem contato', total - on, longe ? `${longe} ha mais de 7 dias` : 'desligados ou sem agente', total - on ? 'erro' : ''],
    ['Seguranca em risco', conta('seguranca'), 'Defender, BitLocker ou TPM', conta('seguranca') ? 'erro' : ''],
    ['Windows sem suporte', semSup, 'Windows 10 sem atualizacao desde out/2025', semSup ? 'aviso' : ''],
    ['Hardware fraco', conta('hardware'), 'disco cheio, HD mecanico ou pouca RAM', conta('hardware') ? 'aviso' : ''],
  ];

  const problemas = rows.flatMap(r => winProblemas(r).map(x => ({ ...x, key: winKey(r) })))
    .sort((a, b) => a.peso - b.peso);
  const pct = (n) => (total ? Math.round(n / total * 100) : 0);
  const sim = fn => rows.filter(fn).length;
  const saude = [
    ['Agente respondendo', on],
    ['Defender ativo', sim(r => winSeg(r).defender_realtime === true)],
    ['BitLocker no C:', sim(r => winBitlockerC(r) === true)],
    ['Windows com suporte', sim(r => winOsNome(r) && !winSemSuporte(r))],
    ['Com SSD', sim(r => r.has_ssd === true)],
    ['Memoria >= 8 GB', sim(r => winRamGb(r) >= 7.5)],
    ['Tarefa do agente agendada', sim(r => r.agent_scheduled === true)],
  ];
  const corBarra = p => (p >= 90 ? 'ok' : p >= 70 ? 'aviso' : 'erro');
  const ultimo = rows.reduce((m, r) => { const d = winData(r.last_seen); return d && (!m || d > m) ? d : m; }, null);
  setText('winSubtitulo', `${total} computador${total === 1 ? '' : 'es'}${sites.size ? ` em ${sites.size} site${sites.size === 1 ? '' : 's'}` : ''} · ultimo relatorio ${winQuando(ultimo)}`);

  el.innerHTML = `
    <section class="win-kpis" aria-label="Resumo dos computadores">
      ${kpis.map(([rot, val, sub, cl]) => `<div class="win-kpi"><span>${esc(rot)}</span><b class="${cl}">${esc(val)}</b><small>${esc(sub)}</small></div>`).join('')}
    </section>
    <div class="win-duas">
      <section class="panel win-atencao">
        <div class="win-cab"><h2>Precisa de atencao</h2><span>${problemas.length ? 'mais grave primeiro' : ''}</span></div>
        ${problemas.length ? problemas.slice(0, 7).map(x => `<div class="win-item">
            <span class="win-tag ${x.grupo}">${esc(x.tipo)}</span>
            <div class="win-item-txt"><b>${esc(x.titulo)}</b><span>${esc(x.det || '')}</span></div>
            <button class="secondary-action" type="button" data-win-abrir="${esc(x.key)}">Abrir</button>
          </div>`).join('')
          : '<p class="win-vazio">Nenhum problema nos computadores com agente.</p>'}
        ${problemas.length > 7 ? `<p class="win-vazio">Mais ${problemas.length - 7} na tabela abaixo (filtros).</p>` : ''}
      </section>
      <section class="panel win-saude">
        <div class="win-cab"><h2>Saude do parque</h2><span>computadores que cumprem cada item</span></div>
        ${saude.map(([rot, n]) => { const p = pct(n); return `<div class="win-barra-item">
          <div><span>${esc(rot)}</span><span class="mono">${n} / ${total}</span></div>
          <div class="win-trilho"><i class="${corBarra(p)}" style="width:${p}%"></i></div></div>`; }).join('')}
      </section>
    </div>`;
  el.querySelectorAll('[data-win-abrir]').forEach(b => b.addEventListener('click', () => {
    const row = _winRows.find(r => winKey(r) === b.dataset.winAbrir);
    if (row) openWinPanel(row);
  }));
}

function winPrimeiroUsoHtml() {
  const cliente = (typeof _currentUser !== 'undefined' && _currentUser)
    ? (_currentUser.effective_tenant_name || _currentUser.tenant_name || '') : '';
  return `<section class="panel win-guia">
      <div class="win-passo">
        <span class="win-num">1</span>
        <h2>Baixe o instalador</h2>
        <p>Um programa so, ja com o endereco e a chave${cliente ? ` da <b>${esc(cliente)}</b>` : ''}. Leve num pen drive ou abra direto no computador.</p>
        <button class="primary-action" type="button" data-win-baixar="1"><i data-lucide="download"></i> Baixar instalador (.exe)</button>
      </div>
      <div class="win-passo">
        <span class="win-num">2</span>
        <h2>Abra no computador</h2>
        <p>O Windows pede permissao de administrador. Informe o site e o setor e clique em <b>Instalar</b>. Se aparecer "O Windows protegeu o computador", clique em <i>Mais informacoes</i> e <i>Executar assim mesmo</i>.</p>
      </div>
      <div class="win-passo">
        <span class="win-num">3</span>
        <h2>Pronto: aparece aqui e no Zabbix</h2>
        <p>O computador entra na lista na hora, com hardware, seguranca e AnyDesk, e se atualiza sozinho a cada 15 min.</p>
        <div class="win-esperando"><i></i>Esperando o primeiro computador...</div>
      </div>
    </section>
    <section class="win-guia-info">
      <div class="panel"><h3>O que o agente envia</h3><p>Hardware, discos e espaco, Windows e atualizacoes, BitLocker, Defender, TPM, usuario logado e ID do AnyDesk.</p></div>
      <div class="panel"><h3>O que ele nao faz</h3><p>Nao le arquivos, nao grava tela e nao abre porta no computador. So envia o inventario para o SightOps.</p></div>
      <div class="panel"><h3>Muitos computadores?</h3><p>Para GPO ou script remoto, use o <button type="button" class="win-link" data-win-script="1">agente em PowerShell</button>, sem janela:
        <code class="win-cmd-txt">-Silencioso -Site "Sede" -Setor "Financeiro"</code></p></div>
    </section>`;
}
function winLigarPrimeiroUso(guia) {
  if (!guia) return;
  guia.querySelector('[data-win-baixar]')?.addEventListener('click', winBaixarAgente);
  guia.querySelector('[data-win-script]')?.addEventListener('click', winBaixarScript);
  lucide.createIcons();
}
// O script embute o endereco para onde o agente reporta. A v3 fica sob
// /v3-api/: sem mandar a base, o servidor gravava a raiz do dominio, que e a
// API de producao v2 -- o computador nunca apareceria aqui.
function winBaseAgente() {
  return encodeURIComponent(typeof API_BASE !== 'undefined' ? API_BASE : window.location.origin);
}
function winBaixarAgente() {
  return downloadWithAuth(`/api/windows/agent-exe?base=${winBaseAgente()}`, 'SightOps-Agente.exe');
}
// Instalacao em massa (GPO, script remoto): o mesmo agente, sem janela.
function winBaixarScript() {
  return downloadWithAuth(`/api/windows/agent-script?base=${winBaseAgente()}`, 'sightops-agente-windows.ps1');
}
async function winAtualizar() {
  const btn = document.getElementById('btnWinAtualizar');
  if (btn) btn.disabled = true;
  try {
    await loadInvWindows();
    showToast(`Computadores atualizados: ${_winRows.length}.`);
  } catch (err) {
    showToast('Nao consegui atualizar a lista.', true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function updateWinSummary() { winPintarResumo(); }
function updateWinSelectionUi() {
  setText('winSelectedCount', `${_winSelected.size} selecionado${_winSelected.size === 1 ? '' : 's'}`);
  const visibleKeys = _winFilteredRows.map(winKey).filter(Boolean);
  const selectedVisible = visibleKeys.filter(k => _winSelected.has(k)).length;
  const all = document.getElementById('chkWinAll');
  if (all) {
    all.checked = visibleKeys.length > 0 && selectedVisible === visibleKeys.length;
    all.indeterminate = selectedVisible > 0 && selectedVisible < visibleKeys.length;
  }
}
function winSelo(rot, bom) {
  if (bom == null) return `<span class="win-selo nd" title="${esc(rot)}: sem dado (agente sem Administrador?)">${esc(rot)}</span>`;
  return `<span class="win-selo ${bom ? 'ok' : 'ruim'}" title="${esc(rot)}: ${bom ? 'ok' : 'com problema'}">${esc(rot)}</span>`;
}
function renderWinRows(rows) {
  const tbody = document.getElementById('invWindowsTable');
  if (!tbody) return;
  if (!rows.length) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="9">Nenhum computador neste filtro.</td></tr>';
    setText('invWindowsFooter', `0 de ${_winRows.length}`);
    updateWinSelectionUi();
    return;
  }
  tbody.innerHTML = rows.map(row => {
    const key = winKey(row);
    const on = winIsOnline(row);
    const seg = winSeg(row);
    const c = winVolumeC(row);
    const livre = c ? Number(c.free_percent) : NaN;
    const usado = Number.isFinite(livre) ? Math.max(0, Math.min(100, 100 - livre)) : 0;
    const corC = !Number.isFinite(livre) ? '' : livre < 10 ? 'erro' : livre < 20 ? 'aviso' : 'ok';
    const anydesk = winText(row.anydesk_id);
    return `<tr class="win-row" data-key="${esc(key)}">
        <td><input type="checkbox" class="chk-win" value="${esc(key)}" ${_winSelected.has(key) ? 'checked' : ''} aria-label="Selecionar ${esc(row.hostname || key)}"></td>
        <td><div class="win-pc"><i class="win-pt ${on ? 'ok' : ''}" title="${on ? 'online' : 'sem contato'}"></i>
          <div><b>${esc(row.hostname || '-')}</b><small>${esc(winUserLabel(row))} · <span class="mono">${esc(row.ip || '-')}</span></small></div></div></td>
        <td>${esc(row.site || '-')}<small>${esc(row.sector || row.setor || '')}</small></td>
        <td><span class="win-os ${winSemSuporte(row) ? 'velho' : ''}">${esc(winOsNome(row).replace(/^Windows\s*/i, '') || '-')}</span></td>
        <td class="win-hw">${esc(winCpuLabel(row))}<small>${esc(winRamLabel(row))} · ${esc(winDiscoLabel(row))}</small></td>
        <td>${Number.isFinite(livre) ? `<div class="win-c"><div class="win-trilho"><i class="${corC}" style="width:${usado}%"></i></div><span class="mono">${livre.toFixed(0)}%</span></div>` : '<span class="text-muted">-</span>'}</td>
        <td><div class="win-selos">${winSelo('BitLocker', winBitlockerC(row))}${winSelo('Defender', seg.defender_realtime == null ? null : seg.defender_realtime === true && seg.defender_enabled !== false)}${winSelo('TPM', seg.tpm_ready)}</div></td>
        <td class="text-muted">${esc(winQuando(row.last_seen || row.updated_at))}</td>
        <td class="win-acoes">
          ${anydesk ? `<a class="win-anydesk" href="anydesk:${encodeURIComponent(anydesk)}" title="Conectar AnyDesk ${esc(anydesk)}">AnyDesk</a>` : ''}
          <button class="secondary-action" type="button" data-win-detalhe="${esc(key)}">Abrir</button>
        </td>
      </tr>`;
  }).join('');
  setText('invWindowsFooter', rows.length === _winRows.length
    ? `${rows.length} computador${rows.length === 1 ? '' : 'es'}`
    : `Mostrando ${rows.length} de ${_winRows.length}`);
  tbody.querySelectorAll('.chk-win').forEach(chk => {
    chk.addEventListener('click', e => e.stopPropagation());
    chk.addEventListener('change', () => {
      if (chk.checked) _winSelected.add(chk.value); else _winSelected.delete(chk.value);
      updateWinSelectionUi();
    });
  });
  tbody.querySelectorAll('.win-anydesk').forEach(a => a.addEventListener('click', e => e.stopPropagation()));
  tbody.querySelectorAll('.win-row').forEach(tr => tr.addEventListener('click', () => {
    const row = _winRows.find(r => winKey(r) === tr.dataset.key);
    if (row) openWinPanel(row);
  }));
  updateWinSelectionUi();
}
function applyWindowsFilters() {
  _winFilteredRows = _winRows.filter(winMatchesFilter);
  renderWinRows(_winFilteredRows);
}
async function loadInvWindows() {
  const data = await apiJson('/api/windows/inventory');
  _winRows = data?.inventory || data?.hosts || (Array.isArray(data) ? data : []);
  // Mais grave primeiro, depois por nome.
  const peso = r => Math.min(99, ...winProblemas(r).map(x => x.peso));
  _winRows.sort((a, b) => (peso(a) - peso(b)) || winText(a.hostname).localeCompare(winText(b.hostname), 'pt-BR', { numeric: true }));
  _winSelected = new Set([..._winSelected].filter(key => _winRows.some(r => winKey(r) === key)));
  updateWinSummary();
  populateWinFilters();
  applyWindowsFilters();
}
function clearWinFilters() {
  ['searchInvWindows', 'filterWinSite', 'filterWinSector'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  _winFiltro = 'todos';
  _winSelected.clear();
  populateWinFilters();
  applyWindowsFilters();
}
// ── Detalhe do computador ──
// Substitui o painel lateral de 2026-09 (lista de campos soltos): agora em
// blocos -- seguranca, discos, hardware, sistema, rede/caminho fisico e o
// historico que o servidor monta a cada relatorio do agente (`eventos`).
function winLinha(rot, val) {
  return `<dt>${esc(rot)}</dt><dd>${esc(winText(val) || '-')}</dd>`;
}
function winCheck(rot, bom, txt) {
  const cl = bom == null ? 'nd' : bom ? 'ok' : 'ruim';
  const ico = bom == null ? '?' : bom ? '✓' : '!';
  return `<div class="win-check"><span class="win-check-ico ${cl}" aria-hidden="true">${ico}</span><span>${esc(rot)}</span><b class="${cl}">${esc(txt)}</b></div>`;
}
function openWinPanel(row) {
  _winActive = row;
  const tampa = document.getElementById('winDetalhe') || (() => {
    const el = document.createElement('div');
    el.id = 'winDetalhe';
    document.body.appendChild(el);
    return el;
  })();
  const on = winIsOnline(row);
  const seg = winSeg(row);
  const os = row.os && typeof row.os === 'object' ? row.os : {};
  const cpu = row.cpu && typeof row.cpu === 'object' ? row.cpu : {};
  const mb = row.motherboard && typeof row.motherboard === 'object' ? row.motherboard : {};
  const zbx = row.zabbix_agent && typeof row.zabbix_agent === 'object' ? row.zabbix_agent : {};
  const p = winPhysical(row);
  const anydesk = winText(row.anydesk_id);
  const flags = Array.isArray(row.health_flags) ? row.health_flags : [];
  const hot = (row.hotfixes || []).find(h => h && h.id);
  const boot = winData(os.last_boot);
  const bl = winBitlockerC(row);
  const rt = seg.defender_realtime;
  const gpus = (row.gpus || []).map(g => winText(g && g.name)).filter(Boolean).join(', ');
  const modulos = (row.memory_modules || []).filter(m => m && m.capacity_gb);
  const ddr = modulos.map(m => winText(m.ddr)).find(Boolean) || '';
  const velocidade = modulos.map(m => m.configured_speed_mhz || m.speed_mhz).find(Boolean) || '';
  const net = (row.network || []).find(n => n && n.mac) || {};
  const gw = Array.isArray(net.gateway) ? net.gateway.filter(Boolean).join(', ') : winText(net.gateway);
  const eventos = (Array.isArray(row.eventos) ? row.eventos : []).slice().reverse();
  const caminho = [
    ['Switch', p.switch_name, p.switch_port ? `porta ${p.switch_port}` : ''],
    ['Patch panel', p.patch_panel, p.patch_port ? `porta ${p.patch_port}` : ''],
    ['Tomada', p.outlet, ''],
    ['Rack', p.rack, ''],
  ].filter(x => winText(x[1]));

  tampa.innerHTML = `<div class="win-det-tampa" role="dialog" aria-modal="true" aria-label="Computador ${esc(row.hostname || row.ip)}">
    <div class="win-det">
      <header class="win-det-cab">
        <div class="win-det-id">
          <div class="win-det-tit"><h2>${esc(row.hostname || row.ip || 'Computador')}</h2>
            <span class="win-estado ${on ? 'ok' : ''}"><i></i>${on ? 'Online' : 'Sem contato'} · ${esc(winQuando(row.last_seen || row.updated_at))}</span></div>
          <p>${esc([winUserLabel(row), [row.site, row.sector || row.setor].map(winText).filter(Boolean).join(' › '), winModelLabel(row), row.serial ? `serial ${row.serial}` : ''].filter(x => x && x !== '-').join(' · '))}</p>
        </div>
        <div class="win-det-acoes">
          ${anydesk ? `<a class="primary-action" href="anydesk:${encodeURIComponent(anydesk)}">Conectar AnyDesk · ${esc(anydesk)}</a>` : ''}
          <button class="secondary-action" type="button" data-win-acao="ping">Ping</button>
          <button class="secondary-action" type="button" data-win-acao="edit">Caminho fisico</button>
          <button class="secondary-action" type="button" data-win-fechar="1" aria-label="Fechar">Fechar</button>
        </div>
      </header>
      ${flags.length ? `<div class="win-det-alerta" role="alert"><b>${flags.length} alerta${flags.length === 1 ? '' : 's'}:</b> ${esc(flags.join(' · '))}</div>` : ''}
      ${row.agent_scheduled === false ? '<div class="win-det-aviso">O agente deste computador nao tem a tarefa agendada: ele so reporta quando alguem roda o script. Rode o instalador (.exe) neste computador para ele se atualizar sozinho.</div>' : ''}
      <div class="win-det-grade">
        <section class="win-bloco"><h3>Seguranca</h3>
          ${winCheck('Defender em tempo real', rt == null ? null : rt === true, rt == null ? 'sem dado' : rt ? 'Ligado' : 'Desligado')}
          ${winCheck('BitLocker no C:', bl, bl == null ? 'sem dado' : bl ? 'Protegido' : 'Desligado')}
          ${winCheck('TPM', seg.tpm_ready == null ? null : seg.tpm_ready === true, seg.tpm_ready == null ? 'sem dado' : seg.tpm_ready ? 'Pronto' : (seg.tpm_present ? 'Presente, nao pronto' : 'Ausente'))}
          ${winCheck('Secure Boot', seg.secure_boot == null ? null : seg.secure_boot === true, seg.secure_boot == null ? 'sem dado' : seg.secure_boot ? 'Ativo' : 'Desligado')}
          ${winCheck('Windows com suporte', winOsNome(row) ? !winSemSuporte(row) : null, winSemSuporte(row) ? 'Sem suporte' : (winOsNome(row) ? 'Sim' : 'sem dado'))}
          ${seg.tpm_ready == null && rt != null ? '<p class="win-det-nota">"Sem dado" em TPM/BitLocker: o agente rodou sem Administrador.</p>' : ''}
        </section>
        <section class="win-bloco"><h3>Discos</h3>
          ${(row.volumes || []).filter(v => v && v.drive).map(v => {
            const livre = Number(v.free_percent);
            const usado = Number.isFinite(livre) ? 100 - livre : 0;
            const cor = !Number.isFinite(livre) ? '' : livre < 10 ? 'erro' : livre < 20 ? 'aviso' : 'ok';
            return `<div class="win-vol"><div><b>${esc(v.drive)} ${esc(v.label || '')}</b><span>${v.free_gb != null ? `${Math.round(v.free_gb)} GB livres de ${Math.round(v.size_gb || 0)} GB` : ''}${Number.isFinite(livre) ? ` · ${livre.toFixed(0)}% livre` : ''}</span></div>
              <div class="win-trilho grosso"><i class="${cor}" style="width:${usado}%"></i></div></div>`;
          }).join('') || '<p class="win-vazio">Sem volumes informados.</p>'}
          <p class="win-det-nota">Fisico: ${esc((row.disks || []).filter(d => d && d.model).map(d => `${d.model}${d.size_gb ? ` (${Math.round(d.size_gb)} GB)` : ''}`).join(' · ') || winDiscoLabel(row))}</p>
        </section>
        <section class="win-bloco"><h3>Hardware</h3><dl>
          ${winLinha('Processador', [winText(cpu.name || row.cpu), cpu.cores ? `${cpu.cores} nucleos / ${cpu.threads || '?'} threads` : ''].filter(Boolean).join(' · '))}
          ${winLinha('Memoria', [winRamLabel(row), ddr, velocidade ? `${velocidade} MHz` : '', modulos.length ? `${modulos.length} pente${modulos.length === 1 ? '' : 's'}` : ''].filter(x => x && x !== '-').join(' · '))}
          ${winLinha('Placa-mae', [mb.manufacturer, mb.model].map(winText).filter(Boolean).join(' '))}
          ${winLinha('Video', gpus)}
          ${winLinha('Bateria', (row.batteries || []).length ? (row.batteries || []).map(b => `${winText(b.name)} ${b.estimated_charge != null ? b.estimated_charge + '%' : ''}`).join(', ') : 'Sem bateria (desktop)')}
        </dl></section>
        <section class="win-bloco"><h3>Sistema</h3><dl>
          ${winLinha('Windows', [winOsNome(row), os.build ? `build ${os.build}` : '', os.arch].filter(Boolean).join(' · '))}
          ${winLinha('Ultima atualizacao', hot ? [hot.id, hot.installed_on].map(winText).filter(Boolean).join(' · ') : '')}
          ${winLinha('Ligado desde', boot ? `${winQuando(boot)} (${boot.toLocaleString('pt-BR')})` : '')}
          ${winLinha('Dominio', row.domain)}
          ${winLinha('Agente SightOps', [row.agent_version ? `versao ${row.agent_version}` : 'versao antiga', row.agent_scheduled ? 'tarefa agendada' : (row.agent_scheduled === false ? 'sem tarefa agendada' : '')].filter(Boolean).join(' · '))}
          ${winLinha('Zabbix Agent', zbx.installed ? [zbx.service_status, zbx.version].map(winText).filter(Boolean).join(' · ') : 'nao instalado')}
        </dl></section>
        <section class="win-bloco"><h3>Rede e caminho fisico</h3><dl>
          ${winLinha('IP', row.ip)}
          ${winLinha('MAC', row.mac)}
          ${winLinha('Gateway', gw)}
          ${winLinha('Placa', net.description)}
        </dl>
          ${caminho.length ? `<div class="win-caminho">${[['Computador', row.hostname, ''], ...caminho].map(([t, n, d], i) => `${i ? '<span aria-hidden="true">→</span>' : ''}<div><small>${esc(t)}</small><b>${esc(n)}</b>${d ? `<small>${esc(d)}</small>` : ''}</div>`).join('')}</div>`
            : '<p class="win-det-nota">Caminho fisico ainda nao informado: use "Caminho fisico" para registrar switch, porta, patch panel e tomada.</p>'}
        </section>
        <section class="win-bloco"><h3>O que mudou</h3>
          ${eventos.length ? eventos.slice(0, 12).map(e => `<div class="win-ev"><span>${esc(winQuando(e.em))}</span><span>${esc(e.txt)}</span></div>`).join('')
            : '<p class="win-vazio">Sem historico ainda: o agente versao 2.0 registra as mudancas a cada relatorio.</p>'}
        </section>
      </div>
    </div></div>`;
  const fechar = () => closeWinPanel();
  tampa.querySelector('.win-det-tampa').addEventListener('click', ev => { if (ev.target === ev.currentTarget) fechar(); });
  tampa.querySelectorAll('[data-win-fechar]').forEach(b => b.addEventListener('click', fechar));
  tampa.querySelectorAll('[data-win-acao]').forEach(b => b.addEventListener('click', () => winPanelAction(b.dataset.winAcao)));
  tampa.querySelector('[data-win-fechar]')?.focus();
}
function closeWinPanel() {
  _winActive = null;
  const tampa = document.getElementById('winDetalhe');
  if (tampa) tampa.innerHTML = '';
}
document.addEventListener('keydown', ev => {
  if (ev.key === 'Escape' && document.getElementById('winDetalhe')?.innerHTML) closeWinPanel();
});
function winPanelAction(action) {
  if (!_winActive && !['agent', 'pdf', 'refresh'].includes(action)) return;
  if (action === 'ping') return openPingTerminal(_winActive.ip);
  if (action === 'anydesk') {
    const id = winText(_winActive.anydesk_id);
    if (!id) return showToast('Este computador nao tem AnyDesk informado.', true);
    window.open(`anydesk:${encodeURIComponent(id)}`, '_blank');
    return;
  }
  if (action === 'edit') {
    const key = winKey(_winActive);
    _winSelected = new Set([key]);
    closeWinPanel();
    applyWindowsFilters();
    openWinPhysicalModal();
    return;
  }
  if (action === 'agent') return winBaixarAgente();
  if (action === 'pdf') return downloadWithAuth('/api/windows/report.pdf', 'windows-inventory.pdf');
  if (action === 'refresh') return loadInvWindows();
}
function selectedWinRows() {
  return _winRows.filter(r => _winSelected.has(winKey(r)));
}
function openWinPhysicalModal() {
  const rows = selectedWinRows();
  if (!rows.length) { showToast('Selecione um computador para editar.', true); return; }
  const row = rows[0];
  _winEditingKey = winKey(row);
  const p = winPhysical(row);
  setText('winPhysicalTitle', `Editar - ${row.hostname || row.ip || 'computador'}`);
  const map = {
    SwitchName: p.switch_name,
    SwitchPort: p.switch_port,
    PatchPanel: p.patch_panel,
    PatchPort: p.patch_port,
    Outlet: p.outlet,
    Rack: p.rack,
    CableId: p.cable_id,
    AssetTag: p.asset_tag,
    Notes: p.notes,
  };
  Object.entries(map).forEach(([k,v]) => { const el = document.getElementById(`winPhysical${k}`); if (el) el.value = winText(v); });
  document.getElementById('winPhysicalErro').hidden = true;
  document.getElementById('modalWinPhysical')?.classList.remove('hidden');
  lucide.createIcons();
}
function closeWinPhysicalModal() { document.getElementById('modalWinPhysical')?.classList.add('hidden'); }
async function saveWinPhysical() {
  if (!_winEditingKey) return;
  const erro = document.getElementById('winPhysicalErro');
  const btn = document.getElementById('saveWinPhysical');
  const physical = {
    switch_name: document.getElementById('winPhysicalSwitchName').value.trim(),
    switch_port: document.getElementById('winPhysicalSwitchPort').value.trim(),
    patch_panel: document.getElementById('winPhysicalPatchPanel').value.trim(),
    patch_port: document.getElementById('winPhysicalPatchPort').value.trim(),
    outlet: document.getElementById('winPhysicalOutlet').value.trim(),
    rack: document.getElementById('winPhysicalRack').value.trim(),
    cable_id: document.getElementById('winPhysicalCableId').value.trim(),
    asset_tag: document.getElementById('winPhysicalAssetTag').value.trim(),
    notes: document.getElementById('winPhysicalNotes').value.trim(),
  };
  btn.disabled = true;
  try {
    const res = await api('/api/windows/inventory/manual', { method: 'PATCH', body: JSON.stringify({ key: _winEditingKey, physical }) });
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok || data?.ok === false) throw new Error(data?.detail || data?.error || 'Falha ao salvar.');
    showToast('Caminho fisico salvo.');
    closeWinPhysicalModal();
    await loadInvWindows();
  } catch (err) {
    erro.textContent = err.message || 'Falha ao salvar.';
    erro.hidden = false;
    showToast(erro.textContent, true);
  } finally {
    btn.disabled = false;
  }
}
async function deleteSelectedWindows() {
  const keys = [..._winSelected];
  if (!keys.length) { showToast('Selecione ao menos um computador.', true); return; }
  if (!await showConfirm({ title: 'Remover computadores', msg: `Remover ${keys.length} computador(es) do inventario Windows?`, label: 'Remover' })) return;
  const res = await api('/api/windows/inventory/delete', { method: 'POST', body: JSON.stringify({ keys }) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) { showToast(data?.detail || data?.error || 'Falha ao remover.', true); return; }
  _winSelected.clear();
  showToast(`${data.removed || keys.length} computador(es) removido(s).`);
  await loadInvWindows();
}
async function clearWindowsInventory() {
  if (!await showConfirm({ title: 'Apagar inventario Windows', msg: 'Apagar todos os computadores Windows salvos?', label: 'Apagar tudo' })) return;
  const res = await api('/api/windows/clear', { method: 'POST', body: '{}' });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok || data?.ok === false) { showToast(data?.detail || data?.error || 'Falha ao limpar.', true); return; }
  _winRows = [];
  _winSelected.clear();
  updateWinSummary();
  populateWinFilters();
  applyWindowsFilters();
  showToast('Inventario Windows limpo.');
}
// Snapshots 
let _snapCamAll = [];

async function loadSnapCam() {
  // /api/cameras sozinho so devolve o modo OLT -- busca os 3 modos e
  // mescla por chave, senao cameras cadastradas so em Basico/Switch nunca
  // aparecem aqui (mesmo tendo snapshot).
  const [basico, olt, sw] = await Promise.all([
    apiJson('/api/cameras?mode=basico').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=olt').catch(() => ({ cameras: [] })),
    apiJson('/api/cameras?mode=switch').catch(() => ({ cameras: [] })),
  ]);
  const merged = new Map();
  [basico, olt, sw].forEach(data => {
    (data?.cameras || []).forEach(c => {
      const key = c.inventory_key || c.ip;
      if (key && !merged.has(key)) merged.set(key, c);
    });
  });
  _snapCamAll = [...merged.values()]
    .sort((a, b) => {
      const toInt = ip => (ip||'0.0.0.0').split('.').reduce((a,b) => (a<<8)|(parseInt(b)||0), 0) >>> 0;
      return toInt(a.ip) - toInt(b.ip);
    });

  // Popula filtro de sites
  const sites = [...new Set(_snapCamAll.map(c => c.local).filter(Boolean))].sort();
  const selSite = document.getElementById('filterSnapCamSite');
  if (selSite) {
    const cur = selSite.value;
    selSite.innerHTML = '<option value="">Todos os sites</option>' +
      sites.map(s => `<option${s===cur?' selected':''}>${esc(s)}</option>`).join('');
  }

  applySnapCamFilters();
}

function applySnapCamFilters() {
  const q      = (document.getElementById('searchSnapCam')?.value || '').toLowerCase();
  const status = document.getElementById('filterSnapCamStatus')?.value || '';
  const site   = document.getElementById('filterSnapCamSite')?.value   || '';

  const filtered = _snapCamAll.filter(c => {
    const temFoto = !!(c.snapshot_url);
    if (status === 'com' && !temFoto) return false;
    if (status === 'sem' && temFoto)  return false;
    if (site && c.local !== site)     return false;
    if (q) return [c.ip, c.titulo, c.local, c.model, c.fabricante]
      .some(f => (f||'').toLowerCase().includes(q));
    return true;
  });

  // Contadores
  setText('snapCamTotal',   _snapCamAll.length);
  setText('snapCamComFoto', _snapCamAll.filter(c => c.snapshot_url).length);
  setText('snapCamSemFoto', _snapCamAll.filter(c => !c.snapshot_url).length);

  renderSnapCamGrid(filtered);
}

