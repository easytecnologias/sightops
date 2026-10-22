// Aba Pessoas do Painel de Acesso (/v3/acesso/#pessoas).
// Lista: GET /api/access-control/painel/pessoas (so leitura).
// Salvar: POST /people (rota de sempre: CPF obrigatorio, matricula do aluno,
// casamento por CPF/matricula). Foto: POST /people/{id}/face-photo.
// Grupos: PUT /painel/pessoas/{id}/grupos (so as linhas desta pessoa).
// Excluir: POST /painel/pessoas/{id}/excluir (tira dos leitores antes de apagar).
// save_person faz UPDATE completo e, sem id, casa por CPF/matricula: a tela
// reenvia todos os campos ao editar e barra "nova pessoa" com CPF/matricula
// que ja existem, em vez de sobrescrever alguem sem avisar.

let _psDados = null;
let _psBusca = '';
let _psFiltro = 'todos';
let _psMostrar = 120;
let _psEditando = null;
let _psFoto = null;          // Blob ja redimensionado, pronto para enviar
let _psLigado = false;

const PS_TIPOS = {
  escola: [['student', 'Aluno', 'graduation-cap'], ['employee', 'Funcionário', 'briefcase'], ['visitor', 'Visitante', 'user-round']],
  condominio: [['resident', 'Morador', 'home'], ['employee', 'Funcionário', 'briefcase'], ['contractor', 'Prestador', 'wrench'], ['visitor', 'Visitante', 'user-round']],
  empresa: [['employee', 'Colaborador', 'briefcase'], ['contractor', 'Prestador', 'wrench'], ['visitor', 'Visitante', 'user-round']],
  evento: [['participant', 'Participante', 'ticket'], ['staff', 'Equipe', 'badge-check'], ['visitor', 'Convidado', 'user-round']],
};
// Tipo antigo que nao existe no tipo do local (ex.: "Aluno" num condominio)
// vira o principal daquele local ao salvar; a gaveta avisa antes.
function psTiposDoLocal(site) { return PS_TIPOS[psTipoLocal(site)] || PS_TIPOS.escola; }
// Equivalencia do tipo antigo em cada tipo de local (o mesmo que AP_VOCAB mostra).
const PS_EQUIVALE = {
  escola: { resident: 'student', participant: 'student', staff: 'employee', contractor: 'employee' },
  condominio: { student: 'resident', participant: 'resident', staff: 'employee' },
  empresa: { student: 'employee', resident: 'employee', participant: 'employee', staff: 'employee' },
  evento: { student: 'participant', resident: 'participant', employee: 'staff', contractor: 'staff' },
};
function psTipoNoLocal(tipo, site) {
  const lista = psTiposDoLocal(site);
  if (lista.some(x => x[0] === tipo)) return tipo;
  const eq = (PS_EQUIVALE[psTipoLocal(site)] || {})[tipo];
  return eq && lista.some(x => x[0] === eq) ? eq : lista[0][0];
}

function psCampo(id) { return document.getElementById(id); }
function psTipoLocal(site) { return typeof apTipoLocal === 'function' ? apTipoLocal(site) : 'escola'; }
function psCondo(site) { return psTipoLocal(site) === 'condominio'; }
function psTipoRot(p) {
  return (typeof apTipo === 'function' && apTipo(p.tipo, p.site)) || p.tipo;
}
function psDigitos(v) { return String(v || '').replace(/\D/g, ''); }
function psCpfFmt(v) {
  const d = psDigitos(v).slice(0, 11);
  return d.replace(/^(\d{3})(\d)/, '$1.$2').replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3').replace(/\.(\d{3})(\d{1,2})$/, '.$1-$2');
}
function psCpfValido(v) {
  const d = psDigitos(v);
  if (d.length !== 11 || /^(\d)\1{10}$/.test(d)) return false;
  const dv = n => { let s = 0; for (let i = 0; i < n; i++) s += +d[i] * (n + 1 - i); const r = (s * 10) % 11; return r === 10 ? 0 : r; };
  return dv(9) === +d[9] && dv(10) === +d[10];
}
function psFoneFmt(v) {
  let d = psDigitos(v);
  if (d.startsWith('55') && d.length > 11) d = d.slice(2);
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return v || '';
}
function psIniciais(n) { return String(n || '?').trim().split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase() || '?'; }
function psFotoUrl(p) { return `${API_BASE}/api/access-control/people/${encodeURIComponent(p.id)}/face-photo?t=${encodeURIComponent(p.foto_em || '')}`; }
function psLocalData(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T')); return isNaN(d) ? null : d; }

// Situacao da pessoa nos leitores, resumida em um estado.
function psSituacao(p) {
  const l = p.leitores || [];
  if (!p.ativo) return { cls: 'inativo', txt: 'Inativa · bloqueada nos leitores' };
  if (!p.grupos.length) return { cls: 'atencao', txt: 'Sem grupo · não abre nenhuma porta' };
  const rec = l.filter(x => x.status === 'failed');
  const pend = l.filter(x => x.status !== 'ok' && x.status !== 'failed');
  const ok = l.filter(x => x.status === 'ok');
  const nomes = arr => arr.map(x => apPorta(x.leitor)).join(', ');
  const qtos = (arr, um, varios) => (arr.length === 1 ? `${um} ${apPorta(arr[0].leitor)}` : `${varios.replace('#', arr.length)}`);
  if (rec.length) return { cls: 'ruim', txt: 'Foto recusada ' + qtos(rec, 'no', 'em # leitores'), erro: `${nomes(rec)}: ${rec[0].erro}` };
  if (pend.length) return { cls: 'espera', txt: 'Enviando ' + qtos(pend, 'para', 'para # leitores'), erro: nomes(pend) };
  if (!p.tem_foto) return { cls: 'atencao', txt: 'Sem foto', erro: ok.length ? 'No leitor só com cartão ou senha: ' + nomes(ok) : '' };
  if (ok.length) return { cls: 'ok', txt: qtos(ok, 'No leitor', 'Nos # leitores'), erro: nomes(ok) };
  return { cls: 'espera', txt: 'Aguardando envio' };
}

const PS_PLURAL = { Aluno: 'Alunos', Morador: 'Moradores', 'Funcionário': 'Funcionários', Prestador: 'Prestadores', Visitante: 'Visitantes',
  Colaborador: 'Colaboradores', Participante: 'Participantes', Equipe: 'Equipe', Convidado: 'Convidados' };
function psFiltros() {
  const tipos = PS_TIPOS[(_apPerfil && _apPerfil.tipo) || 'escola'] || PS_TIPOS.escola;
  return [['todos', 'Todas', () => true]]
    .concat(tipos.map(([v, rot]) => [v, PS_PLURAL[rot] || rot, p => psTipoNoLocal(p.tipo, p.site) === v]))
    .concat(PS_FILTROS);
}
const PS_FILTROS = [
  ['semfoto', 'Sem foto', p => p.ativo && !p.tem_foto],
  ['recusada', 'Foto recusada', p => (p.leitores || []).some(x => x.status === 'failed')],
  ['semgrupo', 'Sem grupo', p => p.ativo && !p.grupos.length],
  // Trazidas do leitor (que nao guarda CPF): o ID no leitor e a identidade ate preencher.
  ['semcpf', 'Sem CPF', p => !psDigitos(p.cpf)],
  ['inativos', 'Inativas', p => !p.ativo],
];

// ---------------------------------------------------------------- lista
function psCards(lista) {
  const ativas = lista.filter(p => p.ativo);
  const comFoto = ativas.filter(p => p.tem_foto && (p.leitores || []).some(x => x.status === 'ok')).length;
  const recusadas = lista.filter(p => (p.leitores || []).some(x => x.status === 'failed')).length;
  const semGrupo = ativas.filter(p => !p.grupos.length).length;
  const escola = (_apPerfil && _apPerfil.tipo) === 'escola';
  const semResp = ativas.filter(p => p.tipo === 'student' && !psDigitos(p.telefone)).length;
  const card = ({ icone, cor, estado = '', rot, val, sub, subCor = '', filtro = '' }) => `
    <button type="button" class="ap-card ${estado}" ${filtro ? `data-ps-filtro="${filtro}"` : 'disabled'}>
      <span class="metric-icon ${cor}"><i data-lucide="${icone}"></i></span>
      <span class="ap-card-txt"><span class="ap-card-rot">${rot}</span>
        <strong class="ap-card-val">${val}</strong><small class="${subCor}">${sub}</small></span>
    </button>`;
  return `<div class="ap-cards">
    ${card({ icone: 'users', cor: 'blue', rot: 'Pessoas ativas', val: apNum(ativas.length), sub: `${apNum(lista.length - ativas.length)} inativa${lista.length - ativas.length === 1 ? '' : 's'}` })}
    ${card({ icone: 'scan-face', cor: 'green', rot: 'Rosto nos leitores', val: `${apNum(comFoto)}<span class="ap-card-de">/${apNum(ativas.length)}</span>`, sub: 'abrem a porta pelo rosto', filtro: 'semfoto' })}
    ${card({ icone: 'image-off', cor: recusadas ? 'amber' : 'green', estado: recusadas ? 'atencao' : '', rot: 'Fotos recusadas', val: apNum(recusadas), sub: recusadas ? 'trocar a foto' : 'nenhuma recusada', subCor: recusadas ? 'atencao' : '', filtro: recusadas ? 'recusada' : '' })}
    ${card({ icone: 'door-closed', cor: semGrupo ? 'amber' : 'green', estado: semGrupo ? 'atencao' : '', rot: 'Sem grupo', val: apNum(semGrupo), sub: semGrupo ? 'não abrem nenhuma porta' : 'todas com acesso', subCor: semGrupo ? 'atencao' : '', filtro: semGrupo ? 'semgrupo' : '' })}
    ${escola ? card({ icone: 'phone-off', cor: semResp ? 'amber' : 'green', rot: 'Sem responsável', val: apNum(semResp), sub: semResp ? 'alunos sem aviso no WhatsApp' : 'todos com telefone' }) : ''}
  </div>`;
}

function psLinha(p) {
  const s = psSituacao(p);
  const condo = psCondo(p.site);
  const escolaLocal = psTipoLocal(p.site) === 'escola';
  const unidade = condo ? (p.turma || (typeof apUnidade === 'function' ? apUnidade(p.nome, p.site) : '')) : '';
  const ult = psLocalData(p.ultima);
  const det = [psTipoRot(p), condo ? (unidade ? 'unidade ' + unidade : '') : p.turma, p.matricula && escolaLocal ? 'matr. ' + p.matricula : '']
    .filter(Boolean).join(' · ');
  return `<div class="ps-linha ${p.ativo ? '' : 'inativo'}" data-ps="${esc(p.id)}">
    <span class="ps-av">${psIniciais(p.nome)}${p.tem_foto ? `<img src="${psFotoUrl(p)}" alt="" loading="lazy" onerror="this.remove()">` : ''}</span>
    <div class="ps-quem"><b>${esc(p.nome)}</b><small>${esc(det)}</small></div>
    <div class="ps-sit ${s.cls}" ${s.erro ? `title="${esc(s.erro)}"` : ''}><i></i><span>${esc(s.txt)}</span></div>
    <div class="ps-resp">${!escolaLocal
      ? `<span class="dv-l-rot">Local</span><div>${esc(p.site || '—')}</div>`
      : `<span class="dv-l-rot">Responsável</span><div>${esc(p.responsavel || '—')}</div><small class="monospace">${esc(psFoneFmt(p.telefone)) || (p.tipo === 'student' ? '<span class="ps-falta">sem telefone</span>' : '')}</small>`}</div>
    <div class="ps-ult"><span class="dv-l-rot">Última passagem</span><div>${ult ? (Date.now() - ult < 86400000 ? 'hoje ' + apHm(ult) : ult.toLocaleDateString('pt-BR')) : '—'}</div></div>
    <button type="button" class="dv-btn" data-ps-editar="${esc(p.id)}"><i data-lucide="pencil"></i><span>Editar</span></button>
  </div>`;
}

function psDesenhar() {
  const el = psCampo('psConteudo');
  if (!el || !_psDados) return;
  const todas = _psDados.pessoas || [];
  const b = _psBusca.trim().toLowerCase();
  const bDig = psDigitos(b);
  const filtros = psFiltros();
  const f = (filtros.find(x => x[0] === _psFiltro) || filtros[0])[2];
  const lista = todas.filter(p => f(p) && (!b || [p.nome, p.turma, p.matricula, p.responsavel, p.site].some(x => String(x || '').toLowerCase().includes(b))
    || (bDig.length >= 3 && (psDigitos(p.cpf).includes(bDig) || psDigitos(p.telefone).includes(bDig)))));
  const conta = fn => todas.filter(fn).length;
  el.innerHTML = `
    ${psCards(todas)}
    <div class="ps-filtros">${filtros.map(([id, rot, fn]) => {
      const n = conta(fn);
      return (id === 'todos' || n || id === _psFiltro) ? `<button type="button" class="ap-fl ${_psFiltro === id ? 'on' : ''}" data-ps-filtro="${id}">${rot} <span class="monospace">${apNum(n)}</span></button>` : '';
    }).join('')}</div>
    ${lista.length ? `<div class="dv-lista ps-lista">${lista.slice(0, _psMostrar).map(psLinha).join('')}</div>
      ${lista.length > _psMostrar ? `<button type="button" class="ps-mais" data-ps-mais>Mostrar mais ${apNum(Math.min(120, lista.length - _psMostrar))} de ${apNum(lista.length - _psMostrar)}</button>` : ''}`
    : `<div class="dv-vazio"><i data-lucide="${b ? 'search-x' : 'users'}"></i><b>${b ? 'Ninguém com “' + esc(_psBusca) + '”' : 'Ninguém neste filtro'}</b>
      <p>${b ? 'Busque por nome, CPF, matrícula, turma ou responsável.' : 'Troque o filtro ou cadastre uma pessoa.'}</p></div>`}`;
  el.querySelectorAll('[data-ps-filtro]').forEach(x => x.addEventListener('click', () => { _psFiltro = x.dataset.psFiltro; _psMostrar = 120; psDesenhar(); }));
  el.querySelectorAll('[data-ps-editar]').forEach(x => x.addEventListener('click', () => psAbrir(todas.find(p => p.id === x.dataset.psEditar))));
  el.querySelectorAll('.ps-linha').forEach(x => x.addEventListener('dblclick', () => psAbrir(todas.find(p => p.id === x.dataset.ps))));
  el.querySelector('[data-ps-mais]')?.addEventListener('click', () => { _psMostrar += 120; psDesenhar(); });
  if (window.lucide) lucide.createIcons();
}

async function psCarregar() {
  const q = typeof _apSite === 'string' && _apSite ? `?site=${encodeURIComponent(_apSite)}` : '';
  const dados = await acJson(`/api/access-control/painel/pessoas${q}`);
  if (!dados) return;
  _psDados = dados;
  if (dados.perfil && typeof apMostrarPerfil === 'function') apMostrarPerfil(dados.perfil);
  psDesenhar();
}

// ---------------------------------------------------------------- gaveta
function psMarcar(id, valor) {
  psCampo(id).value = valor;
  document.querySelectorAll(`[data-ps-seg="${id}"] button`).forEach(b => {
    const on = b.dataset.valor === valor;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', String(on));
  });
}

function psAjustarPorLocal() {
  const site = psCampo('psSite').value;
  const condo = psCondo(site);
  const tipoLocal = psTipoLocal(site);
  const tipoAtual = psCampo('psTipo').value;
  psCampo('psTipos').innerHTML = psTiposDoLocal(site).map(([v, rot, ic]) =>
    `<button type="button" data-valor="${v}"><i data-lucide="${ic}"></i>${rot}</button>`).join('');
  psCampo('psTipos').querySelectorAll('button').forEach(b => b.addEventListener('click', () => { psMarcar('psTipo', b.dataset.valor); psAjustarPorTipo(); }));
  psMarcar('psTipo', tipoAtual ? psTipoNoLocal(tipoAtual, site) : psTiposDoLocal(site)[0][0]);
  const v = (typeof AP_VOCAB !== 'undefined' && AP_VOCAB[tipoLocal]) || {};
  psCampo('psRotTurma').textContent = v.grupo || 'Turma';
  psCampo('psRotCpf').textContent = condo ? 'CPF (opcional)' : 'CPF';
  psCampo('psTurma').placeholder = { escola: 'Ex.: 4º Ano', condominio: 'Ex.: A01, Bloco C 06', empresa: 'Ex.: Financeiro', evento: 'Ex.: VIP, Imprensa' }[tipoLocal] || '';
  const turmas = [...new Set((_psDados.pessoas || []).filter(p => p.site === site && p.turma).map(p => p.turma))].sort((a, b) => a.localeCompare(b, 'pt-BR', { numeric: true }));
  psCampo('psTurmas').innerHTML = turmas.map(t => `<option value="${esc(t)}">`).join('');
  // Avisos valem para todo tipo de local (o e-mail tambem serve a empresa e
  // condominio); fora da escola o contato e a propria pessoa.
  psCampo('psRotResp').textContent = tipoLocal === 'escola' ? 'Responsável' : 'Contato';
  psGrupos();
  psAjustarPorTipo();
  if (window.lucide) lucide.createIcons();
}

function psAjustarPorTipo() {
  const tipo = psCampo('psTipo').value;
  const aluno = tipo === 'student';
  psCampo('psMatriculaBox').hidden = !aluno;
  const ant = _psEditando && _psEditando.tipo;
  const mudou = ant && ant !== tipo;
  psCampo('psNotaTipo').hidden = !mudou;
  if (mudou) {
    const rot = t => (psTiposDoLocal(psCampo('psSite').value).find(x => x[0] === t) || [, ({ student: 'Aluno', resident: 'Morador', employee: 'Funcionário', visitor: 'Visitante' })[t] || t])[1];
    psCampo('psNotaTipo').textContent = `Estava cadastrada como ${rot(ant)}. Vai ser salva como ${rot(tipo)}.`;
  }
}

function psGrupos() {
  const site = psCampo('psSite').value.toUpperCase();
  const marcados = new Set([...document.querySelectorAll('#psGrupos input:checked')].map(x => x.value).concat(psCampo('psGrupos').dataset.iniciais ? psCampo('psGrupos').dataset.iniciais.split(',') : []));
  psCampo('psGrupos').dataset.iniciais = '';
  const grupos = (_psDados.grupos || []).slice().sort((a, b) => ((b.site.toUpperCase() === site) - (a.site.toUpperCase() === site)) || a.nome.localeCompare(b.nome, 'pt-BR'));
  psCampo('psGrupos').innerHTML = grupos.length ? grupos.map(g => {
    const outro = site && g.site && g.site.toUpperCase() !== site;
    return `<label class="ps-grupo ${outro ? 'outro' : ''}"><input type="checkbox" value="${esc(g.id)}" ${marcados.has(g.id) ? 'checked' : ''}>
      <span class="ps-grupo-box"><b>${esc(g.nome)}</b>
        <small>${g.leitores.length ? 'abre ' + g.leitores.map(l => esc(apPorta(l.nome))).join(', ') : '<span class="ps-falta">sem porta ligada</span>'}${outro ? ' · ' + esc(g.site) : ''} · ${apNum(g.membros)} pessoa${g.membros === 1 ? '' : 's'}</small></span></label>`;
  }).join('') : '<p class="dv-ajuda">Nenhum grupo cadastrado. Sem grupo a pessoa não vai para nenhum leitor.</p>';
}

function psFotoVer(url, txt) {
  const box = psCampo('psFotoVer');
  box.innerHTML = url ? `<img src="${url}" alt="" onerror="this.replaceWith(document.createTextNode('${esc(txt || '?').replace(/'/g, '')}'))">` : `<span>${esc(txt || '?')}</span>`;
}

function psSituacaoLeitores(p) {
  const el = psCampo('psLeitores');
  const l = (p && p.leitores) || [];
  el.innerHTML = l.length ? l.map(x => `<div class="ps-lt ${x.status === 'ok' ? 'ok' : x.status === 'failed' ? 'ruim' : 'espera'}">
      <i data-lucide="${x.status === 'ok' ? 'check' : x.status === 'failed' ? 'x' : 'loader-circle'}"></i>
      <b>${esc(apPorta(x.leitor))}</b><span>${x.status === 'ok' ? 'cadastrada' : x.status === 'failed' ? esc(x.erro || 'recusada') : 'aguardando envio'}</span></div>`).join('')
    : `<p class="dv-ajuda">${p ? 'Ainda não foi enviada a nenhum leitor.' : 'Depois de salvar, a pessoa vai para os leitores dos grupos marcados.'}</p>`;
}

function psAbrir(p) {
  _psEditando = p || null;
  _psFoto = null;
  const novo = !p;
  psCampo('psTitulo').textContent = novo ? 'Nova pessoa' : 'Editar pessoa';
  psCampo('psSubtitulo').textContent = novo ? 'Cadastro e acesso aos leitores.' : p.nome;
  psCampo('psSites').innerHTML = (_psDados.sites || []).map(s => `<option value="${esc(s)}">`).join('');
  psCampo('psSite').value = novo ? (typeof _apSite === 'string' ? _apSite : '') : p.site;
  psCampo('psTipo').value = novo ? '' : p.tipo;
  psCampo('psNome').value = novo ? '' : p.nome;
  psCampo('psCpf').value = novo ? '' : psCpfFmt(p.cpf);
  psCampo('psMatricula').value = novo ? '' : p.matricula;
  psCampo('psTurma').value = novo ? '' : p.turma;
  psCampo('psResp').value = novo ? '' : p.responsavel;
  psCampo('psFone').value = novo ? '' : psFoneFmt(p.telefone);
  psCampo('psZap').checked = novo ? true : p.whatsapp;
  psCampo('psEmail').value = novo ? '' : (p.email || '');
  psCampo('psAvisaEmail').checked = novo ? true : p.avisa_email !== false;
  psCampo('psAtivo').checked = novo ? true : p.ativo;
  psCampo('psNotas').value = novo ? '' : p.notas;
  psCampo('psIdLeitor').textContent = novo ? 'gerado ao salvar' : (p.id_controladora || 'sem ID: não vai para leitor Intelbras');
  psCampo('psGrupos').dataset.iniciais = novo ? '' : p.grupos.join(',');
  psCampo('psGrupos').innerHTML = '';
  psFotoVer(!novo && p.tem_foto ? psFotoUrl(p) : '', novo ? '?' : psIniciais(p.nome));
  psCampo('psFotoArq').value = '';
  psSituacaoLeitores(p);
  psCampo('psExcluir').hidden = novo;
  psCampo('psConfirma').hidden = true;
  psCampo('psErro').hidden = true;
  psCampo('psResultado').hidden = true;
  psAjustarPorLocal();
  psCampo('psGaveta').hidden = false;
  requestAnimationFrame(() => psCampo('psGaveta').classList.add('aberta'));
  setTimeout(() => psCampo(novo && !psCampo('psSite').value ? 'psSite' : 'psNome').focus(), 150);
  if (window.lucide) lucide.createIcons();
}

function psFechar() {
  const g = psCampo('psGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function psErro(msg, html) {
  const e = psCampo('psErro');
  if (html) e.innerHTML = html; else e.textContent = msg || '';
  e.hidden = !(msg || html);
  if (!e.hidden) e.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Foto: reduz para no maximo 800 px e JPEG antes de enviar. Leitor recusa foto
// grande demais; e upload de celular chega com 4-8 MB.
function psPrepararFoto(arquivo) {
  return new Promise((ok, falha) => {
    if (!/^image\//.test(arquivo.type)) return falha(new Error('Escolha uma imagem (JPG ou PNG).'));
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 800 / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      c.toBlob(b => (b ? ok(b) : falha(new Error('Não consegui ler a foto.'))), 'image/jpeg', 0.9);
    };
    img.onerror = () => falha(new Error('Não consegui abrir a imagem.'));
    img.src = URL.createObjectURL(arquivo);
  });
}

async function psEscolherFoto(arquivo) {
  if (!arquivo) return;
  try {
    _psFoto = await psPrepararFoto(arquivo);
    psFotoVer(URL.createObjectURL(_psFoto));
    psCampo('psFotoNota').textContent = 'Foto nova: vai para os leitores ao salvar.';
  } catch (err) {
    psErro(err.message);
  }
}

function psPayload() {
  const p = _psEditando || {};
  const tipo = psCampo('psTipo').value;
  return {
    id: p.id || '',
    full_name: psCampo('psNome').value.trim().replace(/\s+/g, ' '),
    person_type: tipo,
    document_id: psDigitos(psCampo('psCpf').value),
    enrollment_code: tipo === 'student' ? psCampo('psMatricula').value.trim() : (p.matricula || ''),
    class_name: psCampo('psTurma').value.trim(),
    site: psCampo('psSite').value.trim(),
    controller_user_id: p.id_controladora || '',
    guardian_name: psCampo('psResp').value.trim(),
    guardian_phone: psDigitos(psCampo('psFone').value),
    whatsapp_enabled: psCampo('psZap').checked,
    guardian_email: psCampo('psEmail').value.trim(),
    email_enabled: psCampo('psAvisaEmail').checked,
    active: psCampo('psAtivo').checked,
    notes: psCampo('psNotas').value.trim(),
  };
}

async function psEnviarFoto(id, blob) {
  const fd = new FormData();
  fd.append('file', blob, 'rosto.jpg');
  const res = await fetch(`${API_BASE}/api/access-control/people/${encodeURIComponent(id)}/face-photo`, { method: 'POST', credentials: 'same-origin', body: fd });
  if (!res.ok) {
    let d = ''; try { d = (await res.json()).detail; } catch (_) {}
    throw new Error(typeof d === 'string' && d ? d : 'HTTP ' + res.status);
  }
}

async function psSalvar() {
  const p = psPayload();
  if (!p.site) return psErro('Escolha o local da pessoa.');
  if (!p.person_type) return psErro('Escolha o tipo da pessoa.');
  if (p.full_name.length < 3) return psErro('Informe o nome completo.');
  // CPF: escola, empresa e evento exigem; condominio nao (o SightOps gera o ID
  // no leitor). Quem veio do leitor tambem pode ficar sem ate alguem preencher.
  const semCpfOk = psCondo(p.site) || !!p.controller_user_id;
  if (p.document_id === '' ? !semCpfOk : !psCpfValido(p.document_id)) return psErro(p.document_id ? 'CPF inválido. Confira os 11 dígitos.' : 'Informe o CPF da pessoa.');
  if (p.person_type === 'student' && !p.enrollment_code) return psErro('Informe a matrícula do aluno.');
  // Sem id, o backend casa por CPF/matricula e ATUALIZA quem ja existe: barra aqui.
  if (!p.id) {
    // CPF vazio nao e duplicata de quem tambem nao tem CPF.
    const dup = (_psDados.pessoas || []).find(x => (p.document_id && psDigitos(x.cpf) === p.document_id) || (p.enrollment_code && x.matricula === p.enrollment_code));
    if (dup) {
      psErro('', `${p.document_id && psDigitos(dup.cpf) === p.document_id ? 'Este CPF' : 'Esta matrícula'} já é de <b>${esc(dup.nome)}</b>. <button type="button" class="ps-link" id="psAbrirDup">Abrir o cadastro dela</button>`);
      psCampo('psAbrirDup').addEventListener('click', () => psAbrir(dup));
      return;
    }
  }
  psErro('');
  const grupos = [...document.querySelectorAll('#psGrupos input:checked')].map(x => x.value);
  const botoes = document.querySelectorAll('#psGaveta .dv-gaveta-pe button');
  botoes.forEach(b => { b.disabled = true; });
  try {
    const r = await acEnviar('POST', '/api/access-control/people', p);
    const id = (r.person || {}).id;
    const avisos = [];
    if (id && _psFoto) {
      try { await psEnviarFoto(id, _psFoto); } catch (err) { avisos.push('A foto não foi aceita: ' + err.message); }
    }
    const antes = (_psEditando && _psEditando.grupos) || [];
    if (id && (grupos.join() !== antes.slice().sort().join() || !p.id)) {
      const g = await acEnviar('PUT', `/api/access-control/painel/pessoas/${encodeURIComponent(id)}/grupos`, { grupos });
      (g.falhas_remocao || []).forEach(f => avisos.push(`Não consegui tirar do leitor ${f.leitor}: ${f.erro}`));
    }
    psFechar();
    await psCarregar();
    acToast(avisos.length ? avisos.join(' · ') : (p.id ? 'Cadastro atualizado. Enviando para os leitores.' : 'Pessoa cadastrada. Enviando para os leitores.'), avisos.length > 0);
    const linha = id && document.querySelector(`[data-ps="${CSS.escape(id)}"]`);
    if (linha) { linha.scrollIntoView({ behavior: 'smooth', block: 'center' }); linha.classList.add('destaque'); }
  } catch (err) {
    psErro((err && err.message) || 'Não foi possível salvar.');
  } finally {
    botoes.forEach(b => { b.disabled = false; });
  }
}

async function psExcluir() {
  const p = _psEditando;
  if (!p) return;
  const btn = psCampo('psConfirmaSim');
  btn.disabled = true;
  btn.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i> Removendo dos leitores…';
  if (window.lucide) lucide.createIcons();
  try {
    const r = await acEnviar('POST', `/api/access-control/painel/pessoas/${encodeURIComponent(p.id)}/excluir`);
    if (r.excluida) {
      psFechar();
      await psCarregar();
      acToast(`${p.nome} excluída${r.removidos.length ? ' e removida de ' + r.removidos.join(', ') : ''}.`);
      return;
    }
    psCampo('psConfirma').hidden = true;
    const res = psCampo('psResultado');
    res.hidden = false;
    res.innerHTML = `<b>Não excluí: algum leitor não respondeu.</b>
      ${r.removidos.length ? `<span>Removida de ${esc(r.removidos.join(', '))}.</span>` : ''}
      ${r.falhas.map(f => `<span>${esc(f.leitor)}: ${esc(f.erro)}</span>`).join('')}
      <span>A pessoa ficou <b>desativada</b>: o leitor a bloqueia quando voltar. Tente excluir de novo depois.</span>`;
    await psCarregar();
  } catch (err) {
    psErro((err && err.message) || 'Não foi possível excluir.');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Excluir';
  }
}

function psLigarGaveta() {
  psCampo('psFechar').addEventListener('click', psFechar);
  psCampo('psCancelar').addEventListener('click', psFechar);
  psCampo('psFundo').addEventListener('click', psFechar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !psCampo('psGaveta').hidden) psFechar(); });
  psCampo('psForm').addEventListener('submit', ev => { ev.preventDefault(); psSalvar(); });
  psCampo('psSite').addEventListener('change', psAjustarPorLocal);
  psCampo('psSite').addEventListener('input', () => { if ((_psDados.sites || []).includes(psCampo('psSite').value)) psAjustarPorLocal(); });
  psCampo('psCpf').addEventListener('input', ev => {
    ev.target.value = psCpfFmt(ev.target.value);
    const d = psDigitos(ev.target.value);
    psCampo('psCpfNota').textContent = d.length === 11 ? (psCpfValido(d) ? '' : 'CPF inválido') : '';
  });
  psCampo('psFone').addEventListener('blur', ev => { ev.target.value = psFoneFmt(ev.target.value); });
  psCampo('psFotoArq').addEventListener('change', ev => psEscolherFoto(ev.target.files[0]));
  const zona = psCampo('psFotoZona');
  ['dragover', 'dragenter'].forEach(t => zona.addEventListener(t, ev => { ev.preventDefault(); zona.classList.add('sobre'); }));
  ['dragleave', 'drop'].forEach(t => zona.addEventListener(t, () => zona.classList.remove('sobre')));
  zona.addEventListener('drop', ev => { ev.preventDefault(); psEscolherFoto(ev.dataTransfer.files[0]); });
  psCampo('psExcluir').addEventListener('click', () => {
    const p = _psEditando;
    const ok = (p.leitores || []).map(x => apPorta(x.leitor));
    psCampo('psConfirmaTxt').textContent = `Excluir ${p.nome}? Ela sai ${ok.length ? 'dos leitores ' + ok.join(', ') + ' e ' : ''}do SightOps. As passagens já registradas continuam.`;
    psCampo('psConfirma').hidden = false;
  });
  psCampo('psConfirmaNao').addEventListener('click', () => { psCampo('psConfirma').hidden = true; });
  psCampo('psConfirmaSim').addEventListener('click', psExcluir);
}

// Chamado pelo Painel ao abrir a aba.
async function psAbrirAba() {
  if (!_psLigado) {
    _psLigado = true;
    psLigarGaveta();
    psCampo('psNova').addEventListener('click', () => psAbrir(null));
    piLigar();
    psCampo('psImportar').addEventListener('click', piAbrir);
    pfLigar();
    psCampo('psImportarFotos').addEventListener('click', pfAbrir);
    psCampo('psBusca').addEventListener('input', ev => { _psBusca = ev.target.value; _psMostrar = 120; psDesenhar(); });
  }
  if (_psDados) psDesenhar();
  try {
    await psCarregar();
  } catch (err) {
    if (!_psDados) psCampo('psConteudo').innerHTML = `<p class="ap-vazio">Não consegui carregar as pessoas: ${esc((err && err.message) || err)}</p>`;
  }
}

// ---------------------------------------------------------------- importar planilha
// POST /people/import?aplicar=false analisa (nada gravado); aplicar=true grava.
// Atualizar nao apaga nada: o backend parte do cadastro atual e so troca o
// que a planilha traz preenchido.
let _piArquivo = null;
let _piAnalise = null;

const PI_MODELOS = {
  escola: { cab: ['Nome', 'CPF', 'Matrícula', 'Turma', 'Responsável', 'WhatsApp do responsável', 'Tipo', 'Grupo'],
    ex: [['MARIA EXEMPLO DA SILVA', '000.000.000-00', '1234', '5º Ano A', 'Joana da Silva', '(82) 99999-0000', 'aluno', ''],
      ['JOSE EXEMPLO PROFESSOR', '000.000.000-00', '', 'Sala dos professores', '', '', 'funcionario', '']],
    txt: 'Escola: Nome, CPF e Matrícula (para aluno) são obrigatórios. Turma e WhatsApp do responsável completam o cadastro e o aviso de entrada e saída.' },
  condominio: { cab: ['Nome', 'CPF', 'Unidade', 'Tipo', 'Grupo', 'Observações'],
    ex: [['ANA EXEMPLO MORADORA', '000.000.000-00', 'Bloco A 101', 'morador', '', ''],
      ['CARLOS EXEMPLO DIARISTA', '000.000.000-00', 'Bloco A 101', 'prestador', '', 'seg, qua e sex']],
    txt: 'Condomínio: Nome e CPF são obrigatórios. Use Unidade (bloco e apartamento) e Tipo: morador, prestador, funcionário ou visitante.' },
  empresa: { cab: ['Nome', 'CPF', 'Setor', 'Tipo', 'Grupo', 'Observações'],
    ex: [['PAULA EXEMPLO ANALISTA', '000.000.000-00', 'Financeiro', 'colaborador', '', ''],
      ['RUI EXEMPLO TECNICO', '000.000.000-00', 'Manutenção', 'prestador', '', 'empresa terceira']],
    txt: 'Empresa: Nome e CPF são obrigatórios. Use Setor e Tipo: colaborador, prestador ou visitante.' },
  evento: { cab: ['Nome', 'CPF', 'Credencial', 'Tipo', 'Grupo'],
    ex: [['LUCAS EXEMPLO PARTICIPANTE', '000.000.000-00', 'VIP', 'participante', ''],
      ['BIA EXEMPLO PRODUCAO', '000.000.000-00', 'Produção', 'equipe', '']],
    txt: 'Evento: Nome e CPF são obrigatórios. Use Credencial (VIP, Imprensa...) e Tipo: participante, equipe ou convidado.' },
};
const PI_TIPO_ROT = { student: 'Aluno', resident: 'Morador', employee: 'Funcionário', contractor: 'Prestador', visitor: 'Visitante', participant: 'Participante', staff: 'Equipe' };

function piTipoLocal() {
  const site = psCampo('piSite').value.trim();
  const t = site ? psTipoLocal(site) : ((_apPerfil && _apPerfil.tipo) || 'escola');
  return PI_MODELOS[t] ? t : 'escola';
}

function piAtualizarModelo() {
  const m = PI_MODELOS[piTipoLocal()];
  psCampo('piModeloTxt').textContent = m.txt;
}

function piAbrir() {
  _piArquivo = null;
  _piAnalise = null;
  psCampo('piSite').value = typeof _apSite === 'string' ? _apSite : '';
  const grupos = (_psDados && _psDados.grupos) || [];
  psCampo('piGrupo').innerHTML = '<option value="">Nenhum (usar a coluna Grupo, se houver)</option>' +
    grupos.map(g => `<option value="${esc(g.id)}">${esc(g.nome)}${g.site ? ' · ' + esc(g.site) : ''}</option>`).join('');
  psCampo('piArquivo').value = '';
  psCampo('piZonaTxt').textContent = 'Escolher a planilha';
  psCampo('piPassoConferir').hidden = true;
  psCampo('piErro').hidden = true;
  psCampo('piAplicar').disabled = true;
  psCampo('piAplicar').innerHTML = '<i data-lucide="check"></i> Importar';
  piAtualizarModelo();
  psCampo('piGaveta').hidden = false;
  requestAnimationFrame(() => psCampo('piGaveta').classList.add('aberta'));
  if (window.lucide) lucide.createIcons();
}

function piFechar() {
  const g = psCampo('piGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function piErro(msg) {
  const e = psCampo('piErro');
  e.textContent = msg || '';
  e.hidden = !msg;
}

// Modelo em CSV com ponto e virgula e BOM: o Excel brasileiro abre direto.
function piBaixarModelo() {
  const m = PI_MODELOS[piTipoLocal()];
  const linha = l => l.map(v => (/[;"\n]/.test(v) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(';');
  const csv = '﻿' + [m.cab].concat(m.ex).map(linha).join('\r\n') + '\r\n';
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = `modelo-pessoas-${piTipoLocal()}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function piEnviar(aplicar) {
  const q = new URLSearchParams({ site: psCampo('piSite').value.trim(), aplicar: aplicar ? 'true' : 'false', grupo: psCampo('piGrupo').value });
  const fd = new FormData();
  fd.append('arquivo', _piArquivo, _piArquivo.name);
  const res = await fetch(`${API_BASE}/api/access-control/people/import?${q}`, { method: 'POST', credentials: 'same-origin', body: fd });
  let d = null;
  try { d = await res.json(); } catch (_) { d = null; }
  if (!res.ok) {
    const det = d && d.detail;
    throw new Error(res.status === 403 ? 'Seu perfil não pode importar pessoas.' : (typeof det === 'string' ? det : 'HTTP ' + res.status));
  }
  return d;
}

function piMostrarAnalise(a) {
  const novos = a.criar || [], atual = a.atualizar || [], rec = a.recusados || [], av = a.avisos || [];
  const total = novos.length + atual.length;
  const grupoNome = psCampo('piGrupo').selectedOptions[0] && psCampo('piGrupo').value ? psCampo('piGrupo').selectedOptions[0].textContent : '';
  const linhas = novos.map(r => ({ ...r, sit: 'nova' })).concat(atual.map(r => ({ ...r, sit: 'atualiza' })))
    .sort((x, y) => x.linha - y.linha);
  const ROT = { enrollment_code: 'matrícula', full_name: 'nome', guardian_phone: 'WhatsApp', guardian_name: 'responsável', class_name: 'turma/unidade/setor', document_id: 'CPF', controller_user_id: 'ID no leitor', person_type: 'tipo', groups: 'grupo', notes: 'observações' };
  psCampo('piAnalise').innerHTML = `
    <div class="pi-numeros">
      <div class="ok"><b>${apNum(novos.length)}</b><span>nova${novos.length === 1 ? '' : 's'}</span></div>
      <div class="azul"><b>${apNum(atual.length)}</b><span>atualizada${atual.length === 1 ? '' : 's'}</span></div>
      <div class="${rec.length ? 'ruim' : ''}"><b>${apNum(rec.length)}</b><span>recusada${rec.length === 1 ? '' : 's'}</span></div>
      <div class="${av.length ? 'at' : ''}"><b>${apNum(av.length)}</b><span>aviso${av.length === 1 ? '' : 's'}</span></div>
    </div>
    <p class="dv-ajuda">${apNum(a.total_linhas)} linhas lidas. Colunas reconhecidas: ${(a.colunas_reconhecidas || []).map(c => `<span class="ag-chip">${esc(ROT[c] || c)}</span>`).join(' ')}
      ${grupoNome ? `<br>Todos vão para o grupo <b>${esc(grupoNome)}</b>.` : ''} Quem já existe só tem trocado o que a planilha traz preenchido.</p>
    ${rec.length ? `<details class="pi-lista ruim" open><summary>${apNum(rec.length)} linha${rec.length === 1 ? '' : 's'} recusada${rec.length === 1 ? '' : 's'}: não entram</summary>
      <ul>${rec.slice(0, 200).map(r => `<li><b>Linha ${r.linha}</b> ${esc(r.nome || '')} · ${esc(r.motivo)}</li>`).join('')}</ul></details>` : ''}
    ${av.length ? `<details class="pi-lista at"><summary>${apNum(av.length)} aviso${av.length === 1 ? '' : 's'}: a pessoa entra assim mesmo</summary>
      <ul>${av.slice(0, 200).map(r => `<li><b>Linha ${r.linha}</b> ${esc(r.nome || '')} · ${esc(r.aviso)}</li>`).join('')}</ul></details>` : ''}
    ${linhas.length ? `<div class="ap-tabela pi-tabela"><table><thead><tr><th>Linha</th><th></th><th>Nome</th><th>Tipo</th><th>Turma/unidade</th><th>Grupos</th></tr></thead><tbody>
      ${linhas.slice(0, 300).map(r => `<tr><td class="monospace">${r.linha}</td><td><span class="ap-chip ${r.sit === 'nova' ? 'entrada' : 'pi-atual'}">${r.sit === 'nova' ? 'nova' : 'atualiza'}</span></td>
        <td>${esc(r.full_name)}${r.sit === 'atualiza' && r.nome_atual && r.nome_atual !== r.full_name ? `<small class="pi-antes">era ${esc(r.nome_atual)}</small>` : ''}</td>
        <td>${esc(PI_TIPO_ROT[r.person_type] || r.person_type)}</td><td>${esc(r.class_name || '—')}</td><td>${esc((r.grupos_nomes || []).join(', ') || '—')}</td></tr>`).join('')}
    </tbody></table></div>${linhas.length > 300 ? `<small class="dv-ajuda">Mostrando 300 de ${apNum(linhas.length)}.</small>` : ''}` : ''}`;
  psCampo('piPassoConferir').hidden = false;
  psCampo('piAplicar').disabled = !total;
  psCampo('piAplicar').innerHTML = `<i data-lucide="check"></i> Importar ${apNum(total)} pessoa${total === 1 ? '' : 's'}`;
  if (window.lucide) lucide.createIcons();
  psCampo('piPassoConferir').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function piAnalisar() {
  if (!_piArquivo) return;
  piErro('');
  psCampo('piAplicar').disabled = true;
  psCampo('piPassoConferir').hidden = false;
  psCampo('piAnalise').innerHTML = '<p class="dv-ajuda"><i data-lucide="loader-circle" class="dv-gira"></i> Lendo a planilha…</p>';
  if (window.lucide) lucide.createIcons();
  try {
    _piAnalise = await piEnviar(false);
    piMostrarAnalise(_piAnalise);
  } catch (err) {
    psCampo('piPassoConferir').hidden = true;
    piErro(err.message);
  }
}

async function piAplicar() {
  const b = psCampo('piAplicar');
  b.disabled = true;
  b.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i> Importando…';
  if (window.lucide) lucide.createIcons();
  try {
    const r = await piEnviar(true);
    const falhas = r.falhas || [];
    piFechar();
    await psCarregar();
    acToast(`${apNum(r.criados)} nova${r.criados === 1 ? '' : 's'}, ${apNum(r.atualizados)} atualizada${r.atualizados === 1 ? '' : 's'}${falhas.length ? `, ${falhas.length} com erro (${esc(falhas[0].motivo)})` : ''}. Quem está em grupo vai para os leitores.`, falhas.length > 0);
  } catch (err) {
    piErro(err.message);
    b.disabled = false;
    b.innerHTML = '<i data-lucide="check"></i> Tentar de novo';
    if (window.lucide) lucide.createIcons();
  }
}

function piLigar() {
  psCampo('piFechar').addEventListener('click', piFechar);
  psCampo('piCancelar').addEventListener('click', piFechar);
  psCampo('piFundo').addEventListener('click', piFechar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !psCampo('piGaveta').hidden) piFechar(); });
  psCampo('piModelo').addEventListener('click', piBaixarModelo);
  psCampo('piSite').addEventListener('change', () => { piAtualizarModelo(); if (_piArquivo) piAnalisar(); });
  psCampo('piGrupo').addEventListener('change', () => { if (_piArquivo) piAnalisar(); });
  const escolher = f => {
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { piErro('Arquivo maior que 10 MB.'); return; }
    _piArquivo = f;
    psCampo('piZonaTxt').textContent = f.name;
    piAnalisar();
  };
  psCampo('piArquivo').addEventListener('change', ev => escolher(ev.target.files[0]));
  const zona = psCampo('piZona');
  ['dragover', 'dragenter'].forEach(t => zona.addEventListener(t, ev => { ev.preventDefault(); zona.classList.add('sobre'); }));
  ['dragleave', 'drop'].forEach(t => zona.addEventListener(t, () => zona.classList.remove('sobre')));
  zona.addEventListener('drop', ev => { ev.preventDefault(); escolher(ev.dataTransfer.files[0]); });
  psCampo('piAplicar').addEventListener('click', piAplicar);
}

// ---------------------------------------------------------------- importar fotos
// Tudo no navegador: abre o .zip (JSZip), casa o nome de cada arquivo com o CPF
// ou a matricula, reduz a foto (psPrepararFoto) e envia uma a uma pela rota de
// sempre (POST /people/{id}/face-photo), que ja manda a foto para os leitores.
// Assim nenhum envio passa do limite de 25 MB do servidor.
const PF_EXT = { jpg: 'image/jpeg', jpeg: 'image/jpeg', png: 'image/png', webp: 'image/webp' };
let _pfItens = [];          // [{arquivo, nome, chave, pessoa, problema}]
let _pfEnviando = false;
let _pfFeito = false;       // terminou: o botao vira Fechar

function pfAbrir() {
  _pfItens = [];
  _pfFeito = false;
  psCampo('pfArquivos').value = '';
  psCampo('pfZonaTxt').textContent = 'Escolher um .zip ou várias fotos';
  psCampo('pfPassoConferir').hidden = true;
  psCampo('pfErro').hidden = true;
  psCampo('pfAplicar').disabled = true;
  psCampo('pfAplicar').innerHTML = '<i data-lucide="upload"></i> Enviar fotos';
  psCampo('pfGaveta').hidden = false;
  requestAnimationFrame(() => psCampo('pfGaveta').classList.add('aberta'));
  if (window.lucide) lucide.createIcons();
}

function pfFechar() {
  if (_pfEnviando) return;
  const g = psCampo('pfGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function pfErro(msg) { const e = psCampo('pfErro'); e.textContent = msg || ''; e.hidden = !msg; }

function pfCarregarJsZip() {
  if (window.JSZip) return Promise.resolve(window.JSZip);
  return new Promise((ok, falha) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
    s.onload = () => (window.JSZip ? ok(window.JSZip) : falha(new Error('Não consegui abrir o .zip.')));
    s.onerror = () => falha(new Error('Não consegui carregar o leitor de .zip. Selecione as fotos soltas.'));
    document.head.appendChild(s);
  });
}

// "fotos/529.982.247-25.JPG" -> {nome:"529.982.247-25.JPG", chave:"52998224725", ext:"jpg"}
function pfChave(caminho) {
  const nome = String(caminho).split(/[\\/]/).pop();
  const ext = (nome.split('.').pop() || '').toLowerCase();
  const base = nome.replace(/\.[^.]+$/, '').trim();
  return { nome, ext, base, digitos: base.replace(/\D/g, '') };
}

function pfCasar(itens) {
  const pessoas = (_psDados && _psDados.pessoas) || [];
  const porCpf = new Map(), porMatricula = new Map();
  pessoas.forEach(p => {
    if (psDigitos(p.cpf).length === 11) porCpf.set(psDigitos(p.cpf), p);
    if (p.matricula) porMatricula.set(String(p.matricula).trim().toLowerCase(), p);
  });
  const vistos = new Map();
  itens.forEach(it => {
    const k = pfChave(it.nome);
    it.nome = k.nome;
    if (!PF_EXT[k.ext]) { it.problema = 'não é foto (use .jpg, .png ou .webp)'; return; }
    const p = (k.digitos.length === 11 && porCpf.get(k.digitos)) || porMatricula.get(k.base.toLowerCase()) || porMatricula.get(k.digitos);
    if (!p) { it.problema = 'nenhuma pessoa com esse CPF ou matrícula'; return; }
    if (vistos.has(p.id)) { it.problema = `mesma pessoa de ${vistos.get(p.id)}`; return; }
    vistos.set(p.id, k.nome);
    it.pessoa = p;
  });
  return itens;
}

async function pfLerArquivos(lista) {
  pfErro('');
  psCampo('pfPassoConferir').hidden = false;
  psCampo('pfAnalise').innerHTML = '<p class="dv-ajuda"><i data-lucide="loader-circle" class="dv-gira"></i> Lendo as fotos…</p>';
  if (window.lucide) lucide.createIcons();
  const itens = [];
  try {
    for (const f of lista) {
      if (/\.zip$/i.test(f.name)) {
        const JSZip = await pfCarregarJsZip();
        const zip = await JSZip.loadAsync(f);
        const entradas = Object.values(zip.files).filter(e => !e.dir && !/(^|\/)(__MACOSX|\.)/.test(e.name));
        if (entradas.length > 3000) throw new Error('O .zip tem mais de 3.000 arquivos. Divida em partes.');
        for (const e of entradas) itens.push({ nome: e.name, ler: () => e.async('blob') });
      } else {
        itens.push({ nome: f.name, ler: async () => f });
      }
    }
  } catch (err) {
    psCampo('pfPassoConferir').hidden = true;
    pfErro(err.message || 'Não consegui ler os arquivos.');
    return;
  }
  _pfItens = pfCasar(itens);
  pfMostrar();
}

function pfMostrar() {
  const ok = _pfItens.filter(i => i.pessoa), ruins = _pfItens.filter(i => !i.pessoa);
  const trocam = ok.filter(i => i.pessoa.tem_foto).length;
  psCampo('pfAnalise').innerHTML = `
    <div class="pi-numeros">
      <div class="ok"><b>${apNum(ok.length)}</b><span>com pessoa</span></div>
      <div class="azul"><b>${apNum(trocam)}</b><span>trocam a foto atual</span></div>
      <div class="${ruins.length ? 'ruim' : ''}"><b>${apNum(ruins.length)}</b><span>não entram</span></div>
      <div><b>${apNum(_pfItens.length)}</b><span>arquivos</span></div>
    </div>
    ${ruins.length ? `<details class="pi-lista ruim" ${ok.length ? '' : 'open'}><summary>${apNum(ruins.length)} arquivo${ruins.length === 1 ? '' : 's'} não entra${ruins.length === 1 ? '' : 'm'}</summary>
      <ul>${ruins.slice(0, 300).map(i => `<li><b class="monospace">${esc(i.nome)}</b> · ${esc(i.problema)}</li>`).join('')}</ul></details>` : ''}
    ${ok.length ? `<div class="ap-tabela pi-tabela"><table><thead><tr><th>Arquivo</th><th>Pessoa</th><th>Foto atual</th><th>Situação</th></tr></thead><tbody>
      ${ok.slice(0, 500).map((i, n) => `<tr><td class="monospace">${esc(i.nome)}</td><td>${esc(i.pessoa.nome)}<small class="pi-antes">${esc(psTipoRot(i.pessoa))}${i.pessoa.turma ? ' · ' + esc(i.pessoa.turma) : ''}</small></td>
        <td>${i.pessoa.tem_foto ? 'será trocada' : '<span class="ps-falta">sem foto</span>'}</td><td id="pfSit${n}" class="pf-sit">pronta</td></tr>`).join('')}
    </tbody></table></div>` : ''}
    <div class="pf-barra" id="pfBarra" hidden><i></i><span></span></div>`;
  psCampo('pfAplicar').disabled = !ok.length;
  psCampo('pfAplicar').innerHTML = `<i data-lucide="upload"></i> Enviar ${apNum(ok.length)} foto${ok.length === 1 ? '' : 's'}`;
  if (window.lucide) lucide.createIcons();
}

async function pfEnviar() {
  if (_pfFeito) return pfFechar();
  const ok = _pfItens.filter(i => i.pessoa);
  if (!ok.length || _pfEnviando) return;
  _pfEnviando = true;
  const b = psCampo('pfAplicar');
  b.disabled = true;
  psCampo('pfCancelar').disabled = true;
  const barra = psCampo('pfBarra');
  barra.hidden = false;
  let feitas = 0, erros = 0, prox = 0;
  const marcar = () => {
    barra.querySelector('i').style.width = `${Math.round(feitas * 100 / ok.length)}%`;
    barra.querySelector('span').textContent = `${apNum(feitas)} de ${apNum(ok.length)}: ${apNum(feitas - erros)} enviada${feitas - erros === 1 ? '' : 's'}${erros ? `, ${erros} com erro` : ''}`;
    b.innerHTML = `<i data-lucide="loader-circle" class="dv-gira"></i> Enviando ${apNum(feitas)}/${apNum(ok.length)}`;
    if (window.lucide) lucide.createIcons();
  };
  marcar();
  // Tres por vez: rapido sem afogar o servidor (cada uma grava e enfileira o envio ao leitor).
  const trabalhador = async () => {
    while (prox < ok.length) {
      const n = prox++;
      const it = ok[n];
      const cel = psCampo('pfSit' + n);
      try {
        const bruto = await it.ler();
        const ext = pfChave(it.nome).ext;
        const arquivo = new File([bruto], it.nome, { type: PF_EXT[ext] || bruto.type || 'image/jpeg' });
        const foto = await psPrepararFoto(arquivo);
        await psEnviarFoto(it.pessoa.id, foto);
        if (cel) { cel.textContent = 'enviada'; cel.className = 'pf-sit ok'; }
      } catch (err) {
        erros++;
        if (cel) { cel.textContent = (err && err.message) || 'erro'; cel.className = 'pf-sit ruim'; }
      }
      feitas++;
      marcar();
    }
  };
  await Promise.all([trabalhador(), trabalhador(), trabalhador()]);
  _pfEnviando = false;
  _pfFeito = true;
  psCampo('pfCancelar').disabled = false;
  b.disabled = false;
  b.innerHTML = '<i data-lucide="check"></i> Fechar';
  if (window.lucide) lucide.createIcons();
  acToast(`${apNum(feitas - erros)} foto${feitas - erros === 1 ? '' : 's'} enviada${feitas - erros === 1 ? '' : 's'}${erros ? `, ${erros} com erro (veja na lista)` : ''}. Os leitores recebem em seguida.`, erros > 0);
  psCarregar().catch(() => {});
}

function pfLigar() {
  psCampo('pfFechar').addEventListener('click', pfFechar);
  psCampo('pfCancelar').addEventListener('click', pfFechar);
  psCampo('pfFundo').addEventListener('click', pfFechar);
  document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !psCampo('pfGaveta').hidden) pfFechar(); });
  const escolher = lista => {
    const arr = [...(lista || [])];
    if (!arr.length) return;
    psCampo('pfZonaTxt').textContent = arr.length === 1 ? arr[0].name : `${arr.length} arquivos`;
    pfLerArquivos(arr);
  };
  psCampo('pfArquivos').addEventListener('change', ev => escolher(ev.target.files));
  const zona = psCampo('pfZona');
  ['dragover', 'dragenter'].forEach(t => zona.addEventListener(t, ev => { ev.preventDefault(); zona.classList.add('sobre'); }));
  ['dragleave', 'drop'].forEach(t => zona.addEventListener(t, () => zona.classList.remove('sobre')));
  zona.addEventListener('drop', ev => { ev.preventDefault(); escolher(ev.dataTransfer.files); });
  psCampo('pfAplicar').addEventListener('click', pfEnviar);
}
