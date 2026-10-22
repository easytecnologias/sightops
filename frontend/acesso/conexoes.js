// Aba Conexoes do Painel (/v3/acesso/#conexoes): o WhatsApp que leva os avisos
// de entrada e saida aos responsaveis. Mesmas rotas da aba Conexoes da tela
// antiga (/api/access-control/whatsapp*); gravar e desconectar sao so de
// administrador (security.py), entao para os outros a tela fica so de leitura.

let _cnLigado = false;
let _cnSite = '';
let _cnSites = [];
let _cnCfg = null;
let _cnCon = null;
let _cnTeste = null;          // { estado, texto }
let _cnOcupado = '';          // 'salvar' | 'verificar' | 'desconectar' | 'teste'

function cnCampo(id) { return document.getElementById(id); }
function cnAdmin() {
  const u = typeof acUsuario !== 'undefined' && acUsuario ? acUsuario : {};
  return !!u.is_platform_admin || ['owner', 'admin'].includes(String(u.role || '').toLowerCase());
}
function cnCloud(p) { return ['cloud_api', 'cloud', 'oficial'].includes(String(p || 'cloud_api').toLowerCase()); }
function cnProvedor() { return (cnCampo('cnProvider') || {}).value || (_cnCfg && _cnCfg.provider) || 'cloud_api'; }

const CN_EVOLUTION = { connected: 'Conectado', waiting_qr: 'Aguardando leitura do QR Code', disconnected: 'Desconectado',
  not_configured: 'Não configurado', error: 'Erro ao consultar', unknown: 'Desconhecido' };

// Situacao do canal numa frase: o que aparece no selo do topo.
function cnSituacao() {
  const c = _cnCfg || {}, k = _cnCon;
  if (!c.configured) return { cls: 'cinza', txt: 'Não configurado' };
  if (!c.enabled) return { cls: 'cinza', txt: 'Configurado, envio desligado' };
  if (!k) return { cls: 'cinza', txt: 'Verificando…' };
  const evo = !cnCloud(k.provider || c.provider);
  if (k.state === 'error') return { cls: 'ruim', txt: 'Erro ao consultar' };
  if (evo ? k.connected : k.configured) return { cls: 'ok', txt: 'Enviando avisos' };
  return { cls: 'atencao', txt: CN_EVOLUTION[k.state] || 'Sem conexão' };
}

function cnDesenhar() {
  const el = cnCampo('cnConteudo');
  if (!el) return;
  if (!_cnCfg) { el.innerHTML = '<p class="ap-vazio">Carregando…</p>'; return; }
  const c = _cnCfg, k = _cnCon || {};
  const admin = cnAdmin();
  const cloud = cnCloud(cnProvedor());
  const s = cnSituacao();
  const dis = admin ? '' : 'disabled';
  const QUAL = { GREEN: 'Boa', YELLOW: 'Média', RED: 'Baixa', UNKNOWN: 'Sem histórico' };
  const SIT = { APPROVED: 'aprovado', PENDING: 'em análise', REJECTED: 'reprovado' };
  const modelo = k.template_name ? `${k.template_name}${SIT[String(k.template_status || '').toUpperCase()] ? ' (' + SIT[String(k.template_status).toUpperCase()] + ')' : ''}` : '—';
  const qr = k.qrcode ? (String(k.qrcode).startsWith('data:') ? k.qrcode : `data:image/png;base64,${k.qrcode}`) : '';
  const bot = (id, icone, rot, cls = 'secondary-action', extra = '') => `<button type="button" class="${cls}" id="${id}" ${extra} ${_cnOcupado ? 'disabled' : ''}>
      <i data-lucide="${_cnOcupado === id ? 'loader-circle' : icone}" class="${_cnOcupado === id ? 'dv-gira' : ''}"></i> ${rot}</button>`;
  const fato = (rot, val) => `<div><dt>${rot}</dt><dd>${esc(val || '—')}</dd></div>`;
  el.innerHTML = `
    <div class="cn-topo">
      <label class="rl-campo">Canal usado por<select id="cnSite">
        <option value="">Todos os locais (padrão do cliente)</option>
        ${_cnSites.map(x => `<option value="${esc(x)}" ${x === _cnSite ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>
      <span class="cn-selo ${s.cls}"><i></i>${esc(s.txt)}</span>
      <p class="cn-ajuda">${_cnSite ? (c.site_configured ? `${esc(_cnSite)} tem canal próprio.` : `${esc(_cnSite)} usa o canal padrão do cliente. Salvar aqui cria um canal só para este local.`) : 'O canal padrão vale para todo local que não tem canal próprio.'}</p>
    </div>
    ${admin ? '' : '<div class="ap-nota cn-leitura"><i data-lucide="lock"></i><div>Só administrador altera o canal, desconecta ou envia teste. Aqui você vê como está.</div></div>'}
    <div class="cn-grade">
      <section class="panel rl-bloco">
        <div class="rl-bloco-cab"><h3>Canal dos avisos</h3><p>De onde saem as mensagens de entrada e saída para os responsáveis.</p></div>
        <fieldset class="cn-form" ${dis}>
          <label class="dv-chave"><input type="checkbox" id="cnEnabled" ${c.enabled ? 'checked' : ''}><span></span>Enviar avisos por WhatsApp</label>
          <label class="rl-campo">Provedor<select id="cnProvider">
            <option value="cloud_api" ${cloud ? 'selected' : ''}>API oficial (Meta)</option>
            <option value="evolution" ${!cloud ? 'selected' : ''}>Evolution API</option></select></label>
          ${cloud ? `<label class="rl-campo">Phone Number ID<input id="cnPhoneId" value="${esc(c.phone_number_id || '')}" placeholder="Identificação do número na Meta"></label>
          <details class="cn-tec"><summary><i data-lucide="settings-2"></i> Configuração técnica</summary>
            <div class="cn-tec-grade">
              <label class="rl-campo">WABA ID<input id="cnWaba" value="${esc(c.waba_id || '')}" placeholder="Conta WhatsApp Business"></label>
              <label class="rl-campo">Token de acesso<input id="cnToken" type="password" placeholder="${c.configured ? 'Deixe vazio para manter o atual' : 'Token permanente da Meta'}" autocomplete="off"></label>
              <label class="rl-campo">Modelo aprovado<input id="cnTemplate" value="${esc(c.template_name || '')}" placeholder="acesso_entrada_saida"></label>
              <label class="rl-campo">Idioma do modelo<input id="cnLang" value="${esc(c.template_language || 'pt_BR')}" placeholder="pt_BR"></label>
            </div></details>`
            : '<p class="cn-ajuda">O endereço e a chave do Evolution ficam na plataforma. Aqui só liga, desliga e pareia o celular.</p>'}
        </fieldset>
        ${admin ? `<div class="cn-acoes">${bot('cnSalvar', 'save', 'Salvar', 'primary-action')}</div>` : ''}
      </section>
      <div class="cn-col">
        <section class="panel rl-bloco">
          <div class="rl-bloco-cab"><h3>Conexão</h3><p>${cloud ? 'Na API oficial não há sessão nem QR Code: a autenticação é um token permanente.' : 'A sessão precisa estar conectada ao celular do local.'}</p></div>
          <dl class="cn-fatos">${cloud
            ? fato('Número remetente', k.display_phone_number || k.phone_number_id) + fato('Nome exibido', k.verified_name) + fato('Modelo de mensagem', modelo) + fato('Qualidade da conta', QUAL[String(k.quality_rating || '').toUpperCase()])
            : fato('Instância', k.instance) + fato('Sessão', CN_EVOLUTION[k.state] || k.state)}</dl>
          ${qr ? `<div class="cn-qr"><img src="${qr}" alt="QR Code do WhatsApp"><p>No celular do local: WhatsApp › Aparelhos conectados › Conectar aparelho.</p></div>` : ''}
          ${k.error ? `<p class="dv-erro">${esc(k.error)}</p>` : ''}
          <div class="cn-acoes">${bot('cnVerificar', 'activity', 'Verificar conexão')}${!cloud && admin && k.connected ? bot('cnDesconectar', 'log-out', 'Desconectar') : ''}</div>
        </section>
        <section class="panel rl-bloco">
          <div class="rl-bloco-cab"><h3>Teste de envio</h3><p>Manda uma mensagem simples pelo mesmo canal dos avisos.</p></div>
          <div class="cn-teste"><label class="rl-campo">Número<input id="cnNumero" placeholder="Ex.: (82) 98136-6839" inputmode="tel" ${dis}></label>
            ${admin ? bot('cnTestar', 'send', 'Enviar teste') : ''}</div>
          ${_cnTeste ? `<p class="dvc-res ${_cnTeste.estado}">${esc(_cnTeste.texto)}</p>` : ''}
        </section>
      </div>
    </div>
    <ol class="cn-fluxo" aria-label="Como o aviso chega">
      <li><b>Passagem</b><span>entrada ou saída no leitor</span></li>
      <li><b>Responsável</b><span>número no cadastro da pessoa</span></li>
      <li><b>Canal</b><span>${cloud ? 'API oficial da Meta' : 'Evolution'}${_cnSite ? ' · ' + esc(_cnSite) : ''}</span></li>
      <li><b>Entrega</b><span>conferida no Messenger</span></li>
    </ol>`;
  cnCampo('cnSite')?.addEventListener('change', ev => { _cnSite = ev.target.value; _cnTeste = null; cnCarregar(); });
  cnCampo('cnProvider')?.addEventListener('change', ev => { _cnCfg = { ..._cnCfg, provider: ev.target.value }; cnDesenhar(); });
  cnCampo('cnSalvar')?.addEventListener('click', () => cnSalvar());
  cnCampo('cnVerificar')?.addEventListener('click', cnVerificar);
  cnCampo('cnDesconectar')?.addEventListener('click', cnDesconectar);
  cnCampo('cnTestar')?.addEventListener('click', cnTestar);
  if (window.lucide) lucide.createIcons();
}

function cnQ(extra) {
  const q = new URLSearchParams(extra || {});
  if (_cnSite) q.set('site', _cnSite);
  const s = q.toString();
  return s ? '?' + s : '';
}

async function cnConexao() {
  try {
    _cnCon = await acJson(`/api/access-control/whatsapp/connection${cnQ(cnCloud(cnProvedor()) ? {} : { refresh_qr: '1' })}`);
  } catch (err) {
    _cnCon = { state: 'error', error: (err && err.message) || 'Não consegui consultar a conexão.' };
  }
  return _cnCon;
}

async function cnCarregar() {
  try {
    const s = await acJson('/api/access-control/people/sites');
    _cnSites = (s && s.sites) || [];
    _cnCfg = await acJson(`/api/access-control/whatsapp${cnQ()}`) || {};
    _cnCon = null;
    cnDesenhar();
    await cnConexao();
  } catch (err) {
    if (!_cnCfg) { const el = cnCampo('cnConteudo'); if (el) el.innerHTML = `<p class="ap-vazio">Não consegui carregar: ${esc(err.message || err)}</p>`; return; }
  }
  cnDesenhar();
}

function cnPayload() {
  const p = { site: _cnSite, enabled: !!(cnCampo('cnEnabled') || {}).checked, provider: cnProvedor() };
  if (cnCloud(p.provider)) {
    p.phone_number_id = (cnCampo('cnPhoneId')?.value || '').trim();
    p.waba_id = (cnCampo('cnWaba')?.value || '').trim();
    p.access_token = (cnCampo('cnToken')?.value || '').trim();
    p.template_name = (cnCampo('cnTemplate')?.value || '').trim();
    p.template_language = (cnCampo('cnLang')?.value || '').trim() || 'pt_BR';
  }
  return p;
}

async function cnSalvar(silencioso) {
  const p = cnPayload();
  if (cnCloud(p.provider) && p.enabled) {
    if (!p.phone_number_id) { acToast('Informe o Phone Number ID para ligar a API oficial.', true); cnCampo('cnPhoneId')?.focus(); return null; }
    if (!p.access_token && !(_cnCfg && _cnCfg.configured)) { acToast('Informe o token de acesso da Meta.', true); return null; }
  }
  _cnOcupado = 'cnSalvar'; cnDesenhar();
  try {
    const d = await acEnviar('PUT', '/api/access-control/whatsapp', p);
    _cnCfg = { ..._cnCfg, ...d, ...{ phone_number_id: p.phone_number_id ?? _cnCfg.phone_number_id, waba_id: p.waba_id ?? _cnCfg.waba_id,
      template_name: p.template_name ?? _cnCfg.template_name, template_language: p.template_language ?? _cnCfg.template_language } };
    _cnOcupado = '';
    await cnConexao();
    if (!silencioso) acToast(d.configured ? 'Canal salvo.' : (cnCloud(p.provider) ? 'Salvo, mas falta o Phone Number ID e o token da Meta.' : 'Salvo, mas falta configurar o Evolution na plataforma.'));
    return d;
  } catch (err) {
    acToast(err.message || 'Não consegui salvar.', true);
    return null;
  } finally {
    _cnOcupado = ''; cnDesenhar();
  }
}

async function cnVerificar() {
  _cnOcupado = 'cnVerificar'; cnDesenhar();
  const k = await cnConexao();
  _cnOcupado = ''; cnDesenhar();
  if (!k || k.state === 'error') acToast((k && k.error) || 'Não consegui falar com o provedor.', true);
  else if (!k.configured) acToast(k.error || 'Canal ainda não configurado.', true);
  else if (!cnCloud(k.provider || cnProvedor())) acToast(k.connected ? `Sessão conectada (instância ${k.instance || '—'}).` : `Sessão ${String(CN_EVOLUTION[k.state] || 'não conectada').toLowerCase()}.`, !k.connected);
  else acToast(`Canal ativo em ${k.display_phone_number || k.phone_number_id}.`);
}

async function cnDesconectar() {
  _cnOcupado = 'cnDesconectar'; cnDesenhar();
  try {
    await acEnviar('POST', '/api/access-control/whatsapp/disconnect', { site: _cnSite });
    acToast('Sessão desconectada.');
    await cnConexao();
  } catch (err) {
    acToast(err.message || 'Não consegui desconectar.', true);
  } finally {
    _cnOcupado = ''; cnDesenhar();
  }
}

async function cnTestar() {
  const numero = (cnCampo('cnNumero')?.value || '').trim();
  if (!numero) { acToast('Informe o número de teste.', true); cnCampo('cnNumero')?.focus(); return; }
  // Como na tela antiga: salva antes, para testar o que esta na tela.
  if (!await cnSalvar(true)) return;
  _cnOcupado = 'cnTestar'; cnDesenhar();
  if (cnCampo('cnNumero')) cnCampo('cnNumero').value = numero;
  try {
    const d = await acEnviar('POST', '/api/access-control/whatsapp/test', { number: numero, site: _cnSite });
    _cnTeste = d.status === 'whatsapp_pending'
      ? { estado: 'ok', texto: 'A API aceitou a mensagem, mas ainda não confirmou a entrega. Confira no Messenger.' }
      : { estado: 'ok', texto: `Teste enviado para ${numero}. Confira o WhatsApp desse número.` };
  } catch (err) {
    _cnTeste = { estado: 'ruim', texto: err.message || 'Não consegui enviar o teste.' };
  } finally {
    _cnOcupado = ''; cnDesenhar();
    if (cnCampo('cnNumero')) cnCampo('cnNumero').value = numero;
  }
}

// Chamado pelo Painel ao abrir a aba. O local do topo vira o local do canal.
async function cnAbrirAba() {
  if (!_cnLigado) { _cnLigado = true; _cnSite = typeof _apSite === 'string' ? _apSite : ''; }
  else if (typeof _apSite === 'string' && _apSite && _apSite !== _cnSite) { _cnSite = _apSite; _cnCfg = null; }
  cnDesenhar();
  await cnCarregar();
}
