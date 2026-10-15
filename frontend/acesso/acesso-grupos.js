// Aba Acesso do Painel (/v3/acesso/#acesso): grupos, horarios, feriados e a
// simulacao contra as passagens reais. Nesta etapa nada vai para os leitores:
// monta, simula, confere e so depois envia.
// Rotas: GET/PUT/DELETE /api/access-control/painel/acesso/*.

let _agDados = null;
let _agVista = 'grupos';
let _agLigado = false;
let _agEditGrupo = null;
let _agEditHorario = null;
let _agGrade = null;          // { linha: Array(48) de booleanos }
let _agSim = null;
let _agSimMostrar = 100;
let _agFeriadoSite = '';
let _agFeriados = [];
let _agVoltarGrupo = null;    // horario criado de dentro da gaveta do grupo

const AG_LINHAS = [['1', 'Seg'], ['2', 'Ter'], ['3', 'Qua'], ['4', 'Qui'], ['5', 'Sex'], ['6', 'Sáb'], ['0', 'Dom'], ['feriado', 'Feriado']];
const AG_SEMANA = { '0': 'domingo', '1': 'segunda', '2': 'terça', '3': 'quarta', '4': 'quinta', '5': 'sexta', '6': 'sábado', feriado: 'feriado' };
const AG_DIA_UTIL = d => Object.fromEntries(['1', '2', '3', '4', '5'].map(k => [k, d]));
const AG_MODELOS = {
  escola: [
    ['Turno manhã', AG_DIA_UTIL([['06:30', '12:30']])],
    ['Turno tarde', AG_DIA_UTIL([['12:30', '18:30']])],
    ['Turno noite', AG_DIA_UTIL([['18:00', '22:30']])],
    ['Administrativo', AG_DIA_UTIL([['07:00', '18:00']])],
  ],
  condominio: [
    ['24 horas', Object.fromEntries(['0', '1', '2', '3', '4', '5', '6', 'feriado'].map(k => [k, [['00:00', '24:00']]]))],
    ['Prestadores', { ...AG_DIA_UTIL([['08:00', '18:00']]), '6': [['08:00', '12:00']] }],
    ['Áreas comuns', Object.fromEntries(['0', '1', '2', '3', '4', '5', '6', 'feriado'].map(k => [k, [['06:00', '22:00']]]))],
  ],
  empresa: [
    ['Horário comercial', { ...AG_DIA_UTIL([['07:30', '18:30']]), '6': [['08:00', '12:00']] }],
    ['Limpeza', { ...AG_DIA_UTIL([['05:00', '08:00'], ['18:00', '21:00']]), '6': [['05:00', '09:00']] }],
  ],
  evento: [
    ['Dias do evento', {}],
    ['Montagem e desmontagem', {}],
  ],
};

function agCampo(id) { return document.getElementById(id); }
function agSite() { return typeof _apSite === 'string' ? _apSite : ''; }
function agHorario(id) { return ((_agDados && _agDados.horarios) || []).find(h => h.id === id) || null; }
function agLeitor(id) { return ((_agDados && _agDados.leitores) || []).find(l => l.id === id) || null; }

// "06:30-12:30, 13:00-17:00" de uma linha do horario
function agFaixasTxt(f) { return (f || []).map(([a, b]) => `${a}–${b === '24:00' ? '24h' : b}`).join(', '); }

// Resumo legivel: "Seg a sex 06:30–12:30 · Sáb 08:00–12:00"
function agResumo(h) {
  if (!h) return '24 horas, todos os dias';
  const grupos = [];
  AG_LINHAS.slice(0, 7).forEach(([k, rot]) => {
    const txt = agFaixasTxt(h.dias[k]);
    if (!txt) return;
    const ult = grupos[grupos.length - 1];
    if (ult && ult.txt === txt && ult.fimIdx === AG_LINHAS.findIndex(x => x[0] === k) - 1) { ult.fim = rot; ult.fimIdx++; }
    else grupos.push({ ini: rot, fim: rot, txt, fimIdx: AG_LINHAS.findIndex(x => x[0] === k) });
  });
  const partes = grupos.map(g => `${g.ini === g.fim ? g.ini : g.ini + ' a ' + g.fim.toLowerCase()} ${g.txt}`);
  if ((h.dias.feriado || []).length) partes.push(`Feriado ${agFaixasTxt(h.dias.feriado)}`);
  return partes.join(' · ') || 'Fechado o tempo todo';
}

// Semana em miniatura: 8 linhas x 48 meias-horas
function agMini(h, grande) {
  const linhas = AG_LINHAS.map(([k, rot]) => {
    const cel = agCelulas(h ? h.dias[k] : [['00:00', '24:00']]);
    return `<div class="ag-mini-l">${grande ? `<span>${rot}</span>` : ''}<div class="ag-mini-c">${cel.map(v => `<i class="${v ? 'on' : ''}"></i>`).join('')}</div></div>`;
  }).join('');
  return `<div class="ag-mini ${grande ? 'grande' : ''}" aria-hidden="true">${linhas}
    ${grande ? '<div class="ag-mini-l"><span></span><div class="ag-mini-e"><b>0h</b><b>6h</b><b>12h</b><b>18h</b><b>24h</b></div></div>' : ''}</div>`;
}

function agMin(h) { const [a, b] = h.split(':').map(Number); return a * 60 + b; }
function agCelulas(faixas) {
  const c = Array(48).fill(false);
  (faixas || []).forEach(([a, b]) => {
    const fim = b === '23:59' ? 1440 : agMin(b);
    for (let i = 0; i < 48; i++) { const m = i * 30; if (m >= agMin(a) && m < fim) c[i] = true; }
  });
  return c;
}
function agFaixas(cel) {
  const f = [];
  let ini = -1;
  for (let i = 0; i <= 48; i++) {
    if (i < 48 && cel[i] && ini < 0) ini = i;
    if ((i === 48 || !cel[i]) && ini >= 0) {
      const h = m => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
      f.push([h(ini * 30), i === 48 ? '24:00' : h(i * 30)]);
      ini = -1;
    }
  }
  return f;
}

// ---------------------------------------------------------------- grupos
function agCardGrupo(g) {
  const h = agHorario(g.horario_id);
  const portas = g.portas.map(agLeitor).filter(Boolean);
  const avisos = [];
  if (!portas.length) avisos.push('<span class="ag-aviso"><i data-lucide="door-closed"></i>Nenhuma porta: quem está neste grupo não abre nada.</span>');
  if (!g.membros) avisos.push('<span class="ag-aviso neutro"><i data-lucide="users"></i>Ninguém no grupo ainda. Coloque pessoas pela aba Pessoas.</span>');
  return `<article class="ag-card ${g.ativo ? '' : 'inativo'}">
    <header class="ag-card-cab">
      <div><b>${esc(g.nome)}</b><small>${esc(g.site || 'sem local')} · ${apNum(g.membros)} pessoa${g.membros === 1 ? '' : 's'}${g.ativo ? '' : ' · inativo'}</small></div>
      <button type="button" class="dv-btn" data-ag-grupo="${esc(g.id)}"><i data-lucide="pencil"></i><span>Editar</span></button>
    </header>
    <div class="ag-frase">
      <span class="ag-rot">abre</span>
      <span class="ag-chips">${portas.length ? portas.map(l => `<span class="ag-chip porta"><i data-lucide="${l.funcao === 'saida' ? 'log-out' : 'log-in'}"></i>${esc(apPorta(l.nome))}</span>`).join('') : '<span class="ag-chip vazio">nenhuma porta</span>'}</span>
      <span class="ag-rot">em</span>
      <span class="ag-chips"><span class="ag-chip horario ${h ? '' : 'livre'}"><i data-lucide="clock"></i>${esc(h ? h.nome : '24 horas')}</span>
        ${g.saida_livre && h ? '<span class="ag-chip saida"><i data-lucide="log-out"></i>saída livre</span>' : ''}</span>
    </div>
    <div class="ag-card-semana">${agMini(h)}<small>${esc(agResumo(h))}</small></div>
    ${avisos.join('')}
  </article>`;
}

function agVistaGrupos() {
  const grupos = _agDados.grupos || [];
  return `<div class="ag-barra"><p>Cada grupo diz <b>quem</b> abre <b>quais portas</b> e <b>quando</b>. As pessoas entram nos grupos pela aba Pessoas.</p>
      <button class="primary-action" type="button" data-ag-novo-grupo><i data-lucide="plus"></i> Novo grupo</button></div>
    ${grupos.length ? `<div class="ag-cards">${grupos.map(agCardGrupo).join('')}</div>`
      : '<div class="dv-vazio"><i data-lucide="users"></i><b>Nenhum grupo</b><p>Crie o primeiro grupo: quem abre quais portas e em que horário.</p></div>'}`;
}

// ---------------------------------------------------------------- horarios e feriados
function agVistaHorarios() {
  const horarios = _agDados.horarios || [];
  const tipo = (_apPerfil && _apPerfil.tipo) || 'escola';
  const modelos = AG_MODELOS[tipo] || AG_MODELOS.escola;
  const sites = [...new Set((_agDados.leitores || []).map(l => l.site).concat((_agDados.grupos || []).map(g => g.site)).filter(Boolean))].sort();
  if (!_agFeriadoSite || !sites.includes(_agFeriadoSite)) {
    _agFeriadoSite = agSite() && sites.includes(agSite()) ? agSite() : (sites[0] || '');
    _agFeriados = ((_agDados.feriados[_agFeriadoSite.toUpperCase()] || {}).datas || []).slice();
  }
  return `<div class="ag-barra"><p>Horários são quadros da semana com nome. Um horário serve para vários grupos. No leitor, cabem até 6 faixas por dia.</p>
      <div class="ag-novo-h"><button class="primary-action" type="button" data-ag-novo-horario=""><i data-lucide="plus"></i> Novo horário</button>
        <div class="ag-modelos"><span>ou comece de um modelo:</span>${modelos.map(([n], i) => `<button type="button" class="ap-fl" data-ag-modelo="${i}">${esc(n)}</button>`).join('')}</div></div></div>
    ${horarios.length ? `<div class="ag-horarios">${horarios.map(h => `<article class="ag-h">
        <header><div><b>${esc(h.nome)}</b><small>${h.grupos ? `usado por ${h.grupos} grupo${h.grupos === 1 ? '' : 's'}` : 'nenhum grupo usa'}${h.site ? ' · ' + esc(h.site) : ''}</small></div>
          <button type="button" class="dv-btn" data-ag-horario="${esc(h.id)}"><i data-lucide="pencil"></i><span>Editar</span></button></header>
        ${agMini(h, true)}<small class="ag-h-resumo">${esc(agResumo(h))}</small></article>`).join('')}</div>`
      : '<div class="dv-vazio"><i data-lucide="calendar-clock"></i><b>Nenhum horário ainda</b><p>Sem horário, o grupo abre 24 horas, todos os dias, como é hoje.</p></div>'}
    <section class="ag-feriados">
      <header><div><b>Feriados</b><small>Nos feriados vale a linha "Feriado" de cada horário. Cada local tem a sua lista.</small></div>
        ${sites.length ? `<select id="agFeriadoSite" aria-label="Local dos feriados">${sites.map(s => `<option ${s === _agFeriadoSite ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select>` : ''}</header>
      ${_agFeriadoSite ? `<div class="ag-fer-lista">${_agFeriados.length ? _agFeriados.map((f, i) => `<span class="ag-fer"><b class="monospace">${f.data.split('-').reverse().join('/')}</b>${esc(f.nome || '')}<button type="button" aria-label="Tirar ${esc(f.nome || f.data)}" data-ag-fer-tira="${i}">×</button></span>`).join('') : '<span class="dv-ajuda">Nenhum feriado neste local.</span>'}</div>
      <div class="ag-fer-add"><input type="date" id="agFerData" aria-label="Data do feriado"><input id="agFerNome" placeholder="Nome (ex.: Padroeira)" maxlength="60" aria-label="Nome do feriado">
        <button type="button" class="secondary-action" id="agFerAdd"><i data-lucide="plus"></i> Adicionar</button>
        <button type="button" class="secondary-action" id="agFerNac"><i data-lucide="flag"></i> Nacionais de ${new Date().getFullYear()}</button>
        <button type="button" class="primary-action" id="agFerSalvar"><i data-lucide="save"></i> Salvar feriados</button></div>` : '<p class="dv-ajuda">Cadastre um leitor para ter um local.</p>'}
    </section>`;
}

// Feriados nacionais (Lei 662/1949 e posteriores) + Sexta-feira Santa, Carnaval e
// Corpus Christi, que dependem da Pascoa.
function agFeriadosNacionais(ano) {
  const a = ano % 19, b = Math.floor(ano / 100), c = ano % 100, d = Math.floor(b / 4), e = b % 4;
  const f = Math.floor((b + 8) / 25), g = Math.floor((b - f + 1) / 3), h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4), k = c % 4, l = (32 + 2 * e + 2 * i - h - k) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  const mes = Math.floor((h + l - 7 * m + 114) / 31), dia = ((h + l - 7 * m + 114) % 31) + 1;
  const pascoa = new Date(Date.UTC(ano, mes - 1, dia));
  const rel = n => new Date(pascoa.getTime() + n * 86400000).toISOString().slice(0, 10);
  return [
    [`${ano}-01-01`, 'Confraternização Universal'], [rel(-48), 'Carnaval (ponto facultativo)'], [rel(-47), 'Carnaval (ponto facultativo)'],
    [rel(-2), 'Sexta-feira Santa'], [`${ano}-04-21`, 'Tiradentes'], [`${ano}-05-01`, 'Dia do Trabalho'],
    [rel(60), 'Corpus Christi (ponto facultativo)'], [`${ano}-09-07`, 'Independência'], [`${ano}-10-12`, 'Nossa Senhora Aparecida'],
    [`${ano}-11-02`, 'Finados'], [`${ano}-11-15`, 'Proclamação da República'], [`${ano}-11-20`, 'Consciência Negra'], [`${ano}-12-25`, 'Natal'],
  ].map(([data, nome]) => ({ data, nome }));
}

// ---------------------------------------------------------------- simulacao
function agVistaSimulacao() {
  // Simulacao de outro local (o filtro do topo mudou) nao vale para este.
  const s = _agSim && (_agSim.rodando || (_agSim.site || '') === agSite()) ? _agSim : null;
  const local = agSite() || 'todos os locais';
  const topo = `<div class="ag-sim-barra">
      <div><b>Simular com as passagens reais</b><p>Usa as passagens de ${esc(local)} e o que está em Grupos e Horários, como se o horário já estivesse no leitor. <b>Nada é enviado aos leitores.</b></p></div>
      <div class="ag-sim-ctl"><select id="agSimDias" aria-label="Período"><option value="7">Últimos 7 dias</option><option value="14" selected>Últimos 14 dias</option><option value="30">Últimos 30 dias</option></select>
        <button type="button" class="primary-action" id="agSimRodar"><i data-lucide="play"></i> Simular</button></div></div>`;
  if (!s) return topo + '<div class="dv-vazio"><i data-lucide="flask-conical"></i><b>Monte os grupos e horários e clique em Simular</b><p>A simulação mostra quem teria sido barrado, em que porta e quando.</p></div>';
  if (s.rodando) return topo + '<div class="dv-vazio"><i data-lucide="loader-circle" class="dv-gira"></i><b>Simulando…</b></div>';
  if (!s.analisadas) return topo + '<div class="dv-vazio"><i data-lucide="search-x"></i><b>Nenhuma passagem de pessoa cadastrada no período</b><p>Troque o período ou o local no topo.</p></div>';
  const card = ({ icone, cor, estado = '', rot, val, sub, subCor = '' }) => `<div class="ap-card ${estado}"><span class="metric-icon ${cor}"><i data-lucide="${icone}"></i></span>
      <span class="ap-card-txt"><span class="ap-card-rot">${rot}</span><strong class="ap-card-val">${val}</strong><small class="${subCor}">${sub}</small></span></div>`;
  const max = Math.max(1, ...s.por_hora);
  const dia = q => { const d = new Date(q.replace(' ', 'T')); return d.toLocaleDateString('pt-BR', { weekday: 'short', day: '2-digit', month: '2-digit' }) + ' ' + q.slice(11, 16); };
  return topo + `
    <div class="ap-cards">
      ${card({ icone: 'footprints', cor: 'blue', rot: 'Passagens analisadas', val: apNum(s.analisadas), sub: `últimos ${s.dias} dias` })}
      ${card({ icone: 'check-circle-2', cor: 'green', rot: 'Seriam liberadas', val: apNum(s.liberadas), sub: `${apPct(s.liberadas, s.analisadas)}% das passagens` })}
      ${card({ icone: 'ban', cor: s.barradas ? 'red' : 'green', estado: s.barradas ? 'ruim' : '', rot: 'Barradas pelo horário', val: apNum(s.barradas), sub: s.barradas ? `${apNum(s.barradas_entrada)} entradas · ${apNum(s.barradas_saida)} saídas` : 'ninguém seria barrado', subCor: s.barradas ? 'ruim' : '' })}
      ${card({ icone: 'door-closed', cor: s.fora_das_portas ? 'amber' : 'green', estado: s.fora_das_portas ? 'atencao' : '', rot: 'Porta fora do grupo', val: apNum(s.fora_das_portas), sub: s.fora_das_portas ? 'passaram por porta que o grupo não abre' : 'todas as portas batem', subCor: s.fora_das_portas ? 'atencao' : '' })}
      ${card({ icone: 'users', cor: s.pessoas_afetadas ? 'amber' : 'green', rot: 'Pessoas afetadas', val: apNum(s.pessoas_afetadas), sub: 'teriam pelo menos uma barrada' })}
    </div>
    ${s.barradas ? `<div class="ap-rel">
      <section class="panel ap-bloco"><div class="ap-bloco-cab"><div><h3>Quando seriam barradas</h3><p>Barradas por hora do dia, somando o período</p></div></div>
        <div class="ag-horas">${s.por_hora.map((n, h) => `<div title="${String(h).padStart(2, '0')}h: ${n} barradas"><i style="height:${Math.round(n * 100 / max)}%"></i><span>${h % 3 === 0 ? h : ''}</span></div>`).join('')}</div></section>
      <section class="panel ap-bloco"><div class="ap-bloco-cab"><div><h3>Por grupo</h3><p>Liberadas e barradas em cada grupo</p></div></div>
        ${s.por_grupo.map(g => `<div class="ap-top"><span title="${esc(g.nome)}">${esc(g.nome)}</span><span class="ap-trilho ag-trilho"><i style="width:${apPct(g.barradas, g.barradas + g.liberadas)}%"></i></span><span class="monospace">${apNum(g.barradas)}</span></div>`).join('')}
      </section></div>` : ''}
    ${s.lista_barradas.length ? `<section class="panel ap-tab-hoje"><div class="panel-header ap-cab"><div><h3>Passagens que seriam barradas</h3><p>As mais recentes primeiro${s.barradas > s.lista_barradas.length ? ` · mostrando ${s.lista_barradas.length} de ${apNum(s.barradas)}` : ''}</p></div></div>
      <div class="ap-tabela"><table><thead><tr><th>Pessoa</th><th>Quando</th><th>Porta</th><th>Grupo e horário</th></tr></thead><tbody>
      ${s.lista_barradas.slice(0, _agSimMostrar).map(b => `<tr><td>${esc(b.pessoa)}</td><td class="monospace">${esc(dia(b.quando))}${b.feriado ? ' <span class="ap-chip saida">feriado</span>' : ''}</td>
        <td>${esc(apPorta(b.porta))} <span class="ap-chip ${b.tipo === 'saida' ? 'saida' : 'entrada'}">${b.tipo === 'saida' ? 'saída' : 'entrada'}</span></td><td>${esc(b.grupos.join(', '))}${b.horario ? ' · ' + esc(b.horario) : ''}</td></tr>`).join('')}
      </tbody></table></div>
      ${s.lista_barradas.length > _agSimMostrar ? '<button type="button" class="ps-mais" data-ag-sim-mais>Mostrar mais</button>' : ''}</section>` : ''}
    ${s.lista_fora.length ? `<details class="ag-fora"><summary>${apNum(s.fora_das_portas)} passagens por porta que o grupo da pessoa não abre</summary>
      <p class="dv-ajuda">A pessoa está cadastrada nesse leitor, mas nenhum grupo dela tem essa porta. Quando o envio começar, ela perderia o acesso ali. Inclua a porta no grupo, se for o caso.</p>
      <div class="ap-tabela"><table><thead><tr><th>Pessoa</th><th>Quando</th><th>Porta</th><th>Grupos da pessoa</th></tr></thead><tbody>
      ${s.lista_fora.slice(0, 100).map(b => `<tr><td>${esc(b.pessoa)}</td><td class="monospace">${esc(dia(b.quando))}</td><td>${esc(apPorta(b.porta))}</td><td>${esc(b.grupos.join(', ') || 'nenhum grupo')}</td></tr>`).join('')}
      </tbody></table></div></details>` : ''}`;
}

// ---------------------------------------------------------------- desenho e eventos
function agDesenhar() {
  const el = agCampo('agConteudo');
  if (!el || !_agDados) return;
  document.querySelectorAll('[data-ag-vista]').forEach(b => {
    const on = b.dataset.agVista === _agVista;
    b.classList.toggle('on', on);
    b.setAttribute('aria-pressed', String(on));
  });
  el.innerHTML = _agVista === 'horarios' ? agVistaHorarios() : _agVista === 'simulacao' ? agVistaSimulacao() : agVistaGrupos();
  el.querySelectorAll('[data-ag-grupo]').forEach(b => b.addEventListener('click', () => agAbrirGrupo((_agDados.grupos || []).find(g => g.id === b.dataset.agGrupo))));
  el.querySelector('[data-ag-novo-grupo]')?.addEventListener('click', () => agAbrirGrupo(null));
  el.querySelectorAll('[data-ag-horario]').forEach(b => b.addEventListener('click', () => agAbrirHorario(agHorario(b.dataset.agHorario))));
  el.querySelector('[data-ag-novo-horario]')?.addEventListener('click', () => agAbrirHorario(null));
  el.querySelectorAll('[data-ag-modelo]').forEach(b => b.addEventListener('click', () => {
    const [nome, dias] = (AG_MODELOS[(_apPerfil && _apPerfil.tipo) || 'escola'] || AG_MODELOS.escola)[+b.dataset.agModelo];
    agAbrirHorario(null, { nome, dias });
  }));
  agCampo('agFeriadoSite')?.addEventListener('change', ev => {
    _agFeriadoSite = ev.target.value;
    _agFeriados = ((_agDados.feriados[_agFeriadoSite.toUpperCase()] || {}).datas || []).slice();
    agDesenhar();
  });
  el.querySelectorAll('[data-ag-fer-tira]').forEach(b => b.addEventListener('click', () => { _agFeriados.splice(+b.dataset.agFerTira, 1); agDesenhar(); }));
  agCampo('agFerAdd')?.addEventListener('click', () => {
    const data = agCampo('agFerData').value;
    if (!data) { acToast('Escolha a data do feriado.', true); return; }
    _agFeriados = _agFeriados.filter(f => f.data !== data).concat([{ data, nome: agCampo('agFerNome').value.trim() }]).sort((a, b) => a.data.localeCompare(b.data));
    agDesenhar();
  });
  agCampo('agFerNac')?.addEventListener('click', () => {
    const nac = agFeriadosNacionais(new Date().getFullYear());
    const tem = new Set(_agFeriados.map(f => f.data));
    _agFeriados = _agFeriados.concat(nac.filter(f => !tem.has(f.data))).sort((a, b) => a.data.localeCompare(b.data));
    agDesenhar();
    acToast('Feriados nacionais adicionados. Confira e clique em Salvar feriados.');
  });
  agCampo('agFerSalvar')?.addEventListener('click', async () => {
    try {
      await acEnviar('PUT', '/api/access-control/painel/acesso/feriados', { site: _agFeriadoSite, feriados: _agFeriados });
      acToast(`Feriados de ${_agFeriadoSite} salvos.`);
      await agCarregar();
    } catch (err) { acToast(err.message, true); }
  });
  agCampo('agSimRodar')?.addEventListener('click', agSimular);
  el.querySelector('[data-ag-sim-mais]')?.addEventListener('click', () => { _agSimMostrar += 100; agDesenhar(); });
  if (_agSim && _agSim.dias && agCampo('agSimDias')) agCampo('agSimDias').value = String(_agSim.dias);
  if (window.lucide) lucide.createIcons();
}

async function agCarregar() {
  const q = agSite() ? `?site=${encodeURIComponent(agSite())}` : '';
  const d = await apiJson(`/api/access-control/painel/acesso${q}`);
  if (!d) return;
  _agDados = d;
  if (d.perfil && typeof apMostrarPerfil === 'function') apMostrarPerfil(d.perfil);
  agDesenhar();
}

async function agSimular() {
  const dias = agCampo('agSimDias') ? agCampo('agSimDias').value : '14';
  _agSim = { rodando: true, dias };
  _agSimMostrar = 100;
  agDesenhar();
  try {
    const q = new URLSearchParams({ dias });
    if (agSite()) q.set('site', agSite());
    _agSim = await apiJson(`/api/access-control/painel/acesso/simulacao?${q}`);
  } catch (err) {
    _agSim = null;
    acToast('Não consegui simular: ' + err.message, true);
  }
  agDesenhar();
}

// ---------------------------------------------------------------- gaveta do grupo
function agAbrirGrupo(g) {
  _agEditGrupo = g || null;
  const novo = !g;
  agCampo('agGTitulo').textContent = novo ? 'Novo grupo' : 'Editar grupo';
  agCampo('agGSub').textContent = novo ? 'Quem abre quais portas e quando.' : g.nome;
  agCampo('agGNome').value = novo ? '' : g.nome;
  const sites = [...new Set((_agDados.leitores || []).map(l => l.site).filter(Boolean))].sort();
  agCampo('agGSites').innerHTML = sites.map(s => `<option value="${esc(s)}">`).join('');
  agCampo('agGSite').value = novo ? agSite() : g.site;
  agCampo('agGAtivo').checked = novo ? true : g.ativo;
  agCampo('agGSaida').checked = novo ? true : g.saida_livre;
  agPortas(novo ? [] : g.portas);
  agHorariosOpcoes(novo ? '' : g.horario_id);
  agCampo('agGMembros').textContent = novo ? 'Depois de criar, coloque as pessoas pela aba Pessoas.' : `${apNum(g.membros)} pessoa${g.membros === 1 ? '' : 's'} neste grupo. Para mudar, use a aba Pessoas.`;
  agCampo('agGExcluir').hidden = novo;
  agCampo('agGConfirma').hidden = true;
  agCampo('agGErro').hidden = true;
  agMostrar('agGGaveta');
  setTimeout(() => agCampo('agGNome').focus(), 150);
}

// Seletor de portas que aguenta 100 leitores: a selecao fica num Set (busca e
// filtro so mudam o que aparece), o local do grupo vem aberto e os outros
// recolhidos, atalhos por funcao e "marcar todas" por local.
let _agPortasSel = new Set();
let _agPortasBusca = '';
let _agPortasAbertos = new Set();

// "ENTRADA 1 - ESCOLA X" dentro da secao ESCOLA X vira "ENTRADA 1".
function agSemLocal(nome, site) {
  const suf = ' - ' + String(site || '').toUpperCase();
  return String(nome || '').toUpperCase().endsWith(suf) && nome.length > suf.length ? nome.slice(0, -suf.length) : nome;
}

function agFuncaoRot(f) { return f === 'saida' ? 'saída' : f === 'entrada_saida' ? 'entrada e saída' : 'entrada'; }

function agPortas(marcadas) {
  if (marcadas) {
    _agPortasSel = new Set(marcadas);
    _agPortasBusca = '';
    _agPortasAbertos = new Set();
  }
  const site = agCampo('agGSite').value.trim().toUpperCase();
  const todos = _agDados.leitores || [];
  const el = agCampo('agGPortas');
  if (!todos.length) { el.innerHTML = '<p class="dv-ajuda">Nenhum leitor cadastrado. Cadastre em Dispositivos.</p>'; return; }
  const b = _agPortasBusca.trim().toLowerCase();
  const porLocal = new Map();
  todos.forEach(l => {
    const k = l.site || 'Sem local';
    if (!porLocal.has(k)) porLocal.set(k, []);
    porLocal.get(k).push(l);
  });
  const locais = [...porLocal.keys()].sort((a, c) => ((c.toUpperCase() === site) - (a.toUpperCase() === site)) || a.localeCompare(c, 'pt-BR'));
  const doLocal = site ? (porLocal.get(locais.find(x => x.toUpperCase() === site)) || []) : [];
  const escolhidas = todos.filter(l => _agPortasSel.has(l.id));
  const aberto = k => b || k.toUpperCase() === site || _agPortasAbertos.has(k) || locais.length === 1;
  el.innerHTML = `
    <div class="agp-topo">
      <span class="agp-conta"><b>${escolhidas.length}</b> de ${todos.length} porta${todos.length === 1 ? '' : 's'}</span>
      <label class="dv-busca agp-busca"><i data-lucide="search"></i><input type="search" id="agpBusca" placeholder="Buscar porta ou local" value="${esc(_agPortasBusca)}" aria-label="Buscar porta"></label>
    </div>
    ${doLocal.length ? `<div class="agp-atalhos">
      <button type="button" class="ap-fl" data-agp-atalho="todas">Todas do local <span class="monospace">${doLocal.length}</span></button>
      <button type="button" class="ap-fl" data-agp-atalho="entrada">Só entradas</button>
      <button type="button" class="ap-fl" data-agp-atalho="saida">Só saídas</button>
      <button type="button" class="ap-fl" data-agp-atalho="limpar">Limpar</button>
    </div>` : ''}
    ${escolhidas.length ? `<div class="agp-escolhidas">${escolhidas.slice(0, 6).map(l => `<span class="ag-chip porta">${esc(l.nome)}<button type="button" aria-label="Tirar ${esc(l.nome)}" data-agp-tira="${esc(l.id)}">×</button></span>`).join('')}${escolhidas.length > 6 ? `<span class="ag-chip saida">+${escolhidas.length - 6}</span>` : ''}</div>` : ''}
    <div class="agp-locais">${locais.map(k => {
      const itens = porLocal.get(k).filter(l => !b || [l.nome, l.site].some(x => String(x || '').toLowerCase().includes(b)))
        .sort((a, c) => a.nome.localeCompare(c.nome, 'pt-BR'));
      if (!itens.length) return '';
      const marc = porLocal.get(k).filter(l => _agPortasSel.has(l.id)).length;
      const todasMarc = marc === porLocal.get(k).length;
      return `<section class="agp-local ${aberto(k) ? 'aberto' : ''}">
        <header>
          <button type="button" class="agp-abre" data-agp-abre="${esc(k)}" aria-expanded="${aberto(k)}"><i data-lucide="chevron-right"></i><b>${esc(k)}</b>
            <small>${marc ? `${marc} de ${porLocal.get(k).length} marcada${marc === 1 ? '' : 's'}` : `${porLocal.get(k).length} porta${porLocal.get(k).length === 1 ? '' : 's'}`}${k.toUpperCase() === site ? ' · local do grupo' : ''}</small></button>
          <label class="agp-todas"><input type="checkbox" data-agp-local="${esc(k)}" ${todasMarc ? 'checked' : ''}> todas</label>
        </header>
        ${aberto(k) ? `<div class="agp-grade">${itens.map(l => `<label class="agp-porta ${_agPortasSel.has(l.id) ? 'on' : ''}">
            <input type="checkbox" value="${esc(l.id)}" ${_agPortasSel.has(l.id) ? 'checked' : ''}>
            <i data-lucide="${l.funcao === 'saida' ? 'log-out' : l.funcao === 'entrada_saida' ? 'arrow-left-right' : 'log-in'}"></i>
            <span><b title="${esc(l.nome)}">${esc(agSemLocal(l.nome, l.site))}</b><small>${agFuncaoRot(l.funcao)}${l.ativo ? '' : ' · inativo'}</small></span></label>`).join('')}</div>` : ''}
      </section>`;
    }).join('') || '<p class="dv-ajuda">Nenhuma porta com essa busca.</p>'}</div>`;
  const redesenha = () => { agPortas(); const bi = agCampo('agpBusca'); if (bi && document.activeElement !== bi && _agPortasBusca) { /* mantem */ } };
  el.querySelectorAll('.agp-porta input').forEach(x => x.addEventListener('change', () => {
    if (x.checked) _agPortasSel.add(x.value); else _agPortasSel.delete(x.value);
    redesenha();
  }));
  el.querySelectorAll('[data-agp-local]').forEach(x => x.addEventListener('change', () => {
    porLocal.get(x.dataset.agpLocal).forEach(l => (x.checked ? _agPortasSel.add(l.id) : _agPortasSel.delete(l.id)));
    _agPortasAbertos.add(x.dataset.agpLocal);
    redesenha();
  }));
  el.querySelectorAll('[data-agp-abre]').forEach(x => x.addEventListener('click', () => {
    const k = x.dataset.agpAbre;
    if (_agPortasAbertos.has(k)) _agPortasAbertos.delete(k); else _agPortasAbertos.add(k);
    redesenha();
  }));
  el.querySelectorAll('[data-agp-tira]').forEach(x => x.addEventListener('click', () => { _agPortasSel.delete(x.dataset.agpTira); redesenha(); }));
  el.querySelectorAll('[data-agp-atalho]').forEach(x => x.addEventListener('click', () => {
    const a = x.dataset.agpAtalho;
    if (a === 'limpar') _agPortasSel.clear();
    else doLocal.forEach(l => {
      const ok = a === 'todas' || l.funcao === a || l.funcao === 'entrada_saida';
      if (ok) _agPortasSel.add(l.id); else if (a !== 'todas') _agPortasSel.delete(l.id);
    });
    redesenha();
  }));
  const busca = agCampo('agpBusca');
  busca.addEventListener('input', () => {
    _agPortasBusca = busca.value;
    const pos = busca.selectionStart;
    agPortas();
    const nb = agCampo('agpBusca');
    nb.focus();
    try { nb.setSelectionRange(pos, pos); } catch (_) {}
  });
  if (window.lucide) lucide.createIcons();
}

function agHorariosOpcoes(sel) {
  const hs = _agDados.horarios || [];
  agCampo('agGHorarios').innerHTML = [`<label class="ag-op"><input type="radio" name="agGHorario" value="" ${!sel ? 'checked' : ''}><span><b>24 horas</b><small>Sem restrição, todos os dias (como é hoje).</small></span></label>`]
    .concat(hs.map(h => `<label class="ag-op"><input type="radio" name="agGHorario" value="${esc(h.id)}" ${sel === h.id ? 'checked' : ''}><span><b>${esc(h.nome)}</b><small>${esc(agResumo(h))}</small></span>${agMini(h)}</label>`))
    .join('') + '<button type="button" class="ag-link" id="agGNovoH"><i data-lucide="plus"></i> Criar horário novo</button>';
  agCampo('agGNovoH').addEventListener('click', () => {
    _agVoltarGrupo = { grupo: _agEditGrupo, form: agFormGrupo() };
    agFechar('agGGaveta');
    setTimeout(() => agAbrirHorario(null), 220);
  });
  if (window.lucide) lucide.createIcons();
}

function agFormGrupo() {
  return {
    id: (_agEditGrupo && _agEditGrupo.id) || '',
    nome: agCampo('agGNome').value.trim(),
    site: agCampo('agGSite').value.trim(),
    portas: [..._agPortasSel],
    horario_id: (document.querySelector('input[name="agGHorario"]:checked') || {}).value || '',
    saida_livre: agCampo('agGSaida').checked,
    ativo: agCampo('agGAtivo').checked,
  };
}

async function agSalvarGrupo() {
  const p = agFormGrupo();
  const e = agCampo('agGErro');
  const erro = m => { e.textContent = m; e.hidden = false; };
  if (!p.nome) return erro('Dê um nome ao grupo.');
  if (!p.site) return erro('Escolha o local do grupo.');
  e.hidden = true;
  try {
    await acEnviar('PUT', '/api/access-control/painel/acesso/grupos', p);
    agFechar('agGGaveta');
    acToast('Grupo salvo. Nada foi enviado aos leitores.');
    _agSim = null;
    await agCarregar();
  } catch (err) { erro(err.message); }
}

// ---------------------------------------------------------------- gaveta do horario
function agAbrirHorario(h, modelo) {
  _agEditHorario = h || null;
  const base = h || (modelo ? { nome: modelo.nome, dias: modelo.dias } : { nome: '', dias: {} });
  agCampo('agHTitulo').textContent = h ? 'Editar horário' : 'Novo horário';
  agCampo('agHNome').value = base.nome || '';
  agCampo('agHSite').value = (h && h.site) || agSite();
  _agGrade = Object.fromEntries(AG_LINHAS.map(([k]) => [k, agCelulas((base.dias || {})[k])]));
  agDesenharGrade();
  agCampo('agHExcluir').hidden = !h;
  agCampo('agHConfirma').hidden = true;
  agCampo('agHErro').hidden = true;
  agMostrar('agHGaveta');
  setTimeout(() => agCampo('agHNome').focus(), 150);
}

function agDesenharGrade() {
  const g = agCampo('agHGrade');
  g.innerHTML = AG_LINHAS.map(([k, rot]) => {
    const f = agFaixas(_agGrade[k]);
    const demais = f.length > 6;
    return `<div class="ag-gl ${k === 'feriado' ? 'fer' : ''}"><span class="ag-gl-rot">${rot}</span>
      <div class="ag-gl-cel" data-linha="${k}">${_agGrade[k].map((v, i) => `<i data-i="${i}" class="${v ? 'on' : ''} ${i % 2 ? '' : 'hora'}"></i>`).join('')}</div>
      <span class="ag-gl-txt ${demais ? 'ruim' : ''}">${f.length ? esc(agFaixasTxt(f)) : 'fechado'}${demais ? ' · mais de 6 faixas' : ''}</span></div>`;
  }).join('') + `<div class="ag-gl"><span class="ag-gl-rot"></span><div class="ag-gl-escala"><b>0h</b><b>3h</b><b>6h</b><b>9h</b><b>12h</b><b>15h</b><b>18h</b><b>21h</b><b>24h</b></div><span></span></div>`;
}

// Pintar arrastando: o primeiro quadrinho define se pinta ou apaga.
function agLigarGrade() {
  const g = agCampo('agHGrade');
  let pintando = null;
  const marcar = alvo => {
    if (!alvo || alvo.tagName !== 'I' || !alvo.parentElement.dataset.linha) return;
    const k = alvo.parentElement.dataset.linha, i = +alvo.dataset.i;
    if (_agGrade[k][i] === pintando) return;
    _agGrade[k][i] = pintando;
    alvo.classList.toggle('on', pintando);
  };
  g.addEventListener('pointerdown', ev => {
    const alvo = ev.target;
    if (alvo.tagName !== 'I' || !alvo.parentElement.dataset.linha) return;
    ev.preventDefault();
    pintando = !_agGrade[alvo.parentElement.dataset.linha][+alvo.dataset.i];
    marcar(alvo);
  });
  g.addEventListener('pointermove', ev => { if (pintando !== null) marcar(document.elementFromPoint(ev.clientX, ev.clientY)); });
  document.addEventListener('pointerup', () => { if (pintando !== null) { pintando = null; agDesenharGrade(); } });
}

async function agSalvarHorario() {
  const e = agCampo('agHErro');
  const erro = m => { e.textContent = m; e.hidden = false; };
  const nome = agCampo('agHNome').value.trim();
  if (!nome) return erro('Dê um nome ao horário.');
  const dias = Object.fromEntries(AG_LINHAS.map(([k]) => [k, agFaixas(_agGrade[k])]));
  const cheio = AG_LINHAS.find(([k]) => dias[k].length > 6);
  if (cheio) return erro(`${cheio[1]} tem mais de 6 faixas. O leitor guarda até 6 por dia.`);
  e.hidden = true;
  try {
    const r = await acEnviar('PUT', '/api/access-control/painel/acesso/horarios', { id: (_agEditHorario && _agEditHorario.id) || '', nome, site: agCampo('agHSite').value.trim(), dias });
    agFechar('agHGaveta');
    acToast('Horário salvo. Nada foi enviado aos leitores.');
    _agSim = null;
    await agCarregar();
    if (_agVoltarGrupo) {   // criado de dentro do grupo: volta para ele com o horario novo marcado
      const v = _agVoltarGrupo;
      _agVoltarGrupo = null;
      setTimeout(() => {
        agAbrirGrupo(v.grupo);
        agCampo('agGNome').value = v.form.nome;
        agCampo('agGSite').value = v.form.site;
        agPortas(v.form.portas);
        agHorariosOpcoes(r.horario.id);
        agCampo('agGSaida').checked = v.form.saida_livre;
        agCampo('agGAtivo').checked = v.form.ativo;
      }, 220);
    }
  } catch (err) { erro(err.message); }
}

// ---------------------------------------------------------------- gavetas (abrir/fechar)
function agMostrar(id) {
  const g = agCampo(id);
  g.hidden = false;
  requestAnimationFrame(() => g.classList.add('aberta'));
  if (window.lucide) lucide.createIcons();
}
function agFechar(id) {
  const g = agCampo(id);
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function agLigarGavetas() {
  ['agG', 'agH'].forEach(p => {
    agCampo(p + 'Fechar').addEventListener('click', () => { _agVoltarGrupo = null; agFechar(p + 'Gaveta'); });
    agCampo(p + 'Cancelar').addEventListener('click', () => { _agVoltarGrupo = null; agFechar(p + 'Gaveta'); });
    agCampo(p + 'Fundo').addEventListener('click', () => { _agVoltarGrupo = null; agFechar(p + 'Gaveta'); });
    agCampo(p + 'ConfirmaNao').addEventListener('click', () => { agCampo(p + 'Confirma').hidden = true; });
    agCampo(p + 'Excluir').addEventListener('click', () => { agCampo(p + 'Confirma').hidden = false; });
  });
  document.addEventListener('keydown', ev => {
    if (ev.key !== 'Escape') return;
    ['agGGaveta', 'agHGaveta'].forEach(id => { if (!agCampo(id).hidden) agFechar(id); });
  });
  agCampo('agGForm').addEventListener('submit', ev => { ev.preventDefault(); agSalvarGrupo(); });
  agCampo('agHForm').addEventListener('submit', ev => { ev.preventDefault(); agSalvarHorario(); });
  agCampo('agGSite').addEventListener('change', () => agPortas());
  agCampo('agGConfirmaSim').addEventListener('click', async () => {
    try {
      await acEnviar('DELETE', `/api/access-control/painel/acesso/grupos/${encodeURIComponent(_agEditGrupo.id)}`);
      agFechar('agGGaveta'); acToast('Grupo excluído.'); _agSim = null; await agCarregar();
    } catch (err) { agCampo('agGConfirma').hidden = true; const e = agCampo('agGErro'); e.textContent = err.message; e.hidden = false; }
  });
  agCampo('agHConfirmaSim').addEventListener('click', async () => {
    try {
      await acEnviar('DELETE', `/api/access-control/painel/acesso/horarios/${encodeURIComponent(_agEditHorario.id)}`);
      agFechar('agHGaveta'); acToast('Horário excluído.'); _agSim = null; await agCarregar();
    } catch (err) { agCampo('agHConfirma').hidden = true; const e = agCampo('agHErro'); e.textContent = err.message; e.hidden = false; }
  });
  agCampo('agHCopiar').addEventListener('click', () => { ['2', '3', '4', '5'].forEach(k => { _agGrade[k] = _agGrade['1'].slice(); }); agDesenharGrade(); });
  agCampo('agHLimpar').addEventListener('click', () => { AG_LINHAS.forEach(([k]) => { _agGrade[k] = Array(48).fill(false); }); agDesenharGrade(); });
  agLigarGrade();
}

// Chamado pelo Painel ao abrir a aba.
async function agAbrirAba() {
  if (!_agLigado) {
    _agLigado = true;
    agLigarGavetas();
    document.querySelectorAll('[data-ag-vista]').forEach(b => b.addEventListener('click', () => { _agVista = b.dataset.agVista; agDesenhar(); }));
  }
  if (_agDados) agDesenhar();
  try {
    await agCarregar();
  } catch (err) {
    if (!_agDados) agCampo('agConteudo').innerHTML = `<p class="ap-vazio">Não consegui carregar: ${esc((err && err.message) || err)}</p>`;
  }
}
