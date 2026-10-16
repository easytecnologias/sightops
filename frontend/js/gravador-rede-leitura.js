// Gravador aberto > Rede: as quatro abas de LEITURA. Nada aqui escreve no
// gravador. A edicao (IP, DNS, portas), o reiniciar e as correcoes de rede sao
// do gravador-rede-editar.js, feito em paralelo; quando uma aba daqui mostra
// algo que se corrige ("nao avisa IP duplicado", "DNS vazio"), a correcao
// fica no rodape "Correcoes de rede" daquele arquivo.
//
// Uma leitura so para as quatro abas: GET /api/deployments/recorder-rede
// (caminho e tempo de resposta pelo conector, portas e acessos, onde cada
// camera esta ligada, quedas recentes). O resto vem do raio-x ja carregado.

let _rl = null;   // {chave, carregando, erro, dados}

function rlEstado() {
  const chave = recChave();
  if (!_rl || _rl.chave !== chave) _rl = { chave, carregando: false, erro: '', dados: null };
  return _rl;
}

async function rlCarregar(d, forcar = false) {
  const r = rlEstado();
  if (r.carregando || (!forcar && (r.dados || r.erro))) return;
  const alvo = recAvAlvo();
  r.carregando = true; r.erro = '';
  if (forcar) recPintarApp();   // clique em "Medir de novo": mostra que esta lendo
  try {
    const canais = (d.canais || []).filter(c => c.ip).map(c => `${c.canal}:${c.ip}`).join(',');
    const q = new URLSearchParams({ host: alvo.host, http_port: alvo.http_port, connector_id: alvo.connector_id, canais });
    const res = await api(`/api/deployments/recorder-rede?${q}`);
    const j = await res.json().catch(() => ({}));
    if (_rl !== r) return;
    if (!res.ok) r.erro = j.detail === 'SEM_CREDENCIAL' ? 'Sem senha salva deste gravador.' : (j.detail || `HTTP ${res.status}`);
    else r.dados = j;
  } catch (e) {
    if (_rl === r) r.erro = e.message;
  }
  if (_rl === r) r.carregando = false;
  if (_recSec === 'rede') recPintarApp();
}

function rlHa(iso) {
  const t = new Date(iso).getTime();
  if (!t) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  return s < 90 ? `há ${s} s` : s < 5400 ? `há ${Math.round(s / 60)} min` : `há ${Math.round(s / 3600)} h`;
}

function rlData(iso) {
  const t = new Date(String(iso || ''));   // ja vem "…Z" (UTC) do servidor
  if (isNaN(t)) return String(iso || '');
  const p = n => String(n).padStart(2, '0');
  return `${p(t.getDate())}/${p(t.getMonth() + 1)} ${p(t.getHours())}:${p(t.getMinutes())}`;
}

// Cabecalho de espera/erro comum as quatro abas.
function rlEspera() {
  const r = rlEstado();
  if (r.carregando || (!r.dados && !r.erro)) return '<div class="bloco"><p class="rl-vazio">Lendo a rede do gravador pelo conector… leva alguns segundos.</p></div>';
  if (r.erro) return `<div class="bloco"><p class="rl-vazio rl-ruim">Não consegui ler a rede: ${esc(r.erro)} <button class="mini" type="button" data-rl-reler>Tentar de novo</button></p></div>`;
  return '';
}

function rlLinhas(pares) {
  return `<div class="rolo"><table><tbody>${pares.map(([k, v, cls, nota]) =>
    `<tr><td class="rl-rot">${esc(k)}</td><td><b class="${cls ? 'rl-' + cls : ''}">${esc(v)}</b>${nota ? `<small class="rl-nota">${esc(nota)}</small>` : ''}</td></tr>`).join('')}</tbody></table></div>`;
}

// ---------------------------------------------------------------- 1. Caminho e banda
function rlCaminho(d) {
  const espera = rlEspera(); if (espera) return espera;
  const x = rlEstado().dados, rd = d.rede || {}, pt = x.portas || {};
  const con = x.conector, resp = x.resposta || {};
  const no = (rot, val, sub, cls = '') => `<div class="rl-no ${cls}"><span class="rl-no-rot">${esc(rot)}</span><b>${esc(val)}</b><small>${sub}</small></div>`;
  const seta = txt => `<div class="rl-seta"><span>${txt}</span></div>`;
  const respTxt = resp.ok ? `${resp.media_ms} ms` : 'sem resposta';
  const caminho = `<div class="rl-caminho">
    ${no('Servidor', 'SightOps', 'central')}
    ${con ? seta('túnel') + no('Conector', con.nome || con.id, `${esc(con.status || '')} · último contato ${esc(rlHa(con.ultimo_contato))}`, con.status === 'online' ? 'bom' : 'ruim') : seta('direto')}
    ${seta(x.alcance !== x.host ? 'IP virtual' : 'IP')}
    ${no('Gravador', `${x.alcance}:${x.porta}`, x.alcance !== x.host ? `real ${esc(x.host)}` : 'mesmo IP', '')}
    ${seta(esc(respTxt))}
    ${no('Resposta', respTxt, resp.ok ? `mín ${resp.min_ms} · máx ${resp.max_ms} ms${resp.perdidas ? ` · <b class="rl-ruim">${resp.perdidas} sem resposta</b>` : ''}` : esc(resp.erro || ''), resp.ok ? (resp.media_ms > 400 ? 'medio' : 'bom') : 'ruim')}
  </div>`;

  const comCam = (d.canais || []).filter(c => c.ip);
  const kbps = comCam.reduce((s, c) => s + (Number(c.taxa_kbps) || 0), 0);
  const mbps = kbps / 1000;
  const placa = pt.placa || {};
  const cap = placa.velocidade_mbps || 1000;
  const pct = Math.min(100, Math.round(mbps / cap * 100));
  const top = [...comCam].filter(c => Number(c.taxa_kbps)).sort((a, b) => b.taxa_kbps - a.taxa_kbps).slice(0, 5);
  const banda = kbps ? `<div class="rl-banda">
      <div class="rl-banda-num"><b>${mbps.toLocaleString('pt-BR', { maximumFractionDigits: 1 })} Mbps</b> <span>somando os ${comCam.length} canais (fluxo principal)</span></div>
      <div class="rl-trilho"><i style="width:${pct}%" class="${pct > 70 ? 'alto' : ''}"></i></div>
      <small>${pct}% de ${cap >= 1000 ? cap / 1000 + ' Gbps' : cap + ' Mbps'}${placa.velocidade_mbps ? '' : ' (a placa não informou a velocidade; considerei 1 Gbps)'}${pct > 70 ? ' · <b class="rl-ruim">perto do limite da placa</b>' : ''}</small>
      ${top.length ? `<table class="rl-top"><tbody>${top.map(c => `<tr><td class="n">${String(c.canal).padStart(2, '0')}</td><td>${esc(c.nome || '-')}</td><td class="n">${(Number(c.taxa_kbps) / 1000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} Mbps</td><td class="fraco">${esc([c.codec, c.resolucao].filter(Boolean).join(' · '))}</td></tr>`).join('')}</tbody></table>` : ''}
    </div>` : '<p class="rl-vazio">O gravador não informou o bitrate dos canais.</p>';

  return `<div class="bloco"><div class="bloco-cab"><div><h2>Caminho até o gravador</h2><p>Medido agora, pelo mesmo caminho que o SightOps usa</p></div>
      <div class="bloco-dir"><button class="acao" type="button" data-rl-reler>Medir de novo</button></div></div>${caminho}</div>
    <div class="bloco"><div class="bloco-cab"><div><h2>Rede do gravador</h2><p>Em vermelho, o que falta ou está fora do padrão</p></div></div>
      ${rlLinhas([
        ['IP', rd.ip || '-', '', pt.rede ? (pt.rede.dhcp ? 'DHCP: pode mudar sozinho' : 'IP fixo') : ''],
        ['Máscara', rd.mascara || '-'], ['Gateway', rd.gateway || '-', rd.gateway ? '' : 'ruim'],
        ['DNS', rd.dns || 'não configurado', rd.dns && rd.dns !== '0.0.0.0' ? '' : 'ruim', rd.dns && rd.dns !== '0.0.0.0' ? '' : 'sem DNS: NTP por nome e nuvem não resolvem'],
        ['MAC', rd.mac || '-'],
        ['MTU', rd.mtu || '-', rd.mtu && String(rd.mtu) !== '1500' ? 'ruim' : '', rd.mtu && String(rd.mtu) !== '1500' ? 'o padrão é 1500' : ''],
        ['Placa', placa.nome ? `${placa.nome} · ${placa.conectada ? 'conectada' : 'desconectada'}` : '-', placa.nome && !placa.conectada ? 'ruim' : ''],
      ])}</div>
    <div class="bloco"><div class="bloco-cab"><div><h2>Banda</h2><p>O que as câmeras mandam para o gravador contra o que a placa aguenta</p></div></div>${banda}</div>`;
}

// ---------------------------------------------------------------- 2. Cameras na rede
function rlFaixa(ip, rede, mascara) {
  const n = s => String(s || '').split('.').map(Number);
  const a = n(ip), b = n(rede), m = n(mascara);
  if (a.length !== 4 || b.length !== 4 || m.length !== 4 || m.some(isNaN)) return true;
  return a.every((x, i) => (x & m[i]) === (b[i] & m[i]));
}

function rlCameras(d) {
  const espera = rlEspera(); if (espera) return espera;
  const x = rlEstado().dados, rd = d.rede || {};
  const porCanal = {}; (x.cameras || []).forEach(c => { porCanal[c.canal] = c; });
  const linhas = (d.canais || []).filter(c => c.ip).map(c => {
    const r = porCanal[c.canal] || {};
    const sit = r.duplicado ? ['ruim', 'IP repetido em outro canal']
      : rd.ip && rd.mascara && !rlFaixa(c.ip, rd.ip, rd.mascara) ? ['medio', 'fora da faixa do gravador (passa pelo gateway)']
      : !r.mac ? ['neutro', 'sem MAC no inventário'] : ['bom', 'ok'];
    return { c, r, sit };
  });
  const problemas = linhas.filter(l => l.sit[0] === 'ruim' || l.sit[0] === 'medio').length;
  return `<div class="bloco"><div class="bloco-cab"><div><h2>Câmeras na rede</h2>
      <p>${linhas.length} câmeras · onde cada uma está ligada, pelo inventário do SightOps${problemas ? ` · <b class="rl-ruim">${problemas} com problema</b>` : ''}</p></div></div>
    <div class="rolo"><table>
      <thead><tr><th>Canal</th><th>Nome</th><th>IP</th><th>MAC</th><th>Onde está ligada</th><th>Situação</th></tr></thead>
      <tbody>${linhas.map(({ c, r, sit }) => `<tr>
        <td class="n">${String(c.canal).padStart(2, '0')}</td><td>${esc(c.nome || '-')}</td><td class="n">${esc(c.ip)}</td>
        <td class="n">${esc(r.mac || '-')}</td>
        <td>${r.onde && r.onde.texto ? `<span class="rl-onde ${esc(r.onde.tipo)}">${esc(r.onde.tipo === 'onu' ? 'ONU' : 'Switch')}</span> ${esc(r.onde.texto)}` : '<span class="fraco">não está no inventário de câmeras</span>'}</td>
        <td><span class="tag ${sit[0] === 'bom' ? 'ok' : sit[0] === 'ruim' ? 'erro' : 'neutro'}"${sit[0] === 'medio' ? ' style="background:var(--amber-soft);color:var(--amber)"' : ''}>${esc(sit[1])}</span></td>
      </tr>`).join('') || '<tr><td colspan="6">Nenhum canal com câmera.</td></tr>'}</tbody>
    </table></div>
    <p class="rl-dica">Câmera sem imagem que mudou de IP: na seção <b>Canais</b>, "Procurar câmeras na rede" acha para onde ela foi pelo MAC.</p>
  </div>`;
}

// ---------------------------------------------------------------- 3. Portas e acessos
function rlPortas(d) {
  const espera = rlEspera(); if (espera) return espera;
  const x = rlEstado().dados, p = x.portas;
  const sv = d.servicos || {}, pl = d.plataforma || {};
  if (!p) {
    return `<div class="bloco"><div class="bloco-cab"><div><h2>Portas e acessos</h2><p>${esc(x.marca || '')}</p></div></div>
      ${rlLinhas([
        ['Nuvem P2P', pl.ligada ? `ligada${pl.servidor ? ' · ' + pl.servidor : ''}` : 'desligada', pl.ligada ? 'ruim' : 'bom', pl.ligada ? 'qualquer um com o app entra sem passar pelo SightOps' : ''],
        ['HTTPS', sv.https_ligado ? 'ligado' : 'desligado'], ['SNMP', sv.snmp_ligado ? 'ligado' : 'desligado', sv.snmp_ligado ? 'bom' : 'medio', sv.snmp_ligado ? '' : 'o Zabbix não lê temperatura nem disco'],
      ])}<p class="rl-dica">Portas detalhadas ainda só para Intelbras.</p></div>`;
  }
  const lin = [
    ['Web (HTTP)', p.web.ligado ? `porta ${p.web.porta}` : 'desligado', p.web.ligado ? 'bom' : 'ruim', 'usado pelo SightOps, só pelo conector'],
    ['RTSP (vídeo)', p.rtsp.ligado ? `porta ${p.rtsp.porta}` : 'desligado', p.rtsp.ligado ? 'bom' : 'ruim', 'ao vivo e gravações no SightOps'],
    ['SDK', p.sdk.porta ? `porta ${p.sdk.porta}` : '-', '', 'troca de câmera nos canais (NetSDK)'],
    ['Nuvem P2P', p.p2p.ligado ? `ligada · ${p.p2p.servidor || 'servidor do fabricante'}` : 'desligada', p.p2p.ligado ? 'ruim' : 'bom', p.p2p.ligado ? 'risco: quem tiver o app do fabricante entra sem passar pelo SightOps' : 'só acessa quem passa pelo SightOps'],
    ['HTTPS', p.https.ligado ? `ligado · porta ${p.https.porta}` : 'desligado', '', ''],
    ['SNMP', p.snmp.ligado ? 'ligado' : 'desligado', p.snmp.ligado ? 'bom' : 'medio', p.snmp.ligado ? 'o Zabbix pode ler temperatura e disco' : 'o Zabbix não lê temperatura nem disco'],
    ['UPnP', p.upnp.ligado ? `ligado · ${p.upnp.mapeamentos} portas` : 'desligado', p.upnp.ligado ? 'ruim' : 'bom', p.upnp.ligado ? 'risco: o gravador abre portas sozinho no roteador do cliente' : ''],
  ];
  return `<div class="bloco"><div class="bloco-cab"><div><h2>Portas e acessos</h2><p>Por onde se entra no gravador · lido agora da configuração</p></div></div>
    ${rlLinhas(lin)}
    ${p.falhas && p.falhas.length ? `<p class="rl-dica">Não li: ${esc(p.falhas.join('; '))}</p>` : ''}
  </div>${rlCelular(d, p.p2p.ligado)}`;
}

// QR Code para o iSIC Lite: o app da Intelbras adiciona o gravador pela nuvem
// (P2P) lendo o NUMERO DE SERIE. So funciona com a nuvem ligada -- que e o
// mesmo acesso que a linha acima marca como risco: o celular entra sem passar
// pelo SightOps. A biblioteca do QR so carrega quando esta aba abre.
function rlCelular(d, p2pLigado) {
  const serie = String((d.equipamento || {}).serial || '').trim();
  if (!serie) return '';
  return `<div class="bloco"><div class="bloco-cab"><div><h2>Ver no celular (iSIC Lite)</h2>
      <p>${p2pLigado ? 'Aponte o iSIC Lite para o QR: Adicionar dispositivo → Cloud (P2P) → ler QR Code' : '<b class="rl-ruim">A nuvem P2P está desligada: o QR só funciona com ela ligada</b>'}</p></div></div>
    <div class="rl-qr-caixa">
      <div class="rl-qr" data-rl-qr="${esc(serie)}" aria-label="QR Code do número de série"></div>
      <div class="rl-qr-txt">
        <span class="rl-rot">Número de série</span><b class="mono">${esc(serie)}</b>
        <small>Depois de ler, o app pede usuário e senha do gravador (os mesmos que o SightOps usa).</small>
        <small>Quem tiver esse QR e a senha vê as câmeras pelo celular, fora do SightOps.</small>
      </div>
    </div></div>`;
}

function rlCarregarQr() {
  if (window.QRCode) return Promise.resolve(window.QRCode);
  if (rlCarregarQr._p) return rlCarregarQr._p;
  rlCarregarQr._p = new Promise((ok, falha) => {
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js';
    s.onload = () => (window.QRCode ? ok(window.QRCode) : falha(new Error('sem QRCode')));
    s.onerror = () => { rlCarregarQr._p = null; falha(new Error('não carregou o gerador de QR')); };
    document.head.appendChild(s);
  });
  return rlCarregarQr._p;
}

function rlDesenharQr(app) {
  const el = app.querySelector('[data-rl-qr]');
  if (!el || el.dataset.feito) return;
  el.dataset.feito = '1';
  rlCarregarQr().then(QR => {
    el.innerHTML = '';
    new QR(el, { text: el.dataset.rlQr, width: 168, height: 168, correctLevel: QR.CorrectLevel.M });
  }).catch(e => { el.innerHTML = `<small class="rl-ruim">${esc(e.message)}</small>`; });
}

// ---------------------------------------------------------------- 4. Alertas de rede
function rlAlertas(d) {
  const espera = rlEspera(); if (espera) return espera;
  const x = rlEstado().dados, al = d.alarmes || {};
  const itens = [['ip_duplicado', 'IP duplicado na rede'], ['mac_duplicado', 'MAC duplicado'], ['rede_caiu', 'Rede caiu (cabo/porta)'], ['login_falho', 'Senha errada várias vezes']];
  const conhecidos = itens.filter(([k]) => k in al);
  const naoAvisa = conhecidos.filter(([k]) => !al[k]).length;
  const quedas = x.quedas || [];
  return `<div class="bloco"><div class="bloco-cab"><div><h2>O gravador avisa quando…</h2>
      <p>${conhecidos.length ? (naoAvisa ? `<b class="rl-ruim">${naoAvisa} alarme${naoAvisa === 1 ? '' : 's'} de rede desligado${naoAvisa === 1 ? '' : 's'}</b> · a correção fica em "Correções de rede"` : 'todos os alarmes de rede ligados') : 'este modelo não informa os alarmes'}</p></div></div>
    ${conhecidos.length ? rlLinhas(conhecidos.map(([k, rot]) => [rot, al[k] ? 'avisa' : 'não avisa', al[k] ? 'bom' : 'ruim'])) : ''}
  </div>
  <div class="bloco"><div class="bloco-cab"><div><h2>Quedas vistas pelo SightOps</h2><p>Gravador e conector · últimos 7 dias</p></div></div>
    ${quedas.length ? `<ul class="rl-quedas">${quedas.map(q => {
      const caiu = !['up', 'online'].includes(String(q.para).toLowerCase());
      return `<li class="${caiu ? 'ruim' : 'bom'}"><span class="mono">${esc(rlData(q.quando))}</span><b>${esc(q.quem === 'conector' ? 'Conector' : 'Gravador')} ${caiu ? 'ficou sem resposta' : 'voltou'}</b><small>${esc(q.de)} → ${esc(q.para)}</small></li>`;
    }).join('')}</ul>` : '<p class="rl-vazio">Nenhuma queda do gravador ou do conector nos últimos 7 dias.</p>'}
  </div>`;
}

function rlLigar(app, d) {
  rlCarregar(d);
  rlDesenharQr(app);
  app.querySelectorAll('[data-rl-reler]').forEach(b => b.addEventListener('click', () => rlCarregar(d, true).then(recPintarApp)));
}

recRegistrarAbaRede('caminho', 'Caminho e banda', rlCaminho, rlLigar, 10);
recRegistrarAbaRede('cameras', 'Câmeras na rede', rlCameras, rlLigar, 20);
recRegistrarAbaRede('portas', 'Portas e acessos', rlPortas, rlLigar, 30);
recRegistrarAbaRede('alertas', 'Alertas de rede', rlAlertas, rlLigar, 40);
