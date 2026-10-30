// Ponto de venda -- auditoria de caixa. Sem IA: os dados do proprio PDV
// (Espiao + Teclas, mandados pelo coletor do caixa) e o video do gravador como
// prova. Telas: Ao vivo, Visao geral, Cupons; caixas em Configuracoes.
// Revisao e Operadores (regras e ranking) entram na fase 2.

const PDV_MODOS = {
  scanner: ['bipado', 'pdv-modo-bipado'],
  manual: ['digitado', 'pdv-modo-digitado'],
  menu: ['menu', 'pdv-modo-menu'],
  outro: ['outro', 'pdv-modo-outro'],
  sem_tecla: ['sem tecla', 'pdv-modo-outro'],
};
const PDV_SITUACAO = {
  aberto: ['em andamento', 'pdv-sit-aberto'],
  fechado: ['fechado', 'pdv-sit-ok'],
  cancelado: ['cancelado', 'pdv-sit-cancelado'],
};

let _pdvCaixas = [];
let _pdvDia = '';
let _pdvTimer = null;
// modo 'parede' (todos os caixas da loja) ou 'foco' (um caixa, video grande e cupom)
let _pdvVivo = { caixaId: '', handle: null, timer: null, alta: false, modo: 'parede', loja: '', pedidoFoco: '', parede: new Map() };

// ---------------------------------------------------------------- comum

function pdvHoje() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function pdvMoeda(centavos) {
  return (Number(centavos || 0) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
}

function pdvNum(n) {
  return Number(n || 0).toLocaleString('pt-BR');
}

function pdvPlural(n, palavra) {
  return `${pdvNum(n)} ${palavra}${Number(n) === 1 ? '' : 's'}`;
}

function pdvHora(ts) {
  return String(ts || '').slice(11, 19);
}

function pdvChip(mapa, chave) {
  const [txt, cls] = mapa[chave] || [chave || '-', 'pdv-modo-outro'];
  return `<span class="pdv-chip ${cls}">${esc(txt)}</span>`;
}

function pdvDiaRotulo(dia) {
  if (dia === pdvHoje()) return 'Hoje';
  const [a, m, d] = dia.split('-');
  return `${d}/${m}/${a}`;
}

function pdvMudarDia(dia, delta) {
  const d = new Date(`${dia}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function pdvIdade(ts) {
  // ultimo_contato vem em UTC ('...Z'); devolve segundos ou null
  if (!ts) return null;
  const t = Date.parse(ts);
  return Number.isNaN(t) ? null : Math.max(0, Math.round((Date.now() - t) / 1000));
}

function pdvSaudeCaixa(c) {
  if (!c.ativo) return { cls: 'cinza', txt: 'desligado' };
  const idade = pdvIdade(c.ultimo_contato);
  if (idade === null) return { cls: 'cinza', txt: 'coletor não instalado' };
  if (idade > 180) return { cls: 'ambar', txt: `sem contato há ${Math.round(idade / 60)} min` };
  return { cls: 'verde', txt: 'coletando' };
}

function pdvRelogio(c) {
  if (c.relogio_dvr_offset_s === null || c.relogio_dvr_offset_s === undefined) return 'não medido';
  const s = Number(c.relogio_dvr_offset_s);
  return `${s >= 0 ? '+' : ''}${s} s`;
}

let _pdvSites = [];

async function pdvCarregarCaixas() {
  const r = await apiJson('/api/pdv/caixas', { forceRefresh: true });
  _pdvCaixas = r?.caixas || [];
  _pdvSites = r?.sites || [];
  return _pdvCaixas;
}

function pdvVisivel(viewId) {
  const el = document.getElementById(viewId);
  return el && !el.classList.contains('hidden');
}

function pdvParar() {
  if (_pdvTimer) { clearInterval(_pdvTimer); _pdvTimer = null; }
  if (_pdvVivo.timer) { clearInterval(_pdvVivo.timer); _pdvVivo.timer = null; }
  if (_pdvVivo.handle) { try { _pdvVivo.handle.stop(); } catch (_) {} _pdvVivo.handle = null; }
  _pdvVivo.parede.forEach(h => { try { h.stop(); } catch (_) {} });
  _pdvVivo.parede.clear();
  if (typeof pdvPararGravacao === 'function') pdvPararGravacao();
}

function pdvSemCaixa(boxId) {
  const box = document.getElementById(boxId);
  if (!box) return;
  box.innerHTML = `
    <div class="pdv-vazio">
      <div class="pdv-vazio-icone"><i data-lucide="scan-barcode"></i></div>
      <h2>Nenhum caixa cadastrado</h2>
      <p>Cadastre o caixa em Configurações › Ponto de venda e instale o coletor nele. Em até 1 minuto as vendas começam a aparecer aqui.</p>
      <button class="secondary-action" type="button" data-pdv-config>Configurar caixas</button>
    </div>`;
  box.querySelector('[data-pdv-config]')?.addEventListener('click', pdvAbrirConfig);
  lucide.createIcons();
}

function pdvAbrirConfig() {
  document.querySelector('.nav-item[data-view="settings"]')?.click();
  setTimeout(() => activateSettingsTab('pdv'), 50);
}

// ---------------------------------------------------------------- lojas
// Os caixas agrupados pelo site (loja) de cada um. So as lojas que o usuario
// acessa (o servidor filtra). Situacao "agora" so no dia de hoje.

let _pdvLojasDia = '';
const PDV_ESTADO_CX = {
  em_venda: ['em venda', 'pdv-cx-venda'],
  livre: ['livre', 'pdv-cx-livre'],
  parado: ['sem venda há mais de 1 h', 'pdv-cx-parado'],
  sem_coletor: ['sem coletor', 'pdv-cx-sem'],
  desligado: ['desligado', 'pdv-cx-livre'],
};

async function loadPdvLojas() {
  pdvParar();
  _pdvLojasDia = _pdvLojasDia || pdvHoje();
  await pdvRenderLojas();
  _pdvTimer = setInterval(() => {
    if (!pdvVisivel('viewPdvLojas')) { pdvParar(); return; }
    if (_pdvLojasDia === pdvHoje()) pdvRenderLojas();
  }, 30000);
}

function pdvLojasDia(delta) {
  _pdvLojasDia = pdvMudarDia(_pdvLojasDia || pdvHoje(), delta);
  if (_pdvLojasDia > pdvHoje()) _pdvLojasDia = pdvHoje();
  pdvRenderLojas();
}

function pdvPorMil(x) {
  return Number(x || 0).toLocaleString('pt-BR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function pdvAlertaTexto(a) {
  const v = a.valor_centavos ? ` ${pdvMoeda(a.valor_centavos)}` : '';
  switch (a.tipo) {
    case 'CIT': return [`Item cancelado: ${a.descricao || a.codigo || '?'}${v}`, 'pdv-l-vermelho'];
    case 'CCV': return [`Cupom ${a.cupom} cancelado${v}`, 'pdv-l-vermelho'];
    case 'CCG': return [`Cupom anterior cancelado${v}`, 'pdv-l-vermelho'];
    case 'ITEMSEMCAD': return [`Código sem cadastro: ${a.codigo || '?'}`, 'pdv-l-vermelho'];
    case 'DST': return [`Desconto no subtotal do cupom ${a.cupom}`, 'pdv-l-ambar'];
    case 'SGR': return [`Sangria${v}`, 'pdv-l-azul'];
    default: return [a.tipo, 'pdv-l-ambar'];
  }
}

function pdvIrAoVivo(caixaId) {
  if (!caixaId) return;
  _pdvVivo.caixaId = caixaId;
  _pdvVivo.pedidoFoco = caixaId;  // abre direto o caixa (pelo menu, abre a parede)
  document.querySelector('.nav-item[data-view="pdv-vivo"]')?.click();
}

function pdvIrLoja(nome) {
  _pdvVivo.loja = nome || '';
  _pdvVivo.pedidoFoco = '';
  document.querySelector('.nav-item[data-view="pdv-vivo"]')?.click();
}

async function pdvRenderLojas() {
  const box = document.getElementById('pdvLojasBody');
  if (!box) return;
  const r = await apiJson(`/api/pdv/lojas?dia=${_pdvLojasDia}`, { forceRefresh: true });
  setText('pdvLojasDia', pdvDiaRotulo(_pdvLojasDia));
  if (!r || !Array.isArray(r.lojas)) {
    box.innerHTML = '<p class="pdv-nota">Não foi possível carregar as lojas agora.</p>';
    return;
  }
  if (!r.lojas.length) { pdvSemCaixa('pdvLojasBody'); return; }
  const rede = r.rede || {};
  const ticket = rede.cupons ? rede.vendido_centavos / rede.cupons : 0;
  const semCol = r.sem_coletor || [];
  const nLojas = r.lojas.length;
  const umaLoja = nLojas === 1 ? r.lojas[0] : null;
  setText('pdvLojasTitulo', umaLoja ? umaLoja.nome : 'Lojas da rede');
  setText('pdvLojasSub', umaLoja ? 'Vendas, caixas e ocorrências da loja, agora.' : 'Vendas, caixas e ocorrências de cada loja, agora.');
  // a tabela e o painel de ocorrencias lado a lado com a mesma altura: linha de
  // tabela tem 40 px e ocorrencia ~60, entao mostra ~2/3 de ocorrencias por linha
  const linhasTabela = umaLoja ? umaLoja.caixas.length + 1 : nLojas + 1;
  const nAlertas = Math.max(2, Math.round(linhasTabela * 2 / 3));
  const coletaTxt = semCol.length
    ? `${esc(semCol[0].caixa)}${nLojas > 1 ? ` da ${esc(semCol[0].loja)}` : ''} sem coletor${semCol.length > 1 ? ` e mais ${semCol.length - 1}` : ''}`
    : 'todos coletando';

  const cartao = l => {
    const tk = l.cupons ? l.vendido_centavos / l.cupons : 0;
    const okCx = l.coletando === l.n_caixas;
    return `
      <article class="pdv-l-card pdv-l-s3 pdv-l-loja">
        <div class="pdv-l-head pdv-l-topo">
          <div class="pdv-l-stat"><strong class="pdv-l-nome" title="${esc(l.nome)}">${esc(l.nome)}</strong>
            <span class="pdv-l-sub">${pdvPlural(l.n_caixas, 'caixa')}</span></div>
          <button type="button" class="pdv-l-link" data-pdv-loja="${esc(l.nome)}" title="Ver os caixas desta loja ao vivo">Abrir</button>
        </div>
        <div class="pdv-l-stat"><span class="pdv-l-k">Vendido ${r.hoje ? 'hoje' : 'no dia'}</span>
          <strong class="pdv-l-big">${pdvMoeda(l.vendido_centavos)}</strong></div>
        <div class="pdv-l-tres">
          <div class="pdv-l-stat"><span class="pdv-l-k">Cupons</span><strong>${pdvNum(l.cupons)}</strong></div>
          <div class="pdv-l-stat"><span class="pdv-l-k">Ticket</span><strong>${pdvMoeda(tk)}</strong></div>
          <div class="pdv-l-stat"><span class="pdv-l-k pdv-l-k-ambar">Revisar</span><strong>${pdvNum(l.revisar)}</strong></div>
        </div>
        <div class="pdv-l-caixas">
          <div class="pdv-l-head"><span class="pdv-l-k">${r.hoje ? 'Caixas agora' : 'Caixas'}</span>
            ${r.hoje ? `<span class="pdv-l-cont ${okCx ? 'ok' : 'ruim'}">${l.coletando} de ${l.n_caixas}</span>` : ''}</div>
          <div class="pdv-l-cxs">${l.caixas.map(c => {
            const [txt, cls] = PDV_ESTADO_CX[c.estado] || ['', 'pdv-cx-neutro'];
            const parado = c.estado === 'parado' && c.parado_min ? ` (${c.parado_min} min)` : '';
            const tit = `${c.nome}${txt ? ` · ${txt}${parado}` : ''} · ${pdvNum(c.cupons)} ${Number(c.cupons) === 1 ? 'cupom' : 'cupons'} ·${pdvMoeda(c.vendido_centavos)}`;
            return `<button type="button" class="pdv-l-cx ${cls}" data-pdv-ir="${esc(c.id)}" title="${esc(tit)}"
              aria-label="${esc(tit)}">${String(c.numero || '').padStart(2, '0')}</button>`;
          }).join('')}</div>
        </div>
      </article>`;
  };

  const linha = l => `
    <tr>
      <td><strong title="${esc(l.nome)}">${esc(l.nome)}</strong></td>
      <td class="num"><strong>${pdvMoeda(l.vendido_centavos)}</strong></td>
      <td class="num">${pdvNum(l.cupons)}</td>
      <td class="num">${pdvMoeda(l.cupons ? l.vendido_centavos / l.cupons : 0)}</td>
      <td class="num">${pdvPct(l.bipados, l.itens)}</td>
      <td class="num ${l.cancelados_por_mil > rede.cancelados_por_mil * 1.5 && l.cancelados ? 'pdv-l-ruim' : ''}">${pdvPorMil(l.cancelados_por_mil)}</td>
      <td class="num">${pdvNum(l.revisar)}</td>
      <td class="num ${r.hoje && l.coletando < l.n_caixas ? 'pdv-l-ruim' : ''}">${r.hoje ? `${l.coletando}/${l.n_caixas}` : l.n_caixas}</td>
    </tr>`;

  const linhaCaixa = c => {
    const [txt, cls] = PDV_ESTADO_CX[c.estado] || ['–', 'pdv-cx-neutro'];
    const sit = c.estado === 'parado' && c.parado_min ? `sem venda há ${c.parado_min} min` : txt;
    return `
    <tr class="pdv-l-clica" data-pdv-ir="${esc(c.id)}" title="Abrir ${esc(c.nome)} ao vivo">
      <td><strong>${esc(c.nome)}</strong></td>
      <td>${r.hoje ? `<i class="pdv-l-sit ${cls}" aria-hidden="true"></i>${esc(sit)}` : '<span class="pdv-muted">–</span>'}</td>
      <td class="num"><strong>${pdvMoeda(c.vendido_centavos)}</strong></td>
      <td class="num">${pdvNum(c.cupons)}</td>
      <td class="num">${pdvMoeda(c.cupons ? c.vendido_centavos / c.cupons : 0)}</td>
      <td class="num">${pdvPct(c.bipados, c.itens)}</td>
      <td class="num">${pdvNum(c.cancelados)}</td>
      <td class="num">${pdvNum(c.cancelados + c.sem_cadastro)}</td>
    </tr>`;
  };

  const tabelaLojas = `
        <div class="pdv-l-head pdv-l-titulo"><h2 class="pdv-l-h2">Comparar lojas</h2>
          <span class="pdv-l-sub">números de ${r.hoje ? 'hoje' : esc(pdvDiaRotulo(r.dia))}</span></div>
        <div class="pdv-l-rolar"><table class="pdv-l-tb">
          <colgroup><col><col style="width:128px"><col style="width:80px"><col style="width:96px"><col style="width:84px"><col style="width:112px"><col style="width:76px"><col style="width:64px"></colgroup>
          <thead><tr><th>Loja</th><th class="num">Vendido</th><th class="num">Cupons</th><th class="num">Ticket</th>
            <th class="num">Bipados</th><th class="num">Cancel. por mil</th><th class="num">Revisar</th><th class="num">Caixas</th></tr></thead>
          <tbody>${r.lojas.map(linha).join('')}</tbody>
          <tfoot><tr><td><strong>Rede</strong></td><td class="num"><strong>${pdvMoeda(rede.vendido_centavos)}</strong></td>
            <td class="num">${pdvNum(rede.cupons)}</td><td class="num">${pdvMoeda(ticket)}</td><td class="num">${pdvPct(rede.bipados, rede.itens)}</td>
            <td class="num">${pdvPorMil(rede.cancelados_por_mil)}</td><td class="num">${pdvNum(rede.revisar)}</td>
            <td class="num">${r.hoje ? `${rede.coletando}/${rede.n_caixas}` : rede.n_caixas}</td></tr></tfoot>
        </table></div>`;

  const tabelaCaixas = umaLoja ? `
        <div class="pdv-l-head pdv-l-titulo"><h2 class="pdv-l-h2">Caixas da loja</h2>
          ${r.hoje ? `<div class="pdv-l-legenda pdv-l-sub">
            <span><i class="pdv-cx-venda"></i>em venda</span><span><i class="pdv-cx-livre"></i>livre</span>
            <span><i class="pdv-cx-parado"></i>parado</span><span><i class="pdv-cx-sem"></i>sem coletor</span></div>`
            : `<span class="pdv-l-sub">números de ${esc(pdvDiaRotulo(r.dia))}</span>`}</div>
        <div class="pdv-l-rolar"><table class="pdv-l-tb">
          <colgroup><col style="width:96px"><col><col style="width:128px"><col style="width:80px"><col style="width:96px"><col style="width:84px"><col style="width:92px"><col style="width:76px"></colgroup>
          <thead><tr><th>Caixa</th><th>Situação</th><th class="num">Vendido</th><th class="num">Cupons</th><th class="num">Ticket</th>
            <th class="num">Bipados</th><th class="num">Cancelados</th><th class="num">Revisar</th></tr></thead>
          <tbody>${umaLoja.caixas.map(linhaCaixa).join('')}</tbody>
          <tfoot><tr><td><strong>Loja</strong></td><td class="pdv-l-sub">${r.hoje ? `${umaLoja.coletando} de ${umaLoja.n_caixas} coletando` : ''}</td>
            <td class="num"><strong>${pdvMoeda(umaLoja.vendido_centavos)}</strong></td><td class="num">${pdvNum(umaLoja.cupons)}</td>
            <td class="num">${pdvMoeda(ticket)}</td><td class="num">${pdvPct(umaLoja.bipados, umaLoja.itens)}</td>
            <td class="num">${pdvNum(umaLoja.cancelados)}</td><td class="num">${pdvNum(umaLoja.revisar)}</td></tr></tfoot>
        </table></div>` : '';

  const alertas = (r.alertas || []).slice(0, nAlertas).map(a => {
    const [txt, cor] = pdvAlertaTexto(a);
    return `
      <div class="pdv-l-alerta">
        <i class="${cor}" aria-hidden="true"></i>
        <div class="pdv-l-stat">
          <span class="pdv-l-sub pdv-l-uma">${esc(pdvHora(a.ts))} · <strong>${esc(nLojas > 1 ? a.loja : a.caixa)}</strong>${nLojas > 1 ? ` · ${esc(a.caixa)}` : ''}</span>
          <span class="pdv-l-txt" title="${esc(txt)}">${esc(txt)}</span>
        </div>
        <button type="button" class="pdv-l-link" data-pdv-cupom="${esc(a.cupom || '')}" data-pdv-caixa="${esc(a.caixa_id)}"
          data-pdv-dia="${esc(String(a.ts || '').slice(0, 10))}" title="Abrir o cupom, com os itens e o vídeo">abrir</button>
      </div>`;
  }).join('') || '<p class="pdv-l-sub pdv-l-vazio">Nenhuma ocorrência neste dia.</p>';

  box.innerHTML = `
    <div class="pdv-l-grade">
      <section class="pdv-l-card pdv-l-s3"><div class="pdv-l-stat"><span class="pdv-l-k">Vendido ${nLojas > 1 ? 'na rede' : 'na loja'}</span>
        <strong class="pdv-l-big">${pdvMoeda(rede.vendido_centavos)}</strong>
        <span class="pdv-l-sub">${pdvPlural(nLojas, 'loja')}${r.hoje ? ` · até ${new Date().toTimeString().slice(0, 5)}` : ''}</span></div></section>
      <section class="pdv-l-card pdv-l-s3"><div class="pdv-l-stat"><span class="pdv-l-k">Cupons</span>
        <strong class="pdv-l-big">${pdvNum(rede.cupons)}</strong>
        <span class="pdv-l-sub">ticket médio ${pdvMoeda(ticket)}</span></div></section>
      <section class="pdv-l-card pdv-l-s3"><div class="pdv-l-stat"><span class="pdv-l-k">Caixas coletando</span>
        <strong class="pdv-l-big">${r.hoje ? pdvNum(rede.coletando) : '–'} <em>de ${pdvNum(rede.n_caixas)}</em></strong>
        <span class="pdv-l-sub pdv-l-uma ${semCol.length && r.hoje ? 'pdv-l-ruim' : ''}" title="${r.hoje ? coletaTxt : ''}">${r.hoje ? coletaTxt : 'situação só no dia de hoje'}</span></div></section>
      <section class="pdv-l-card pdv-l-s3"><div class="pdv-l-stat"><span class="pdv-l-k pdv-l-k-ambar">Para revisar</span>
        <strong class="pdv-l-big">${pdvNum(rede.revisar)}</strong>
        <span class="pdv-l-sub pdv-l-uma">${pdvNum(rede.cancelados)} cancelados · ${pdvNum(rede.sem_cadastro)} sem cadastro</span></div></section>

      ${umaLoja ? '' : `<div class="pdv-l-s12 pdv-l-head pdv-l-secao">
        <h2 class="pdv-l-h2">Lojas</h2>
        ${r.hoje ? `<div class="pdv-l-legenda pdv-l-sub">
          <span><i class="pdv-cx-venda"></i>em venda</span><span><i class="pdv-cx-livre"></i>livre</span>
          <span><i class="pdv-cx-parado"></i>sem venda há mais de 1 h</span><span><i class="pdv-cx-sem"></i>sem coletor</span>
        </div>` : ''}
      </div>
      ${r.lojas.map(cartao).join('')}`}

      <section class="pdv-l-card pdv-l-tabela pdv-l-mais">${umaLoja ? tabelaCaixas : tabelaLojas}</section>

      <aside class="pdv-l-card pdv-l-lado pdv-l-mais pdv-l-agora" aria-label="Últimas ocorrências">
        <div class="pdv-l-head pdv-l-agora-topo"><h2 class="pdv-l-h2">${r.hoje ? 'Acontecendo agora' : 'Últimas ocorrências'}</h2>
          <span class="pdv-l-sub">${nLojas > 1 ? 'todas as lojas' : 'da loja'}</span></div>
        ${alertas}
        <div class="pdv-l-agora-pe"><button type="button" class="pdv-l-link" data-pdv-cupons>Ver os cupons</button></div>
      </aside>
    </div>`;
  box.querySelectorAll('[data-pdv-ir]').forEach(b => b.addEventListener('click', () => pdvIrAoVivo(b.dataset.pdvIr)));
  box.querySelectorAll('[data-pdv-loja]').forEach(b => b.addEventListener('click', () => pdvIrLoja(b.dataset.pdvLoja)));
  box.querySelectorAll('[data-pdv-cupom]').forEach(b => b.addEventListener('click', () =>
    pdvIrCupom(b.dataset.pdvCaixa, b.dataset.pdvDia || _pdvLojasDia, b.dataset.pdvCupom)));
  box.querySelector('[data-pdv-cupons]')?.addEventListener('click', () => document.querySelector('.nav-item[data-view="pdv-cupons"]')?.click());
  lucide.createIcons();
}

// ---------------------------------------------------------------- visao geral

async function loadPdvVisao() {
  pdvParar();
  _pdvDia = _pdvDia || pdvHoje();
  await pdvRenderVisao();
  _pdvTimer = setInterval(() => {
    if (!pdvVisivel('viewPdvVisao')) { pdvParar(); return; }
    if (_pdvDia === pdvHoje()) pdvRenderVisao();
  }, 15000);
}

function pdvHaQuanto(ts) {
  // ts = hora do caixa 'AAAA-MM-DD HH:MM:SS' (mesmo fuso do navegador)
  if (!ts) return '';
  const t = new Date(ts.replace(' ', 'T')).getTime();
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 60) return 'agora';
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (ts.slice(0, 10) === pdvHoje()) return `às ${ts.slice(11, 16)}`;
  return `${ts.slice(8, 10)}/${ts.slice(5, 7)} ${ts.slice(11, 16)}`;
}

function pdvPct(parte, todo) {
  return todo ? (100 * parte / todo).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%' : '–';
}

async function pdvRenderVisao() {
  const box = document.getElementById('pdvVisaoBody');
  if (!box) return;
  const [caixas, resumo] = await Promise.all([
    pdvCarregarCaixas(),
    apiJson(`/api/pdv/resumo?dia=${_pdvDia}`, { forceRefresh: true }),
  ]);
  setText('pdvVisaoDia', pdvDiaRotulo(_pdvDia));
  if (!caixas.length) { pdvSemCaixa('pdvVisaoBody'); return; }
  const r = resumo || {};
  const m = r.modos || {};
  const n = k => (m[k]?.n || 0);
  const v = k => (m[k]?.centavos || 0);
  const itens = r.itens || 0;
  const cup = r.cupons || {};
  const ev = r.eventos || {};
  const porCaixa = r.por_caixa || {};
  const fechados = cup.fechado || 0;
  const ticket = fechados ? r.vendido_centavos / fechados : 0;
  const coletando = caixas.filter(c => pdvSaudeCaixa(c).cls === 'verde').length;
  const semVenda = caixas.filter(c => pdvSaudeCaixa(c).cls === 'verde' && !porCaixa[c.id]?.cupons).length;
  const semColetor = caixas.length - coletando;
  const alertaCaixas = semColetor ? `${semColetor} sem coletor` : (semVenda ? `${semVenda} sem venda lida hoje` : '');
  const cancItens = ev.CIT || 0;
  const cancCupons = (ev.CCV || 0) + (ev.CCG || 0);

  const fatias = [
    { k: 'bipado', rot: 'Bipados', n: n('scanner'), v: v('scanner'), cls: 'bipado' },
    { k: 'digitado', rot: 'Digitados', n: n('manual'), v: v('manual'), cls: 'digitado' },
    { k: 'menu', rot: 'Pelo menu', n: n('menu'), v: v('menu'), cls: 'menu' },
    { k: 'sem', rot: 'Sem tecla', n: n('sem_tecla') + n('outro'), v: v('sem_tecla') + v('outro'), cls: 'sem' },
  ];
  const ocorrencias = [
    ['x-circle', 'Itens cancelados', cancItens, itens ? `${(1000 * cancItens / itens).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} por mil itens` : ''],
    ['ban', 'Cupons cancelados', cancCupons, ''],
    ['percent', 'Descontos em item', ev.DIT || 0, ''],
    ['badge-percent', 'Descontos no subtotal', ev.DST || 0, ''],
    ['scan-search', 'Código sem cadastro', ev.ITEMSEMCAD || 0, ''],
    ['hand-coins', 'Sangrias', ev.SGR || 0, ''],
    ['archive', 'Gaveta aberta', ev.GAV || 0, ''],
  ];

  box.innerHTML = `
    <section class="pdv-kpis">
      <article class="pdv-kpi">
        <div class="metric-icon blue"><i data-lucide="banknote"></i></div>
        <div><span>Vendido</span><strong>${pdvMoeda(r.vendido_centavos)}</strong>
          <small>${pdvNum(fechados)} cupons · média ${pdvMoeda(ticket)}</small></div>
      </article>
      <article class="pdv-kpi">
        <div class="metric-icon green"><i data-lucide="scan-barcode"></i></div>
        <div><span>Itens passados</span><strong>${pdvNum(itens)}</strong>
          <small>${pdvPct(n('scanner'), itens)} bipados</small></div>
      </article>
      <article class="pdv-kpi">
        <div class="metric-icon amber"><i data-lucide="x-circle"></i></div>
        <div><span>Cancelamentos</span><strong>${pdvNum(cancItens + cancCupons)}</strong>
          <small>${pdvNum(cancItens)} ${cancItens === 1 ? 'item' : 'itens'} · ${pdvNum(cancCupons)} ${cancCupons === 1 ? 'cupom' : 'cupons'}</small></div>
      </article>
      <article class="pdv-kpi ${alertaCaixas ? 'pdv-kpi-alerta' : ''}">
        <div class="metric-icon ${coletando === caixas.length ? 'green' : 'red'}"><i data-lucide="monitor-check"></i></div>
        <div><span>Caixas coletando</span><strong>${coletando} <em>de ${caixas.length}</em></strong>
          <small>${alertaCaixas || 'todos com vendas hoje'}</small></div>
      </article>
    </section>

    <div class="pdv-grade-2">
      <section class="panel pdv-painel">
        <div class="pdv-panel-head"><h2>Como os itens entraram no caixa</h2><small>dados do próprio PDV</small></div>
        <div class="pdv-barra" role="img" aria-label="Proporção de itens por forma de entrada">
          ${fatias.filter(f => f.n).map(f => `<span class="pdv-barra-${f.cls}" style="flex:${f.n}" title="${esc(f.rot)}: ${pdvPct(f.n, itens)}"></span>`).join('') || '<span class="pdv-barra-vazia"></span>'}
        </div>
        <table class="pdv-legenda">
          <tbody>${fatias.map(f => `<tr>
            <td><span class="pdv-legenda-cor pdv-barra-${f.cls}"></span>${f.rot}</td>
            <td class="num"><strong>${pdvNum(f.n)}</strong></td>
            <td class="num pdv-muted">${pdvPct(f.n, itens)}</td>
            <td class="num pdv-muted">${pdvMoeda(f.v)}</td></tr>`).join('')}
          </tbody>
          <tfoot><tr><td>Total</td><td class="num"><strong>${pdvNum(itens)}</strong></td><td></td>
            <td class="num"><strong>${pdvMoeda(fatias.reduce((s, f) => s + f.v, 0))}</strong></td></tr></tfoot>
        </table>
      </section>

      <section class="panel pdv-painel">
        <div class="pdv-panel-head"><h2>Ocorrências do dia</h2><small>para revisar com o vídeo</small></div>
        <ul class="pdv-ocorrencias">${ocorrencias.map(([ic, rot, qtd, sub]) => `
          <li class="${qtd ? '' : 'zero'}"><i data-lucide="${ic}"></i>
            <span>${rot}${sub ? `<small>${sub}</small>` : ''}</span><strong>${pdvNum(qtd)}</strong></li>`).join('')}
        </ul>
      </section>
    </div>

    <section class="panel pdv-painel">
      <div class="pdv-panel-head"><h2>Caixas</h2><small>saúde da coleta · também no Zabbix</small></div>
      <div class="table-wrap"><table class="data-table pdv-tabela pdv-tabela-caixas">
        <colgroup><col style="width:18%"><col style="width:16%"><col style="width:10%"><col style="width:14%"><col style="width:16%"><col style="width:12%"><col style="width:14%"></colgroup>
        <thead><tr><th>Caixa</th><th>Coletor</th><th class="num">Cupons</th><th class="num">Vendido</th><th>Última venda</th><th>Câmera</th><th></th></tr></thead>
        <tbody>${caixas.map(c => {
          const s = pdvSaudeCaixa(c);
          const pc = porCaixa[c.id] || {};
          const ultima = c.ultimo_evento && c.ultimo_evento.slice(0, 10) === _pdvDia ? pdvHaQuanto(c.ultimo_evento) : '';
          const semDado = s.cls === 'verde' && !pc.cupons;
          return `<tr>
            <td><strong>${esc(c.nome)}</strong><small class="pdv-sub">estação ${String(c.numero).padStart(3, '0')}</small></td>
            <td><span class="pdv-ponto pdv-ponto-${s.cls}"></span>${esc(s.txt)}</td>
            <td class="num">${pc.cupons ? pdvNum(pc.cupons) : '<span class="pdv-muted">0</span>'}</td>
            <td class="num">${pc.cupons ? pdvMoeda(pc.vendido_centavos) : '<span class="pdv-muted">–</span>'}</td>
            <td>${ultima ? esc(ultima) : semDado
              ? '<span class="pdv-chip pdv-sit-alerta" title="O coletor está ligado, mas nenhuma venda foi lida deste caixa hoje">nenhuma lida</span>'
              : '<span class="pdv-muted">–</span>'}</td>
            <td>${c.gravador_canal ? `canal ${c.gravador_canal} <small class="pdv-sub">relógio ${esc(pdvRelogio(c))}</small>` : '<span class="pdv-muted">sem câmera</span>'}</td>
            <td class="pdv-acao"><button class="secondary-action pdv-mini" type="button" data-pdv-vivo="${esc(c.id)}" ${c.gravador_canal ? '' : 'disabled title="Configure o gravador e o canal do caixa"'}><i data-lucide="cctv"></i> Ao vivo</button></td>
          </tr>`;
        }).join('')}</tbody>
      </table></div>
    </section>`;
  box.querySelectorAll('[data-pdv-vivo]').forEach(b => b.addEventListener('click', () => {
    _pdvVivo.caixaId = b.dataset.pdvVivo;
    document.querySelector('.nav-item[data-view="pdv-vivo"]')?.click();
  }));
  lucide.createIcons();
}

function pdvVisaoDia(delta) {
  _pdvDia = pdvMudarDia(_pdvDia || pdvHoje(), delta);
  if (_pdvDia > pdvHoje()) _pdvDia = pdvHoje();
  pdvRenderVisao();
}

// ---------------------------------------------------------------- ao vivo

async function loadPdvVivo() {
  pdvParar();
  const caixas = await pdvCarregarCaixas();
  if (!caixas.length) { pdvSemCaixa('pdvVivoBody'); return; }
  const foco = _pdvVivo.pedidoFoco;
  _pdvVivo.pedidoFoco = '';
  if (foco && caixas.some(c => c.id === foco)) {
    _pdvVivo.modo = 'foco';
    _pdvVivo.caixaId = foco;
    pdvRenderVivo();
    return;
  }
  _pdvVivo.modo = 'parede';
  await pdvRenderParede();
}

// ---- parede: todos os caixas da loja, video leve (SD) em cada um
const PDV_PAREDE_MAX_VIDEOS = 8;  // mais que isso pesa no link da loja: os outros ficam so com o cupom
const PDV_TILE_CLS = { em_venda: 'pdv-v-venda', parado: 'pdv-v-parado', sem_coletor: 'pdv-v-sem', livre: 'pdv-v-livre', desligado: 'pdv-v-livre' };

function pdvParedeUrl() {
  return `/api/pdv/ao-vivo-loja?loja=${encodeURIComponent(_pdvVivo.loja || '')}`;
}

async function pdvRenderParede() {
  const box = document.getElementById('pdvVivoBody');
  if (!box) return;
  const r = await apiJson(pdvParedeUrl(), { forceRefresh: true });
  if (!r?.loja) { box.innerHTML = '<p class="pdv-nota">Não foi possível carregar os caixas agora.</p>'; return; }
  _pdvVivo.loja = r.loja.nome;
  const cad = new Map(_pdvCaixas.map(c => [c.id, c]));
  const kpi = (id, rot, cls = '') => `<section class="pdv-l-card pdv-l-s3"><div class="pdv-l-stat" id="${id}">
    <span class="pdv-l-k ${cls}">${rot}</span><strong class="pdv-l-big">–</strong><span class="pdv-l-sub">&nbsp;</span></div></section>`;
  const tile = (c, i) => {
    const temVideo = cad.get(c.id)?.gravador_host && cad.get(c.id)?.gravador_canal;
    return `
      <article class="pdv-v-tile pdv-l-s3" id="pdvVt-${esc(c.id)}" data-pdv-foco="${esc(c.id)}">
        <div class="pdv-v-video">
          ${temVideo && i < PDV_PAREDE_MAX_VIDEOS ? `<video id="pdvVv-${esc(c.id)}" autoplay muted playsinline></video>` : ''}
          <span class="pdv-v-aviso" data-aviso>${temVideo ? (i < PDV_PAREDE_MAX_VIDEOS ? 'Conectando...' : 'vídeo no foco do caixa') : 'sem câmera configurada'}</span>
          <span class="pdv-v-lbl pdv-v-nome">${esc(c.nome)}</span>
          <span class="pdv-v-lbl pdv-v-sit" data-sit></span>
          <span class="pdv-v-lbl pdv-v-ultimo" data-ultimo hidden></span>
        </div>
        <div class="pdv-v-corpo">
          <div class="pdv-l-head"><strong class="pdv-v-op" data-op>–</strong>
            <button type="button" class="pdv-l-link" data-pdv-abrir="${esc(c.id)}" aria-label="Abrir ${esc(c.nome)} em tela grande">abrir</button></div>
          <div class="pdv-v-linhas" data-linhas></div>
          <div class="pdv-l-head pdv-v-pe"><span class="pdv-l-sub" data-rodape></span><strong class="pdv-v-total" data-total></strong></div>
        </div>
      </article>`;
  };
  box.innerHTML = `
    <div class="pdv-l-grade pdv-v-grade">
      ${kpi('pdvVkVendido', 'Vendido hoje')}${kpi('pdvVkCupons', 'Cupons')}${kpi('pdvVkBip', 'Bipados')}${kpi('pdvVkRev', 'Para revisar', 'pdv-l-k-ambar')}
      <div class="pdv-l-s12 pdv-l-head pdv-l-secao">
        <h2 class="pdv-l-h2">Caixas</h2>
        <div class="pdv-l-legenda pdv-l-sub">
          <span><i class="pdv-cx-venda"></i>em venda</span><span><i class="pdv-cx-livre"></i>livre</span>
          <span><i class="pdv-cx-parado"></i>sem venda há mais de 1 h</span><span><i class="pdv-cx-sem"></i>sem coletor</span>
          ${r.lojas.length > 1 ? `<label class="pdv-v-loja">Loja <select id="pdvVivoLoja">${r.lojas.map(n =>
            `<option value="${esc(n)}" ${n === r.loja.nome ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>` : ''}
        </div>
      </div>
      <aside class="pdv-l-card pdv-v-lado pdv-l-agora" aria-label="Acontecendo agora na loja">
        <div class="pdv-l-head pdv-l-agora-topo"><h2 class="pdv-l-h2">Acontecendo agora</h2><span class="pdv-l-sub">da loja</span></div>
        <div id="pdvVtAlertas"></div>
        <div class="pdv-l-agora-pe"><button type="button" class="pdv-l-link" data-pdv-cupons>Ver os cupons</button></div>
      </aside>
      ${r.caixas.map(tile).join('')}
    </div>
    <p class="pdv-nota">O vídeo sai do gravador pelo conector da loja, como as outras câmeras do SightOps; aqui vai leve (SD). Clique num caixa para ver grande, em HD, com o cupom ao lado.</p>`;

  document.getElementById('pdvVivoLoja')?.addEventListener('change', ev => {
    pdvParar();
    _pdvVivo.loja = ev.target.value;
    pdvRenderParede();
  });
  box.querySelector('[data-pdv-cupons]')?.addEventListener('click', () => document.querySelector('.nav-item[data-view="pdv-cupons"]')?.click());
  const abrir = id => { pdvParar(); _pdvVivo.modo = 'foco'; _pdvVivo.caixaId = id; pdvRenderVivo(); };
  box.querySelectorAll('[data-pdv-foco]').forEach(el => el.addEventListener('click', ev => {
    if (ev.target.closest('button,a,select,video[controls]')) return;
    abrir(el.dataset.pdvFoco);
  }));
  box.querySelectorAll('[data-pdv-abrir]').forEach(b => b.addEventListener('click', () => abrir(b.dataset.pdvAbrir)));
  box.addEventListener('click', ev => {
    const b = ev.target.closest('[data-pdv-cupom]');
    if (b) pdvIrCupom(b.dataset.pdvCaixa, b.dataset.pdvDia || pdvHoje(), b.dataset.pdvCupom);
  });

  // video leve de cada caixa, pelo mesmo caminho do ao vivo de gravador do SightOps
  r.caixas.slice(0, PDV_PAREDE_MAX_VIDEOS).forEach(c => {
    const x = cad.get(c.id);
    const video = document.getElementById(`pdvVv-${c.id}`);
    if (!x || !video || typeof mountLiveStream !== 'function') return;
    const aviso = () => document.querySelector(`#pdvVt-${CSS.escape(c.id)} [data-aviso]`);
    _pdvVivo.parede.set(c.id, mountLiveStream(video, {
      ip: x.gravador_host, user: 'admin', pass: '', subtype: 1, connectorId: x.connector_id,
      registrar: async () => {
        const res = await api('/api/deployments/recorder-live-stream', {
          method: 'POST',
          body: JSON.stringify({ recorder_host: x.gravador_host, canal: Number(x.gravador_canal), connector_id: x.connector_id, alta: 0 }),
        });
        const j = await res?.json().catch(() => ({}));
        if (res?.status === 428) throw new Error('gravador sem senha guardada');
        if (res?.status === 403) throw new Error('gravador de loja que você não acessa');
        if (!res?.ok || !j?.stream_name) throw new Error(j?.detail || 'não consegui abrir o vídeo');
        return j.stream_name;
      },
      onStatus: texto => { const a = aviso(); if (a) { a.hidden = !texto; if (texto) a.textContent = texto; } },
    }));
  });

  pdvPintarParede(r);
  _pdvVivo.timer = setInterval(async () => {
    if (!pdvVisivel('viewPdvVivo') || _pdvVivo.modo !== 'parede') { pdvParar(); return; }
    const r2 = await apiJson(pdvParedeUrl(), { forceRefresh: true });
    if (r2?.loja && r2.loja.nome === _pdvVivo.loja && _pdvVivo.modo === 'parede') pdvPintarParede(r2);
  }, 3000);
}

// so troca textos e classes: os videos continuam tocando
function pdvPintarParede(r) {
  const l = r.loja;
  setText('pdvVivoSub', `${l.nome} · ${pdvPlural(l.n_caixas, 'caixa')} · ${l.coletando} coletando`);
  const pinta = (id, big, sub) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector('.pdv-l-big').innerHTML = big;
    const s = el.querySelector('.pdv-l-sub');
    s.innerHTML = sub;
    s.title = s.textContent;
  };
  const ticket = l.cupons ? l.vendido_centavos / l.cupons : 0;
  pinta('pdvVkVendido', pdvMoeda(l.vendido_centavos), `até ${new Date().toTimeString().slice(0, 5)}`);
  pinta('pdvVkCupons', pdvNum(l.cupons), `ticket médio ${pdvMoeda(ticket)}`);
  pinta('pdvVkBip', pdvPct(l.bipados, l.itens), `${pdvNum(l.itens)} itens passados`);
  pinta('pdvVkRev', pdvNum(l.revisar), `${pdvNum(l.cancelados)} cancelados · ${pdvNum(l.sem_cadastro)} sem cadastro`);

  (r.caixas || []).forEach(c => {
    const t = document.getElementById(`pdvVt-${c.id}`);
    if (!t) return;
    Object.values(PDV_TILE_CLS).forEach(k => t.classList.remove(k));
    t.classList.add(PDV_TILE_CLS[c.estado] || 'pdv-v-livre');
    const k = c.cupom || {};
    const sit = { em_venda: 'em venda', livre: 'livre', parado: `sem venda há ${c.parado_min || 60} min`,
      sem_coletor: 'sem coletor', desligado: 'desligado' }[c.estado] || '–';
    const q = sel => t.querySelector(sel);
    q('[data-sit]').textContent = sit;
    q('[data-op]').textContent = k.operador || c.operador || 'sem operador';
    const ult = (c.ultimos || [])[0];
    q('[data-ultimo]').hidden = !ult;
    if (ult) q('[data-ultimo]').innerHTML = `<span>${esc(ult.descricao || '')}</span><b>${esc(pdvMoeda(ult.valor_centavos))}</b>`;
    const linha = (h, txt, v = '', cls = '') => `<div class="pdv-v-ln ${cls}"><span>${esc(h)}</span><span title="${esc(txt)}">${esc(txt)}</span><span>${esc(v)}</span></div>`;
    let linhas;
    if (k.aberto) {
      linhas = (c.ultimos || []).map(i => linha(pdvHora(i.ts), `${i.descricao || ''}${i.modo === 'manual' ? ' · digitado' : ''}`,
        pdvMoeda(i.valor_centavos), i.modo === 'manual' ? 'pdv-v-dig' : ''));
      while (linhas.length < 2) linhas.push(linha('', ''));
      q('[data-rodape]').textContent = `cupom ${k.cupom} · ${pdvNum(k.itens)} ${Number(k.itens) === 1 ? 'item' : 'itens'}`;
      q('[data-total]').textContent = pdvMoeda(k.total_centavos);
      q('[data-total]').classList.remove('pdv-v-apagado');
    } else {
      const quando = k.fechado_em ? pdvHora(k.fechado_em).slice(0, 5) : '';
      linhas = [
        linha(quando, k.cupom ? 'Última venda' : 'Nenhuma venda hoje', k.cupom ? pdvMoeda(k.total_centavos) : ''),
        linha('', { livre: k.fechado_em ? `Caixa livre ${pdvHaQuanto(k.fechado_em)}` : 'Caixa livre', parado: 'Parado com a loja aberta',
          sem_coletor: 'Coletor sem resposta', desligado: 'Desligado no cadastro' }[c.estado] || '',
          '', c.estado === 'parado' ? 'pdv-v-dig' : (c.estado === 'sem_coletor' ? 'pdv-v-ruim' : '')),
      ];
      q('[data-rodape]').textContent = `${pdvNum(c.cupons)} ${Number(c.cupons) === 1 ? 'cupom' : 'cupons'} hoje`;
      q('[data-total]').textContent = pdvMoeda(c.vendido_centavos);
      q('[data-total]').classList.add('pdv-v-apagado');
    }
    q('[data-linhas]').innerHTML = linhas.join('');
  });

  const alvo = document.getElementById('pdvVtAlertas');
  if (alvo) {
    alvo.innerHTML = (r.alertas || []).slice(0, 7).map(a => {
      const [txt, cor] = pdvAlertaTexto(a);
      return `<div class="pdv-l-alerta"><i class="${cor}" aria-hidden="true"></i>
        <div class="pdv-l-stat"><span class="pdv-l-sub pdv-l-uma">${esc(pdvHora(a.ts))} · <strong>${esc(a.caixa)}</strong></span>
          <span class="pdv-l-txt" title="${esc(txt)}">${esc(txt)}</span></div>
        <button type="button" class="pdv-l-link" data-pdv-cupom="${esc(a.cupom || '')}" data-pdv-caixa="${esc(a.caixa_id)}"
          data-pdv-dia="${esc(String(a.ts || '').slice(0, 10))}" title="Abrir o cupom, com os itens e o vídeo">abrir</button></div>`;
    }).join('') || '<p class="pdv-l-sub pdv-l-vazio">Nada fora do normal hoje.</p>';
  }
}

function pdvRenderVivo() {
  const box = document.getElementById('pdvVivoBody');
  const c = _pdvCaixas.find(x => x.id === _pdvVivo.caixaId);
  if (!box || !c) return;
  box.innerHTML = `
    <div class="pdv-v-voltar"><button type="button" class="secondary-action" data-pdv-parede><i data-lucide="layout-grid"></i> Todos os caixas da loja</button></div>
    <div class="pdv-vivo">
      <section class="pdv-palco">
        <video id="pdvVivoVideo" autoplay muted playsinline></video>
        <div class="pdv-palco-topo">
          <div><span class="pdv-selo-vivo"><span></span>Ao vivo</span><strong>${esc(c.nome)}</strong></div>
          <span class="pdv-palco-info">${c.gravador_host ? `canal ${c.gravador_canal} ·
            <button type="button" class="pdv-qualidade" id="pdvVivoQualidade" title="SD é leve; HD pesa mais no link da loja">${_pdvVivo.alta ? 'HD' : 'SD'}</button>` : ''}</span>
        </div>
        <div class="pdv-palco-aviso" id="pdvVivoAviso">${c.gravador_host && c.gravador_canal ? 'Conectando...' : 'Este caixa ainda não tem gravador e canal configurados.'}</div>
        <div class="pdv-palco-osd" id="pdvVivoOsd" hidden></div>
      </section>
      <aside class="panel pdv-painel pdv-cupom-vivo" id="pdvCupomVivo"><p class="pdv-nota">Carregando o cupom...</p></aside>
    </div>
    <section class="pdv-miniaturas">${_pdvCaixas.map(x => {
      const s = pdvSaudeCaixa(x);
      return `<button type="button" class="pdv-miniatura ${x.id === c.id ? 'ativa' : ''}" data-pdv-caixa="${esc(x.id)}">
        <strong>${esc(x.nome)}</strong><span><span class="pdv-ponto pdv-ponto-${s.cls}"></span>${esc(s.txt)}</span>
      </button>`;
    }).join('')}</section>
    <p class="pdv-nota">O vídeo sai do gravador pelo conector da loja, como as outras câmeras do SightOps. O caixa não transmite vídeo.</p>`;
  box.querySelector('[data-pdv-parede]')?.addEventListener('click', () => {
    pdvParar();
    _pdvVivo.modo = 'parede';
    _pdvVivo.loja = (c.site || '').trim() || _pdvVivo.loja;
    pdvRenderParede();
  });
  document.getElementById('pdvVivoQualidade')?.addEventListener('click', () => {
    pdvParar();
    _pdvVivo.alta = !_pdvVivo.alta;
    pdvRenderVivo();
  });
  box.querySelectorAll('[data-pdv-caixa]').forEach(b => b.addEventListener('click', () => {
    pdvParar();
    _pdvVivo.caixaId = b.dataset.pdvCaixa;
    pdvRenderVivo();
  }));
  lucide.createIcons();

  if (c.gravador_host && c.gravador_canal && typeof mountLiveStream === 'function') {
    const video = document.getElementById('pdvVivoVideo');
    _pdvVivo.handle = mountLiveStream(video, {
      ip: c.gravador_host, user: 'admin', pass: '', subtype: _pdvVivo.alta ? 0 : 1, connectorId: c.connector_id,
      registrar: async () => {
        const res = await api('/api/deployments/recorder-live-stream', {
          method: 'POST',
          body: JSON.stringify({ recorder_host: c.gravador_host, canal: Number(c.gravador_canal), connector_id: c.connector_id, alta: _pdvVivo.alta ? 1 : 0 }),
        });
        const r = await res?.json().catch(() => ({}));
        if (res?.status === 428) throw new Error('Este gravador não tem senha guardada.');
        if (!res?.ok || !r?.stream_name) throw new Error(r?.detail || 'não consegui preparar o vídeo');
        return r.stream_name;
      },
      onStatus: texto => {
        const aviso = document.getElementById('pdvVivoAviso');
        if (aviso) { aviso.hidden = !texto; if (texto) aviso.textContent = texto; }
      },
    });
  }
  pdvAtualizarCupomVivo();
  _pdvVivo.timer = setInterval(() => {
    if (!pdvVisivel('viewPdvVivo')) { pdvParar(); return; }
    pdvAtualizarCupomVivo();
  }, 2000);
}

async function pdvAtualizarCupomVivo() {
  const caixaId = _pdvVivo.caixaId;
  const r = await apiJson(`/api/pdv/ao-vivo/${encodeURIComponent(caixaId)}`, { forceRefresh: true });
  const box = document.getElementById('pdvCupomVivo');
  if (!box || caixaId !== _pdvVivo.caixaId) return;
  const k = r?.cupom;
  if (!k) { box.innerHTML = '<p class="pdv-nota">Nenhuma venda recebida deste caixa ainda.</p>'; return; }
  const itens = r.itens || [];
  const osd = document.getElementById('pdvVivoOsd');
  if (osd && itens[0]) {
    osd.hidden = false;
    osd.innerHTML = `<span>CUPOM ${esc(k.cupom)}</span>${esc(itens[0].descricao || '')} ${esc(pdvMoeda(itens[0].valor_centavos))}`;
  }
  const cancel = new Set((r.cancelados || []).map(x => `${x.codigo}`));
  box.innerHTML = `
    <div class="pdv-cupom-topo">
      <div><small>${k.situacao === 'aberto' ? 'Cupom em andamento' : 'Último cupom'}</small><strong>${esc(k.cupom)}</strong>
        <span>aberto ${esc(pdvHora(k.aberto_em))} · ${esc(k.operador || '-')}</span></div>
      ${pdvChip(PDV_SITUACAO, k.situacao)}
    </div>
    <div class="pdv-cupom-itens">${itens.map(i => `
      <div class="pdv-cupom-item">
        <span class="pdv-hora">${esc(pdvHora(i.ts))}</span>
        <div><strong>${esc(i.descricao || i.codigo)}</strong>${pdvChip(PDV_MODOS, i.modo)}${i.provisorio ? ' <small class="pdv-muted" title="classificação ainda sendo confirmada pelo Teclas">…</small>' : ''}</div>
        <strong class="pdv-valor">${esc(pdvMoeda(i.valor_centavos))}</strong>
      </div>`).join('') || '<p class="pdv-nota">Cupom aberto, nenhum item ainda.</p>'}</div>
    <div class="pdv-cupom-total"><span>${pdvNum(k.itens)} itens${k.itens_cancelados ? ` · ${k.itens_cancelados} cancelado${k.itens_cancelados > 1 ? 's' : ''}` : ''}</span>
      <strong>${esc(pdvMoeda(k.total_centavos))}</strong></div>
    ${k.itens_cancelados ? `<div class="pdv-aviso">Item cancelado neste cupom${cancel.size ? '' : ''}. Fica disponível para revisão com o vídeo.</div>` : ''}`;
}

// ---------------------------------------------------------------- cupons

async function loadPdvCupons() {
  pdvParar();
  const pedido = _pdvAbrirDepois;  // veio de outra tela (Lojas) para abrir um cupom
  _pdvAbrirDepois = null;
  const caixas = await pdvCarregarCaixas();
  const sel = document.getElementById('pdvCupFiltroCaixa');
  if (sel) {
    const atual = pedido ? pedido.caixaId : sel.value;
    sel.innerHTML = '<option value="">Todos os caixas</option>' + caixas.map(c => `<option value="${esc(c.id)}">${esc(c.nome)}</option>`).join('');
    sel.value = atual;
  }
  const dia = document.getElementById('pdvCupFiltroDia');
  if (dia && pedido) dia.value = pedido.dia;
  if (dia && !dia.value) dia.value = pdvHoje();
  if (!caixas.length) { pdvSemCaixa('pdvCuponsBody'); return; }
  await pdvBuscarCupons();
  if (pedido?.cupom) pdvAbrirCupom(pedido.caixaId, pedido.dia, pedido.cupom);
}

let _pdvAbrirDepois = null;

function pdvIrCupom(caixaId, dia, cupom) {
  _pdvAbrirDepois = { caixaId, dia, cupom };
  document.querySelector('.nav-item[data-view="pdv-cupons"]')?.click();
}

async function pdvBuscarCupons() {
  const v = id => encodeURIComponent(document.getElementById(id)?.value || '');
  const q = `dia=${v('pdvCupFiltroDia')}&caixa_id=${v('pdvCupFiltroCaixa')}&situacao=${v('pdvCupFiltroSituacao')}`
    + `&texto=${v('pdvCupFiltroBusca')}&de=${v('pdvCupFiltroDe')}&ate=${v('pdvCupFiltroAte')}`;
  const box = document.getElementById('pdvCuponsBody');
  if (!box) return;
  box.innerHTML = '<p class="pdv-nota">Buscando...</p>';
  const r = await apiJson(`/api/pdv/cupons?${q}`, { forceRefresh: true });
  const cupons = r?.cupons || [];
  box.innerHTML = cupons.length ? `
    <div class="table-wrap"><table class="data-table pdv-tabela">
      <thead><tr><th>Hora</th><th>Caixa</th><th>Cupom</th><th>Operador</th><th class="num">Itens</th><th>Entrada</th>
        <th>Pagamento</th><th class="num">Total</th><th>Situação</th></tr></thead>
      <tbody>${cupons.map(k => `
        <tr class="pdv-linha-clicavel" data-pdv-cupom="${esc(k.caixa_id)}|${esc(k.dia)}|${esc(k.cupom)}">
          <td>${esc(pdvHora(k.aberto_em).slice(0, 5))}</td><td>${esc(k.caixa)}</td><td><strong>${esc(k.cupom)}</strong></td>
          <td>${esc(k.operador)}</td><td class="num">${pdvNum(k.itens)}</td>
          <td class="pdv-muted">${pdvPlural(k.bipados, 'bipado')}${k.digitados ? ` · ${pdvPlural(k.digitados, 'digitado')}` : ''}${k.menu ? ` · ${k.menu} menu` : ''}</td>
          <td>${esc(k.pagamento || '-')}</td><td class="num"><strong>${esc(pdvMoeda(k.total_centavos))}</strong></td>
          <td>${pdvChip(PDV_SITUACAO, k.situacao)}${k.itens_cancelados ? ` <span class="pdv-chip pdv-sit-alerta">${k.itens_cancelados} item canc.</span>` : ''}</td>
        </tr>`).join('')}</tbody>
    </table></div>
    <p class="pdv-nota">${cupons.length} cupons${cupons.length >= 200 ? ' (mostrando os 200 mais recentes; filtre por horário)' : ''}.</p>
    <div id="pdvCupomDetalhe"></div>`
    : '<p class="pdv-nota">Nenhum cupom com esses filtros.</p>';
  box.querySelectorAll('[data-pdv-cupom]').forEach(tr => tr.addEventListener('click', () => {
    box.querySelectorAll('.pdv-linha-clicavel').forEach(x => x.classList.toggle('ativa', x === tr));
    pdvAbrirCupom(...tr.dataset.pdvCupom.split('|'));
  }));
}

async function pdvAbrirCupom(caixaId, dia, cupom) {
  const box = document.getElementById('pdvCupomDetalhe');
  if (!box) return;
  box.innerHTML = '<p class="pdv-nota">Abrindo o cupom...</p>';
  const r = await apiJson(`/api/pdv/cupons/${encodeURIComponent(caixaId)}/${dia}/${encodeURIComponent(cupom)}`, { forceRefresh: true });
  if (!r?.cupom) { box.innerHTML = '<p class="pdv-nota">Não consegui abrir o cupom.</p>'; return; }
  const k = r.cupom;
  box.innerHTML = `
    <section class="panel pdv-painel pdv-detalhe">
      <div class="pdv-panel-head">
        <div><h2>Cupom ${esc(k.cupom)} · ${esc(r.caixa.nome)} · ${esc(k.operador)}</h2>
          <small>aberto ${esc(pdvHora(k.aberto_em))}${k.fechado_em ? ` · ${k.situacao === 'cancelado' ? 'cancelado' : 'fechado'} ${esc(pdvHora(k.fechado_em))}` : ''} · ${esc(k.pagamento || 'sem pagamento')}</small></div>
        <button class="secondary-action" type="button" data-pdv-video="${esc(k.aberto_em)}"><i data-lucide="video"></i> Ver vídeo do cupom</button>
      </div>
      <div id="pdvVideoBox"></div>
      <div class="pdv-detalhe-grade">
        <div class="table-wrap"><table class="data-table pdv-tabela">
          <thead><tr><th>Hora</th><th>Código</th><th>Produto</th><th class="num">Qtd</th><th class="num">Valor</th><th>Como entrou</th><th></th></tr></thead>
          <tbody>${(r.itens || []).map(i => `<tr>
            <td>${esc(pdvHora(i.ts))}</td><td>${esc(i.codigo)}</td><td>${esc(i.descricao)}</td><td class="num">${esc(i.quant)}</td>
            <td class="num">${esc(pdvMoeda(i.valor_centavos))}</td><td>${pdvChip(PDV_MODOS, i.modo)}</td>
            <td><button class="secondary-action pdv-mini" type="button" data-pdv-video="${esc(i.ts)}" title="Vídeo deste item"><i data-lucide="video"></i></button></td>
          </tr>`).join('')}</tbody>
        </table></div>
        <div class="pdv-linha-tempo">
          <h3>Linha do tempo do caixa</h3>
          ${(r.linha_do_tempo || []).map(e => `<div class="pdv-evento pdv-ev-${esc(e.tipo)}">
            <span class="pdv-hora">${esc(pdvHora(e.ts))}</span><span>${esc(pdvEventoTexto(e))}</span></div>`).join('')}
        </div>
      </div>
    </section>`;
  box.querySelectorAll('[data-pdv-video]').forEach(b => b.addEventListener('click', () => pdvVerVideo(caixaId, b.dataset.pdvVideo)));
  lucide.createIcons();
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

const PDV_EVENTO_NOME = {
  ABRECUPOM: 'Cupom aberto', VIT: 'Item', CIT: 'Item cancelado', SBT: 'Subtotal', FIN: 'Pagamento',
  TRC: 'Troco', FECHACUPOM: 'Cupom fechado', CCV: 'Cupom cancelado', CCG: 'Cancelamento de cupom anterior',
  SUP: 'Liberação de supervisor', SUPERVISOR: 'Supervisor', GER: 'Tecla de gerente', GAV: 'Gaveta aberta',
  SGR: 'Sangria', DIT: 'Desconto no item', DST: 'Desconto no subtotal', DAS: 'Desconto retirado',
  MTP: 'Multiplicação', ITEMSEMCAD: 'Código sem cadastro', CSP: 'Consulta de preço', CLIENTE: 'Cliente identificado',
  VENDACF: 'Início da venda', EOP: 'Entrada do operador', SOP: 'Saída do operador',
};

function pdvEventoTexto(e) {
  const nome = PDV_EVENTO_NOME[e.tipo] || e.tipo;
  const valor = e.valor_centavos ? ` · ${pdvMoeda(e.valor_centavos)}` : '';
  const desc = ['VIT', 'CIT', 'FIN', 'DIT', 'SUPERVISOR', 'ITEMSEMCAD'].includes(e.tipo) ? ` · ${e.descricao || e.codigo || ''}` : '';
  return `${nome}${desc}${valor}`;
}

// Video do cupom/item: a GRAVACAO toca no player padrao do SightOps (o mesmo
// do ao vivo), pelo /api/nvr/driver/playback -- igual a Gravacoes e a
// Investigacao. Comeca na hora, sem baixar arquivo, e a rota ja confere que o
// gravador e do cliente e de site que a pessoa acessa. Do PDV so sai o horario
// ja no relogio do gravador (/api/pdv/video).
let _pdvGravacao = null;
let _pdvGravacaoTimer = null;

function pdvPararGravacao() {
  if (_pdvGravacaoTimer) { clearInterval(_pdvGravacaoTimer); _pdvGravacaoTimer = null; }
  if (_pdvGravacao) { try { _pdvGravacao.stop(); } catch (_) {} _pdvGravacao = null; }
}

async function pdvVerVideo(caixaId, ts) {
  const box = document.getElementById('pdvVideoBox');
  if (!box) return;
  pdvPararGravacao();
  box.innerHTML = '<p class="pdv-nota">Calculando o horário no gravador...</p>';
  const j = await apiJson(`/api/pdv/video/${encodeURIComponent(caixaId)}?ts=${encodeURIComponent(ts)}&antes=15&depois=45`, { forceRefresh: true });
  if (!j?.host) { box.innerHTML = '<p class="pdv-nota pdv-erro">Este caixa ainda não tem gravador e canal configurados.</p>'; return; }
  const aviso = j.relogio_medido ? `gravador ${j.gravador_menos_caixa_s >= 0 ? '+' : ''}${j.gravador_menos_caixa_s} s em relação ao caixa`
    : 'relógio do gravador ainda não medido: o vídeo pode estar alguns segundos deslocado';
  box.innerHTML = `
    <div class="pdv-gravacao">
      <video id="pdvGravVideo" class="pdv-video" autoplay muted playsinline controls></video>
      <p class="pdv-nota" id="pdvGravAviso">Abrindo a gravação do gravador...</p>
    </div>
    <p class="pdv-nota">Começa às ${esc(j.inicio.slice(11))} no gravador, 15 s antes do momento (caixa ${esc(j.momento_caixa.slice(11))} · gravador ${esc(j.momento_gravador.slice(11))}) · ${esc(aviso)}.</p>`;
  const video = document.getElementById('pdvGravVideo');
  if (!video || typeof mountLiveStream !== 'function') return;
  _pdvGravacao = mountLiveStream(video, {
    registrar: async () => {
      const res = await api('/api/nvr/driver/playback', {
        method: 'POST', body: JSON.stringify({ host: j.host, http_port: 80, canal: j.canal, inicio: j.inicio, connector_id: j.connector_id }),
      });
      const r = await res?.json().catch(() => ({}));
      if (res?.status === 428) throw new Error('O gravador não tem senha guardada no SightOps.');
      if (res?.status === 403) throw new Error('Este gravador é de uma loja que você não acessa.');
      if (!res?.ok || !r?.stream_name) throw new Error(r?.detail || 'Não consegui abrir a gravação.');
      return r.stream_name;
    },
    onStatus: texto => {
      const a = document.getElementById('pdvGravAviso');
      if (!a) return;
      a.hidden = !texto;
      if (texto) a.textContent = texto;
    },
  });
  // saiu da tela (ou o cupom foi trocado): para de puxar video pelo link da loja
  _pdvGravacaoTimer = setInterval(() => {
    if (!pdvVisivel('viewPdvCupons') || !document.getElementById('pdvGravVideo')) pdvPararGravacao();
  }, 2000);
}

// ---------------------------------------------------------------- configuracoes

let _pdvConectores = [];

function pdvOpcoesConector(sel) {
  return '<option value="">Sem conector</option>' + _pdvConectores.map(c =>
    `<option value="${esc(c.id)}" ${c.id === sel ? 'selected' : ''}>${esc(c.name || c.id)}</option>`).join('');
}

function pdvCamposCaixa(c) {
  return `
      <label>Nome<input name="nome" required maxlength="60" placeholder="PDV 01" value="${esc(c?.nome || '')}"></label>
      <label>Estação<input name="numero" type="number" min="1" max="999" value="${esc(c?.numero || 1)}" title="O .NNN do arquivo do PDV (Espiao271026.001 = 1)"></label>
      <label>Loja<input name="site" maxlength="120" list="pdvSitesLista" placeholder="Escolha ou digite o nome da loja" value="${esc(c?.site || '')}"
        title="Os caixas com a mesma loja aparecem juntos em Ponto de venda › Lojas"></label>
      <label>Conector da loja<select name="connector_id">${pdvOpcoesConector(c?.connector_id || '')}</select></label>
      <label>Gravador (IP na loja)<input name="gravador_host" maxlength="120" placeholder="192.168.24.227" value="${esc(c?.gravador_host || '')}"></label>
      <label>Canal da câmera do caixa<input name="gravador_canal" type="number" min="0" max="256" value="${esc(c?.gravador_canal || 0)}"></label>`;
}

async function pdvSalvarCaixa(form) {
  const dados = Object.fromEntries(new FormData(form).entries());
  const res = await api('/api/pdv/caixas', { method: 'POST', body: JSON.stringify(dados) });
  const r = await res?.json().catch(() => ({}));
  if (!res?.ok) { showToast(r?.detail || 'Não consegui salvar o caixa.', true); return null; }
  return r.caixa;
}

async function loadPdvConfig(abrirId = '') {
  const box = document.getElementById('pdvConfigBody');
  if (!box) return;
  const [caixas, con] = await Promise.all([pdvCarregarCaixas(), apiJson('/api/connectors', { forceRefresh: true })]);
  _pdvConectores = con?.connectors || con?.items || [];
  box.innerHTML = `
    <datalist id="pdvSitesLista">${_pdvSites.map(s => `<option value="${esc(s)}"></option>`).join('')}</datalist>
    <div class="table-wrap"><table class="data-table pdv-tabela pdv-tabela-config">
      <thead><tr><th>Caixa</th><th>Gravador e canal</th><th>Coletor</th><th>Relógio</th><th>Instalação</th><th></th></tr></thead>
      <tbody>${caixas.map(c => {
        const s = pdvSaudeCaixa(c);
        return `<tr>
          <td><strong>${esc(c.nome)}</strong><small class="pdv-muted"> · estação ${String(c.numero).padStart(3, '0')}</small></td>
          <td>${c.gravador_host ? `${esc(c.gravador_host)} · canal ${c.gravador_canal}` : '-'}</td>
          <td><span class="pdv-ponto pdv-ponto-${s.cls}"></span>${esc(s.txt)}${c.coletor_versao ? ` <small class="pdv-muted">v${esc(c.coletor_versao)}</small>` : ''}</td>
          <td>${esc(pdvRelogio(c))}</td>
          <td>${pdvInstalacaoTxt(c)}</td>
          <td><div class="pdv-acoes">
            <button class="primary-action pdv-mini" type="button" data-pdv-abrir="${esc(c.id)}"><i data-lucide="pencil"></i> Editar e instalar</button>
            <button class="secondary-action pdv-mini" type="button" data-pdv-relogio="${esc(c.id)}">Medir relógio</button>
          </div></td></tr>`;
      }).join('') || '<tr><td colspan="6" class="pdv-muted">Nenhum caixa cadastrado.</td></tr>'}</tbody>
    </table></div>
    <div id="pdvCaixaPainel"></div>
    <form class="pdv-form" id="pdvCaixaNovo" autocomplete="off">
      <h3>Adicionar caixa</h3>
      ${pdvCamposCaixa(null)}
      <div class="pdv-form-acoes"><button class="primary-action" type="submit">Adicionar caixa</button></div>
    </form>
    <p class="pdv-nota">Cada caixa conta como 1 equipamento na licença. Monitorar operador exige ciência por escrito dos funcionários.</p>`;

  document.getElementById('pdvCaixaNovo').addEventListener('submit', async ev => {
    ev.preventDefault();
    const novo = await pdvSalvarCaixa(ev.currentTarget);
    if (!novo) return;
    showToast('Caixa adicionado. Agora informe o acesso ao caixa para instalar o coletor.');
    loadPdvConfig(novo.id);
  });
  box.querySelectorAll('[data-pdv-abrir]').forEach(b => b.addEventListener('click', () => pdvAbrirCaixa(b.dataset.pdvAbrir)));
  box.querySelectorAll('[data-pdv-relogio]').forEach(b => b.addEventListener('click', async () => {
    b.disabled = true;
    const res = await api(`/api/pdv/relogio/${encodeURIComponent(b.dataset.pdvRelogio)}`, { method: 'POST', body: '{}' });
    const r = await res?.json().catch(() => ({}));
    b.disabled = false;
    if (!res?.ok) { showToast(r?.detail || 'Não consegui ler o relógio do gravador.', true); return; }
    showToast(`Gravador ${r.gravador_menos_caixa_s >= 0 ? '+' : ''}${r.gravador_menos_caixa_s} s em relação ao caixa. Nada foi alterado no gravador.`);
    loadPdvConfig();
  }));
  lucide.createIcons();
  if (abrirId) pdvAbrirCaixa(abrirId);
}

function pdvInstalacaoTxt(c) {
  if (c.instalacao_estado === 'instalado') return `<span class="pdv-chip pdv-sit-ok">instalado</span> <small class="pdv-muted">${esc((c.instalacao_em || '').slice(0, 10).split('-').reverse().join('/'))}</small>`;
  if (c.instalacao_estado === 'falhou') return '<span class="pdv-chip pdv-sit-cancelado">falhou</span>';
  return c.pdv_host ? `<small class="pdv-muted">${esc(c.pdv_host)}</small>` : '<small class="pdv-muted">não instalado</small>';
}

// Um painel por caixa: dados, acesso pelo tunel (instalar / status) e excluir.
// A instalacao e feita PELO SightOps, pelo IP virtual do conector -- nunca pelo
// IP publico da loja.
function pdvAbrirCaixa(caixaId) {
  const c = _pdvCaixas.find(x => x.id === caixaId);
  const box = document.getElementById('pdvCaixaPainel');
  if (!c || !box) return;
  box.innerHTML = `
    <section class="pdv-caixa-painel">
      <div class="pdv-panel-head">
        <h2>${esc(c.nome)}</h2>
        <button class="secondary-action pdv-mini" type="button" id="pdvPainelFechar">Fechar</button>
      </div>

      <form class="pdv-form" id="pdvDadosForm" autocomplete="off">
        <h3>Dados do caixa</h3>
        <input type="hidden" name="id" value="${esc(c.id)}">
        ${pdvCamposCaixa(c)}
        <div class="pdv-form-acoes"><button class="primary-action" type="submit">Salvar dados</button></div>
      </form>

      <form class="pdv-form" id="pdvAcessoForm" autocomplete="off">
        <h3>Acesso ao caixa pelo túnel do conector</h3>
        <p class="pdv-nota pdv-form-largo">O SightOps entra no caixa pelo conector da loja (nunca pelo IP público), confere o caixa,
          copia o coletor e liga o serviço. Nada mais é alterado no caixa. A senha fica cifrada no SightOps.
          Use o IP e a porta do caixa <strong>dentro da loja</strong> (SSH normalmente na 22), não os do roteador.</p>
        <label>IP do caixa na loja<input name="pdv_host" required value="${esc(c.pdv_host || '')}" placeholder="192.168.24.97"></label>
        <label>Porta SSH do caixa<input name="ssh_porta" type="number" min="1" max="65535" value="${esc(c.ssh_porta || 22)}"></label>
        <label>Usuário<input name="ssh_usuario" required value="${esc(c.ssh_usuario || '')}" placeholder="rpdv" autocomplete="off"></label>
        <label>Senha<input name="ssh_senha" type="password" autocomplete="new-password" placeholder="${c.tem_senha ? 'guardada (em branco mantém)' : ''}"></label>
        <div class="pdv-form-acoes">
          <button class="secondary-action" type="button" id="pdvAcessoSalvar">Salvar acesso</button>
          <button class="secondary-action" type="button" id="pdvAcessoStatus" ${c.tem_senha ? '' : 'disabled'}>Ver status</button>
          <button class="primary-action" type="submit" id="pdvAcessoInstalar"><i data-lucide="download"></i> Salvar e instalar</button>
        </div>
        <div id="pdvPassos" class="pdv-passos"></div>
      </form>

      <div class="pdv-perigo">
        <div><strong>Excluir caixa</strong><small>Apaga o caixa e todas as vendas recebidas dele. O coletor no caixa para de enviar. Não dá para desfazer.</small></div>
        <button class="secondary-action pdv-mini pdv-botao-perigo" type="button" id="pdvExcluir"><i data-lucide="trash-2"></i> Excluir</button>
      </div>
    </section>`;
  lucide.createIcons();

  const passos = document.getElementById('pdvPassos');
  const acesso = document.getElementById('pdvAcessoForm');
  document.getElementById('pdvPainelFechar').addEventListener('click', () => { box.innerHTML = ''; });

  document.getElementById('pdvDadosForm').addEventListener('submit', async ev => {
    ev.preventDefault();
    if (!(await pdvSalvarCaixa(ev.currentTarget))) return;
    showToast('Dados do caixa salvos.');
    loadPdvConfig(caixaId);
  });

  const salvarAcesso = async () => {
    const dados = Object.fromEntries(new FormData(acesso).entries());
    const res = await api(`/api/pdv/caixas/${encodeURIComponent(caixaId)}/acesso`, { method: 'POST', body: JSON.stringify(dados) });
    const r = await res?.json().catch(() => ({}));
    if (!res?.ok) { showToast(r?.detail || 'Não consegui salvar o acesso ao caixa.', true); return false; }
    acesso.ssh_senha.value = '';
    acesso.ssh_senha.placeholder = r.acesso?.tem_senha ? 'guardada (em branco mantém)' : 'a senha foi apagada: digite de novo';
    document.getElementById('pdvAcessoStatus').disabled = !r.acesso?.tem_senha;
    return r.acesso;
  };

  document.getElementById('pdvAcessoSalvar').addEventListener('click', async () => {
    if (!acesso.reportValidity()) return;
    const a = await salvarAcesso();
    if (a) showToast(a.tem_senha ? 'Acesso salvo.' : 'Acesso salvo. IP ou porta mudaram: digite a senha de novo.');
  });

  document.getElementById('pdvAcessoStatus').addEventListener('click', async () => {
    passos.innerHTML = '<p class="pdv-nota">Consultando o serviço no caixa pelo túnel...</p>';
    const res = await api(`/api/pdv/caixas/${encodeURIComponent(caixaId)}/coletor`, { method: 'POST', body: '{}' });
    const r = await res?.json().catch(() => ({}));
    if (!r?.ok) { passos.innerHTML = `<p class="pdv-nota pdv-erro">${esc(r?.erro || r?.detail || 'Não consegui consultar o caixa.')}</p>`; return; }
    passos.innerHTML = `<p class="pdv-nota">Serviço: <strong>${r.ativo ? 'rodando' : esc(r.estado || 'parado')}</strong>${r.desde ? ` desde ${esc(r.desde)}` : ''}</p>
      <pre class="pdv-log">${esc(r.log || '')}</pre>`;
  });

  acesso.addEventListener('submit', async ev => {
    ev.preventDefault();
    const ok = document.getElementById('pdvAcessoInstalar');
    ok.disabled = true;
    passos.innerHTML = '<p class="pdv-nota">Salvando o acesso...</p>';
    const a = await salvarAcesso();
    if (!a || !a.tem_senha) {
      ok.disabled = false;
      passos.innerHTML = a ? '<p class="pdv-nota pdv-erro">Digite a senha do caixa para instalar.</p>' : '';
      return;
    }
    passos.innerHTML = '<p class="pdv-nota">Instalando pelo túnel do conector... o caixa pode demorar a responder.</p>';
    const res = await api(`/api/pdv/caixas/${encodeURIComponent(caixaId)}/instalar`, { method: 'POST', body: '{}' });
    const ini = await res?.json().catch(() => ({}));
    if (!res?.ok || !ini?.job_id) {
      ok.disabled = false;
      passos.innerHTML = `<p class="pdv-nota pdv-erro">${esc(ini?.detail || 'Não consegui iniciar a instalação.')}</p>`;
      return;
    }
    const desenhar = (lista, rodando, seg) => {
      passos.innerHTML = lista.map(p => `
        <div class="pdv-passo ${p.ok ? 'ok' : 'erro'}"><i data-lucide="${p.ok ? 'check-circle' : 'x-circle'}"></i>
          <div><strong>${esc(p.passo)}</strong>${p.detalhe ? `<pre class="pdv-log">${esc(p.detalhe)}</pre>` : ''}</div></div>`).join('')
        + (rodando ? `<p class="pdv-nota">Trabalhando no caixa... ${seg} s</p>` : '');
      lucide.createIcons();
    };
    let r = null;
    for (let i = 0; i < 150; i++) {
      await new Promise(fim => setTimeout(fim, 2000));
      r = await apiJson(`/api/pdv/instalacao/${ini.job_id}`, { forceRefresh: true });
      if (!r) break;
      desenhar(r.passos || [], !r.fim, r.segundos);
      if (r.fim) break;
    }
    ok.disabled = false;
    showToast(r?.ok ? 'Coletor instalado. As vendas começam a chegar em até 1 minuto.' : 'A instalação não terminou. Veja o passo com erro.', !r?.ok);
    pdvCarregarCaixas();
  });

  document.getElementById('pdvExcluir').addEventListener('click', async () => {
    const nome = prompt(`Para excluir, digite o nome do caixa: ${c.nome}\n\nIsso apaga o caixa e todas as vendas recebidas dele.`);
    if (nome === null) return;
    if (nome.trim() !== c.nome) { showToast('O nome não confere. Nada foi excluído.', true); return; }
    const res = await api(`/api/pdv/caixas/${encodeURIComponent(caixaId)}`, { method: 'DELETE', body: '{}' });
    const r = await res?.json().catch(() => ({}));
    if (!res?.ok) { showToast(r?.detail || 'Não consegui excluir o caixa.', true); return; }
    showToast(`${c.nome} excluído.`);
    loadPdvConfig();
  });

  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('pdvLojasAnterior')?.addEventListener('click', () => pdvLojasDia(-1));
  document.getElementById('pdvLojasProximo')?.addEventListener('click', () => pdvLojasDia(1));
  document.getElementById('pdvVisaoAnterior')?.addEventListener('click', () => pdvVisaoDia(-1));
  document.getElementById('pdvVisaoProximo')?.addEventListener('click', () => pdvVisaoDia(1));
  document.getElementById('pdvCupBuscar')?.addEventListener('click', pdvBuscarCupons);
  document.getElementById('pdvCupFiltroBusca')?.addEventListener('keydown', ev => { if (ev.key === 'Enter') pdvBuscarCupons(); });
  ['pdvCupFiltroDia', 'pdvCupFiltroCaixa', 'pdvCupFiltroSituacao'].forEach(id =>
    document.getElementById(id)?.addEventListener('change', pdvBuscarCupons));
  document.querySelector('[data-settings-tab="pdv"]')?.addEventListener('click', () => loadPdvConfig());
});
