// Gravador aberto > Canais, Discos e Historico (parte 5 do mini DVR).
//
// Canais: o caso que mais custa tempo no campo e o canal SEM IMAGEM porque a
// camera mudou de IP. O gravador continua tentando o IP velho; o SightOps sabe
// o MAC da camera daquele canal (inventario) e o proprio gravador acha na rede
// quem responde com esse MAC. Daqui sai "Apontar canal 07 para 10.10.10.157".
// Tambem: cameras que o gravador enxerga na rede e nao estao em canal nenhum.
//
// Discos: uso de cada disco e quantos dias o gravador guarda (retencao real,
// lida pela gravacao mais antiga em /api/nvr/driver/resumo).
//
// Historico: o que o SightOps mudou no gravador (correcoes de configuracao e
// edicoes de canal, com quem e quando, e Desfazer quando der) e as quedas e
// voltas das cameras dos canais no monitoramento.
//
// EQUIPAMENTO VIVO: apontar, renomear e desfazer mudam o gravador do cliente.
// Cada um pede confirmacao. Mora fora do deploy.js de proposito: entra pelo
// recRegistrarSecao, enquanto a parte 4 (Gravacoes) e feita em outro arquivo.

let _g5 = null;   // {chave, busca:{...}, hist:{...}, renomeando, armado, trabalhando}

function g5Estado() {
  const chave = recChave();
  if (!_g5 || _g5.chave !== chave) {
    _g5 = { chave, busca: null, hist: null, macs: null, renomeando: 0, armado: '', trabalhando: '', senhaPara: 0 };
  }
  return _g5;
}

function g5Mac(v) { return String(v || '').toLowerCase().replace(/[^0-9a-f]/g, ''); }
function g5Num(c) { return String(c).padStart(2, '0'); }
function g5Data(iso) {
  const t = new Date(String(iso || '').replace(' ', 'T'));
  if (isNaN(t)) return String(iso || '');
  const p = n => String(n).padStart(2, '0');
  return `${p(t.getDate())}/${p(t.getMonth() + 1)} ${p(t.getHours())}:${p(t.getMinutes())}`;
}

// Linhas do inventario do SightOps para ESTE gravador (mesmo host e conector):
// e de la que vem o MAC da camera de cada canal e o estado medido.
function g5Inventario(d) {
  const alvo = recAvAlvo();
  const itens = (typeof _deployStandaloneRecorderSavedItems !== 'undefined' ? _deployStandaloneRecorderSavedItems : []) || [];
  const item = itens.find(i => i.host === (d.host || alvo.host) && String(i.connectorId || '') === String(alvo.connector_id || ''))
    || itens.find(i => i.host === (d.host || alvo.host));
  const porCanal = {};
  (item?.rows || []).forEach(r => { porCanal[Number(r.channel || r.ch || 0)] = r; });
  return porCanal;
}

function g5Imagem(c, inv) {
  const st = String(inv?.status || '').toLowerCase();
  if (!c.ip) return 'livre';
  if (c.online === false || ['camera_offline', 'offline', 'nvr_offline', 'sem_imagem'].includes(st) || String(inv?.video_loss) === 'True' || inv?.video_loss === true) return 'sem';
  if (c.online === true || st === 'online') return 'ok';
  return 'semleitura';
}

// MAC de cada camera pelo INVENTARIO DE CAMERAS (pelo IP do canal). O
// camera_mac das linhas do gravador estava errado em 30 de 31 canais no
// gravador de teste (16/10/2026): com ele, um canal sem imagem seria apontado
// para a camera de OUTRO canal.
async function g5Macs(d) {
  const g = g5Estado();
  if (g.macs) return;
  g.macs = { carregando: true, mapa: {} };
  try {
    const ips = (d.canais || []).map(c => c.ip).filter(Boolean).join(',');
    const res = await api(`/api/deployments/recorder-macs?${new URLSearchParams({ ips })}`);
    const j = await res.json().catch(() => ({}));
    if (_g5 === g) g.macs = { carregando: false, mapa: (res.ok && j.macs) || {} };
  } catch (e) {
    if (_g5 === g) g.macs = { carregando: false, mapa: {}, erro: e.message };
  }
  if (_recSec === 'canais') recPintarApp();
}

// Canal sem imagem cuja camera (pelo MAC) responde em outro IP na rede.
function g5Mudaram(d) {
  const g = g5Estado();
  const achadas = g.busca?.cameras || [];
  if (!achadas.length || !g.macs || g.macs.carregando) return [];
  const inv = g5Inventario(d);
  const porMac = new Map(achadas.filter(a => g5Mac(a.mac)).map(a => [g5Mac(a.mac), a]));
  const saida = [];
  (d.canais || []).forEach(c => {
    if (!c.ip || g5Imagem(c, inv[c.canal]) !== 'sem') return;
    const macTxt = g.macs.mapa[c.ip] || '';
    const mac = g5Mac(macTxt);
    const achou = mac && porMac.get(mac);
    if (achou && achou.ip && achou.ip !== c.ip) saida.push({ canal: c, mac: macTxt, ip: achou.ip, cam: achou });
  });
  return saida;
}

// Cameras na rede do gravador fora de canal nenhum (e que nao sao as que so
// mudaram de IP de um canal ja existente).
function g5ForaDeCanal(d, mudaram) {
  const g = g5Estado();
  const ipsCanal = new Set((d.canais || []).map(c => c.ip).filter(Boolean));
  const jaUsadas = new Set(mudaram.map(m => m.ip));
  return (g.busca?.cameras || []).filter(a => a.ip && !ipsCanal.has(a.ip) && !jaUsadas.has(a.ip) && !a.no_gravador);
}

async function g5Buscar() {
  const g = g5Estado();
  if (g.busca?.carregando) return;
  const alvo = recAvAlvo();
  g.busca = { carregando: true, erro: '', cameras: [] };
  recPintarApp();
  try {
    const p = deployStandaloneRecorderPayload();
    const res = await api('/api/deployments/recorder-buscar-cameras', {
      method: 'POST',
      body: JSON.stringify({ recorder_host: alvo.host, recorder_http_port: alvo.http_port, connector_id: alvo.connector_id, marca: 'auto', site: p.site || '' }),
    });
    const j = await res.json().catch(() => ({}));
    if (_g5 !== g) return;
    if (!res.ok || j.ok === false) throw new Error(j.detail === 'SEM_CREDENCIAL' ? 'Sem senha salva deste gravador.' : (j.detail || `HTTP ${res.status}`));
    g.busca = { carregando: false, erro: '', cameras: Array.isArray(j.cameras) ? j.cameras : [], quando: new Date() };
    // O "+ Adicionar camera" do deploy.js oferece as cameras achadas daqui.
    if (typeof _recCamerasAchadas !== 'undefined') _recCamerasAchadas = g.busca.cameras;
  } catch (e) {
    if (_g5 === g) g.busca = { carregando: false, erro: e.message, cameras: [] };
  }
  recPintarApp();
}

// ---------------------------------------------------------------- Canais
function g5SecCanais(d) {
  const g = g5Estado();
  const canais = d.canais || [];
  const inv = g5Inventario(d);
  const comCam = canais.filter(c => c.ip);
  const sem = comCam.filter(c => g5Imagem(c, inv[c.canal]) === 'sem');
  const livres = canais.filter(c => !c.ip);
  const mudaram = g5Mudaram(d);
  const fora = g5ForaDeCanal(d, mudaram);
  const primeiroLivre = livres[0]?.canal || 0;

  const busca = !g.busca ? `<div class="g5-aviso">
        <div><b>${sem.length ? `${sem.length} cana${sem.length === 1 ? 'l' : 'is'} sem imagem.` : 'Câmera mudou de IP?'}</b>
        O gravador procura na rede dele quem responde com o MAC de cada câmera e mostra para onde ela foi.</div>
        <button class="acao forte" type="button" data-g5-buscar>Procurar câmeras na rede</button></div>`
    : g.busca.carregando ? '<div class="g5-aviso"><div>Procurando na rede do gravador… leva alguns segundos.</div></div>'
    : g.busca.erro ? `<div class="g5-aviso erro"><div>Não deu para procurar: ${esc(g.busca.erro)}</div><button class="acao" type="button" data-g5-buscar>Tentar de novo</button></div>`
    : '';

  const cartoes = mudaram.map(m => {
    const n = g5Num(m.canal.canal);
    const armado = g.armado === `apontar-${m.canal.canal}`;
    return `<div class="g5-cartao">
      <div class="g5-cartao-txt"><b>Canal ${n}${m.canal.nome ? ' · ' + esc(m.canal.nome) : ''}: sem imagem porque a câmera mudou de IP</b>
        <span>O gravador tenta <span class="mono">${esc(m.canal.ip)}</span>; a câmera com o mesmo MAC (<span class="mono">${esc(m.mac)}</span>) responde em <b class="mono">${esc(m.ip)}</b>.</span>
        ${g.senhaPara === m.canal.canal ? `<span class="g5-senha">Não há senha salva para esta câmera. Senha da câmera: <input type="password" data-g5-senha="${m.canal.canal}" autocomplete="off"></span>` : ''}</div>
      <button class="acao ${armado ? 'perigo' : 'forte'}" type="button" data-g5-apontar="${m.canal.canal}" ${g.trabalhando ? 'disabled' : ''}>
        ${g.trabalhando === `apontar-${m.canal.canal}` ? 'Enviando ao gravador…' : armado ? `Confirmar: canal ${n} → ${esc(m.ip)}` : `Apontar canal ${n} para ${esc(m.ip)}`}</button>
    </div>`;
  }).join('');

  const semMudanca = g.busca && !g.busca.carregando && !g.busca.erro && !mudaram.length && sem.length
    ? `<div class="g5-aviso"><div>Nenhum canal sem imagem tem a câmera em outro IP: ${sem.length === 1 ? 'a câmera dele não respondeu' : 'as câmeras deles não responderam'} na rede pelo mesmo MAC. Pode ser câmera desligada, cabo ou PoE.</div><button class="acao" type="button" data-g5-buscar>Procurar de novo</button></div>` : '';

  const foraHtml = fora.length ? `<details class="g5-fora" ${mudaram.length ? '' : 'open'}><summary>${fora.length} câmera${fora.length === 1 ? '' : 's'} na rede fora de canal nenhum${primeiroLivre ? ` · ${livres.length} cana${livres.length === 1 ? 'l livre' : 'is livres'}` : ' · nenhum canal livre'}</summary>
      <div class="rolo"><table><thead><tr><th>IP</th><th>Modelo</th><th>MAC</th><th></th></tr></thead><tbody>
      ${fora.map(a => `<tr><td class="n">${esc(a.ip)}</td><td>${esc([a.fabricante, a.modelo].filter(Boolean).join(' ') || '-')}</td><td class="n">${esc(a.mac || '-')}</td>
        <td>${primeiroLivre ? `<button class="mini" type="button" data-rec-add="${primeiroLivre}" title="Abre o cadastro no canal ${g5Num(primeiroLivre)}">Adicionar no canal ${g5Num(primeiroLivre)}</button>` : ''}</td></tr>`).join('')}
      </tbody></table></div></details>` : '';

  const linha = c => {
    const r = inv[c.canal];
    const img = g5Imagem(c, r);
    const grava = !c.ip ? '' : String(r?.recording || '').toLowerCase() === 'sim'
      ? `grava${c.movimento ? ' · movimento ligado' : ''}` : r ? '<span class="g5-ruim">não grava</span>' : '<span class="fraco">—</span>';
    const video = [c.codec, c.resolucao, c.fps ? `${c.fps} fps` : ''].filter(Boolean).join(' · ');
    const ren = g.renomeando === c.canal;
    return `<tr${img === 'sem' ? ' class="g5-linha-ruim"' : ''}>
      <td>${c.ip ? `<input type="checkbox" data-rec-sel="${c.canal}">` : ''}</td>
      <td class="n">${g5Num(c.canal)}</td>
      <td>${ren ? `<span class="g5-ren"><input data-g5-novo-nome value="${esc(c.nome || '')}" maxlength="60">
            <button class="mini" type="button" data-g5-salvar-nome="${c.canal}" ${g.trabalhando ? 'disabled' : ''}>${g.trabalhando === `ren-${c.canal}` ? 'Salvando…' : 'Salvar'}</button>
            <button class="mini" type="button" data-g5-cancelar-nome>Cancelar</button></span>`
          : `<b>${esc(c.nome || '-')}</b>`}</td>
      <td class="n">${esc(c.ip || '-')}</td>
      <td>${img === 'livre' ? '<span class="tag neutro">livre</span>' : img === 'sem' ? '<span class="tag erro">sem imagem</span>'
          : img === 'ok' ? '<span class="tag ok">ok</span>' : '<span class="tag neutro">sem leitura</span>'}</td>
      <td>${grava}</td>
      <td class="fraco">${esc(video || (c.ip ? '-' : ''))}</td>
      <td><span class="linha-acoes">
        ${c.ip ? `${ren ? '' : `<button class="mini" type="button" data-g5-renomear="${c.canal}">Renomear</button>`}
                  <button class="mini" type="button" data-rec-editar="${c.canal}" title="Trocar a câmera deste canal (IP, senha, protocolo)">Trocar câmera</button>
                  <button class="mini perigo" type="button" data-rec-soltar="${c.canal}">Excluir</button>`
               : `<button class="mini" type="button" data-rec-add="${c.canal}">Usar</button>`}
      </span></td>
    </tr>`;
  };

  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Canais</h2>
      <p>${comCam.length} com câmera · ${livres.length} livre${livres.length === 1 ? '' : 's'}${sem.length ? ` · <b class="g5-ruim">${sem.length} sem imagem</b>` : ''}</p></div>
      <div class="bloco-dir">
        <button class="acao perigo" type="button" data-rec-excluir-sel disabled>Excluir selecionados</button>
        <button class="acao" type="button" data-g5-buscar ${g.busca?.carregando ? 'disabled' : ''}>Procurar câmeras na rede</button>
        <button class="acao forte" type="button" data-rec-add="${primeiroLivre || 1}">+ Adicionar câmera</button></div></div>
    ${busca}${cartoes}${semMudanca}${foraHtml}
    <div class="rolo"><table>
      <thead><tr><th><input type="checkbox" data-rec-sel-todos title="Marcar todos os canais com câmera"></th><th>Canal</th><th>Nome</th><th>IP da câmera</th><th>Imagem</th><th>Gravando</th><th>Vídeo</th><th></th></tr></thead>
      <tbody>${canais.map(linha).join('')}</tbody>
    </table></div>
  </div>`;
}

async function g5Editar(corpo) {
  const p = deployStandaloneRecorderPayload();
  const alvo = recAvAlvo();
  const res = await api('/api/deployments/recorder-edit', {
    method: 'POST',
    body: JSON.stringify({
      recorder_host: alvo.host, recorder_user: p.recorder_user, recorder_password: p.recorder_password,
      recorder_http_port: alvo.http_port, connector_id: alvo.connector_id, site: p.site || '', ...corpo,
    }),
  });
  const j = await res?.json().catch(() => ({}));
  if (!res?.ok || j?.ok === false) throw new Error(j?.detail || j?.error || 'o gravador recusou');
  return j;
}

async function g5Apontar(d, canal, app) {
  const g = g5Estado();
  const m = g5Mudaram(d).find(x => Number(x.canal.canal) === canal);
  if (!m) return;
  const chave = `apontar-${canal}`;
  if (g.armado !== chave) { g.armado = chave; recPintarApp(); setTimeout(() => { if (g.armado === chave) { g.armado = ''; recPintarApp(); } }, 6000); return; }
  g.armado = ''; g.trabalhando = chave; recPintarApp();
  const senha = app.querySelector(`[data-g5-senha="${canal}"]`)?.value || '';
  try {
    const r = await g5Editar({
      acao: 'editar', canal, nome: m.canal.nome || '', camera_ip: m.ip, camera_mac: m.mac,
      camera_password: senha, protocolo: m.canal.protocolo || '',
      antes: { ip: m.canal.ip, nome: m.canal.nome || '', mac: m.mac, protocolo: m.canal.protocolo || '' },
    });
    g.senhaPara = 0;
    showToast(r.online === false
      ? `Canal ${g5Num(canal)} apontado para ${m.ip}, mas a câmera ainda não conectou: ${r.aviso || 'confira a senha'}`
      : `Canal ${g5Num(canal)} apontado para ${m.ip}. Desfazer fica no Histórico.`, r.online === false);
    g.hist = null;
    deployRecorderCarregarXray();
  } catch (e) {
    if (/senha da camera/i.test(e.message)) g.senhaPara = canal;
    showToast(`Canal ${g5Num(canal)}: ${e.message}`, true);
  } finally {
    g.trabalhando = ''; recPintarApp();
  }
}

async function g5Renomear(d, canal, app) {
  const g = g5Estado();
  const c = (d.canais || []).find(x => Number(x.canal) === canal);
  const nome = (app.querySelector('[data-g5-novo-nome]')?.value || '').trim();
  if (!c || !nome || nome === c.nome) { g.renomeando = 0; recPintarApp(); return; }
  g.trabalhando = `ren-${canal}`; recPintarApp();
  try {
    await g5Editar({ acao: 'renomear', canal, nome, antes: { nome: c.nome || '', ip: c.ip || '' } });
    showToast(`Canal ${g5Num(canal)} renomeado para "${nome}".`);
    g.renomeando = 0; g.hist = null;
    deployRecorderCarregarXray();
  } catch (e) {
    showToast(`Canal ${g5Num(canal)}: ${e.message}`, true);
  } finally {
    g.trabalhando = ''; recPintarApp();
  }
}

// ---------------------------------------------------------------- Discos
function g5Tb(n) { return `${(Math.round(Number(n || 0) * 10) / 10).toLocaleString('pt-BR')} TB`; }

function g5SecDiscos(d) {
  const ds = d.discos || [];
  const total = ds.reduce((s, x) => s + (Number(x.total_tb) || 0), 0);
  const usadoDe = x => Number(x.usado_tb) || (x.livre_tb != null && x.total_tb ? Math.max(0, Number(x.total_tb) - Number(x.livre_tb)) : 0);
  const usado = ds.reduce((s, x) => s + usadoDe(x), 0);
  const temUso = ds.some(x => usadoDe(x) > 0);
  const res = _recRes && _recRes.host === (d.host || recAvAlvo().host) ? _recRes : null;
  const ret = res?.dados?.retencao;
  const dias = ret && !ret.erro ? Number(ret.dias) : 0;

  let previsao = '';
  if (!ds.length) previsao = '<b class="g5-ruim">O gravador não reportou disco: não está gravando.</b>';
  else if (res?.carregando) previsao = 'Lendo a gravação mais antiga para calcular quantos dias o gravador guarda…';
  else if (!dias) previsao = `Ainda não sei quantos dias o gravador guarda. <button class="mini" type="button" data-g5-retencao>Ler agora</button>`;
  else {
    const cheio = temUso && total && usado / total >= 0.9;
    if (cheio || !temUso) {
      const precisa = dias < 30 ? total * 30 / dias - total : 0;
      previsao = `Os ${g5Tb(total)} guardam <b>${Math.floor(dias)} dias</b>${cheio ? ' (discos cheios, gravando por cima do mais antigo)' : ''}.
        ${dias < 30 ? `Para chegar a 30 dias, mais <b>${g5Tb(Math.ceil(precisa))}</b>.` : 'Passa de 30 dias.'}
        <small>Gravação mais antiga: ${esc(g5Data(ret.mais_antiga))}, canal ${g5Num(ret.canal)}.</small>`;
    } else {
      const cabe = dias * total / usado;
      previsao = `Em ${Math.floor(dias)} dias o gravador usou ${g5Tb(usado)} de ${g5Tb(total)}. No ritmo atual os discos cabem <b>uns ${Math.floor(cabe)} dias</b> antes de começar a gravar por cima.
        ${cabe < 30 ? `Para 30 dias, mais <b>${g5Tb(Math.ceil(total * 30 / cabe - total))}</b>.` : ''}`;
    }
  }

  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Discos</h2>
      <p>${ds.length} disco${ds.length === 1 ? '' : 's'}${total ? ' · ' + g5Tb(total) : ''}${temUso ? ` · ${g5Tb(usado)} usados` : ''}${ds.some(x => x.erro) ? ' · <b class="g5-ruim">com falha</b>' : ''}</p></div></div>
    <div class="g5-previsao">${previsao}</div>
    <div class="rolo"><table>
      <thead><tr><th>#</th><th>Disco</th><th>Capacidade</th><th>Uso</th><th>Tipo</th><th>Estado</th></tr></thead>
      <tbody>${ds.length ? ds.map(x => {
        const u = usadoDe(x), pct = x.total_tb && u ? Math.round(u / Number(x.total_tb) * 100) : null;
        return `<tr>
        <td class="n">${esc(String(x.id).padStart(2, '0'))}</td>
        <td>${esc(x.caminho || x.nome || '-')}</td>
        <td class="n">${x.total_tb ? g5Tb(x.total_tb) : '-'}</td>
        <td>${pct === null ? '<span class="fraco">não informado</span>'
            : `<span class="g5-uso"><span class="g5-trilho"><i style="width:${pct}%"></i></span><span class="mono">${pct}%</span></span>`}</td>
        <td>${esc(x.tipo || '-')}</td>
        <td>${x.erro ? `<span class="tag erro">com falha${x.situacao || x.estado ? ': ' + esc(x.situacao || x.estado) : ''}</span>` : '<span class="tag ok">ok</span>'}</td>
      </tr>`;
      }).join('') : '<tr><td colspan="6">Nenhum disco.</td></tr>'}</tbody>
    </table></div>
  </div>`;
}

// ---------------------------------------------------------------- Historico
async function g5HistCarregar(d, forcar = false) {
  const g = g5Estado();
  if (!forcar && g.hist) return;   // erro tambem fica: tentar de novo e no botao Atualizar
  const alvo = recAvAlvo();
  g.hist = { carregando: true, erro: '', dados: null };
  try {
    const ips = (d.canais || []).map(c => c.ip).filter(Boolean).join(',');
    const q = new URLSearchParams({ host: alvo.host, connector_id: alvo.connector_id, ips, dias: 7 });
    const res = await api(`/api/deployments/recorder-historico?${q}`);
    const j = await res.json().catch(() => ({}));
    if (_g5 !== g) return;
    g.hist = res.ok ? { carregando: false, erro: '', dados: j } : { carregando: false, erro: j.detail || `HTTP ${res.status}`, dados: null };
  } catch (e) {
    if (_g5 === g) g.hist = { carregando: false, erro: e.message, dados: null };
  }
  if (_recSec === 'historico') recPintarApp();
}

function g5SecHistorico(d) {
  const g = g5Estado();
  const h = g.hist;
  const canalPorIp = {};
  (d.canais || []).forEach(c => { if (c.ip) canalPorIp[c.ip] = c; });
  const itens = [];
  if (d.uptime_s) {
    const ini = new Date(Date.now() - Number(d.uptime_s) * 1000);
    itens.push({ quando: ini.toISOString(), tipo: 'info', titulo: `Gravador ligado desde ${g5Data(ini.toISOString())}`, sub: `último reinício há ${Math.floor(Number(d.uptime_s) / 86400)} dias` });
  }
  const res = _recRes && _recRes.host === (d.host || recAvAlvo().host) ? _recRes : null;
  const ret = res?.dados?.retencao;
  if (ret && ret.mais_antiga && !ret.erro) itens.push({ quando: ret.mais_antiga, tipo: 'info', titulo: `Gravação mais antiga: ${g5Data(ret.mais_antiga)}`, sub: `canal ${g5Num(ret.canal)} · ${Math.floor(Number(ret.dias))} dias guardados` });
  (h?.dados?.eventos || []).forEach(e => {
    const c = canalPorIp[e.ip];
    const caiu = !['online', 'up'].includes(String(e.para).toLowerCase());
    itens.push({ quando: e.quando, tipo: caiu ? 'ruim' : 'bom', titulo: `${c ? `Canal ${g5Num(c.canal)}${c.nome ? ' · ' + c.nome : ''}` : 'Câmera'} ${caiu ? 'ficou sem imagem' : 'voltou'}`,
      sub: `${e.ip}${e.mensagem ? ' · ' + e.mensagem : ''}` });
  });
  (h?.dados?.registros || []).forEach(r => {
    const canal = r.tipo === 'canal';
    const pode = canal ? r.desfazivel_canal : r.desfazivel;
    itens.push({ quando: r.quando, tipo: 'sightops', titulo: r.titulo || 'Mudança feita pelo SightOps',
      sub: `pelo SightOps${r.por ? ' · ' + r.por : ''}${r.ok === false ? ' · <b class="g5-ruim">o gravador recusou</b>' : ''}${r.desfeito_em ? ` · desfeito em ${esc(g5Data(r.desfeito_em))}${r.desfeito_por ? ' por ' + esc(r.desfeito_por) : ''}` : ''}`,
      subHtml: true, reg: r, pode: pode && !r.desfeito_em && r.ok !== false });
  });
  // Eventos do monitoramento vem em UTC ("…Z"); registros e gravador, na hora
  // local. Ordena pelo instante, nao pelo texto.
  const ms = q => { const t = new Date(String(q || '').replace(' ', 'T')).getTime(); return isNaN(t) ? 0 : t; };
  itens.sort((a, b) => ms(b.quando) - ms(a.quando));

  const corpo = !h || h.carregando ? '<p class="g5-vazio">Lendo o histórico…</p>'
    : h.erro ? `<p class="g5-vazio g5-ruim">Não consegui ler o histórico: ${esc(h.erro)}</p>`
    : !itens.length ? '<p class="g5-vazio">Nada registrado nos últimos 7 dias.</p>'
    : `<ul class="g5-hist">${itens.map(i => {
        const armado = i.reg && g.armado === `desfazer-${i.reg.id}`;
        return `<li class="g5-h-${i.tipo}"><span class="g5-h-quando mono">${esc(g5Data(i.quando))}</span>
        <span class="g5-h-txt"><b>${esc(i.titulo)}</b><small>${i.subHtml ? i.sub : esc(i.sub || '')}</small></span>
        ${i.pode ? `<button class="mini ${armado ? 'perigo' : ''}" type="button" data-g5-desfazer="${esc(i.reg.id)}" data-g5-tipo="${i.reg.tipo === 'canal' ? 'canal' : 'config'}" ${g.trabalhando ? 'disabled' : ''}>
          ${g.trabalhando === `desfazer-${i.reg.id}` ? 'Desfazendo…' : armado ? 'Confirmar desfazer' : 'Desfazer'}</button>` : ''}
      </li>`;
      }).join('')}</ul>`;
  return `<div class="bloco">
    <div class="bloco-cab"><div><h2>Histórico</h2><p>O que aconteceu com o gravador e o que o SightOps mudou nele · últimos 7 dias</p></div>
      <div class="bloco-dir"><button class="acao" type="button" data-g5-hist-reler>Atualizar</button></div></div>
    ${corpo}
  </div>`;
}

async function g5Desfazer(d, regId, tipo) {
  const g = g5Estado();
  const chave = `desfazer-${regId}`;
  if (g.armado !== chave) { g.armado = chave; recPintarApp(); setTimeout(() => { if (g.armado === chave) { g.armado = ''; recPintarApp(); } }, 6000); return; }
  g.armado = ''; g.trabalhando = chave; recPintarApp();
  const alvo = recAvAlvo();
  const p = deployStandaloneRecorderPayload();
  try {
    const res = tipo === 'canal'
      ? await api('/api/deployments/recorder-canal-desfazer', { method: 'POST', body: JSON.stringify({
          recorder_host: alvo.host, recorder_http_port: alvo.http_port, connector_id: alvo.connector_id,
          recorder_user: p.recorder_user, recorder_password: p.recorder_password, site: p.site || '', registro: regId }) })
      : await api('/api/nvr/driver/desfazer', { method: 'POST', body: JSON.stringify({ ...alvo, registro: regId }) });
    const j = await res.json().catch(() => ({}));
    if (!res.ok || j.ok === false) throw new Error(j.detail || `HTTP ${res.status}`);
    showToast('Desfeito no gravador.');
    if (tipo === 'canal') deployRecorderCarregarXray(); else _recAv = null;
  } catch (e) {
    showToast(`Não deu para desfazer: ${e.message}`, true);
  } finally {
    g.trabalhando = '';
    await g5HistCarregar(d, true);
    recPintarApp();
  }
}

// ---------------------------------------------------------------- ligar
function g5Ligar(app, d) {
  const g = g5Estado();
  if (_recSec === 'canais') g5Macs(d);
  if (_recSec === 'discos' && typeof recResCarregar === 'function') recResCarregar();
  if (_recSec === 'historico') {
    if (typeof recResCarregar === 'function') recResCarregar();
    g5HistCarregar(d);
  }
  app.querySelectorAll('[data-g5-buscar]').forEach(b => b.addEventListener('click', () => g5Buscar()));
  app.querySelectorAll('[data-g5-apontar]').forEach(b => b.addEventListener('click', () => g5Apontar(d, Number(b.dataset.g5Apontar), app)));
  app.querySelectorAll('[data-g5-renomear]').forEach(b => b.addEventListener('click', () => {
    g.renomeando = Number(b.dataset.g5Renomear); recPintarApp();
    const i = document.querySelector('[data-g5-novo-nome]'); if (i) { i.focus(); i.select(); }
  }));
  app.querySelector('[data-g5-cancelar-nome]')?.addEventListener('click', () => { g.renomeando = 0; recPintarApp(); });
  app.querySelector('[data-g5-salvar-nome]')?.addEventListener('click', ev => g5Renomear(d, Number(ev.currentTarget.dataset.g5SalvarNome), app));
  app.querySelector('[data-g5-novo-nome]')?.addEventListener('keydown', ev => {
    if (ev.key === 'Enter') g5Renomear(d, g.renomeando, app);
    if (ev.key === 'Escape') { g.renomeando = 0; recPintarApp(); }
  });
  app.querySelector('[data-g5-retencao]')?.addEventListener('click', () => { if (typeof recResCarregar === 'function') recResCarregar(true); });
  app.querySelector('[data-g5-hist-reler]')?.addEventListener('click', () => g5HistCarregar(d, true).then(recPintarApp));
  app.querySelectorAll('[data-g5-desfazer]').forEach(b => b.addEventListener('click', () => g5Desfazer(d, b.dataset.g5Desfazer, b.dataset.g5Tipo)));
}

recRegistrarSecao('canais', 'Canais', g5SecCanais, g5Ligar);
recRegistrarSecao('discos', 'Discos', g5SecDiscos);
recRegistrarSecao('historico', 'Histórico', g5SecHistorico, null, 'deteccao');
