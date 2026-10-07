// TR-069: ONUs do cliente que conversam com o servidor de gerencia.
// Backend: /api/tr069 (app/services/tr069_service.py). O cliente nunca ve o
// GenieACS: a lista ja vem filtrada pelo serial das ONUs do inventario dele.

let _tr069Lista = [];
let _tr069Serial = '';

const TR069_ESTADO = {
  gerenciada:  ['b-green', 'Gerenciada'],
  sem_contato: ['b-amber', 'Sem contato'],
  aguardando:  ['b-blue', 'Aguardando 1º contato'],
  // Fala com o servidor, mas o serial ainda nao foi coletado da OLT.
  // Antes era simplesmente omitido: o aparelho funcionava e sumia da tela.
  fora_do_inventario: ['b-amber', 'Fora do inventário'],
};

function tr069Quando(iso) {
  if (!iso) return '—';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return 'agora';
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function tr069Duracao(seg) {
  const s = Number(seg);
  if (!Number.isFinite(s) || s <= 0) return '—';
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return d ? `${d} d ${h} h` : h ? `${h} h ${m} min` : `${m} min`;
}

function tr069Badge(estado) {
  const [cls, txt] = TR069_ESTADO[estado] || ['b-gray', 'Sem TR-069'];
  return `<span class="tr-badge ${cls}">${esc(txt)}</span>`;
}

function tr069Wan(w) {
  if (!w) return '—';
  if (!w.status) return '<span class="tr-badge plain b-gray">aguardando leitura</span>';
  const ok = String(w.status || '').toLowerCase() === 'connected';
  const txt = [w.vlan != null && w.vlan !== -1 ? `VLAN ${w.vlan}` : '', w.tipo === 'pppoe' ? 'PPPoE' : 'IP', ok ? '' : (w.status || 'desconectada')]
    .filter(Boolean).join(' · ');
  return `<span class="tr-badge plain ${ok ? 'b-green' : 'b-red'}">${esc(txt)}</span>`;
}

async function loadTr069(forcar = false) {
  const corpo = document.getElementById('tr069Tbody');
  if (!corpo) return;
  // Nada da carga anterior fica na tela: listas e paineis sao do cliente de antes.
  _tr069Lista = []; _tr069Cand = []; _tr069Modo = null;
  ['tr069AtivarBox', 'tr069ConfigPanel'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.classList.add('hidden'); if (id === 'tr069AtivarBox') el.innerHTML = ''; }
  });
  const det = document.getElementById('tr069DetalheBox');
  if (det) det.innerHTML = '';
  tr069MostrarLista();
  corpo.innerHTML = '<tr><td colspan="9" class="tr-vazio">Carregando ONUs do servidor TR-069…</td></tr>';
  const data = await apiJson('/api/tr069/devices', { forceRefresh: forcar, cacheTtl: 0 });
  if (!data || !data.ok) {
    corpo.innerHTML = `<tr><td colspan="9" class="tr-vazio tr-erro">${esc(data?.error || 'Não foi possível consultar o servidor TR-069.')}</td></tr>`;
    return;
  }
  _tr069Lista = data.onus || [];
  const c = data.contagem || {};
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v ?? 0; };
  set('tr069SumGer', c.gerenciada); set('tr069SumSem', c.sem_contato);
  set('tr069SumAg', c.aguardando); set('tr069SumSemTr', c.sem_tr069);
  set('tr069SumFora', c.fora_do_inventario || 0);
  const cartaoFora = document.getElementById('tr069CardFora');
  // So aparece quando ha o que mostrar: cartao cravado em zero vira
  // paisagem e ninguem olha mais.
  if (cartaoFora) cartaoFora.hidden = !(c.fora_do_inventario || 0);
  const total = document.getElementById('tr069SumTotal');
  if (total) total.textContent = `das ${data.total_onus || 0} ONUs do inventário`;
  tr069RenderLista();
}

function tr069RenderLista() {
  const corpo = document.getElementById('tr069Tbody');
  const busca = (document.getElementById('tr069Busca')?.value || '').trim().toLowerCase();
  const filtro = document.getElementById('tr069Filtro')?.value || '';
  const linhas = _tr069Lista.filter(o => (!filtro || o.estado === filtro) &&
    (!busca || [o.serial, o.modelo, o.nome, o.pon, o.olt, o.site].some(v => String(v ?? '').toLowerCase().includes(busca))));
  if (!linhas.length) {
    corpo.innerHTML = `<tr><td colspan="9" class="tr-vazio">${_tr069Lista.length
      ? 'Nenhuma ONU com esse filtro.'
      : 'Nenhuma ONU deste cliente conversa com o servidor TR-069 ainda.'}</td></tr>`;
    return;
  }
  corpo.innerHTML = linhas.map(o => `
    <tr data-serial="${esc(o.serial)}" class="tr-linha">
      <td><b class="tr-serial">${esc(o.serial)}</b><span class="tr-sub">${esc(o.nome || '—')}</span></td>
      <td>${o.estado === 'fora_do_inventario'
        ? `<span class="tr-muted">fora do inventário</span><span class="tr-sub">gerencia ${esc(o.ip_gerencia || '—')}</span>`
        : `${esc(o.pon ?? '—')} · ONU ${esc(o.onu_id ?? '—')}<span class="tr-sub">${esc(o.olt || '')}</span>`}</td>
      <td>${esc([o.fabricante, o.modelo].filter(Boolean).join(' '))}<span class="tr-sub">${esc(o.firmware || '—')}</span></td>
      <td>${tr069Badge(o.estado)}</td>
      <td>${esc(tr069Quando(o.ultimo_contato))}</td>
      <td>${tr069Wan(o.wan)}</td>
      <td>${o.lan_total ? `${o.lan_com_link} de ${o.lan_total}` : '—'}</td>
      <td>${o.tem_wifi ? `${o.wifi_clientes ?? 0} cliente(s)` : '<span class="tr-muted">sem rádio</span>'}</td>
      <td class="tr-num">${esc(tr069Dbm(o.sinal_dbm))}</td>
    </tr>`).join('');
}

function tr069MostrarLista() {
  document.getElementById('tr069ListaBox')?.classList.remove('hidden');
  document.getElementById('tr069DetalheBox')?.classList.add('hidden');
  _tr069Serial = '';
}

async function tr069AbrirDetalhe(serial) {
  _tr069Serial = serial;
  document.getElementById('tr069ListaBox')?.classList.add('hidden');
  const box = document.getElementById('tr069DetalheBox');
  box.classList.remove('hidden');
  box.innerHTML = '<div class="panel"><div class="tr-vazio">Lendo a ONU…</div></div>';
  const d = await apiJson(`/api/tr069/devices/${encodeURIComponent(serial)}`, { cacheTtl: 0 });
  if (_tr069Serial !== serial) return;
  if (!d || !d.ok) {
    box.innerHTML = `<div class="panel"><div class="tr-vazio tr-erro">${esc(d?.error || 'Falha ao ler a ONU.')}</div>
      <div class="tr-pad"><button class="secondary-action" data-tr069-voltar><i data-lucide="arrow-left"></i> Voltar</button></div></div>`;
    lucide.createIcons();
    return;
  }
  const r = d.detalhe || {};
  const wan = (r.wan || []).find(w => w.habilitada) || (r.wan || [])[0];
  const temWifi = (r.wifi || []).length > 0;
  const lanLink = (r.lan || []).filter(p => p.link).length;
  const wanInfo = [wan?.vlan ? 'VLAN ' + wan.vlan : '', wan?.ip].filter(Boolean).join(' · ') || '—';
  const painelWifi = !temWifi ? '' : `
        <section class="panel">
          <div class="tr-panel-head"><div><h3>Wi-Fi</h3><p>Nome e senha das redes da ONU.</p></div></div>
          <div class="tr-pad">${r.wifi.map(w => `
            <div class="tr-form" data-tr069-wifi="${esc(w.indice)}">
              <div class="form-group"><label for="tr069Ssid${esc(w.indice)}">Nome da rede ${esc(w.indice)}${w.clientes != null ? ` · ${esc(w.clientes)} cliente(s)` : ''}</label>
                <input id="tr069Ssid${esc(w.indice)}" value="${esc(w.ssid || '')}" maxlength="32"></div>
              <div class="form-group"><label for="tr069Senha${esc(w.indice)}">Nova senha</label>
                <input id="tr069Senha${esc(w.indice)}" type="password" placeholder="em branco = manter" maxlength="63"></div>
              <button class="primary-action" data-tr069-salvar-wifi="${esc(w.indice)}"><i data-lucide="save"></i> Salvar na ONU</button>
            </div>`).join('')}</div>
        </section>`;
  box.innerHTML = `
  <div class="tr-detail">
    <div class="page-heading">
      <div><p class="eyebrow">TR-069 · ${esc(d.olt || '')}</p><h1>${esc(tr069Titulo(d))}</h1>
        <p>Mudanças vão para a ONU na hora, pelo conector. Se ela não responder, ficam na fila e entram no próximo contato.</p></div>
      <div class="page-heading-actions">
        <button class="secondary-action" data-tr069-voltar><i data-lucide="arrow-left"></i> Voltar</button>
        <button class="secondary-action" data-tr069-acao="ler"><i data-lucide="refresh-cw"></i> Ler agora</button>
        <button class="primary-action" data-tr069-modo><i data-lucide="layers"></i> Modo de operação</button>
      </div>
    </div>
    <section class="panel">
      <div class="tr-head">
        <div class="tr-dev"><div class="tr-dev-ico"><i data-lucide="router"></i></div>
          <div><h2>${esc(d.serial)}</h2>
          <p>${esc([r.fabricante, r.modelo].filter(Boolean).join(' '))} · PON ${esc(d.pon ?? '—')} · ONU ${esc(d.onu_id ?? '—')}</p></div></div>
        ${tr069Badge(d.estado)}
      </div>
      <div class="tr-tiles">
        <div class="tr-tile"><span>Sinal na ONU</span><b>${esc(tr069Dbm(d.sinal_dbm))}</b><small>lido pela OLT</small></div>
        <div class="tr-tile"><span>Tempo ligada</span><b>${esc(tr069Duracao(r.uptime_s))}</b><small>último boot ${esc(tr069Quando(r.ultimo_boot))}</small></div>
        <div class="tr-tile"><span>WAN</span><b>${esc(tr069StatusWan(wan?.status))}</b><small>${wan?.vlan ? 'VLAN ' + esc(wan.vlan) + ' · ' : ''}${wan?.ip
          ? `<a href="#" class="tr-ip-web" data-tr069-web="${esc(wan.ip)}" title="Abrir a web da ONU pela rede do cliente">${esc(wan.ip)} ↗</a>` : '—'}</small></div>
        <div class="tr-tile"><span>Portas LAN</span><b>${lanLink} de ${(r.lan || []).length}</b><small>com link agora</small></div>
        <div class="tr-tile"><span>DHCP da LAN</span><b>${r.dhcp_lan === null || r.dhcp_lan === undefined
          ? '—' : (r.dhcp_lan ? 'ligado' : 'desligado')}</b>
          <small>${r.dhcp_lan === null || r.dhcp_lan === undefined
            ? 'esta ONU nao informa'
            : `<button class="tr-link" data-tr069-dhcp="${r.dhcp_lan ? '0' : '1'}">${r.dhcp_lan ? 'desligar' : 'ligar'}</button>`}</small></div>
        <div class="tr-tile"><span>Último contato</span><b>${esc(tr069Quando(r.ultimo_contato))}</b><small>contato a cada ${Math.round((r.intervalo_s || 300) / 60)} min</small></div>
      </div>
    </section>
    <div class="tr-grid">
      <div class="tr-stack">
        <section class="panel">
          <div class="tr-panel-head"><div><h3>Portas LAN</h3><p>Desligar e religar uma porta reinicia o equipamento ligado nela.</p></div></div>
          <div class="tr-pad"><div class="tr-ports">${(r.lan || []).map(p => `
            <div class="tr-port"><div class="tr-port-top"><b>LAN ${esc(p.porta)}</b>
              <button class="tr-switch" role="switch" aria-checked="${p.habilitada ? 'true' : 'false'}" aria-label="Ligar ou desligar a LAN ${esc(p.porta)}"
                data-tr069-porta="${esc(p.porta)}"></button></div>
              <span class="tr-badge ${p.link ? 'b-green' : 'b-gray'}">${p.link ? 'com link' : 'sem link'}</span>
              <small class="tr-sub">${p.velocidade_mbps ? 'até ' + (p.velocidade_mbps >= 1000 ? (p.velocidade_mbps / 1000) + ' Gb/s' : p.velocidade_mbps + ' Mb/s') : '&nbsp;'}</small></div>`).join('') || '<span class="tr-sub">A ONU não informou portas LAN.</span>'}
          </div></div>
        </section>
        ${painelWifi}
        <section class="panel">
          <div class="tr-panel-head"><div><h3>Histórico</h3><p>Quem pediu, o quê, e se a ONU aplicou.</p></div></div>
          <div class="tr-pad"><ul class="tr-timeline">${(d.historico || []).map(h => {
            const cor = h.resultado === 'aplicada' ? 'd-green' : String(h.resultado).startsWith('falhou') ? 'd-red' : 'd-amber';
            const txt = h.resultado === 'aplicada' ? 'aplicado' : h.resultado === 'na_fila' ? 'na fila, vai no próximo contato' : h.resultado;
            return `<li><span class="tr-dot ${cor}"></span><div>${esc(h.descricao)}<span class="tr-sub">${esc(h.autor)} · ${esc(txt)}${h.detalhe ? ' · ' + esc(h.detalhe) : ''}</span></div><span class="tr-when">${esc(tr069Quando(h.em))}</span></li>`;
          }).join('') || '<li class="tr-vazio-li">Nenhuma ação ainda.</li>'}</ul></div>
        </section>
      </div>
      <div class="tr-stack">
        <section class="panel">
          <div class="tr-panel-head"><div><h3>Ações</h3><p>Valem só para esta ONU.</p></div></div>
          <div class="tr-pad"><div class="tr-quick">
            <button class="secondary-action" data-tr069-acao="reiniciar"><i data-lucide="power"></i> Reiniciar ONU</button>
            <button class="secondary-action" data-tr069-abrir="poe"><i data-lucide="plug-zap"></i> Religar PoE</button>
            <button class="secondary-action" data-tr069-abrir="ping"><i data-lucide="activity"></i> Ping pela ONU</button>
            <button class="secondary-action danger-action" data-tr069-reset><i data-lucide="rotate-ccw"></i> Reset de fábrica</button>
          </div>
          ${(d.servicos || []).find(x => x.gerencia && x.ip) ? `<button class="secondary-action tr-web-btn" data-tr069-web="${esc((d.servicos || []).find(x => x.gerencia && x.ip).ip)}"><i data-lucide="globe"></i> Abrir web da ONU · ${esc((d.servicos || []).find(x => x.gerencia && x.ip).ip)}</button>` : ''}
          <div class="tr-inline hidden" id="tr069PoeBox">
            <p>Escolha a porta. Ela desliga, espera 5 s e liga de novo: a câmera reinicia.</p>
            <div class="tr-pchips">${(r.lan || []).map(p => `<button type="button" class="tr-pchip" data-tr069-religar="${esc(p.porta)}">LAN ${esc(p.porta)}</button>`).join('')}</div>
          </div>
          <div class="tr-inline hidden" id="tr069PingBox">
            <p>A própria ONU pinga o endereço: mostra se a câmera responde do lado dela.</p>
            <div class="tr-inline-row"><input id="tr069PingHost" placeholder="IP, ex.: 10.200.1.112" aria-label="Endereço para pingar">
              <button class="primary-action" data-tr069-pingar><i data-lucide="activity"></i> Pingar</button></div>
            <div id="tr069PingRes"></div>
          </div>
          <div class="tr-confirm hidden" id="tr069ConfirmReset">
            <p><b>Reset de fábrica apaga a configuração da ONU.</b> O que estiver ligado nela fica sem rede até ela ser configurada de novo. Para confirmar, digite o serial.</p>
            <input id="tr069ConfirmSerial" placeholder="${esc(d.serial)}" aria-label="Digite o serial para confirmar">
            <div class="page-heading-actions"><button class="secondary-action danger-action" data-tr069-acao="reset_fabrica">Apagar configuração</button>
              <button class="secondary-action" data-tr069-reset-cancelar>Cancelar</button></div>
          </div></div>
        </section>
        <section class="panel">
          <div class="tr-panel-head"><div><h3>Equipamento</h3><p>Como a própria ONU se apresenta ao servidor.</p></div></div>
          <div class="tr-pad"><dl class="tr-kv">
            <dt>Fabricante</dt><dd>${esc(r.fabricante || '—')}${r.oui ? ` · OUI ${esc(r.oui)}` : ''}</dd>
            <dt>Modelo</dt><dd>${esc(r.modelo || '—')}</dd>
            <dt>Hardware</dt><dd>${esc(r.hardware || '—')}</dd>
            <dt>Firmware</dt><dd>${esc(r.firmware || '—')}</dd>
            <dt>Wi-Fi</dt><dd>${temWifi ? `${r.wifi.length} rede(s)` : 'sem rádio'}</dd>
            <dt>Padrão</dt><dd>${r.padrao === 'tr098' ? 'TR-098' : 'TR-181'}</dd>
            <dt>No servidor desde</dt><dd>${esc(tr069Quando(r.registrado_em))}</dd>
          </dl></div>
        </section>
      </div>
    </div>
  </div>`;
  lucide.createIcons();
}

// Nome que a OLT da por padrao ("gpon 4/6 onu 89") nao diz nada: vira "ONU 4/6 · 89".
function tr069Titulo(d) {
  const nome = String(d?.nome || '').trim();
  if (nome && !/^gpon\s+\d+\/\d+\s+onu\s+\d+$/i.test(nome)) return nome;
  return d?.pon ? `ONU ${d.pon} · ${d.onu_id}` : (d?.serial || 'ONU');
}

function tr069Dbm(v) {
  const n = Number(String(v ?? '').replace(',', '.'));
  if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return '—';
  return `${n < 0 ? '−' : ''}${Math.abs(n).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} dBm`;
}

function tr069StatusWan(st) {
  if (!st) return 'aguardando leitura';
  const k = String(st || '').toLowerCase();
  return { connected: 'Conectada', disconnected: 'Desconectada', connecting: 'Conectando', unconfigured: 'Sem configuração' }[k] || (st || '—');
}

async function tr069Executar(acao, dados = {}, botao = null) {
  if (!_tr069Serial) return;
  if (botao) botao.disabled = true;
  showToast('Enviando para a ONU…');
  try {
    const res = await api(`/api/tr069/devices/${encodeURIComponent(_tr069Serial)}/action`, {
      method: 'POST', body: JSON.stringify({ acao, ...dados }) });
    if (!res) return;
    if (res.status === 403) { showToast('Seu perfil não pode alterar ONU.', true); return; }
    const r = await res.json();
    if (!r.ok) { showToast(r.error || r.resultado || 'A ONU recusou.', true); }
    else if (r.resultado === 'aplicada') { showToast(`${r.descricao}: aplicado.`); }
    else { showToast(`${r.descricao}: na fila. ${r.detalhe || 'Vai no próximo contato da ONU.'}`); }
    await tr069AbrirDetalhe(_tr069Serial);
  } finally {
    if (botao) botao.disabled = false;
  }
}

async function loadTr069Config() {
  const box = document.getElementById('tr069ConfigBox');
  if (!box) return;
  const c = await apiJson('/api/tr069/config', { cacheTtl: 0 });
  if (!c) { box.innerHTML = '<div class="tr-sub">Só o administrador vê as configurações de TR-069.</div>'; return; }
  box.innerHTML = `
    <div class="tr-row"><div><b>Servidor TR-069</b><small>${c.servidor?.ok ? 'No ar e respondendo.' : esc(c.servidor?.error || 'fora do ar')}</small></div>
      <span class="tr-badge ${c.servidor?.ok ? 'b-green' : 'b-red'}">${c.servidor?.ok ? 'no ar' : 'fora do ar'}</span></div>
    <div class="tr-row"><div><b>Usuário das ONUs</b><small>Exclusivo deste cliente. A senha fica cifrada e nunca aparece na tela.</small></div>
      <code class="tr-code">${esc(c.username || '—')}</code></div>
    <div class="tr-row"><div><b>Ativar TR-069 ao autorizar ONU</b><small>ONU autorizada pelo SightOps numa OLT FiberHome já sai com TR-069 ligado, em segundo plano.</small></div>
      <button class="tr-switch" role="switch" aria-checked="${c.auto_ativar ? 'true' : 'false'}" aria-label="Ativar TR-069 ao autorizar ONU" data-tr069-auto></button></div>
    <div class="tr-row"><div><b>VLAN de gerência TR-069</b><small>Usada para ativar ONU em OLT Intelbras 8820i: a OLT põe esse serviço na ONU e o DHCP com opção 43 faz o resto.</small></div>
      <div class="tr-inline-row"><input id="tr069VlanGer" inputmode="numeric" value="${esc(c.vlan_gerencia || '')}" placeholder="ex.: 7" aria-label="VLAN de gerencia" style="width:90px">
        <button class="secondary-action tr-small" data-tr069-salvar-vlan>Salvar</button></div></div>
    <div class="tr-row"><div><b>Senha da web das ONUs</b><small>${c.tem_senha_web
        ? 'Definida. Aplicada sozinha em toda ONU gerenciada deste cliente, inclusive nas novas.'
        : 'Nao definida: as ONUs ficam com a senha de fabrica.'} Nunca aparece na tela depois de salva.</small></div>
      <div class="tr-inline-row"><input id="tr069SenhaWeb" type="password" autocomplete="new-password"
             placeholder="${c.tem_senha_web ? 'definida — digite para trocar' : 'minimo 6 caracteres'}"
             aria-label="Senha da web das ONUs" style="width:190px">
        <button class="secondary-action tr-small" data-tr069-salvar-senhaweb>Salvar</button></div></div>
    <div class="tr-row"><div><b>Intervalo de contato</b><small>Hoje fixo em 5 minutos para todas as ONUs.</small></div>
      <span class="tr-badge plain b-gray">5 min</span></div>`;
}

document.addEventListener('click', ev => {
  const view = document.getElementById('viewDeployTr069');
  if (!view || !view.contains(ev.target)) return;
  const t = ev.target.closest('button, tr.tr-linha');
  if (!t) return;
  if (t.matches('tr.tr-linha')) return tr069AbrirDetalhe(t.dataset.serial);
  if (t.id === 'btnTr069Atualizar') return loadTr069(true);
  if (t.id === 'btnTr069Config') {
    const box = document.getElementById('tr069ConfigPanel');
    box.classList.toggle('hidden');
    if (!box.classList.contains('hidden')) loadTr069Config();
    return;
  }
  if (t.hasAttribute('data-tr069-voltar')) return loadTr069();
  if (t.hasAttribute('data-tr069-reset')) {
    ['tr069PoeBox', 'tr069PingBox'].forEach(id => document.getElementById(id)?.classList.add('hidden'));
    return document.getElementById('tr069ConfirmReset')?.classList.remove('hidden');
  }
  if (t.hasAttribute('data-tr069-reset-cancelar')) return document.getElementById('tr069ConfirmReset')?.classList.add('hidden');
  if (t.dataset.tr069Porta) {
    const ligar = t.getAttribute('aria-checked') !== 'true';
    return tr069Executar('porta_lan', { porta: Number(t.dataset.tr069Porta), habilitar: ligar }, t);
  }
  if (t.dataset.tr069SalvarWifi) {
    const i = t.dataset.tr069SalvarWifi;
    return tr069Executar('wifi', { indice: Number(i), ssid: document.getElementById(`tr069Ssid${i}`)?.value || '',
      senha: document.getElementById(`tr069Senha${i}`)?.value || '' }, t);
  }
  if (t.dataset.tr069Acao) {
    const acao = t.dataset.tr069Acao;
    const dados = acao === 'reset_fabrica' ? { confirmar_serial: document.getElementById('tr069ConfirmSerial')?.value || '' } : {};
    return tr069Executar(acao, dados, t);
  }
});

document.addEventListener('input', ev => {
  if (ev.target.id === 'tr069Busca') tr069RenderLista();
});

document.addEventListener('click', async ev => {
  const box = document.getElementById('tr069DetalheBox');
  if (!box || !box.contains(ev.target)) return;
  const t = ev.target.closest('button, a[data-tr069-web]');
  if (!t) return;
  if (t.dataset.tr069Web) { ev.preventDefault(); return openDeviceWeb(t.dataset.tr069Web, 80); }
  if (t.dataset.tr069Abrir) {
    const alvo = t.dataset.tr069Abrir === 'poe' ? 'tr069PoeBox' : 'tr069PingBox';
    ['tr069PoeBox', 'tr069PingBox', 'tr069ConfirmReset'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.classList.toggle('hidden', id !== alvo || !el.classList.contains('hidden'));
    });
    if (alvo === 'tr069PingBox') document.getElementById('tr069PingHost')?.focus();
    return;
  }
  if (t.dataset.tr069Religar) return tr069Executar('religar_porta', { porta: Number(t.dataset.tr069Religar) }, t);
  if (t.hasAttribute('data-tr069-pingar')) {
    const host = document.getElementById('tr069PingHost')?.value.trim();
    const out = document.getElementById('tr069PingRes');
    if (!host) { showToast('Informe o IP para pingar.', true); return; }
    t.disabled = true;
    out.innerHTML = '<span class="tr-sub tr-mt">Pingando pela ONU… leva uns 20 segundos.</span>';
    try {
      const res = await api(`/api/tr069/devices/${encodeURIComponent(_tr069Serial)}/action`, {
        method: 'POST', body: JSON.stringify({ acao: 'ping', host }) });
      if (res && res.status === 403) { out.innerHTML = ''; showToast('Seu perfil não pode usar diagnóstico.', true); return; }
      const r = res ? await res.json() : null;
      const p = r?.ping;
      out.innerHTML = p
        ? `<div class="tr-box tr-mt ${Number(p.ok) > 0 ? 'tr-ok-box' : 'tr-erro-box'}"><b>${esc(p.ok)} de 4 responderam</b>${Number(p.ok) > 0 ? ` · média ${esc(p.media_ms)} ms · pior ${esc(p.max_ms)} ms` : ' · o endereço não responde do lado da ONU'}</div>`
        : `<div class="tr-box tr-mt tr-erro-box">${esc(r?.error || r?.detalhe || r?.resultado || 'A ONU não respondeu.')}</div>`;
    } finally { t.disabled = false; }
  }
});
document.addEventListener('change', ev => {
  if (ev.target.id === 'tr069Filtro') tr069RenderLista();
});

// --------------------------------------------------------------------------
// Modo de operacao: os servicos da ONT e os cenarios prontos.
// A tela edita um RASCUNHO da lista de servicos (sem a gerencia); "Ver o que
// muda" pede a previa ao backend, "Aplicar" executa passo a passo.
// --------------------------------------------------------------------------
let _tr069Modo = null;

const TR069_FUNCOES = [['cameras', 'Câmeras'], ['internet', 'Internet'], ['iptv', 'IPTV'], ['voip', 'VoIP'], ['outro', 'Outro']];
const TR069_MODOS = [['bridge', 'Bridge'], ['dhcp', 'Roteador · DHCP'], ['pppoe', 'Roteador · PPPoE']];
const TR069_CENARIOS = [
  ['cameras_bridge', 'cctv', 'Câmeras em bridge (VEIP)', 'Gerência + bridge da VLAN das câmeras nas portas escolhidas'],
  ['internet_pppoe', 'globe', 'Internet do cliente · PPPoE', 'A ONT roteia: PPPoE na VLAN da internet'],
  ['roteador_ipoe', 'network', 'Roteador IPoE', 'A ONT roteia com DHCP na VLAN'],
  ['bridge_total', 'cable', 'Bridge total', 'Uma VLAN em todas as portas; o roteador do cliente faz o PPPoE'],
  ['multisservico', 'tv', 'Multisserviço', 'Internet + IPTV (VLAN 1334) + câmeras em portas separadas'],
];

function tr069Rascunho(s) {
  return {
    id: s.id || null, tipo: s.tipo || (s.modo === 'pppoe' ? 'ppp' : 'ip'),
    funcao: s.funcao === 'gerencia' ? 'outro' : (s.funcao || 'outro'),
    modo: s.modo, vlan: s.vlan || '', prioridade: s.prioridade ?? '', portas: [...(s.portas || [])],
    usuario: s.usuario || '', senha: '', mcast_vlan: s.mcast_vlan || '', igmp: !!s.igmp,
  };
}

async function tr069AbrirModo() {
  const box = document.getElementById('tr069DetalheBox');
  box.innerHTML = '<div class="panel"><div class="tr-vazio">Lendo os serviços da ONT…</div></div>';
  const d = await apiJson(`/api/tr069/devices/${encodeURIComponent(_tr069Serial)}`, { cacheTtl: 0 });
  if (!d || !d.ok) {
    box.innerHTML = `<div class="panel"><div class="tr-vazio tr-erro">${esc(d?.error || 'Falha ao ler a ONU.')}</div></div>`;
    return;
  }
  const servicos = d.servicos || [];
  const gerencia = servicos.find(s => s.gerencia);
  _tr069Modo = {
    d, gerencia,
    editavel: !!gerencia && servicos.filter(s => !s.gerencia).every(s => s.editavel) && gerencia.perfil,
    rascunho: servicos.filter(s => !s.gerencia).map(tr069Rascunho),
    cenario: d.cenario?.chave || '',
  };
  tr069RenderModo();
}

function tr069Dis(ed) { return ed ? '' : 'disabled'; }

function tr069CardGerencia(g) {
  if (!g) return '<div class="tr-box tr-warn">Não identifiquei o serviço de gerência desta ONU. Por segurança, a tela fica só para leitura.</div>';
  return `
    <article class="tr-wan tr-locked">
      <header><div class="tr-wan-title"><span class="tr-wan-ico ico-cyan"><i data-lucide="radio-tower"></i></span>
        <div><b>Gerência TR-069</b><small>por onde o servidor fala com a ONU</small></div></div>
        <span class="tr-badge b-green">${esc(tr069StatusWan(g.status))}</span></header>
      <dl class="tr-wan-kv">
        <div><dt>Modo</dt><dd>${g.modo === 'dhcp' ? 'Roteador · DHCP' : esc(g.modo)}</dd></div>
        <div><dt>VLAN</dt><dd>${esc(g.vlan ?? '—')}</dd></div>
        <div><dt>Prioridade</dt><dd>${esc(g.prioridade ?? '—')}</dd></div>
        <div><dt>IP</dt><dd>${esc(g.ip || '—')}</dd></div>
      </dl>
      <footer class="tr-wan-lock"><i data-lucide="lock"></i>É por este serviço que o servidor fala com a ONU. A tela não deixa apagar nem trocar a VLAN dele: sem ele, só indo a campo.</footer>
    </article>`;
}

function tr069CardServico(s, i, lans, ed) {
  const modoTxt = (TR069_MODOS.find(m => m[0] === s.modo) || [null, 'Serviço'])[1];
  const funcao = s.funcao && s.funcao !== 'outro'
    ? (TR069_FUNCOES.find(f => f[0] === s.funcao) || [null, 'Serviço'])[1]
    : `${modoTxt}${s.vlan ? ' · VLAN ' + s.vlan : ''}`;
  const pppoe = s.modo !== 'pppoe' ? '' : `
    <div class="tr-wan-form tr-mt">
      <div class="form-group"><label>Usuário PPPoE</label><input data-srv-campo="usuario" value="${esc(s.usuario)}" ${tr069Dis(ed)}></div>
      <div class="form-group"><label>Senha PPPoE</label><input data-srv-campo="senha" type="password" placeholder="${s.id ? 'em branco = manter' : ''}" ${tr069Dis(ed)}></div>
    </div>`;
  const iptv = s.funcao !== 'iptv' ? '' : `
    <div class="tr-wan-form tr-mt">
      <div class="form-group"><label>VLAN de multicast</label><input data-srv-campo="mcast_vlan" inputmode="numeric" value="${esc(s.mcast_vlan)}" ${tr069Dis(ed)}></div>
      <div class="form-group"><label class="tr-check"><input type="checkbox" data-srv-campo="igmp" ${s.igmp ? 'checked' : ''} ${tr069Dis(ed)}> IGMP proxy</label></div>
    </div>`;
  return `
    <article class="tr-wan" data-tr069-srv="${i}">
      <header><div class="tr-wan-title"><span class="tr-wan-ico ico-green"><i data-lucide="${s.modo === 'bridge' ? 'cable' : 'globe'}"></i></span>
        <div><b>${esc(funcao)}</b><small>${s.id ? 'já existe na ONT' : 'novo'}</small></div></div>
        ${ed ? `<button class="secondary-action tr-small" data-tr069-srv-rem="${i}"><i data-lucide="trash-2"></i> Remover</button>` : ''}</header>
      <div class="tr-pad">
        <div class="tr-wan-form">
          <div class="form-group"><label>Função</label><select data-srv-campo="funcao" ${tr069Dis(ed)}>${TR069_FUNCOES.map(([v, t]) => `<option value="${v}" ${s.funcao === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
          <div class="form-group"><label>Modo</label><select data-srv-campo="modo" ${tr069Dis(ed)}>${TR069_MODOS.map(([v, t]) => `<option value="${v}" ${s.modo === v ? 'selected' : ''}>${t}</option>`).join('')}</select></div>
          <div class="form-group"><label>VLAN</label><input data-srv-campo="vlan" inputmode="numeric" value="${esc(s.vlan)}" ${tr069Dis(ed)}></div>
          <div class="form-group"><label>Prioridade 802.1p</label><select data-srv-campo="prioridade" ${tr069Dis(ed)}><option value="">sem prioridade</option>${[0, 1, 2, 3, 4, 5, 6, 7].map(n => `<option value="${n}" ${String(s.prioridade) === String(n) ? 'selected' : ''}>${n}</option>`).join('')}</select></div>
        </div>
        <div class="form-group tr-mt"><label>Portas LAN</label><div class="tr-pchips">${lans.map(p => `<button type="button" class="tr-pchip ${s.portas.includes(p) ? 'on' : ''}" data-srv-porta="${p}" aria-pressed="${s.portas.includes(p)}" ${tr069Dis(ed)}>${p}</button>`).join('')}</div></div>
        ${pppoe}${iptv}
      </div>
    </article>`;
}

function tr069RenderModo(previa = null) {
  const { d, gerencia, editavel, rascunho } = _tr069Modo;
  const lans = d.portas_lan || [];
  const motivo = (d.servicos || []).find(s => !s.gerencia && !s.editavel)?.motivo || 'Esta ONU está só para leitura.';
  const cards = rascunho.map((s, i) => tr069CardServico(s, i, lans, editavel)).join('');
  const cenarios = !editavel ? '' : `
    <div class="panel"><div class="tr-panel-head"><div><h3>Cenários prontos</h3><p>Preenche os serviços ao lado. Você revisa antes de aplicar.</p></div></div>
      <div class="tr-pad tr-cen-list">${TR069_CENARIOS.map(([k, ic, t, sub]) => `
        <button class="tr-cen ${_tr069Modo.cenario === k ? 'on' : ''}" data-tr069-cen="${k}"><span class="tr-wan-ico ico-blue"><i data-lucide="${ic}"></i></span>
          <span><b>${t}</b><small>${sub}</small></span></button>`).join('')}</div></div>`;
  const acaoPrevia = editavel
    ? '<button class="secondary-action" data-tr069-previa><i data-lucide="list-checks"></i> Ver o que muda</button>'
    : '<span class="tr-sub">Só leitura.</span>';
  document.getElementById('tr069DetalheBox').innerHTML = `
  <div class="tr-detail">
    <div class="page-heading">
      <div><p class="eyebrow">TR-069 · ${esc(tr069Titulo(d))} · ${esc(d.serial)}</p><h1>Modo de operação</h1>
        <p>Os serviços que a ONT tem por dentro: cada um sai para a OLT com sua VLAN, seu modo e as portas que atende.</p></div>
      <div class="page-heading-actions">
        <button class="secondary-action" data-tr069-voltar-onu><i data-lucide="arrow-left"></i> Voltar à ONU</button>
        ${editavel ? '<button class="primary-action" data-tr069-srv-novo><i data-lucide="plus"></i> Novo serviço</button>' : ''}
      </div>
    </div>
    <div class="tr-op-banner"><div class="tr-op-ico"><i data-lucide="layers"></i></div>
      <div><b>${esc(d.cenario?.nome || '—')}</b><p>${esc(d.cenario?.texto || '')}</p></div>
      <span class="tr-badge b-green">cenário atual</span></div>
    ${editavel ? '' : `<div class="tr-box tr-warn">${esc(motivo)}</div>`}
    <div class="tr-grid">
      <div class="tr-stack"><div class="panel">
        <div class="tr-panel-head"><div><h3>Serviços da ONT</h3><p>Edite à vontade: nada vai para a ONU até você aplicar.</p></div></div>
        <div class="tr-pad tr-wans">${tr069CardGerencia(gerencia)}${cards || '<span class="tr-sub">Nenhum serviço além da gerência.</span>'}</div>
      </div></div>
      <div class="tr-stack">
        ${cenarios}
        <div class="panel"><div class="tr-panel-head"><div><h3>O que vai mudar na ONU</h3><p>Prévia calculada pelo servidor a partir do que está na ONU agora.</p></div></div>
          <div class="tr-pad" id="tr069Previa">${previa || acaoPrevia}</div></div>
      </div>
    </div>
  </div>`;
  lucide.createIcons();
}

function tr069LerRascunho() {
  document.querySelectorAll('#tr069DetalheBox [data-tr069-srv]').forEach(card => {
    const s = _tr069Modo.rascunho[Number(card.dataset.tr069Srv)];
    card.querySelectorAll('[data-srv-campo]').forEach(el => {
      s[el.dataset.srvCampo] = el.type === 'checkbox' ? el.checked : el.value;
    });
    s.portas = [...card.querySelectorAll('.tr-pchip.on')].map(b => b.dataset.srvPorta);
  });
}

function tr069Payload() {
  return {
    servicos: _tr069Modo.rascunho.map(s => ({
      id: s.id, funcao: s.funcao, modo: s.modo, vlan: Number(s.vlan),
      prioridade: s.prioridade === '' ? null : Number(s.prioridade), portas: s.portas, nat: s.modo !== 'bridge',
      usuario: s.usuario, senha: s.senha, mcast_vlan: s.mcast_vlan ? Number(s.mcast_vlan) : null, igmp: !!s.igmp,
    })),
  };
}

function tr069AplicarCenario(chave) {
  const lans = _tr069Modo.d.portas_lan || [];
  const atuais = (_tr069Modo.d.servicos || []).filter(s => !s.gerencia);
  const vlanAtual = atuais.find(s => s.vlan)?.vlan || '';
  const modelos = {
    cameras_bridge: [{ funcao: 'cameras', modo: 'bridge', vlan: vlanAtual, portas: lans }],
    bridge_total: [{ funcao: 'outro', modo: 'bridge', vlan: vlanAtual, portas: lans }],
    internet_pppoe: [{ funcao: 'internet', modo: 'pppoe', vlan: '', portas: lans }],
    roteador_ipoe: [{ funcao: 'internet', modo: 'dhcp', vlan: '', portas: lans }],
    multisservico: [
      { funcao: 'internet', modo: 'pppoe', vlan: '', portas: lans.slice(0, 2) },
      { funcao: 'iptv', modo: 'bridge', vlan: 1334, portas: lans.slice(2, 3), mcast_vlan: 1334, igmp: true },
      { funcao: 'cameras', modo: 'bridge', vlan: vlanAtual, portas: lans.slice(3) },
    ],
  };
  // Reaproveita servico existente do mesmo tipo: menos remover/criar, menos tempo sem rede.
  const livres = [...atuais];
  _tr069Modo.rascunho = (modelos[chave] || []).map(m => {
    const tipo = m.modo === 'pppoe' ? 'ppp' : 'ip';
    const i = livres.findIndex(s => s.tipo === tipo);
    const reuso = i >= 0 ? livres.splice(i, 1)[0] : null;
    return tr069Rascunho({ ...m, id: reuso?.id || null, tipo });
  });
  _tr069Modo.cenario = chave;
  tr069RenderModo();
}

async function tr069Previa() {
  tr069LerRascunho();
  const alvo = document.getElementById('tr069Previa');
  alvo.innerHTML = '<span class="tr-sub">Calculando…</span>';
  const res = await api(`/api/tr069/devices/${encodeURIComponent(_tr069Serial)}/servicos/plano`, {
    method: 'POST', body: JSON.stringify(tr069Payload()) });
  const r = res ? await res.json() : null;
  if (!r || !r.ok) {
    alvo.innerHTML = `<div class="tr-box tr-erro-box">${esc(r?.error || 'Não foi possível calcular.')}</div>
      <button class="secondary-action tr-mt" data-tr069-previa>Recalcular</button>`;
    return;
  }
  const icone = { remover: ['del', 'minus'], editar: ['edit', 'pencil'], criar: ['add', 'plus'] };
  const passos = r.passos || [];
  alvo.innerHTML = `
    <ul class="tr-plan"><li class="keep"><i data-lucide="lock"></i>${esc(r.mantida)}</li>
      ${passos.map(p => `<li class="${icone[p.op][0]}"><i data-lucide="${icone[p.op][1]}"></i>${esc(p.texto)}</li>`).join('')
        || '<li class="keep">Nada muda: a ONT já está assim.</li>'}</ul>
    ${(r.avisos || []).map(a => `<div class="tr-box tr-warn tr-mt">${esc(a)}</div>`).join('')}
    <div class="page-heading-actions tr-mt"><button class="secondary-action" data-tr069-previa>Recalcular</button>
      ${passos.length ? '<button class="primary-action" data-tr069-aplicar-modo><i data-lucide="send"></i> Aplicar na ONU</button>' : ''}</div>`;
  lucide.createIcons();
}

async function tr069AplicarModo(botao) {
  tr069LerRascunho();
  botao.disabled = true;
  const alvo = document.getElementById('tr069Previa');
  const res = await api(`/api/tr069/devices/${encodeURIComponent(_tr069Serial)}/servicos`, {
    method: 'POST', body: JSON.stringify(tr069Payload()) });
  if (res && res.status === 403) { showToast('Seu perfil não pode alterar ONU.', true); botao.disabled = false; return; }
  const r = res ? await res.json() : null;
  if (!r || !r.ok) { showToast(r?.error || 'A ONU recusou.', true); botao.disabled = false; return; }
  if (!r.job) { showToast('Nada a mudar.'); return; }
  const total = (r.passos || []).length;
  for (let i = 0; i < 120; i++) {
    const j = await apiJson(`/api/tr069/jobs/${r.job}`, { cacheTtl: 0 });
    if (j && j.ok) {
      alvo.innerHTML = `<div class="tr-box">Aplicando na ONU: ${j.feitos.length} de ${total} passo(s)…</div>`;
      if (j.estado !== 'rodando') {
        if (j.estado === 'concluido') showToast('Modo de operação aplicado na ONU.');
        else showToast(`Parou no passo ${j.feitos.length + 1} de ${total}: ${j.erro}`, true);
        return tr069AbrirModo();
      }
    }
    await new Promise(ok => setTimeout(ok, 2500));
  }
  showToast('A ONU está demorando; veja o histórico da ONU em alguns minutos.', true);
}

document.addEventListener('click', ev => {
  const box = document.getElementById('tr069DetalheBox');
  if (!box || !box.contains(ev.target)) return;
  const t = ev.target.closest('button');
  if (!t) return;
  if (t.hasAttribute('data-tr069-modo')) return tr069AbrirModo();
  if (!_tr069Modo) return;
  if (t.hasAttribute('data-tr069-voltar-onu')) { _tr069Modo = null; return tr069AbrirDetalhe(_tr069Serial); }
  if (t.dataset.srvPorta) {
    const on = !t.classList.contains('on');
    t.classList.toggle('on', on);
    t.setAttribute('aria-pressed', String(on));
    return;
  }
  if (t.hasAttribute('data-tr069-srv-novo')) {
    tr069LerRascunho();
    _tr069Modo.rascunho.push(tr069Rascunho({ funcao: 'outro', modo: 'bridge', portas: [] }));
    return tr069RenderModo();
  }
  if (t.dataset.tr069SrvRem !== undefined) {
    tr069LerRascunho();
    _tr069Modo.rascunho.splice(Number(t.dataset.tr069SrvRem), 1);
    return tr069RenderModo();
  }
  if (t.dataset.tr069Cen) return tr069AplicarCenario(t.dataset.tr069Cen);
  if (t.hasAttribute('data-tr069-previa')) return tr069Previa();
  if (t.hasAttribute('data-tr069-aplicar-modo')) return tr069AplicarModo(t);
});

document.addEventListener('change', ev => {
  const card = ev.target.closest && ev.target.closest('#tr069DetalheBox [data-tr069-srv]');
  if (!card || !_tr069Modo) return;
  if (['modo', 'funcao'].includes(ev.target.dataset.srvCampo)) { tr069LerRascunho(); tr069RenderModo(); }
});

// --------------------------------------------------------------------------
// Ativar TR-069 numa ONU: pela OLT (FiberHome) ou pelo DHCP do conector.
// --------------------------------------------------------------------------
let _tr069Cand = [];

async function tr069AbrirAtivar() {
  const box = document.getElementById('tr069AtivarBox');
  if (!box) return;
  box.classList.remove('hidden');
  box.innerHTML = `<div class="tr-panel-head"><div><h3>Ativar TR-069</h3><p>Escolha a ONU. O SightOps sugere o caminho pelo fabricante da OLT; nada é enviado até você confirmar.</p></div>
    <button class="secondary-action tr-small" data-tr069-ativar-fechar>Fechar</button></div>
    <div class="tr-pad"><div class="tr-cand-filtros">
      <input class="tr-search" id="tr069CandBusca" placeholder="Buscar por serial, PON, ONU ou nome" aria-label="Buscar ONU para ativar">
      <select class="filter-select" id="tr069CandOlt" aria-label="OLT"><option value="">Todas as OLTs</option></select>
      <select class="filter-select" id="tr069CandSt" aria-label="Situacao"><option value="">Online e offline</option><option value="on">Só online</option></select>
    </div>
    <div id="tr069CandConta" class="tr-sub tr-mt"></div>
    <div id="tr069CandLista" class="tr-cand-lista tr-mt"><span class="tr-sub">Carregando ONUs sem TR-069…</span></div><div id="tr069AtivarPlano"></div></div>`;
  const r = await apiJson('/api/tr069/candidatas', { cacheTtl: 0 });
  _tr069Cand = r?.ok ? (r.onus || []) : [];
  const olts = [...new Set(_tr069Cand.map(o => o.olt || '—'))].sort();
  const sel = document.getElementById('tr069CandOlt');
  if (sel) sel.innerHTML = '<option value="">Todas as OLTs</option>' + olts.map(o => `<option>${esc(o)}</option>`).join('');
  if (!r?.ok) document.getElementById('tr069CandLista').innerHTML = `<span class="tr-erro">${esc(r?.error || 'Falha ao listar ONUs.')}</span>`;
  else tr069RenderCand();
}

function tr069RenderCand() {
  const alvo = document.getElementById('tr069CandLista');
  const q = (document.getElementById('tr069CandBusca')?.value || '').trim().toLowerCase();
  const olt = document.getElementById('tr069CandOlt')?.value || '';
  const soOn = document.getElementById('tr069CandSt')?.value === 'on';
  const filtradas = _tr069Cand.filter(o => (!olt || (o.olt || '—') === olt)
    && (!soOn || String(o.status_onu || '').toLowerCase() === 'active')
    && (!q || [o.serial, `${o.pon}/${o.onu_id}`, `onu ${o.onu_id}`, o.nome, o.modelo, o.olt].some(v => String(v ?? '').toLowerCase().includes(q))));
  const LIMITE = 100;
  const conta = document.getElementById('tr069CandConta');
  if (conta) conta.textContent = filtradas.length > LIMITE
    ? `${filtradas.length} ONUs sem TR-069 com esse filtro. Mostrando as ${LIMITE} primeiras: use a busca ou escolha a OLT.`
    : `${filtradas.length} ONU(s) sem TR-069 com esse filtro.`;
  alvo.innerHTML = filtradas.slice(0, LIMITE).map(o => {
    const on = String(o.status_onu || '').toLowerCase() === 'active';
    return `<button class="tr-cand" data-tr069-cand="${esc(o.serial)}"><b class="tr-serial">${esc(o.serial)}</b>
      <span>${esc(o.olt || '')} · PON ${esc(o.pon)} · ONU ${esc(o.onu_id)}${o.modelo ? ' · ' + esc(o.modelo) : ''}</span>
      <span class="tr-badge plain ${on ? 'b-green' : 'b-red'}">${on ? 'online' : esc(o.status_onu || 'offline')}</span></button>`;
  }).join('') || '<span class="tr-sub">Nenhuma ONU sem TR-069 com esse filtro.</span>';
}

async function tr069PlanoAtivar(serial) {
  const alvo = document.getElementById('tr069AtivarPlano');
  document.getElementById('tr069CandLista').innerHTML = '';
  alvo.innerHTML = '<span class="tr-sub">Preparando…</span>';
  const p = await apiJson(`/api/tr069/ativar/${encodeURIComponent(serial)}`, { cacheTtl: 0 });
  if (!p?.ok) { alvo.innerHTML = `<div class="tr-box tr-erro-box">${esc(p?.error || 'Não foi possível preparar.')}</div>`; return; }
  const offline = String(p.status_onu || '').toLowerCase() !== 'active';
  alvo.innerHTML = `
    <div class="tr-ativ-head"><b class="tr-serial">${esc(p.serial)}</b> · ${esc(p.modelo || '')} · ${esc(p.olt || '')} PON ${esc(p.pon)} ONU ${esc(p.onu_id)}</div>
    ${offline ? '<div class="tr-box tr-warn">A ONU está offline na OLT: a configuração fica gravada, mas o 1º contato só acontece quando ela voltar.</div>' : ''}
    <label class="tr-choice ${p.metodo_sugerido === 'olt' ? 'on' : ''}" for="tr069MetOlt">
      <input type="radio" name="tr069Metodo" id="tr069MetOlt" value="olt" ${p.metodo_sugerido === 'olt' ? 'checked' : ''} ${p.pela_olt_disponivel ? '' : 'disabled'}>
      <span><b>Pela OLT</b><small>${!p.pela_olt_disponivel ? 'Esta OLT ainda não faz isso pelo SightOps.'
        : p.vlan_gerencia ? `A OLT põe na ONU o serviço da VLAN ${esc(p.vlan_gerencia)} (gerência). A ONU pega IP por DHCP e acha o servidor sozinha pela opção 43.`
        : 'O SightOps manda o endereço do servidor para a ONU através da OLT, confere e salva.'}</small></span></label>
    <label class="tr-choice ${p.metodo_sugerido === 'dhcp' ? 'on' : ''}" for="tr069MetDhcp">
      <input type="radio" name="tr069Metodo" id="tr069MetDhcp" value="dhcp" ${p.metodo_sugerido === 'dhcp' ? 'checked' : ''}>
      <span><b>Pelo DHCP do conector</b><small>O MikroTik do cliente entrega o endereço na opção 43. Serve para qualquer fabricante; você cola o script no roteador.</small></span></label>
    <div id="tr069MetOltBox" class="${p.metodo_sugerido === 'olt' ? '' : 'hidden'}">
      <p class="tr-sub tr-mt">O que vai para a OLT (uma linha, só nesta ONU):</p><pre class="tr-pre">${esc(p.comando_olt || '')}</pre></div>
    <div id="tr069MetDhcpBox" class="${p.metodo_sugerido === 'dhcp' ? '' : 'hidden'} tr-mt">
      <div class="form-group"><label for="tr069RedeGer">Rede de gerência das ONUs no MikroTik</label>
        <input id="tr069RedeGer" placeholder="ex.: 172.18.1.0/24"></div></div>
    <div class="tr-box tr-mt">A ONU precisa ter IP de gerência (uma WAN com DHCP numa VLAN que chegue ao MikroTik, como a VLAN 7 da SIERRA). Servidor desta ONU: <span class="monospace">${esc(p.servidor)}</span></div>
    <div class="page-heading-actions tr-mt"><button class="secondary-action" data-tr069-ativar-voltar>Escolher outra ONU</button>
      <button class="primary-action" data-tr069-ativar-ir="${esc(p.serial)}"><i data-lucide="radio-tower"></i> Ativar nesta ONU</button></div>`;
  lucide.createIcons();
}

async function tr069Ativar(serial, botao) {
  const metodo = document.querySelector('input[name="tr069Metodo"]:checked')?.value || '';
  const rede = document.getElementById('tr069RedeGer')?.value || '';
  botao.disabled = true;
  showToast(metodo === 'olt' ? 'Configurando na OLT…' : 'Gerando o script…');
  const res = await api('/api/tr069/ativar', { method: 'POST', body: JSON.stringify({ serial, metodo, rede_gerencia: rede }) });
  if (res && res.status === 403) { showToast('Seu perfil não pode alterar ONU.', true); botao.disabled = false; return; }
  const r = res ? await res.json() : null;
  botao.disabled = false;
  const alvo = document.getElementById('tr069AtivarPlano');
  if (!r?.ok) { showToast(r?.error || 'Não foi possível ativar.', true); return; }
  if (r.metodo === 'dhcp') {
    alvo.innerHTML = `<div class="tr-box">Cole no terminal do MikroTik do cliente. A ONU aparece como <b>Aguardando 1º contato</b> e sai sozinha desse estado quando falar com o servidor.</div>
      <pre class="tr-pre tr-mt" id="tr069Script">${esc(r.script)}</pre>
      <div class="page-heading-actions tr-mt"><button class="primary-action" data-tr069-copiar><i data-lucide="copy"></i> Copiar script</button></div>`;
    lucide.createIcons();
  } else {
    showToast('TR-069 ligado na OLT. A ONU aparece assim que fizer o 1º contato.');
    document.getElementById('tr069AtivarBox').classList.add('hidden');
  }
  loadTr069(true);
}

async function tr069CarregarAuto() {
  const el = document.querySelector('[data-tr069-auto]');
  if (!el) return;
  const c = await apiJson('/api/tr069/config', { cacheTtl: 0 });
  if (c) el.setAttribute('aria-checked', c.auto_ativar ? 'true' : 'false');
}

document.addEventListener('click', async ev => {
  const view = document.getElementById('viewDeployTr069');
  if (!view || !view.contains(ev.target)) return;
  const t = ev.target.closest('button, label.tr-choice');
  if (!t) return;
  if (t.id === 'btnTr069Ativar') return tr069AbrirAtivar();
  if (t.hasAttribute('data-tr069-ativar-fechar')) return document.getElementById('tr069AtivarBox').classList.add('hidden');
  if (t.hasAttribute('data-tr069-ativar-voltar')) { document.getElementById('tr069AtivarPlano').innerHTML = ''; return tr069RenderCand(); }
  if (t.dataset.tr069Cand) return tr069PlanoAtivar(t.dataset.tr069Cand);
  if (t.dataset.tr069AtivarIr) return tr069Ativar(t.dataset.tr069AtivarIr, t);
  if (t.hasAttribute('data-tr069-copiar')) {
    const txt = document.getElementById('tr069Script')?.textContent || '';
    try { await navigator.clipboard.writeText(txt); showToast('Script copiado.'); }
    catch { const r = document.createRange(); r.selectNodeContents(document.getElementById('tr069Script')); getSelection().removeAllRanges(); getSelection().addRange(r); showToast('Selecionei o script: use Ctrl+C.'); }
    return;
  }
  if (t.hasAttribute('data-tr069-dhcp')) {
    const ligar = t.getAttribute('data-tr069-dhcp') === '1';
    // Desligar o DHCP numa casa onde ele e o unico servidor deixa o cliente
    // sem endereco. Confirma antes, com o efeito escrito.
    if (!ligar && !confirm('Desligar o DHCP da LAN desta ONU? Quem estiver atras dela so pegara endereco de outro servidor da rede.')) return;
    // Reaproveita o caminho que ja existe: trata 403, distingue fila de
    // aplicado e redesenha o detalhe no fim.
    await tr069Executar('dhcp_lan', { habilitar: ligar }, t);
    return;
  }
  if (t.hasAttribute('data-tr069-salvar-senhaweb')) {
    const campo = document.getElementById('tr069SenhaWeb');
    const v = campo?.value || '';
    if (v && v.length < 6) { showToast('A senha precisa de pelo menos 6 caracteres.', true); return; }
    const res = await api('/api/tr069/config', { method: 'POST', body: JSON.stringify({ senha_web: v }) });
    const r = res ? await res.json() : null;
    // Limpa o campo mesmo quando da certo: senha nao fica em tela.
    if (campo) campo.value = '';
    showToast(r?.ok
      ? (r.tem_senha_web
          ? 'Senha salva. Vai sendo aplicada nas ONUs nos proximos ciclos.'
          : 'Senha padrao removida. As ONUs ficam como estao.')
      : (r?.error || 'So o administrador muda isso.'), !r?.ok);
    // Redesenha para o texto passar de "nao definida" para "definida".
    if (r?.ok) loadTr069Config();
    return;
  }
  if (t.hasAttribute('data-tr069-salvar-vlan')) {
    const v = document.getElementById('tr069VlanGer')?.value.trim();
    const res = await api('/api/tr069/config', { method: 'POST', body: JSON.stringify({ vlan_gerencia: v ? Number(v) : null }) });
    const r = res ? await res.json() : null;
    showToast(r?.ok ? (r.vlan_gerencia ? `VLAN de gerência: ${r.vlan_gerencia}.` : 'VLAN de gerência removida.') : (r?.error || 'Só o administrador muda isso.'), !r?.ok);
    return;
  }
  if (t.hasAttribute('data-tr069-auto')) {
    const ligar = t.getAttribute('aria-checked') !== 'true';
    const res = await api('/api/tr069/config', { method: 'POST', body: JSON.stringify({ auto_ativar: ligar }) });
    const r = res ? await res.json() : null;
    if (r?.ok) { t.setAttribute('aria-checked', String(!!r.auto_ativar)); showToast(r.auto_ativar ? 'ONU autorizada pelo SightOps já sai com TR-069.' : 'Ativação automática desligada.'); }
    else showToast(r?.error || 'Só o administrador muda isso.', true);
  }
});

document.addEventListener('change', ev => {
  if (ev.target.name === 'tr069Metodo') {
    const olt = ev.target.value === 'olt';
    document.getElementById('tr069MetOltBox')?.classList.toggle('hidden', !olt);
    document.getElementById('tr069MetDhcpBox')?.classList.toggle('hidden', olt);
    document.querySelectorAll('label.tr-choice').forEach(l => l.classList.toggle('on', l.contains(ev.target)));
  }
});
document.addEventListener('input', ev => { if (ev.target.id === 'tr069CandBusca') tr069RenderCand(); });
document.addEventListener('change', ev => { if (['tr069CandOlt', 'tr069CandSt'].includes(ev.target.id)) tr069RenderCand(); });
