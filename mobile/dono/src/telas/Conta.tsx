import { Link } from 'react-router-dom';
import { diaRotulo, moeda, num, pct, useFiltro, useResumo } from '../lib/pdv';
import { Cabecalho, Carregando, Erro, Icone } from '../ui/pecas';

/** Do valor passado no caixa ao vendido: o que saiu no caminho. */
export function Conta() {
  const { dia, loja } = useFiltro();
  const resumo = useResumo(dia, loja);
  const r = resumo.data;
  const c = r?.conferencia;
  const m = r?.modos || {};
  const n = (k: string) => m[k]?.n || 0;
  const itens = r?.itens || 0;
  const linhas: [string, number, string][] = c ? [
    ['Cupons cancelados inteiros', c.cupons_cancelados, 'cupons_cancelados'],
    ['Itens cancelados', c.itens_cancelados, 'cancelados'],
    ['Descontos em item', c.desc_item, 'descontos'],
    ['Descontos no subtotal do cupom', c.desc_subtotal, 'descontos'],
    ['Descontos sem registro no PDV', c.desc_outros, ''],
    ['Cupons ainda abertos', c.abertos, ''],
  ] : [];
  const saiu = linhas.reduce((t, l) => t + l[1], 0);
  return (
    <>
      <Cabecalho titulo="Conta do dia" sub={`${diaRotulo(dia)} · ${loja || 'todas as lojas'}`} />
      <div className="pagina">
        {resumo.isLoading ? <Carregando /> : resumo.error ? <Erro erro={resumo.error} aoTentar={() => resumo.refetch()} /> : c ? (
          <>
            <section className="cartao">
              <span className="rotulo">Valor passado no caixa</span>
              <strong className="grande">{moeda(c.passado)}</strong>
              <span className="barra-modos">
                <i style={{ flex: n('scanner') || 0.01, background: '#1971c2' }} /><i style={{ flex: n('manual'), background: '#f59f00' }} />
                <i style={{ flex: n('menu'), background: '#0b7285' }} /><i style={{ flex: n('sem_tecla') + n('outro'), background: '#adb5bd' }} />
              </span>
              <span className="legenda">
                <span><b style={{ color: '#1971c2' }}>●</b> {pct(n('scanner'), itens)} bipados</span>
                <span><b style={{ color: '#f59f00' }}>●</b> {pct(n('manual'), itens)} digitados</span>
                <span><b style={{ color: '#0b7285' }}>●</b> {pct(n('menu'), itens)} menu</span>
                <span><b style={{ color: '#adb5bd' }}>●</b> {pct(n('sem_tecla') + n('outro'), itens)} sem tecla</span>
              </span>
            </section>
            <section className="cartao lista">
              {linhas.filter((l) => l[1]).map(([rot, v, tipo]) => tipo ? (
                <Link key={rot} to={`/conferir?t=${tipo}`} className="linha-conta">
                  <span className="cresce">{rot}</span><b className="verm">− {moeda(v)}</b>{Icone.dir}</Link>
              ) : (
                <div key={rot} className="linha-conta apagada"><span className="cresce">{rot}</span><b className="verm">− {moeda(v)}</b><span style={{ width: 16 }} /></div>
              ))}
              <div className="linha-conta total"><span className="cresce">Total que saiu da soma dos itens</span><b className="verm">− {moeda(saiu)}</b><span style={{ width: 16 }} /></div>
            </section>
            <section className="cartao azul">
              <span className="rotulo">Vendido · cupons fechados</span>
              <strong className="grande">{moeda(r?.vendido_centavos)}</strong>
              <span className="sub">{moeda(c.passado)} − {moeda(saiu)} · {num(r?.cupons?.fechado || 0)} cupons</span>
            </section>
            <p className="nota">Toque numa linha para ver os cupons e o vídeo de cada um.</p>
          </>
        ) : <Erro erro={new Error('O servidor ainda não manda a conta do dia.')} />}
      </div>
    </>
  );
}
