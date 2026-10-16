// Gravador aberto > Rede: esqueleto com abas.
//
// A secao e feita por duas sessoes ao mesmo tempo, cada uma no seu arquivo:
//   - leitura (Caminho e banda, Cameras na rede, Portas e acessos, Alertas de rede);
//   - escrita (Editar rede, Reiniciar, Correcoes de rede).
// Cada arquivo registra o que e seu:
//   recRegistrarAbaRede(id, rotulo, render(d) -> html, ligar(app, d), ordem)
//   recRegistrarRodapeRede(id, render(d) -> html, ligar(app, d), ordem)
// O rodape aparece embaixo de qualquer aba (ex.: as correcoes de rede).
// Sem aba nenhuma registrada, a secao mostra a lista antiga (recSecRede).

const _REDE_ABAS = [];
const _REDE_RODAPES = [];
let _grRedeAba = '';

function recRegistrarAbaRede(id, rotulo, render, ligar, ordem = 50) {
  const i = _REDE_ABAS.findIndex(a => a.id === id);
  const aba = { id, rotulo, render, ligar, ordem };
  if (i >= 0) _REDE_ABAS[i] = aba; else _REDE_ABAS.push(aba);
  _REDE_ABAS.sort((a, b) => a.ordem - b.ordem);
}

function recRegistrarRodapeRede(id, render, ligar, ordem = 50) {
  const i = _REDE_RODAPES.findIndex(a => a.id === id);
  const r = { id, render, ligar, ordem };
  if (i >= 0) _REDE_RODAPES[i] = r; else _REDE_RODAPES.push(r);
  _REDE_RODAPES.sort((a, b) => a.ordem - b.ordem);
}

function redeAbaAtual() {
  return _REDE_ABAS.find(a => a.id === _grRedeAba) || _REDE_ABAS[0] || null;
}

function recSecRedeAbas(d) {
  const aba = redeAbaAtual();
  if (!aba) return recSecRede(d);
  const corpo = (() => { try { return aba.render(d); } catch (e) { console.error('aba de rede', e); return `<div class="bloco"><p class="rec-muted" style="padding:12px 15px">Não consegui montar esta aba: ${esc(e.message)}</p></div>`; } })();
  const rodapes = _REDE_RODAPES.map(r => { try { return r.render(d) || ''; } catch (e) { console.error('rodape de rede', e); return ''; } }).join('');
  return `<div class="gr-rede">
    <div class="gr-abas" role="tablist" aria-label="Rede do gravador">${_REDE_ABAS.map(a =>
      `<button type="button" role="tab" data-gr-aba="${esc(a.id)}" aria-selected="${a === aba}">${esc(a.rotulo)}</button>`).join('')}</div>
    ${corpo}
    ${rodapes}
  </div>`;
}

function recLigarRede(app, d) {
  if (_recSec !== 'rede') return;
  app.querySelectorAll('[data-gr-aba]').forEach(b => b.addEventListener('click', () => {
    _grRedeAba = b.dataset.grAba;
    recPintarApp();
  }));
  const aba = redeAbaAtual();
  try { aba?.ligar?.(app, d); } catch (e) { console.error('aba de rede', e); }
  _REDE_RODAPES.forEach(r => { try { r.ligar?.(app, d); } catch (e) { console.error('rodape de rede', e); } });
}

recRegistrarSecao('rede', 'Rede', recSecRedeAbas, recLigarRede);
