// Painel de Acesso (/v3/acesso/). O menu, o login e as chamadas a API ficam
// em shell.js, compartilhado com as outras paginas novas.
// ---- Painel (so leitura). Dados: /api/access-control/painel/*
// (GET, so leitura). Quatro abas, cada uma com um trabalho (estudo de UX dos
// sistemas de mercado): Ao vivo (lista + passagem selecionada com o recibo do
// aviso), Portas (um cartao por leitor), Alertas (o que precisa de alguem) e
// Relatorios (o que e para analisar, fora do ao vivo).
let _apTela = 'vivo';
let _apSite = '';
let _apPortas = [];   // ids de leitor; vazio = todas as portas do local
let _apFonte = null;
let _apTimer = null;
let _apRelogio = null;
let _apCarregando = false;
let _apUsaAvisos = false;
const _apDados = { vivo: null, geral: null, rel: null, geralEm: 0 };
let _apFiltro = 'todas';
let _apBusca = '';
let _apPessoa = '';          // "ver so esta pessoa"
let _apSel = '';             // passagem escolhida ('' = segue a mais recente)
let _apPausado = false;
let _apTopoVisto = '';       // id da passagem mais recente desenhada (para contar novas na pausa)
const AP_TELAS = ['vivo', 'dispositivos', 'pessoas', 'acesso', 'alertas', 'relatorios', 'messenger', 'conexoes'];
// Abas com arquivo proprio: o Painel so mostra/esconde e pede para carregar.
const AP_ABAS_PROPRIAS = {
  dispositivos: { el: 'apDisp', abrir: () => dvAbrirAba(), carregar: () => dvCarregar() },
  pessoas: { el: 'apPess', abrir: () => psAbrirAba(), carregar: () => psCarregar() },
  acesso: { el: 'apAcesso', abrir: () => agAbrirAba(), carregar: () => agCarregar() },
  // Messenger e Conexoes vieram da tela antiga (Controle de Acesso) em 22/10/2026.
  messenger: { el: 'apMsg', abrir: () => msAbrirAba(), carregar: () => msCarregar() },
  conexoes: { el: 'apConex', abrir: () => cnAbrirAba(), carregar: () => cnAbrirAba() },
};

// ---- datas: o leitor grava hora local sem fuso; o WhatsApp grava UTC ----
function apLocal(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T')); return isNaN(d) ? null : d; }
function apUtc(s) { const d = new Date(String(s || '').slice(0, 19).replace(' ', 'T') + 'Z'); return isNaN(d) ? null : d; }
function apHm(d) { return d ? d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : ''; }
function apHms(d) { return d ? d.toLocaleTimeString('pt-BR') : ''; }
function apHa(d) {
  if (!d) return 'nunca';
  const m = Math.round((Date.now() - d.getTime()) / 60000);
  if (m < 1) return 'agora';
  if (m < 60) return `há ${m} min`;
  if (m < 48 * 60) return `há ${Math.round(m / 60)} h`;
  return d.toLocaleDateString('pt-BR');
}
function apDur(a, b) {
  if (!a || !b) return '';
  const m = Math.max(0, Math.round((b - a) / 60000));
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
}
function apIniciais(n) {
  return String(n || '?').trim().split(/\s+/).filter(Boolean).slice(0, 2).map(x => x[0]).join('').toUpperCase() || '?';
}
function apFoto(p) {
  return p.pessoa_id && p.tem_foto
    ? `<img src="${API_BASE}/api/access-control/people/${encodeURIComponent(p.pessoa_id)}/face-photo" alt="" loading="lazy" onerror="this.remove()">` : '';
}
function apSaida(tipo) { return String(tipo || '').startsWith('saida'); }
// ---- escola x condominio -------------------------------------------------
// O tipo de cada local vem do backend (perfil, detectado pelo cadastro: escola
// tem aluno com turma/responsavel). O cadastro antigo so tem Aluno/Funcionario/
// Visitante, entao no condominio "student" e morador.
let _apPerfil = { tipo: 'escola', locais: [] };
const AP_VOCAB = {
  escola: {
    nome: 'Escola', grupo: 'Turma', dentro: 'presentes agora', hoje: 'Chegada e saída de hoje',
    tipos: { student: 'Aluno', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador' },
    sub: 'Quem está passando agora, se os responsáveis foram avisados e o que precisa de alguém.',
  },
  condominio: {
    nome: 'Condomínio', grupo: 'Unidade', dentro: 'dentro agora', hoje: 'Quem passou hoje',
    tipos: { student: 'Morador', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador', contractor: 'Prestador' },
    sub: 'Quem está entrando e saindo, como portarias e áreas comuns estão sendo usadas e o que precisa de alguém.',
  },
  empresa: {
    nome: 'Empresa', grupo: 'Setor', dentro: 'no prédio agora', hoje: 'Entrada e saída de hoje',
    tipos: { student: 'Colaborador', employee: 'Colaborador', contractor: 'Prestador', visitor: 'Visitante', resident: 'Colaborador' },
    sub: 'Quem está entrando e saindo, a jornada de cada colaborador e o que precisa de alguém.',
  },
  evento: {
    nome: 'Evento', grupo: 'Credencial', dentro: 'no evento agora', hoje: 'Check-in de hoje',
    tipos: { student: 'Participante', participant: 'Participante', staff: 'Equipe', visitor: 'Convidado', employee: 'Equipe', resident: 'Participante' },
    sub: 'Quem fez check-in, quantas pessoas estão no evento agora e o que precisa de alguém.',
  },
  misto: {
    nome: 'Vários tipos', grupo: 'Grupo', dentro: 'dentro agora', hoje: 'Quem passou hoje',
    tipos: { student: 'Aluno', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador', contractor: 'Prestador', participant: 'Participante', staff: 'Equipe' },
    sub: 'Locais de tipos diferentes juntos. Escolha um local no topo para ver o vocabulário de cada um.',
  },
};
const AP_TIPOS_LOCAL = [
  ['escola', 'Escola', 'graduation-cap', 'Alunos, turmas e aviso ao responsável'],
  ['condominio', 'Condomínio', 'building-2', 'Moradores, unidades e visitantes'],
  ['empresa', 'Empresa', 'briefcase', 'Colaboradores, setores e jornada'],
  ['evento', 'Evento', 'ticket', 'Participantes, credenciais e check-in'],
];
const AP_ORIGEM = { escolhido: 'escolhido por você', cadastro: 'palpite pelo cadastro de pessoas', nome: 'palpite pelo nome do local', cliente: 'palpite pelo restante do cliente' };
function apTipoLocal(site) {
  const s = String(site || '').toUpperCase();
  const l = (_apPerfil.locais || []).find(x => String(x.site).toUpperCase() === s);
  return l ? l.tipo : (_apPerfil.tipo === 'misto' ? 'escola' : _apPerfil.tipo);
}
function apVocab(site) { return AP_VOCAB[site === undefined ? _apPerfil.tipo : apTipoLocal(site)] || AP_VOCAB.escola; }
function apTipo(t, site) { return apVocab(site).tipos[String(t || '').toLowerCase()] || ''; }
function apEhCondominio() { return _apPerfil.tipo === 'condominio'; }
// No condominio a unidade vem no fim do nome gravado no leitor ("QUITERIA
// CASSIA C06", "THAMIS A01"): o cadastro nao tem campo de unidade.
function apUnidade(nome, site) {
  if (apTipoLocal(site) !== 'condominio') return '';
  const m = String(nome || '').trim().match(/\s([A-Z]{1,2}\d{1,3})$/i);
  return m ? m[1].toUpperCase() : '';
}
// Segunda linha da pessoa: turma (escola) ou unidade (condominio), senao o tipo.
function apGrupoDe(p) {
  return p.turma || apUnidade(p.nome, p.site) || apTipo(p.tipo_pessoa, p.site);
}

function apMostrarPerfil(perfil) {
  if (!perfil || !perfil.tipo) return;
  _apPerfil = perfil;
  const v = apVocab();
  const chip = document.getElementById('apPerfil');
  if (chip) {
    chip.textContent = v.nome;
    chip.className = 'ap-perfil ' + perfil.tipo;
    const local = _apSite ? (perfil.locais || []).find(l => l.site.toUpperCase() === _apSite.toUpperCase()) : null;
    chip.title = local ? `${local.site}: ${v.nome} (${AP_ORIGEM[local.origem] || 'palpite'}). Clique para mudar.`
      : (perfil.locais || []).map(l => `${l.site}: ${(AP_VOCAB[l.tipo] || {}).nome || l.tipo} (${AP_ORIGEM[l.origem] || 'palpite'})`).join('\n');
    chip.classList.toggle('palpite', !!local && local.origem !== 'escolhido');
    chip.dataset.site = local ? local.site : '';
  }
  const sub = document.getElementById('apSubtitulo');
  if (sub) sub.textContent = v.sub;
}
// Menu "o que e este local": aparece ao clicar no selo de tipo (topo do Painel
// e cabecalho de cada local em Dispositivos). Grava em PUT /painel/locais/tipo.
function apMenuTipo(ancora, site) {
  document.getElementById('apMenuTipo')?.remove();
  if (!site) { acToast('Escolha um local no topo para dizer o que ele é.'); return; }
  const local = (_apPerfil.locais || []).find(l => l.site.toUpperCase() === site.toUpperCase()) || {};
  const menu = document.createElement('div');
  menu.id = 'apMenuTipo';
  menu.className = 'ap-menu-tipo';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = `<div class="ap-menu-cab"><b>${esc(site)}</b><small>Este local é…</small></div>
    ${AP_TIPOS_LOCAL.map(([v, rot, ic, desc]) => `<button type="button" role="menuitemradio" aria-checked="${local.tipo === v && local.origem === 'escolhido'}" data-tipo="${v}" class="${local.tipo === v ? 'on' : ''}">
      <i data-lucide="${ic}"></i><span><b>${rot}</b><small>${desc}</small></span>${local.tipo === v ? '<i data-lucide="check" class="ap-menu-ok"></i>' : ''}</button>`).join('')}
    ${local.origem === 'escolhido' ? `<button type="button" data-tipo="" class="ap-menu-auto"><i data-lucide="wand-sparkles"></i><span><b>Voltar ao automático</b><small>o SightOps sugere: ${esc((AP_VOCAB[local.sugestao] || {}).nome || '—')}</small></span></button>` : ''}`;
  document.body.appendChild(menu);
  const r = ancora.getBoundingClientRect();
  menu.style.top = (window.scrollY + r.bottom + 6) + 'px';
  menu.style.left = Math.max(12, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - menu.offsetWidth - 12)) + 'px';
  if (window.lucide) lucide.createIcons();
  const fechar = ev => { if (!menu.contains(ev.target) && ev.target !== ancora) { menu.remove(); document.removeEventListener('mousedown', fechar); } };
  setTimeout(() => document.addEventListener('mousedown', fechar), 0);
  menu.querySelector('button')?.focus();
  menu.addEventListener('keydown', ev => { if (ev.key === 'Escape') { menu.remove(); ancora.focus(); } });
  menu.querySelectorAll('[data-tipo]').forEach(b => b.addEventListener('click', async () => {
    menu.remove();
    try {
      await acEnviar('PUT', '/api/access-control/painel/locais/tipo', { site, tipo: b.dataset.tipo });
      acToast(b.dataset.tipo ? `${site} agora é ${(AP_VOCAB[b.dataset.tipo] || {}).nome}.` : `${site} voltou ao tipo automático.`);
      apRecarregarTudo();
    } catch (err) {
      acToast((err && err.message) || 'Não foi possível mudar o tipo.', true);
    }
  }));
}

// Depois de mudar o tipo de um local: tudo que depende do vocabulario recarrega.
function apRecarregarTudo() {
  _apDados.vivo = _apDados.rel = _apDados.relCat = _apDados.geral = null;
  if (typeof _dvDados !== 'undefined') _dvDados = null;
  if (typeof _psDados !== 'undefined') _psDados = null;
  if (typeof _agDados !== 'undefined') { _agDados = null; _agSim = null; }
  apGeral(true).then(g => { apMostrarPerfil(g && g.perfil); }).catch(() => {});
  apAtualizar(true);
}

// "ENTRADA - ESCOLA PRESIDENTE DUTRA" -> "ENTRADA": o site ja esta no filtro e
// o nome inteiro nao cabia na linha.
function apPorta(nome) {
  // So com um site escolhido: em "Todos os sites" duas portas virariam "SAIDA".
  const n = String(nome || '');
  const suf = _apSite ? ' - ' + _apSite : '';
  return suf && n.toUpperCase().endsWith(suf.toUpperCase()) && n.length > suf.length ? n.slice(0, -suf.length) : n;
}
function apPct(a, b) { return b ? Math.round(a * 100 / b) : 0; }
function apNum(n) { return Number(n || 0).toLocaleString('pt-BR'); }

// O status gravado do leitor nao e confiavel (os dois da escola apareciam
// offline com 182 marcacoes no dia): a ultima marcacao conta junto.
function apPortaViva(p) {
  const u = apLocal(p.ultima);
  return String(p.status).toLowerCase() === 'online' || (u && Date.now() - u.getTime() < 30 * 60000);
}

function apKpi(icone, cor, rot, val, sub) {
  return `<article><div class="metric-icon ${cor}"><i data-lucide="${icone}"></i></div>
    <div><span>${esc(rot)}</span><strong>${esc(val)}</strong><small>${esc(sub)}</small></div></article>`;
}

// ---------------------------------------------------------------- ao vivo
// Recibo do aviso em trilha vertical: passou -> enviado -> entregue -> lido.
function apTrilha(p) {
  const a = p.aviso || {};
  const passou = apLocal(p.hora);
  const linha = (cls, rot, sub, hora) => `<div class="ap-tr ${cls}"><i></i><div><b>${rot}</b>${sub ? `<small>${sub}</small>` : ''}</div><span class="monospace">${hora || ''}</span></div>`;
  const rel = d => (d && passou ? '+' + Math.max(0, Math.round((d - passou) / 1000)) + ' s' : '');
  let corpo = linha('feito', 'Passou no leitor', esc(apPorta(p.porta)), apHms(passou));
  if (a.status === 'sem_pessoa') {
    corpo += linha('parado', 'Sem aviso', 'pessoa só está no leitor, não no cadastro do SightOps', '');
  } else if (a.status === 'sem_aviso') {
    corpo += linha('parado', 'Sem aviso', 'sem número de responsável no cadastro', '');
  } else if (!a.status) {
    corpo += linha(_apUsaAvisos ? 'espera' : 'parado', _apUsaAvisos ? 'Aviso ainda não registrado' : 'Este cliente não usa aviso por WhatsApp', a.para ? 'para ' + esc(a.para) : '', '');
  } else {
    const env = apUtc(a.enviado), at = apUtc(a.atualizado);
    const nivel = { enviado: 1, entregue: 2, lido: 3 }[a.status] || 0;
    corpo += linha('feito', 'WhatsApp enviado', a.para ? 'para ' + esc(a.para) : '', rel(env));
    if (a.status === 'falha') {
      corpo += linha('ruim', 'Não entregue', esc(a.erro || 'a Meta recusou o envio'), apHms(at));
    } else {
      corpo += linha(nivel >= 2 ? 'feito' : 'espera', 'Entregue no celular', '', nivel === 2 ? apHm(at) : '');
      corpo += linha(nivel >= 3 ? 'feito' : 'espera', 'Lido', '', nivel >= 3 ? apHm(at) : '');
    }
  }
  return `<div class="ap-trilha">${corpo}</div>`;
}

function apZap(p) {
  const s = (p.aviso || {}).status;
  if (s === 'lido') return '<span class="ap-ok">lido</span>';
  if (s === 'entregue') return '<span>entregue</span>';
  if (s === 'enviado') return '<span>enviado</span>';
  if (s === 'falha') return '<span class="ap-ruim">não entregue</span>';
  if (s === 'sem_pessoa') return '';
  return _apUsaAvisos ? '<span>sem aviso</span>' : '';
}

// Classe da linha: a tarja colorida a esquerda mostra o que pede atencao.
function apMarca(p) {
  if ((p.aviso || {}).status === 'falha') return 'falhou';
  if (!p.pessoa_id) return 'semcad';
  return '';
}

const AP_FILTROS = [
  ['todas', 'Todas', () => true],
  ['entradas', 'Entradas', p => !apSaida(p.tipo)],
  ['saidas', 'Saídas', p => apSaida(p.tipo)],
  ['semcad', 'Sem cadastro', p => !p.pessoa_id],
  ['falhou', 'Aviso não entregue', p => (p.aviso || {}).status === 'falha'],
];

function apFiltradas(lista) {
  const f = (AP_FILTROS.find(x => x[0] === _apFiltro) || AP_FILTROS[0])[2];
  const b = _apBusca.trim().toLowerCase();
  return lista.filter(p => f(p)
    && (!_apPessoa || (p.pessoa_id || p.nome) === _apPessoa)
    && (!b || [p.nome, p.turma, p.porta, apUnidade(p.nome, p.site)].some(x => String(x || '').toLowerCase().includes(b))));
}

// Cards do topo: mescla dos cards antigos (icone colorido, rotulo, numero
// grande, linha de contexto) com a faixa nova (uma peca so, compacta, clicavel
// e com a cor dizendo o estado: verde normal, ambar atencao, vermelho problema).
function apSaude(d) {
  const r = d.resumo || {}, ah = d.avisos_hoje || {};
  const totAv = (ah.lido || 0) + (ah.entregue || 0) + (ah.enviado || 0) + (ah.falha || 0);
  const portas = d.portas || [];
  const vivas = portas.filter(apPortaViva).length;
  const semCad = r.without_person || 0, total = r.total || 0;
  const alunos = (d.turmas || []).reduce((n, t) => n + (t.total || 0), 0);
  const card = ({ icone, cor, estado = '', rot, val, sub, subCor = '', tela = '' }) => `
    <button type="button" class="ap-card ${estado}" ${tela ? `data-ap-ir="${tela}" title="Abrir ${tela}"` : 'disabled'}>
      <span class="metric-icon ${cor}"><i data-lucide="${icone}"></i></span>
      <span class="ap-card-txt"><span class="ap-card-rot">${rot}</span>
        <strong class="ap-card-val">${val}</strong>
        <small class="${subCor}">${sub}</small></span>
      ${tela ? '<i data-lucide="chevron-right" class="ap-card-ir"></i>' : ''}
    </button>`;
  const cards = [];
  const semSinal = portas.length - vivas;
  cards.push(card({ icone: 'door-open', cor: semSinal ? 'red' : 'green', estado: semSinal ? 'ruim' : '',
    rot: 'Leitores com sinal', val: `${vivas}<span class="ap-card-de">/${portas.length}</span>`,
    sub: semSinal ? `${semSinal} sem sinal` : 'todos respondendo', subCor: semSinal ? 'ruim' : '', tela: 'dispositivos' }));
  const dentro = r.inside_now ?? 0;
  const semSaida = (d.sem_saida || []).length;
  cards.push(card({ icone: 'users', cor: 'cyan', estado: semSaida ? 'atencao' : '', rot: apEhCondominio() ? 'Dentro agora' : 'Presentes agora', val: apNum(dentro),
    sub: semSaida ? `${apNum(semSaida)} saída${semSaida === 1 ? '' : 's'} não registrada${semSaida === 1 ? '' : 's'}`
      : (!apEhCondominio() && alunos ? `de ${apNum(alunos)} alunos ativos` : 'última passagem foi entrada'),
    subCor: semSaida ? 'atencao' : '', tela: semSaida ? 'alertas' : 'relatorios' }));
  cards.push(card({ icone: 'log-in', cor: 'green', rot: 'Entradas hoje', val: apNum(r.entries ?? 0),
    sub: `${apNum(r.exits ?? 0)} saída${(r.exits ?? 0) === 1 ? '' : 's'}${r.manual_exits ? ` · ${r.manual_exits} manual` : ''}` }));
  if (_apUsaAvisos) {
    const entregues = (ah.lido || 0) + (ah.entregue || 0);
    const pct = totAv ? apPct(entregues, totAv) : null;
    const ruim = (ah.falha || 0) > 0;
    cards.push(card({ icone: 'message-circle', cor: ruim ? (pct !== null && pct < 90 ? 'red' : 'amber') : 'green', estado: ruim ? 'atencao' : '',
      rot: 'Avisos entregues', val: pct === null ? '—' : pct + '%',
      sub: ruim ? `${ah.falha} não entregue${ah.falha === 1 ? '' : 's'} hoje` : (totAv ? `${apPct(ah.lido || 0, totAv)}% lidos pelos responsáveis` : 'nenhum aviso hoje'),
      subCor: ruim ? 'atencao' : '', tela: 'alertas' }));
  }
  const comum = total >= 20 && semCad / total >= 0.2;
  cards.push(card({ icone: 'user-x', cor: semCad ? 'amber' : 'blue', estado: semCad && !comum ? 'atencao' : '',
    rot: apEhCondominio() ? 'Só no leitor' : 'Sem cadastro', val: apNum(semCad),
    sub: semCad ? `${apPct(semCad, total)}% das passagens de hoje` : 'todas no cadastro',
    subCor: semCad && !comum ? 'atencao' : '', tela: semCad ? 'relatorios' : '' }));
  return `<div class="ap-cards">${cards.join('')}</div>`;
}

function apLinhaPassagem(p, sel) {
  const novo = Date.now() - (apLocal(p.hora) || 0) < 60000;
  return `<button type="button" class="ap-ev ${apMarca(p)} ${sel ? 'sel' : ''} ${novo ? 'novo' : ''}" data-ap-sel="${esc(p.id)}">
    <span class="ap-tarja"></span>
    <span class="ap-av">${apIniciais(p.nome)}${apFoto(p)}</span>
    <span class="ap-quem"><b>${esc(p.nome || 'sem nome no leitor')}</b>
      <small>${esc([p.pessoa_id ? apGrupoDe(p) : ['só no leitor', apUnidade(p.nome, p.site)].filter(Boolean).join(' · '), apPorta(p.porta)].filter(Boolean).join(' · '))}</small></span>
    <span class="ap-zap">${apZap(p)}</span>
    <span class="ap-chip ${apSaida(p.tipo) ? 'saida' : 'entrada'}">${apSaida(p.tipo) ? 'Saiu' : 'Entrou'}</span>
    <span class="ap-hora monospace">${apHm(apLocal(p.hora))}</span>
  </button>`;
}

function apDetalhe(p, todas) {
  if (!p) return `<section class="panel ap-det"><div class="panel-header ap-cab"><div><h3>Passagem</h3></div></div><p class="ap-vazio ap-pad">Nenhuma passagem hoje.</p></section>`;
  const chave = p.pessoa_id || p.nome;
  const dele = todas.filter(x => (x.pessoa_id || x.nome) === chave).slice().reverse();
  return `<section class="panel ap-det">
    <div class="panel-header ap-cab"><div><h3>${_apSel ? 'Passagem selecionada' : 'Última passagem'}</h3><p>${apHa(apLocal(p.hora))}</p></div>
      ${_apSel ? '<button type="button" class="ap-link" data-ap-seguir>seguir a mais recente</button>' : ''}</div>
    <div class="ap-det-topo">
      <div class="ap-foto">${apIniciais(p.nome)}${apFoto(p)}<span class="ap-dir ${apSaida(p.tipo) ? 'saida' : ''}">${apSaida(p.tipo) ? 'SAIU' : 'ENTROU'}</span></div>
      <div class="ap-info"><b>${esc(p.nome || 'Pessoa não identificada')}</b>
        <small>${esc(p.pessoa_id ? [apTipo(p.tipo_pessoa, p.site), p.turma || (apUnidade(p.nome, p.site) ? 'unidade ' + apUnidade(p.nome, p.site) : '')].filter(Boolean).join(' · ') : ['só no leitor, fora do cadastro do SightOps', apUnidade(p.nome, p.site) ? 'unidade ' + apUnidade(p.nome, p.site) : ''].filter(Boolean).join(' · ')) || '&nbsp;'}</small>
        <small>${esc(apPorta(p.porta))} · <span class="monospace">${apHms(apLocal(p.hora))}</span></small>
        ${dele.length > 1 ? `<small>${dele.length} passagens hoje</small>` : ''}
      </div>
    </div>
    ${apComAviso(p) ? `<div class="ap-det-sec"><div class="ap-rot">Recibo do aviso</div>${apTrilha(p)}</div>` : ''}
    ${dele.length > 1 || !apComAviso(p) ? `<div class="ap-det-sec"><div class="ap-rot">Percurso de hoje</div>${apPercurso(dele, p)}</div>` : ''}
    <div class="ap-det-acoes">
      <button type="button" class="secondary-action" data-ap-pessoa="${esc(chave)}"><i data-lucide="user-search"></i> ${_apPessoa ? 'Ver todas as passagens' : 'Só esta pessoa'}</button>
      <button type="button" class="secondary-action" data-ap-ir="dispositivos"><i data-lucide="door-open"></i> Ver o leitor</button>
      ${p.pessoa_id && dele.length && !apSaida(dele[dele.length - 1].tipo) ? `<button type="button" class="secondary-action" data-ap-saida="${esc(p.pessoa_id)}" data-ap-saida-nome="${esc(p.nome)}" data-ap-saida-site="${esc(p.site || '')}"><i data-lucide="log-out"></i> Registrar saída</button>` : ''}
    </div>
  </section>`;
}

// Saida manual (veio da tela antiga): a pessoa saiu sem passar no leitor --
// buscada pelo responsavel, leitor fora, saiu pela entrada. Grava um evento
// "saida_manual" com o motivo e quem registrou. Janela so fecha por X,
// Cancelar ou Esc (clique fora perdia o que foi digitado).
function apRegistrarSaida(pid, nome, site) {
  let dlg = document.getElementById('apSaidaDlg');
  if (!dlg) {
    dlg = document.createElement('dialog');
    dlg.id = 'apSaidaDlg';
    dlg.className = 'ap-dlg';
    document.getElementById('viewAccessPainel').appendChild(dlg);
  }
  dlg.innerHTML = `<form method="dialog" class="ap-dlg-corpo">
      <header><div><b>Registrar saída</b><small>${esc(nome || 'pessoa')}${site ? ' · ' + esc(site) : ''}</small></div>
        <button type="button" class="icon-button" data-dlg-fechar aria-label="Fechar"><i data-lucide="x"></i></button></header>
      <p>Use quando a pessoa saiu sem passar no leitor. Fica no histórico como <b>saída manual</b>, com o motivo e o seu usuário.</p>
      <label class="rl-campo">Motivo<input id="apSaidaMotivo" maxlength="200" placeholder="Ex.: buscado pela mãe na secretaria"></label>
      <p class="dv-erro" id="apSaidaErro" hidden></p>
      <footer><button type="button" class="secondary-action" data-dlg-fechar>Cancelar</button>
        <button type="submit" class="primary-action" id="apSaidaOk"><i data-lucide="log-out"></i> Registrar saída</button></footer>
    </form>`;
  dlg.querySelectorAll('[data-dlg-fechar]').forEach(b => b.addEventListener('click', () => dlg.close()));
  dlg.querySelector('form').addEventListener('submit', async ev => {
    ev.preventDefault();
    const ok = document.getElementById('apSaidaOk');
    ok.disabled = true;
    try {
      await acEnviar('POST', '/api/access-control/reports/manual-exit', { person_id: pid, site, reason: document.getElementById('apSaidaMotivo').value.trim() });
      dlg.close();
      acToast(`Saída de ${nome || 'pessoa'} registrada.`);
      _apDados.vivo = null;
      apAtualizar(true);
    } catch (err) {
      const e = document.getElementById('apSaidaErro');
      e.textContent = err.message || 'Não consegui registrar.';
      e.hidden = false;
      ok.disabled = false;
    }
  });
  dlg.showModal();
  if (window.lucide) lucide.createIcons();
  setTimeout(() => document.getElementById('apSaidaMotivo')?.focus(), 50);
}

// Rodape da lista: o dia em quatro numeros. Tudo sai do que o ao vivo ja traz.
function apRodape(d, todas) {
  if (!todas.length) return '';
  const horas = d.horas || [];
  const primeira = todas[todas.length - 1];
  const pico = horas.reduce((m, h) => (h.entradas + h.saidas > m.n ? { h: h.h, n: h.entradas + h.saidas } : m), { h: -1, n: 0 });
  const agora = Date.now();
  const ultimaHora = todas.filter(p => agora - (apLocal(p.hora) || 0) < 3600000).length;
  const itens = [
    ['sunrise', 'Primeira do dia', apHm(apLocal(primeira.hora)), esc(primeira.nome || apPorta(primeira.porta) || '')],
    ['trending-up', 'Pico', pico.h >= 0 ? String(pico.h).padStart(2, '0') + 'h' : '—', pico.n ? `${apNum(pico.n)} passagens` : ''],
    ['timer', 'Última hora', apNum(ultimaHora), ultimaHora === 1 ? 'passagem' : 'passagens'],
  ];
  // Escola: quanto o responsavel espera pelo aviso (mediana passagem -> envio).
  const atrasos = todas.map(p => {
    const env = apUtc((p.aviso || {}).enviado), hora = apLocal(p.hora);
    return env && hora ? (env - hora) / 1000 : null;
  }).filter(x => x !== null && x >= 0 && x < 600).sort((a, b) => a - b);
  if (_apUsaAvisos && atrasos.length) {
    const med = Math.round(atrasos[Math.floor(atrasos.length / 2)]);
    itens.push(['send', 'Aviso chega em', med < 60 ? `${med} s` : `${Math.round(med / 60)} min`, `mediana de ${apNum(atrasos.length)} avisos`]);
  } else {
    const porPorta = {};
    todas.forEach(p => { porPorta[p.porta] = (porPorta[p.porta] || 0) + 1; });
    const top = Object.entries(porPorta).sort((a, b) => b[1] - a[1])[0];
    if (top) itens.push(['door-open', 'Porta mais usada', esc(apPorta(top[0])), `${apNum(top[1])} passagens`]);
  }
  return `<footer class="ap-rodape">${itens.map(([ic, rot, val, sub]) => `<div class="ap-rd">
      <i data-lucide="${ic}"></i><div><span>${rot}</span><b>${val}</b>${sub ? `<small>${sub}</small>` : ''}</div></div>`).join('')}</footer>`;
}

// Recibo do aviso so onde existe aviso: escola, ou condominio que usa WhatsApp.
function apComAviso(p) { return _apUsaAvisos || apTipoLocal(p.site) === 'escola'; }

// Por onde a pessoa passou hoje (portaria, academia, sauna...), na ordem.
// No condominio e o que importa; na escola completa o recibo do aviso.
function apPercurso(dele, sel) {
  const lista = dele.length ? dele : [sel];
  return `<div class="ap-trilha">${lista.map(x => `<div class="ap-tr feito ${x.id === sel.id ? 'atual' : ''}"><i></i>
    <div><b>${apSaida(x.tipo) ? 'Saiu' : 'Entrou'} · ${esc(apPorta(x.porta) || (x.tipo === 'saida_manual' ? 'saída manual' : '—'))}</b></div><span class="monospace">${apHm(apLocal(x.hora))}</span></div>`).join('')}</div>`;
}

function apDesenharVivo(d) {
  const el = document.getElementById('apVivo');
  if (!el) return;
  _apUsaAvisos = Object.keys(d.avisos_hoje || {}).length > 0;
  const todas = d.passagens || [];
  const r = d.resumo || {};
  const ag = d.avisos_agora || {};
  const semCad = r.without_person || 0, total = r.total || 0;
  const avisos = [];
  if (ag.alerta) {
    avisos.push(`<div class="ap-alerta"><i data-lucide="alert-triangle"></i><div><b>Avisos de WhatsApp falhando agora:</b>
      ${ag.falhas} de ${ag.enviados} · ${esc(ag.erro_principal || 'sem motivo informado pela Meta')}</div></div>`);
  }
  // Pessoa fora do cadastro so e alerta quando e excecao. No condominio 92%
  // das passagens sao de moradores que so estao no leitor: vira nota.
  if (total >= 20 && semCad / total >= 0.2) {
    avisos.push(`<div class="ap-nota"><i data-lucide="info"></i><div><b>${apPct(semCad, total)}% das passagens de hoje são de pessoas que só estão no leitor</b>
      (${semCad} de ${total}). Elas ficam fora da presença, dos relatórios e dos avisos.
      <a href="#" data-ap-ir="relatorios">Ver por porta</a></div></div>`);
  }
  const lista = apFiltradas(todas);
  let sel = _apSel ? todas.find(p => p.id === _apSel) : null;
  if (!sel) { _apSel = ''; sel = lista[0] || todas[0]; }
  _apTopoVisto = todas[0] ? todas[0].id : '';
  const conta = id => todas.filter((AP_FILTROS.find(x => x[0] === id) || AP_FILTROS[0])[2]).length;
  const pessoaNome = _apPessoa ? ((todas.find(p => (p.pessoa_id || p.nome) === _apPessoa) || {}).nome || 'pessoa') : '';

  el.innerHTML = `
    ${apSaude(d)}
    ${avisos.join('')}
    <div class="ap-grade">
      <section class="panel ap-feed" aria-label="Passagens de hoje">
        <div class="panel-header ap-cab"><div><h3>Passagens</h3><p>${apNum(total)} hoje · mais recente primeiro${todas.length < total ? ` · mostrando as ${todas.length} últimas` : ''}</p></div>
          <div class="ap-pausa">${_apPausado
            ? `<span class="ap-pausado">pausado<span id="apNovas"></span></span><button type="button" class="secondary-action" data-ap-pausa><i data-lucide="play"></i> Continuar</button>`
            : `<span class="ap-pulso"></span><span>ao vivo</span><button type="button" class="secondary-action" data-ap-pausa><i data-lucide="pause"></i> Pausar</button>`}</div></div>
        <div class="ap-filtros">
          ${AP_FILTROS.filter(([id]) => id === 'todas' || conta(id) || id === _apFiltro).map(([id, rot]) => `<button type="button" class="ap-fl ${_apFiltro === id ? 'on' : ''}" data-ap-filtro="${id}">${rot} <span class="monospace">${conta(id)}</span></button>`).join('')}
          ${_apPessoa ? `<button type="button" class="ap-fl on" data-ap-pessoa="">${esc(pessoaNome)} ✕</button>` : ''}
          <input type="search" id="apBusca" class="ap-busca" placeholder="Buscar nome, ${apEhCondominio() ? 'unidade' : 'turma'} ou porta" value="${esc(_apBusca)}" aria-label="Buscar passagem">
        </div>
        <div class="ap-lista" id="apLista">${lista.length ? lista.map(p => apLinhaPassagem(p, sel && p.id === sel.id)).join('') : `<p class="ap-vazio ap-pad">${todas.length ? 'Nenhuma passagem neste filtro.' : 'Nenhuma passagem hoje.'}</p>`}</div>
        ${apRodape(d, todas)}
      </section>
      <div class="ap-lado">${apDetalhe(sel, todas)}</div>
    </div>`;
  apLigarAcoes(el);
  const busca = document.getElementById('apBusca');
  busca?.addEventListener('input', () => {
    _apBusca = busca.value;
    const pos = busca.selectionStart;
    apDesenharVivo(_apDados.vivo || {});
    const nb = document.getElementById('apBusca');
    if (nb) { nb.focus(); try { nb.setSelectionRange(pos, pos); } catch (_) {} }
  });
  lucide.createIcons();
}

// Botoes comuns das abas: filtro, selecao, pausa, ir para outra aba.
function apLigarAcoes(el) {
  el.querySelectorAll('[data-ap-ir]').forEach(a => a.addEventListener('click', ev => { ev.preventDefault(); apTrocarTela(a.dataset.apIr); }));
  el.querySelectorAll('[data-ap-saida]').forEach(b => b.addEventListener('click', () => apRegistrarSaida(b.dataset.apSaida, b.dataset.apSaidaNome, b.dataset.apSaidaSite)));
  el.querySelectorAll('[data-ap-filtro]').forEach(b => b.addEventListener('click', () => { _apFiltro = b.dataset.apFiltro; apDesenharVivo(_apDados.vivo || {}); }));
  el.querySelectorAll('[data-ap-sel]').forEach(b => b.addEventListener('click', () => { _apSel = b.dataset.apSel; apDesenharVivo(_apDados.vivo || {}); }));
  el.querySelectorAll('[data-ap-seguir]').forEach(b => b.addEventListener('click', () => { _apSel = ''; apDesenharVivo(_apDados.vivo || {}); }));
  el.querySelectorAll('[data-ap-pessoa]').forEach(b => b.addEventListener('click', () => {
    _apPessoa = _apPessoa ? '' : b.dataset.apPessoa; apDesenharVivo(_apDados.vivo || {});
  }));
  el.querySelectorAll('[data-ap-pausa]').forEach(b => b.addEventListener('click', () => {
    _apPausado = !_apPausado;
    if (!_apPausado) apAtualizar(); else apDesenharVivo(_apDados.vivo || {});
  }));
}

// ---------------------------------------------------------------- alertas
// O que precisa de alguem, com gravidade. Separado da lista de passagens
// (como no C•CURE / Verkada): a passagem comum nao disputa espaco com o alarme.
// Cada alerta abre a lista de QUEM e afetado, com o motivo e o botao que leva
// ao cadastro da pessoa. Antes era so a contagem e um "Ver" que pulava para
// Relatorios sem dizer nada (22/10/2026).
let _apAlAbertos = new Set();

const AP_MOTIVO_LEITOR = {
  sem_id: 'sem ID no leitor. Abra o cadastro e salve: o SightOps usa a matrícula como ID e envia ao leitor.',
  foto: 'o leitor recusou a foto. Troque por uma foto de frente, rosto inteiro e bem iluminado.',
  leitor: 'o leitor não respondeu no envio. Confira o leitor em Dispositivos; o SightOps tenta de novo sozinho.',
};

// "Message undeliverable" da Meta e numero errado ou sem WhatsApp, quase sempre.
function apMotivoZap(erro) {
  const e = String(erro || '').toLowerCase();
  if (e.includes('undeliverable')) return 'o WhatsApp não entrega: número errado ou sem WhatsApp';
  if (e.includes('not a valid') || e.includes('invalid')) return 'número inválido';
  if (e.includes('re-engagement') || e.includes('24 hour')) return 'a pessoa não fala com o robô há mais de 24 h';
  return erro ? `a Meta respondeu: ${erro}` : 'falhou sem motivo informado';
}

function apListaAlertas() {
  const v = _apDados.vivo || {}, g = _apDados.geral || {};
  const itens = [];
  const ag = v.avisos_agora || {};
  const hm = x => { const t = apLocal(x); return t ? apHm(t) : ''; };
  if (ag.alerta) itens.push({ id: 'zap', nivel: 'grave', icone: 'message-circle-warning', titulo: 'Avisos de WhatsApp falhando agora',
    texto: `${ag.falhas} de ${ag.enviados} avisos não chegaram nos últimos ${ag.janela_min} min. Motivo da Meta: ${ag.erro_principal || 'não informado'}.` });
  (v.portas || []).filter(p => !apPortaViva(p)).forEach(p => itens.push({ id: 'sinal-' + p.id, nivel: 'grave', icone: 'door-closed', titulo: `Leitor sem sinal: ${apPorta(p.nome)}`,
    texto: `${p.ultima ? 'Última passagem ' + apHa(apLocal(p.ultima)) : 'Nenhuma passagem hoje'} e o leitor informa "${p.status || 'sem status'}".`,
    ir: 'dispositivos', irRot: 'Abrir Dispositivos' }));
  (v.portas || []).filter(p => p.relogio_errado).forEach(p => itens.push({ id: 'relogio-' + p.id, nivel: 'medio', icone: 'clock-alert', titulo: `Relógio errado: ${apPorta(p.nome)}`,
    texto: `${p.relogio_errado} passagens chegaram com data antes de 2020 e ficam fora dos relatórios. Acerte a hora em Dispositivos › Controladora.`,
    ir: 'dispositivos', irRot: 'Abrir Dispositivos' }));

  // Quem nao foi para o leitor, uma linha por pessoa (antes: uma por pessoa x leitor, tudo como "foto").
  const porPessoa = new Map();
  ((g.fotos || {}).recusadas || []).forEach(r => {
    const k = r.pessoa_id || r.pessoa;
    if (!porPessoa.has(k)) porPessoa.set(k, { ...r, leitores: [] });
    porPessoa.get(k).leitores.push(apPorta(r.leitor));
  });
  const fora = [...porPessoa.values()];
  const semLeitor = fora.filter(r => r.motivo !== 'foto');
  const fotoRuim = fora.filter(r => r.motivo === 'foto');
  const linhaLeitor = r => ({ nome: r.pessoa, sub: r.turma, pessoa_id: r.pessoa_id,
    detalhe: `${r.leitores.join(' e ')}: ${AP_MOTIVO_LEITOR[r.motivo] || r.erro || 'recusado'}`, acao: 'Abrir cadastro' });
  if (semLeitor.length) itens.push({ id: 'semleitor', nivel: 'medio', icone: 'user-x',
    titulo: `${semLeitor.length} pessoa${semLeitor.length === 1 ? ' não está' : 's não estão'} nos leitores`,
    texto: 'Estão no SightOps mas não abrem a porta: não foram cadastradas no leitor.', linhas: semLeitor.map(linhaLeitor) });
  if (fotoRuim.length) itens.push({ id: 'foto', nivel: 'medio', icone: 'scan-face',
    titulo: `${fotoRuim.length} foto${fotoRuim.length === 1 ? '' : 's'} recusada${fotoRuim.length === 1 ? '' : 's'} pelos leitores`,
    texto: 'Essas pessoas não abrem a porta pelo rosto até a foto ser trocada.', linhas: fotoRuim.map(linhaLeitor) });

  const av = g.avisos || {};
  const falhando = (av.falhando || []).filter(f => f.pessoa_id);
  if (falhando.length) itens.push({ id: 'avisos', nivel: 'medio', icone: 'phone-off',
    titulo: `${falhando.length} responsáve${falhando.length === 1 ? 'l não está' : 'is não estão'} recebendo aviso`,
    texto: 'O último aviso para esses números não chegou. Confira o número no cadastro.',
    linhas: falhando.map(f => ({ nome: f.responsavel || f.pessoa, pessoa_id: f.pessoa_id,
      sub: f.responsavel && f.responsavel !== f.pessoa ? `responsável por ${f.pessoa}${f.turma ? ' · ' + f.turma : ''}` : f.turma,
      detalhe: `${typeof psFoneFmt === 'function' ? psFoneFmt(f.numero) : f.numero}: ${apMotivoZap(f.erro)}${f.quando ? ' · ' + apHa(apLocal(f.quando)) : ''}`,
      acao: 'Corrigir número' })) });

  // Presenca vale 8 h: quem entrou e nao passou na saida vira aviso e o dia
  // comeca zerado. Duas entradas seguidas e o motivo mais comum: saiu pelo
  // leitor de entrada. Um alerta so por pessoa (antes eram dois cartoes).
  const semSaida = v.sem_saida || [];
  if (semSaida.length) itens.push({ id: 'saida', nivel: 'medio', icone: 'log-out',
    titulo: `${semSaida.length} saída${semSaida.length === 1 ? '' : 's'} não registrada${semSaida.length === 1 ? '' : 's'}`,
    texto: 'Entraram e não passaram no leitor de saída em 8 horas; não contam mais como presentes.',
    linhas: semSaida.map(x => ({ nome: x.nome, pessoa_id: x.pessoa_id, saida: true, site: x.site || '', sub: x.desde ? `entrou ${hm(x.desde)}` : '',
      detalhe: x.dupla_entrada ? 'Passou duas vezes na entrada: provavelmente saiu pelo leitor de entrada.' : 'Nenhuma passagem de saída depois da entrada.' })) });
  const duplas = (v.dentro || []).filter(x => x.dupla_entrada);
  if (duplas.length) itens.push({ id: 'duplas', nivel: 'info', icone: 'repeat', titulo: `${duplas.length} com duas entradas seguidas`,
    texto: 'Estão contando como presentes, mas passaram duas vezes na entrada: talvez tenham saído pelo leitor de entrada.',
    linhas: duplas.map(x => ({ nome: x.nome, pessoa_id: x.pessoa_id, sub: x.desde ? `entrou ${hm(x.desde)}` : '' })) });

  const semNum = av.sem_numero || [];
  if (av.sem_numero_total) itens.push({ id: 'semnum', nivel: 'info', icone: 'contact',
    titulo: `${av.sem_numero_total} aluno${av.sem_numero_total === 1 ? '' : 's'} sem número de responsável`,
    texto: 'Não recebem aviso nenhum de entrada e saída.',
    linhas: semNum.map(x => ({ nome: x.pessoa, sub: x.turma, pessoa_id: x.pessoa_id, acao: 'Adicionar número' })) });
  const r = v.resumo || {};
  const semCad = r.without_person || 0, total = r.total || 0;
  if (semCad) itens.push({ id: 'semcad', nivel: total >= 20 && semCad / total >= 0.2 ? 'info' : 'medio', icone: 'user-search',
    titulo: `${semCad} passage${semCad === 1 ? 'm' : 'ns'} hoje de quem só está no leitor`,
    texto: apEhCondominio()
      ? 'Moradores que estão no leitor mas não no cadastro do SightOps ficam fora de "dentro agora" e dos relatórios. Para trazer: Pessoas › Trazer do leitor.'
      : 'Ficam fora da presença, dos relatórios e dos avisos. Para trazer: Pessoas › Trazer do leitor.',
    ir: 'relatorios', irRot: 'Ver por porta' });
  return itens;
}

function apContaAlertas() {
  if (!_apDados.vivo) return 0;
  return apListaAlertas().filter(i => i.nivel === 'grave' || i.nivel === 'medio').length;
}

// Numero de alertas no submenu "Alertas" do menu lateral.
function apMarcarAba() {
  const b = document.querySelector('.nav-item[data-ap-tela="alertas"]');
  if (!b) return;
  const n = apContaAlertas();
  let s = b.querySelector('.ap-nav-n');
  if (!s) { s = document.createElement('span'); s.className = 'alert-nav-badge ap-nav-n'; b.appendChild(s); }
  s.textContent = n;
  s.hidden = !n;
}

function apDesenharAlertas() {
  const el = document.getElementById('apAlertas');
  if (!el) return;
  const ordem = { grave: 0, medio: 1, info: 2 };
  const itens = apListaAlertas().sort((a, b) => ordem[a.nivel] - ordem[b.nivel]);
  const rot = { grave: 'agir agora', medio: 'resolver hoje', info: 'para saber' };
  if (!itens.length) {
    el.innerHTML = '<div class="dv-vazio"><i data-lucide="shield-check"></i><b>Nada precisando de alguém</b><p>Leitores no ar, avisos chegando e todo mundo cadastrado nos leitores.</p></div>';
    lucide.createIcons();
    return;
  }
  const linha = l => `<li class="ap-al-l">
      <div class="ap-cresce"><b>${esc(l.nome || 'sem nome')}</b>${l.sub ? `<small>${esc(l.sub)}</small>` : ''}${l.detalhe ? `<p>${esc(l.detalhe)}</p>` : ''}</div>
      ${l.saida && l.pessoa_id ? `<button type="button" class="secondary-action" data-ap-saida="${esc(l.pessoa_id)}" data-ap-saida-nome="${esc(l.nome)}" data-ap-saida-site="${esc(l.site || '')}">Registrar saída</button>`
        : l.pessoa_id && !String(l.pessoa_id).startsWith('ctl-') ? `<button type="button" class="secondary-action" data-ap-abre-pessoa="${esc(l.pessoa_id)}">${esc(l.acao || 'Abrir cadastro')}</button>` : ''}</li>`;
  el.innerHTML = `<div class="ap-alertas">${itens.map(i => {
    const n = (i.linhas || []).length;
    const aberto = _apAlAbertos.has(i.id);
    return `<article class="ap-al ${i.nivel} ${aberto ? 'aberto' : ''}">
      <div class="ap-al-cab">
        <span class="ap-al-ic"><i data-lucide="${i.icone}"></i></span>
        <div class="ap-cresce"><div class="ap-al-tit"><b>${esc(i.titulo)}</b><span class="ap-al-niv">${rot[i.nivel]}</span></div><p>${esc(i.texto)}</p></div>
        ${n ? `<button type="button" class="secondary-action" data-ap-al-abre="${esc(i.id)}" aria-expanded="${aberto}"><i data-lucide="${aberto ? 'chevron-up' : 'chevron-down'}"></i> ${aberto ? 'Fechar' : n === 1 ? 'Ver quem' : `Ver os ${n}`}</button>`
          : i.ir ? `<button type="button" class="secondary-action" data-ap-ir="${i.ir}">${esc(i.irRot || 'Ver')}</button>` : ''}
      </div>
      ${n && aberto ? `<ul class="ap-al-lista">${i.linhas.map(linha).join('')}</ul>` : ''}
    </article>`;
  }).join('')}</div>`;
  apLigarAcoes(el);
  el.querySelectorAll('[data-ap-al-abre]').forEach(b => b.addEventListener('click', () => {
    const id = b.dataset.apAlAbre;
    if (_apAlAbertos.has(id)) _apAlAbertos.delete(id); else _apAlAbertos.add(id);
    apDesenharAlertas();
  }));
  el.querySelectorAll('[data-ap-abre-pessoa]').forEach(b => b.addEventListener('click', () => apAbrirPessoa(b.dataset.apAbrePessoa)));
  lucide.createIcons();
}

// Leva ao cadastro da pessoa (aba Pessoas, gaveta aberta).
async function apAbrirPessoa(id) {
  apTrocarTela('pessoas');
  const acha = () => ((typeof _psDados !== 'undefined' && _psDados && _psDados.pessoas) || []).find(p => p.id === id);
  try {
    if (!acha()) await psCarregar();
  } catch (_) {}
  const p = acha();
  if (p) psAbrir(p);
  else acToast('Não achei essa pessoa no local escolhido. Troque o local no topo para "Todos".', true);
}

// ---------------------------------------------------------------- relatorios
// Catalogo por modo do local (escola, condominio, empresa, evento): cada
// relatorio responde uma pergunta, tem periodo/filtros e sai em PDF. Desenho
// aprovado em 22/10/2026. Diagnostico do sistema (leitores, fotos, marcacoes
// sem pessoa) nao fica aqui: esta em Alertas e Dispositivos.
const AP_DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];
let _apRelSel = '';
let _apRelF = { periodo: 'mes', de: '', ate: '', dia: '', grupo: '', quem: '' };
let _apRelMostrar = 150;
let _apRelPedido = 0;          // so a resposta do ultimo pedido vale (troca rapida de relatorio)

function apMapaCalor(mapa) {
  mapa = mapa || [];
  const comDado = h => mapa.some(l => l[h]);
  let ini = 0, fim = 23;
  while (ini < 23 && !comDado(ini)) ini++;
  while (fim > ini && !comDado(fim)) fim--;
  ini = Math.min(ini, 6); fim = Math.max(fim, 20);
  const horas = []; for (let h = ini; h <= fim; h++) horas.push(h);
  const max = Math.max(1, ...mapa.flat());
  const nivel = n => (!n ? 0 : n / max < 0.15 ? 1 : n / max < 0.4 ? 2 : n / max < 0.7 ? 3 : 4);
  return `<div class="ap-calor" style="grid-template-columns:34px repeat(${horas.length},minmax(16px,1fr))">
    <span></span>${horas.map(h => `<span class="ap-calor-h monospace">${h % 3 === 0 ? h + 'h' : ''}</span>`).join('')}
    ${AP_DIAS.map((dia, di) => `<span class="ap-calor-d">${dia}</span>${horas.map(h => {
      const n = (mapa[di] || [])[h] || 0;
      return `<span class="ap-calor-c n${nivel(n)}" title="${dia} ${String(h).padStart(2, '0')}h: ${n} passagens"></span>`;
    }).join('')}`).join('')}
  </div>
  <div class="ap-calor-esc"><span>menos</span>${[0, 1, 2, 3, 4].map(n => `<i class="ap-calor-c n${n}"></i>`).join('')}<span>mais</span></div>`;
}

function apSerieDias(serie, campo = 'passagens', rot = 'passagens') {
  serie = serie || [];
  const max = Math.max(1, ...serie.map(s => s[campo] || 0));
  const dia = s => `${s.slice(8, 10)}/${s.slice(5, 7)}`;
  return `<div class="ap-dias">${serie.map(s => `<div title="${dia(s.dia)}: ${apNum(s[campo])} ${rot}${s.pessoas !== undefined ? `, ${apNum(s.pessoas)} pessoas` : ''}">
      <i style="height:${Math.round((s[campo] || 0) * 100 / max)}%"></i></div>`).join('')}</div>
    <div class="ap-eixo monospace"><span>${serie[0] ? dia(serie[0].dia) : ''}</span><span>${serie.length ? dia(serie[serie.length - 1].dia) : ''}</span></div>`;
}

const apMaiuscula = t => String(t || '').charAt(0).toUpperCase() + String(t || '').slice(1);
const apBr = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : '';
const apDiaMes = iso => iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '';
const apHoraTxt = t => (t || '').slice(11, 16) || '—';
const apMin = m => (m === null || m === undefined) ? '—' : m < 60 ? `${m} min` : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`;
function apIsoHoje(off = 0) { const d = new Date(Date.now() + off * 86400000); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }

// Periodo escolhido -> de/ate (data local)
function apRelPeriodo() {
  const f = _apRelF, hoje = apIsoHoje();
  if (f.periodo === 'escolher') return { de: f.de || apIsoHoje(-29), ate: f.ate || hoje };
  if (f.periodo === 'hoje') return { de: hoje, ate: hoje };
  if (f.periodo === 'semana') { const dow = (new Date().getDay() + 6) % 7; return { de: apIsoHoje(-dow), ate: hoje }; }
  if (f.periodo === 'mes') return { de: hoje.slice(0, 8) + '01', ate: hoje };
  if (f.periodo === 'bimestre') return { de: apIsoHoje(-59), ate: hoje };
  return { de: apIsoHoje(-29), ate: hoje };
}

function apRelQuery(rel) {
  const q = new URLSearchParams();
  if (_apSite) q.set('site', _apSite);
  const m = (rel || {}).motor;
  if (m === 'diario') q.set('dia', _apRelF.dia || apIsoHoje());
  else if (m !== 'cadastro') { const p = apRelPeriodo(); q.set('de', p.de); q.set('ate', p.ate); }
  if (m === 'presenca') { if (_apRelF.grupo) q.set('grupo', _apRelF.grupo); if (_apRelF.quem) q.set('quem', _apRelF.quem); }
  if ((m === 'diario' || m === 'uso') && _apPortas.length) q.set('portas', _apPortas.join(','));
  return q.toString();
}

function apRelAtual() {
  const c = _apDados.relCat || {};
  return (c.relatorios || []).find(r => r.id === _apRelSel) || (c.relatorios || [])[0] || null;
}

async function apRelCarregar() {
  const pedido = ++_apRelPedido;
  const cat = await acJson(`/api/access-control/painel/relatorios/catalogo${_apSite ? `?site=${encodeURIComponent(_apSite)}` : ''}`) || {};
  if (pedido !== _apRelPedido) return;
  _apDados.relCat = cat;
  apMostrarPerfil(cat.perfil);
  if (cat.precisa_local) { _apDados.rel = null; return; }
  const rel = apRelAtual();
  if (!rel) return;
  _apRelSel = rel.id;
  if (!(cat.quem || []).some(q => q.id === _apRelF.quem)) _apRelF.quem = (cat.quem || [])[0] ? cat.quem[0].id : '';
  const grupos = ((cat.quem || []).find(q => q.id === _apRelF.quem) || {}).grupos || [];
  if (_apRelF.grupo && !grupos.includes(_apRelF.grupo)) _apRelF.grupo = '';   // trocou de local ou de "quem"
  _apDados.rel = { carregando: true, id: rel.id };
  apDesenharRel();
  let r;
  try {
    r = await acJson(`/api/access-control/painel/relatorios/r/${encodeURIComponent(rel.id)}?${apRelQuery(rel)}`) || {};
  } catch (err) {
    r = { erro: (err && err.message) || 'falhou' };
  }
  if (pedido === _apRelPedido) _apDados.rel = r;
}

function apRelFiltros(rel) {
  const c = _apDados.relCat || {}, v = c.vocab || {};
  const m = rel.motor;
  const chip = (id, rot) => `<button type="button" class="${_apRelF.periodo === id ? 'on' : ''}" data-rl-periodo="${id}">${rot}</button>`;
  let h = '';
  if (m === 'diario') {
    h += `<label class="rl-campo">Dia<input type="date" id="rlDia" value="${esc(_apRelF.dia || apIsoHoje())}" max="${apIsoHoje()}"></label>`;
  } else if (m !== 'cadastro') {
    const p = apRelPeriodo();
    h += `<div class="rl-campo"><span>Período</span><div class="rl-seg" role="group" aria-label="Período">
      ${chip('hoje', 'Hoje')}${chip('semana', 'Semana')}${chip('mes', 'Mês')}${chip('30', '30 dias')}${c.modo === 'escola' ? chip('bimestre', 'Bimestre') : ''}${chip('escolher', 'Escolher datas')}</div></div>`;
    if (_apRelF.periodo === 'escolher') h += `<label class="rl-campo">De<input type="date" id="rlDe" value="${esc(p.de)}" max="${apIsoHoje()}"></label>
      <label class="rl-campo">Até<input type="date" id="rlAte" value="${esc(p.ate)}" max="${apIsoHoje()}"></label>`;
  }
  if (m === 'presenca') {
    const quem = (c.quem || []).find(q => q.id === _apRelF.quem) || (c.quem || [])[0] || { grupos: [] };
    if ((c.quem || []).length > 1) h += `<label class="rl-campo">Quem<select id="rlQuem">${c.quem.map(q => `<option value="${esc(q.id)}" ${q.id === _apRelF.quem ? 'selected' : ''}>${esc(q.nome)}</option>`).join('')}</select></label>`;
    h += `<label class="rl-campo">${esc(v.grupo || 'Grupo')}<select id="rlGrupo"><option value="">Todas as ${esc(v.grupos || 'opções')}</option>
      ${(quem.grupos || []).map(g => `<option ${g === _apRelF.grupo ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></label>`;
  }
  return h;
}

function apRelCorpo(r, rel) {
  if (!r || r.carregando) return '<div class="dv-vazio"><i data-lucide="loader-circle" class="dv-gira"></i><b>Montando o relatório…</b></div>';
  if (r.erro) return `<p class="ap-vazio">Não consegui montar: ${esc(r.erro)}</p>`;
  if (r.id !== rel.id) return '';
  const v = r.vocab || {}, res = r.resumo || {};
  const kpis = l => `<div class="metrics rl-kpis">${l.map(([ic, cor, rot, val, sub]) => apKpi(ic, cor, rot, val, sub)).join('')}</div>`;
  const tabela = (cab, linhas, vazio) => linhas.length ? `<div class="ap-tabela"><table><thead><tr>${cab.map(c => `<th>${c}</th>`).join('')}</tr></thead><tbody>${linhas.join('')}</tbody></table></div>` : `<p class="ap-vazio ap-pad">${vazio}</p>`;
  const bloco = (titulo, sub, corpo) => `<section class="panel rl-bloco"><div class="rl-bloco-cab"><h3>${titulo}</h3>${sub ? `<p>${sub}</p>` : ''}</div>${corpo}</section>`;
  const barra = pct => `<span class="rl-barra"><i style="width:${pct || 0}%" class="${pct !== null && pct < 80 ? 'baixa' : ''}"></i></span><span class="monospace rl-pct">${pct === null || pct === undefined ? '—' : pct + '%'}</span>`;

  if (r.motor === 'presenca') {
    const evento = r.modo === 'evento';
    const k = evento
      ? [['users', 'blue', `${v.pessoas} credenciados`, apNum(res.pessoas), r.quem], ['check-circle-2', 'green', 'Vieram', apNum(res.vieram), `${apPct(res.vieram, res.pessoas)}%`],
         ['user-x', res.nao_vieram ? 'amber' : 'green', 'Não vieram', apNum(res.nao_vieram), 'lista abaixo'], ['calendar', 'blue', 'Dias do evento', apNum(res.dias), '']]
      : [['check-circle-2', 'green', 'Presença média', res.pct === null ? '—' : res.pct + '%', `${r.quem} · por dia contado`], ['calendar-x', 'blue', 'Faltas no período', apNum(res.faltas), 'pessoa-dia sem passagem'],
         ['alert-triangle', res.criticos ? 'amber' : 'green', `Com ${r.faltas_alerta}+ faltas`, apNum(res.criticos), 'lista abaixo'], ['calendar', 'blue', 'Dias contados', apNum(res.dias), r.de === r.ate && r.ate === apIsoHoje() ? 'hoje, até agora: quem chega mais tarde ainda conta como falta' : `${apBr(r.de)} a ${apBr(r.ate)}`]];
    const grupos = tabela([v.grupo, v.pessoas, 'Presença', evento ? 'Vieram' : 'Faltas', evento ? 'Não vieram' : `${r.faltas_alerta}+ faltas`],
      r.grupos.map(g => `<tr><td><button type="button" class="rl-link" data-rl-grupo="${esc(g.grupo)}">${esc(g.grupo)}</button></td><td class="monospace">${apNum(g.pessoas)}</td><td class="rl-pres">${barra(g.pct)}</td>
        <td class="monospace">${apNum(evento ? g.vieram : g.faltas)}</td><td class="monospace ${(evento ? g.pessoas - g.vieram : g.criticos) ? 'ap-ruim' : ''}">${apNum(evento ? g.pessoas - g.vieram : g.criticos)}</td></tr>`), 'Ninguém neste filtro.');
    const lista = evento ? r.pessoas.filter(x => !x.presencas) : r.pessoas;
    const pessoas = tabela(evento ? ['Nome', v.grupo] : ['Nome', v.grupo, 'Presenças', 'Faltas', 'Dias de falta'],
      lista.slice(0, _apRelMostrar).map(x => evento ? `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td></tr>`
        : `<tr class="${x.faltas >= r.faltas_alerta ? 'rl-alerta' : ''}"><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td><td class="monospace">${apNum(x.presencas)}</td><td class="monospace">${apNum(x.faltas)}</td>
          <td class="monospace rl-dias">${x.dias_falta.map(apDiaMes).join(', ') || '—'}</td></tr>`), evento ? 'Todos vieram.' : 'Ninguém neste filtro.');
    return kpis(k)
      + (r.fora_leitor.length ? `<div class="ap-alerta"><i data-lucide="user-x"></i><div><b>${apNum(r.fora_leitor.length)} fora da conta: não estão em nenhum leitor.</b> ${esc(r.fora_leitor.slice(0, 6).map(x => x.nome).join(', '))}${r.fora_leitor.length > 6 ? '…' : ''}. Sem cadastro aceito pelo leitor não dá para passar; falta seria injusta. Corrija em Alertas.</div></div>` : '')
      + bloco(`Por ${esc((v.grupo || '').toLowerCase())}`, 'Clique para ver só esse grupo.', grupos)
      + (r.serie.length ? bloco('Presença dia a dia', 'Só os dias contados.', apSerieDias(r.serie, 'pct', '% presentes')) : '')
      + bloco(evento ? `${esc(apMaiuscula(v.pessoas))} que não vieram` : `${esc(apMaiuscula(v.pessoas))}, mais faltas primeiro`, evento ? '' : `Em destaque quem tem ${r.faltas_alerta} ou mais.`, pessoas
        + (lista.length > _apRelMostrar ? '<button type="button" class="ps-mais" data-rl-mais>Mostrar mais</button>' : ''))
      + (r.dias_fora.length ? `<details class="ag-fora rl-fora"><summary>${r.dias_fora.length} dia${r.dias_fora.length === 1 ? '' : 's'} fora da conta</summary>
          ${tabela(['Dia', 'Motivo'], r.dias_fora.map(d => `<tr><td class="monospace">${apBr(d.dia)}</td><td>${esc(d.motivo)}</td></tr>`), '')}</details>` : '')
      + `<p class="ap-dica">Presença: passou em qualquer leitor do local no dia. ${evento ? '' : 'Contam segunda a sexta, menos feriados do local. '}Dia com menos de 1/4 das pessoas não conta (leitor fora do ar). Hoje só entra quando o período é só hoje.</p>`;
  }
  if (r.motor === 'cadastro') {
    return kpis([['users', 'blue', v.pessoas, apNum(res.pessoas), `${apNum(res.grupos)} ${v.grupos}`], ['image-off', res.sem_foto ? 'amber' : 'green', 'Sem foto', apNum(res.sem_foto), 'não abrem pelo rosto'],
        ['scan-line', res.fora_leitor ? 'amber' : 'green', 'Fora do leitor', apNum(res.fora_leitor), 'nenhum leitor aceitou'], ['moon', 'blue', 'Sem passar há 30 dias', apNum(res.parados), 'mudou ou viajou?']])
      + bloco(`Por ${esc((v.grupo || '').toLowerCase())}`, '', tabela([v.grupo, v.pessoas, 'Sem foto', 'Fora do leitor', 'Sem passar há 30 dias'],
        r.grupos.map(g => `<tr><td>${esc(g.grupo)}</td><td class="monospace">${apNum(g.pessoas)}</td><td class="monospace ${g.sem_foto ? 'ap-ruim' : ''}">${apNum(g.sem_foto)}</td><td class="monospace ${g.fora_leitor ? 'ap-ruim' : ''}">${apNum(g.fora_leitor)}</td><td class="monospace">${apNum(g.parados)}</td></tr>`), ''))
      + bloco(esc(apMaiuscula(v.pessoas)), '', tabela(['Nome', v.grupo, 'Foto', 'No leitor', 'Última passagem'],
        r.pessoas.slice(0, _apRelMostrar).map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td><td>${x.foto ? 'sim' : '<span class="ap-ruim">não</span>'}</td><td>${x.leitor ? 'sim' : '<span class="ap-ruim">não</span>'}</td>
          <td class="monospace">${x.ultima ? apBr(x.ultima) + ' ' + apHoraTxt(x.ultima) : 'nunca'}</td></tr>`), '')
        + (r.pessoas.length > _apRelMostrar ? '<button type="button" class="ps-mais" data-rl-mais>Mostrar mais</button>' : ''));
  }
  if (r.motor === 'diario') {
    const saidas = r.saidas_confiaveis;
    const linhas = r.pessoas.slice(0, _apRelMostrar).map(x => saidas
      ? `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo || '—')}</td><td class="monospace">${apHoraTxt(x.chegou)}</td><td class="monospace">${x.saiu ? apHoraTxt(x.saiu) : (x.dentro ? '<span class="ap-chip entrada">dentro</span>' : '—')}</td><td class="monospace">${apMin(x.minutos)}</td><td>${esc(x.portas.map(apPorta).join(', '))}</td></tr>`
      : `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo || '—')}</td><td class="monospace">${apHoraTxt(x.primeira)}</td><td class="monospace">${apHoraTxt(x.ultima)}</td><td class="monospace">${apNum(x.passagens)}</td><td>${esc(x.portas.map(apPorta).join(', '))}</td></tr>`);
    return kpis([['users', 'blue', 'Pessoas do cadastro', apNum(res.pessoas), apBr(r.dia)], ['footprints', 'blue', 'Passagens', apNum(res.passagens), 'todas as marcações'],
        saidas ? ['log-in', 'green', 'Ainda dentro', apNum(res.dentro), 'última passagem foi entrada'] : ['log-out', 'blue', 'Saídas', '—', 'local quase sem leitor de saída'],
        res.nao_vieram ? ['user-x', 'amber', `${v.pessoas} sem passagem`, apNum(res.nao_vieram), 'lista abaixo'] : ['user-search', res.so_leitor ? 'amber' : 'green', 'Só no leitor', apNum(res.so_leitor), 'sem cadastro no SightOps']])
      + bloco('Quem passou', saidas ? 'Chegou: primeira entrada. Saiu: última saída.' : 'Este local quase não registra saída: primeira e última passagem do dia.',
        tabela(saidas ? ['Nome', v.grupo, 'Chegou', 'Saiu', 'Tempo', 'Portas'] : ['Nome', v.grupo, 'Primeira', 'Última', 'Passagens', 'Portas'], linhas, 'Ninguém do cadastro passou neste dia.')
        + (r.pessoas.length > _apRelMostrar ? '<button type="button" class="ps-mais" data-rl-mais>Mostrar mais</button>' : ''))
      + (r.nao_vieram.length ? `<details class="ag-fora rl-fora"><summary>${apNum(r.nao_vieram.length)} ${esc(v.pessoas)} sem passagem no dia</summary>
          ${tabela(['Nome', v.grupo], r.nao_vieram.map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td></tr>`), '')}</details>` : '')
      + (r.so_leitor.length ? `<details class="ag-fora rl-fora"><summary>${apNum(r.so_leitor.length)} só no leitor (sem cadastro no SightOps)</summary>
          ${tabela(['Nome no leitor', 'Passagens', 'Primeira', 'Última'], r.so_leitor.map(x => `<tr><td>${esc(x.nome)}</td><td class="monospace">${apNum(x.passagens)}</td><td class="monospace">${apHoraTxt(x.primeira)}</td><td class="monospace">${apHoraTxt(x.ultima)}</td></tr>`), '')}</details>` : '');
  }
  if (r.motor === 'uso') {
    const hm = res.hora_mais;
    const maxP = Math.max(1, ...r.portas.map(p => p.passagens));
    return kpis([['footprints', 'blue', 'Passagens', apNum(res.passagens), `${apBr(r.de)} a ${apBr(r.ate)}`], ['bar-chart-3', 'blue', 'Média por dia', apNum(res.media_dia), `${apNum(res.dias_com_movimento)} dias com movimento`],
        ['users', 'green', 'Pico de gente dentro', res.pico === null ? '—' : apNum(res.pico), res.pico === null ? 'local quase sem leitor de saída' : `${apBr(res.pico_dia)} às ${res.pico_hora}`],
        ['clock', 'blue', 'Horário mais cheio', hm ? `${AP_DIAS[hm.dia_semana]} ${String(hm.hora).padStart(2, '0')}h` : '—', 'no período']])
      + `<div class="ap-rel">${bloco('Por dia da semana e hora', 'Passagens somadas no período', apMapaCalor(r.mapa))}
        ${bloco('Dia a dia', 'Passe o mouse para ver pessoas', apSerieDias(r.serie) + '<h3 class="ap-h3b">Portas</h3>'
          + (r.portas.map(p => `<div class="ap-top"><span title="${esc(p.porta)}">${esc(apPorta(p.porta))}</span><span class="ap-trilho"><i style="width:${apPct(p.passagens, maxP)}%"></i></span><span class="monospace">${apNum(p.passagens)}</span></div>`).join('') || '<p class="ap-vazio">Sem passagens no período.</p>'))}</div>`;
  }
  // avisos
  const ok = res.lidos + res.entregues;
  const maxDia = Math.max(1, ...r.serie.map(x => x.lido + x.entregue + x.enviado + x.falha));
  const h = n => Math.round(n * 100 / maxDia) + '%';
  return kpis([['message-circle', 'blue', 'Avisos enviados', apNum(res.enviados), `${apNum(res.pessoas_avisadas)} ${v.pessoas}`], ['check-check', apPct(ok, res.enviados) >= 95 ? 'green' : 'amber', 'Entregues ou lidos', res.enviados ? apPct(ok, res.enviados) + '%' : '—', `${apPct(res.lidos, res.enviados)}% lidos`],
      ['phone-off', res.falhas ? 'red' : 'green', 'Não entregues', apNum(res.falhas), `${apNum(res.falhando)} números falhando agora`], ['contact', res.sem_numero ? 'amber' : 'green', 'Sem número', apNum(res.sem_numero), 'não recebem aviso']])
    + bloco('Dia a dia', '<span class="ap-legenda"><span><i class="lido"></i>lido</span><span><i class="entregue"></i>entregue</span><span><i class="enviado"></i>sem confirmação</span><span><i class="falha"></i>não entregue</span></span>',
      `<div class="ap-grafico">${r.serie.map(x => `<div title="${apDiaMes(x.dia)}: ${x.lido} lidos, ${x.entregue} entregues, ${x.falha} não entregues">
        <i class="falha" style="height:${h(x.falha)}"></i><i class="enviado" style="height:${h(x.enviado)}"></i><i class="entregue" style="height:${h(x.entregue)}"></i><i class="lido" style="height:${h(x.lido)}"></i></div>`).join('')}</div>
       <div class="ap-eixo monospace"><span>${apDiaMes(r.de)}</span><span>${apDiaMes(r.ate)}</span></div>`)
    + bloco(`Por ${esc(v.pessoa || 'pessoa')}`, 'Quem está com o último aviso falhando vem primeiro.', tabela(['Nome', v.grupo, 'Responsável', 'Enviados', 'Lidos', 'Falhas', 'Último'],
      r.pessoas.slice(0, _apRelMostrar).map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td><td>${esc(x.responsavel || '—')}</td><td class="monospace">${apNum(x.enviados)}</td><td class="monospace">${apNum(x.lidos)}</td><td class="monospace">${apNum(x.falhas)}</td>
        <td>${x.ultimo_ok === false ? `<span class="ap-ruim" title="${esc(x.erro)}">falhou</span>` : 'ok'}</td></tr>`), 'Ninguém recebeu aviso no período.')
      + (r.pessoas.length > _apRelMostrar ? '<button type="button" class="ps-mais" data-rl-mais>Mostrar mais</button>' : ''))
    + (r.sem_numero.length ? `<details class="ag-fora rl-fora"><summary>${apNum(r.sem_numero.length)} sem número de responsável</summary>
        ${tabela(['Nome', v.grupo], r.sem_numero.map(x => `<tr><td>${esc(x.nome)}</td><td>${esc(x.grupo)}</td></tr>`), '')}</details>` : '');
}

function apDesenharRel() {
  const el = document.getElementById('apRelTopo');
  if (!el) return;
  const geral = document.getElementById('apGeral');
  if (geral) geral.innerHTML = '';
  const c = _apDados.relCat;
  if (!c) { el.innerHTML = '<p class="ap-vazio">Carregando…</p>'; return; }
  if (c.precisa_local) {
    el.innerHTML = `<div class="dv-vazio"><i data-lucide="map-pin"></i><b>Escolha um local no topo</b><p>Cada relatório é de um local: o tipo dele (escola, condomínio, empresa ou evento) decide quais relatórios existem.</p></div>`;
    lucide.createIcons();
    return;
  }
  const rel = apRelAtual();
  const r = _apDados.rel;
  const pronto = r && !r.carregando && !r.erro && r.id === (rel || {}).id;
  el.innerHTML = `<div class="rl">
    <aside class="rl-cat" aria-label="Escolher relatório">
      <div class="rl-cat-cab"><b>Qual relatório você precisa?</b><small>${esc((c.vocab || {}).local || '')} · cada um sai em PDF</small></div>
      ${(c.relatorios || []).map(x => `<button type="button" class="rl-item ${x.id === _apRelSel ? 'on' : ''}" data-rl-sel="${esc(x.id)}" aria-pressed="${x.id === _apRelSel}">
        <b>${esc(x.nome)}</b><span>${esc(x.pergunta)}</span></button>`).join('')}
      <p class="rl-nota"><i data-lucide="info"></i><span>Leitores, fotos e cadastros com problema ficam em <a href="#" data-ap-ir="alertas">Alertas</a>.</span></p>
    </aside>
    <div class="rl-main">
      ${rel ? `<section class="panel rl-topo">
        <div class="rl-topo-cab"><div><h2>${esc(rel.nome)}</h2><p>${esc(rel.pergunta)}</p></div>
          <div class="rl-baixar">${pronto ? `<button type="button" class="secondary-action rl-pdf" data-rl-csv><i data-lucide="sheet"></i> Planilha</button>
            <a class="primary-action rl-pdf" href="${API_BASE}/api/access-control/painel/relatorios/r/${encodeURIComponent(rel.id)}/pdf?${apRelQuery(rel)}" download><i data-lucide="download"></i> Baixar PDF</a>`
            : '<span class="secondary-action rl-pdf" aria-disabled="true"><i data-lucide="sheet"></i> Planilha</span><span class="primary-action rl-pdf" aria-disabled="true"><i data-lucide="download"></i> Baixar PDF</span>'}</div></div>
        <div class="rl-filtros">${apRelFiltros(rel)}</div>
      </section>
      ${apRelCorpo(r, rel)}` : ''}
    </div></div>`;
  apLigarAcoes(el);
  el.querySelectorAll('[data-rl-sel]').forEach(b => b.addEventListener('click', () => { _apRelSel = b.dataset.rlSel; _apRelMostrar = 150; apRelRecarregar(); }));
  el.querySelectorAll('[data-rl-periodo]').forEach(b => b.addEventListener('click', () => { _apRelF.periodo = b.dataset.rlPeriodo; if (b.dataset.rlPeriodo === 'escolher') { const p = apRelPeriodo(); _apRelF.de = p.de; _apRelF.ate = p.ate; } apRelRecarregar(); }));
  el.querySelector('#rlDia')?.addEventListener('change', ev => { _apRelF.dia = ev.target.value; apRelRecarregar(); });
  el.querySelector('#rlDe')?.addEventListener('change', ev => { _apRelF.de = ev.target.value; apRelRecarregar(); });
  el.querySelector('#rlAte')?.addEventListener('change', ev => { _apRelF.ate = ev.target.value; apRelRecarregar(); });
  el.querySelector('#rlGrupo')?.addEventListener('change', ev => { _apRelF.grupo = ev.target.value; apRelRecarregar(); });
  el.querySelector('#rlQuem')?.addEventListener('change', ev => { _apRelF.quem = ev.target.value; _apRelF.grupo = ''; apRelRecarregar(); });
  el.querySelectorAll('[data-rl-grupo]').forEach(b => b.addEventListener('click', () => { _apRelF.grupo = b.dataset.rlGrupo; apRelRecarregar(); }));
  el.querySelector('[data-rl-mais]')?.addEventListener('click', () => { _apRelMostrar += 150; apDesenharRel(); });
  el.querySelector('[data-rl-csv]')?.addEventListener('click', () => apRelCsv(_apDados.rel));
  lucide.createIcons();
}

// Planilha (CSV com ";" e BOM: abre certo no Excel em portugues). A tela antiga
// exportava a movimentacao; aqui sai a tabela principal de cada relatorio.
function apRelCsv(r) {
  if (!r || !r.motor) return;
  const v = r.vocab || {};
  const hm = t => (t || '').slice(11, 16);
  const tabelas = {
    presenca: () => [['Nome', v.grupo, 'Presenças', 'Faltas', 'Presença %', 'Dias de falta'],
      (r.pessoas || []).map(x => [x.nome, x.grupo, x.presencas, x.faltas, x.pct ?? '', x.dias_falta.map(apBr).join(', ')])],
    cadastro: () => [['Nome', v.grupo, 'Foto', 'No leitor', 'Última passagem'],
      (r.pessoas || []).map(x => [x.nome, x.grupo, x.foto ? 'sim' : 'não', x.leitor ? 'sim' : 'não', x.ultima ? `${apBr(x.ultima)} ${hm(x.ultima)}` : 'nunca'])],
    diario: () => [['Nome', v.grupo, 'Chegou', 'Saiu', 'Minutos', 'Primeira', 'Última', 'Passagens', 'Portas'],
      (r.pessoas || []).map(x => [x.nome, x.grupo, hm(x.chegou), hm(x.saiu), x.minutos ?? '', hm(x.primeira), hm(x.ultima), x.passagens, x.portas.join(', ')])],
    uso: () => [['Dia', 'Passagens', 'Pessoas', 'Pico dentro', 'Hora do pico'],
      (r.serie || []).map(x => [apBr(x.dia), x.passagens, x.pessoas, x.pico ?? '', x.pico_hora || ''])],
    avisos: () => [['Nome', v.grupo, 'Responsável', 'Número', 'Enviados', 'Lidos', 'Entregues', 'Falhas', 'Último'],
      (r.pessoas || []).map(x => [x.nome, x.grupo, x.responsavel, x.numero, x.enviados, x.lidos, x.entregues, x.falhas, x.ultimo_ok === false ? 'falhou' : 'ok'])],
  };
  // So a tabela do relatorio aberto: montar todas lia campo que nao existe ("portas" na Frequencia).
  const [cab, linhas] = tabelas[r.motor] ? tabelas[r.motor]() : [[], []];
  if (!linhas.length) { acToast('Nada para exportar neste filtro.', true); return; }
  const cel = val => { const t = String(val ?? ''); return /[;"\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
  const csv = [cab, ...linhas].map(l => l.map(cel).join(';')).join('\r\n');
  const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  const nome = `${r.nome} ${r.site} ${r.dia || r.ate || ''}`.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').toLowerCase();
  a.href = url; a.download = `${nome || 'relatorio'}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function apRelRecarregar() {
  try { await apRelCarregar(); } catch (err) { _apDados.rel = { erro: (err && err.message) || 'falhou' }; }
  apDesenharRel();
}

// ---------------------------------------------------------------- ciclo
function apQ(extra) {
  const p = new URLSearchParams(extra || {});
  if (_apSite) p.set('site', _apSite);
  if (_apPortas.length) p.set('portas', _apPortas.join(','));
  const s = p.toString();
  return s ? '?' + s : '';
}

// A visao geral (avisos 30 dias, fotos, leitores) muda devagar: no maximo a cada 2 min.
async function apGeral(forcar) {
  if (forcar || !_apDados.geral || Date.now() - _apDados.geralEm > 120000) {
    _apDados.geral = await acJson(`/api/access-control/painel/visao-geral${apQ()}`) || {};
    _apDados.geralEm = Date.now();
  }
  return _apDados.geral;
}

function apDesenharAtual() {
  if (AP_ABAS_PROPRIAS[_apTela]) { apMarcarAba(); return; }   // Dispositivos/Pessoas se desenham sozinhas
  apMostrarPerfil(_apTela === 'relatorios' ? (_apDados.relCat || {}).perfil : ((_apDados.vivo || {}).perfil || (_apDados.geral || {}).perfil));
  if (_apTela === 'vivo') apDesenharVivo(_apDados.vivo || {});
  else if (_apTela === 'alertas') apDesenharAlertas();
  else apDesenharRel();
  apMarcarAba();
}

async function apAtualizar(manual) {
  if (AP_ABAS_PROPRIAS[_apTela]) {
    // Gaveta aberta: nao redesenha por baixo de quem esta editando.
    if (document.querySelector('.dv-gaveta:not([hidden])')) return;
    // Messenger tem relogio proprio (6 s); Conexoes consulta a Meta: so no clique ou troca de local.
    if (!manual) { if (!['messenger', 'conexoes'].includes(_apTela)) AP_ABAS_PROPRIAS[_apTela].carregar().catch(() => {}); return; }
    // Clique: o botao gira ate terminar. Antes recarregava calado e parecia
    // que nao fazia nada (o resultado de um teste antigo continuava na linha).
    if (_apTela === 'dispositivos' && typeof _dvTestes !== 'undefined') {
      Object.keys(_dvTestes).forEach(k => { if (!_dvTestes[k].rodando) delete _dvTestes[k]; });
    }
    const b = document.getElementById('btnApAtualizar');
    if (b) { b.disabled = true; b.classList.add('girando'); }
    try {
      await AP_ABAS_PROPRIAS[_apTela].carregar();
      acToast('Atualizado.');
    } catch (err) {
      acToast((err && err.message) || 'Não foi possível atualizar.', true);
    } finally {
      if (b) { b.disabled = false; b.classList.remove('girando'); }
    }
    return;
  }
  if (_apCarregando) return;
  _apCarregando = true;
  try {
    if (_apTela === 'relatorios') {
      // Relatorio nao se refaz sozinho a cada passagem: so ao abrir, no
      // Atualizar e ao trocar filtro (e analise, nao operacao).
      if (!manual && _apDados.relCat && _apDados.rel && !_apDados.rel.erro) { apDesenharAtual(); return; }
      await apRelCarregar();
      apGeral().then(apMarcarAba).catch(() => {});
    } else {
      const vivo = await acJson(`/api/access-control/painel/ao-vivo${apQ({ limit: 400 })}`) || {};
      if (_apTela === 'alertas') await apGeral(manual);
      else apGeral().then(apMarcarAba).catch(() => {});
      // Pausado: guarda o dado novo, mas nao mexe na lista que o operador esta lendo.
      if (_apTela === 'vivo' && _apPausado && _apDados.vivo && !manual) {
        const ids = (vivo.passagens || []).map(p => p.id);
        const pos = ids.indexOf(_apTopoVisto);
        const novas = pos < 0 ? ids.length : pos;
        const n = document.getElementById('apNovas');
        if (n) n.textContent = novas ? ` · ${novas} nova${novas === 1 ? '' : 's'}` : '';
        return;
      }
      _apDados.vivo = vivo;
    }
    apDesenharAtual();
  } catch (err) {
    const alvo = document.getElementById({ vivo: 'apVivo', alertas: 'apAlertas', relatorios: 'apRelTopo' }[_apTela]);
    if (alvo && !alvo.innerHTML.trim()) alvo.innerHTML = `<p class="ap-vazio">Não consegui carregar: ${esc(err?.message || err)}</p>`;
  } finally {
    _apCarregando = false;
  }
}

function apLigarStream() {
  if (_apFonte) { _apFonte.close(); _apFonte = null; }
  if (!['vivo', 'alertas'].includes(_apTela) || typeof EventSource === 'undefined') return;
  _apFonte = new EventSource(`${API_BASE}/api/access-control/live/stream${apQ()}`);
  _apFonte.addEventListener('access-event', () => apAtualizar());
}

function apTrocarTela(tela) {
  if (tela === 'geral') tela = 'relatorios';   // aba antiga "Visao geral"
  if (tela === 'portas') tela = 'dispositivos';  // aba Portas foi para Dispositivos
  _apTela = AP_TELAS.includes(tela) ? tela : 'vivo';
  if (_apTela !== 'vivo') _apPausado = false;
  document.querySelectorAll('[data-ap-tela]').forEach(b => {
    const on = b.dataset.apTela === _apTela;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  document.getElementById('apVivo').hidden = _apTela !== 'vivo';
  document.getElementById('apAlertas').hidden = _apTela !== 'alertas';
  document.getElementById('apRel').hidden = _apTela !== 'relatorios';
  Object.entries(AP_ABAS_PROPRIAS).forEach(([k, a]) => { document.getElementById(a.el).hidden = _apTela !== k; });
  // Menu lateral: o grupo Controle de Acesso fica aberto e o submenu da aba aceso.
  document.getElementById('ngAcesso')?.classList.add('open');
  try { sessionStorage.setItem('sightops.acesso.painel.tela', _apTela); } catch (_) {}
  apLigarStream();
  if (AP_ABAS_PROPRIAS[_apTela]) { AP_ABAS_PROPRIAS[_apTela].abrir(); return; }
  // Troca de aba desenha na hora com o que ja tem; o fetch atualiza depois.
  if ((_apTela === 'relatorios' && _apDados.relCat) || (_apTela !== 'relatorios' && _apDados.vivo)) apDesenharAtual();
  apAtualizar();
}

// Chamado ao sair da tela (navigateTo): fecha o stream e para os timers.
function stopAccessPainel() {
  if (_apFonte) { _apFonte.close(); _apFonte = null; }
  clearInterval(_apTimer); _apTimer = null;
  clearInterval(_apRelogio); _apRelogio = null;
}

async function loadAccessPainel() {
  const sel = document.getElementById('apSite');
  if (sel && !sel.dataset.ligado) {
    sel.dataset.ligado = '1';
    sel.addEventListener('change', () => {
      _apSite = sel.value;
      _apPortas = [];
      apPortasRotulo();
      _apDados.vivo = _apDados.rel = _apDados.relCat = _apDados.geral = null;
      _apSel = ''; _apPessoa = '';
      apLigarStream(); apAtualizar(true);
    });
    document.getElementById('btnApAtualizar')?.addEventListener('click', () => apAtualizar(true));
    document.getElementById('apPortas')?.addEventListener('click', ev => apMenuPortas(ev.currentTarget));
    document.getElementById('apPerfil')?.addEventListener('click', ev => apMenuTipo(ev.currentTarget, ev.currentTarget.dataset.site));
  }
  try {
    const g = await acJson('/api/access-control/painel/visao-geral');
    const sites = [...new Set(((g?.leitores || {}).lista || []).map(l => l.site).filter(Boolean))].sort();
    if (sel) {
      sel.innerHTML = '<option value="">Todos os sites</option>' + sites.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join('');
      if (sites.includes(_apSite)) sel.value = _apSite;
      else if (sites.length === 1) { _apSite = sites[0]; sel.value = _apSite; }
      else _apSite = '';
    }
    if (!_apSite) { _apDados.geral = g || {}; _apDados.geralEm = Date.now(); }
    apMostrarPerfil(g && g.perfil);
  } catch (_) { /* a propria tela mostra o erro ao carregar */ }
  let salva = 'vivo';
  try { salva = sessionStorage.getItem('sightops.acesso.painel.tela') || 'vivo'; } catch (_) {}
  // Dentro do /v3 a aba vem do submenu clicado (sessionStorage); o "#" do
  // endereco era da pagina propria e aqui deixava a aba velha vencer o clique.
  stopAccessPainel();
  apTrocarTela(salva);
  _apTimer = setInterval(() => { if (!document.hidden) apAtualizar(); }, 20000);
  _apRelogio = setInterval(() => {
    const r = document.getElementById('apRelogio');
    if (r) r.textContent = new Date().toLocaleTimeString('pt-BR');
  }, 1000);
}

window.acPagina = { id: 'painel', iniciar: loadAccessPainel };

// ---------------------------------------------------------------- filtro de portas
// Ver so algumas portas do local (ex.: entrada + saida da portaria). Vale para
// Ao vivo, Alertas e Relatorios; "quem esta aqui" continua sendo o local todo.
function apPortasDoLocal() {
  const lista = ((_apDados.geral || {}).leitores || {}).lista || [];
  return lista.filter(l => !_apSite || String(l.site).toUpperCase() === _apSite.toUpperCase())
    .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR'));
}

function apPortasRotulo() {
  const b = document.getElementById('apPortas');
  if (!b) return;
  const nomes = apPortasDoLocal().filter(l => _apPortas.includes(l.id)).map(l => apPorta(l.nome));
  const txt = !_apPortas.length ? 'Todas as portas' : nomes.length === 1 ? nomes[0] : `${_apPortas.length} portas`;
  b.querySelector('span').textContent = txt;
  b.classList.toggle('on', _apPortas.length > 0);
  b.title = nomes.join(' + ') || 'Todas as portas';
}

function apMenuPortas(ancora) {
  document.getElementById('apMenuPortas')?.remove();
  const portas = apPortasDoLocal();
  if (!portas.length) { acToast('Nenhuma porta neste local.'); return; }
  const menu = document.createElement('div');
  menu.id = 'apMenuPortas';
  menu.className = 'ap-menu-tipo ap-menu-portas';
  menu.innerHTML = `<div class="ap-menu-cab"><b>Portas</b><small>Marque as que quer ver</small></div>
    <label class="ap-mp-item"><input type="checkbox" data-mp-todas ${_apPortas.length ? '' : 'checked'}><span>Todas as portas</span></label>
    ${portas.map(l => `<label class="ap-mp-item"><input type="checkbox" value="${esc(l.id)}" ${_apPortas.includes(l.id) ? 'checked' : ''}><span>${esc(_apSite ? apPorta(l.nome) : l.nome)}</span></label>`).join('')}
    <div class="ap-mp-pe"><button type="button" class="primary-action" data-mp-ok>Ver</button></div>`;
  document.body.appendChild(menu);
  const r = ancora.getBoundingClientRect();
  menu.style.top = (window.scrollY + r.bottom + 6) + 'px';
  menu.style.left = Math.max(12, Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - menu.offsetWidth - 12)) + 'px';
  const todas = menu.querySelector('[data-mp-todas]');
  const caixas = [...menu.querySelectorAll('input[value]')];
  todas.addEventListener('change', () => { if (todas.checked) caixas.forEach(c => { c.checked = false; }); });
  caixas.forEach(c => c.addEventListener('change', () => { todas.checked = !caixas.some(x => x.checked); }));
  const fechar = ev => { if (!menu.contains(ev.target) && ev.target !== ancora && !ancora.contains(ev.target)) { menu.remove(); document.removeEventListener('mousedown', fechar); } };
  setTimeout(() => document.addEventListener('mousedown', fechar), 0);
  menu.addEventListener('keydown', ev => { if (ev.key === 'Escape') { menu.remove(); ancora.focus(); } });
  menu.querySelector('[data-mp-ok]').addEventListener('click', () => {
    const marcadas = caixas.filter(c => c.checked).map(c => c.value);
    _apPortas = marcadas.length === portas.length ? [] : marcadas;
    menu.remove();
    apPortasRotulo();
    _apDados.vivo = _apDados.rel = _apDados.relCat = null;
    _apSel = '';
    apAtualizar(true);
  });
  caixas[0]?.focus();
}
