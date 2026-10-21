// Configuracoes > Notificacoes: grupos do Telegram (destinos) e quem recebe
// cada site. Rotas em /api/monitoring/notificacoes (so administrador).
// Janela de grupo: fecha so por X/Cancelar/Esc (clicar fora perdia o que se
// digitou).

const _nt = { dados: null, marcados: new Set(), busca: '', filtro: 'todos', codigo: null, timer: null };

const NT_EVENTOS_ORDEM = ['queda', 'volta', 'sem_imagem', 'sinal_onu', 'alarme', 'panico', 'acesso'];

function ntGrupoPorId(id) { return (_nt.dados?.grupos || []).find(g => g.id === id); }

// Grupos que recebem o site: os que o listam; senao, os padrao.
function ntGruposDoSite(site) {
  const chave = String(site || '').toUpperCase();
  const ativos = (_nt.dados?.grupos || []).filter(g => g.ativo);
  const proprios = ativos.filter(g => (g.sites || []).includes(chave));
  return proprios.length ? { proprios, padrao: false } : { proprios: ativos.filter(g => g.padrao), padrao: true };
}

function ntResumoEventos(lista) {
  const evs = _nt.dados?.eventos || {};
  const curtos = { queda: 'queda', volta: 'volta', sem_imagem: 'sem imagem', sinal_onu: 'sinal ONU', alarme: 'alarme', panico: 'pânico', acesso: 'passagens' };
  const tem = NT_EVENTOS_ORDEM.filter(e => (lista || []).includes(e) && evs[e]);
  return tem.length === NT_EVENTOS_ORDEM.length ? 'tudo' : tem.map(e => curtos[e]).join(' · ') || 'nada';
}

function ntQuando(iso) {
  return typeof cfgMinutos === 'function' && iso ? cfgMinutos(iso) : '—';
}

async function ntCarregar() {
  const box = document.getElementById('ntConteudo');
  if (!box) return;
  try {
    const res = await api('/api/monitoring/notificacoes');
    const data = await res?.json().catch(() => ({}));
    if (!res?.ok) {
      box.innerHTML = `<div class="so-note"><i data-lucide="lock"></i><span>${esc(data?.detail || 'Só administradores configuram as notificações.')}</span></div>`;
      lucide.createIcons();
      return;
    }
    _nt.dados = data;
    ntRender();
  } catch (e) {
    box.innerHTML = `<p class="text-muted">Não foi possível carregar: ${esc(e?.message || e)}</p>`;
  }
}

function ntRender() {
  const d = _nt.dados;
  if (!d) return;
  const grupos = d.grupos || [];
  const ativos = grupos.filter(g => g.ativo);
  const sites = d.sites || [];
  const comProprio = sites.filter(s => !ntGruposDoSite(s.site).padrao).length;
  const semNada = sites.filter(s => !ntGruposDoSite(s.site).proprios.length).length;
  const r = d.resumo || {};
  setText('settingsNavNotifSub', ativos.length ? `${ativos.length} grupo${ativos.length === 1 ? '' : 's'} · ${comProprio} de ${sites.length} sites` : 'Nenhum grupo ligado');

  const robo = d.bot_easy || {};
  const avisoRobo = robo.configurado ? '' : `<div class="so-note amber"><i data-lucide="bot"></i><span>${d.dono_plataforma
    ? 'O robô do SightOps ainda não foi configurado. Configure abaixo para os clientes vincularem grupos pelo código.'
    : 'O robô do SightOps ainda não foi ligado pela Easy. Enquanto isso, dá para usar um robô próprio (avançado).'}</span></div>`;
  const caixaRobo = d.dono_plataforma ? `<details class="nt-robo" ${robo.configurado ? '' : 'open'}>
      <summary><i data-lucide="bot"></i> Robô do SightOps <small>${robo.configurado ? `@${esc(robo.username)} · só a Easy vê isto` : 'não configurado · só a Easy vê isto'}</small></summary>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="ntRoboToken">Token do robô (BotFather)</label><input id="ntRoboToken" type="password" autocomplete="off" placeholder="${robo.configurado ? 'deixe vazio para manter' : '123456:ABC…'}"></div>
        <div class="form-group" style="margin:0"><label for="ntRoboUrl">Endereço do SightOps (botão nos avisos)</label><input id="ntRoboUrl" value="${esc(robo.url_publica || '')}" placeholder="https://sightops.easytecnologias.com.br/v2"></div>
      </div>
      <div class="page-heading-actions" style="justify-content:flex-start;margin-top:10px"><button class="primary-action" type="button" data-nt="salvar-robo"><i data-lucide="save"></i> Salvar robô</button></div>
    </details>` : '';

  const kpi = (rot, val, sub, cor) => `<div class="nt-kpi"><span>${esc(rot)}</span><strong>${val}</strong><small class="${cor || ''}">${esc(sub)}</small></div>`;
  const kpis = [
    kpi('Grupos ligados', licNum(ativos.length), grupos.some(g => g.ultimo_erro && g.ativo) ? 'algum com erro de envio' : (ativos.length ? 'todos respondendo' : 'nenhum ainda'), grupos.some(g => g.ultimo_erro && g.ativo) ? 'amber' : 'green'),
    kpi('Sites com grupo próprio', `${licNum(comProprio)} <em>de ${licNum(sites.length)}</em>`, semNada ? `${semNada} sem ninguém recebendo` : `${sites.length - comProprio} usam o grupo padrão`, semNada ? 'red' : ''),
    kpi('Avisos nas últimas 24 h', licNum(r.avisos_24h || 0), r.agrupados_24h ? `${licNum(r.agrupados_24h)} quedas juntadas em mensagens` : 'quedas do mesmo site saem juntas'),
    kpi('Falhas de envio', licNum(r.falhas_24h || 0), 'nas últimas 24 h', r.falhas_24h ? 'red' : ''),
  ].join('');

  const linhaGrupo = g => {
    const qtd = (g.sites || []).length;
    const alcance = g.padrao ? (qtd ? `padrão + ${qtd} site${qtd === 1 ? '' : 's'}` : 'sites sem grupo próprio') : `${qtd} site${qtd === 1 ? '' : 's'}`;
    const estado = !g.ativo ? '<span class="nt-dot off"></span>desligado'
      : g.ultimo_erro ? `<span class="nt-dot err"></span>${esc(String(g.ultimo_erro).replace(/^\S+\s/, ''))}`
      : g.silencio?.ativo ? `<span class="nt-dot off"></span>silêncio ${esc(g.silencio.de)}–${esc(g.silencio.ate)}`
      : `<span class="nt-dot ok"></span>${g.ultimo_envio ? `último aviso ${esc(ntQuando(g.ultimo_envio))}` : 'ainda sem aviso'}`;
    return `<button type="button" class="nt-grupo" data-nt="editar" data-id="${esc(g.id)}">
      <span class="nt-ico"><i data-lucide="send"></i></span>
      <span class="nt-grupo-txt"><span class="nt-grupo-nome">${esc(g.nome)}${g.padrao ? '<span class="nt-tag">padrão</span>' : ''}${g.bot === 'proprio' ? '<span class="nt-tag gray">robô próprio</span>' : ''}</span>
        <small>${esc(alcance)} · ${esc(ntResumoEventos(g.eventos))}</small>
        <small class="nt-estado">${estado}</small></span></button>`;
  };

  const q = _nt.busca.trim().toUpperCase();
  const lista = sites.filter(s => !q || String(s.site).toUpperCase().includes(q))
    .filter(s => _nt.filtro === 'todos' || (_nt.filtro === 'sem' && ntGruposDoSite(s.site).padrao));
  const opcoesGrupo = grupos.map(g => `<option value="${esc(g.id)}">${esc(g.nome)}</option>`).join('');
  const linhaSite = s => {
    const dest = ntGruposDoSite(s.site);
    const chips = dest.proprios.length
      ? dest.proprios.map(g => `<span class="nt-chip ${dest.padrao ? 'padrao' : ''}">${esc(g.nome)}${dest.padrao ? ' (padrão)' : ''}</span>`).join('')
      : '<span class="nt-chip vazio">ninguém recebe</span>';
    const evs = [...new Set(dest.proprios.flatMap(g => g.eventos || []))];
    const marcado = _nt.marcados.has(s.site);
    return `<tr class="${marcado ? 'nt-sel' : ''}">
      <td><input type="checkbox" data-nt-site="${esc(s.site)}" ${marcado ? 'checked' : ''} aria-label="Marcar ${esc(s.site)}"></td>
      <td class="nt-site">${esc(s.site)}</td>
      <td class="text-muted">${licNum(s.equipamentos || 0)}</td>
      <td><span class="nt-chips">${chips}</span></td>
      <td class="text-muted">${esc(dest.proprios.length ? ntResumoEventos(evs) : '—')}</td>
      <td><button type="button" class="ghost-action" data-nt="site" data-site="${esc(s.site)}" aria-label="Escolher grupos de ${esc(s.site)}"><i data-lucide="sliders-horizontal"></i></button></td></tr>`;
  };

  document.getElementById('ntConteudo').innerHTML = `
    ${avisoRobo}${caixaRobo}
    <div class="nt-kpis">${kpis}</div>
    <div class="nt-cols">
      <section class="nt-col-grupos" aria-label="Grupos do Telegram">
        <header><h3>Grupos do Telegram</h3><p>Para onde os avisos podem ir</p></header>
        <div class="nt-grupos">${grupos.map(linhaGrupo).join('') || '<p class="text-muted" style="padding:10px">Nenhum grupo ainda. Vincule o primeiro: ele vira o padrão e recebe todos os sites.</p>'}</div>
        <button type="button" class="nt-mais" data-nt="vincular">+ Vincular grupo</button>
      </section>
      <section class="nt-col-sites" aria-label="Sites">
        <header class="nt-sites-head">
          <div><h3>Sites</h3><p>Cada site manda para os grupos dele. Marque vários para mudar de uma vez.</p></div>
          <div class="nt-filtros">
            <label class="nt-busca"><i data-lucide="search"></i><input id="ntBusca" type="search" placeholder="Buscar site" aria-label="Buscar site" value="${esc(_nt.busca)}"></label>
            <button type="button" class="nt-filtro ${_nt.filtro === 'todos' ? 'on' : ''}" data-nt="filtro" data-f="todos">Todos ${licNum(sites.length)}</button>
            <button type="button" class="nt-filtro ${_nt.filtro === 'sem' ? 'on' : ''}" data-nt="filtro" data-f="sem">Sem grupo próprio ${licNum(sites.length - comProprio)}</button>
          </div>
        </header>
        ${_nt.marcados.size && grupos.length ? `<div class="nt-lote"><strong>${_nt.marcados.size} site${_nt.marcados.size === 1 ? '' : 's'} marcado${_nt.marcados.size === 1 ? '' : 's'}</strong>
          <select id="ntLoteModo" aria-label="O que fazer"><option value="adicionar">mandar também para</option><option value="tirar">parar de mandar para</option></select>
          <select id="ntLoteGrupo" aria-label="Grupo">${opcoesGrupo}</select>
          <button type="button" class="primary-action" data-nt="lote">Aplicar</button>
          <button type="button" class="ghost-action" data-nt="limpar">Desmarcar</button></div>` : ''}
        <div class="table-wrap"><table class="data-table nt-tabela">
          <thead><tr><th style="width:34px"><input type="checkbox" data-nt="todos" aria-label="Marcar todos"></th><th>Site</th><th>Equip.</th><th>Grupos que recebem</th><th>O que avisa</th><th style="width:48px"></th></tr></thead>
          <tbody>${lista.map(linhaSite).join('') || '<tr class="empty-row"><td colspan="6">Nenhum site com esse filtro.</td></tr>'}</tbody></table></div>
        <footer class="nt-rodape">Mostrando ${licNum(lista.length)} de ${licNum(sites.length)} sites · site sem grupo próprio usa o grupo padrão</footer>
      </section>
    </div>`;
  lucide.createIcons();
}

// ------------------------------------------------------------- janela do grupo (vincular / editar)

function ntFecharJanela() {
  clearInterval(_nt.timer);
  _nt.timer = null;
  _nt.codigo = null;
  document.getElementById('ntJanela')?.remove();
  document.removeEventListener('keydown', ntEsc, true);
}

function ntEsc(e) { if (e.key === 'Escape') { e.stopPropagation(); ntFecharJanela(); } }

function ntFormGrupo(g) {
  const d = _nt.dados || {};
  const evs = d.eventos || {};
  const tipos = d.tipos || {};
  const sel = new Set(g.eventos || ['queda', 'volta', 'sem_imagem', 'alarme', 'panico']);
  const tsel = new Set(g.tipos || Object.keys(tipos));
  const sitesDoGrupo = new Set(g.sites || []);
  const sil = g.silencio || { ativo: false, de: '22:00', ate: '06:00' };
  return `
    <div class="form-group"><label for="ntNome">Nome que aparece no SightOps</label><input id="ntNome" maxlength="80" value="${esc(g.nome || '')}"></div>
    <div class="form-group"><span class="nt-rot">Sites que este grupo recebe</span>
      <div class="nt-sites-escolha">${(d.sites || []).map(s => `<label class="nt-pill"><input type="checkbox" data-nt-gsite="${esc(String(s.site).toUpperCase())}" ${sitesDoGrupo.has(String(s.site).toUpperCase()) ? 'checked' : ''}><span>${esc(s.site)}</span></label>`).join('') || '<span class="text-muted">Nenhum site cadastrado.</span>'}</div>
      <label class="nt-check"><input type="checkbox" id="ntPadrao" ${g.padrao ? 'checked' : ''}> Grupo padrão: recebe também os sites que não têm grupo próprio</label>
    </div>
    <fieldset class="nt-box"><legend>O que avisar</legend>
      <div class="nt-grid2">${NT_EVENTOS_ORDEM.filter(e => evs[e]).map(e => `<label class="nt-check"><input type="checkbox" data-nt-ev="${e}" ${sel.has(e) ? 'checked' : ''}> ${esc(evs[e])}</label>`).join('')}</div>
      <div class="nt-tipos"><span class="text-muted">Equipamentos:</span>${Object.entries(tipos).map(([k, v]) => `<label class="nt-pill"><input type="checkbox" data-nt-tipo="${esc(k)}" ${tsel.has(k) ? 'checked' : ''}><span>${esc(v)}</span></label>`).join('')}</div>
    </fieldset>
    <fieldset class="nt-box"><legend>Para não virar barulho</legend>
      <label class="nt-check"><input type="checkbox" id="ntJuntar" ${g.juntar !== false ? 'checked' : ''}> Juntar quedas do mesmo site em uma mensagem só</label>
      <label class="nt-check"><input type="checkbox" id="ntSilencio" ${sil.ativo ? 'checked' : ''}> Silêncio das <input type="time" id="ntSilDe" value="${esc(sil.de || '22:00')}" aria-label="Início do silêncio"> às <input type="time" id="ntSilAte" value="${esc(sil.ate || '06:00')}" aria-label="Fim do silêncio">, menos quando cai o site inteiro e alerta de pânico</label>
      <label class="nt-check"><input type="checkbox" id="ntAtivo" ${g.ativo !== false ? 'checked' : ''}> Grupo ligado</label>
      <p class="text-muted" style="margin:4px 0 0;font-size:12px">Quantas falhas seguidas até avisar fica em Alarmes. O que acontecer no silêncio e continuar assim sai quando ele acaba.</p>
    </fieldset>
    <details class="nt-avancado" ${g.bot === 'proprio' ? 'open' : ''}><summary>Robô próprio do cliente (avançado)</summary>
      <label class="nt-check"><input type="checkbox" id="ntBotProprio" ${g.bot === 'proprio' ? 'checked' : ''}> Mandar por um robô do próprio cliente</label>
      <div class="form-row">
        <div class="form-group" style="margin:0"><label for="ntChat">Número do grupo (chat id)</label><input id="ntChat" value="${esc(g.chat_id || '')}" placeholder="-1001234567890"></div>
        <div class="form-group" style="margin:0"><label for="ntTokenProprio">Token do robô próprio</label><input id="ntTokenProprio" type="password" autocomplete="off" placeholder="${d.bot_proprio ? 'deixe vazio para manter' : '123456:ABC…'}"></div>
      </div>
    </details>
    <p id="ntErro" class="login-error" hidden></p>`;
}

function ntAbrirJanela(titulo, corpo, rodape) {
  ntFecharJanela();
  const wrap = document.createElement('div');
  wrap.id = 'ntJanela';
  wrap.className = 'nt-backdrop';
  wrap.innerHTML = `<aside class="nt-drawer" role="dialog" aria-modal="true" aria-labelledby="ntJanelaTitulo">
    <header><div><p class="eyebrow">Notificações</p><h2 id="ntJanelaTitulo">${esc(titulo)}</h2></div>
      <button type="button" class="ghost-action" data-nt="fechar" aria-label="Fechar"><i data-lucide="x"></i></button></header>
    <div class="nt-drawer-corpo">${corpo}</div>
    <footer>${rodape}</footer></aside>`;
  document.body.appendChild(wrap);
  document.addEventListener('keydown', ntEsc, true);
  lucide.createIcons();
  return wrap;
}

function ntRodapeGrupo(g) {
  return `${g.id ? `<button type="button" class="secondary-action" data-nt="testar" data-id="${esc(g.id)}"><i data-lucide="send"></i> Enviar teste</button>
    <button type="button" class="ghost-action nt-excluir" data-nt="excluir" data-id="${esc(g.id)}"><i data-lucide="trash-2"></i> Excluir</button>` : ''}
    <span style="flex:1"></span>
    <button type="button" class="secondary-action" data-nt="fechar">Cancelar</button>
    <button type="button" class="primary-action" data-nt="salvar" data-id="${esc(g.id || '')}"><i data-lucide="save"></i> Salvar grupo</button>`;
}

function ntEditar(id) {
  const g = ntGrupoPorId(id);
  if (!g) return;
  ntAbrirJanela(g.nome, ntFormGrupo(g), ntRodapeGrupo(g));
}

async function ntVincular() {
  const d = _nt.dados || {};
  if (!d.bot_easy?.configurado) {
    // Sem o robo do SightOps: grupo com robo proprio (numero do grupo + token).
    ntAbrirJanela('Novo grupo do Telegram', ntFormGrupo({ bot: 'proprio', padrao: !(d.grupos || []).length }), ntRodapeGrupo({}));
    return;
  }
  const res = await api('/api/monitoring/notificacoes/vincular', { method: 'POST', body: '{}' });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok) { showToast(data?.detail || 'Não foi possível gerar o código.', true); return; }
  _nt.codigo = data.codigo;
  const passos = `<ol class="nt-passos">
      <li><span>1</span><div><strong>Adicione o robô do SightOps no grupo</strong>
        <div class="nt-copiar"><code>@${esc(data.bot_username || '')}</code><button type="button" class="secondary-action" data-nt="copiar" data-txt="@${esc(data.bot_username || '')}">Copiar</button></div></div></li>
      <li><span>2</span><div><strong>No grupo, mande esta mensagem</strong>
        <div class="nt-copiar"><code class="nt-codigo">/vincular ${esc(data.codigo)}</code><button type="button" class="secondary-action" data-nt="copiar" data-txt="/vincular ${esc(data.codigo)}">Copiar</button></div>
        <small class="text-muted">O código vale 10 minutos e só serve para este cliente.</small></div></li>
      <li><span>3</span><div id="ntVincStatus" class="nt-aguardando"><strong>Aguardando o grupo…</strong><small>Esta janela atualiza sozinha.</small></div></li>
    </ol>`;
  ntAbrirJanela('Vincular grupo do Telegram', passos, '<span style="flex:1"></span><button type="button" class="secondary-action" data-nt="fechar">Cancelar</button>');
  _nt.timer = setInterval(ntConferirCodigo, 3000);
}

async function ntConferirCodigo() {
  if (!_nt.codigo) return;
  const data = await apiJson(`/api/monitoring/notificacoes/vincular/${encodeURIComponent(_nt.codigo)}`, { forceRefresh: true }).catch(() => null);
  const st = data?.status;
  const box = document.getElementById('ntVincStatus');
  if (st === 'vinculado' && data.grupo?.id) {
    clearInterval(_nt.timer);
    _nt.timer = null;
    _nt.codigo = null;
    showToast(`Grupo "${data.grupo.nome}" vinculado.`);
    await ntCarregar();
    ntEditar(data.grupo.id); // escolhe sites e avisos na hora
  } else if (st === 'expirado' || st === 'invalido') {
    clearInterval(_nt.timer);
    if (box) box.innerHTML = '<strong>O código venceu.</strong><small>Feche e gere outro.</small>';
  }
}

function ntLerForm() {
  const v = id => document.getElementById(id);
  const proprio = !!v('ntBotProprio')?.checked;
  const payload = {
    nome: v('ntNome')?.value.trim() || '',
    padrao: !!v('ntPadrao')?.checked,
    ativo: !!v('ntAtivo')?.checked,
    juntar: !!v('ntJuntar')?.checked,
    sites: [...document.querySelectorAll('[data-nt-gsite]:checked')].map(c => c.dataset.ntGsite),
    eventos: [...document.querySelectorAll('[data-nt-ev]:checked')].map(c => c.dataset.ntEv),
    tipos: [...document.querySelectorAll('[data-nt-tipo]:checked')].map(c => c.dataset.ntTipo),
    silencio: { ativo: !!v('ntSilencio')?.checked, de: v('ntSilDe')?.value || '22:00', ate: v('ntSilAte')?.value || '06:00' },
    bot: proprio ? 'proprio' : 'easy',
    chat_id: v('ntChat')?.value.trim() || '',
  };
  const tok = v('ntTokenProprio')?.value.trim();
  if (tok) payload.bot_proprio_token = tok;
  return payload;
}

async function ntSalvar(id) {
  const erro = document.getElementById('ntErro');
  const payload = ntLerForm();
  if (id) payload.id = id;
  if (!payload.eventos.length) { erro.textContent = 'Marque pelo menos um aviso.'; erro.hidden = false; return; }
  const res = await api('/api/monitoring/notificacoes/grupos', { method: 'POST', body: JSON.stringify(payload) });
  const data = await res?.json().catch(() => ({}));
  if (!res?.ok) { erro.textContent = data?.detail || 'Não foi possível salvar.'; erro.hidden = false; return; }
  showToast('Grupo salvo.');
  ntFecharJanela();
  await ntCarregar();
}

// Site: escolher os grupos que o recebem (atalho para a mudanca em lote de 1 site).
function ntEditarSite(site) {
  const grupos = _nt.dados?.grupos || [];
  const chave = String(site).toUpperCase();
  const corpo = grupos.length ? `<p class="text-muted" style="margin:0 0 10px">Marque os grupos que recebem os avisos de <strong>${esc(site)}</strong>. Sem nenhum marcado, vale o grupo padrão.</p>
    ${grupos.map(g => `<label class="nt-check nt-linha"><input type="checkbox" data-nt-sg="${esc(g.id)}" ${(g.sites || []).includes(chave) ? 'checked' : ''}> <strong>${esc(g.nome)}</strong>${g.padrao ? ' <span class="nt-tag">padrão</span>' : ''} <small class="text-muted">${esc(ntResumoEventos(g.eventos))}</small></label>`).join('')}`
    : '<p class="text-muted">Vincule um grupo primeiro.</p>';
  ntAbrirJanela(site, corpo, `<span style="flex:1"></span><button type="button" class="secondary-action" data-nt="fechar">Cancelar</button>
    ${grupos.length ? `<button type="button" class="primary-action" data-nt="salvar-site" data-site="${esc(site)}"><i data-lucide="save"></i> Salvar</button>` : ''}`);
}

async function ntSalvarSite(site) {
  const chave = String(site).toUpperCase();
  const pedidos = [];
  document.querySelectorAll('[data-nt-sg]').forEach(c => {
    const g = ntGrupoPorId(c.dataset.ntSg);
    const tem = (g?.sites || []).includes(chave);
    if (c.checked !== tem) pedidos.push(api(`/api/monitoring/notificacoes/grupos/${encodeURIComponent(g.id)}/sites`, { method: 'POST', body: JSON.stringify({ sites: [chave], modo: c.checked ? 'adicionar' : 'tirar' }) }));
  });
  const res = await Promise.all(pedidos);
  if (res.some(r => !r?.ok)) showToast('Algum grupo não foi atualizado.', true); else showToast('Site atualizado.');
  ntFecharJanela();
  await ntCarregar();
}

async function ntAcao(btn) {
  const acao = btn.dataset.nt;
  if (acao === 'fechar') return ntFecharJanela();
  if (acao === 'vincular') return ntVincular();
  if (acao === 'editar') return ntEditar(btn.dataset.id);
  if (acao === 'salvar') return ntSalvar(btn.dataset.id);
  if (acao === 'site') return ntEditarSite(btn.dataset.site);
  if (acao === 'salvar-site') return ntSalvarSite(btn.dataset.site);
  if (acao === 'filtro') { _nt.filtro = btn.dataset.f; return ntRender(); }
  if (acao === 'limpar') { _nt.marcados.clear(); return ntRender(); }
  if (acao === 'copiar') { try { await navigator.clipboard.writeText(btn.dataset.txt); showToast('Copiado.'); } catch { showToast('Copie manualmente.', true); } return; }
  if (acao === 'testar') {
    const r = await api(`/api/monitoring/notificacoes/grupos/${encodeURIComponent(btn.dataset.id)}/teste`, { method: 'POST', body: '{}' });
    const d = await r?.json().catch(() => ({}));
    return showToast(r?.ok && d.ok ? 'Mensagem de teste enviada.' : (d?.erro || d?.detail || 'O Telegram recusou o envio.'), !(r?.ok && d.ok));
  }
  if (acao === 'testar-todos') {
    const grupos = (_nt.dados?.grupos || []).filter(g => g.ativo);
    if (!grupos.length) return showToast('Nenhum grupo ligado.', true);
    const rs = await Promise.all(grupos.map(g => api(`/api/monitoring/notificacoes/grupos/${encodeURIComponent(g.id)}/teste`, { method: 'POST', body: '{}' }).then(r => r?.json()).catch(() => ({}))));
    const ok = rs.filter(x => x?.ok).length;
    showToast(`${ok} de ${grupos.length} grupos receberam o teste.`, ok < grupos.length);
    return ntCarregar();
  }
  if (acao === 'excluir') {
    const g = ntGrupoPorId(btn.dataset.id);
    if (!g || !(await showConfirm({ title: 'Excluir grupo', msg: `Parar de avisar "${g.nome}" e tirar o grupo do SightOps? O grupo continua existindo no Telegram.`, label: 'Excluir' }))) return;
    const r = await api(`/api/monitoring/notificacoes/grupos/${encodeURIComponent(g.id)}`, { method: 'DELETE' });
    if (!r?.ok) return showToast((await r?.json().catch(() => ({})))?.detail || 'Não foi possível excluir.', true);
    showToast('Grupo excluído.');
    ntFecharJanela();
    return ntCarregar();
  }
  if (acao === 'lote') {
    const gid = document.getElementById('ntLoteGrupo')?.value;
    const modo = document.getElementById('ntLoteModo')?.value || 'adicionar';
    const r = await api(`/api/monitoring/notificacoes/grupos/${encodeURIComponent(gid)}/sites`, { method: 'POST', body: JSON.stringify({ sites: [..._nt.marcados], modo }) });
    if (!r?.ok) return showToast((await r?.json().catch(() => ({})))?.detail || 'Não foi possível aplicar.', true);
    showToast(`${_nt.marcados.size} site${_nt.marcados.size === 1 ? '' : 's'} atualizado${_nt.marcados.size === 1 ? '' : 's'}.`);
    _nt.marcados.clear();
    return ntCarregar();
  }
  if (acao === 'salvar-robo') {
    const r = await api('/api/monitoring/notificacoes/robo-easy', { method: 'PUT', body: JSON.stringify({ token: document.getElementById('ntRoboToken')?.value.trim() || '', url_publica: document.getElementById('ntRoboUrl')?.value.trim() || '' }) });
    const d = await r?.json().catch(() => ({}));
    if (!r?.ok) return showToast(d?.detail || 'Não foi possível salvar o robô.', true);
    showToast(`Robô @${d.username} configurado.`);
    return ntCarregar();
  }
}

(function bindNotificacoes() {
  document.addEventListener('click', ev => {
    const btn = ev.target.closest('[data-nt]');
    if (!btn || !(btn.closest('#ntConteudo') || btn.closest('#ntJanela') || btn.closest('[data-settings-panel="notifications"]'))) return;
    if (btn.dataset.nt === 'todos') return; // checkbox: tratado no change
    ntAcao(btn).catch(e => showToast(e?.message || 'Falha na ação.', true));
  });
  document.addEventListener('change', ev => {
    const c = ev.target;
    if (c.matches?.('[data-nt-site]')) {
      if (c.checked) _nt.marcados.add(c.dataset.ntSite); else _nt.marcados.delete(c.dataset.ntSite);
      ntRender();
    } else if (c.matches?.('#ntConteudo [data-nt="todos"]')) {
      document.querySelectorAll('#ntConteudo [data-nt-site]').forEach(x => { if (c.checked) _nt.marcados.add(x.dataset.ntSite); else _nt.marcados.delete(x.dataset.ntSite); });
      ntRender();
    }
  });
  let t = null;
  document.addEventListener('input', ev => {
    if (ev.target.id !== 'ntBusca') return;
    _nt.busca = ev.target.value;
    clearTimeout(t);
    t = setTimeout(() => { ntRender(); const b = document.getElementById('ntBusca'); b?.focus(); b?.setSelectionRange(b.value.length, b.value.length); }, 250);
  });
})();
