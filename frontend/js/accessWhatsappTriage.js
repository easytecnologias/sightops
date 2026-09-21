let _accessTriageRows = [];
let _accessTriageSelectedId = '';
let _accessTriageBound = false;
let _accessTriageSearchTimer = null;

function accessTriageStatusLabel(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'ready') return 'Pronto';
  if (key === 'review') return 'Revisar';
  if (key === 'duplicate') return 'Duplicado';
  if (key === 'approved') return 'Aprovado';
  if (key === 'rejected') return 'Recusado';
  return 'Pendente';
}

function accessTriageStatusClass(status) {
  const key = String(status || '').toLowerCase();
  if (key === 'ready' || key === 'approved') return 'badge-green';
  if (key === 'review') return 'badge-amber';
  if (key === 'duplicate' || key === 'rejected') return 'badge-red';
  return 'badge-gray';
}

function accessTriageSuggested(item) {
  return item?.suggested && typeof item.suggested === 'object' ? item.suggested : {};
}

function bindAccessWhatsappTriage() {
  if (_accessTriageBound) return;
  _accessTriageBound = true;
  document.getElementById('btnAccessTriageRefresh')?.addEventListener('click', () => loadAccessWhatsappTriage(true));
  document.getElementById('btnAccessTriageApproveAll')?.addEventListener('click', approveReadyAccessTriage);
  document.getElementById('btnAccessTriageMock')?.addEventListener('click', createMockAccessTriageItem);
  document.getElementById('accessTriageStatus')?.addEventListener('change', () => loadAccessWhatsappTriage(true));
  document.getElementById('accessTriageSearch')?.addEventListener('input', () => {
    clearTimeout(_accessTriageSearchTimer);
    _accessTriageSearchTimer = setTimeout(renderAccessTriageList, 160);
  });
}

async function loadAccessWhatsappTriage(force = false) {
  bindAccessWhatsappTriage();
  const status = document.getElementById('accessTriageStatus')?.value || '';
  const query = new URLSearchParams();
  if (status) query.set('status', status);
  const url = `/api/access-control/whatsapp/triage${query.toString() ? `?${query}` : ''}`;
  const data = await apiJson(url, { forceRefresh: force, cacheTtl: 0 });
  _accessTriageRows = Array.isArray(data?.items) ? data.items : [];
  renderAccessTriageSummary(data?.summary || {});
  renderAccessTriageList();
  if (_accessTriageSelectedId && !_accessTriageRows.some(item => item.id === _accessTriageSelectedId)) {
    _accessTriageSelectedId = '';
  }
  renderAccessTriageDetail(_accessTriageRows.find(item => item.id === _accessTriageSelectedId) || _accessTriageRows[0] || null);
}

function renderAccessTriageSummary(summary = {}) {
  setText('accessTriageReady', summary.ready || 0);
  setText('accessTriageReview', summary.review || 0);
  setText('accessTriageDuplicate', summary.duplicate || 0);
  setText('accessTriageApproved', summary.approved || 0);
  setText('accessTriageCount', `${summary.total || _accessTriageRows.length || 0} itens`);
  const approveAll = document.getElementById('btnAccessTriageApproveAll');
  if (approveAll) {
    const ready = Number(summary.ready || 0);
    approveAll.disabled = ready <= 0;
    approveAll.innerHTML = `<i data-lucide="check-check"></i> Aprovar prontos${ready ? ` (${ready})` : ''}`;
  }
  lucide.createIcons();
}

function filteredAccessTriageRows() {
  const q = String(document.getElementById('accessTriageSearch')?.value || '').trim().toLowerCase();
  if (!q) return _accessTriageRows;
  return _accessTriageRows.filter(item => {
    const s = accessTriageSuggested(item);
    return [
      s.full_name,
      s.site,
      s.group_name,
      s.unit_label,
      item.source_group,
      item.raw_text,
      item.from_name,
    ].join(' ').toLowerCase().includes(q);
  });
}

function renderAccessTriageList() {
  const box = document.getElementById('accessTriageList');
  if (!box) return;
  const rows = filteredAccessTriageRows();
  if (!rows.length) {
    box.innerHTML = '<div class="access-triage-empty">Nenhum item encontrado na fila.</div>';
    return;
  }
  box.innerHTML = rows.map(item => {
    const s = accessTriageSuggested(item);
    const selected = item.id === _accessTriageSelectedId;
    const reasons = Array.isArray(item.reasons) ? item.reasons.filter(Boolean).slice(0, 2).join(', ') : '';
    const name = s.full_name || 'Nome nao identificado';
    return `
      <article class="access-triage-item ${selected ? 'selected' : ''}" data-triage-id="${esc(item.id)}" onclick="selectAccessTriageItem('${esc(item.id)}')">
        <div class="access-triage-avatar">${item.photo_url || item.photo_base64 ? '<i data-lucide="image"></i>' : '<i data-lucide="message-square"></i>'}</div>
        <div class="access-triage-item-main">
          <div class="access-triage-item-title">
            <strong>${esc(name)}</strong>
            <span class="badge ${accessTriageStatusClass(item.status)}">${esc(accessTriageStatusLabel(item.status))}</span>
          </div>
          <p>${esc([s.unit_label, s.site, item.source_group].filter(Boolean).join(' - ') || item.raw_text || 'Mensagem sem texto')}</p>
          ${reasons ? `<small>${esc(reasons)}</small>` : ''}
        </div>
      </article>
    `;
  }).join('');
  lucide.createIcons();
}

function selectAccessTriageItem(id) {
  _accessTriageSelectedId = id;
  renderAccessTriageList();
  renderAccessTriageDetail(_accessTriageRows.find(item => item.id === id) || null);
}

function renderAccessTriageDetail(item) {
  const box = document.getElementById('accessTriageDetail');
  const status = document.getElementById('accessTriageDetailStatus');
  if (!box) return;
  if (!item) {
    if (status) {
      status.className = 'badge badge-gray';
      status.textContent = 'Selecione';
    }
    box.innerHTML = '<div class="access-triage-empty">Selecione um item da fila para revisar.</div>';
    return;
  }
  _accessTriageSelectedId = item.id;
  const s = accessTriageSuggested(item);
  if (status) {
    status.className = `badge ${accessTriageStatusClass(item.status)}`;
    status.textContent = accessTriageStatusLabel(item.status);
  }
  const reasons = Array.isArray(item.reasons) && item.reasons.length
    ? `<div class="access-triage-reasons">${item.reasons.map(reason => `<span>${esc(reason)}</span>`).join('')}</div>`
    : '';
  box.innerHTML = `
    <div class="access-triage-preview">
      <div class="access-triage-photo">${item.photo_url ? `<img src="${esc(item.photo_url)}" alt="">` : '<i data-lucide="image"></i><span>Foto pendente</span>'}</div>
      <div>
        <strong>${esc(s.full_name || 'Nome nao identificado')}</strong>
        <span>${esc(item.source_group || 'Origem WhatsApp')}</span>
        ${reasons}
      </div>
    </div>
    <div class="access-triage-form">
      ${accessTriageField('Nome', 'full_name', s.full_name)}
      ${accessTriageField('Matricula/identificacao', 'enrollment_code', s.enrollment_code)}
      ${accessTriageField('ID controladora', 'controller_user_id', s.controller_user_id)}
      ${accessTriageField('Site', 'site', s.site)}
      ${accessTriageField('Grupo de pessoas', 'group_name', s.group_name)}
      ${accessTriageField('Quadra/lote/apto', 'unit_label', s.unit_label)}
      ${accessTriageField('Responsavel', 'guardian_name', s.guardian_name)}
      ${accessTriageField('Telefone', 'guardian_phone', s.guardian_phone)}
    </div>
    <label class="access-triage-raw">
      Mensagem recebida
      <textarea id="accessTriageRawText">${esc(item.raw_text || '')}</textarea>
    </label>
    <div class="access-triage-detail-actions">
      <button class="secondary-action" type="button" onclick="saveAccessTriageSelected()"><i data-lucide="save"></i> Salvar revisao</button>
      <button class="primary-action" type="button" ${item.status === 'approved' ? 'disabled' : ''} onclick="approveAccessTriageSelected()"><i data-lucide="check"></i> Aprovar cadastro</button>
      <button class="secondary-action danger-action" type="button" ${item.status === 'approved' ? 'disabled' : ''} onclick="rejectAccessTriageSelected()"><i data-lucide="x"></i> Recusar</button>
    </div>
  `;
  lucide.createIcons();
}

function accessTriageField(label, key, value) {
  return `
    <div class="form-group">
      <label for="accessTriageField_${esc(key)}">${esc(label)}</label>
      <input id="accessTriageField_${esc(key)}" data-triage-field="${esc(key)}" value="${esc(value || '')}">
    </div>
  `;
}

function currentAccessTriagePayload() {
  const suggested = {};
  document.querySelectorAll('[data-triage-field]').forEach(input => {
    suggested[input.dataset.triageField] = input.value.trim();
  });
  return {
    raw_text: document.getElementById('accessTriageRawText')?.value || '',
    suggested,
  };
}

async function saveAccessTriageSelected() {
  if (!_accessTriageSelectedId) return;
  try {
    const res = await api(`/api/access-control/whatsapp/triage/${encodeURIComponent(_accessTriageSelectedId)}`, {
      method: 'PUT',
      body: JSON.stringify(currentAccessTriagePayload()),
    });
    const data = await jsonOrReadableError(res, 'Nao foi possivel salvar a revisao.');
    _accessTriageRows = data.items || _accessTriageRows;
    renderAccessTriageSummary(data.summary || {});
    renderAccessTriageList();
    renderAccessTriageDetail(data.item);
    showToast('Triagem salva.');
  } catch (err) {
    showToast(err?.message || 'Nao foi possivel salvar a revisao.', true);
  }
}

async function approveAccessTriageSelected() {
  if (!_accessTriageSelectedId) return;
  try {
    await saveAccessTriageSelected();
    const res = await api(`/api/access-control/whatsapp/triage/${encodeURIComponent(_accessTriageSelectedId)}/approve`, { method: 'POST' });
    const data = await jsonOrReadableError(res, 'Nao foi possivel aprovar o cadastro.');
    _accessTriageRows = data.items || _accessTriageRows;
    renderAccessTriageSummary(data.summary || {});
    renderAccessTriageList();
    renderAccessTriageDetail(data.item);
    showToast(`Cadastro aprovado: ${data.person?.full_name || 'pessoa'}.`);
  } catch (err) {
    showToast(err?.message || 'Nao foi possivel aprovar o cadastro.', true);
  }
}

async function rejectAccessTriageSelected() {
  if (!_accessTriageSelectedId) return;
  const ok = await showConfirm({
    eyebrow: 'Triagem WhatsApp',
    title: 'Recusar este item?',
    msg: 'Ele continuara no historico como recusado e nao criara cadastro.',
    label: 'Recusar',
    danger: true,
  });
  if (!ok) return;
  try {
    const res = await api(`/api/access-control/whatsapp/triage/${encodeURIComponent(_accessTriageSelectedId)}/reject`, {
      method: 'POST',
      body: JSON.stringify({ reason: 'recusado manualmente' }),
    });
    const data = await jsonOrReadableError(res, 'Nao foi possivel recusar.');
    _accessTriageRows = data.items || _accessTriageRows;
    renderAccessTriageSummary(data.summary || {});
    renderAccessTriageList();
    renderAccessTriageDetail(data.item);
    showToast('Item recusado.');
  } catch (err) {
    showToast(err?.message || 'Nao foi possivel recusar.', true);
  }
}

async function approveReadyAccessTriage() {
  const ready = _accessTriageRows.filter(item => item.status === 'ready').length;
  if (!ready) return;
  const ok = await showConfirm({
    eyebrow: 'Triagem WhatsApp',
    title: `Aprovar ${ready} cadastro(s) pronto(s)?`,
    msg: 'Itens em revisao ou duplicados ficarao pendentes.',
    label: 'Aprovar prontos',
    danger: false,
  });
  if (!ok) return;
  try {
    const res = await api('/api/access-control/whatsapp/triage/approve-ready', { method: 'POST' });
    const data = await jsonOrReadableError(res, 'Nao foi possivel aprovar os prontos.');
    _accessTriageRows = data.items || _accessTriageRows;
    renderAccessTriageSummary(data.summary || {});
    renderAccessTriageList();
    renderAccessTriageDetail(_accessTriageRows.find(item => item.id === _accessTriageSelectedId) || _accessTriageRows[0] || null);
    showToast(data.group_message || 'Cadastros aprovados.');
  } catch (err) {
    showToast(err?.message || 'Nao foi possivel aprovar os prontos.', true);
  }
}

async function createMockAccessTriageItem() {
  try {
    const res = await api('/api/access-control/whatsapp/triage', {
      method: 'POST',
      body: JSON.stringify({
        source_group: 'Reconhecimento facial portaria - Jardins 2',
        site: 'RESERVA',
        text: 'Natalia Borges\\nQuadra G-37',
        from_name: 'Atendimento',
      }),
    });
    const data = await jsonOrReadableError(res, 'Nao foi possivel criar simulacao.');
    _accessTriageRows = data.items || _accessTriageRows;
    _accessTriageSelectedId = data.item?.id || '';
    renderAccessTriageSummary(data.summary || {});
    renderAccessTriageList();
    renderAccessTriageDetail(data.item);
    showToast('Mensagem simulada criada na triagem.');
  } catch (err) {
    showToast(err?.message || 'Nao foi possivel criar simulacao.', true);
  }
}
