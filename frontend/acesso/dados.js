// Janela "Dados" do Painel de Acesso: backup do cliente (ou de um local) e
// excluir um local inteiro. Rotas /painel/dados* (so admin, security.py).
// Excluir faz o backup antes, no servidor, e pede o nome do local digitado.
let _daDados = null;
let _daOcupado = false;

function daCampo(id) { return document.getElementById(id); }

function daTam(b) {
  b = Number(b || 0);
  return b >= 1048576 ? (b / 1048576).toFixed(1).replace('.', ',') + ' MB' : Math.max(1, Math.round(b / 1024)) + ' KB';
}

function daQuando(iso) {
  const m = String(iso || '').match(/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/);
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}:${m[5]}` : '';
}

function daUrl(nome) { return `${API_BASE}/api/access-control/painel/dados/backup/${encodeURIComponent(nome)}`; }

function daBaixar(nome) {
  const a = document.createElement('a');
  a.href = daUrl(nome); a.download = nome;
  document.body.appendChild(a); a.click(); a.remove();
}

async function daAbrir() {
  daCampo('daGaveta').hidden = false;
  requestAnimationFrame(() => daCampo('daGaveta').classList.add('aberta'));
  daCampo('daConteudo').innerHTML = '<p class="dv-ajuda"><i data-lucide="loader-circle" class="dv-gira"></i> Lendo…</p>';
  if (window.lucide) lucide.createIcons();
  try {
    _daDados = await apiJson('/api/access-control/painel/dados');
    daDesenhar();
  } catch (err) {
    daCampo('daConteudo').innerHTML = `<p class="dv-erro">${/403/.test(err.message) ? 'Só administrador pode fazer backup ou excluir local.' : esc(err.message || 'Não consegui ler.')}</p>`;
  }
}

function daFechar() {
  if (_daOcupado) return;
  const g = daCampo('daGaveta');
  g.classList.remove('aberta');
  setTimeout(() => { g.hidden = true; }, 200);
}

function daDesenhar(siteExcluir) {
  const d = _daDados || { locais: [], backups: [] };
  const atual = siteExcluir !== undefined ? siteExcluir : (typeof _apSite === 'string' ? _apSite : '');
  const loc = d.locais.find(l => l.site.toUpperCase() === String(atual).toUpperCase());
  daCampo('daConteudo').innerHTML = `
    <section class="dv-passo">
      <h3 class="dv-passo-tit"><i data-lucide="database-backup"></i>Backup</h3>
      <p class="dv-ajuda">Pessoas, fotos, grupos, horários, leitores e passagens deste cliente num arquivo .zip. Fica guardado no servidor (os ${apNum(30)} mais recentes) e baixa no seu computador.</p>
      <div class="da-linha">
        <select id="daBkSite" aria-label="O que entra no backup"><option value="">Cliente inteiro</option>
          ${d.locais.map(l => `<option value="${esc(l.site)}" ${l.site === atual ? 'selected' : ''}>${esc(l.site)}</option>`).join('')}</select>
        <button type="button" class="primary-action" id="daBkFazer"><i data-lucide="download"></i> Fazer backup e baixar</button>
      </div>
      ${d.backups.length ? `<ul class="da-lista">${d.backups.map(b => `<li>
        <span><b>${esc(b.site || 'Cliente inteiro')}</b><small>${esc(daQuando(b.feito_em))}${b.por ? ' · ' + esc(b.por) : ''}${b.motivo && b.motivo !== 'manual' ? ' · ' + esc(b.motivo) : ''}</small></span>
        <small>${apNum((b.contagem || {}).access_people)} pessoas · ${apNum((b.contagem || {}).fotos)} fotos · ${daTam(b.bytes)}</small>
        <a class="da-baixar" href="${daUrl(b.nome)}" download="${esc(b.nome)}"><i data-lucide="download"></i> Baixar</a></li>`).join('')}</ul>`
        : '<p class="dv-ajuda">Nenhum backup feito por aqui ainda.</p>'}
    </section>
    <section class="dv-passo da-perigo">
      <h3 class="dv-passo-tit"><i data-lucide="trash-2"></i>Excluir um local inteiro</h3>
      <p class="dv-ajuda">Apaga do SightOps as pessoas, fotos, grupos, horários e leitores do local. Antes, faz um backup sozinho. As pessoas saem dos leitores primeiro; se algum leitor não responder, ela fica desativada e o resto não é apagado.</p>
      <select id="daExSite" aria-label="Local a excluir"><option value="">Escolha o local…</option>
        ${d.locais.map(l => `<option value="${esc(l.site)}" ${loc && l.site === loc.site ? 'selected' : ''}>${esc(l.site)}</option>`).join('')}</select>
      ${loc ? `<div class="pi-numeros da-numeros">
          <div class="ruim"><b>${apNum(loc.pessoas)}</b><span>pessoas</span></div>
          <div><b>${apNum(loc.fotos)}</b><span>fotos</span></div>
          <div><b>${apNum(loc.leitores)}</b><span>leitores</span></div>
          <div><b>${apNum(loc.grupos + loc.grupos_portas)}</b><span>grupos</span></div>
        </div>
        ${loc.leitores ? `<p class="dv-ajuda">Os ${apNum(loc.leitores)} leitores precisam estar com sinal para as pessoas saírem deles.</p>` : '<p class="dv-ajuda">Sem leitor cadastrado: só apaga do SightOps. Quem estiver gravado em algum aparelho continua lá.</p>'}
        <label class="dv-chave"><input type="checkbox" id="daExHist"><span></span>Apagar também o histórico de passagens<small>${apNum(loc.passagens)} passagens. Desmarcado, os relatórios antigos continuam.</small></label>
        <label class="dv-rot" for="daExConf">Para confirmar, digite <b>${esc(loc.site)}</b></label>
        <input id="daExConf" autocomplete="off" spellcheck="false">
        <button type="button" class="dv-remover forte da-excluir" id="daExFazer" disabled><i data-lucide="trash-2"></i> Fazer backup e excluir ${esc(loc.site)}</button>` : ''}
      <div id="daExRes" role="alert"></div>
    </section>`;
  if (window.lucide) lucide.createIcons();
  daCampo('daBkFazer').addEventListener('click', daBackup);
  daCampo('daExSite').addEventListener('change', ev => daDesenhar(ev.target.value));
  if (loc) {
    const conf = daCampo('daExConf');
    const igual = () => conf.value.trim().replace(/\s+/g, ' ').toUpperCase() === loc.site.trim().replace(/\s+/g, ' ').toUpperCase();
    conf.addEventListener('input', () => { daCampo('daExFazer').disabled = !igual(); });
    daCampo('daExFazer').addEventListener('click', () => { if (igual()) daExcluir(loc.site, conf.value); });
  }
}

async function daBackup() {
  const b = daCampo('daBkFazer');
  const site = daCampo('daBkSite').value;
  b.disabled = true;
  b.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i> Fazendo backup…';
  if (window.lucide) lucide.createIcons();
  try {
    const r = await acEnviar('POST', '/api/access-control/painel/dados/backup', { site });
    daBaixar(r.nome);
    acToast(`Backup pronto: ${apNum(r.contagem.access_people)} pessoas e ${apNum(r.contagem.fotos)} fotos (${daTam(r.bytes)}).`);
    _daDados = await apiJson('/api/access-control/painel/dados');
    daDesenhar(daCampo('daExSite') ? daCampo('daExSite').value : undefined);
  } catch (err) {
    acToast((err && err.message) || 'Não foi possível fazer o backup.', true);
    b.disabled = false;
    b.innerHTML = '<i data-lucide="download"></i> Fazer backup e baixar';
    if (window.lucide) lucide.createIcons();
  }
}

async function daExcluir(site, confirmacao) {
  const b = daCampo('daExFazer');
  _daOcupado = true;
  b.disabled = true;
  b.innerHTML = '<i data-lucide="loader-circle" class="dv-gira"></i> Fazendo backup e excluindo…';
  if (window.lucide) lucide.createIcons();
  let r = null, erro = '';
  try {
    r = await acEnviar('POST', '/api/access-control/painel/dados/excluir-local', { site, confirmacao, apagar_historico: daCampo('daExHist').checked });
  } catch (err) {
    erro = (err && err.message) || 'Não foi possível excluir.';
  }
  _daOcupado = false;
  try { _daDados = await apiJson('/api/access-control/painel/dados'); } catch (_) {}
  daDesenhar('');
  const res = daCampo('daExRes');
  if (erro) {
    res.innerHTML = `<p class="dv-erro">${esc(erro)}</p>`;
  } else if (!r.ok) {
    res.innerHTML = `<div class="dvc-res ruim">Parou no meio: ${apNum(r.pessoas_mantidas.length)} pessoa${r.pessoas_mantidas.length === 1 ? '' : 's'} não saíram de um leitor sem resposta e ficaram desativadas. ${apNum(r.pessoas_excluidas)} foram excluídas. Leitores e grupos continuam para dar para terminar quando o leitor voltar. Backup: ${esc(r.backup)}.</div>`;
  } else {
    res.innerHTML = `<div class="dvc-res ok">${esc(r.site)} excluído: ${apNum(r.pessoas_excluidas)} pessoas, ${apNum(r.leitores)} leitores, ${apNum(r.grupos + r.grupos_portas)} grupos${r.passagens ? `, ${apNum(r.passagens)} passagens` : ''}. Backup feito antes: <a href="${daUrl(r.backup)}" download="${esc(r.backup)}">${esc(r.backup)}</a>.</div>`;
  }
  if (typeof apRecarregarTudo === 'function') apRecarregarTudo();
}

(function daLigar() {
  const ligar = () => {
    if (!daCampo('apDados')) return;
    daCampo('apDados').addEventListener('click', daAbrir);
    daCampo('daFechar').addEventListener('click', daFechar);
    daCampo('daFundo').addEventListener('click', daFechar);
    document.addEventListener('keydown', ev => { if (ev.key === 'Escape' && !daCampo('daGaveta').hidden) daFechar(); });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ligar); else ligar();
})();
