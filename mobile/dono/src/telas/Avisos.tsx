import { Link } from 'react-router-dom';
import { diaRotulo, hm, hoje, textoAlerta, useFiltro, useLojas, type Alerta } from '../lib/pdv';
import { Carregando, Erro, Ico, Icone, Vazio } from '../ui/pecas';

const ICONE: Record<string, [JSX.Element, 'verm' | 'ambar' | 'azul']> = {
  CIT: [Icone.x, 'verm'], CCV: [Icone.proibido, 'verm'], CCG: [Icone.proibido, 'verm'],
  ITEMSEMCAD: [Icone.scan, 'ambar'], DST: [Icone.pct, 'ambar'], SGR: [Icone.dinheiro, 'azul'],
};

function destino(a: Alerta) {
  return a.cupom
    ? `/cupom/${encodeURIComponent(a.caixa_id)}/${a.ts.slice(0, 10)}/${encodeURIComponent(a.cupom)}?ts=${encodeURIComponent(a.ts)}`
    : `/momento/${encodeURIComponent(a.caixa_id)}?ts=${encodeURIComponent(a.ts)}&rot=${encodeURIComponent(textoAlerta(a))}`;
}

/** O que aconteceu de fora do normal no dia (as ocorrencias da tela Lojas). */
export function Avisos() {
  const { dia, loja } = useFiltro();
  const r = useLojas(dia);
  const alertas = (r.data?.alertas || []).filter((a) => !loja || a.loja === loja);
  return (
    <>
      <section className="topo-azul baixo">
        <div className="col"><span className="claro">{diaRotulo(dia)} · {loja || 'todas as lojas'}</span><h1>Avisos</h1></div>
        <span className="claro">Cancelamentos, sangrias, descontos e códigos sem cadastro{dia === hoje() ? ', atualizado a cada 30 segundos' : ''}.</span>
      </section>
      <div className="pagina">
        {r.isLoading ? <Carregando /> : r.error ? <Erro erro={r.error} aoTentar={() => r.refetch()} /> : !alertas.length ? <Vazio texto="Nada fora do normal neste dia." /> : (
          <div className="cartao lista">
            {alertas.map((a) => {
              const [ic, cor] = ICONE[a.tipo] || [Icone.relogio, 'ambar'];
              return (
                <Link key={`${a.caixa_id}${a.ts}${a.tipo}`} to={destino(a)} className="linha">
                  <Ico cor={cor}>{ic}</Ico>
                  <span className="col cresce"><b className="um">{a.caixa}{(r.data?.lojas.length || 0) > 1 ? ` · ${a.loja}` : ''}</b><small className="sub um">{textoAlerta(a)}</small></span>
                  <span className="col dir"><small className="sub">{hm(a.ts)}</small><span className="play-azul">{Icone.play}</span></span>
                </Link>
              );
            })}
          </div>
        )}
        <p className="nota">Aviso no celular na hora (notificação) fica para a próxima versão.</p>
      </div>
    </>
  );
}
