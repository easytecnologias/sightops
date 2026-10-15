// Dispositivos (/v3/acesso/dispositivos/): leitores faciais e controladoras de
// cada local. Lista: GET /api/access-control/painel/dispositivos (so leitura).
// Cadastro, teste e remocao usam as rotas que ja existiam e as mesmas
// permissoes: POST /devices (operador), POST /devices/{id}/test, DELETE (admin).
// save_device faz UPDATE completo: a edicao reenvia todos os campos do leitor.

let _dvDados = null;
let _dvBusca = '';
let _dvEditando = null;      // dispositivo aberto na gaveta (null = novo)
let _dvNomeManual = false;   // o usuario mexeu no nome? (senao ele acompanha local + funcao)
let _dvPreviaTimer = null;
const _dvTestes = {};        // resultado do ultimo teste por dispositivo

const DV_FUNCAO = {
  entrada: { rot: 'Entrada', cls: 'entrada', icone: 'log-in' },
  saida: { rot: 'Saída', cls: 'saida', icone: 'log-out' },
  entrada_saida: { rot: 'Entrada e saída', cls: 'ambos', icone: 'arrow-left-right' },
};
const DV_FABRICANTE = { intelbras: 'Intelbras', dahua: 'Dahua' };
const DV_TIPO = { escola: 'Escola', condominio: 'Condomínio', misto: 'Escola e condomínio' };

function dvLocal(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T')); return isNaN(d) ? null : d; }
function dvUtc(s) {
  const t = String(s || '').trim();
  if (!t) return null;
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(t) ? t : t.slice(0, 19).replace(' ', 'T') + 'Z');
  return isNaN(d) ? null : d;
}
function dvHa(d) {
  if (!d) return 'nunca';
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 1) return 'agora';
  if (m < 60) return `há ${m} min`;
  if (m < 48 * 60) return `há ${Math.round(m / 60)} h`;
  return 'em ' + d.toLocaleDateString('pt-BR');
}
function dvHm(d) { return d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '—'; }
function dvNum(n) { return Number(n || 0).toLocaleString('pt-BR'); }

// Mesmo criterio do Painel: o status gravado pelo leitor ja mostrou offline
// com passagens no dia; passagem nos ultimos 30 min tambem conta como sinal.
function dvComSinal(d) {
  const u = dvLocal(d.ultima);
  return d.status === 'online' || (u && Date.now() - u.getTime() < 30 * 60000);
}
function dvEstado(d) {
  if (!d.ativo) return { cls: 'inativo', rot: 'Inativo', cor: 'blue' };
  if (!dvComSinal(d)) return { cls: 'ruim', rot: 'Sem sinal', cor: 'red' };
  if (d.relogio_errado || d.fotos_falha) return { cls: 'atencao', rot: 'Com sinal', cor: 'amber' };
  return { cls: 'ok', rot: 'Com sinal', cor: 'green' };
}

// ---------------------------------------------------------------- lista
function dvCards(lista) {
  const ativos = lista.filter(d => d.ativo);
  const vivos = ativos.filter(dvComSinal).length;
  const hoje = lista.reduce((n, d) => n + (d.hoje || 0), 0);
  const recusadas = lista.reduce((n, d) => n + (d.fotos_falha || 0), 0);
  const relogio = lista.filter(d => d.relogio_errado).length;
  const card = ({ icone, cor, estado = '', rot, val, sub, subCor = '' }) => `
    <div class="ap-card ${estado}">
      <span class="metric-icon ${cor}"><i data-lucide="${icone}"></i></span>
      <span class="ap-card-txt"><span class="ap-card-rot">${rot}</span>
        <strong class="ap-card-val">${val}</strong><small class="${subCor}">${sub}</small></span>
    </div>`;
  const semSinal = ativos.length - vivos;
  return `<div class="ap-cards">
    ${card({ icone: 'scan-face', cor: 'blue', rot: 'Leitores', val: dvNum(lista.length), sub: `${dvNum(ativos.length)} ativo${ativos.length === 1 ? '' : 's'} em ${dvNum(new Set(lista.map(d => d.site)).size)} local${new Set(lista.map(d => d.site)).size === 1 ? '' : 'is'}` })}
    ${card({ icone: 'radio', cor: semSinal ? 'red' : 'green', estado: semSinal ? 'ruim' : '', rot: 'Com sinal', val: `${vivos}<span class="ap-card-de">/${ativos.length}</span>`, sub: semSinal ? `${semSinal} sem sinal` : 'todos respondendo', subCor: semSinal ? 'ruim' : '' })}
    ${card({ icone: 'footprints', cor: 'cyan', rot: 'Passagens hoje', val: dvNum(hoje), sub: 'somando todos os leitores' })}
    ${card({ icone: 'image-off', cor: recusadas ? 'amber' : 'green', estado: recusadas ? 'atencao' : '', rot: 'Fotos recusadas', val: dvNum(recusadas), sub: recusadas ? 'pessoas que não abrem a porta' : 'todos aceitaram as fotos', subCor: recusadas ? 'atencao' : '' })}
    ${card({ icone: 'clock-alert', cor: relogio ? 'amber' : 'green', estado: relogio ? 'atencao' : '', rot: 'Relógio errado', val: dvNum(relogio), sub: relogio ? 'leitor gravou data antes de 2020' : 'todos com a hora certa', subCor: relogio ? 'atencao' : '' })}
  </div>`;
}

// Uma linha por leitor, dentro do painel do local: nome inteiro, rota em uma
// linha (IP real -> IP virtual), movimento do dia, estado com um ponto discreto
// e as acoes. Avisos (relogio, fotos) e o resultado do teste vao numa linha
// fina embaixo, so quando existem: a lista fica calma quando esta tudo bem.
function dvRotaTexto(d) {
  const ip = d.ip || {};
  if (ip.bloqueado) return { val: `<span class="monospace">${esc(d.host)}</span>`, sub: '<span class="ap-ruim">conector não é deste cliente</span>' };
  if (ip.traduzido) {
    return {
      val: `<span class="monospace">${esc(ip.host || d.host)}</span><i data-lucide="arrow-right" class="dv-seta"></i><span class="monospace dv-virtual">${esc(ip.virtual)}</span>`,
      sub: `pelo conector ${esc(d.conector)}${d.conector_status && d.conector_status !== 'online' ? ` <span class="ap-ruim">(${esc(d.conector_status)})</span>` : ''}`,
    };
  }
  return { val: `<span class="monospace">${esc(ip.virtual || d.host)}</span>`, sub: d.connector_id ? `pelo conector ${esc(d.conector)}` : 'direto do servidor' };
}

function dvObs(d) {
  const itens = [];
  const t = _dvTestes[d.id];
  if (t && t.rodando) itens.push('<span class="dv-obs-teste"><i data-lucide="loader-circle" class="dv-gira"></i>Testando conexão…</span>');
  else if (t && t.ok) itens.push(`<span class="dv-obs-ok"><i data-lucide="check"></i>Respondeu em ${(t.ms / 1000).toFixed(1).replace('.', ',')} s${t.modelo ? ' · ' + esc(t.modelo) : ''}</span>`);
  else if (t) itens.push(`<span class="dv-obs-ruim"><i data-lucide="x"></i>${esc(t.erro)}</span>`);
  if (d.relogio_errado) itens.push(`<span class="dv-obs-at"><i data-lucide="clock-alert"></i>Relógio do leitor zerou: ${d.relogio_errado} passage${d.relogio_errado === 1 ? 'm' : 'ns'} com data antes de 2020</span>`);
  if (d.fotos_falha) itens.push(`<span class="dv-obs-at"><i data-lucide="image-off"></i>${d.fotos_falha} foto${d.fotos_falha === 1 ? '' : 's'} recusada${d.fotos_falha === 1 ? '' : 's'} pelo leitor</span>`);
  return itens.length ? `<div class="dv-obs">${itens.join('')}</div>` : '';
}

function dvLinha(d) {
  const e = dvEstado(d);
  const f = DV_FUNCAO[d.funcao] || DV_FUNCAO.entrada;
  const r = dvRotaTexto(d);
  const ultima = dvLocal(d.ultima);
  const ultimaTxt = ultima ? (Date.now() - ultima < 86400000 ? 'última ' + dvHm(ultima) : 'última em ' + ultima.toLocaleDateString('pt-BR')) : 'sem passagem';
  const rodando = (_dvTestes[d.id] || {}).rodando;
  return `<div class="dv-linha ${e.cls}" data-dv="${esc(d.id)}">
    <div class="dv-l-quem">
      <span class="dv-ic ${f.cls}" title="${f.rot}"><i data-lucide="${f.icone}"></i></span>
      <div><b>${esc(d.nome)}</b>
        <small>${f.rot} · ${esc([DV_FABRICANTE[d.fabricante] || d.fabricante, d.modelo].filter(Boolean).join(' ') || 'modelo ainda não lido')}</small></div>
    </div>
    <div class="dv-l-rota"><span class="dv-l-rot">Rota</span><div>${r.val}</div><small>${r.sub}</small></div>
    <div class="dv-l-mov"><span class="dv-l-rot">Hoje</span><div><b class="monospace">${dvNum(d.hoje)}</b> <span>passage${d.hoje === 1 ? 'm' : 'ns'}</span></div><small>${ultimaTxt}</small></div>
    <div class="dv-l-est"><span class="dv-ponto ${e.cls}"></span><div><b>${e.rot}</b><small>${d.visto ? 'falou ' + dvHa(dvUtc(d.visto)) : 'nunca testado'}</small></div></div>
    <div class="dv-l-acoes">
      <button type="button" class="dv-btn" data-dv-testar="${esc(d.id)}" ${rodando ? 'disabled' : ''} title="Testar conexão"><i data-lucide="activity"></i><span>Testar</span></button>
      <button type="button" class="dv-btn" data-dv-editar="${esc(d.id)}" title="Editar"><i data-lucide="pencil"></i><span>Editar</span></button>
    </div>
    ${dvObs(d)}
  </div>`;
}

function dvDesenhar() {
  const el = document.getElementById('dvConteudo');
  if (!el || !_dvDados) return;
  const todos = _dvDados.dispositivos || [];
  const b = _dvBusca.trim().toLowerCase();
  const lista = todos.filter(d => !b || [d.nome, d.site, d.host, d.modelo, d.conector, (d.ip || {}).virtual]
    .some(x => String(x || '').toLowerCase().includes(b)));
  const locais = _dvDados.locais || [];
  const porLocal = new Map();
  lista.forEach(d => {
    const k = (d.site || 'Sem local').toUpperCase();
    if (!porLocal.has(k)) porLocal.set(k, { site: d.site || 'Sem local', itens: [] });
    porLocal.get(k).itens.push(d);
  });
  const conectores = new Map((_dvDados.conectores || []).map(c => [c.id, c]));
  const grupos = [...porLocal.values()].sort((a, b2) => a.site.localeCompare(b2.site, 'pt-BR'));
  const vazios = b ? [] : locais.filter(l => !l.leitores);

  el.innerHTML = `
    ${dvCards(todos)}
    ${grupos.map(g => {
      const info = locais.find(l => l.site.toUpperCase() === g.site.toUpperCase()) || {};
      const con = conectores.get(info.connector_id || (g.itens[0] || {}).connector_id) || null;
      const ordem = g.itens.slice().sort((x, y) => (dvComSinal(x) - dvComSinal(y)) || x.nome.localeCompare(y.nome, 'pt-BR'));
      return `<section class="dv-local">
        <header class="dv-local-cab">
          <div><h2>${esc(g.site)}</h2>
            <span class="ap-perfil ${info.tipo || ''}" title="${info.origem === 'cadastro' ? 'Pelo cadastro de pessoas' : info.origem === 'nome' ? 'Pelo nome do local' : 'Pelo restante do cliente'}">${DV_TIPO[info.tipo] || ''}</span></div>
          <div class="dv-local-meta">
            ${con ? `<span class="dv-con ${con.status === 'online' ? 'ok' : 'ruim'}"><i></i>Conector ${esc(con.nome)} · ${esc(con.status || 'sem status')}</span>` : ''}
            <span>${g.itens.length} leitor${g.itens.length === 1 ? '' : 'es'}</span>
            <button type="button" class="ghost-action dv-add-local" data-dv-novo="${esc(g.site)}"><i data-lucide="plus"></i> Leitor neste local</button>
          </div>
        </header>
        <div class="dv-lista">${ordem.map(dvLinha).join('')}</div>
      </section>`;
    }).join('') || `<div class="dv-vazio"><i data-lucide="${b ? 'search-x' : 'scan-face'}"></i>
      <b>${b ? 'Nenhum leitor com “' + esc(_dvBusca) + '”' : 'Nenhum leitor cadastrado'}</b>
      <p>${b ? 'Busque por nome, local, IP ou modelo.' : 'Cadastre o primeiro leitor para o SightOps começar a receber as passagens.'}</p>
      ${b ? '' : '<button type="button" class="primary-action" data-dv-novo=""><i data-lucide="plus"></i> Novo dispositivo</button>'}</div>`}
    ${vazios.length ? `<details class="dv-sem-discreto">
      <summary>${vazios.length} local${vazios.length === 1 ? '' : 'is'} do cliente ainda sem leitor</summary>
      <div class="dv-sem-lista">${vazios.map(l => `<button type="button" class="dv-sem-item" data-dv-novo="${esc(l.site)}">
        <span>${esc(l.site)}</span><i data-lucide="plus"></i></button>`).join('')}</div>
    </details>` : ''}`;
  dvLigar(el);
  if (window.lucide) lucide.createIcons();
}

function dvLigar(el) {
  el.querySelectorAll('[data-dv-novo]').forEach(b => b.addEventListener('click', () => dvAbrir(null, b.dataset.dvNovo)));
  el.querySelectorAll('[data-dv-editar]').forEach(b => b.addEventListener('click', () => {
    dvAbrir((_dvDados.dispositivos || []).find(d => d.id === b.dataset.dvEditar));
  }));
  el.querySelectorAll('[data-dv-testar]').forEach(b => b.addEventListener('click', () => dvTestar(b.dataset.dvTestar)));
}

async function dvCarregar() {
  const dados = await apiJson('/api/access-control/painel/dispositivos');
  if (!dados) return;
  _dvDados = dados;
  const chip = document.getElementById('dvPerfil');
  if (chip && dados.perfil) { chip.textContent = DV_TIPO[dados.perfil.tipo] || ''; chip.className = 'ap-perfil ' + dados.perfil.tipo; }
  dvDesenhar();
}

// ---------------------------------------------------------------- teste
async function dvTestar(id) {
  const inicio = performance.now();
  _dvTestes[id] = { rodando: true };
  dvDesenhar();
  try {
    const r = await acEnviar('POST', `/api/access-control/devices/${encodeURIComponent(id)}/test`);
    const info = r.info || {};
    _dvTestes[id] = { ok: true, ms: performance.now() - inicio, modelo: info.deviceType || info.updateSerial || (r.device || {}).model || '' };
    acToast('O leitor respondeu.');
  } catch (err) {
    _dvTestes[id] = { ok: false, erro: (err && err.message) || 'O leitor não respondeu.' };
  }
  await dvCarregar();
}

// ---------------------------------------------------------------- gaveta
function dvCampo(id) { return document.getElementById(id); }

function dvNomeSugerido() {
  const f = dvCampo('dvFuncao').value;
  const site = dvCampo('dvSite').value.trim().toUpperCase();
  const rot = { entrada: 'ENTRADA', saida: 'SAIDA', entrada_saida: 'PORTARIA' }[f] || 'ENTRADA';
  return site ? `${rot} - ${site}` : rot;
}

function dvOpcoesConector(selecionado) {
  const sel = dvCampo('dvConector');
  const lista = _dvDados.conectores || [];
  sel.innerHTML = '<option value="">Sem conector · o servidor alcança direto</option>' + lista.map(c =>
    `<option value="${esc(c.id)}">${esc(c.nome)}${c.site && c.site !== c.nome ? ' · ' + esc(c.site) : ''} (${esc(c.status || 'sem status')})</option>`).join('') +
    (selecionado && !lista.some(c => c.id === selecionado) ? `<option value="${esc(selecionado)}">${esc(selecionado)} (não encontrado)</option>` : '');
  sel.value = selecionado || '';
}

function dvAbrir(d, siteSugerido) {
  _dvEditando = d || null;
  const novo = !d;
  dvCampo('dvTitulo').textContent = novo ? 'Novo dispositivo' : 'Editar dispositivo';
  dvCampo('dvSubtitulo').textContent = novo ? 'Leitor facial ou controladora de um local do cliente.' : d.nome;
  const locais = _dvDados.locais || [];
  dvCampo('dvSites').innerHTML = locais.map(l => `<option value="${esc(l.site)}">`).join('');
  const livres = novo ? locais.filter(l => !l.leitores) : [];
  const sug = dvCampo('dvSugestoes');
  sug.hidden = !livres.length;
  sug.innerHTML = livres.length ? `<span>Ainda sem leitor:</span>${livres.map(l =>
    `<button type="button" data-dv-sug="${esc(l.site)}">${esc(l.site)}</button>`).join('')}` : '';
  sug.querySelectorAll('[data-dv-sug]').forEach(b => b.addEventListener('click', () => {
    dvCampo('dvSite').value = b.dataset.dvSug;
    dvCampo('dvSite').dispatchEvent(new Event('input'));
    dvCampo('dvHost').focus();
  }));
  dvCampo('dvSite').value = novo ? (siteSugerido || '') : d.site;
  dvOpcoesConector(novo ? ((locais.find(l => l.site.toUpperCase() === String(siteSugerido || '').toUpperCase()) || {}).connector_id || '') : d.connector_id);
  dvCampo('dvHost').value = novo ? '' : d.host;
  dvCampo('dvUsuario').value = novo ? 'admin' : (d.usuario || 'admin');
  dvCampo('dvSenha').value = '';
  dvCampo('dvSenha').placeholder = novo ? 'Senha do leitor' : 'Deixe em branco para manter a atual';
  dvCampo('dvSenha').required = novo;
  dvMarcar('dvFuncao', novo ? 'entrada' : (d.funcao || 'entrada'));
  dvMarcar('dvFabricante', novo ? 'intelbras' : (d.fabricante || 'intelbras'));
  dvCampo('dvAtivo').checked = novo ? true : d.ativo;
  _dvNomeManual = !novo;
  dvCampo('dvNome').value = novo ? dvNomeSugerido() : d.nome;
  dvCampo('dvRemover').hidden = novo;
  dvCampo('dvConfirma').hidden = true;
  dvCampo('dvErro').hidden = true;
  dvPrevia();
  dvCampo('dvGaveta').hidden = false;
  requestAnimationFrame(() => dvCampo('dvGaveta').classList.add('aberta'));
  setTimeout(() => (novo && !siteSugerido ? dvCampo('dvSite') : dvCampo('dvHost')).focus(), 150);
  if (window.lucide) lucide.createIcons();
}

function dvFechar() {
  const g = dvCampo('dvGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

// Botoes segmentados (Funcao, Fabricante): o valor fica num input escondido.
function dvMarcar(id, valor) {
  dvCampo(id).value = valor;
  document.querySelectorAll(`[data-dv-seg="${id}"] button`).forEach(b => {
    const on = b.dataset.valor === valor;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

// Previa ao vivo: por qual IP o SightOps vai falar com o leitor.
function dvPrevia() {
  clearTimeout(_dvPreviaTimer);
  const box = dvCampo('dvPrevia');
  const host = dvCampo('dvHost').value.trim();
  const cid = dvCampo('dvConector').value;
  const con = (_dvDados.conectores || []).find(c => c.id === cid);
  if (!host) {
    box.className = 'dv-previa neutro';
    box.innerHTML = '<i data-lucide="info"></i><span>Informe o IP do leitor na rede do local. O SightOps mostra aqui por onde vai falar com ele.</span>';
    if (window.lucide) lucide.createIcons();
    return;
  }
  if (!cid) {
    box.className = 'dv-previa neutro';
    box.innerHTML = `<i data-lucide="network"></i><span>O servidor vai falar direto com <b class="monospace">${esc(host)}</b>. Use isto só se o leitor estiver na rede do próprio servidor ou na VPN.</span>`;
    if (window.lucide) lucide.createIcons();
    return;
  }
  _dvPreviaTimer = setTimeout(async () => {
    try {
      const r = await apiJson(`/api/access-control/painel/ip-virtual?connector_id=${encodeURIComponent(cid)}&host=${encodeURIComponent(host)}`);
      if (!r) return;
      if (r.bloqueado) {
        box.className = 'dv-previa ruim';
        box.innerHTML = '<i data-lucide="shield-x"></i><span>Este conector não é deste cliente. Escolha o conector do local.</span>';
      } else if (r.traduzido) {
        box.className = 'dv-previa ok';
        box.innerHTML = `<i data-lucide="route"></i><span>O SightOps vai falar com o leitor pelo IP virtual <b class="monospace">${esc(r.virtual)}</b>, através do conector <b>${esc(con ? con.nome : cid)}</b>${con && con.status !== 'online' ? ` <em class="ap-ruim">(conector ${esc(con.status || 'sem status')})</em>` : ''}.</span>`;
      } else {
        box.className = 'dv-previa atencao';
        box.innerHTML = `<i data-lucide="alert-triangle"></i><span><b class="monospace">${esc(host)}</b> não está numa rede mapeada do conector ${esc(con ? con.nome : cid)}. Confira o IP: se o leitor estiver atrás do conector, o servidor não vai alcançá-lo por este endereço.</span>`;
      }
    } catch (_) {
      box.className = 'dv-previa neutro';
      box.innerHTML = '<i data-lucide="info"></i><span>Não consegui calcular o IP virtual agora.</span>';
    }
    if (window.lucide) lucide.createIcons();
  }, 300);
}

function dvPayload() {
  const d = _dvEditando || {};
  return {
    id: d.id || '',
    name: dvCampo('dvNome').value.trim(),
    site: dvCampo('dvSite').value.trim(),
    vendor: dvCampo('dvFabricante').value,
    model: d.modelo || '',
    host: dvCampo('dvHost').value.trim(),
    connector_id: dvCampo('dvConector').value,
    username: dvCampo('dvUsuario').value.trim() || 'admin',
    password: dvCampo('dvSenha').value,
    access_direction: dvCampo('dvFuncao').value,
    active: dvCampo('dvAtivo').checked,
  };
}

function dvErro(msg) {
  const e = dvCampo('dvErro');
  e.textContent = msg;
  e.hidden = !msg;
}

async function dvSalvar(testar) {
  const p = dvPayload();
  if (!p.site) return dvErro('Escolha o local do leitor.');
  if (!p.host) return dvErro('Informe o IP do leitor na rede do local.');
  if (!/^[\w.-]+$/.test(p.host)) return dvErro('O IP tem caracteres inválidos.');
  if (!p.name) return dvErro('Dê um nome ao leitor.');
  if (!p.id && !p.password) return dvErro('Informe a senha do leitor.');
  dvErro('');
  const botoes = document.querySelectorAll('#dvGaveta .dv-gaveta-pe button');
  botoes.forEach(b => { b.disabled = true; });
  try {
    const r = await acEnviar('POST', '/api/access-control/devices', p);
    const id = (r.device || {}).id;
    acToast(p.id ? 'Dispositivo atualizado.' : 'Dispositivo cadastrado.');
    dvFechar();
    await dvCarregar();
    if (id) {
      const card = document.querySelector(`[data-dv="${CSS.escape(id)}"]`);
      if (card) { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); card.classList.add('destaque'); }
      if (testar) dvTestar(id);
    }
  } catch (err) {
    dvErro((err && err.message) || 'Não foi possível salvar.');
  } finally {
    botoes.forEach(b => { b.disabled = false; });
  }
}

async function dvRemover() {
  const d = _dvEditando;
  if (!d) return;
  try {
    await acEnviar('DELETE', `/api/access-control/devices/${encodeURIComponent(d.id)}`);
    acToast('Dispositivo removido.');
    dvFechar();
    await dvCarregar();
  } catch (err) {
    dvErro((err && err.message) || 'Não foi possível remover.');
  }
}

function dvLigarGaveta() {
  dvCampo('dvFechar').addEventListener('click', dvFechar);
  dvCampo('dvCancelar').addEventListener('click', dvFechar);
  dvCampo('dvFundo').addEventListener('click', dvFechar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !dvCampo('dvGaveta').hidden) dvFechar(); });
  dvCampo('dvForm').addEventListener('submit', ev => { ev.preventDefault(); dvSalvar(true); });
  dvCampo('dvSoSalvar').addEventListener('click', () => dvSalvar(false));
  document.querySelectorAll('[data-dv-seg] button').forEach(b => b.addEventListener('click', () => {
    dvMarcar(b.closest('[data-dv-seg]').dataset.dvSeg, b.dataset.valor);
    if (!_dvNomeManual) dvCampo('dvNome').value = dvNomeSugerido();
  }));
  dvCampo('dvSite').addEventListener('input', () => {
    const site = dvCampo('dvSite').value.trim().toUpperCase();
    const l = (_dvDados.locais || []).find(x => x.site.toUpperCase() === site);
    if (l && l.connector_id) dvOpcoesConector(l.connector_id);
    if (!_dvNomeManual) dvCampo('dvNome').value = dvNomeSugerido();
    dvPrevia();
  });
  dvCampo('dvNome').addEventListener('input', () => { _dvNomeManual = true; });
  dvCampo('dvHost').addEventListener('input', dvPrevia);
  dvCampo('dvConector').addEventListener('change', dvPrevia);
  dvCampo('dvVerSenha').addEventListener('click', () => {
    const s = dvCampo('dvSenha');
    s.type = s.type === 'password' ? 'text' : 'password';
    dvCampo('dvVerSenha').setAttribute('aria-pressed', String(s.type === 'text'));
  });
  dvCampo('dvRemover').addEventListener('click', () => { dvCampo('dvConfirma').hidden = false; });
  dvCampo('dvConfirmaNao').addEventListener('click', () => { dvCampo('dvConfirma').hidden = true; });
  dvCampo('dvConfirmaSim').addEventListener('click', dvRemover);
}

async function dvIniciar() {
  dvLigarGaveta();
  dvCampo('dvNovo').addEventListener('click', () => dvAbrir(null, ''));
  dvCampo('dvBusca').addEventListener('input', ev => { _dvBusca = ev.target.value; dvDesenhar(); });
  dvCampo('dvAtualizar').addEventListener('click', dvCarregar);
  try {
    await dvCarregar();
  } catch (err) {
    dvCampo('dvConteudo').innerHTML = `<p class="ap-vazio">Não consegui carregar os dispositivos: ${esc((err && err.message) || err)}</p>`;
  }
  setInterval(() => { if (!document.hidden && dvCampo('dvGaveta').hidden) dvCarregar().catch(() => {}); }, 60000);
}

window.acPagina = { id: 'dispositivos', iniciar: dvIniciar };
