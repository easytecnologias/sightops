import { useState } from 'react';
import { Link } from 'react-router-dom';
import { dec, hoje, iniciais, moeda, mudarDia, num, tempo, useFiltro, useMomentos, useRankings } from '../lib/pdv';
import { Carregando, Erro, Vazio } from '../ui/pecas';
import { semRota } from './Olhar';

const PERIODOS: [string, string][] = [['hoje', 'Hoje'], ['7', '7 dias'], ['30', '30 dias']];
function datas(p: string): [string, string] {
  const h = hoje();
  return p === 'hoje' ? [h, h] : [mudarDia(h, -(Number(p) - 1)), h];
}

/** Equipe: em cima so quem esta fora do normal da loja; embaixo todos por venda. */
export function Equipe() {
  const { loja } = useFiltro();
  const [periodo, setPeriodo] = useState('7');
  const [de, ate] = datas(periodo);
  const rk = useRankings(de, ate, loja);
  const mom = useMomentos(hoje(), loja);
  const fora = mom.data?.fora_da_media || [];
  const nomes = mom.data?.regras || {};
  const lista = [...(rk.data?.operadores || [])].sort((a, b) => b.vendido - a.vendido);
  const foraNomes = new Set(fora.map((f) => f.operador));

  return (
    <>
      <section className="topo-azul baixo">
        <div className="col"><span className="claro">{loja || 'Todas as lojas'}</span><h1>Equipe</h1></div>
        <div className="seg largo tres">
          {PERIODOS.map(([p, rot]) => <button type="button" key={p} className={periodo === p ? 'on' : ''} onClick={() => setPeriodo(p)}>{rot}</button>)}
        </div>
      </section>
      <div className="pagina">
        {mom.isLoading ? null : mom.error ? (semRota(mom.error) ? null : <Erro erro={mom.error} />) : (
          <section className="cartao lista">
            <span className="rotulo">Fora do normal da loja · últimos {mom.data?.media_dias || 7} dias</span>
            {!fora.length ? <span className="sub vazio-curto">Ninguém bem acima da média da loja.</span> : fora.map((f) => (
              <Link key={`${f.loja}|${f.operador}`} to={`/olhar?op=${encodeURIComponent(f.operador)}`} className="linha">
                <span className="avatar peq ruim">{iniciais(f.operador)}</span>
                <span className="col cresce"><b className="um">{f.operador}</b>
                  <small className="sub um">mais {(nomes[f.regra_principal] || f.regra_principal).toLowerCase()} · {num(f.momentos)} em {num(f.cupons)} cupons</small></span>
                <span className="col dir"><b className="verm num">{dec(f.vezes)}×</b><small className="sub">a média</small></span>
              </Link>
            ))}
          </section>
        )}

        {rk.isLoading ? <Carregando texto="Somando as vendas…" /> : rk.error ? <Erro erro={rk.error} aoTentar={() => rk.refetch()} />
          : !lista.length ? <Vazio texto="Nenhuma venda no período." /> : (
            <section className="cartao lista">
              <span className="linha-entre"><span className="rotulo">Todos · por venda</span><small className="sub">{num(lista.length)} operadores</small></span>
              {lista.map((x) => (
                <Link key={x.chave} to={`/ficha/operadores/${encodeURIComponent(x.chave)}`} className="linha">
                  <span className={`avatar peq ${foraNomes.has(x.nome) ? 'ruim' : ''}`}>{iniciais(x.nome)}</span>
                  <span className="col cresce"><b className="um">{x.nome}</b>
                    <small className="sub um">{num(x.cupons)} cupons · {tempo(x.tempo_mediano_s)} por cliente</small></span>
                  <b className="num">{moeda(x.vendido)}</b>
                </Link>
              ))}
            </section>
          )}
        <Link to="/rankings" className="link-azul centro">Ver os rankings completos</Link>
      </div>
    </>
  );
}
