// Painel do Dono > Saude do sistema.
// Faixa de situacao, maquina, servicos e tempo de resposta por rota. A pagina
// atualiza sozinha enquanto esta aberta e para quando o dono sai dela.

const SAUDE_ATUALIZA_MS = 30000;
let _saudeJanela = 60;
let _saudeTimer = null;
let _saudeDados = null;

function _saudeBytes(valor) {
  if (valor === null || valor === undefined) return '—';
  const gb = valor / 1073741824;
  return gb >= 100 ? `${Math.round(gb)} GB` : `${gb.toFixed(1).replace('.', ',')} GB`;
}

function _saudeMs(valor) {
  if (valor === null || valor === undefined) return '—';
  if (valor > 0 && valor < 1) return '< 1 ms';
  return valor >= 1000 ? `${(valor / 1000).toFixed(1).replace('.', ',')} s` : `${Math.round(valor)} ms`;
}

function _saudeNum(valor, casas = 0) {
  if (valor === null || valor === undefined) return '—';
  return (Number(valor) || 0).toLocaleString('pt-BR', { minimumFractionDigits: casas, maximumFractionDigits: casas });
}

function _saudeTempoAtivo(segundos) {
  const dias = Math.floor(segundos / 86400);
  const horas = Math.floor((segundos % 86400) / 3600);
  return dias ? `${dias} d ${horas} h` : `${horas} h`;
}

function _saudeHora(ts) {
  return new Date(ts * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

// Tres niveis, sempre com o mesmo corte da avaliacao do servidor.
function _saudeNivelUso(pct, atencao = 80, critico = 90) {
  if (pct === null || pct === undefined) return '';
  if (pct >= critico) return 'saude-critico';
  return pct >= atencao ? 'saude-atencao' : '';
}

function _saudeBarra(pct, classe = '') {
  const largura = Math.max(0, Math.min(100, Number(pct) || 0));
  return `<span class="saude-barra ${classe}"><i style="width:${largura}%"></i></span>`;
}

function _saudeGrafico(serie) {
  const pontos = (serie || []);
  const maior = Math.max(1000, ...pontos.map(p => p.p95_ms || 0));
  const barras = pontos.map(p => {
    const altura = p.p95_ms ? Math.max(4, Math.round(Math.sqrt(p.p95_ms / maior) * 100)) : 2;
    const classe = p.erros_5xx ? 'erro' : (p.p95_ms >= 2500 ? 'lenta' : '');
    const texto = `${_saudeHora(p.ts)}: ${p.requisicoes} req, 95% em até ${_saudeMs(p.p95_ms)}${p.erros_5xx ? `, ${p.erros_5xx} erro(s)` : ''}`;
    return `<i class="${classe}" style="height:${altura}%" title="${esc(texto)}"></i>`;
  }).join('');
  return `<div class="saude-grafico" role="img" aria-label="Tempo de resposta por minuto na última hora">${barras}</div>`;
}

function _saudeFaixa(d) {
  const situacao = d.situacao || {};
  const http = d.http || {};
  const memoria = d.maquina?.memoria || {};
  const frase = {
    ok: 'Tudo funcionando normalmente',
    atencao: 'Atenção: há pontos para olhar',
    critico: 'Problema no sistema',
  }[situacao.nivel] || 'Situação desconhecida';
  const motivos = (situacao.motivos || []).slice(0, 4).map(m => `<li>${esc(m)}</li>`).join('');
  const metrica = (rotulo, valor) => `<div><small>${esc(rotulo)}</small><strong>${esc(valor)}</strong></div>`;
  return `
    <div class="saude-faixa saude-faixa-${esc(situacao.nivel || 'critico')}">
      <div class="saude-faixa-texto">
        <small>Situação agora · atualizado às ${esc(_saudeHora(d.gerado_em))}</small>
        <h2>${esc(frase)}</h2>
        ${motivos ? `<ul>${motivos}</ul>` : '<p>Nenhum limite ultrapassado.</p>'}
      </div>
      <div class="saude-faixa-metricas">
        ${metrica('Resposta (95%)', _saudeMs(http.p95_ms))}
        ${metrica('Requisições', _saudeNum(http.requisicoes))}
        ${metrica('Erros', _saudeNum(http.erros_5xx))}
        ${metrica('Memória livre', memoria.disponivel ? _saudeBytes(memoria.disponivel) : '—')}
      </div>
      ${_saudeGrafico(http.serie)}
    </div>`;
}

function _saudeMaquina(d) {
  const m = d.maquina || {};
  if (m.ok === false) return '<p class="saude-vazio">Não consegui ler os dados da máquina.</p>';
  const memoria = m.memoria || {};
  const usadaPct = memoria.disponivel_pct === null || memoria.disponivel_pct === undefined ? null : 100 - memoria.disponivel_pct;
  const carga = m.carga?.[0];
  const cargaPct = carga === undefined ? null : 100 * carga / (m.nucleos || 1);
  const linha = (nome, valor, pct, classe) => `<tr><td>${esc(nome)}</td><td class="saude-num">${esc(valor)}</td><td>${_saudeBarra(pct, classe)}</td></tr>`;
  const espacos = Array.isArray(d.espacos) ? d.espacos : [];
  return `<table class="data-table saude-tabela"><colgroup><col><col class="saude-col-valor"><col class="saude-col-barra"></colgroup><tbody>
    ${linha(`Carga (${m.nucleos || '?'} núcleos)`, _saudeNum(carga, 1), cargaPct, _saudeNivelUso(cargaPct, 100, 200))}
    ${linha('Memória em uso', `${_saudeNum(usadaPct)}%`, usadaPct, _saudeNivelUso(usadaPct))}
    ${linha('Swap em uso', `${_saudeBytes(memoria.swap_usado)} de ${_saudeBytes(memoria.swap_total)}`, memoria.swap_pct, _saudeNivelUso(memoria.swap_pct, 50, 90))}
    ${linha('Espera por disco', `${_saudeNum(m.espera_disco_pct)}%`, m.espera_disco_pct, _saudeNivelUso(m.espera_disco_pct, 15, 30))}
    ${espacos.map(e => linha(e.nome, `${_saudeBytes(e.usado)} de ${_saudeBytes(e.total)}`, e.usado_pct, _saudeNivelUso(e.usado_pct))).join('')}
    <tr><td>Máquina ligada há</td><td class="saude-num">${esc(_saudeTempoAtivo(m.ativa_desde_s || 0))}</td><td></td></tr>
  </tbody></table>`;
}

function _saudeServicos(d) {
  const banco = d.banco || {};
  const linhas = (d.servicos || []).map(s => `<tr><td><span class="saude-ponto ${s.ok ? 'ok' : 'erro'}"></span>${esc(s.nome)}</td><td class="saude-num">${s.ok ? esc(_saudeMs(s.ms)) : 'sem resposta'}</td></tr>`).join('');
  const dadosBanco = banco.ok && banco.tipo === 'postgres' ? `
    <tr><td>Tamanho do banco</td><td class="saude-num">${esc(_saudeBytes(banco.tamanho))}</td></tr>
    <tr><td>Conexões do banco</td><td class="saude-num">${esc(`${banco.conexoes} de ${banco.limite}`)}</td></tr>
    <tr><td>Consulta mais longa agora</td><td class="saude-num">${esc(`${_saudeNum(banco.consulta_mais_longa_s, 1)} s`)}</td></tr>` : '';
  return `<table class="data-table saude-tabela"><colgroup><col><col class="saude-col-valor"></colgroup><tbody>${linhas}${dadosBanco}</tbody></table>`;
}

function _saudeDiscos(d) {
  const discos = d.maquina?.discos || [];
  if (!discos.length) return '<p class="saude-vazio">Sem leitura de disco.</p>';
  return `<table class="data-table saude-tabela"><thead><tr><th>Disco</th><th class="saude-num">Uso</th><th class="saude-num">Leituras/s</th><th class="saude-num">Escritas/s</th><th class="saude-num">Espera (leitura)</th><th class="saude-num">Espera (escrita)</th></tr></thead><tbody>
    ${discos.map(x => `<tr><td>${esc(x.nome)}</td><td class="saude-num"><span class="${_saudeNivelUso(x.uso_pct)}">${esc(_saudeNum(x.uso_pct))}%</span></td><td class="saude-num">${esc(_saudeNum(x.leituras_s))}</td><td class="saude-num">${esc(_saudeNum(x.escritas_s))}</td><td class="saude-num">${esc(_saudeMs(x.espera_leitura_ms))}</td><td class="saude-num">${esc(_saudeMs(x.espera_escrita_ms))}</td></tr>`).join('')}
  </tbody></table>`;
}

function _saudeRotas() {
  const corpo = document.getElementById('saudeRotasBody');
  if (!corpo || !_saudeDados) return;
  const busca = (document.getElementById('saudeRotasBusca')?.value || '').trim().toLowerCase();
  const ordem = document.getElementById('saudeRotasOrdem')?.value || 'p95_ms';
  const linhas = (_saudeDados.http?.rotas || [])
    .filter(r => !busca || `${r.metodo} ${r.rota}`.toLowerCase().includes(busca))
    .sort((a, b) => ordem === 'rota' ? String(a.rota).localeCompare(String(b.rota), 'pt-BR', { numeric: true }) : (b[ordem] || 0) - (a[ordem] || 0));
  corpo.innerHTML = linhas.length ? linhas.map(r => `<tr>
      <td class="saude-rota" title="${esc(r.rota)}">${r.metodo ? `<b>${esc(r.metodo)}</b> ` : ''}${esc(r.rota)}</td>
      <td class="saude-num">${esc(_saudeNum(r.requisicoes))}</td>
      <td class="saude-num">${esc(_saudeMs(r.media_ms))}</td>
      <td class="saude-num">${esc(_saudeMs(r.p95_ms))}</td>
      <td class="saude-num">${esc(_saudeMs(r.max_ms))}</td>
      <td class="saude-num">${esc(_saudeNum(r.lentas))}</td>
      <td class="saude-num ${r.erros_5xx ? 'saude-critico' : ''}">${esc(_saudeNum(r.erros_5xx))}</td>
    </tr>`).join('') : '<tr><td colspan="7" class="saude-vazio">Nenhuma rota nesta janela.</td></tr>';
}

function _saudeErros(d) {
  const erros = d.http?.erros || [];
  if (!erros.length) return '<p class="saude-vazio">Nenhum erro de servidor nesta janela.</p>';
  return `<table class="data-table saude-tabela"><thead><tr><th>Hora</th><th>Rota</th><th class="saude-num">Código</th><th class="saude-num">Tempo</th></tr></thead><tbody>
    ${erros.map(e => `<tr><td>${esc(_saudeHora(e.ts))}</td><td class="saude-rota" title="${esc(e.rota)}"><b>${esc(e.metodo)}</b> ${esc(e.rota)}</td><td class="saude-num saude-critico">${esc(e.status)}</td><td class="saude-num">${esc(_saudeMs(e.ms))}</td></tr>`).join('')}
  </tbody></table>`;
}

function _saudeRender(d) {
  _saudeDados = d;
  const preencher = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
  preencher('saudeFaixa', _saudeFaixa(d));
  preencher('saudeMaquina', _saudeMaquina(d));
  preencher('saudeServicos', _saudeServicos(d));
  preencher('saudeDiscos', _saudeDiscos(d));
  preencher('saudeErros', _saudeErros(d));
  const total = d.http?.rotas_total || 0;
  const desde = d.http?.desde ? new Date(d.http.desde * 1000).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : '';
  setText('saudeRotasResumo', `${total} rota(s) nesta janela · contagem desde ${desde}, quando a API iniciou.`);
  _saudeRotas();
}

async function loadOwnerHealth() {
  clearTimeout(_saudeTimer);
  try {
    const resposta = await api(`/api/monitoring/saude?janela=${_saudeJanela}`, { cache: 'no-store' });
    if (resposta) {
      const dados = await resposta.json().catch(() => ({}));
      if (!resposta.ok) throw new Error(dados.detail || `Erro ${resposta.status}`);
      _saudeRender(dados);
    }
  } catch (erro) {
    const faixa = document.getElementById('saudeFaixa');
    if (faixa) {
      faixa.innerHTML = `<div class="saude-faixa saude-faixa-critico"><div class="saude-faixa-texto"><small>Situação agora</small><h2>Não consegui consultar a saúde do sistema</h2><p>${esc(erro?.message || 'Sem resposta do servidor.')}</p></div></div>`;
    }
  }
  if (_currentView === 'owner-health' && !document.hidden) {
    _saudeTimer = setTimeout(loadOwnerHealth, SAUDE_ATUALIZA_MS);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btnOwnerHealthRefresh')?.addEventListener('click', loadOwnerHealth);
  document.getElementById('saudeRotasBusca')?.addEventListener('input', _saudeRotas);
  document.getElementById('saudeRotasOrdem')?.addEventListener('change', _saudeRotas);
  document.getElementById('saudeJanela')?.addEventListener('change', evento => {
    _saudeJanela = Number(evento.target.value) || 60;
    loadOwnerHealth();
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && _currentView === 'owner-health') loadOwnerHealth();
  });
});
