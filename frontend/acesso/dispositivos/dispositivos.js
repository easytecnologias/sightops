// Aba Dispositivos do Painel de Acesso (/v3/acesso/#dispositivos): leitores
// faciais e controladoras de cada local. Lista: GET /api/access-control/painel/dispositivos (so leitura).
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
const DV_TIPO = { escola: 'Escola', condominio: 'Condomínio', empresa: 'Empresa', evento: 'Evento', misto: 'Vários tipos' };

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
  let t = _dvTestes[d.id];
  // Falha velha: o leitor falou depois do teste (ex.: senha corrigida). Nao
  // deixa um "HTTP 502" de antes ao lado de "Com sinal".
  const visto = dvUtc(d.visto);
  if (t && t.ok === false && visto && visto.getTime() > (t.em || 0)) { delete _dvTestes[d.id]; t = null; }
  if (t && t.rodando) itens.push('<span class="dv-obs-teste"><i data-lucide="loader-circle" class="dv-gira"></i>Testando conexão…</span>');
  else if (t && t.ok) itens.push(`<span class="dv-obs-ok"><i data-lucide="check"></i>Respondeu em ${(t.ms / 1000).toFixed(1).replace('.', ',')} s${t.modelo ? ' · ' + esc(t.modelo) : ''}</span>`);
  else if (t) itens.push(`<span class="dv-obs-ruim"><i data-lucide="x"></i>${esc(t.erro)}</span>`);
  if (d.relogio_errado) itens.push(`<span class="dv-obs-at"><i data-lucide="clock-alert"></i>Relógio do leitor zerou: ${d.relogio_errado} passage${d.relogio_errado === 1 ? 'm' : 'ns'} com data antes de 2020 <button type="button" class="dv-obs-link" data-dvc-abrir="${esc(d.id)}">Ver e acertar a hora</button></span>`);
  if (d.fotos_falha) itens.push(`<span class="dv-obs-at"><i data-lucide="image-off"></i>${d.fotos_falha} foto${d.fotos_falha === 1 ? '' : 's'} recusada${d.fotos_falha === 1 ? '' : 's'} pelo leitor</span>`);
  return itens.length ? `<div class="dv-obs">${itens.join('')}</div>` : '';
}

// Curva de hoje (24 h) do leitor, com o pico. Vinha da aba Portas.
function dvCurva(horas) {
  horas = horas || [];
  const max = Math.max(...horas, 0);
  if (!max) return '';
  const w = 96, h = 26, agoraH = new Date().getHours();
  const pts = horas.slice(0, agoraH + 1).map((n, i) => [i * w / 23, h - 2 - n / max * (h - 4)]);
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const pico = horas.indexOf(max);
  return `<span class="dv-curva" title="Movimento de hoje por hora · pico às ${String(pico).padStart(2, '0')}h (${max})">
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true"><path d="${d} L${pts[pts.length - 1][0].toFixed(1)} ${h} L0 ${h} Z" fill="var(--primary-soft)"/><path d="${d}" fill="none" stroke="var(--primary)" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>
    <small>pico ${String(pico).padStart(2, '0')}h</small></span>`;
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
    <div class="dv-l-mov"><span class="dv-l-rot">Hoje</span><div class="dv-l-mov-l"><span><b class="monospace">${dvNum(d.hoje)}</b> <span>passage${d.hoje === 1 ? 'm' : 'ns'}</span><small>${ultimaTxt}</small></span>${dvCurva(d.horas)}</div></div>
    <div class="dv-l-est"><span class="dv-ponto ${e.cls}"></span><div><b>${e.rot}</b><small>${d.visto ? 'falou ' + dvHa(dvUtc(d.visto)) : 'nunca testado'}</small></div></div>
    <div class="dv-l-acoes">
      <button type="button" class="dv-btn dv-porta-abrir" data-dv-porta="abrir" data-id="${esc(d.id)}" title="Abrir a porta agora"><i data-lucide="lock-open"></i><span>Abrir</span></button>
      <button type="button" class="dv-btn" data-dv-porta="fechar" data-id="${esc(d.id)}" title="Fechar (travar) a porta agora"><i data-lucide="lock"></i><span>Fechar</span></button>
      <button type="button" class="dv-btn" data-dvc-abrir="${esc(d.id)}" title="Hora, NTP, página do leitor, reiniciar"><i data-lucide="settings-2"></i><span>Controladora</span></button>
    </div>
    ${dvObs(d)}
  </div>`;
}

function dvDesenhar() {
  const el = document.getElementById('dvConteudo');
  if (!el || !_dvDados) return;
  // Respeita o site escolhido no topo do Painel.
  const siteFiltro = typeof _apSite === 'string' ? _apSite.toUpperCase() : '';
  const todos = (_dvDados.dispositivos || []).filter(d => !siteFiltro || String(d.site).toUpperCase() === siteFiltro);
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
  const vazios = b || siteFiltro ? [] : locais.filter(l => !l.leitores);

  el.innerHTML = `
    ${dvCards(todos)}
    ${grupos.map(g => {
      const info = locais.find(l => l.site.toUpperCase() === g.site.toUpperCase()) || {};
      const con = conectores.get(info.connector_id || (g.itens[0] || {}).connector_id) || null;
      const ordem = g.itens.slice().sort((x, y) => (dvComSinal(x) - dvComSinal(y)) || x.nome.localeCompare(y.nome, 'pt-BR'));
      return `<section class="dv-local">
        <header class="dv-local-cab">
          <div><h2>${esc(g.site)}</h2>
            <button type="button" class="ap-perfil ${info.tipo || ''} ${info.origem === 'escolhido' ? '' : 'palpite'}" data-dv-tipo="${esc(g.site)}" aria-haspopup="menu"
              title="${info.origem === 'escolhido' ? 'Escolhido por você' : 'Palpite do SightOps'}. Clique para mudar.">${DV_TIPO[info.tipo] || 'Definir tipo'}</button></div>
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

// ---------------------------------------------------------------- porta: abrir/fechar
// Dois cliques: o primeiro so arma ("Confirmar abrir"), o segundo executa.
// Porta de cliente e coisa seria: ninguem abre sem querer.
function dvConfirmar(btn, rotulo, acao) {
  if (btn.dataset.armado) {
    clearTimeout(+btn.dataset.armado);
    delete btn.dataset.armado;
    btn.classList.remove('armado');
    acao();
    return;
  }
  const original = btn.innerHTML;
  btn.classList.add('armado');
  btn.innerHTML = `<i data-lucide="alert-triangle"></i><span>${rotulo}</span>`;
  if (window.lucide) lucide.createIcons();
  btn.dataset.armado = String(setTimeout(() => {
    delete btn.dataset.armado;
    btn.classList.remove('armado');
    btn.innerHTML = original;
    if (window.lucide) lucide.createIcons();
  }, 4000));
}

async function dvPorta(id, acao, btn) {
  const d = (_dvDados.dispositivos || []).find(x => x.id === id) || {};
  if (btn) { btn.disabled = true; btn.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i><span>Enviando…</span>'; if (window.lucide) lucide.createIcons(); }
  try {
    if (acao === 'abrir') await acEnviar('POST', `/api/access-control/devices/${encodeURIComponent(id)}/open-door?channel=1`);
    else await acEnviar('POST', `/api/access-control/painel/controladora/${encodeURIComponent(id)}/fechar?canal=1`);
    acToast(`${apPorta(d.nome || 'Porta')}: ${acao === 'abrir' ? 'porta aberta' : 'porta fechada'}.`);
    return true;
  } catch (err) {
    acToast(`${apPorta(d.nome || 'Porta')}: não consegui ${acao} (${err.message}).`, true);
    return false;
  } finally {
    if (btn) dvDesenhar();
  }
}

function dvLigar(el) {
  el.querySelectorAll('[data-dv-novo]').forEach(b => b.addEventListener('click', () => dvAbrir(null, b.dataset.dvNovo)));
  el.querySelectorAll('[data-dv-editar]').forEach(b => b.addEventListener('click', () => {
    dvAbrir((_dvDados.dispositivos || []).find(d => d.id === b.dataset.dvEditar));
  }));
  el.querySelectorAll('[data-dv-testar]').forEach(b => b.addEventListener('click', () => dvTestar(b.dataset.dvTestar)));
  el.querySelectorAll('[data-dv-porta]').forEach(b => b.addEventListener('click', () => {
    const acao = b.dataset.dvPorta;
    dvConfirmar(b, acao === 'abrir' ? 'Confirmar abrir' : 'Confirmar fechar', () => dvPorta(b.dataset.id, acao, b));
  }));
  el.querySelectorAll('[data-dvc-abrir]').forEach(b => b.addEventListener('click', () => dvcAbrir(b.dataset.dvcAbrir)));
  el.querySelectorAll('[data-dv-tipo]').forEach(b => b.addEventListener('click', () => {
    if (_dvDados && _dvDados.perfil && typeof apMostrarPerfil === 'function') _apPerfil = _dvDados.perfil;
    apMenuTipo(b, b.dataset.dvTipo);
  }));
}

async function dvCarregar() {
  const dados = await acJson('/api/access-control/painel/dispositivos');
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
    _dvTestes[id] = { ok: false, erro: (err && err.message) || 'O leitor não respondeu.', em: Date.now() };
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
  dvTipoDoLocal();
  dvPrevia();
  dvCampo('dvGaveta').hidden = false;
  requestAnimationFrame(() => dvCampo('dvGaveta').classList.add('aberta'));
  setTimeout(() => (novo && !siteSugerido ? dvCampo('dvSite') : dvCampo('dvHost')).focus(), 150);
  if (window.lucide) lucide.createIcons();
}

// O tipo do local vem marcado (escolhido antes ou o palpite do SightOps).
function dvTipoDoLocal() {
  const site = dvCampo('dvSite').value.trim().toUpperCase();
  const l = (_dvDados.locais || []).find(x => x.site.toUpperCase() === site);
  const tipo = l ? l.tipo : (/\b(ESCOLA|COL[EÉ]GIO|CRECHE)\b/.test(site) ? 'escola' : '');
  dvMarcar('dvTipoLocal', tipo || '');
  dvCampo('dvTipoNota').textContent = !site ? 'Escolha o local acima.'
    : l && l.origem === 'escolhido' ? 'Já definido para este local. Mudar aqui vale para o local inteiro.'
      : tipo ? 'Sugestão do SightOps. Confirme ou troque: vale para o local inteiro.' : 'Diga o que este local é.';
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
      const r = await acJson(`/api/access-control/painel/ip-virtual?connector_id=${encodeURIComponent(cid)}&host=${encodeURIComponent(host)}`);
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
  const tipoLocal = dvCampo('dvTipoLocal').value;
  if (!tipoLocal) return dvErro('Diga se o local é escola, condomínio, empresa ou evento.');
  dvErro('');
  const botoes = document.querySelectorAll('#dvGaveta .dv-gaveta-pe button');
  botoes.forEach(b => { b.disabled = true; });
  try {
    const r = await acEnviar('POST', '/api/access-control/devices', p);
    const id = (r.device || {}).id;
    // Tipo do local: grava quando mudou ou quando ainda era so palpite.
    const l = (_dvDados.locais || []).find(x => x.site.toUpperCase() === p.site.toUpperCase());
    if (!l || l.origem !== 'escolhido' || l.tipo !== tipoLocal) {
      try { await acEnviar('PUT', '/api/access-control/painel/locais/tipo', { site: p.site, tipo: tipoLocal }); } catch (_) { /* o leitor ja foi salvo */ }
      if (typeof apRecarregarTudo === 'function' && (!l || l.tipo !== tipoLocal)) apRecarregarTudo();
    }
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
    acToast('Dispositivo excluído.');
    dvFechar();
    await dvCarregar();
  } catch (err) {
    dvErro((err && err.message) || 'Não foi possível excluir.');
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
    const campo = b.closest('[data-dv-seg]').dataset.dvSeg;
    dvMarcar(campo, b.dataset.valor);
    if (campo === 'dvTipoLocal') return;
    if (!_dvNomeManual) dvCampo('dvNome').value = dvNomeSugerido();
  }));
  dvCampo('dvSite').addEventListener('input', () => {
    const site = dvCampo('dvSite').value.trim().toUpperCase();
    const l = (_dvDados.locais || []).find(x => x.site.toUpperCase() === site);
    if (l && l.connector_id) dvOpcoesConector(l.connector_id);
    if (!_dvNomeManual) dvCampo('dvNome').value = dvNomeSugerido();
    dvTipoDoLocal();
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

// ---------------------------------------------------------------- gaveta Controladora
// Estado lido do leitor (so leitura) e os ajustes. Escrita so no clique, com
// confirmacao nas que mexem na porta ou derrubam o leitor.
let _dvcId = '';
let _dvcDiag = null;

function dvcDif(seg) {
  const a = Math.abs(seg);
  const txt = a < 60 ? `${a} s` : a < 3600 ? `${Math.round(a / 60)} min` : a < 86400 * 2 ? `${Math.floor(a / 3600)} h ${Math.round((a % 3600) / 60)} min` : `${Math.round(a / 86400)} dias`;
  return `${seg > 0 ? 'adiantado' : 'atrasado'} ${txt}`;
}

function dvcEstado() {
  const box = dvCampo('dvcEstado');
  const g = _dvcDiag;
  if (!g) { box.innerHTML = '<p class="dv-ajuda">Lendo o leitor…</p>'; return; }
  if (g.erro) { box.innerHTML = `<p class="dv-erro">${esc(g.erro)}</p>`; return; }
  const hora = 'diferenca_segundos' in g
    ? (g.hora_ok ? `<span class="dvc-ok">certa</span>` : `<span class="dvc-ruim">${dvcDif(g.diferenca_segundos)}</span>`)
    : '<span class="dvc-ruim">não leu</span>';
  const ntp = g.ntp ? (g.ntp.ativo ? `<span class="dvc-ok">ligada</span> · ${esc(g.ntp.servidor)}` : '<span class="dvc-at">desligada</span>') : '<span class="dv-ajuda">não leu</span>';
  const fuso = g.ntp ? (g.ntp.fuso_ok ? '<span class="dvc-ok">Brasília (GMT-03)</span>' : `<span class="dvc-at">${esc(g.ntp.fuso_desc || 'fuso ' + g.ntp.fuso)}</span>`) : '—';
  const porta = { aberta: '<span class="dvc-at">aberta</span>', fechada: '<span class="dvc-ok">fechada</span>', forcada: '<span class="dvc-ruim">forçada</span>' }[g.porta] || esc(g.porta || '—');
  box.innerHTML = `<dl class="dvc-grade">
      <div><dt>Hora do leitor</dt><dd class="monospace">${esc((g.hora_leitor || '—').replace(/^(\d{4})-(\d\d)-(\d\d)/, '$3/$2/$1'))}</dd><dd>${hora}</dd></div>
      <div><dt>Hora certa (Brasília)</dt><dd class="monospace">${esc((g.hora_certa || '').replace(/^(\d{4})-(\d\d)-(\d\d)/, '$3/$2/$1'))}</dd></div>
      <div><dt>Sincronização (NTP)</dt><dd>${ntp}</dd></div>
      <div><dt>Fuso</dt><dd>${fuso}</dd></div>
      <div><dt>Porta</dt><dd>${porta}</dd></div>
      <div><dt>Modelo</dt><dd>${esc(g.modelo || '—')}</dd></div>
      <div><dt>Firmware</dt><dd class="monospace">${esc(g.firmware || '—')}</dd></div>
      <div><dt>Nº de série</dt><dd class="monospace">${esc(g.serie || '—')}</dd></div>
    </dl>
    ${Object.keys(g.erros || {}).length ? `<small class="dv-ajuda">O leitor não respondeu a: ${Object.keys(g.erros).join(', ')}.</small>` : ''}`;
  if (g.ntp && g.ntp.servidor && !dvCampo('dvcNtp').dataset.mexido) dvCampo('dvcNtp').value = g.ntp.ativo ? g.ntp.servidor : 'a.ntp.br';
  if (window.lucide) lucide.createIcons();
}

async function dvcLer() {
  _dvcDiag = null;
  dvcEstado();
  try {
    _dvcDiag = await acJson(`/api/access-control/painel/controladora/${encodeURIComponent(_dvcId)}`);
  } catch (err) {
    _dvcDiag = { erro: `Não consegui ler o leitor: ${err.message}` };
  }
  dvcEstado();
}

function dvcResultado(id, ok, texto) {
  const el = dvCampo(id);
  el.className = 'dvc-res ' + (ok ? 'ok' : 'ruim');
  el.textContent = texto;
  el.hidden = false;
}

async function dvcAcao(btn, resId, fn, okTxt) {
  btn.disabled = true;
  const original = btn.innerHTML;
  btn.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i> Enviando…';
  if (window.lucide) lucide.createIcons();
  try {
    const r = await fn();
    dvcResultado(resId, true, typeof okTxt === 'function' ? okTxt(r) : okTxt);
    return r;
  } catch (err) {
    dvcResultado(resId, false, err.message || 'O leitor recusou.');
    return null;
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
    if (window.lucide) lucide.createIcons();
  }
}

function dvcAbrir(id) {
  const d = (_dvDados.dispositivos || []).find(x => x.id === id);
  if (!d) return;
  _dvcId = id;
  dvCampo('dvcTitulo').textContent = d.nome;
  const ip = d.ip || {};
  dvCampo('dvcSub').textContent = [[DV_FABRICANTE[d.fabricante] || d.fabricante, d.modelo].filter(Boolean).join(' '), ip.traduzido ? `${d.host} → ${ip.virtual}` : d.host].filter(Boolean).join(' · ');
  dvCampo('dvcNtp').value = 'a.ntp.br';
  delete dvCampo('dvcNtp').dataset.mexido;
  ['dvcResHora', 'dvcResNtp', 'dvcResPorta', 'dvcResTeste', 'dvcResReinicio'].forEach(x => { dvCampo(x).hidden = true; });
  dvCampo('dvcGaveta').hidden = false;
  requestAnimationFrame(() => dvCampo('dvcGaveta').classList.add('aberta'));
  dvcLer();
  if (window.lucide) lucide.createIcons();
}

function dvcFechar() {
  const g = dvCampo('dvcGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function dvcLigar() {
  dvCampo('dvcFechar').addEventListener('click', dvcFechar);
  dvCampo('dvcFundo').addEventListener('click', dvcFechar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !dvCampo('dvcGaveta').hidden) dvcFechar(); });
  dvCampo('dvcLer').addEventListener('click', dvcLer);
  dvCampo('dvcWeb').addEventListener('click', () => {
    const d = (_dvDados.dispositivos || []).find(x => x.id === _dvcId);
    if (d) acAbrirWeb(d.host, 80);
  });
  dvCampo('dvcEditar').addEventListener('click', () => {
    const d = (_dvDados.dispositivos || []).find(x => x.id === _dvcId);
    dvcFechar();
    if (d) setTimeout(() => dvAbrir(d), 220);
  });
  dvCampo('dvcNtp').addEventListener('input', () => { dvCampo('dvcNtp').dataset.mexido = '1'; });
  dvCampo('dvcHora').addEventListener('click', ev => dvcAcao(ev.currentTarget, 'dvcResHora',
    () => acEnviar('POST', `/api/access-control/painel/controladora/${encodeURIComponent(_dvcId)}/hora`),
    r => `Hora acertada para ${r.hora.slice(11)} de ${r.hora.slice(0, 10).split('-').reverse().join('/')}.`).then(r => { if (r) dvcLer(); }));
  dvCampo('dvcNtpLigar').addEventListener('click', ev => dvcAcao(ev.currentTarget, 'dvcResNtp',
    () => acEnviar('POST', `/api/access-control/painel/controladora/${encodeURIComponent(_dvcId)}/ntp`, { servidor: dvCampo('dvcNtp').value.trim(), ativar: true }),
    r => `Sincronização ligada com ${r.servidor}, fuso de Brasília. O leitor precisa alcançar a internet.`).then(r => { if (r) dvcLer(); }));
  dvCampo('dvcNtpDesligar').addEventListener('click', ev => dvcAcao(ev.currentTarget, 'dvcResNtp',
    () => acEnviar('POST', `/api/access-control/painel/controladora/${encodeURIComponent(_dvcId)}/ntp`, { ativar: false }),
    'Sincronização desligada.').then(r => { if (r) dvcLer(); }));
  dvCampo('dvcAbrirPorta').addEventListener('click', ev => {
    const b = ev.currentTarget;
    dvConfirmar(b, 'Confirmar abrir', () => dvcAcao(b, 'dvcResPorta',
      () => acEnviar('POST', `/api/access-control/devices/${encodeURIComponent(_dvcId)}/open-door?channel=1`), 'Porta aberta.').then(r => { if (r) dvcLer(); }));
  });
  dvCampo('dvcFecharPorta').addEventListener('click', ev => {
    const b = ev.currentTarget;
    dvConfirmar(b, 'Confirmar fechar', () => dvcAcao(b, 'dvcResPorta',
      () => acEnviar('POST', `/api/access-control/painel/controladora/${encodeURIComponent(_dvcId)}/fechar?canal=1`), 'Porta fechada.').then(r => { if (r) dvcLer(); }));
  });
  dvCampo('dvcTestar').addEventListener('click', ev => dvcAcao(ev.currentTarget, 'dvcResTeste', async () => {
    const t0 = performance.now();
    await acEnviar('POST', `/api/access-control/devices/${encodeURIComponent(_dvcId)}/test`);
    return { ms: performance.now() - t0 };
  }, r => `Respondeu em ${(r.ms / 1000).toFixed(1).replace('.', ',')} s.`).then(r => { if (r) dvCarregar().catch(() => {}); }));
  dvCampo('dvcReiniciar').addEventListener('click', ev => {
    const b = ev.currentTarget;
    dvConfirmar(b, 'Confirmar reiniciar', () => dvcAcao(b, 'dvcResReinicio',
      () => acEnviar('POST', `/api/access-control/painel/reiniciar-controladora/${encodeURIComponent(_dvcId)}`),
      'Reiniciando. O leitor volta em cerca de 1 minuto; até lá a porta não reconhece ninguém.'));
  });
  dvCampo('dvcExcluir').addEventListener('click', ev => {
    const b = ev.currentTarget;
    const d = (_dvDados.dispositivos || []).find(x => x.id === _dvcId) || {};
    dvConfirmar(b, `Confirmar excluir ${d.nome || ''}`.trim(), () => dvcAcao(b, 'dvcResReinicio',
      () => acEnviar('DELETE', `/api/access-control/devices/${encodeURIComponent(_dvcId)}`), 'Excluído.').then(r => {
      if (!r) return;
      acToast(`${d.nome || 'Leitor'} excluído do SightOps.`);
      dvcFechar();
      dvCarregar().catch(() => {});
    }));
  });
}

// Chamado pelo Painel ao abrir a aba: liga os botoes na primeira vez e carrega.
let _dvLigado = false;
async function dvAbrirAba() {
  if (!_dvLigado) {
    _dvLigado = true;
    dvLigarGaveta();
    dvcLigar();
    dvCampo('dvNovo').addEventListener('click', () => dvAbrir(null, typeof _apSite === 'string' ? _apSite : ''));
    dvCampo('dvBusca').addEventListener('input', ev => { _dvBusca = ev.target.value; dvDesenhar(); });
  }
  if (_dvDados) dvDesenhar();
  try {
    await dvCarregar();
  } catch (err) {
    if (!_dvDados) dvCampo('dvConteudo').innerHTML = `<p class="ap-vazio">Não consegui carregar os dispositivos: ${esc((err && err.message) || err)}</p>`;
  }
}
