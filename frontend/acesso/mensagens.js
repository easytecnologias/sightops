// Aba Messenger do Painel (/v3/acesso/#messenger): as conversas de WhatsApp com
// os responsaveis, so leitura (as mensagens saem sozinhas pelo sistema). Mesmas
// rotas do Messenger da tela antiga (/api/access-control/whatsapp/conversations).
// Atualiza a cada 6 s so enquanto a aba esta aberta e a janela visivel.

let _msConv = [];
let _msSel = '';
let _msMsgs = [];
let _msBusca = '';
let _msTimer = null;
let _msCarregando = false;
let _msSync = '';

function msCampo(id) { return document.getElementById(id); }

// O backend grava em UTC; SQLite sem fuso, Postgres com "+00".
function msData(iso) {
  if (!iso) return null;
  let v = String(iso).trim().replace(' ', 'T');
  if (!/Z$/i.test(v) && !/[+-]\d{2}(:?\d{2})?$/.test(v.slice(10))) v += 'Z';
  const d = new Date(v);
  return isNaN(d) ? null : d;
}
function msHora(iso) { const d = msData(iso); return d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''; }
function msQuando(iso) {
  const d = msData(iso);
  if (!d) return '';
  const hoje = new Date();
  if (d.toDateString() === hoje.toDateString()) return msHora(iso);
  const ontem = new Date(hoje); ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === ontem.toDateString()) return 'ontem';
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
}
function msDia(iso) {
  const d = msData(iso);
  if (!d) return '';
  const hoje = new Date(), ontem = new Date(hoje);
  ontem.setDate(hoje.getDate() - 1);
  if (d.toDateString() === hoje.toDateString()) return 'Hoje';
  if (d.toDateString() === ontem.toDateString()) return 'Ontem';
  return d.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: 'long' });
}
function msFone(n) { return typeof psFoneFmt === 'function' ? psFoneFmt(n) : n; }
function msRotulo(c) {
  if (c.person_name) return { titulo: c.person_name, sub: [c.guardian_name && `resp.: ${c.guardian_name}`, c.class_name].filter(Boolean).join(' · ') || msFone(c.contact_number), nome: true };
  if (c.guardian_name) return { titulo: c.guardian_name, sub: msFone(c.contact_number), nome: true };
  return { titulo: msFone(c.contact_number), sub: 'número sem cadastro', nome: false };
}
function msMarca(status) {
  const k = String(status || '').toLowerCase();
  if (k === 'read') return '<span class="ms-tick lida" title="Lida">✓✓</span>';
  if (k === 'delivered') return '<span class="ms-tick" title="Entregue">✓✓</span>';
  if (['whatsapp_sent', 'sent', 'accepted'].includes(k)) return '<span class="ms-tick" title="Enviada">✓</span>';
  if (k.includes('fail')) return '<span class="ms-tick falhou" title="Falhou">!</span>';
  return '';
}
function msAvatar(c, r) {
  let h = 0;
  for (const ch of String(c.contact_number || '')) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const letra = r.nome ? String(r.titulo).trim().charAt(0).toUpperCase() : '';
  return `<span class="ms-av p${h % 6}" aria-hidden="true">${/[A-ZÀ-Ú]/.test(letra) ? esc(letra) : '<i data-lucide="user-round"></i>'}</span>`;
}

// Local do topo: so as conversas de quem e daquele local.
function msVisiveis() {
  const site = typeof _apSite === 'string' ? _apSite.toUpperCase() : '';
  const termo = _msBusca.trim().toLowerCase(), dig = termo.replace(/\D/g, '');
  return _msConv.filter(c => (!site || String(c.site || '').toUpperCase() === site)
    && (!termo || msRotulo(c).titulo.toLowerCase().includes(termo) || String(c.guardian_name || '').toLowerCase().includes(termo)
        || (dig.length > 0 && String(c.contact_number).includes(dig))));
}

function msDesenhar() {
  const el = msCampo('msConteudo');
  if (!el) return;
  // Redesenha a cada 6 s: guarda onde a pessoa estava lendo.
  const fioAntes = msCampo('msFio'), listaAntes = el.querySelector('.ms-convs');
  const noFim = !fioAntes || fioAntes.scrollHeight - fioAntes.scrollTop - fioAntes.clientHeight < 40;
  const topoFio = fioAntes ? fioAntes.scrollTop : 0, topoLista = listaAntes ? listaAntes.scrollTop : 0;
  const digitando = document.activeElement && document.activeElement.id === 'msBusca' ? document.activeElement.selectionStart : null;
  const lista = msVisiveis();
  const hoje = new Date().toDateString();
  const n = {
    hoje: lista.filter(c => (msData(c.last_at) || {}).toDateString?.() === hoje).length,
    resp: lista.filter(c => c.last_direction === 'in').length,
    falha: lista.filter(c => String(c.last_status || '').includes('fail')).length,
  };
  const conv = _msConv.find(c => c.contact_number === _msSel);
  const r = conv ? msRotulo(conv) : null;
  let dia = '';
  const bolhas = _msMsgs.map(m => {
    const d = msDia(m.created_at), sep = d && d !== dia ? `<div class="ms-dia"><span>${esc(d)}</span></div>` : '';
    dia = d || dia;
    const minha = m.direction === 'out';
    return `${sep}<div class="ms-linha ${minha ? 'out' : 'in'}"><div class="ms-bolha">
      <div class="ms-texto">${esc(m.body) || '<em>(sem texto)</em>'}</div>
      ${m.error ? `<div class="ms-erro">${esc(m.error)}</div>` : ''}
      <div class="ms-meta">${msHora(m.created_at)}${minha ? msMarca(m.status) : ''}</div></div></div>`;
  }).join('');
  el.innerHTML = `
    <div class="ms-chips">
      <span class="ms-chip"><i data-lucide="users"></i>${apNum(lista.length)} conversa${lista.length === 1 ? '' : 's'}</span>
      <span class="ms-chip ${n.hoje ? 'ok' : ''}"><i data-lucide="calendar-clock"></i>${apNum(n.hoje)} hoje</span>
      <span class="ms-chip"><i data-lucide="reply"></i>${apNum(n.resp)} com resposta do responsável</span>
      ${n.falha ? `<span class="ms-chip ruim"><i data-lucide="alert-triangle"></i>${apNum(n.falha)} com falha no último envio</span>` : ''}
      <span class="ms-sync">${_msSync ? 'Atualizado às ' + esc(_msSync) + ' · ' : ''}atualiza sozinho a cada 6 s</span>
    </div>
    <div class="ms">
      <section class="panel ms-lista" aria-label="Conversas">
        <label class="dv-busca ms-busca"><i data-lucide="search"></i><input type="search" id="msBusca" placeholder="Buscar nome ou número" value="${esc(_msBusca)}" aria-label="Buscar conversa"></label>
        <div class="ms-convs">${lista.length ? lista.map(c => {
          const rr = msRotulo(c), out = c.last_direction === 'out';
          return `<button type="button" class="ms-conv ${c.contact_number === _msSel ? 'on' : ''}" data-ms-num="${esc(c.contact_number)}">
            ${msAvatar(c, rr)}
            <span class="ms-conv-txt"><span class="ms-conv-top"><b>${esc(rr.titulo)}</b><small>${esc(msQuando(c.last_at))}</small></span>
              <span class="ms-prev"><i data-lucide="${out ? 'arrow-up-right' : 'arrow-down-left'}" class="${out ? 'out' : 'in'}"></i>${out ? msMarca(c.last_status) : ''}<span>${esc(String(c.last_body || '').replace(/\n+/g, ' ').slice(0, 90)) || '(sem texto)'}</span></span>
              <small class="ms-sub">${esc(rr.sub)}</small></span></button>`;
        }).join('') : `<p class="ap-vazio ap-pad">${_msConv.length ? 'Nenhuma conversa com esse filtro.' : 'Nenhuma conversa ainda.'}</p>`}</div>
      </section>
      <section class="panel ms-chat" aria-label="Mensagens">
        ${conv ? `<header class="ms-chat-cab">${msAvatar(conv, r)}<div><b>${esc(r.titulo)}</b><small>${esc(msFone(conv.contact_number))}${conv.site ? ' · ' + esc(conv.site) : ''}</small></div></header>
          <div class="ms-fio" id="msFio">${bolhas || '<p class="ap-vazio ap-pad">Sem mensagens com este contato.</p>'}</div>`
          : '<div class="dv-vazio ms-nada"><i data-lucide="message-circle"></i><b>Escolha uma conversa</b><p>As mensagens aparecem aqui, com a hora e se foram entregues e lidas.</p></div>'}
        <footer class="ms-rodape"><i data-lucide="lock"></i>Só leitura: as mensagens saem sozinhas a cada entrada e saída.
          <span class="ms-legenda"><span class="ms-tick">✓</span>enviada <span class="ms-tick">✓✓</span>entregue <span class="ms-tick lida">✓✓</span>lida <span class="ms-tick falhou">!</span>falhou</span></footer>
      </section>
    </div>`;
  const b = msCampo('msBusca');
  b?.addEventListener('input', () => { _msBusca = b.value; msDesenhar(); });
  if (b && digitando !== null) { b.focus(); try { b.setSelectionRange(digitando, digitando); } catch (_) {} }
  el.querySelectorAll('[data-ms-num]').forEach(x => x.addEventListener('click', () => msAbrir(x.dataset.msNum)));
  const fio = msCampo('msFio');
  if (fio) fio.scrollTop = noFim || !fioAntes ? fio.scrollHeight : topoFio;
  const lista2 = el.querySelector('.ms-convs');
  if (lista2) lista2.scrollTop = topoLista;
  if (window.lucide) lucide.createIcons();
}

async function msAbrir(numero) {
  _msSel = numero;
  _msMsgs = [];
  const f = msCampo('msFio');
  if (f) f.remove();   // conversa nova abre no fim
  msDesenhar();
  await msFio();
}

async function msFio() {
  if (!_msSel) return;
  const numero = _msSel;
  try {
    const r = await acJson(`/api/access-control/whatsapp/conversations/${encodeURIComponent(numero)}/messages`);
    if (_msSel === numero) { _msMsgs = (r && r.messages) || []; msDesenhar(); }
  } catch (err) {
    acToast('Não consegui abrir a conversa: ' + err.message, true);
  }
}

async function msCarregar() {
  if (_msCarregando) return;
  _msCarregando = true;
  try {
    const r = await acJson('/api/access-control/whatsapp/conversations');
    _msConv = (r && r.conversations) || [];
    _msSync = new Date().toLocaleTimeString('pt-BR');
    msDesenhar();   // msDesenhar devolve o cursor a quem esta digitando na busca
    if (_msSel) await msFio();
  } finally {
    _msCarregando = false;
  }
}

// Chamado pelo Painel ao abrir a aba.
async function msAbrirAba() {
  msDesenhar();
  if (!_msTimer) {
    _msTimer = setInterval(() => {
      if (typeof _apTela === 'string' && _apTela !== 'messenger') return;
      if (typeof _currentView === 'string' && _currentView !== 'access-painel') return;   // saiu do Controle de Acesso
      if (document.hidden) return;
      msCarregar().catch(() => {});
    }, 6000);
  }
  try {
    await msCarregar();
  } catch (err) {
    const el = msCampo('msConteudo');
    if (el && !_msConv.length) el.innerHTML = `<p class="ap-vazio">Não consegui carregar as conversas: ${esc(err.message || err)}</p>`;
  }
}
