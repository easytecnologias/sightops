// Controle de Rotas -- transporte escolar com prestacao de contas do PNATE.
// Cada viagem so conta para pagamento com as 6 provas: km real (GPS), rota
// executada, alunos embarcados, veiculo vistoriado, motorista habilitado e
// documentacao idonea. Serve prefeitura e empresa: operador = quem roda,
// contratante = quem paga, contrato liga os dois, rota pertence a um contrato.

const ROTAS_VAZIO = {
  'rotas-vivo': {
    el: 'rotasVivoBody', icon: 'radar',
    titulo: 'Nenhuma viagem em andamento',
    texto: 'Quando o motorista iniciar a viagem pelo app, o ônibus aparece aqui no mapa com os alunos a bordo.',
    proximo: 'rotas-cadastro', proximoTxt: 'Ver rotas e alunos',
  },
  'rotas-viagens': {
    el: 'rotasViagensBody', icon: 'route',
    titulo: 'Nenhuma viagem registrada',
    texto: 'Cada viagem feita pelo app entra aqui com as 6 provas do PNATE conferidas: válida, pendente ou inválida.',
    proximo: 'rotas-cadastro', proximoTxt: 'Ver rotas e alunos',
  },
  'rotas-pnate': {
    el: 'rotasPnateBody', icon: 'file-check',
    titulo: 'Nada para fechar ainda',
    texto: 'O fechamento do mês soma só as viagens válidas e gera o PDF da prestação de contas, com as glosas e o motivo de cada uma.',
    proximo: 'rotas-viagens', proximoTxt: 'Ver viagens',
  },
};

function rotasRenderVazio(view) {
  const cfg = ROTAS_VAZIO[view];
  const box = cfg && document.getElementById(cfg.el);
  if (!box) return;
  const botao = cfg.proximo
    ? `<button class="secondary-action" type="button" data-rotas-ir="${cfg.proximo}">${cfg.proximoTxt}</button>`
    : '';
  box.innerHTML = `
    <div class="rotas-vazio-icone"><i data-lucide="${cfg.icon}"></i></div>
    <h2>${cfg.titulo}</h2>
    <p>${cfg.texto}</p>
    ${botao}`;
  box.querySelector('[data-rotas-ir]')?.addEventListener('click', (ev) => rotasIrPara(ev.currentTarget.dataset.rotasIr));
  lucide.createIcons();
}

function rotasIrPara(view) {
  document.querySelector(`.nav-item[data-view="${view}"]`)?.click();
}

function loadRotasVivo()     { rotasRenderVazio('rotas-vivo'); }
function loadRotasViagens()  { rotasRenderVazio('rotas-viagens'); }
function loadRotasPnate()    { rotasRenderVazio('rotas-pnate'); }

// ---------------------------------------------------------------- comum

const ROTAS_SITUACAO = {
  liberado: ['Liberado', 'success'],
  atencao: ['Atenção', 'amber'],
  bloqueado: ['Bloqueado', 'danger'],
  inativo: ['Inativo', 'neutral'],
};
const ROTAS_TIPO_VEICULO = { onibus: 'Ônibus', micro: 'Micro-ônibus', van: 'Van', outro: 'Outro' };
const ROTAS_TIPO_OPERADOR = { empresa: 'Empresa contratada', frota_propria: 'Frota própria' };
const ROTAS_TURNOS = { manha: 'Manhã', tarde: 'Tarde', noite: 'Noite', integral: 'Integral' };
const ROTAS_CENTRO_PADRAO = [-14.24, -51.93]; // Brasil, quando nada tem localizacao

function rotasData(iso) {
  if (!iso) return '';
  const [a, m, d] = String(iso).slice(0, 10).split('-');
  return `${d}/${m}/${a}`;
}

function rotasPreco(v) {
  if (!v) return '—';
  return `R$ ${Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
}

function rotasDoc(item, chave, campo, obrigatorio) {
  const sit = item.docs?.[chave] || { st: 'faltando' };
  const cls = { ok: 'success', vence: 'amber', vencido: 'danger', faltando: obrigatorio ? 'danger' : 'neutral' }[sit.st];
  const txt = sit.st === 'faltando' ? 'não informada' : rotasData(item[campo]);
  const dica = sit.st === 'vence' ? ` title="vence em ${sit.dias} dia(s)"` : '';
  return `<span class="pill ${cls}"${dica}>${esc(txt)}</span>`;
}

function rotasPill(situacao) {
  const [txt, cls] = ROTAS_SITUACAO[situacao] || ['—', 'neutral'];
  return `<span class="pill ${cls}">${txt}</span>`;
}

function rotasSituacao(item) {
  const motivos = (item.motivos || []).join(' · ');
  return `${rotasPill(item.situacao)}${motivos ? `<div class="rotas-motivos">${esc(motivos)}</div>` : ''}`;
}

function rotasTabela(cab, linhas, vazio) {
  const colunas = (cab.match(/<th/g) || []).length;
  return `<div class="rotas-tabela-wrap"><table class="data-table rotas-tabela">
    <thead><tr>${cab}</tr></thead>
    <tbody>${linhas.join('') || `<tr class="empty-row"><td colspan="${colunas}">${vazio}</td></tr>`}</tbody>
  </table></div>`;
}

function rotasFiltro(inputId) {
  const busca = (document.getElementById(inputId)?.value || '').trim().toLowerCase();
  return { busca, casa: (...partes) => !busca || partes.join(' ').toLowerCase().includes(busca) };
}

// "-10.18, -36.82" colado do Google Maps num campo de latitude: separa nos dois.
function rotasColarCoordenadas(ev, latEl, lonEl) {
  const txt = (ev.clipboardData || window.clipboardData)?.getData('text') || '';
  const m = txt.match(/(-?\d+(?:[.,]\d+)?)\s*[,;\s]\s*(-?\d+(?:[.,]\d+)?)/);
  if (!m || !latEl || !lonEl) return;
  ev.preventDefault();
  latEl.value = m[1].replace(',', '.');
  lonEl.value = m[2].replace(',', '.');
  latEl.dispatchEvent(new Event('input', { bubbles: true }));
}

function rotasTiles(mapa) {
  // Sem o link "Leaflet" no rodape: ele abre outro site na mesma aba e quem
  // esbarrava nele perdia a rota que estava digitando.
  mapa.attributionControl?.setPrefix(false);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', subdomains: 'abc', maxZoom: 19,
  }).addTo(mapa);
}

function rotasIconeParada(n, ativa) {
  return L.divIcon({
    className: '',
    html: `<span class="rotas-pino${ativa ? ' is-ativa' : ''}">${n}</span>`,
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

// ---------------------------------------------------------------- formulario compartilhado
//
// Cada cadastro descreve seus campos; o modal e montado daqui. Tipos: text,
// number, date, textarea, select (opcoes {valor: texto}) e ref (fonte(atual)
// devolve [[id, texto]]). `so` mostra o campo so para uma funcao (motorista).

let _rotasModal = null; // { tabela, id, cfg, campos, aoSalvar }
let _rotasModalBound = false;

function rotasCampoHtml(c, atual) {
  const v = atual[c.k] ?? '';
  const req = c.req ? ' required' : '';
  const nome = `name="${c.k}" id="rotasCampo_${c.k}"`;
  let input;
  if (c.tipo === 'select' || c.tipo === 'ref') {
    const opcoes = c.tipo === 'ref' ? c.fonte(atual) : Object.entries(c.opcoes);
    input = `<select ${nome}${req}>${rotasOpcoesHtml(opcoes, v)}</select>`;
  } else if (c.tipo === 'textarea') {
    input = `<textarea ${nome} rows="2" maxlength="${c.max}">${esc(v)}</textarea>`;
  } else {
    const tipo = c.tipo || 'text';
    const extra = tipo === 'number' ? ` min="${c.min}" max="${c.max}" step="${c.step || 1}"` : (c.max ? ` maxlength="${c.max}"` : '');
    const valor = tipo === 'number' && (v === '' || v === null || (Number(v) === 0 && !c.zero)) ? (c.padrao ?? '') : v;
    input = `<input type="${tipo}" ${nome} value="${esc(valor ?? '')}"${extra}${c.ph ? ` placeholder="${esc(c.ph)}"` : ''}${req}>`;
  }
  return `<div class="form-group${c.full ? ' rotas-campo-full' : ''}"${c.so ? ` data-so="${c.so}"` : ''}>
    <label for="rotasCampo_${c.k}">${esc(c.l)}${c.req ? ' *' : ''}</label>${input}
    ${c.dica ? `<small class="rotas-dica">${esc(c.dica)}</small>` : ''}</div>`;
}

function rotasOpcoesHtml(opcoes, valor) {
  return opcoes.map(([val, txt]) => `<option value="${esc(val)}"${String(valor ?? '') === String(val) ? ' selected' : ''}>${esc(txt)}</option>`).join('');
}

function rotasBindModal() {
  if (_rotasModalBound) return;
  _rotasModalBound = true;
  document.querySelectorAll('[data-rotas-fechar]').forEach((b) => b.addEventListener('click', rotasFechar));
  document.getElementById('rotasModalSalvar').addEventListener('click', rotasSalvar);
  document.getElementById('rotasModalExcluir').addEventListener('click', rotasExcluir);
  const form = document.getElementById('rotasModalForm');
  form.addEventListener('submit', (ev) => ev.preventDefault());
  form.addEventListener('change', (ev) => {
    if (ev.target.name === 'funcao') rotasMostrarCamposDaFuncao();
    _rotasModal?.cfg.aoMudar?.(ev);
  });
  // Fecha so por X, Cancelar ou Esc: clicar fora perdia o que foi digitado.
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Escape' || document.getElementById('modalRotasCadastro').classList.contains('hidden')) return;
    if (!document.getElementById('modalConfirm')?.classList.contains('hidden')) return;
    rotasFechar();
  });
}

function rotasAbrirForm({ tabela, cfg, item = null, padrao = {}, aoSalvar }) {
  rotasBindModal();
  const atual = item ? { ...item } : { ativo: 1, ...padrao };
  const campos = typeof cfg.campos === 'function' ? cfg.campos(atual) : cfg.campos;
  _rotasModal = { tabela, id: item?.id || '', cfg, campos, aoSalvar };
  document.getElementById('rotasModalTitulo').textContent = `${item ? 'Editar' : 'Novo cadastro:'} ${cfg.titulo}`;
  document.getElementById('rotasModalSub').textContent = cfg.sub || '';
  document.querySelector('#modalRotasCadastro .rotas-modal').classList.toggle('is-larga', Boolean(cfg.larga));
  document.getElementById('rotasModalForm').innerHTML = `
    <div class="rotas-form-grid">${campos.map((c) => rotasCampoHtml(c, atual)).join('')}</div>
    ${cfg.extra ? cfg.extra(atual) : ''}
    <label class="alert-check"><input type="checkbox" name="ativo" ${atual.ativo ? 'checked' : ''}> Cadastro ativo</label>`;
  document.getElementById('rotasModalExcluir').hidden = !item;
  rotasMostrarCamposDaFuncao();
  document.getElementById('modalRotasCadastro').classList.remove('hidden');
  lucide.createIcons();
  cfg.aoAbrir?.(atual);
  document.querySelector('#rotasModalForm [name]')?.focus();
}

function rotasMostrarCamposDaFuncao() {
  const funcao = document.querySelector('#rotasModalForm [name="funcao"]')?.value;
  document.querySelectorAll('#rotasModalForm [data-so]').forEach((el) => {
    el.hidden = Boolean(funcao) && el.dataset.so !== funcao;
  });
}

function rotasFechar() {
  _rotasModal?.cfg.aoFechar?.();
  document.getElementById('modalRotasCadastro').classList.add('hidden');
  _rotasModal = null;
}

async function rotasSalvar() {
  if (!_rotasModal) return;
  const { tabela, id, cfg, campos, aoSalvar } = _rotasModal;
  const payload = { id };
  document.querySelectorAll('#rotasModalForm [name]').forEach((el) => {
    payload[el.name] = el.type === 'checkbox' ? el.checked : el.value.trim();
  });
  cfg.coletar?.(payload);
  const faltando = campos.find((c) => c.req && !payload[c.k]);
  if (faltando) { showToast(`Preencha: ${faltando.l}.`, true); return; }
  const btn = document.getElementById('rotasModalSalvar');
  btn.disabled = true;
  try {
    const res = await api(`/api/rotas/${tabela}`, { method: 'POST', body: JSON.stringify(payload) });
    if (!res) return;
    const out = await jsonOrReadableError(res, 'Falha ao salvar.');
    rotasFechar();
    showToast('Cadastro salvo.');
    await aoSalvar?.(out.id);
  } catch (err) {
    showToast(err.message || 'Falha ao salvar.', true);
  } finally {
    btn.disabled = false;
  }
}

async function rotasExcluir() {
  if (!_rotasModal?.id) return;
  const { tabela, id, aoSalvar } = _rotasModal;
  const ok = await showConfirm({
    eyebrow: 'Controle de Rotas', title: 'Excluir este cadastro?', label: 'Excluir',
    msg: 'Não dá para desfazer. Para só tirar de uso, desmarque "Cadastro ativo" e salve.',
  });
  if (!ok) return;
  try {
    const res = await api(`/api/rotas/${tabela}/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (!res) return;
    await jsonOrReadableError(res, 'Falha ao excluir.');
    rotasFechar();
    showToast('Cadastro excluído.');
    await aoSalvar?.(null);
  } catch (err) {
    showToast(err.message || 'Falha ao excluir.', true);
  }
}

// ---------------------------------------------------------------- frota

let _rotasFrota = { operadores: [], veiculos: [], motoristas: [], resumo: {} };
let _rotasAba = 'veiculos';
let _rotasFrotaBound = false;

function rotasOperadoresFonte(atual) {
  return [['', 'Escolha...'], ...(_rotasFrota.operadores || [])
    .filter((o) => o.ativo || o.id === atual.operador_id).map((o) => [o.id, o.nome])];
}

const ROTAS_FORM_FROTA = {
  operadores: {
    titulo: 'empresa ou frota', sub: 'Quem roda as rotas: empresa contratada ou frota própria da prefeitura.',
    campos: [
      { k: 'nome', l: 'Nome', req: true, max: 160, full: true },
      { k: 'tipo', l: 'Tipo', tipo: 'select', opcoes: ROTAS_TIPO_OPERADOR },
      { k: 'documento', l: 'CNPJ', max: 18, ph: '00.000.000/0000-00' },
      { k: 'contato', l: 'Responsável', max: 160 },
      { k: 'telefone', l: 'Telefone', max: 20, ph: '(82) 99999-0000' },
    ],
  },
  veiculos: {
    titulo: 'veículo', sub: 'Vistoria e autorização vencidas bloqueiam o veículo; o seguro só avisa.',
    campos: [
      { k: 'operador_id', l: 'Empresa / frota', tipo: 'ref', fonte: rotasOperadoresFonte, req: true },
      { k: 'placa', l: 'Placa', req: true, max: 8, ph: 'ABC1D23' },
      { k: 'tipo', l: 'Tipo', tipo: 'select', opcoes: ROTAS_TIPO_VEICULO },
      { k: 'modelo', l: 'Modelo', max: 120 },
      { k: 'lugares', l: 'Lugares', tipo: 'number', min: 0, max: 120 },
      { k: 'ano', l: 'Ano', tipo: 'number', min: 1950, max: 2100 },
      { k: 'vistoria_validade', l: 'Vistoria válida até', tipo: 'date' },
      { k: 'autorizacao_numero', l: 'Nº da autorização escolar', max: 60 },
      { k: 'autorizacao_validade', l: 'Autorização válida até', tipo: 'date' },
      { k: 'seguro_validade', l: 'Seguro válido até', tipo: 'date' },
      { k: 'observacoes', l: 'Observações', tipo: 'textarea', max: 1000, full: true },
    ],
  },
  motoristas: {
    titulo: 'motorista ou monitor', sub: 'Motorista precisa de CNH D ou E e do curso de transporte escolar em dia.',
    campos: [
      { k: 'nome', l: 'Nome completo', req: true, max: 160, full: true },
      { k: 'funcao', l: 'Função', tipo: 'select', opcoes: { motorista: 'Motorista', monitor: 'Monitor(a)' } },
      { k: 'operador_id', l: 'Empresa / frota', tipo: 'ref', fonte: rotasOperadoresFonte, req: true },
      { k: 'cpf', l: 'CPF', max: 14, ph: '000.000.000-00' },
      { k: 'telefone', l: 'Telefone', max: 20 },
      { k: 'cnh_numero', l: 'Nº da CNH', max: 11, so: 'motorista' },
      { k: 'cnh_categoria', l: 'Categoria', tipo: 'select', opcoes: { '': '—', D: 'D', E: 'E', C: 'C', B: 'B', A: 'A' }, so: 'motorista' },
      { k: 'cnh_validade', l: 'CNH válida até', tipo: 'date', so: 'motorista' },
      { k: 'curso_validade', l: 'Curso de transporte escolar até', tipo: 'date', so: 'motorista' },
      { k: 'antecedentes_data', l: 'Antecedentes emitidos em', tipo: 'date' },
      { k: 'observacoes', l: 'Observações', tipo: 'textarea', max: 1000, full: true },
    ],
  },
};

function rotasNomeOperador(id) {
  return _rotasFrota.operadores.find((o) => o.id === id)?.nome || '—';
}

async function loadRotasFrota() {
  if (!_rotasFrotaBound) {
    _rotasFrotaBound = true;
    const view = document.getElementById('viewRotasFrota');
    view.querySelectorAll('[data-rotas-aba]').forEach((b) => b.addEventListener('click', () => {
      _rotasAba = b.dataset.rotasAba;
      rotasRenderFrota();
    }));
    view.querySelectorAll('.page-heading [data-rotas-novo]').forEach((b) => b.addEventListener('click', () => rotasFrotaAbrir(b.dataset.rotasNovo, null)));
    let t = null;
    document.getElementById('rotasFrotaBusca')?.addEventListener('input', () => { clearTimeout(t); t = setTimeout(rotasRenderFrota, 200); });
    document.getElementById('rotasFrotaBody').addEventListener('click', (ev) => {
      const ir = ev.target.closest('[data-rotas-novo]');
      if (ir) { rotasFrotaAbrir(ir.dataset.rotasNovo, null); return; }
      const tr = ev.target.closest('tr[data-id]');
      if (tr) rotasFrotaAbrir(_rotasAba, tr.dataset.id);
    });
  }
  await rotasCarregarFrota();
}

function rotasFrotaAbrir(tabela, id) {
  if (tabela !== 'operadores' && !_rotasFrota.operadores.length) {
    showToast('Cadastre primeiro a empresa ou a frota própria.', true);
    return;
  }
  const item = id ? (_rotasFrota[tabela] || []).find((x) => x.id === id) : null;
  if (id && !item) return;
  rotasAbrirForm({
    tabela, cfg: ROTAS_FORM_FROTA[tabela], item,
    aoSalvar: async () => { _rotasAba = tabela; await rotasCarregarFrota(); },
  });
}

async function rotasCarregarFrota() {
  const body = document.getElementById('rotasFrotaBody');
  try {
    const res = await api('/api/rotas/frota');
    if (!res) return;
    _rotasFrota = await jsonOrReadableError(res, 'Falha ao carregar a frota.');
  } catch (err) {
    body.innerHTML = `<div class="rotas-vazio"><p>${esc(err.message || 'Falha ao carregar a frota.')}</p></div>`;
    return;
  }
  rotasRenderFrota();
}

function rotasRenderFrota() {
  const r = _rotasFrota.resumo || {};
  document.getElementById('rotasFrotaKpis').innerHTML = `
    <article class="rotas-kpi"><span>Veículos liberados</span><strong>${r.veiculos_liberados ?? 0} <small>de ${r.veiculos ?? 0}</small></strong></article>
    <article class="rotas-kpi"><span>Motoristas e monitores liberados</span><strong>${r.motoristas_liberados ?? 0} <small>de ${r.motoristas ?? 0}</small></strong></article>
    <article class="rotas-kpi${r.atencao ? ' is-amber' : ''}"><span>Vencem em 30 dias</span><strong>${r.atencao ?? 0}</strong></article>
    <article class="rotas-kpi${r.bloqueados ? ' is-danger' : ''}"><span>Bloqueados</span><strong>${r.bloqueados ?? 0}</strong></article>`;
  document.querySelectorAll('#viewRotasFrota [data-rotas-aba]').forEach((b) => b.classList.toggle('active', b.dataset.rotasAba === _rotasAba));

  const body = document.getElementById('rotasFrotaBody');
  if (!_rotasFrota.operadores.length) {
    body.innerHTML = `<div class="rotas-vazio">
      <div class="rotas-vazio-icone"><i data-lucide="building-2"></i></div>
      <h2>Comece pela empresa ou pela frota própria</h2>
      <p>Todo veículo e motorista pertence a quem roda a rota: a empresa contratada ou a frota da própria prefeitura.</p>
      <button class="primary-action" type="button" data-rotas-novo="operadores"><i data-lucide="plus"></i> Cadastrar empresa ou frota</button>
    </div>`;
    lucide.createIcons();
    return;
  }

  const { busca, casa } = rotasFiltro('rotasFrotaBusca');
  let cab = '';
  let linhas = [];
  if (_rotasAba === 'veiculos') {
    cab = '<th>Placa</th><th>Empresa</th><th>Veículo</th><th class="c">Lugares</th><th>Vistoria</th><th>Autorização</th><th>Seguro</th><th>Situação</th>';
    linhas = _rotasFrota.veiculos.filter((v) => casa(v.placa, v.modelo, rotasNomeOperador(v.operador_id))).map((v) => `
      <tr data-id="${esc(v.id)}">
        <td><strong>${esc(v.placa)}</strong></td>
        <td>${esc(rotasNomeOperador(v.operador_id))}</td>
        <td>${esc([ROTAS_TIPO_VEICULO[v.tipo], v.modelo, v.ano || ''].filter(Boolean).join(' · '))}</td>
        <td class="c">${v.lugares || '—'}</td>
        <td>${rotasDoc(v, 'vistoria', 'vistoria_validade', true)}</td>
        <td>${rotasDoc(v, 'autorizacao', 'autorizacao_validade', true)}</td>
        <td>${rotasDoc(v, 'seguro', 'seguro_validade', false)}</td>
        <td>${rotasSituacao(v)}</td>
      </tr>`);
  } else if (_rotasAba === 'motoristas') {
    cab = '<th>Nome</th><th>Função</th><th>Empresa</th><th class="c">CNH</th><th>Validade CNH</th><th>Curso escolar</th><th>Situação</th>';
    linhas = _rotasFrota.motoristas.filter((m) => casa(m.nome, m.cpf, rotasNomeOperador(m.operador_id))).map((m) => {
      const monitor = m.funcao === 'monitor';
      const naoAplica = '<span class="pill neutral">não se aplica</span>';
      return `
      <tr data-id="${esc(m.id)}">
        <td><strong>${esc(m.nome)}</strong></td>
        <td>${monitor ? 'Monitor(a)' : 'Motorista'}</td>
        <td>${esc(rotasNomeOperador(m.operador_id))}</td>
        <td class="c">${monitor ? '—' : esc(m.cnh_categoria || '—')}</td>
        <td>${monitor ? naoAplica : rotasDoc(m, 'cnh', 'cnh_validade', true)}</td>
        <td>${monitor ? naoAplica : rotasDoc(m, 'curso', 'curso_validade', true)}</td>
        <td>${rotasSituacao(m)}</td>
      </tr>`;
    });
  } else {
    cab = '<th>Nome</th><th>Tipo</th><th>CNPJ</th><th>Responsável</th><th class="c">Veículos</th><th class="c">Motoristas</th><th>Situação</th>';
    linhas = _rotasFrota.operadores.filter((o) => casa(o.nome, o.documento, o.contato)).map((o) => `
      <tr data-id="${esc(o.id)}">
        <td><strong>${esc(o.nome)}</strong></td>
        <td>${esc(ROTAS_TIPO_OPERADOR[o.tipo] || o.tipo)}</td>
        <td>${esc(o.documento || '—')}</td>
        <td>${esc(o.contato || '—')}</td>
        <td class="c">${o.veiculos}</td>
        <td class="c">${o.motoristas}</td>
        <td><span class="pill ${o.ativo ? 'success' : 'neutral'}">${o.ativo ? 'Ativo' : 'Inativo'}</span></td>
      </tr>`);
  }
  body.innerHTML = rotasTabela(cab, linhas, busca ? 'Nada encontrado com essa busca.' : 'Nenhum cadastro ainda.');
}

// ---------------------------------------------------------------- rotas e alunos

let _rotasCad = null;
let _rotasCadAba = 'rotas';
let _rotasCadBound = false;
let _rotasSel = '';            // rota aberta no detalhe
let _rotasMapaDetalhe = null;
let _rotasMapaEditor = null;
let _rotasParadas = [];        // paradas no editor da rota
let _rotasParadaAtiva = -1;

function rotasCadPor(lista, id) {
  return (_rotasCad?.[lista] || []).find((x) => x.id === id);
}

function rotasNomeContrato(ct) {
  if (!ct) return '—';
  return `${ct.numero ? `Nº ${ct.numero} · ` : ''}${ct.contratante_nome || '?'} → ${ct.operador_nome || '?'}`;
}

function rotasRefFonte(lista, rotulo, filtro = () => true, vazio = 'Escolha...') {
  return (atual) => [['', vazio], ...(_rotasCad?.[lista] || [])
    .filter((x) => (x.ativo && filtro(x)) || Object.values(atual).includes(x.id))
    .map((x) => [x.id, rotulo(x)])];
}

function rotasParadasFonte(atual) {
  const rota = rotasCadPor('rotas', atual.rota_id);
  if (!rota) return [['', 'Escolha a rota primeiro']];
  return [['', 'Sem parada ainda'], ...rota.paradas.map((p) => [p.id, `${p.ordem}. ${p.nome}${p.horario ? ` · ${p.horario}` : ''}`])];
}

const ROTAS_FORM_CAD = {
  contratantes: {
    titulo: 'quem paga', sub: 'Prefeitura ou secretaria que contrata o transporte. Uma empresa pode ter vários.',
    campos: [
      { k: 'nome', l: 'Nome', req: true, max: 160, full: true, ph: 'Prefeitura de ... / Secretaria de Educação' },
      { k: 'documento', l: 'CNPJ', max: 18 },
      { k: 'contato', l: 'Responsável', max: 160 },
      { k: 'telefone', l: 'Telefone', max: 20 },
    ],
  },
  contratos: {
    titulo: 'contrato', sub: 'Liga quem paga a quem roda. O preço por km é o que entra na prestação de contas.',
    campos: [
      { k: 'contratante_id', l: 'Quem paga', tipo: 'ref', req: true, fonte: rotasRefFonte('contratantes', (x) => x.nome) },
      { k: 'operador_id', l: 'Quem roda', tipo: 'ref', req: true, fonte: rotasRefFonte('operadores', (x) => x.nome) },
      { k: 'numero', l: 'Número do contrato', max: 60, ph: '012/2026' },
      { k: 'preco_km', l: 'Preço por km (R$)', max: 12, ph: '4,85' },
      { k: 'inicio', l: 'Início da vigência', tipo: 'date' },
      { k: 'fim', l: 'Fim da vigência', tipo: 'date' },
      { k: 'observacoes', l: 'Observações', tipo: 'textarea', max: 1000, full: true },
    ],
  },
  escolas: {
    titulo: 'escola', sub: 'Destino das rotas. A localização serve para conferir a chegada pelo GPS.',
    campos: [
      { k: 'nome', l: 'Nome', req: true, max: 160, full: true },
      { k: 'inep', l: 'Código INEP', max: 8 },
      { k: 'endereco', l: 'Endereço', max: 255 },
      { k: 'lat', l: 'Latitude', max: 20, ph: '-10.186', dica: 'Pode colar "lat, lon" do Google Maps aqui.' },
      { k: 'lon', l: 'Longitude', max: 20, ph: '-36.825' },
    ],
    aoAbrir() {
      const lat = document.getElementById('rotasCampo_lat');
      lat?.addEventListener('paste', (ev) => rotasColarCoordenadas(ev, lat, document.getElementById('rotasCampo_lon')));
    },
  },
  alunos: {
    titulo: 'aluno', sub: 'Só conta para o PNATE com matrícula e ligado a uma parada da rota.',
    campos: [
      { k: 'nome', l: 'Nome completo', req: true, max: 160, full: true },
      { k: 'matricula', l: 'Matrícula', max: 40 },
      { k: 'codigo_inep', l: 'Código INEP do aluno', max: 12 },
      { k: 'serie', l: 'Série / ano', max: 40, ph: '5º ano' },
      { k: 'escola_id', l: 'Escola', tipo: 'ref', fonte: rotasRefFonte('escolas', (x) => x.nome, () => true, 'A mesma da rota') },
      { k: 'rota_id', l: 'Rota', tipo: 'ref', fonte: rotasRefFonte('rotas', (x) => `${x.nome} · ${ROTAS_TURNOS[x.turno] || x.turno}`, () => true, 'Sem rota ainda') },
      { k: 'parada_id', l: 'Parada', tipo: 'ref', fonte: rotasParadasFonte },
      { k: 'responsavel', l: 'Responsável', max: 160 },
      { k: 'telefone', l: 'Telefone do responsável', max: 20 },
      { k: 'observacoes', l: 'Observações', tipo: 'textarea', max: 1000, full: true },
    ],
    aoMudar(ev) {
      if (ev.target.name !== 'rota_id') return;
      const sel = document.getElementById('rotasCampo_parada_id');
      if (sel) sel.innerHTML = rotasOpcoesHtml(rotasParadasFonte({ rota_id: ev.target.value }), '');
    },
  },
  rotas: {
    titulo: 'rota', sub: 'As paradas em ordem são o trajeto que o GPS confere. Clique no mapa para marcar a parada selecionada.',
    larga: true,
    campos: [
      { k: 'nome', l: 'Nome da rota', req: true, max: 120, ph: 'Rota 07 · Zona Rural Norte' },
      { k: 'turno', l: 'Turno', tipo: 'select', opcoes: ROTAS_TURNOS },
      { k: 'contrato_id', l: 'Contrato', tipo: 'ref', req: true, fonte: rotasRefFonte('contratos', rotasNomeContrato) },
      { k: 'escola_id', l: 'Escola de destino', tipo: 'ref', fonte: rotasRefFonte('escolas', (x) => x.nome) },
      { k: 'veiculo_id', l: 'Veículo', tipo: 'ref', fonte: rotasRefFonte('veiculos', (x) => `${x.placa}${x.lugares ? ` · ${x.lugares} lugares` : ''}${x.situacao === 'bloqueado' ? ' · BLOQUEADO' : ''}`) },
      { k: 'motorista_id', l: 'Motorista', tipo: 'ref', fonte: rotasRefFonte('pessoas', (x) => `${x.nome}${x.situacao === 'bloqueado' ? ' · BLOQUEADO' : ''}`, (x) => x.funcao === 'motorista') },
      { k: 'monitor_id', l: 'Monitor(a)', tipo: 'ref', fonte: rotasRefFonte('pessoas', (x) => x.nome, (x) => x.funcao === 'monitor', 'Sem monitor(a)') },
      { k: 'km_previsto', l: 'Km previsto por viagem', tipo: 'number', min: 0, max: 2000, step: '0.1' },
      { k: 'tolerancia_m', l: 'Tolerância de desvio (m)', tipo: 'number', min: 50, max: 5000, padrao: 300,
        dica: 'Quanto o ônibus pode se afastar do trajeto sem o GPS reprovar.' },
      { k: 'observacoes', l: 'Observações', tipo: 'textarea', max: 1000, full: true },
    ],
    extra: () => `
      <div class="rotas-paradas-titulo">
        <strong>Paradas em ordem</strong>
        <button class="secondary-action" type="button" id="rotasParadaNova"><i data-lucide="plus"></i> Adicionar parada</button>
      </div>
      <div class="rotas-paradas-editor">
        <div class="rotas-paradas-lista" id="rotasParadasLista"></div>
        <div class="rotas-paradas-mapa" id="rotasParadasMapa" aria-label="Mapa das paradas"></div>
      </div>`,
    aoAbrir(atual) { rotasEditorAbrir(atual); },
    aoFechar() { rotasEditorFechar(); },
    coletar(payload) {
      payload.paradas = _rotasParadas.map((p) => ({
        id: p.id || '', nome: (p.nome || '').trim(), referencia: (p.referencia || '').trim(),
        horario: p.horario || '', lat: p.lat ?? '', lon: p.lon ?? '',
      }));
    },
  },
};

async function loadRotasCadastro() {
  if (!_rotasCadBound) {
    _rotasCadBound = true;
    const view = document.getElementById('viewRotasCadastro');
    view.querySelectorAll('[data-rotas-cad-aba]').forEach((b) => b.addEventListener('click', () => {
      _rotasCadAba = b.dataset.rotasCadAba;
      rotasRenderCadastro();
    }));
    view.querySelectorAll('.page-heading [data-rotas-novo]').forEach((b) => b.addEventListener('click', () => rotasCadAbrir(b.dataset.rotasNovo, null)));
    let t = null;
    document.getElementById('rotasCadBusca')?.addEventListener('input', () => { clearTimeout(t); t = setTimeout(rotasRenderCadastro, 200); });
    document.getElementById('rotasCadastroBody').addEventListener('click', (ev) => {
      const ir = ev.target.closest('[data-rotas-ir]');
      if (ir) { rotasIrPara(ir.dataset.rotasIr); return; }
      const novo = ev.target.closest('[data-rotas-novo]');
      if (novo) { rotasCadAbrir(novo.dataset.rotasNovo, null); return; }
      const sel = ev.target.closest('[data-rota-sel]');
      if (sel) { _rotasSel = sel.dataset.rotaSel; rotasRenderCadastro(); return; }
      const ed = ev.target.closest('[data-editar]');
      if (ed) { rotasCadAbrir(ed.dataset.editar, ed.dataset.id); return; }
      const tr = ev.target.closest('tr[data-tabela][data-id]');
      if (tr) rotasCadAbrir(tr.dataset.tabela, tr.dataset.id);
    });
  }
  await rotasCarregarCadastro();
}

async function rotasCarregarCadastro() {
  const body = document.getElementById('rotasCadastroBody');
  try {
    const res = await api('/api/rotas/cadastro');
    if (!res) return;
    _rotasCad = await jsonOrReadableError(res, 'Falha ao carregar as rotas.');
  } catch (err) {
    body.innerHTML = `<div class="rotas-vazio"><p>${esc(err.message || 'Falha ao carregar as rotas.')}</p></div>`;
    return;
  }
  rotasRenderCadastro();
}

function rotasCadAbrir(tabela, id) {
  const cfg = ROTAS_FORM_CAD[tabela];
  if (!cfg || !_rotasCad) return;
  // o que precisa existir antes, com o caminho para resolver
  const falta = {
    contratos: !_rotasCad.operadores.length ? ['Cadastre primeiro quem roda (empresa ou frota própria) em Frota e motoristas.', 'rotas-frota']
      : !_rotasCad.contratantes.length ? ['Cadastre primeiro quem paga (prefeitura ou secretaria).', 'contratantes'] : null,
    rotas: !_rotasCad.contratos.length ? ['Cadastre primeiro o contrato da rota.', 'contratos'] : null,
  }[tabela];
  if (falta && !id) {
    showToast(falta[0], true);
    if (falta[1] === 'rotas-frota') rotasIrPara('rotas-frota');
    else if (falta[1] === 'contratantes') rotasCadAbrir('contratantes', null);
    else { _rotasCadAba = falta[1]; rotasRenderCadastro(); }
    return;
  }
  const item = id ? rotasCadPor(tabela, id) : null;
  if (id && !item) return;
  const padrao = tabela === 'alunos' && _rotasCadAba === 'rotas' && _rotasSel ? { rota_id: _rotasSel } : {};
  rotasAbrirForm({
    tabela, cfg, item, padrao,
    aoSalvar: async (novoId) => {
      if (tabela === 'rotas') _rotasSel = novoId || '';
      // aluno adicionado pelo detalhe da rota continua no detalhe
      _rotasCadAba = { contratantes: 'contratos', alunos: _rotasCadAba === 'rotas' ? 'rotas' : 'alunos' }[tabela] || tabela;
      await rotasCarregarCadastro();
    },
  });
}

function rotasRenderCadastro() {
  if (!_rotasCad) return;
  const r = _rotasCad.resumo || {};
  document.getElementById('rotasCadKpis').innerHTML = `
    <article class="rotas-kpi"><span>Rotas liberadas</span><strong>${r.rotas_liberadas ?? 0} <small>de ${r.rotas ?? 0}</small></strong></article>
    <article class="rotas-kpi${r.alunos_sem_parada ? ' is-amber' : ''}"><span>Alunos</span><strong>${r.alunos ?? 0} <small>${r.alunos_sem_parada ? `${r.alunos_sem_parada} sem parada` : 'todos com parada'}</small></strong></article>
    <article class="rotas-kpi"><span>Km previsto por dia</span><strong>${Number(r.km_dia || 0).toLocaleString('pt-BR')} <small>km</small></strong></article>
    <article class="rotas-kpi${r.rotas_bloqueadas ? ' is-danger' : ''}"><span>Rotas bloqueadas</span><strong>${r.rotas_bloqueadas ?? 0}</strong></article>`;
  document.querySelectorAll('#viewRotasCadastro [data-rotas-cad-aba]').forEach((b) => b.classList.toggle('active', b.dataset.rotasCadAba === _rotasCadAba));
  const body = document.getElementById('rotasCadastroBody');
  rotasDetalheFecharMapa();
  if (_rotasCadAba === 'rotas') body.innerHTML = rotasHtmlRotas();
  else if (_rotasCadAba === 'alunos') body.innerHTML = rotasHtmlAlunos();
  else if (_rotasCadAba === 'escolas') body.innerHTML = rotasHtmlEscolas();
  else body.innerHTML = rotasHtmlContratos();
  lucide.createIcons();
  if (_rotasCadAba === 'rotas') rotasDetalheMapa();
}

function rotasHtmlPrimeirosPassos() {
  const c = _rotasCad;
  const passo = (feito, n, txt, botao) => `<li class="${feito ? 'is-feito' : ''}">
    <span class="rotas-passo-n">${feito ? '✓' : n}</span><span>${txt}</span>${feito ? '' : botao}</li>`;
  return `<div class="rotas-vazio">
    <div class="rotas-vazio-icone"><i data-lucide="map"></i></div>
    <h2>Nenhuma rota cadastrada</h2>
    <p>A rota liga quem paga, quem roda, o ônibus, o motorista e as paradas. Faltam estes passos:</p>
    <ol class="rotas-passos">
      ${passo(c.operadores.length, 1, 'Quem roda: empresa ou frota própria, com veículos e motoristas', '<button class="secondary-action" type="button" data-rotas-ir="rotas-frota">Frota e motoristas</button>')}
      ${passo(c.contratantes.length, 2, 'Quem paga: prefeitura ou secretaria', '<button class="secondary-action" type="button" data-rotas-novo="contratantes">Cadastrar</button>')}
      ${passo(c.contratos.length, 3, 'O contrato entre os dois, com preço por km', '<button class="secondary-action" type="button" data-rotas-novo="contratos">Cadastrar</button>')}
      ${passo(c.escolas.length, 4, 'As escolas de destino', '<button class="secondary-action" type="button" data-rotas-novo="escolas">Cadastrar</button>')}
      ${passo(false, 5, 'A rota com as paradas no mapa', '<button class="primary-action" type="button" data-rotas-novo="rotas">Nova rota</button>')}
    </ol>
  </div>`;
}

function rotasHtmlRotas() {
  const c = _rotasCad;
  if (!c.rotas.length) return rotasHtmlPrimeirosPassos();
  const { casa } = rotasFiltro('rotasCadBusca');
  const lista = c.rotas.filter((r) => casa(r.nome, rotasCadPor('escolas', r.escola_id)?.nome || '', rotasCadPor('veiculos', r.veiculo_id)?.placa || ''));
  if (!lista.some((r) => r.id === _rotasSel)) _rotasSel = lista[0]?.id || '';
  const cards = lista.map((r) => `
    <button type="button" class="rotas-card${r.id === _rotasSel ? ' is-sel' : ''}" data-rota-sel="${esc(r.id)}">
      <span class="rotas-card-topo"><strong>${esc(r.nome)}</strong>${rotasPill(r.situacao)}</span>
      <span class="rotas-card-info">${esc(ROTAS_TURNOS[r.turno] || r.turno)} · ${esc(rotasCadPor('escolas', r.escola_id)?.nome || 'sem escola')}</span>
      <span class="rotas-card-info">${r.paradas.length} paradas · ${r.alunos} alunos · ${Number(r.km_previsto || 0).toLocaleString('pt-BR')} km</span>
    </button>`).join('') || '<p class="rotas-dica">Nada encontrado com essa busca.</p>';
  const rota = rotasCadPor('rotas', _rotasSel);
  return `<div class="rotas-mestre">
    <aside class="rotas-mestre-lista">${cards}</aside>
    <div class="rotas-mestre-detalhe">${rota ? rotasHtmlDetalhe(rota) : ''}</div>
  </div>`;
}

function rotasHtmlDetalhe(rota) {
  const ct = rotasCadPor('contratos', rota.contrato_id);
  const vei = rotasCadPor('veiculos', rota.veiculo_id);
  const mot = rotasCadPor('pessoas', rota.motorista_id);
  const mon = rotasCadPor('pessoas', rota.monitor_id);
  const info = (rotulo, valor) => `<div class="rotas-info"><span>${rotulo}</span><strong>${valor}</strong></div>`;
  const comSituacao = (nome, item) => item ? `${esc(nome)} ${item.situacao !== 'liberado' ? rotasPill(item.situacao) : ''}` : '<span class="rotas-falta">não definido</span>';
  const alunos = _rotasCad.alunos.filter((a) => a.rota_id === rota.id);
  const paradaNome = (id) => rota.paradas.find((p) => p.id === id)?.nome || '<span class="rotas-falta">sem parada</span>';
  return `
    <div class="rotas-detalhe-topo">
      <div><h2>${esc(rota.nome)}</h2><p>${esc(ROTAS_TURNOS[rota.turno] || rota.turno)} · ${esc(rotasCadPor('escolas', rota.escola_id)?.nome || 'sem escola de destino')}</p></div>
      <div class="rotas-detalhe-acoes">${rotasPill(rota.situacao)}
        <button class="secondary-action" type="button" data-editar="rotas" data-id="${esc(rota.id)}"><i data-lucide="pencil"></i> Editar rota e paradas</button></div>
    </div>
    ${rota.motivos.length ? `<ul class="rotas-motivos-lista is-${rota.situacao}">${rota.motivos.map((m) => `<li>${esc(m)}</li>`).join('')}</ul>` : ''}
    <div class="rotas-info-grid">
      ${info('Contrato', esc(rotasNomeContrato(ct)))}
      ${info('Veículo', comSituacao(vei ? `${vei.placa}${vei.lugares ? ` · ${vei.lugares} lugares` : ''}` : '', vei))}
      ${info('Motorista', comSituacao(mot?.nome || '', mot))}
      ${info('Monitor(a)', mon ? esc(mon.nome) : '—')}
      ${info('Km previsto', `${Number(rota.km_previsto || 0).toLocaleString('pt-BR')} km`)}
      ${info('Tolerância de desvio', `${rota.tolerancia_m} m`)}
    </div>
    <div class="rotas-detalhe-corpo">
      <div class="rotas-paradas-ro">
        ${rota.paradas.map((p) => `<div class="rotas-parada-ro">
          <span class="rotas-pino">${p.ordem}</span>
          <div><strong>${esc(p.nome)}</strong><small>${esc(p.referencia || '')}${p.lat == null ? ' <span class="rotas-falta">sem localização</span>' : ''}</small></div>
          <span>${esc(p.horario || '')}</span><span class="pill neutral">${p.alunos} aluno(s)</span>
        </div>`).join('') || '<p class="rotas-dica">Nenhuma parada. Edite a rota para marcar as paradas no mapa.</p>'}
      </div>
      <div class="rotas-detalhe-mapa" id="rotasDetalheMapa"></div>
    </div>
    <div class="rotas-alunos-rota">
      <div class="rotas-paradas-titulo"><strong>Alunos da rota (${alunos.length})</strong>
        <button class="secondary-action" type="button" data-rotas-novo="alunos"><i data-lucide="user-plus"></i> Adicionar aluno</button></div>
      ${rotasTabela('<th>Aluno</th><th>Matrícula</th><th>Série</th><th>Parada</th><th>Situação</th>',
        alunos.map((a) => `<tr data-tabela="alunos" data-id="${esc(a.id)}"><td><strong>${esc(a.nome)}</strong></td>
          <td>${esc(a.matricula || '—')}</td><td>${esc(a.serie || '—')}</td><td>${paradaNome(a.parada_id)}</td><td>${rotasSituacao(a)}</td></tr>`),
        'Nenhum aluno nesta rota.')}
    </div>`;
}

function rotasDetalheFecharMapa() {
  if (_rotasMapaDetalhe) { _rotasMapaDetalhe.remove(); _rotasMapaDetalhe = null; }
}

function rotasDesenharParadas(mapa, paradas, grupo, opcoes = {}) {
  grupo.clearLayers();
  const pontos = [];
  paradas.forEach((p, i) => {
    if (p.lat == null || p.lat === '' || p.lon == null || p.lon === '') return;
    const ll = [Number(p.lat), Number(p.lon)];
    pontos.push(ll);
    const m = L.marker(ll, { icon: rotasIconeParada(i + 1, opcoes.ativa === i), draggable: Boolean(opcoes.arrastar) })
      .bindTooltip(`${i + 1}. ${p.nome || 'parada'}${p.horario ? ` · ${p.horario}` : ''}`);
    if (opcoes.arrastar) m.on('dragend', () => opcoes.arrastar(i, m.getLatLng()));
    if (opcoes.clique) m.on('click', () => opcoes.clique(i));
    m.addTo(grupo);
  });
  if (pontos.length > 1) L.polyline(pontos, { color: '#087f5b', weight: 3, dashArray: '6 6', opacity: 0.8 }).addTo(grupo);
  return pontos;
}

function rotasCentroInicial(rota) {
  const escola = rotasCadPor('escolas', rota?.escola_id) || (_rotasCad?.escolas || []).find((e) => e.lat != null);
  return escola && escola.lat != null ? [[escola.lat, escola.lon], 14] : [ROTAS_CENTRO_PADRAO, 4];
}

function rotasDetalheMapa() {
  const el = document.getElementById('rotasDetalheMapa');
  const rota = rotasCadPor('rotas', _rotasSel);
  if (!el || !rota || typeof L === 'undefined') return;
  _rotasMapaDetalhe = L.map(el, { zoomControl: true, scrollWheelZoom: false });
  rotasTiles(_rotasMapaDetalhe);
  const grupo = L.layerGroup().addTo(_rotasMapaDetalhe);
  const pontos = rotasDesenharParadas(_rotasMapaDetalhe, rota.paradas, grupo);
  const escola = rotasCadPor('escolas', rota.escola_id);
  if (escola?.lat != null) {
    L.marker([escola.lat, escola.lon], { icon: L.divIcon({ className: '', html: '<span class="rotas-pino is-escola">E</span>', iconSize: [26, 26], iconAnchor: [13, 13] }) })
      .bindTooltip(escola.nome).addTo(grupo);
    pontos.push([escola.lat, escola.lon]);
  }
  if (pontos.length > 1) _rotasMapaDetalhe.fitBounds(pontos, { padding: [24, 24] });
  else if (pontos.length) _rotasMapaDetalhe.setView(pontos[0], 15);
  else _rotasMapaDetalhe.setView(...rotasCentroInicial(rota));
  setTimeout(() => _rotasMapaDetalhe?.invalidateSize(), 50);
}

function rotasHtmlAlunos() {
  const c = _rotasCad;
  const { busca, casa } = rotasFiltro('rotasCadBusca');
  const linhas = c.alunos.filter((a) => casa(a.nome, a.matricula, a.codigo_inep, rotasCadPor('rotas', a.rota_id)?.nome || '')).map((a) => {
    const rota = rotasCadPor('rotas', a.rota_id);
    const parada = rota?.paradas.find((p) => p.id === a.parada_id);
    return `<tr data-tabela="alunos" data-id="${esc(a.id)}">
      <td><strong>${esc(a.nome)}</strong></td><td>${esc(a.matricula || '—')}</td><td>${esc(a.serie || '—')}</td>
      <td>${esc(rotasCadPor('escolas', a.escola_id)?.nome || '—')}</td>
      <td>${rota ? esc(rota.nome) : '<span class="rotas-falta">sem rota</span>'}</td>
      <td>${parada ? esc(`${parada.ordem}. ${parada.nome}`) : '<span class="rotas-falta">sem parada</span>'}</td>
      <td>${rotasSituacao(a)}</td></tr>`;
  });
  return rotasTabela('<th>Aluno</th><th>Matrícula</th><th>Série</th><th>Escola</th><th>Rota</th><th>Parada</th><th>Situação</th>',
    linhas, busca ? 'Nada encontrado com essa busca.' : 'Nenhum aluno cadastrado. Use "Novo aluno" no topo.');
}

function rotasHtmlEscolas() {
  const { busca, casa } = rotasFiltro('rotasCadBusca');
  const linhas = _rotasCad.escolas.filter((e) => casa(e.nome, e.inep, e.endereco)).map((e) => `
    <tr data-tabela="escolas" data-id="${esc(e.id)}">
      <td><strong>${esc(e.nome)}</strong></td><td>${esc(e.inep || '—')}</td><td>${esc(e.endereco || '—')}</td>
      <td>${e.lat != null ? '<span class="pill success">marcada</span>' : '<span class="pill amber">sem localização</span>'}</td>
      <td class="c">${e.rotas}</td><td class="c">${e.alunos}</td>
      <td><span class="pill ${e.ativo ? 'success' : 'neutral'}">${e.ativo ? 'Ativa' : 'Inativa'}</span></td></tr>`);
  return `<div class="rotas-secao-acoes"><button class="secondary-action" type="button" data-rotas-novo="escolas"><i data-lucide="plus"></i> Nova escola</button></div>
    ${rotasTabela('<th>Escola</th><th>INEP</th><th>Endereço</th><th>Localização</th><th class="c">Rotas</th><th class="c">Alunos</th><th>Situação</th>',
      linhas, busca ? 'Nada encontrado com essa busca.' : 'Nenhuma escola cadastrada.')}`;
}

function rotasHtmlContratos() {
  const { busca, casa } = rotasFiltro('rotasCadBusca');
  const contratos = _rotasCad.contratos.filter((ct) => casa(ct.numero, ct.contratante_nome, ct.operador_nome)).map((ct) => `
    <tr data-tabela="contratos" data-id="${esc(ct.id)}">
      <td><strong>${esc(ct.numero || 'sem número')}</strong></td><td>${esc(ct.contratante_nome || '—')}</td><td>${esc(ct.operador_nome || '—')}</td>
      <td>${esc(rotasPreco(ct.preco_km))}</td>
      <td>${ct.inicio || ct.fim ? `${esc(rotasData(ct.inicio) || '…')} a ${esc(rotasData(ct.fim) || 'sem fim')}` : '—'}</td>
      <td class="c">${ct.rotas}</td><td>${rotasSituacao(ct)}</td></tr>`);
  const contratantes = _rotasCad.contratantes.filter((x) => casa(x.nome, x.documento, x.contato)).map((x) => `
    <tr data-tabela="contratantes" data-id="${esc(x.id)}">
      <td><strong>${esc(x.nome)}</strong></td><td>${esc(x.documento || '—')}</td><td>${esc(x.contato || '—')}</td>
      <td class="c">${x.contratos}</td><td><span class="pill ${x.ativo ? 'success' : 'neutral'}">${x.ativo ? 'Ativo' : 'Inativo'}</span></td></tr>`);
  const vazio = busca ? 'Nada encontrado com essa busca.' : 'Nenhum cadastro ainda.';
  return `
    <div class="rotas-secao-acoes"><strong>Contratos</strong><button class="primary-action" type="button" data-rotas-novo="contratos"><i data-lucide="plus"></i> Novo contrato</button></div>
    ${rotasTabela('<th>Número</th><th>Quem paga</th><th>Quem roda</th><th>Preço por km</th><th>Vigência</th><th class="c">Rotas</th><th>Situação</th>', contratos, vazio)}
    <div class="rotas-secao-acoes"><strong>Quem paga (prefeituras e secretarias)</strong><button class="secondary-action" type="button" data-rotas-novo="contratantes"><i data-lucide="plus"></i> Novo</button></div>
    ${rotasTabela('<th>Nome</th><th>CNPJ</th><th>Responsável</th><th class="c">Contratos</th><th>Situação</th>', contratantes, vazio)}`;
}

// ---------------------------------------------------------------- editor de paradas (no modal da rota)

function rotasEditorAbrir(atual) {
  _rotasParadas = (atual.paradas || []).map((p) => ({ ...p }));
  _rotasParadaAtiva = -1;
  document.getElementById('rotasParadaNova').addEventListener('click', () => rotasParadaNova(null));
  const lista = document.getElementById('rotasParadasLista');
  lista.addEventListener('input', (ev) => {
    const el = ev.target.closest('[data-p]');
    if (!el) return;
    const p = _rotasParadas[Number(el.dataset.i)];
    if (!p) return;
    if (el.dataset.p === 'lat') {
      // "lat, lon" colado de uma vez
      const m = el.value.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,;]\s*(-?\d+(?:\.\d+)?)\s*$/);
      if (m) { p.lat = m[1]; p.lon = m[2]; rotasEditorRender(); return; }
    }
    p[el.dataset.p] = el.value;
    if (['lat', 'lon', 'nome'].includes(el.dataset.p)) rotasEditorMapa(false);
  });
  lista.addEventListener('focusin', (ev) => {
    const linha = ev.target.closest('[data-linha]');
    if (linha && Number(linha.dataset.linha) !== _rotasParadaAtiva) { _rotasParadaAtiva = Number(linha.dataset.linha); rotasEditorMarcarAtiva(); }
  });
  lista.addEventListener('click', (ev) => {
    const b = ev.target.closest('[data-acao]');
    if (!b) return;
    const i = Number(b.dataset.i);
    if (b.dataset.acao === 'sobe' && i > 0) [_rotasParadas[i - 1], _rotasParadas[i]] = [_rotasParadas[i], _rotasParadas[i - 1]];
    if (b.dataset.acao === 'desce' && i < _rotasParadas.length - 1) [_rotasParadas[i + 1], _rotasParadas[i]] = [_rotasParadas[i], _rotasParadas[i + 1]];
    if (b.dataset.acao === 'tira') { _rotasParadas.splice(i, 1); _rotasParadaAtiva = -1; }
    if (b.dataset.acao === 'sobe') _rotasParadaAtiva = Math.max(0, i - 1);
    if (b.dataset.acao === 'desce') _rotasParadaAtiva = Math.min(_rotasParadas.length - 1, i + 1);
    rotasEditorRender();
  });
  rotasEditorRender();
  if (typeof L === 'undefined') return;
  _rotasMapaEditor = L.map('rotasParadasMapa', { zoomControl: true });
  rotasTiles(_rotasMapaEditor);
  _rotasMapaEditor._grupo = L.layerGroup().addTo(_rotasMapaEditor);
  _rotasMapaEditor.on('click', (ev) => {
    const ll = { lat: ev.latlng.lat.toFixed(6), lon: ev.latlng.lng.toFixed(6) };
    const ativa = _rotasParadas[_rotasParadaAtiva];
    // clique marca a parada selecionada que ainda nao tem local; senao cria
    // outra. Para mudar o lugar de uma parada, arraste o pino.
    if (ativa && (ativa.lat === '' || ativa.lat == null)) Object.assign(ativa, ll);
    else rotasParadaNova(ll);
    rotasEditorRender();
  });
  rotasEditorMapa(true, atual);
  setTimeout(() => { _rotasMapaEditor?.invalidateSize(); rotasEditorMapa(true, atual); }, 80);
}

function rotasEditorFechar() {
  if (_rotasMapaEditor) { _rotasMapaEditor.remove(); _rotasMapaEditor = null; }
  _rotasParadas = [];
  _rotasParadaAtiva = -1;
}

function rotasParadaNova(ll) {
  _rotasParadas.push({ id: '', nome: `Parada ${_rotasParadas.length + 1}`, referencia: '', horario: '', lat: ll?.lat ?? '', lon: ll?.lon ?? '' });
  _rotasParadaAtiva = _rotasParadas.length - 1;
  rotasEditorRender();
  if (!ll) document.querySelector(`#rotasParadasLista [data-linha="${_rotasParadaAtiva}"] [data-p="nome"]`)?.select();
}

function rotasEditorRender() {
  const lista = document.getElementById('rotasParadasLista');
  if (!lista) return;
  const n = _rotasParadas.length;
  lista.innerHTML = n ? _rotasParadas.map((p, i) => `
    <div class="rotas-parada-ed${i === _rotasParadaAtiva ? ' is-ativa' : ''}" data-linha="${i}">
      <span class="rotas-pino${i === _rotasParadaAtiva ? ' is-ativa' : ''}">${i + 1}</span>
      <div class="rotas-parada-campos">
        <input data-p="nome" data-i="${i}" value="${esc(p.nome || '')}" maxlength="160" placeholder="Nome da parada" aria-label="Nome da parada ${i + 1}">
        <input data-p="horario" data-i="${i}" type="time" value="${esc(p.horario || '')}" aria-label="Horário da parada ${i + 1}">
        <input data-p="referencia" data-i="${i}" value="${esc(p.referencia || '')}" maxlength="255" placeholder="Referência (ex.: porteira, capela)" aria-label="Referência da parada ${i + 1}">
        <input data-p="lat" data-i="${i}" value="${esc(p.lat ?? '')}" placeholder="Latitude" aria-label="Latitude da parada ${i + 1}">
        <input data-p="lon" data-i="${i}" value="${esc(p.lon ?? '')}" placeholder="Longitude" aria-label="Longitude da parada ${i + 1}">
      </div>
      <div class="rotas-parada-botoes">
        <button type="button" class="icon-button" data-acao="sobe" data-i="${i}" aria-label="Subir" ${i === 0 ? 'disabled' : ''}><i data-lucide="chevron-up"></i></button>
        <button type="button" class="icon-button" data-acao="desce" data-i="${i}" aria-label="Descer" ${i === n - 1 ? 'disabled' : ''}><i data-lucide="chevron-down"></i></button>
        <button type="button" class="icon-button" data-acao="tira" data-i="${i}" aria-label="Remover parada"><i data-lucide="trash-2"></i></button>
      </div>
    </div>`).join('') : '<p class="rotas-dica">Clique no mapa para criar a primeira parada, ou use "Adicionar parada".</p>';
  lucide.createIcons();
  rotasEditorMapa(false);
}

function rotasEditorMarcarAtiva() {
  document.querySelectorAll('#rotasParadasLista [data-linha]').forEach((el) => {
    const ativa = Number(el.dataset.linha) === _rotasParadaAtiva;
    el.classList.toggle('is-ativa', ativa);
    el.querySelector('.rotas-pino')?.classList.toggle('is-ativa', ativa);
  });
  rotasEditorMapa(false);
}

function rotasEditorMapa(enquadrar, atual) {
  if (!_rotasMapaEditor) return;
  const pontos = rotasDesenharParadas(_rotasMapaEditor, _rotasParadas, _rotasMapaEditor._grupo, {
    ativa: _rotasParadaAtiva,
    arrastar: (i, ll) => { Object.assign(_rotasParadas[i], { lat: ll.lat.toFixed(6), lon: ll.lng.toFixed(6) }); _rotasParadaAtiva = i; rotasEditorRender(); },
    clique: (i) => { _rotasParadaAtiva = i; rotasEditorMarcarAtiva(); },
  });
  if (!enquadrar) return;
  if (pontos.length > 1) _rotasMapaEditor.fitBounds(pontos, { padding: [24, 24] });
  else if (pontos.length) _rotasMapaEditor.setView(pontos[0], 15);
  else _rotasMapaEditor.setView(...rotasCentroInicial(atual));
}
