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

// Cartao de numero do PDV: icone colorido, rotulo, numero, linha de apoio e,
// quando faz sentido, uma barra fina de progresso (0-100). id = alvo do pdvPinta.
function pdvKpi({ id = '', ic, cor = 'azul', rot, big = '–', sub = '&nbsp;', pct = null }) {
  return `<section class="pdv-l-card pdv-l-s3 pdv-k pdv-k-${cor}">
    <div class="pdv-k-top"><span class="pdv-k-ico"><i data-lucide="${ic}"></i></span><span class="pdv-l-k">${rot}</span></div>
    <div class="pdv-l-stat" ${id ? `id="${id}"` : ''}><strong class="pdv-l-big">${big}</strong>
      <span class="pdv-l-sub pdv-l-uma">${sub}</span>
      ${pct === null ? '' : `<i class="pdv-k-barra"><b style="width:${Math.max(0, Math.min(100, pct))}%"></b></i>`}</div>
  </section>`;
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
  if (typeof pdvLateralFechar === 'function') pdvLateralFechar();
  if (typeof pdvRkFichaFechar === 'function') pdvRkFichaFechar();
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

const PDV_ALERTA_ICONE = {
  CIT: ['x-circle', 'verm'], CCV: ['ban', 'verm'], CCG: ['ban', 'verm'], ITEMSEMCAD: ['scan-search', 'ambar'],
  DST: ['percent', 'ambar'], SGR: ['banknote', 'azul'],
};

function pdvAlertaIcone(a) {
  const [ic, cor] = PDV_ALERTA_ICONE[a.tipo] || ['alert-circle', 'ambar'];
  return `<span class="pdv-k-ico pdv-k-${cor}" aria-hidden="true"><i data-lucide="${ic}"></i></span>`;
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
      <article class="pdv-l-card pdv-l-s3 pdv-l-loja pdv-k pdv-k-azul">
        <div class="pdv-l-head pdv-l-topo">
          <div class="pdv-k-top"><span class="pdv-k-ico"><i data-lucide="store"></i></span>
          <div class="pdv-l-stat"><strong class="pdv-l-nome" title="${esc(l.nome)}">${esc(l.nome)}</strong>
            <span class="pdv-l-sub">${pdvPlural(l.n_caixas, 'caixa')}</span></div></div>
          <button type="button" class="pdv-l-link" data-pdv-loja="${esc(l.nome)}" title="Ver os caixas desta loja ao vivo">Abrir</button>
        </div>
        <div class="pdv-l-stat"><span class="pdv-l-k">Vendido ${r.hoje ? 'hoje' : 'no dia'}</span>
          <strong class="pdv-l-big">${pdvMoeda(l.vendido_centavos)}</strong>
          ${nLojas > 1 && rede.vendido_centavos ? `<span class="pdv-l-sub">${Math.round(100 * l.vendido_centavos / rede.vendido_centavos)}% da rede</span>
          <i class="pdv-k-barra"><b style="width:${Math.round(100 * l.vendido_centavos / rede.vendido_centavos)}%"></b></i>` : ''}</div>
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

  // Comparar lojas: uma linha por loja, da que mais vendeu para a que menos vendeu,
  // com a parte dela na venda da rede e os numeros em mini-blocos.
  const mini = (rot, val, cls = '') => `<span class="pdv-cl-mini ${cls}"><small>${rot}</small><strong>${val}</strong></span>`;
  const tabelaLojas = `
        <div class="pdv-l-head pdv-l-titulo"><h2 class="pdv-l-h2">Comparar lojas</h2>
          <span class="pdv-l-sub">números de ${r.hoje ? 'hoje' : esc(pdvDiaRotulo(r.dia))}</span></div>
        <div class="pdv-cl">${[...r.lojas].sort((a, b) => b.vendido_centavos - a.vendido_centavos).map((l, i) => {
          const parte = rede.vendido_centavos ? Math.round(100 * l.vendido_centavos / rede.vendido_centavos) : 0;
          const cancAlto = l.cancelados_por_mil > rede.cancelados_por_mil * 1.5 && l.cancelados;
          const semCx = r.hoje && l.coletando < l.n_caixas;
          return `
          <button type="button" class="pdv-cl-linha" data-pdv-loja="${esc(l.nome)}" title="Ver ${esc(l.nome)} ao vivo">
            <span class="pdv-r-pos ${i === 0 ? 'bom' : ''}">${i + 1}º</span>
            <span class="pdv-cl-nome"><strong class="pdv-l-uma">${esc(l.nome)}</strong>
              <small class="${semCx ? 'pdv-l-ruim' : ''}">${pdvPlural(l.n_caixas, 'caixa')}${r.hoje ? ` · ${l.coletando} de ${l.n_caixas} coletando` : ''}</small></span>
            <span class="pdv-cl-parte"><i class="pdv-k-barra pdv-k-azul"><b style="width:${Math.max(2, parte)}%"></b></i><small>${parte}% da rede</small></span>
            ${mini('Cupons', pdvNum(l.cupons))}${mini('Ticket', pdvMoeda(l.cupons ? l.vendido_centavos / l.cupons : 0))}
            ${mini('Bipados', pdvPct(l.bipados, l.itens))}${mini('Canc. ‰', pdvPorMil(l.cancelados_por_mil), cancAlto ? 'ruim' : '')}
            ${mini('Revisar', pdvNum(l.revisar), l.revisar ? 'ambar' : '')}
            <strong class="pdv-cl-total">${pdvMoeda(l.vendido_centavos)}</strong>
          </button>`;
        }).join('')}
          <div class="pdv-cl-linha pdv-cl-rede">
            <span class="pdv-r-pos">Σ</span>
            <span class="pdv-cl-nome"><strong>Rede</strong><small>${pdvPlural(nLojas, 'loja')} · ${r.hoje ? `${rede.coletando} de ${rede.n_caixas} caixas coletando` : pdvPlural(rede.n_caixas, 'caixa')}</small></span>
            <span class="pdv-cl-parte"></span>
            ${mini('Cupons', pdvNum(rede.cupons))}${mini('Ticket', pdvMoeda(ticket))}${mini('Bipados', pdvPct(rede.bipados, rede.itens))}
            ${mini('Canc. ‰', pdvPorMil(rede.cancelados_por_mil))}${mini('Revisar', pdvNum(rede.revisar))}
            <strong class="pdv-cl-total">${pdvMoeda(rede.vendido_centavos)}</strong>
          </div>
        </div>`;

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
        ${pdvAlertaIcone(a)}
        <div class="pdv-l-stat">
          <span class="pdv-l-sub pdv-l-uma">${esc(pdvHora(a.ts))} · <strong>${esc(nLojas > 1 ? a.loja : a.caixa)}</strong>${nLojas > 1 ? ` · ${esc(a.caixa)}` : ''}</span>
          <span class="pdv-l-txt" title="${esc(txt)}">${esc(txt)}</span>
        </div>
        <button type="button" class="pdv-l-link" data-pdv-cupom="${esc(a.cupom || '')}" data-pdv-caixa="${esc(a.caixa_id)}"
          data-pdv-dia="${esc(String(a.ts || '').slice(0, 10))}" data-pdv-ts="${esc(a.ts || '')}" title="Abrir o cupom, com os itens e o vídeo">abrir</button>
      </div>`;
  }).join('') || '<p class="pdv-l-sub pdv-l-vazio">Nenhuma ocorrência neste dia.</p>';

  box.innerHTML = `
    <div class="pdv-l-grade">
      ${pdvKpi({ ic: 'banknote', cor: 'azul', rot: `Vendido ${nLojas > 1 ? 'na rede' : 'na loja'}`, big: pdvMoeda(rede.vendido_centavos),
        sub: `${pdvPlural(nLojas, 'loja')}${r.hoje ? ` · até ${new Date().toTimeString().slice(0, 5)}` : ''}` })}
      ${pdvKpi({ ic: 'receipt-text', cor: 'verde', rot: 'Cupons', big: pdvNum(rede.cupons), sub: `ticket médio ${pdvMoeda(ticket)}` })}
      ${pdvKpi({ ic: 'monitor-check', cor: semCol.length && r.hoje ? 'verm' : 'ciano', rot: 'Caixas coletando',
        big: `${r.hoje ? pdvNum(rede.coletando) : '–'} <em>de ${pdvNum(rede.n_caixas)}</em>`,
        sub: r.hoje ? coletaTxt : 'situação só no dia de hoje', pct: r.hoje && rede.n_caixas ? 100 * rede.coletando / rede.n_caixas : null })}
      ${pdvKpi({ ic: 'scan-eye', cor: 'ambar', rot: 'Para revisar', big: pdvNum(rede.revisar),
        sub: `${pdvNum(rede.cancelados)} cancelados · ${pdvNum(rede.sem_cadastro)} sem cadastro` })}

      ${umaLoja ? '' : `<div class="pdv-l-s12 pdv-l-head pdv-l-secao">
        <h2 class="pdv-l-h2">Lojas</h2>
        ${r.hoje ? `<div class="pdv-l-legenda pdv-l-sub">
          <span><i class="pdv-cx-venda"></i>em venda</span><span><i class="pdv-cx-livre"></i>livre</span>
          <span><i class="pdv-cx-parado"></i>sem venda há mais de 1 h</span><span><i class="pdv-cx-sem"></i>sem coletor</span>
        </div>` : ''}
      </div>
      ${r.lojas.map(cartao).join('')}`}

      <section class="pdv-l-card pdv-l-tabela pdv-l-mais pdv-sombra">${umaLoja ? tabelaCaixas : tabelaLojas}</section>

      <aside class="pdv-l-card pdv-l-lado pdv-l-mais pdv-l-agora pdv-sombra" aria-label="Últimas ocorrências">
        <div class="pdv-l-head pdv-l-agora-topo"><h2 class="pdv-l-h2">${r.hoje ? 'Acontecendo agora' : 'Últimas ocorrências'}</h2>
          <span class="pdv-l-sub">${nLojas > 1 ? 'todas as lojas' : 'da loja'}</span></div>
        ${alertas}
        <div class="pdv-l-agora-pe"><button type="button" class="pdv-l-link" data-pdv-cupons>Ver os rankings</button></div>
      </aside>
    </div>`;
  box.querySelectorAll('[data-pdv-ir]').forEach(b => b.addEventListener('click', () => pdvIrAoVivo(b.dataset.pdvIr)));
  box.querySelectorAll('[data-pdv-loja]').forEach(b => b.addEventListener('click', () => pdvIrLoja(b.dataset.pdvLoja)));
  box.querySelectorAll('[data-pdv-cupom]').forEach(b => b.addEventListener('click', () =>
    pdvIrCupom(b.dataset.pdvCaixa, b.dataset.pdvDia || _pdvLojasDia, b.dataset.pdvCupom, b.dataset.pdvTs || '')));
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
  _pdvResumo = r;
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
    ['x-circle', 'Itens cancelados', cancItens, itens ? `${(1000 * cancItens / itens).toLocaleString('pt-BR', { maximumFractionDigits: 2 })} por mil itens` : '', 'itens_cancelados'],
    ['ban', 'Cupons cancelados', cancCupons, '', 'cupons_cancelados'],
    ['percent', 'Descontos em item', ev.DIT || 0, '', 'desc_item'],
    ['badge-percent', 'Descontos no subtotal', ev.DST || 0, '', 'desc_subtotal'],
    ['scan-search', 'Código sem cadastro', ev.ITEMSEMCAD || 0, '', 'ev_ITEMSEMCAD'],
    ['hand-coins', 'Sangrias', ev.SGR || 0, '', 'ev_SGR'],
    ['archive', 'Gaveta aberta', ev.GAV || 0, '', 'ev_GAV'],
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
          <tfoot><tr><td>Valor passado no caixa</td><td class="num"><strong>${pdvNum(itens)}</strong></td><td></td>
            <td class="num"><strong>${pdvMoeda(fatias.reduce((s, f) => s + f.v, 0))}</strong></td></tr></tfoot>
        </table>
        ${pdvConferencia(r)}
      </section>

      <section class="panel pdv-painel">
        <div class="pdv-panel-head"><h2>Ocorrências do dia</h2><small>para revisar com o vídeo</small></div>
        <ul class="pdv-ocorrencias">${ocorrencias.map(([ic, rot, qtd, sub, lista]) => `
          <li class="${qtd ? '' : 'zero'} ${qtd && lista ? 'pdv-clica-lista' : ''}" ${qtd && lista ? `data-pdv-lista="${lista}" title="Ver os cupons"` : ''}><i data-lucide="${ic}"></i>
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
  box.querySelectorAll('[data-pdv-lista]').forEach(el => el.addEventListener('click', () => pdvListaLateral(el.dataset.pdvLista)));
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
      ${pdvKpi({ id: 'pdvVkVendido', ic: 'banknote', cor: 'azul', rot: 'Vendido hoje' })}${pdvKpi({ id: 'pdvVkCupons', ic: 'receipt-text', cor: 'verde', rot: 'Cupons' })}
      ${pdvKpi({ id: 'pdvVkBip', ic: 'scan-barcode', cor: 'ciano', rot: 'Bipados', pct: 0 })}${pdvKpi({ id: 'pdvVkRev', ic: 'scan-eye', cor: 'ambar', rot: 'Para revisar' })}
      <div class="pdv-l-s12 pdv-l-head pdv-l-secao">
        <h2 class="pdv-l-h2">Caixas</h2>
        <div class="pdv-l-legenda pdv-l-sub">
          <span><i class="pdv-cx-venda"></i>em venda</span><span><i class="pdv-cx-livre"></i>livre</span>
          <span><i class="pdv-cx-parado"></i>sem venda há mais de 1 h</span><span><i class="pdv-cx-sem"></i>sem coletor</span>
          ${r.lojas.length > 1 ? `<label class="pdv-v-loja">Loja <select id="pdvVivoLoja">${r.lojas.map(n =>
            `<option value="${esc(n)}" ${n === r.loja.nome ? 'selected' : ''}>${esc(n)}</option>`).join('')}</select></label>` : ''}
        </div>
      </div>
      <aside class="pdv-l-card pdv-v-lado pdv-l-agora pdv-sombra" aria-label="Acontecendo agora na loja">
        <div class="pdv-l-head pdv-l-agora-topo"><h2 class="pdv-l-h2">Acontecendo agora</h2><span class="pdv-l-sub">da loja</span></div>
        <div id="pdvVtAlertas"></div>
        <div class="pdv-l-agora-pe"><button type="button" class="pdv-l-link" data-pdv-cupons>Ver os rankings</button></div>
      </aside>
      ${r.caixas.map(tile).join('')}
    </div>
    <p class="pdv-nota">O vídeo sai do gravador pelo conector da loja, como as outras câmeras do SightOps; aqui vai leve (SD). Clique num caixa para ver grande, em HD, com o cupom ao lado.</p>`;
  lucide.createIcons();

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
    if (b) pdvIrCupom(b.dataset.pdvCaixa, b.dataset.pdvDia || pdvHoje(), b.dataset.pdvCupom, b.dataset.pdvTs || '');
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
  const barraBip = document.querySelector('#pdvVkBip .pdv-k-barra b');
  if (barraBip) barraBip.style.width = `${l.itens ? Math.round(100 * l.bipados / l.itens) : 0}%`;
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
      return `<div class="pdv-l-alerta">${pdvAlertaIcone(a)}
        <div class="pdv-l-stat"><span class="pdv-l-sub pdv-l-uma">${esc(pdvHora(a.ts))} · <strong>${esc(a.caixa)}</strong></span>
          <span class="pdv-l-txt" title="${esc(txt)}">${esc(txt)}</span></div>
        <button type="button" class="pdv-l-link" data-pdv-cupom="${esc(a.cupom || '')}" data-pdv-caixa="${esc(a.caixa_id)}"
          data-pdv-dia="${esc(String(a.ts || '').slice(0, 10))}" data-pdv-ts="${esc(a.ts || '')}" title="Abrir o cupom, com os itens e o vídeo">abrir</button></div>`;
    }).join('') || '<p class="pdv-l-sub pdv-l-vazio">Nada fora do normal hoje.</p>';
  }
}

async function pdvVivoKpis(caixaId) {
  const r = await apiJson(`/api/pdv/resumo?dia=${pdvHoje()}&caixa_id=${encodeURIComponent(caixaId)}`, { forceRefresh: true });
  if (!r || _pdvVivo.caixaId !== caixaId || !document.getElementById('pdvFkVendido')) return;
  const cup = r.cupons || {};
  const fechados = cup.fechado || 0;
  const m = r.modos || {};
  const bip = m.scanner?.n || 0;
  const ev = r.eventos || {};
  const canc = (ev.CIT || 0) + (ev.CCV || 0) + (ev.CCG || 0);
  const pinta = (id, big, sub) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.querySelector('.pdv-l-big').innerHTML = big;
    el.querySelector('.pdv-l-sub').innerHTML = sub;
  };
  pinta('pdvFkVendido', pdvMoeda(r.vendido_centavos), `até ${new Date().toTimeString().slice(0, 5)}`);
  pinta('pdvFkCupons', pdvNum(fechados), `ticket médio ${pdvMoeda(fechados ? r.vendido_centavos / fechados : 0)}`);
  pinta('pdvFkBip', pdvPct(bip, r.itens), `${pdvNum(r.itens)} itens passados`);
  const barra = document.querySelector('#pdvFkBip .pdv-k-barra b');
  if (barra) barra.style.width = `${r.itens ? Math.round(100 * bip / r.itens) : 0}%`;
  pinta('pdvFkRev', pdvNum(canc + (ev.ITEMSEMCAD || 0)), `${pdvNum(canc)} cancelados · ${pdvNum(ev.ITEMSEMCAD || 0)} sem cadastro`);
}

function pdvRenderVivo() {
  const box = document.getElementById('pdvVivoBody');
  const c = _pdvCaixas.find(x => x.id === _pdvVivo.caixaId);
  if (!box || !c) return;
  box.innerHTML = `
    <div class="pdv-v-voltar"><button type="button" class="secondary-action" data-pdv-parede><i data-lucide="layout-grid"></i> Todos os caixas da loja</button></div>
    <div class="pdv-l-grade pdv-v-kpis">
      ${pdvKpi({ id: 'pdvFkVendido', ic: 'banknote', cor: 'azul', rot: `Vendido hoje · ${esc(c.nome)}` })}
      ${pdvKpi({ id: 'pdvFkCupons', ic: 'receipt-text', cor: 'verde', rot: 'Cupons' })}
      ${pdvKpi({ id: 'pdvFkBip', ic: 'scan-barcode', cor: 'ciano', rot: 'Bipados', pct: 0 })}
      ${pdvKpi({ id: 'pdvFkRev', ic: 'scan-eye', cor: 'ambar', rot: 'Para revisar' })}
    </div>
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
      <aside class="panel pdv-painel pdv-cupom-vivo pdv-sombra" id="pdvCupomVivo"><p class="pdv-nota">Carregando o cupom...</p></aside>
    </div>
    <section class="pdv-miniaturas">${_pdvCaixas.map(x => {
      const s = pdvSaudeCaixa(x);
      return `<button type="button" class="pdv-miniatura ${x.id === c.id ? 'ativa' : ''}" data-pdv-caixa="${esc(x.id)}">
        <span class="pdv-k-ico pdv-k-${x.id === c.id ? 'azul' : 'ciano'}"><i data-lucide="monitor"></i></span>
        <span class="pdv-mini-txt"><strong>${esc(x.nome)}</strong><span><span class="pdv-ponto pdv-ponto-${s.cls}"></span>${esc(s.txt)}</span></span>
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
  pdvVivoKpis(c.id);
  let voltas = 0;
  _pdvVivo.timer = setInterval(() => {
    if (!pdvVisivel('viewPdvVivo')) { pdvParar(); return; }
    pdvAtualizarCupomVivo();
    if (++voltas % 15 === 0) pdvVivoKpis(c.id);
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

// Do valor passado no caixa ao Vendido do topo: o que saiu no caminho.
function pdvConferencia(r) {
  const c = r.conferencia;
  if (!c) return '';
  const linhas = [
    ['Cupons cancelados inteiros', c.cupons_cancelados, '', 'cupons_cancelados'],
    ['Itens cancelados', c.itens_cancelados, '', 'itens_cancelados'],
    ['Descontos em item', c.desc_item, '', 'desc_item'],
    ['Descontos no subtotal do cupom', c.desc_subtotal, '', 'desc_subtotal'],
    ['Descontos sem registro no PDV', c.desc_outros, 'diferença entre os itens e o total do cupom sem evento de desconto (centavos de arredondamento e outros)'],
    ['Cupons ainda abertos', c.abertos, '', 'abertos'],
    ['Itens sem cupom', c.sem_cupom],
  ].filter(l => l[1]);
  const saiu = linhas.reduce((t, l) => t + l[1], 0);
  const neg = v => `− ${pdvMoeda(Math.abs(v))}`;
  return `
    <table class="pdv-legenda pdv-conferencia">
      <tbody>${linhas.map(([rot, v, dica, lista]) => `<tr${dica ? ` title="${esc(dica)}"` : ''}${lista ? ` class="pdv-clica-lista" data-pdv-lista="${lista}" title="Ver os cupons"` : ''}><td>${rot}${lista ? ' <i data-lucide="chevron-right" class="pdv-seta-lista"></i>' : ''}</td><td class="num pdv-negativo">${v < 0 ? `+ ${pdvMoeda(-v)}` : neg(v)}</td></tr>`).join('')}
        <tr class="pdv-conf-soma"><td>Total que saiu da soma dos itens</td><td class="num pdv-negativo"><strong>${neg(saiu)}</strong></td></tr></tbody>
      <tfoot><tr><td>Vendido (cupons fechados)<small class="pdv-sub">${pdvMoeda(c.passado)} ${neg(saiu)}</small></td>
        <td class="num"><strong>${pdvMoeda(r.vendido_centavos)}</strong></td></tr></tfoot>
    </table>`;
}

// Painel lateral: TELA de video fixa em cima e a lista de cupons embaixo.
// Clicar no cupom toca o video na tela e abre a linha mostrando o que se esta
// vendo (o item cancelado, o desconto...), com um play para cada momento. Assim
// a pessoa sabe o que esta conferindo antes e durante o video.
let _pdvResumo = null;
const PDV_LISTAS = {
  cupons_cancelados: 'Cupons cancelados inteiros',
  itens_cancelados: 'Cupons com item cancelado',
  desc_item: 'Cupons com desconto em item',
  desc_subtotal: 'Cupons com desconto no subtotal',
  abertos: 'Cupons ainda abertos',
  ev_ITEMSEMCAD: 'Códigos sem cadastro',
  ev_SGR: 'Sangrias',
  ev_GAV: 'Gaveta aberta',
};
// o que conferir em cada lista (eventos do cupom)
const PDV_LISTA_EVENTO = {
  itens_cancelados: ['CIT'], desc_item: ['DIT'], desc_subtotal: ['DAS'], cupons_cancelados: ['CCV', 'CCG'],
};
let _pdvLat = { tipo: '', sel: '', atual: null };

const PDV_LAT_VAZIA = `<div class="pdv-lat-vazia"><i data-lucide="play-circle"></i>
  <span>Clique num cupom da lista para ver o vídeo aqui</span></div>`;

function pdvLateralFechar() {
  const d = document.getElementById('pdvLateral');
  if (!d) return;
  _pdvRep = null;
  pdvPararGravacao();
  _pdvLat.sel = '';
  _pdvLat.atual = null;
  d.classList.remove('open');
  setTimeout(() => { d.classList.add('hidden'); document.getElementById('pdvLateralFundo')?.classList.add('hidden'); }, 270);
}

function pdvLateralCriar() {
  if (document.getElementById('pdvLateral')) return;
  // fecha so pelo X ou Esc (regra do sistema: clicar fora nao fecha)
  document.body.insertAdjacentHTML('beforeend', `
    <div id="pdvLateralFundo" class="dash-drawer-overlay hidden"></div>
    <aside id="pdvLateral" class="dash-drawer pdv-lateral hidden" aria-label="Cupons">
      <div class="dash-drawer-header">
        <div><h2 class="pdv-l-h2" id="pdvLateralTitulo"></h2><span class="pdv-l-sub" id="pdvLateralSub"></span></div>
        <button class="icon-button" type="button" id="pdvLateralX" title="Fechar (Esc)"><i data-lucide="x"></i></button>
      </div>
      <div class="pdv-lat-tela" id="pdvLatTela">
        <div class="pdv-videobox"></div>
        <div class="pdv-lat-agora" id="pdvLatAgora"></div>
      </div>
      <div class="pdv-lat-filtros" id="pdvLatFiltros" hidden>
        <label class="pdv-c-campo"><span>Loja</span><select id="pdvLatLoja"></select></label>
        <label class="pdv-c-campo"><span>PDV</span><select id="pdvLatCaixa"></select></label>
        <span class="pdv-l-sub" id="pdvLatConta"></span>
      </div>
      <div class="pdv-lateral-corpo" id="pdvLateralCorpo"></div>
    </aside>`);
  document.getElementById('pdvLateralX').addEventListener('click', pdvLateralFechar);
  document.getElementById('pdvLatLoja').addEventListener('change', () => { pdvLatOpcoesCaixa(); pdvLatDesenhar(); });
  document.getElementById('pdvLatCaixa').addEventListener('change', pdvLatDesenhar);
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && document.getElementById('pdvLateral')?.classList.contains('open')) pdvLateralFechar();
  });
  document.getElementById('pdvLateralCorpo').addEventListener('click', ev => {
    if (ev.target.closest('[data-pdv-inteiro]')) { pdvLatInteiro(); return; }
    if (ev.target.closest('[data-pdv-sair-inteiro]')) { pdvLatSairInteiro(); return; }
    if (ev.target.closest('[data-pdv-mostrar-tudo]')) { if (_pdvRep) { _pdvRep.tudo = true; pdvRepPintar(); } return; }
    const rl = ev.target.closest('[data-pdv-rep]');
    if (rl && _pdvRep) { pdvRepTocar(rl.dataset.pdvRep, 3, rl.querySelector('.pdv-rep-txt')?.innerText || ''); return; }
    const mom = ev.target.closest('[data-pdv-momento]');
    if (mom && _pdvLat.atual) { pdvLatTocar(mom.dataset.pdvMomento, mom.dataset.pdvRotulo || ''); return; }
    const evs = ev.target.closest('[data-pdv-ev]');
    if (evs) { if (ev.target.closest('[data-pdv-play]')) pdvLatTocarEvento(evs); return; }
    const el = ev.target.closest('[data-pdv-abrir]');
    if (el) pdvLatSelecionar(el, !!ev.target.closest('[data-pdv-play]'));
  });
}

function pdvLateralAbrir(titulo, sub) {
  pdvLateralCriar();
  _pdvRep = null;
  pdvPararGravacao();
  _pdvLat.sel = '';
  _pdvLat.atual = null;
  const d = document.getElementById('pdvLateral');
  document.getElementById('pdvLateralTitulo').textContent = titulo;
  document.getElementById('pdvLateralSub').textContent = sub;
  d.querySelector('.pdv-videobox').innerHTML = PDV_LAT_VAZIA;
  document.getElementById('pdvLatAgora').innerHTML = '';
  document.getElementById('pdvLatFiltros').hidden = true;
  document.getElementById('pdvLateralCorpo').innerHTML = '<p class="pdv-nota pdv-c-msg">Buscando os cupons...</p>';
  d.classList.remove('hidden');
  document.getElementById('pdvLateralFundo').classList.remove('hidden');
  requestAnimationFrame(() => requestAnimationFrame(() => d.classList.add('open')));
  lucide.createIcons();
}

// uma linha da lista (o botao do cupom e, embaixo, o que se abre ao clicar)
function pdvLatLinha(k, txt, val, ts = '') {
  return `<div class="pdv-lat-cupom">
    <button type="button" class="pdv-lateral-item" data-pdv-abrir="${esc(k.caixa_id)}|${esc(k.dia)}|${esc(k.cupom)}" data-pdv-ts="${esc(ts)}">
      <span class="pdv-hora">${esc(pdvHora(k.aberto_em).slice(0, 5))}</span>
      <span class="pdv-lateral-meio"><strong>${esc(k.cupom)} · ${esc(k.caixa)}</strong><small>${esc(k.operador)}${txt ? ` · ${esc(txt)}` : ''}</small></span>
      <span class="pdv-lateral-valores">${val ? `<b class="pdv-negativo">${esc(val)}</b>` : ''}<small>total ${esc(pdvMoeda(k.total_centavos))}</small></span>
      <span class="pdv-lat-play" data-pdv-play title="Ver o vídeo"><i data-lucide="play-circle"></i></span>
    </button>
    <div class="pdv-lat-abre" hidden></div>
  </div>`;
}

function pdvLatMomento(ts, rotulo, valor = '') {
  return `<button type="button" class="pdv-lat-mom" data-pdv-momento="${esc(ts)}" data-pdv-rotulo="${esc(rotulo)}">
    <span class="pdv-hora">${esc(pdvHora(ts))}</span><span class="pdv-lat-mom-txt">${esc(rotulo)}</span>
    ${valor ? `<span class="pdv-valor">${esc(valor)}</span>` : ''}<i data-lucide="play"></i></button>`;
}

// toca o video na tela de cima e diz o que esta sendo mostrado
function pdvLatTocar(ts, rotulo) {
  const a = _pdvLat.atual;
  const d = document.getElementById('pdvLateral');
  if (!a || !d) return;
  document.getElementById('pdvLatAgora').innerHTML = `
    <strong>${a.k.cupom ? `Cupom ${esc(a.k.cupom)} · ` : ''}${esc(a.caixaNome)} · ${esc(a.k.operador || '')}</strong>
    <span>Vendo: ${esc(rotulo)} · às ${esc(pdvHora(ts))} no caixa</span>`;
  d.querySelectorAll('.pdv-lat-mom').forEach(b => b.classList.toggle('ativo', b.dataset.pdvMomento === ts && b.dataset.pdvRotulo === rotulo));
  pdvVerVideo(a.caixaId, ts, document.getElementById('pdvLatTela'), 3);
}

// Clicar na linha abre/fecha o cupom; o video so toca no play (da linha ou de um momento).
async function pdvLatSelecionar(btn, tocar = false) {
  const wrap = btn.closest('.pdv-lat-cupom');
  const [caixaId, dia, cupom] = btn.dataset.pdvAbrir.split('|');
  const chave = btn.dataset.pdvAbrir;
  const corpo = document.getElementById('pdvLateralCorpo');
  if (!tocar && wrap.classList.contains('ativa')) {
    wrap.classList.remove('ativa');
    const x = wrap.querySelector('.pdv-lat-abre');
    x.hidden = true; x.innerHTML = '';
    _pdvLat.sel = '';
    return;
  }
  corpo.querySelectorAll('.pdv-lat-cupom').forEach(w => {
    const eu = w === wrap;
    w.classList.toggle('ativa', eu);
    const x = w.querySelector('.pdv-lat-abre');
    if (!eu && x) { x.hidden = true; x.innerHTML = ''; }
  });
  _pdvLat.sel = chave;
  const abre = wrap.querySelector('.pdv-lat-abre');
  abre.hidden = false;
  abre.innerHTML = '<p class="pdv-nota">Abrindo o cupom...</p>';
  const r = await apiJson(`/api/pdv/cupons/${encodeURIComponent(caixaId)}/${dia}/${encodeURIComponent(cupom)}`, { forceRefresh: true });
  if (_pdvLat.sel !== chave) return;
  if (!r?.cupom) { abre.innerHTML = '<p class="pdv-nota pdv-erro">Não consegui abrir o cupom.</p>'; return; }
  const k = r.cupom;
  const linha = r.linha_do_tempo || [];
  const itens = r.itens || [];
  // o que conferir: o horario pedido (aviso) ou os eventos da lista de onde veio
  const ts = btn.dataset.pdvTs || '';
  const tipos = PDV_LISTA_EVENTO[_pdvLat.tipo] || [];
  let foco = ts ? linha.filter(e => e.ts === ts && e.tipo !== 'VIT') : linha.filter(e => tipos.includes(e.tipo));
  if (ts && !foco.length) foco = [{ ts, tipo: '', descricao: '' }];
  const rot = e => e.tipo ? pdvEventoTexto(e) : 'Momento do aviso';
  const fim = k.fechado_em ? `${k.situacao === 'cancelado' ? 'cancelado' : 'fechado'} às ${pdvHora(k.fechado_em)}` : 'ainda aberto';
  abre.innerHTML = `
    ${foco.length ? `<div class="pdv-lat-sec"><span class="pdv-l-k pdv-l-k-ambar">O que conferir no vídeo</span>
      ${foco.map(e => pdvLatMomento(e.ts, rot(e))).join('')}</div>` : ''}
    <div class="pdv-lat-sec">
      ${pdvLatMomento(k.aberto_em, 'Abertura do cupom')}
      ${k.fechado_em ? pdvLatMomento(k.fechado_em, k.situacao === 'cancelado' ? 'Cancelamento do cupom' : 'Fechamento e pagamento') : ''}
      <button type="button" class="pdv-lat-mom pdv-lat-mom-inteiro" data-pdv-inteiro>
        <span class="pdv-hora">${esc(pdvHora(k.aberto_em))}</span><span class="pdv-lat-mom-txt">Ver o cupom inteiro, item a item</span><i data-lucide="play"></i></button>
    </div>
    <p class="pdv-nota">Aberto às ${esc(pdvHora(k.aberto_em))} · ${esc(fim)} · ${esc(k.pagamento || 'sem pagamento')} · ${pdvNum(itens.length)} ${itens.length === 1 ? 'item' : 'itens'} · total ${esc(pdvMoeda(k.total_centavos))}</p>`;
  lucide.createIcons();
  _pdvLat.atual = { caixaId, k, caixaNome: r.caixa.nome, r };
  if (!tocar) return;
  const alvo = foco[0];
  pdvLatTocar(alvo ? alvo.ts : k.aberto_em, alvo ? rot(alvo) : 'Abertura do cupom');
}

// ---- "Ver o cupom inteiro": some a lista, o video comeca na abertura e os itens
// vao aparecendo no ritmo do video (relogio do caixa = inicio do video + tempo tocado).
let _pdvRep = null;
const PDV_REP_EVENTOS = ['CIT', 'DIT', 'DAS', 'CCV', 'CCG', 'SUP', 'SUPERVISOR', 'GER', 'GAV', 'FIN', 'TRC', 'FECHACUPOM', 'ITEMSEMCAD', 'CLIENTE'];

function pdvTsMs(ts) { return new Date(String(ts).replace(' ', 'T')).getTime(); }

function pdvLatInteiro() {
  const a = _pdvLat.atual;
  if (!a) return;
  const corpo = document.getElementById('pdvLateralCorpo');
  // guarda a lista para voltar do jeito que estava
  _pdvRep = { lista: corpo.innerHTML, scroll: corpo.scrollTop, filtros: !document.getElementById('pdvLatFiltros').hidden,
    linhas: [], tudo: false, inicio: null, tocado: 0, ultimo: null, video: null, token: 0 };
  const itens = (a.r.itens || []).map(i => ({ ts: i.ts, tipo: 'VIT', txt: i.descricao || i.codigo,
    sub: (PDV_MODOS[i.modo] || [i.modo])[0], valor: Number(i.valor_centavos || 0) }));
  const eventos = (a.r.linha_do_tempo || []).filter(e => PDV_REP_EVENTOS.includes(e.tipo))
    .map(e => {
      // desconto e cancelamento entram negativos na conta; o resto so aparece na linha
      const menos = ['CIT', 'DIT', 'DAS'].includes(e.tipo);
      const nome = PDV_EVENTO_NOME[e.tipo] || e.tipo;
      const desc = ['CIT', 'DIT'].includes(e.tipo) ? ` · ${e.descricao || e.codigo || ''}` : '';
      return { ts: e.ts, tipo: e.tipo, txt: menos ? nome + desc : pdvEventoTexto(e), sub: '',
        valor: menos ? -Math.abs(Number(e.valor_centavos || 0)) : 0 };
    });
  _pdvRep.linhas = itens.concat(eventos).sort((x, y) => (x.ts < y.ts ? -1 : x.ts > y.ts ? 1 : 0));
  document.getElementById('pdvLatFiltros').hidden = true;
  corpo.innerHTML = `
    <div class="pdv-rep-topo">
      <button type="button" class="pdv-l-link" data-pdv-sair-inteiro>‹ Voltar à lista</button>
      <span class="pdv-l-sub">relógio do caixa <strong id="pdvRepRelogio">--:--:--</strong></span>
    </div>
    <div class="pdv-rep-lista" id="pdvRepLista"></div>
    <div class="pdv-rep-pe2"><button type="button" class="pdv-l-link" data-pdv-mostrar-tudo>Mostrar o cupom todo sem esperar o vídeo</button>
      <span class="pdv-l-sub">clique numa linha para o vídeo ir até ela</span></div>
    <div class="pdv-rep-pe">
      <span id="pdvRepConta"></span><strong id="pdvRepTotal">${pdvMoeda(0)}</strong>
    </div>`;
  corpo.scrollTop = 0;
  pdvRepTocar(a.k.aberto_em);
}

async function pdvRepTocar(ts, antes = 5, rotulo = '') {
  const a = _pdvLat.atual;
  if (!a || !_pdvRep) return;
  const token = ++_pdvRep.token;
  _pdvRep.inicio = null; _pdvRep.tocado = 0; _pdvRep.ultimo = null; _pdvRep.ate = pdvTsMs(ts) - antes * 1000;
  _pdvRep.atual = null;
  _pdvRep.encerrado = false;
  pdvRepPintar();
  document.getElementById('pdvLatAgora').innerHTML = `
    <strong>Cupom ${esc(a.k.cupom)} · ${esc(a.caixaNome)} · ${esc(a.k.operador || '')}</strong>
    <span>Vendo: ${rotulo ? `${esc(rotulo)} · às ${esc(pdvHora(ts))} (e o cupom segue)` : `o cupom inteiro, a partir de ${esc(pdvHora(ts))}`}</span>`;
  const v = await pdvVerVideo(a.caixaId, ts, document.getElementById('pdvLatTela'), antes);
  if (!_pdvRep || token !== _pdvRep.token || !v) return;
  _pdvRep.video = v.video;
  _pdvRep.inicio = v.inicioCaixa;
  // conta so o tempo realmente tocado (pausa e travada nao avancam a lista)
  v.video.addEventListener('timeupdate', () => {
    if (!_pdvRep || token !== _pdvRep.token) return;
    const t = v.video.currentTime;
    if (_pdvRep.ultimo !== null) {
      const d = t - _pdvRep.ultimo;
      if (d > 0 && d < 2) _pdvRep.tocado += d;
    }
    _pdvRep.ultimo = t;
    pdvRepPintar();
  });
}

function pdvRepPintar() {
  const lista = document.getElementById('pdvRepLista');
  if (!lista || !_pdvRep) return;
  const tocando = _pdvRep.inicio !== null;
  const agora = tocando ? _pdvRep.inicio + _pdvRep.tocado * 1000 : _pdvRep.ate;
  // linha atual = o ultimo acontecimento ate o momento do video (fica verde)
  let iAtual = -1;
  _pdvRep.linhas.forEach((l, i) => { if (pdvTsMs(l.ts) <= agora) iAtual = i; });
  const vistas = _pdvRep.tudo ? _pdvRep.linhas : _pdvRep.linhas.slice(0, iAtual + 1);
  const relogio = document.getElementById('pdvRepRelogio');
  if (relogio && tocando) relogio.textContent = new Date(agora).toTimeString().slice(0, 8);
  const modo = `${_pdvRep.tudo}|${vistas.length}`;
  if (_pdvRep.pintado !== modo) {
    _pdvRep.pintado = modo;
    lista.innerHTML = vistas.map(l => `
      <button type="button" class="pdv-rep-linha pdv-rep-${l.tipo}" data-pdv-rep="${esc(l.ts)}">
        <span class="pdv-hora">${esc(pdvHora(l.ts))}</span>
        <span class="pdv-rep-txt">${esc(l.txt)}${l.sub ? ` <small>${esc(l.sub)}</small>` : ''}</span>
        ${l.valor ? `<span class="pdv-valor">${l.valor < 0 ? '− ' : ''}${esc(pdvMoeda(Math.abs(l.valor)))}</span>` : ''}
      </button>`).join('') || '<p class="pdv-nota">Aguardando o vídeo chegar à abertura do cupom...</p>';
    _pdvRep.atual = null;
  }
  // pinta de verde o que esta passando agora e mantem a linha a vista
  if (_pdvRep.atual !== iAtual) {
    _pdvRep.atual = iAtual;
    const filhos = lista.querySelectorAll('.pdv-rep-linha');
    filhos.forEach((b, i) => b.classList.toggle('atual', tocando && i === iAtual));
    const el = tocando && iAtual >= 0 ? filhos[iAtual] : null;
    if (el) el.scrollIntoView({ block: _pdvRep.tudo ? 'center' : 'end', behavior: 'smooth' });
  }
  // o cupom fechou (ou foi cancelado): encerra o video 5 s depois
  const fimEv = _pdvRep.linhas.find(l => ['FECHACUPOM', 'CCV'].includes(l.tipo));
  if (tocando && fimEv && !_pdvRep.encerrado && agora >= pdvTsMs(fimEv.ts) + 5000) pdvRepEncerrar(fimEv);
  // conta e total do que ja passou no video (ou do cupom todo, antes do video comecar)
  const passadas = tocando ? _pdvRep.linhas.slice(0, iAtual + 1) : vistas;
  const itens = passadas.filter(l => l.tipo === 'VIT');
  const k = _pdvLat.atual?.k;
  const fechou = passadas.some(l => ['FECHACUPOM', 'CCV'].includes(l.tipo)) || (_pdvRep.tudo && !tocando);
  const soma = passadas.reduce((t, l) => t + l.valor, 0);
  const dif = fechou && k && k.situacao === 'fechado' ? soma - Number(k.total_centavos || 0) : 0;
  document.getElementById('pdvRepConta').textContent = `${itens.length} de ${_pdvRep.linhas.filter(l => l.tipo === 'VIT').length} itens passados`
    + (fechou && k ? ` · total do cupom${dif ? ` (${pdvMoeda(Math.abs(dif))} de ${dif > 0 ? 'desconto' : 'acréscimo'} sem registro no PDV)` : ''}`
      : ' · já com descontos e cancelamentos');
  document.getElementById('pdvRepTotal').textContent = pdvMoeda(fechou && k && k.situacao === 'fechado' ? k.total_centavos : soma);
}

function pdvRepEncerrar(fimEv) {
  _pdvRep.encerrado = true;
  pdvPararGravacao();
  const a = _pdvLat.atual;
  const box = document.querySelector('#pdvLatTela .pdv-videobox');
  if (!box || !a) return;
  const cancelado = fimEv.tipo === 'CCV';
  box.innerHTML = `<div class="pdv-lat-vazia pdv-lat-fim">
    <i data-lucide="${cancelado ? 'ban' : 'circle-check'}"></i>
    <strong>Cupom ${cancelado ? 'cancelado' : 'fechado'} às ${esc(pdvHora(fimEv.ts))} · vídeo encerrado</strong>
    <button type="button" class="secondary-action pdv-mini" id="pdvRepDeNovo"><i data-lucide="rotate-ccw"></i> Ver de novo desde a abertura</button>
  </div>`;
  document.getElementById('pdvRepDeNovo').addEventListener('click', () => pdvRepTocar(a.k.aberto_em));
  document.getElementById('pdvLatAgora').innerHTML = `
    <strong>Cupom ${esc(a.k.cupom)} · ${esc(a.caixaNome)} · ${esc(a.k.operador || '')}</strong>
    <span>Vídeo encerrado no ${cancelado ? 'cancelamento' : 'fechamento'} do cupom</span>`;
  lucide.createIcons();
}

function pdvLatSairInteiro() {
  if (!_pdvRep) return;
  const rep = _pdvRep;
  _pdvRep = null;
  pdvPararGravacao();
  const corpo = document.getElementById('pdvLateralCorpo');
  corpo.innerHTML = rep.lista;
  corpo.scrollTop = rep.scroll;
  document.getElementById('pdvLatFiltros').hidden = !rep.filtros;
  document.querySelector('#pdvLatTela .pdv-videobox').innerHTML = PDV_LAT_VAZIA;
  document.getElementById('pdvLatAgora').innerHTML = '';
  lucide.createIcons();
}

// evento fora de cupom (sangria, gaveta): so o video daquele segundo
function pdvLatTocarEvento(btn) {
  const [caixaId, ts] = btn.dataset.pdvEv.split('|');
  document.querySelectorAll('#pdvLateralCorpo .pdv-lat-cupom').forEach(w => {
    const eu = w.contains(btn);
    w.classList.toggle('ativa', eu);
    const x = w.querySelector('.pdv-lat-abre');
    if (!eu && x) { x.hidden = true; x.innerHTML = ''; }
  });
  _pdvLat.sel = '';
  _pdvLat.atual = { caixaId, k: { cupom: '', operador: btn.dataset.pdvOp || '' }, caixaNome: btn.dataset.pdvCx || '' };
  pdvLatTocar(ts, btn.dataset.pdvRotulo || '');
}

const PDV_EV_NOME = { ITEMSEMCAD: 'Código sem cadastro', SGR: 'Sangria', GAV: 'Gaveta aberta' };

async function pdvListaEventos(tipoEv) {
  const r = await apiJson(`/api/pdv/eventos?dia=${encodeURIComponent(_pdvDia)}&tipo=${tipoEv}`, { forceRefresh: true });
  if (!r) {
    document.getElementById('pdvLateralCorpo').innerHTML = '<p class="pdv-nota pdv-erro pdv-c-msg">Não consegui buscar a lista.</p>';
    return;
  }
  const nome = PDV_EV_NOME[tipoEv];
  _pdvLat.rotuloSoma = tipoEv === 'SGR' ? 'retirados' : '';
  _pdvLat.lista = (r.eventos || []).map(e => {
    const rot = `${nome}${e.codigo && tipoEv === 'ITEMSEMCAD' ? ` · ${e.codigo}` : ''}${e.descricao && tipoEv === 'SGR' ? ` · ${e.descricao}` : ''}`
      + (e.valor_centavos ? ` · ${pdvMoeda(e.valor_centavos)}` : '');
    const k = { caixa_id: e.caixa_id, dia: String(e.ts).slice(0, 10), cupom: e.cupom, aberto_em: e.ts, caixa: e.caixa,
      operador: e.operador_cupom || (e.operador !== '?' ? e.operador : '') || '', total_centavos: e.total_centavos || 0 };
    // com cupom: abre como os outros cupons, focado neste segundo
    if (e.cupom && e.situacao) {
      return { k, v: e.valor_centavos || 0, html: pdvLatLinha(k, rot, e.valor_centavos ? pdvMoeda(e.valor_centavos) : '', e.ts) };
    }
    return { k, v: e.valor_centavos || 0, html: `<div class="pdv-lat-cupom">
      <button type="button" class="pdv-lateral-item" data-pdv-ev="${esc(e.caixa_id)}|${esc(e.ts)}" data-pdv-rotulo="${esc(rot)}"
        data-pdv-op="${esc(k.operador)}" data-pdv-cx="${esc(e.caixa)}">
        <span class="pdv-hora">${esc(pdvHora(e.ts).slice(0, 5))}</span>
        <span class="pdv-lateral-meio"><strong>${esc(e.caixa)}${k.operador ? ` · ${esc(k.operador)}` : ''}</strong><small>${esc(rot)} · fora de cupom</small></span>
        <span class="pdv-lateral-valores">${e.valor_centavos ? `<b>${esc(pdvMoeda(e.valor_centavos))}</b>` : ''}</span>
        <span class="pdv-lat-play" data-pdv-play title="Ver o vídeo"><i data-lucide="play-circle"></i></span>
      </button></div>` };
  });
}

async function pdvListaLateral(tipo) {
  _pdvLat.tipo = tipo;
  if (tipo.startsWith('ev_')) {
    pdvLateralAbrir(PDV_LISTAS[tipo] || 'Eventos', pdvDiaRotulo(_pdvDia));
    await pdvListaEventos(tipo.slice(3));
    if (!_pdvLat.lista) return;
    await pdvLatPrepararFiltros();
    return;
  }
  _pdvLat.rotuloSoma = 'de desconto';
  pdvLateralAbrir(PDV_LISTAS[tipo] || 'Cupons', pdvDiaRotulo(_pdvDia));
  const corpo = document.getElementById('pdvLateralCorpo');
  const r = await apiJson(`/api/pdv/cupons?dia=${encodeURIComponent(_pdvDia)}&limite=5000`, { forceRefresh: true });
  const cupons = r?.cupons || [];
  // desconto por cupom (do resumo): soma e quantos itens
  const desc = new Map();
  (_pdvResumo?.descontos || []).forEach(x => {
    if (!(tipo === 'desc_item' && x.tipo === 'item') && !(tipo === 'desc_subtotal' && x.tipo === 'subtotal')) return;
    const ch = `${x.caixa_id}|${x.cupom}`;
    const a = desc.get(ch) || { v: 0, n: 0, prods: [] };
    a.v += x.valor_centavos; a.n += 1;
    if (x.produto && !a.prods.includes(x.produto)) a.prods.push(x.produto);
    desc.set(ch, a);
  });
  const filtro = {
    cupons_cancelados: k => k.situacao === 'cancelado',
    itens_cancelados: k => Number(k.itens_cancelados) > 0,
    desc_item: k => desc.has(`${k.caixa_id}|${k.cupom}`),
    desc_subtotal: k => desc.has(`${k.caixa_id}|${k.cupom}`),
    abertos: k => k.situacao === 'aberto',
  }[tipo] || (() => false);
  const lista = cupons.filter(filtro);
  const destaque = k => {
    const dd = desc.get(`${k.caixa_id}|${k.cupom}`);
    if (tipo === 'itens_cancelados') return [`${k.itens_cancelados} ${Number(k.itens_cancelados) === 1 ? 'item cancelado' : 'itens cancelados'}`, ''];
    if (dd && tipo === 'desc_item') return [`${dd.n} ${dd.n === 1 ? 'desconto' : 'descontos'} · ${dd.prods.slice(0, 2).join(', ')}${dd.prods.length > 2 ? '…' : ''}`, `− ${pdvMoeda(dd.v)}`];
    if (dd) return ['desconto no subtotal', `− ${pdvMoeda(dd.v)}`];
    return [`${pdvNum(k.itens)} ${Number(k.itens) === 1 ? 'item' : 'itens'}`, ''];
  };
  const somaDesc = lista.reduce((t, k) => t + (desc.get(`${k.caixa_id}|${k.cupom}`)?.v || 0), 0);
  _pdvLat.lista = lista.map(k => ({ k, d: destaque(k), v: desc.get(`${k.caixa_id}|${k.cupom}`)?.v || 0 }));
  await pdvLatPrepararFiltros();
}

async function pdvLatPrepararFiltros() {
  // filtros de loja e PDV (as lojas sao os sites dos caixas)
  const caixas = await pdvCarregarCaixas();
  _pdvLat.caixas = caixas;
  const lojas = [...new Set(caixas.map(c => c.site || 'Sem loja definida'))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  const selLoja = document.getElementById('pdvLatLoja');
  const lojaAntes = selLoja.value;
  selLoja.innerHTML = '<option value="">Todas as lojas</option>' + lojas.map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
  selLoja.value = lojas.includes(lojaAntes) ? lojaAntes : '';
  pdvLatOpcoesCaixa();
  document.getElementById('pdvLatFiltros').hidden = false;
  pdvLatDesenhar();
}

function pdvLatOpcoesCaixa() {
  const loja = document.getElementById('pdvLatLoja').value;
  const sel = document.getElementById('pdvLatCaixa');
  const antes = sel.value;
  const cxs = (_pdvLat.caixas || []).filter(c => !loja || (c.site || 'Sem loja definida') === loja)
    .sort((a, b) => String(a.nome).localeCompare(String(b.nome), 'pt-BR', { numeric: true }));
  sel.innerHTML = '<option value="">Todos os PDVs</option>' + cxs.map(c => `<option value="${esc(c.id)}">${esc(c.nome)}</option>`).join('');
  sel.value = cxs.some(c => c.id === antes) ? antes : '';
}

function pdvLatDesenhar() {
  const corpo = document.getElementById('pdvLateralCorpo');
  const loja = document.getElementById('pdvLatLoja').value;
  const caixa = document.getElementById('pdvLatCaixa').value;
  const daLoja = new Set((_pdvLat.caixas || []).filter(c => !loja || (c.site || 'Sem loja definida') === loja).map(c => c.id));
  const vistos = (_pdvLat.lista || []).filter(x => daLoja.has(x.k.caixa_id) && (!caixa || x.k.caixa_id === caixa));
  const soma = vistos.reduce((t, x) => t + x.v, 0);
  const ev = String(_pdvLat.tipo).startsWith('ev_');
  document.getElementById('pdvLateralSub').textContent = `${pdvDiaRotulo(_pdvDia)} · ${vistos.length} ${ev ? (vistos.length === 1 ? 'registro' : 'registros') : (vistos.length === 1 ? 'cupom' : 'cupons')}`
    + (soma && _pdvLat.rotuloSoma ? ` · ${_pdvLat.rotuloSoma === 'de desconto' ? '− ' : ''}${pdvMoeda(soma)} ${_pdvLat.rotuloSoma}` : '');
  document.getElementById('pdvLatConta').textContent = vistos.length !== (_pdvLat.lista || []).length ? `${vistos.length} de ${_pdvLat.lista.length}` : '';
  pdvPararGravacao();
  _pdvLat.sel = '';
  _pdvLat.atual = null;
  document.querySelector('#pdvLatTela .pdv-videobox').innerHTML = PDV_LAT_VAZIA;
  document.getElementById('pdvLatAgora').innerHTML = '';
  corpo.innerHTML = vistos.length ? vistos.map(x => x.html || pdvLatLinha(x.k, ...x.d)).join('') : '<p class="pdv-nota pdv-c-msg">Nada com esses filtros.</p>';
  corpo.scrollTop = 0;
  lucide.createIcons();
}

// De um aviso (Lojas, Ao vivo): o painel com a tela e so esse cupom, ja tocando no horario do aviso.
async function pdvIrCupom(caixaId, dia, cupom, ts = '') {
  _pdvLat.tipo = '';
  pdvLateralAbrir(`Cupom ${cupom}`, pdvDiaRotulo(dia));
  const r = await apiJson(`/api/pdv/cupons?dia=${encodeURIComponent(dia)}&texto=${encodeURIComponent(cupom)}&limite=50`, { forceRefresh: true });
  const k = (r?.cupons || []).find(x => x.caixa_id === caixaId && x.cupom === cupom);
  const corpo = document.getElementById('pdvLateralCorpo');
  if (!k) { corpo.innerHTML = '<p class="pdv-nota pdv-erro pdv-c-msg">Não consegui achar o cupom.</p>'; return; }
  corpo.innerHTML = pdvLatLinha(k, '', '', ts);
  lucide.createIcons();
  pdvLatSelecionar(corpo.querySelector('[data-pdv-abrir]'), true);
}

// ---------------------------------------------------------------- cupons

// ---------------------------------------------------------------- rankings
// A tela "pdv-cupons" virou Rankings (a chave fica igual por causa das permissoes
// por tela). Operadores ou caixas comparados no periodo: cartoes "top 5" com
// melhores/piores e a tabela completa, que ordena por qualquer coluna.
let _pdvCup = { sel: '' };  // usado pelo pdvAbrirCupom (painel lateral)
const PDV_CUP_SIT = { ...PDV_SITUACAO, aberto: ['aberto', 'pdv-sit-aberto'] };

let _pdvRk = { periodo: '7', loja: '', por: 'operador', dados: null, todos: {} };

function pdvRkDatas(p) {
  const h = pdvHoje();
  if (p === 'hoje') return [h, h];
  if (p === 'ontem') { const o = pdvMudarDia(h, -1); return [o, o]; }
  return [pdvMudarDia(h, -(Number(p) - 1)), h];
}

function pdvRkTempo(s) {
  if (s === null || s === undefined) return '–';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
}

const pdvRkMoeda = v => (v === null || v === undefined) ? '–' : pdvMoeda(v);
const pdvRkDec = v => (v === null || v === undefined) ? '–' : Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 1 });

// melhor: 'alto' = quanto maior melhor; 'baixo' = quanto menor melhor. ruim = o que importa ver sao os piores.
const PDV_RK_CARDS = [
  { id: 'vendido', titulo: 'Quem mais vende', melhor: 'alto', fmt: pdvMoeda, sub: x => `${pdvNum(x.cupons)} ${x.cupons === 1 ? 'cupom' : 'cupons'} · ticket ${pdvMoeda(x.ticket)}` },
  { id: 'cupons', titulo: 'Mais clientes atendidos', melhor: 'alto', fmt: pdvNum, sub: x => `${pdvNum(x.itens)} itens · ${x.dias} ${x.dias === 1 ? 'dia' : 'dias'}` },
  { id: 'vendido_por_hora', titulo: 'Mais venda por hora atendendo', melhor: 'alto', taxa: true, fmt: pdvMoeda, sub: x => `${pdvRkDec(x.horas_atendendo)} h atendendo` },
  { id: 'tempo_mediano_s', titulo: 'Atende cada cliente mais rápido', melhor: 'baixo', taxa: true, fmt: pdvRkTempo, sub: x => `por cliente · ${pdvRkDec(x.itens_por_cupom)} itens em média` },
  { id: 'seg_por_item', titulo: 'Passa os itens mais rápido', melhor: 'baixo', taxa: true, fmt: v => `${pdvRkDec(v)} s/item`, sub: x => `${pdvNum(x.itens)} itens` },
  { id: 'ticket', titulo: 'Maior ticket médio', melhor: 'alto', taxa: true, fmt: pdvMoeda, sub: x => `${pdvNum(x.cupons)} cupons` },
  { id: 'cancelados_por_mil', titulo: 'Cancelamentos de item', melhor: 'baixo', ruim: true, taxa: true, fmt: v => `${pdvRkDec(v)} ‰`, sub: x => `${pdvNum(x.itens_cancelados)} ${x.itens_cancelados === 1 ? 'item' : 'itens'} · ${pdvMoeda(x.valor_cancelado)}` },
  { id: 'descontos', titulo: 'Descontos dados', melhor: 'baixo', ruim: true, fmt: pdvMoeda, sub: x => `${pdvNum(x.cupons)} cupons no período` },
  { id: 'pct_digitado', titulo: 'Itens digitados em vez de bipados', melhor: 'baixo', ruim: true, taxa: true, fmt: v => `${pdvRkDec(v)}%`, sub: x => `${pdvNum(x.digitados)} de ${pdvNum(x.itens)} itens` },
  { id: 'gaveta_fora', titulo: 'Gaveta aberta fora de venda', melhor: 'baixo', ruim: true, fmt: pdvNum, sub: x => `${pdvNum(x.cupons)} cupons no período` },
  { id: 'sem_cadastro', titulo: 'Código sem cadastro', melhor: 'baixo', ruim: true, fmt: pdvNum, sub: x => `${pdvNum(x.itens)} itens no período` },
  { id: 'valor_sangrias', titulo: 'Sangrias', melhor: 'baixo', ruim: true, fmt: pdvMoeda, sub: x => `${pdvNum(x.sangrias)} ${x.sangrias === 1 ? 'retirada' : 'retiradas'}` },
];


async function loadPdvCupons() {
  pdvParar();
  await pdvRkCarregar();
}

async function pdvRkCarregar() {
  const box = document.getElementById('pdvRkBody');
  if (!box) return;
  document.querySelectorAll('#viewPdvCupons [data-pdv-rk-periodo]').forEach(b => b.classList.toggle('ativo', b.dataset.pdvRkPeriodo === _pdvRk.periodo));
  document.querySelectorAll('#viewPdvCupons [data-pdv-rk-por]').forEach(b => b.classList.toggle('ativo', b.dataset.pdvRkPor === _pdvRk.por));
  box.innerHTML = '<p class="pdv-nota pdv-c-msg">Calculando os rankings...</p>';
  const [de, ate] = pdvRkDatas(_pdvRk.periodo);
  const r = await apiJson(`/api/pdv/rankings?de=${de}&ate=${ate}&loja=${encodeURIComponent(_pdvRk.loja)}`, { forceRefresh: true });
  if (!r) { box.innerHTML = '<p class="pdv-nota pdv-erro pdv-c-msg">Não consegui calcular os rankings.</p>'; return; }
  _pdvRk.dados = r;
  const sel = document.getElementById('pdvRkLoja');
  if (sel) {
    sel.innerHTML = '<option value="">Todas as lojas</option>' + (r.lojas || []).map(l => `<option value="${esc(l)}">${esc(l)}</option>`).join('');
    sel.value = _pdvRk.loja;
  }
  const quando = de === ate ? pdvDiaRotulo(de) : `${pdvDiaRotulo(de)} a ${pdvDiaRotulo(ate)}`;
  setText('pdvRkQuando', quando);
  pdvRkDesenhar();
}

function pdvRkLista(card, lista, lado) {
  const min = _pdvRk.dados?.minimo_cupons || 10;
  // supervisor/gerente com poucos cupons nao entra nas comparacoes de venda e velocidade
  const validos = lista.filter(x => x[card.id] !== null && x[card.id] !== undefined && ((!card.taxa && card.ruim) || x.cupons >= min));
  // 'melhores' = a melhor ponta da medida; 'piores' = a outra
  const altoPrimeiro = (card.melhor === 'alto') === (lado === 'melhores');
  return validos.sort((a, b) => altoPrimeiro ? b[card.id] - a[card.id] : a[card.id] - b[card.id]);
}

// Ficha: a posicao da pessoa (ou do caixa) em cada ranking, no mesmo periodo.
function pdvRkFichaFechar() {
  const d = document.getElementById('pdvFicha');
  if (!d) return;
  d.classList.remove('open');
  setTimeout(() => { d.classList.add('hidden'); document.getElementById('pdvFichaFundo')?.classList.add('hidden'); }, 270);
}

function pdvRkFicha(chave) {
  const r = _pdvRk.dados;
  if (!r) return;
  const lista = (_pdvRk.por === 'operador' ? r.operadores : r.caixas) || [];
  const x = lista.find(o => o.chave === chave);
  if (!x) return;
  if (!document.getElementById('pdvFicha')) {
    // fecha so pelo X ou Esc (regra do sistema: clicar fora nao fecha)
    document.body.insertAdjacentHTML('beforeend', `
      <div id="pdvFichaFundo" class="dash-drawer-overlay hidden"></div>
      <aside id="pdvFicha" class="dash-drawer pdv-ficha hidden" aria-label="Ficha">
        <div class="dash-drawer-header">
          <div><h2 class="pdv-l-h2" id="pdvFichaNome"></h2><span class="pdv-l-sub" id="pdvFichaSub"></span></div>
          <button class="icon-button" type="button" id="pdvFichaX" title="Fechar (Esc)"><i data-lucide="x"></i></button>
        </div>
        <div class="pdv-ficha-corpo" id="pdvFichaCorpo"></div>
      </aside>`);
    document.getElementById('pdvFichaX').addEventListener('click', pdvRkFichaFechar);
    document.addEventListener('keydown', ev => {
      if (ev.key === 'Escape' && document.getElementById('pdvFicha')?.classList.contains('open')) pdvRkFichaFechar();
    });
  }
  const [de, ate] = [r.de, r.ate];
  document.getElementById('pdvFichaNome').textContent = x.nome;
  document.getElementById('pdvFichaSub').textContent =
    `${_pdvRk.por === 'operador' ? (x.outros || []).join(', ') : (x.loja || '')} · ${de === ate ? pdvDiaRotulo(de) : `${pdvDiaRotulo(de)} a ${pdvDiaRotulo(ate)}`}`;
  const min = r.minimo_cupons || 10;
  const linhas = PDV_RK_CARDS.map(card => {
    const ord = pdvRkLista(card, lista, 'melhores');
    const i = ord.findIndex(o => o.chave === chave);
    let pos = i + 1;
    if (i > 0) { let k = i; while (k > 0 && ord[k - 1][card.id] === ord[i][card.id]) k--; pos = k + 1; }
    const n = ord.length;
    const cls = i < 0 ? '' : (n > 6 && i >= n - 3 ? 'ruim' : (i < 3 ? 'bom' : ''));
    const pct = i < 0 || n < 2 ? 0 : Math.round(100 * (n - 1 - i) / (n - 1));
    return `<div class="pdv-ficha-linha">
      <span class="pdv-r-pos ${cls}">${i < 0 ? '–' : `${pos}º`}</span>
      <span class="pdv-r-meio"><strong>${esc(card.titulo)}</strong>
        <small>${i < 0 ? `fora deste ranking (menos de ${min} cupons)` : `${pos}º de ${n} · ${esc(card.sub(x))}`}</small>
        ${i < 0 ? '' : `<i class="pdv-r-bar"><b class="${cls === 'ruim' ? 'pdv-r-bar-ruim' : 'pdv-r-bar-bom'}" style="width:${Math.max(3, pct)}%"></b></i>`}</span>
      <span class="pdv-r-val">${esc(card.fmt(x[card.id]))}</span>
    </div>`;
  }).join('');
  document.getElementById('pdvFichaCorpo').innerHTML = `
    <div class="pdv-ficha-topo">
      <div><span class="pdv-l-k">Vendido</span><strong>${esc(pdvMoeda(x.vendido))}</strong></div>
      <div><span class="pdv-l-k">Cupons</span><strong>${pdvNum(x.cupons)}</strong></div>
      <div><span class="pdv-l-k">${_pdvRk.por === 'operador' ? 'Dias' : 'Dias com venda'}</span><strong>${pdvNum(x.dias)}</strong></div>
    </div>
    <p class="pdv-nota pdv-ficha-nota">A barra mostra a posição: cheia = entre os melhores, curta = entre os piores.</p>
    ${linhas}`;
  const d = document.getElementById('pdvFicha');
  d.classList.remove('hidden');
  document.getElementById('pdvFichaFundo').classList.remove('hidden');
  requestAnimationFrame(() => requestAnimationFrame(() => d.classList.add('open')));
  lucide.createIcons();
}

function pdvRkDesenhar() {
  const box = document.getElementById('pdvRkBody');
  const r = _pdvRk.dados;
  if (!box || !r) return;
  const lista = (_pdvRk.por === 'operador' ? r.operadores : r.caixas) || [];
  if (!lista.length) { box.innerHTML = '<p class="pdv-nota pdv-c-msg">Nenhuma venda no período.</p>'; return; }
  const quem = _pdvRk.por === 'operador' ? 'operador' : 'caixa';

  // destaques
  const topo = (id, lado) => pdvRkLista(PDV_RK_CARDS.find(c => c.id === id), lista, lado)[0];
  const dest = [
    ['trophy', 'Campeão de vendas', topo('vendido', 'melhores'), x => pdvMoeda(x.vendido), 'pdv-r-azul'],
    ['timer', 'Atendimento mais rápido', topo('tempo_mediano_s', 'melhores'), x => `${pdvRkTempo(x.tempo_mediano_s)} por cliente`, 'pdv-r-verde'],
    ['x-circle', 'Mais cancelamentos', topo('cancelados_por_mil', 'piores'), x => `${pdvRkDec(x.cancelados_por_mil)} por mil itens`, 'pdv-r-verm'],
    ['percent', 'Mais descontos', topo('descontos', 'piores'), x => pdvMoeda(x.descontos), 'pdv-r-ambar'],
  ];
  const destaques = dest.map(([ic, rot, x, val, cls]) => `
    <section class="pdv-l-card pdv-l-s3 pdv-r-dest pdv-k">
      <span class="pdv-r-ico ${cls}"><i data-lucide="${ic}"></i></span>
      <div class="pdv-l-stat"><span class="pdv-l-k">${rot}</span>
        ${x ? `<button type="button" class="pdv-r-nome-bt pdv-r-nome pdv-l-uma" data-pdv-rk-ficha="${esc(x.chave)}" title="Ver a ficha de ${esc(x.nome)}">${esc(x.nome)}</button>` : '<strong class="pdv-r-nome">–</strong>'}
        <span class="pdv-l-sub pdv-l-uma">${x ? esc(val(x)) : 'sem dados'}</span></div>
    </section>`).join('');

  // cartoes top 5
  // Uma lista so por medida, com a posicao de verdade (1 = melhor; empate = mesma posicao).
  // O cartao mostra os 3 melhores e os 3 piores; "Ver todos" abre a lista inteira.
  const cards = PDV_RK_CARDS.map(card => {
    const ord = pdvRkLista(card, lista, 'melhores');
    const pos = [];
    ord.forEach((x, i) => { pos[i] = i && ord[i - 1][card.id] === x[card.id] ? pos[i - 1] : i + 1; });
    const n = ord.length;
    const todos = !!_pdvRk.todos[card.id];
    const max = Math.max(...ord.map(x => Math.abs(x[card.id] || 0)), 1);
    const linha = i => {
      const x = ord[i];
      const ruim = n > 6 ? i >= n - 3 : false;
      const bom = n > 6 ? i < 3 : true;
      return `<li class="${ruim ? 'pior' : (bom ? 'melhor' : '')}">
          <span class="pdv-r-pos ${ruim ? 'ruim' : (bom ? 'bom' : '')}">${pos[i]}º</span>
          <span class="pdv-r-meio"><button type="button" class="pdv-r-nome-bt pdv-l-uma" data-pdv-rk-ficha="${esc(x.chave)}" title="Ver a ficha de ${esc(x.nome)}">${esc(x.nome)}</button>
            <small class="pdv-l-uma">${esc(card.sub(x))}</small>
            <i class="pdv-r-bar"><b class="${ruim ? 'pdv-r-bar-ruim' : 'pdv-r-bar-bom'}" style="width:${Math.max(3, Math.round(100 * Math.abs(x[card.id] || 0) / max))}%"></b></i></span>
          <span class="pdv-r-val">${esc(card.fmt(x[card.id]))}</span>
        </li>`;
    };
    const idx = [...Array(n).keys()];
    let corpo;
    if (!n) corpo = '<li class="pdv-r-vazio">Sem dados suficientes.</li>';
    else if (todos || n <= 6) corpo = idx.map(linha).join('');
    else {
      const melhores = `<li class="pdv-r-sep">Melhores</li>${idx.slice(0, 3).map(linha).join('')}`;
      const piores = `<li class="pdv-r-sep pdv-r-sep-ruim">Piores</li>${idx.slice(n - 3).map(linha).join('')}`;
      // nos cartoes de problema (cancelamento, desconto...) o que importa vem primeiro: os piores
      corpo = card.ruim ? piores + melhores : melhores + piores;
    }
    return `
    <section class="pdv-l-card pdv-r-s4 pdv-r-card">
      <div class="pdv-l-head"><h2 class="pdv-l-h2 pdv-l-uma" title="${esc(card.titulo)}">${esc(card.titulo)}</h2>
        <span class="pdv-l-sub">${n} no ranking</span></div>
      <ol class="pdv-r-lista">${corpo}</ol>
      ${n > 6 ? `<button type="button" class="pdv-l-link" data-pdv-rk-todos="${card.id}">${todos ? 'Mostrar só os 3 melhores e os 3 piores' : `Ver a lista inteira (${n})`}</button>` : ''}
      ${card.taxa || !card.ruim ? `<small class="pdv-r-nota">só quem atendeu ${r.minimo_cupons || 10} cupons ou mais</small>` : ''}
    </section>`;
  }).join('');

  box.innerHTML = `<div class="pdv-l-grade">${destaques}${cards}</div>
    <p class="pdv-nota">Clique no nome de qualquer ${quem} para ver a posição dele em todos os rankings.</p>`;
  lucide.createIcons();
}

async function pdvAbrirCupom(caixaId, dia, cupom, silencioso = false, alvo = null) {
  // alvo = onde desenhar (painel lateral); sem alvo, o painel da tela Cupons
  const box = alvo || document.getElementById('pdvCupomDetalhe');
  if (!box) return null;
  const chave = `${caixaId}|${dia}|${cupom}`;
  if (!silencioso) pdvPararGravacao();
  if (!alvo) {
    _pdvCup.sel = chave;
    document.querySelectorAll('#pdvCupLista [data-pdv-cupom]').forEach(tr => tr.classList.toggle('ativa', tr.dataset.pdvCupom === chave));
  }
  if (!silencioso) box.innerHTML = '<p class="pdv-nota pdv-c-msg">Abrindo o cupom...</p>';
  const r = await apiJson(`/api/pdv/cupons/${encodeURIComponent(caixaId)}/${dia}/${encodeURIComponent(cupom)}`, { forceRefresh: true });
  if (!alvo && _pdvCup.sel !== chave) return null;  // trocou de cupom enquanto carregava
  if (alvo && !alvo.isConnected) return null;
  if (!r?.cupom) { if (!silencioso) box.innerHTML = '<p class="pdv-nota pdv-erro pdv-c-msg">Não consegui abrir o cupom.</p>'; return null; }
  const k = r.cupom;
  const itens = r.itens || [];
  const linha = r.linha_do_tempo || [];
  const canc = linha.filter(e => e.tipo === 'CIT');
  const desc = linha.filter(e => e.tipo === 'DIT' || e.tipo === 'DAS');
  const fim = k.fechado_em ? `${k.situacao === 'cancelado' ? 'cancelado' : 'fechado'} às ${esc(pdvHora(k.fechado_em))}` : 'ainda aberto';
  const modos = ['scanner', 'manual', 'menu'].map(m => [m, itens.filter(i => i.modo === m).length]).filter(x => x[1]);
  box.dataset.aberto = k.situacao === 'aberto' ? '1' : '0';
  box.innerHTML = `
    <div class="pdv-c-det-topo">
      <div><span class="pdv-l-k">Cupom</span><h2 class="pdv-c-num">${esc(k.cupom)}</h2></div>
      ${pdvChip(PDV_CUP_SIT, k.situacao)}
    </div>
    <dl class="pdv-c-dados">
      <div><dt>Caixa</dt><dd>${esc(r.caixa.nome)}</dd></div>
      <div><dt>Operador</dt><dd title="${esc(k.operador)}">${esc(k.operador || '-')}</dd></div>
      <div><dt>Horário</dt><dd>${esc(pdvHora(k.aberto_em))} · ${fim}</dd></div>
      <div><dt>Pagamento</dt><dd title="${esc(k.pagamento || '')}">${esc(k.pagamento || 'sem pagamento')}</dd></div>
    </dl>
    <div class="pdv-c-total"><span>${pdvNum(itens.length)} ${itens.length === 1 ? 'item' : 'itens'}${modos.length ? ' · ' + modos.map(([m, n]) => `${n} ${PDV_MODOS[m][0]}${n === 1 ? '' : 's'}`).join(' · ') : ''}</span>
      <strong>${esc(pdvMoeda(k.total_centavos))}</strong></div>
    <button class="primary-action pdv-c-btvideo" type="button" data-pdv-video="${esc(k.aberto_em)}"><i data-lucide="video"></i> Ver vídeo do cupom</button>
    <div class="pdv-videobox"></div>
    ${canc.length ? `<div class="pdv-c-secao"><span class="pdv-l-k pdv-c-k-verm">Itens cancelados (${canc.length})</span>
      ${canc.map(e => `<div class="pdv-c-item pdv-c-item-canc">
        <span class="pdv-hora">${esc(pdvHora(e.ts))}</span>
        <div><strong>${esc(e.descricao || e.codigo || 'item')}</strong><small>${esc(e.codigo || '')}</small></div>
        <span class="pdv-valor">${esc(pdvMoeda(e.valor_centavos))}</span>
        <button class="pdv-c-play" type="button" data-pdv-video="${esc(e.ts)}" title="Vídeo deste cancelamento"><i data-lucide="play"></i></button>
      </div>`).join('')}</div>` : ''}
    ${desc.length ? `<div class="pdv-c-secao"><span class="pdv-l-k pdv-l-k-ambar">Descontos (${pdvMoeda(desc.reduce((s, e) => s + Math.abs(e.valor_centavos || 0), 0))})</span>
      ${desc.map(e => `<div class="pdv-c-item">
        <span class="pdv-hora">${esc(pdvHora(e.ts))}</span>
        <div><strong>${e.tipo === 'DIT' ? esc(e.descricao || e.codigo || 'item') : 'No subtotal do cupom'}</strong><small>${e.tipo === 'DIT' ? `desconto no item · ${esc(e.codigo || '')}` : 'desconto no cupom inteiro'}</small></div>
        <span class="pdv-valor">− ${esc(pdvMoeda(Math.abs(e.valor_centavos || 0)))}</span>
        <button class="pdv-c-play" type="button" data-pdv-video="${esc(e.ts)}" title="Vídeo deste desconto"><i data-lucide="play"></i></button>
      </div>`).join('')}</div>` : ''}
    <div class="pdv-c-secao"><span class="pdv-l-k">Itens</span>
      ${itens.map(i => `<div class="pdv-c-item">
        <span class="pdv-hora">${esc(pdvHora(i.ts))}</span>
        <div><strong>${esc(i.descricao || i.codigo)}</strong><small>${esc(i.codigo)}${Number(i.quant) && Number(i.quant) !== 1 ? ` · ${esc(String(i.quant).replace('.', ','))} un` : ''}</small></div>
        ${i.modo === 'scanner' ? '' : pdvChip(PDV_MODOS, i.modo)}
        <span class="pdv-valor">${esc(pdvMoeda(i.valor_centavos))}</span>
        <button class="pdv-c-play" type="button" data-pdv-video="${esc(i.ts)}" title="Vídeo deste item"><i data-lucide="play"></i></button>
      </div>`).join('') || '<p class="pdv-nota">Nenhum item ainda.</p>'}
    </div>
    <details class="pdv-c-secao pdv-c-tempo"><summary>Tudo o que aconteceu no caixa (${linha.length})</summary>
      ${linha.map(e => `<div class="pdv-evento pdv-ev-${esc(e.tipo)}">
        <span class="pdv-hora">${esc(pdvHora(e.ts))}</span><span>${esc(pdvEventoTexto(e))}</span></div>`).join('')}
    </details>`;
  box.querySelectorAll('[data-pdv-video]').forEach(b => b.addEventListener('click', () => pdvVerVideo(caixaId, b.dataset.pdvVideo, box)));
  lucide.createIcons();
  if (silencioso || alvo) return r;
  // tela estreita: o painel fica embaixo da lista, entao rola ate ele
  if (window.matchMedia('(max-width: 1180px)').matches) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
  else box.scrollTop = 0;
  return r;
}

const PDV_EVENTO_NOME = {
  ABRECUPOM: 'Cupom aberto', VIT: 'Item', CIT: 'Item cancelado', SBT: 'Subtotal', FIN: 'Pagamento',
  TRC: 'Troco', FECHACUPOM: 'Cupom fechado', CCV: 'Cupom cancelado', CCG: 'Cancelamento de cupom anterior',
  SUP: 'Liberação de supervisor', SUPERVISOR: 'Supervisor', GER: 'Tecla de gerente', GAV: 'Gaveta aberta',
  SGR: 'Sangria', DIT: 'Desconto no item', DST: 'Subtotal com desconto', DAS: 'Desconto no subtotal',
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

// antes = quantos segundos antes do momento o video comeca
async function pdvVerVideo(caixaId, ts, raiz = document, antes = 15) {
  const box = raiz.querySelector('.pdv-videobox');
  if (!box) return;
  pdvPararGravacao();
  box.innerHTML = '<p class="pdv-nota">Calculando o horário no gravador...</p>';
  const j = await apiJson(`/api/pdv/video/${encodeURIComponent(caixaId)}?ts=${encodeURIComponent(ts)}&antes=${antes}&depois=45`, { forceRefresh: true });
  if (!j?.host) { box.innerHTML = '<p class="pdv-nota pdv-erro">Este caixa ainda não tem gravador e canal configurados.</p>'; return null; }
  const aviso = j.relogio_medido ? `gravador ${j.gravador_menos_caixa_s >= 0 ? '+' : ''}${j.gravador_menos_caixa_s} s em relação ao caixa`
    : 'relógio do gravador ainda não medido: o vídeo pode estar alguns segundos deslocado';
  box.innerHTML = `
    <div class="pdv-gravacao">
      <video class="pdv-video pdv-grav-video" autoplay muted playsinline controls></video>
      <p class="pdv-nota pdv-grav-aviso">Abrindo a gravação do gravador...</p>
    </div>
    <p class="pdv-nota">Começa às ${esc(j.inicio.slice(11))} no gravador, ${antes} s antes do momento (caixa ${esc(j.momento_caixa.slice(11))} · gravador ${esc(j.momento_gravador.slice(11))}) · ${esc(aviso)}.</p>`;
  const video = box.querySelector('.pdv-grav-video');
  if (!video || typeof mountLiveStream !== 'function') return null;
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
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
      const a = box.querySelector('.pdv-grav-aviso');
      if (!a) return;
      a.hidden = !texto;
      if (texto) a.textContent = texto;
    },
  });
  // saiu da tela (ou o cupom foi trocado): para de puxar video pelo link da loja
  _pdvGravacaoTimer = setInterval(() => {
    // saiu da tela, fechou o painel ou trocou de cupom
    if (!video.isConnected || video.offsetParent === null) pdvPararGravacao();
  }, 2000);
  // o video comeca `antes` s antes do momento, no relogio do caixa
  const m = new Date(String(j.momento_caixa).replace(' ', 'T')).getTime();
  return { video, inicioCaixa: Number.isNaN(m) ? null : m - antes * 1000 };
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
  // Rankings: periodo, loja, operador/caixa, melhores/piores, ver todos e ordem da tabela
  document.getElementById('viewPdvCupons')?.addEventListener('click', ev => {
    const per = ev.target.closest('[data-pdv-rk-periodo]');
    if (per) { _pdvRk.periodo = per.dataset.pdvRkPeriodo; pdvRkCarregar(); return; }
    const por = ev.target.closest('[data-pdv-rk-por]');
    if (por) {
      _pdvRk.por = por.dataset.pdvRkPor;
      document.querySelectorAll('#viewPdvCupons [data-pdv-rk-por]').forEach(b => b.classList.toggle('ativo', b === por));
      pdvRkDesenhar(); return;
    }
    const todos = ev.target.closest('[data-pdv-rk-todos]');
    if (todos) { const id = todos.dataset.pdvRkTodos; _pdvRk.todos[id] = !_pdvRk.todos[id]; pdvRkDesenhar(); return; }
    const fi = ev.target.closest('[data-pdv-rk-ficha]');
    if (fi) pdvRkFicha(fi.dataset.pdvRkFicha);
  });
  document.getElementById('pdvRkLoja')?.addEventListener('change', ev => { _pdvRk.loja = ev.target.value; pdvRkCarregar(); });
  document.querySelector('[data-settings-tab="pdv"]')?.addEventListener('click', () => loadPdvConfig());
});
