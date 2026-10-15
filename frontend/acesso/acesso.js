// Painel de Acesso (/v3/acesso/). O menu, o login e as chamadas a API ficam
// em shell.js, compartilhado com as outras paginas novas.
// ---- Painel (so leitura). Dados: /api/access-control/painel/*
// (GET, so leitura). Quatro abas, cada uma com um trabalho (estudo de UX dos
// sistemas de mercado): Ao vivo (lista + passagem selecionada com o recibo do
// aviso), Portas (um cartao por leitor), Alertas (o que precisa de alguem) e
// Relatorios (o que e para analisar, fora do ao vivo).
let _apTela = 'vivo';
let _apSite = '';
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
const AP_TELAS = ['vivo', 'dispositivos', 'pessoas', 'portas', 'alertas', 'relatorios'];
// Abas com arquivo proprio: o Painel so mostra/esconde e pede para carregar.
const AP_ABAS_PROPRIAS = {
  dispositivos: { el: 'apDisp', abrir: () => dvAbrirAba(), carregar: () => dvCarregar() },
  pessoas: { el: 'apPess', abrir: () => psAbrirAba(), carregar: () => psCarregar() },
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
    tipos: { student: 'Morador', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador' },
    sub: 'Quem está entrando e saindo, como portarias e áreas comuns estão sendo usadas e o que precisa de alguém.',
  },
  misto: {
    nome: 'Escola e condomínio', grupo: 'Turma ou unidade', dentro: 'dentro agora', hoje: 'Quem passou hoje',
    tipos: { student: 'Aluno', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador' },
    sub: 'Escolas e condomínios juntos. Escolha um local para ver o vocabulário e os blocos de cada um.',
  },
};
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
    chip.title = (perfil.locais || []).map(l => `${l.site}: ${AP_VOCAB[l.tipo].nome.toLowerCase()}` +
      (l.tipo === 'escola' ? ` (${l.com_turma} de ${l.alunos} alunos com turma)` : '')).join('\n') +
      '\nDetectado pelo cadastro de pessoas.';
  }
  const sub = document.getElementById('apSubtitulo');
  if (sub) sub.textContent = v.sub;
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
    sub: semSinal ? `${semSinal} sem sinal` : 'todos respondendo', subCor: semSinal ? 'ruim' : '', tela: 'portas' }));
  const dentro = r.inside_now ?? 0;
  cards.push(card({ icone: 'users', cor: 'cyan', rot: apEhCondominio() ? 'Dentro agora' : 'Presentes agora', val: apNum(dentro),
    sub: !apEhCondominio() && alunos ? `de ${apNum(alunos)} alunos ativos` : 'última passagem foi entrada', tela: 'relatorios' }));
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
      <button type="button" class="secondary-action" data-ap-ir="portas"><i data-lucide="door-open"></i> Ver a porta</button>
    </div>
  </section>`;
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
    <div><b>${apSaida(x.tipo) ? 'Saiu' : 'Entrou'} · ${esc(apPorta(x.porta))}</b></div><span class="monospace">${apHm(apLocal(x.hora))}</span></div>`).join('')}</div>`;
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

// ---------------------------------------------------------------- portas
function apCurva(horas) {
  horas = horas || [];
  const w = 240, h = 36, max = Math.max(1, ...horas);
  const agoraH = new Date().getHours();
  const pts = horas.slice(0, agoraH + 1).map((n, i) => [i * w / 23, h - 3 - n / max * (h - 6)]);
  if (!pts.length) return '';
  const d = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const fim = pts[pts.length - 1];
  return `<svg class="ap-curva" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <path d="${d} L${fim[0].toFixed(1)} ${h} L0 ${h} Z" fill="var(--primary-soft)"/>
    <path d="${d}" fill="none" stroke="var(--primary)" stroke-width="1.6" vector-effect="non-scaling-stroke"/>
  </svg><div class="ap-curva-eixo monospace"><span>0h</span><span>12h</span><span>23h</span></div>`;
}

function apDesenharPortas(d) {
  const el = document.getElementById('apPortas');
  if (!el) return;
  const portas = (d.portas || []).slice().sort((a, b) => (apPortaViva(a) - apPortaViva(b)) || (b.relogio_errado ? 1 : 0) - (a.relogio_errado ? 1 : 0) || b.hoje - a.hoje);
  const vivas = portas.filter(apPortaViva).length;
  el.innerHTML = `
    <p class="ap-sub">${vivas} de ${portas.length} leitores com sinal. Sinal é o leitor informar online ou ter passagem nos últimos 30 minutos: o status que o leitor informa sozinho já mostrou offline com passagens no dia.</p>
    <div class="ap-pcs">${portas.map(p => {
      const viva = apPortaViva(p);
      const pico = (p.horas || []).reduce((m, n, i) => (n > m[1] ? [i, n] : m), [-1, 0]);
      const st = !viva ? '<span class="ap-chip falha">sem sinal</span>'
        : p.relogio_errado ? '<span class="ap-chip saida">relógio errado</span>'
        : '<span class="ap-chip entrada">com sinal</span>';
      return `<article class="panel ap-pc ${viva ? '' : 'ruim'}">
        <div class="ap-pc-cab"><div class="ap-cresce"><b title="${esc(p.nome)}">${esc(apPorta(p.nome))}</b>
          <small>${p.ultima ? 'última passagem ' + apHa(apLocal(p.ultima)) : 'nenhuma passagem hoje'}</small></div>${st}</div>
        <div class="ap-pc-nums">
          <div><b class="monospace">${apNum(p.hoje)}</b><small>passagens hoje</small></div>
          <div><b class="monospace">${p.ultima ? apHm(apLocal(p.ultima)) : '—'}</b><small>última</small></div>
          <div><b class="monospace">${pico[0] >= 0 ? String(pico[0]).padStart(2, '0') + 'h' : '—'}</b><small>hora de pico</small></div>
        </div>
        ${apCurva(p.horas)}
        <div class="ap-pc-pe">
          <span>Leitor informa <b>${esc(p.status || 'sem status')}</b>${p.visto ? ' · falou com o SightOps ' + apHa(apUtc(p.visto) || apLocal(p.visto)) : ''}</span>
          ${p.relogio_errado ? `<span class="ap-ruim">${p.relogio_errado} passagem${p.relogio_errado === 1 ? '' : 's'} gravada${p.relogio_errado === 1 ? '' : 's'} com data antes de 2020: o relógio do leitor zerou${p.relogio_errado_em ? ' (última recebida em ' + apLocal(p.relogio_errado_em)?.toLocaleDateString('pt-BR') + ')' : ''}.</span>` : ''}
        </div>
      </article>`;
    }).join('') || '<p class="ap-vazio">Nenhum leitor cadastrado.</p>'}</div>`;
  lucide.createIcons();
}

// ---------------------------------------------------------------- alertas
// O que precisa de alguem, com gravidade. Separado da lista de passagens
// (como no C•CURE / Verkada): a passagem comum nao disputa espaco com o alarme.
function apListaAlertas() {
  const v = _apDados.vivo || {}, g = _apDados.geral || {};
  const itens = [];
  const ag = v.avisos_agora || {};
  if (ag.alerta) itens.push({ nivel: 'grave', icone: 'message-circle-warning', titulo: 'Avisos de WhatsApp falhando agora',
    texto: `${ag.falhas} de ${ag.enviados} avisos não chegaram nos últimos ${ag.janela_min} min. Motivo da Meta: ${ag.erro_principal || 'não informado'}.`, ir: '' });
  (v.portas || []).filter(p => !apPortaViva(p)).forEach(p => itens.push({ nivel: 'grave', icone: 'door-closed', titulo: `Leitor sem sinal: ${apPorta(p.nome)}`,
    texto: `${p.ultima ? 'Última passagem ' + apHa(apLocal(p.ultima)) : 'Nenhuma passagem hoje'} e o leitor informa "${p.status || 'sem status'}".`, ir: 'portas' }));
  (v.portas || []).filter(p => p.relogio_errado).forEach(p => itens.push({ nivel: 'medio', icone: 'clock-alert', titulo: `Relógio errado: ${apPorta(p.nome)}`,
    texto: `${p.relogio_errado} passagens chegaram com data antes de 2020 e ficam fora dos relatórios. Acertar a hora do leitor.`, ir: 'portas' }));
  const av = g.avisos || {};
  if ((av.falhando || []).length) itens.push({ nivel: 'medio', icone: 'phone-off', titulo: `${av.falhando.length} responsáve${av.falhando.length === 1 ? 'l não está' : 'is não estão'} recebendo aviso`,
    texto: av.falhando.slice(0, 4).map(f => `${f.responsavel || f.numero}${f.pessoa ? ' (' + f.pessoa + ')' : ''}`).join(', ') + (av.falhando.length > 4 ? '…' : '') + '. O último aviso para esses números falhou.', ir: 'relatorios' });
  const fotos = g.fotos || {};
  if (fotos.falhou) itens.push({ nivel: 'medio', icone: 'scan-face', titulo: `${fotos.falhou} foto${fotos.falhou === 1 ? '' : 's'} recusada${fotos.falhou === 1 ? '' : 's'} pelos leitores`,
    texto: 'Essas pessoas não abrem a porta pelo rosto até a foto ser trocada.', ir: 'relatorios' });
  const r = v.resumo || {};
  const semCad = r.without_person || 0, total = r.total || 0;
  if (semCad) itens.push({ nivel: total >= 20 && semCad / total >= 0.2 ? 'info' : 'medio', icone: 'user-x', titulo: `${semCad} passage${semCad === 1 ? 'm' : 'ns'} hoje de quem só está no leitor`,
    texto: apEhCondominio()
      ? 'Moradores que estão no leitor mas não no cadastro do SightOps ficam fora de "dentro agora" e dos relatórios. Para trazer: Controle de Acesso › Dispositivos › importar pessoas do leitor.'
      : 'Ficam fora da presença, dos relatórios e dos avisos.', ir: 'relatorios' });
  if (av.sem_numero_total) itens.push({ nivel: 'info', icone: 'contact', titulo: `${av.sem_numero_total} aluno${av.sem_numero_total === 1 ? '' : 's'} sem número de responsável`,
    texto: 'Não recebem aviso nenhum.', ir: 'relatorios' });
  itens.push({ nivel: 'cinza', icone: 'shield-x', titulo: 'Acessos negados ainda não são coletados',
    texto: 'Hoje o SightOps só guarda as passagens liberadas. Quando a coleta guardar as negadas, elas aparecem aqui primeiro.', ir: '' });
  return itens;
}

function apContaAlertas() {
  if (!_apDados.vivo) return 0;
  return apListaAlertas().filter(i => i.nivel === 'grave' || i.nivel === 'medio').length;
}

function apMarcarAba() {
  const b = document.querySelector('[data-ap-tela="alertas"]');
  if (!b) return;
  const n = apContaAlertas();
  b.innerHTML = `Alertas${n ? ` <span class="ap-aba-n">${n}</span>` : ''}`;
}

function apDesenharAlertas() {
  const el = document.getElementById('apAlertas');
  if (!el) return;
  const ordem = { grave: 0, medio: 1, info: 2, cinza: 3 };
  const itens = apListaAlertas().sort((a, b) => ordem[a.nivel] - ordem[b.nivel]);
  const rot = { grave: 'agir agora', medio: 'resolver hoje', info: 'para saber', cinza: 'ainda não existe' };
  el.innerHTML = `<div class="ap-alertas">${itens.map(i => `
    <article class="ap-al ${i.nivel}">
      <span class="ap-al-ic"><i data-lucide="${i.icone}"></i></span>
      <div class="ap-cresce"><div class="ap-al-tit"><b>${esc(i.titulo)}</b><span class="ap-al-niv">${rot[i.nivel]}</span></div><p>${esc(i.texto)}</p></div>
      ${i.ir ? `<button type="button" class="secondary-action" data-ap-ir="${i.ir}">Ver</button>` : ''}
    </article>`).join('')}</div>`;
  apLigarAcoes(el);
  lucide.createIcons();
}

// ---------------------------------------------------------------- relatorios
const AP_DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];

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

function apSerieDias(serie) {
  serie = serie || [];
  const max = Math.max(1, ...serie.map(s => s.passagens));
  const dia = s => `${s.slice(8, 10)}/${s.slice(5, 7)}`;
  return `<div class="ap-dias">${serie.map(s => `<div title="${dia(s.dia)}: ${s.passagens} passagens, ${s.pessoas} pessoas">
      <i style="height:${Math.round(s.passagens * 100 / max)}%"></i></div>`).join('')}</div>
    <div class="ap-eixo monospace"><span>${serie[0] ? dia(serie[0].dia) : ''}</span><span>${serie.length ? dia(serie[serie.length - 1].dia) : ''}</span></div>`;
}

function apDesenharRel(r) {
  const el = document.getElementById('apRelTopo');
  if (!el) return;
  const hoje = r.hoje || [];
  const portas = r.portas || [];
  const maxP = Math.max(1, ...portas.map(p => p.passagens));
  const agora = new Date();
  el.innerHTML = `
    <div class="ap-rel">
      <section class="panel ap-bloco"><div class="ap-bloco-cab"><div><h3>${{ escola: 'Quando a escola é usada', condominio: 'Quando o condomínio é usado' }[_apPerfil.tipo] || 'Quando os locais são usados'}</h3><p>Passagens por dia da semana e hora · últimos ${r.dias || 28} dias</p></div></div>
        ${apMapaCalor(r.mapa)}</section>
      <section class="panel ap-bloco"><div class="ap-bloco-cab"><div><h3>Dia a dia</h3><p>Passagens por dia · passe o mouse para ver pessoas únicas</p></div></div>
        ${apSerieDias(r.serie)}
        <h3 class="ap-h3b">Portas mais usadas</h3>
        ${portas.map(p => `<div class="ap-top"><span title="${esc(p.porta)}">${esc(apPorta(p.porta))}</span><span class="ap-trilho"><i style="width:${apPct(p.passagens, maxP)}%"></i></span><span class="monospace">${apNum(p.passagens)}</span></div>`).join('') || '<p class="ap-vazio">Sem passagens no período.</p>'}
      </section>
    </div>
    <section class="panel ap-tab-hoje">
      <div class="panel-header ap-cab"><div><h3>${apVocab().hoje}</h3><p>${apNum(r.hoje_total || 0)} pessoas do cadastro passaram hoje${r.nao_vieram_total ? ` · ${apNum(r.nao_vieram_total)} alunos ativos ainda sem passagem` : ''}${r.so_leitor_total ? ` · ${apNum(r.so_leitor_total)} só no leitor` : ''}</p></div></div>
      ${hoje.length ? `<div class="ap-tabela"><table><thead><tr><th>Pessoa</th><th>${apVocab().grupo}</th><th>${apEhCondominio() ? 'Primeira entrada' : 'Chegou'}</th><th>${apEhCondominio() ? 'Última saída' : 'Saiu'}</th><th>Tempo</th><th>Agora</th></tr></thead><tbody>
        ${hoje.map(x => {
          const ch = apLocal(x.chegou), sa = apLocal(x.saiu);
          const dentro = x.ultimo_tipo === 'entrada';
          return `<tr><td>${esc(x.nome)}</td><td>${esc(x.turma || apUnidade(x.nome, x.site) || '—')}</td><td class="monospace">${ch ? apHm(ch) : '—'}</td>
            <td class="monospace">${sa ? apHm(sa) : '—'}</td><td class="monospace">${ch ? apDur(ch, dentro ? agora : (sa || agora)) : '—'}</td>
            <td>${dentro ? '<span class="ap-chip entrada">dentro</span>' : '<span class="ap-chip saida">saiu</span>'}</td></tr>`;
        }).join('')}</tbody></table></div>` : '<p class="ap-vazio ap-pad">Ninguém do cadastro passou hoje.</p>'}
      ${(r.nao_vieram || []).length ? `<details class="ap-naovieram"><summary>${apNum(r.nao_vieram_total)} alunos ativos sem passagem hoje</summary>
        <div class="ap-naovieram-lista">${r.nao_vieram.map(x => `<span>${esc(x.nome)}${x.turma ? ` <small>${esc(x.turma)}</small>` : ''}</span>`).join('')}</div></details>` : ''}
    </section>
    ${(r.so_leitor_hoje || []).length ? `<section class="panel ap-tab-hoje">
      <div class="panel-header ap-cab"><div><h3>Só no leitor hoje</h3><p>${apNum(r.so_leitor_total)} nome${r.so_leitor_total === 1 ? '' : 's'} que o leitor reconhece e o SightOps não tem no cadastro${apEhCondominio() ? ': em condomínio, quase sempre moradores' : ''}</p></div></div>
      <div class="ap-tabela"><table><thead><tr><th>Nome no leitor</th><th>Passagens</th><th>Última porta</th><th>Última</th></tr></thead><tbody>
        ${r.so_leitor_hoje.map(x => `<tr><td>${esc(x.nome)}</td><td class="monospace">${apNum(x.passagens)}</td><td>${esc(apPorta(x.porta))}</td><td class="monospace">${apHm(apLocal(x.ultima))}</td></tr>`).join('')}
      </tbody></table></div>
      <p class="ap-dica ap-dica-pe">Para trazer essas pessoas ao SightOps: Controle de Acesso › Dispositivos › importar pessoas do leitor.</p>
    </section>` : ''}`;
}

// ---------------------------------------------------------------- visao geral
function apDesenharGeral(d) {
  const el = document.getElementById('apGeral');
  if (!el) return;
  const av = d.avisos || {}, s7 = av.sete_dias || {};
  const env = s7.enviados || 0, entregue = (s7.lidos || 0) + (s7.entregues || 0);
  const m7 = d.marcacoes_7d || {}, fotos = d.fotos || {}, leit = d.leitores || {};
  const semP = apPct(m7.sem_pessoa || 0, m7.total || 0);
  const serie = av.serie_30d || [];
  const usaAvisos = serie.some(x => x.lido + x.entregue + x.enviado + x.falha) || (av.incidentes || []).length > 0;
  const maxDia = Math.max(1, ...serie.map(x => x.lido + x.entregue + x.enviado + x.falha));
  const h = n => Math.round(n * 100 / maxDia) + '%';
  const dia = s => s ? `${s.slice(8, 10)}/${s.slice(5, 7)}` : '';
  // So portas com volume que importa: 1 marcacao sem pessoa em 370 nao e problema.
  const portasSem = (m7.por_porta || []).filter(p => p.sem_pessoa >= 20 || apPct(p.sem_pessoa, p.total) >= 5);

  el.innerHTML = `
    <div class="metrics">
      ${usaAvisos ? apKpi('message-circle', apPct(entregue, env) >= 95 ? 'green' : 'red', 'Avisos entregues · 7 dias', env ? apPct(entregue, env) + '%' : '—', `${apPct(s7.lidos || 0, env)}% lidos pelos responsáveis`)
                  : apKpi('message-circle', 'blue', 'Avisos de WhatsApp', '—', 'não usado neste cliente')}
      ${apKpi('user-x', semP > 10 ? 'red' : 'green', 'Marcações sem pessoa · 7 dias', semP + '%', `${m7.sem_pessoa || 0} de ${m7.total || 0}`)}
      ${apKpi('scan-face', fotos.falhou ? 'amber' : 'green', 'Fotos recusadas pelo leitor', fotos.falhou || 0, 'pessoas que não abrem a porta')}
      ${apKpi('door-open', leit.online === leit.total ? 'green' : 'amber', 'Leitores com status online', `${leit.online || 0} / ${leit.total || 0}`, 'status informado pelo leitor')}
    </div>

    ${usaAvisos ? `<section class="panel ap-bloco">
      <div class="ap-bloco-cab"><div><h3>Avisos aos responsáveis · 30 dias</h3><p>O WhatsApp informa entrega e leitura de cada aviso.</p></div>
        <div class="ap-legenda"><span><i class="lido"></i>lido</span><span><i class="entregue"></i>entregue</span><span><i class="enviado"></i>sem confirmação</span><span><i class="falha"></i>não entregue</span></div></div>
      <div class="ap-grafico">${serie.map(x => `<div title="${dia(x.dia)}: ${x.lido} lidos, ${x.entregue} entregues, ${x.falha} não entregues">
        <i class="falha" style="height:${h(x.falha)}"></i><i class="enviado" style="height:${h(x.enviado)}"></i>
        <i class="entregue" style="height:${h(x.entregue)}"></i><i class="lido" style="height:${h(x.lido)}"></i></div>`).join('')}</div>
      <div class="ap-eixo monospace"><span>${dia(serie[0]?.dia)}</span><span>${dia(serie[15]?.dia)}</span><span>${dia(serie[29]?.dia)}</span></div>
      ${(av.incidentes || []).slice().reverse().slice(0, 3).map(i => `<div class="ap-alerta"><i data-lucide="alert-triangle"></i><div>
        <b>${dia(i.inicio)}${i.fim !== i.inicio ? ' a ' + dia(i.fim) : ''}: ${i.falhas.toLocaleString('pt-BR')} avisos não chegaram aos responsáveis.</b>
        ${i.erro ? ` Motivo informado pela Meta: "${esc(i.erro)}"${/payment/i.test(i.erro) ? ' (pendência de pagamento da conta do WhatsApp Business)' : ''}.` : ''}</div></div>`).join('')}
      <p class="ap-dica">Se mais de 10% dos avisos falharem em 30 minutos, o canal de WhatsApp fica fora no Monitoramento, com o motivo.</p>
    </section>` : ''}

    <div class="ap-duas">
      ${usaAvisos ? `<section class="panel ap-bloco"><h3>Responsáveis que não estão recebendo</h3><p>O último aviso para estes números falhou. Motivo dado pela Meta.</p>
        ${(av.falhando || []).map(f => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(f.responsavel || 'número sem cadastro')}</b>
            <small>${esc([f.pessoa, f.turma].filter(Boolean).join(' · '))}</small></div>
          <span class="monospace">${esc(f.numero)}</span><span class="ap-ruim">${esc(f.erro || 'falhou')}</span></div>`).join('') || '<p class="ap-vazio">Nenhum responsável com aviso falhando.</p>'}
        ${av.sem_numero_total ? `<p class="ap-dica">${av.sem_numero_total} aluno${av.sem_numero_total === 1 ? '' : 's'} sem número de responsável: não recebe${av.sem_numero_total === 1 ? '' : 'm'} aviso nenhum.</p>` : ''}
      </section>` : `<section class="panel ap-bloco"><h3>Avisos por WhatsApp</h3><p class="ap-vazio">Nenhum aviso enviado nos últimos 60 dias: este cliente não usa os avisos aos responsáveis.</p></section>`}
      <section class="panel ap-bloco"><h3>Marcações sem pessoa no SightOps</h3><p>A pessoa está no leitor, mas não no cadastro: fica fora de relatório, presença e aviso.</p>
        ${portasSem.map(p => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(p.porta)}</b>
            <small>${p.sem_pessoa} de ${p.total} marcações · ${p.nomes_distintos} nome${p.nomes_distintos === 1 ? '' : 's'} diferentes${p.exemplos.length ? ' · ex.: ' + p.exemplos.map(esc).join(', ') : ''}</small>
            <div class="ap-barra"><i style="width:${apPct(p.sem_pessoa, p.total)}%"></i></div></div>
          <b class="ap-ruim">${apPct(p.sem_pessoa, p.total)}%</b></div>`).join('') || '<p class="ap-vazio">Todas as marcações estão ligadas a uma pessoa.</p>'}
        ${portasSem.length ? '<p class="ap-dica">Para corrigir hoje: Controle de Acesso › Dispositivos › importar pessoas do leitor.</p>' : ''}
      </section>
    </div>
    <div class="ap-duas">
      <section class="panel ap-bloco"><h3>Fotos recusadas pelos leitores</h3><p>${fotos.ok || 0} fotos aceitas · ${fotos.falhou || 0} recusadas${fotos.pendente ? ' · ' + fotos.pendente + ' aguardando' : ''}</p>
        ${(fotos.recusadas || []).map(f => `<div class="ap-linha"><div class="ap-cresce"><b>${esc(f.pessoa)}</b>
            <small>${esc([f.turma, f.leitor].filter(Boolean).join(' · '))}</small></div><span class="ap-ruim">${esc(f.erro || 'recusada')}</span></div>`).join('') || '<p class="ap-vazio">Nenhuma foto recusada.</p>'}
      </section>
      <section class="panel ap-bloco"><h3>Leitores</h3><p>Status informado pelo leitor e última vez que o SightOps falou com ele.</p>
        ${(leit.lista || []).map(l => {
          const on = String(l.status).toLowerCase() === 'online';
          return `<div class="ap-linha"><span class="ap-pt ${on ? 'ok' : 'ruim'}"></span><div class="ap-cresce"><b>${esc(l.nome)}</b>
            <small>${esc(l.site)} · visto ${apHa(apUtc(l.visto) || apLocal(l.visto))}</small></div><span class="${on ? 'ap-ok' : 'ap-ruim'}">${esc(l.status || 'sem status')}</span></div>`;
        }).join('') || '<p class="ap-vazio">Nenhum leitor cadastrado.</p>'}
      </section>
    </div>`;
  lucide.createIcons();
}

// ---------------------------------------------------------------- ciclo
function apQ(extra) {
  const p = new URLSearchParams(extra || {});
  if (_apSite) p.set('site', _apSite);
  const s = p.toString();
  return s ? '?' + s : '';
}

// A visao geral (avisos 30 dias, fotos, leitores) muda devagar: no maximo a cada 2 min.
async function apGeral(forcar) {
  if (forcar || !_apDados.geral || Date.now() - _apDados.geralEm > 120000) {
    _apDados.geral = await apiJson(`/api/access-control/painel/visao-geral${apQ()}`) || {};
    _apDados.geralEm = Date.now();
  }
  return _apDados.geral;
}

function apDesenharAtual() {
  if (AP_ABAS_PROPRIAS[_apTela]) { apMarcarAba(); return; }   // Dispositivos/Pessoas se desenham sozinhas
  apMostrarPerfil((_apTela === 'relatorios' ? (_apDados.rel || {}).perfil : (_apDados.vivo || {}).perfil) || (_apDados.geral || {}).perfil);
  if (_apTela === 'vivo') apDesenharVivo(_apDados.vivo || {});
  else if (_apTela === 'portas') apDesenharPortas(_apDados.vivo || {});
  else if (_apTela === 'alertas') apDesenharAlertas();
  else {
    apDesenharRel(_apDados.rel || {});
    apDesenharGeral(_apDados.geral || {});
  }
  apMarcarAba();
}

async function apAtualizar(manual) {
  if (AP_ABAS_PROPRIAS[_apTela]) {
    // Gaveta aberta: nao redesenha por baixo de quem esta editando.
    if (document.querySelector('.dv-gaveta:not([hidden])')) return;
    AP_ABAS_PROPRIAS[_apTela].carregar().catch(() => {});
    return;
  }
  if (_apCarregando) return;
  _apCarregando = true;
  try {
    if (_apTela === 'relatorios') {
      const [rel] = await Promise.all([apiJson(`/api/access-control/painel/relatorios${apQ()}`), apGeral(manual)]);
      _apDados.rel = rel || {};
    } else {
      const vivo = await apiJson(`/api/access-control/painel/ao-vivo${apQ({ limit: 400 })}`) || {};
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
    const alvo = document.getElementById({ vivo: 'apVivo', portas: 'apPortas', alertas: 'apAlertas', relatorios: 'apRelTopo' }[_apTela]);
    if (alvo && !alvo.innerHTML.trim()) alvo.innerHTML = `<p class="ap-vazio">Não consegui carregar: ${esc(err?.message || err)}</p>`;
  } finally {
    _apCarregando = false;
  }
}

function apLigarStream() {
  if (_apFonte) { _apFonte.close(); _apFonte = null; }
  if (!['vivo', 'portas', 'alertas'].includes(_apTela) || typeof EventSource === 'undefined') return;
  _apFonte = new EventSource(`${API_BASE}/api/access-control/live/stream${apQ()}`);
  _apFonte.addEventListener('access-event', () => apAtualizar());
}

function apTrocarTela(tela) {
  if (tela === 'geral') tela = 'relatorios';   // aba antiga "Visao geral"
  _apTela = AP_TELAS.includes(tela) ? tela : 'vivo';
  if (_apTela !== 'vivo') _apPausado = false;
  document.querySelectorAll('[data-ap-tela]').forEach(b => {
    const on = b.dataset.apTela === _apTela;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', String(on));
  });
  document.getElementById('apVivo').hidden = _apTela !== 'vivo';
  document.getElementById('apPortas').hidden = _apTela !== 'portas';
  document.getElementById('apAlertas').hidden = _apTela !== 'alertas';
  document.getElementById('apRel').hidden = _apTela !== 'relatorios';
  Object.entries(AP_ABAS_PROPRIAS).forEach(([k, a]) => { document.getElementById(a.el).hidden = _apTela !== k; });
  // Menu lateral: "Dispositivos" acende na aba dele; nas outras, "Painel de Acesso".
  document.querySelectorAll('#sidebar .nav-item[data-pagina]').forEach(b =>
    b.classList.toggle('active', b.dataset.pagina === (_apTela === 'dispositivos' ? 'dispositivos' : 'painel')));
  try { sessionStorage.setItem('sightops.acesso.painel.tela', _apTela); } catch (_) {}
  try { history.replaceState(null, '', '#' + _apTela); } catch (_) {}
  apLigarStream();
  if (AP_ABAS_PROPRIAS[_apTela]) { AP_ABAS_PROPRIAS[_apTela].abrir(); return; }
  // Troca de aba desenha na hora com o que ja tem; o fetch atualiza depois.
  if ((_apTela === 'relatorios' && _apDados.rel) || (_apTela !== 'relatorios' && _apDados.vivo)) apDesenharAtual();
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
      _apDados.vivo = _apDados.rel = _apDados.geral = null;
      _apSel = ''; _apPessoa = '';
      apLigarStream(); apAtualizar(true);
    });
    document.querySelectorAll('[data-ap-tela]').forEach(b => b.addEventListener('click', () => apTrocarTela(b.dataset.apTela)));
    document.getElementById('btnApAtualizar')?.addEventListener('click', () => apAtualizar(true));
  }
  try {
    const g = await apiJson('/api/access-control/painel/visao-geral');
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
  // A aba do endereco manda (/v3/acesso/#dispositivos, link do menu, recarregar).
  const pedida = window.location.hash.slice(1);
  if (AP_TELAS.includes(pedida)) salva = pedida;
  if (!window._apHashLigado) {
    window._apHashLigado = true;
    window.addEventListener('hashchange', () => {
      const h = window.location.hash.slice(1);
      if (AP_TELAS.includes(h) && h !== _apTela) apTrocarTela(h);
    });
  }
  stopAccessPainel();
  apTrocarTela(salva);
  _apTimer = setInterval(() => { if (!document.hidden) apAtualizar(); }, 20000);
  _apRelogio = setInterval(() => {
    const r = document.getElementById('apRelogio');
    if (r) r.textContent = new Date().toLocaleTimeString('pt-BR');
  }, 1000);
}

window.acPagina = { id: 'painel', iniciar: loadAccessPainel };
