import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { dec, diaRotulo, hoje, iniciais, moeda, mudarDia, num, tempo, useFiltro, useRankings, type Rank } from '../lib/pdv';
import { Cabecalho, Carregando, Erro, Icone, Pos, Vazio } from '../ui/pecas';

type Card = { id: keyof Rank; titulo: string; melhor: 'alto' | 'baixo'; ruim?: boolean; taxa?: boolean; fmt: (v: number) => string; sub: (x: Rank) => string };
const CARDS: Card[] = [
  { id: 'vendido', titulo: 'Quem mais vende', melhor: 'alto', fmt: moeda, sub: (x) => `${num(x.cupons)} cupons · ticket ${moeda(x.ticket)}` },
  { id: 'cupons', titulo: 'Mais clientes atendidos', melhor: 'alto', fmt: num, sub: (x) => `${num(x.itens)} itens · ${x.dias} ${x.dias === 1 ? 'dia' : 'dias'}` },
  { id: 'vendido_por_hora', titulo: 'Mais venda por hora atendendo', melhor: 'alto', taxa: true, fmt: moeda, sub: (x) => `${dec(x.horas_atendendo)} h atendendo` },
  { id: 'tempo_mediano_s', titulo: 'Atende cada cliente mais rápido', melhor: 'baixo', taxa: true, fmt: tempo, sub: (x) => `por cliente · ${dec(x.itens_por_cupom)} itens em média` },
  { id: 'seg_por_item', titulo: 'Passa os itens mais rápido', melhor: 'baixo', taxa: true, fmt: (v) => `${dec(v)} s/item`, sub: (x) => `${num(x.itens)} itens` },
  { id: 'ticket', titulo: 'Maior ticket médio', melhor: 'alto', taxa: true, fmt: moeda, sub: (x) => `${num(x.cupons)} cupons` },
  { id: 'cancelados_por_mil', titulo: 'Cancelamentos de item', melhor: 'baixo', ruim: true, taxa: true, fmt: (v) => `${dec(v)} ‰`, sub: (x) => `${num(x.itens_cancelados)} ${x.itens_cancelados === 1 ? 'item' : 'itens'} · ${moeda(x.valor_cancelado)}` },
  { id: 'descontos', titulo: 'Descontos dados', melhor: 'baixo', ruim: true, fmt: moeda, sub: (x) => `${num(x.cupons)} cupons no período` },
  { id: 'pct_digitado', titulo: 'Itens digitados em vez de bipados', melhor: 'baixo', ruim: true, taxa: true, fmt: (v) => `${dec(v)}%`, sub: (x) => `${num(x.digitados)} de ${num(x.itens)} itens` },
  { id: 'gaveta_fora', titulo: 'Gaveta aberta fora de venda', melhor: 'baixo', ruim: true, fmt: num, sub: (x) => `${num(x.cupons)} cupons no período` },
  { id: 'sem_cadastro', titulo: 'Código sem cadastro', melhor: 'baixo', ruim: true, fmt: num, sub: (x) => `${num(x.itens)} itens no período` },
  { id: 'valor_sangrias', titulo: 'Sangrias', melhor: 'baixo', ruim: true, fmt: moeda, sub: (x) => `${num(x.sangrias)} retiradas` },
];

// periodo e operador/caixa ficam guardados enquanto o app esta aberto (a ficha usa os mesmos)
let _periodo = '7';
let _por: 'operadores' | 'caixas' = 'operadores';
function datas(p: string): [string, string] {
  const h = hoje();
  if (p === 'hoje') return [h, h];
  if (p === 'ontem') { const o = mudarDia(h, -1); return [o, o]; }
  return [mudarDia(h, -(Number(p) - 1)), h];
}

function ordenar(card: Card, lista: Rank[], min: number) {
  const v = (x: Rank) => x[card.id] as number | null;
  const validos = lista.filter((x) => v(x) !== null && v(x) !== undefined && ((!card.taxa && card.ruim) || x.cupons >= min));
  validos.sort((a, b) => (card.melhor === 'alto' ? (v(b)! - v(a)!) : (v(a)! - v(b)!)));
  const pos: number[] = [];
  validos.forEach((x, i) => { pos[i] = i && v(validos[i - 1]) === v(x) ? pos[i - 1] : i + 1; });
  return { ord: validos, pos };
}

export function Rankings() {
  const { loja } = useFiltro();
  const [periodo, setPeriodo] = useState(_periodo);
  const [por, setPor] = useState(_por);
  const [todos, setTodos] = useState<Record<string, boolean>>({});
  const [de, ate] = datas(periodo);
  const rk = useRankings(de, ate, loja);
  const lista = rk.data?.[por] || [];
  const min = rk.data?.minimo_cupons || 10;
  const mudarPeriodo = (p: string) => { _periodo = p; setPeriodo(p); };
  const mudarPor = (p: 'operadores' | 'caixas') => { _por = p; setPor(p); };

  return (
    <>
      <section className="topo-azul baixo">
        <div className="linha-entre">
          <div className="col"><span className="claro">{de === ate ? diaRotulo(de) : `${diaRotulo(de)} a ${diaRotulo(ate).toLowerCase()}`} · {loja || 'todas as lojas'}</span><h1>Rankings</h1></div>
          <div className="seg pequeno">
            <button type="button" className={por === 'operadores' ? 'on' : ''} onClick={() => mudarPor('operadores')}>Operador</button>
            <button type="button" className={por === 'caixas' ? 'on' : ''} onClick={() => mudarPor('caixas')}>Caixa</button>
          </div>
        </div>
        <div className="seg largo">
          {[['hoje', 'Hoje'], ['ontem', 'Ontem'], ['7', '7 dias'], ['30', '30 dias']].map(([p, rot]) => (
            <button type="button" key={p} className={periodo === p ? 'on' : ''} onClick={() => mudarPeriodo(p)}>{rot}</button>
          ))}
        </div>
      </section>
      <div className="pagina">
        {rk.isLoading ? <Carregando texto="Calculando os rankings…" /> : rk.error ? <Erro erro={rk.error} aoTentar={() => rk.refetch()} />
          : !lista.length ? <Vazio texto="Nenhuma venda no período." /> : CARDS.map((card) => {
            const { ord, pos } = ordenar(card, lista, min);
            const n = ord.length;
            const linha = (i: number) => {
              const x = ord[i];
              const ruim = n > 6 && i >= n - 3;
              const bom = n > 6 ? i < 3 : true;
              return (
                <Link key={x.chave} to={`/ficha/${por}/${encodeURIComponent(x.chave)}`} className="linha-rank">
                  <Pos n={pos[i]} tipo={ruim ? 'ruim' : bom ? 'bom' : ''} />
                  <span className="col cresce"><b className="um">{x.nome}</b><small className="sub um">{card.sub(x)}</small></span>
                  <b className="num">{card.fmt(x[card.id] as number)}</b>
                </Link>
              );
            };
            const idx = [...Array(n).keys()];
            const aberto = !!todos[card.id as string];
            const melhores = <><span className="sep">Melhores</span>{idx.slice(0, 3).map(linha)}</>;
            const piores = <><span className="sep ruim">Piores</span>{idx.slice(n - 3).map(linha)}</>;
            return (
              <section key={card.id as string} className="cartao lista">
                <span className="linha-entre"><b className="t14">{card.titulo}</b><small className="sub">{n} no ranking</small></span>
                {!n ? <Vazio texto="Sem dados suficientes." /> : aberto || n <= 6 ? idx.map(linha) : card.ruim ? <>{piores}{melhores}</> : <>{melhores}{piores}</>}
                {n > 6 ? <button type="button" className="link-azul centro" onClick={() => setTodos({ ...todos, [card.id as string]: !aberto })}>
                  {aberto ? 'Mostrar só os 3 melhores e os 3 piores' : `Ver a lista inteira (${n})`}</button> : null}
                {card.taxa || !card.ruim ? <small className="sub">só quem atendeu {min} cupons ou mais</small> : null}
              </section>
            );
          })}
      </div>
    </>
  );
}

export function Ficha() {
  const { por = 'operadores', chave = '' } = useParams();
  const { loja } = useFiltro();
  const [de, ate] = datas(_periodo);
  const rk = useRankings(de, ate, loja);
  const lista = rk.data?.[por as 'operadores' | 'caixas'] || [];
  const x = lista.find((o) => o.chave === chave);
  const min = rk.data?.minimo_cupons || 10;
  return (
    <>
      <Cabecalho titulo={x?.nome || 'Ficha'} sub={x ? `${por === 'operadores' ? x.outros.join(', ') : x.loja} · ${de === ate ? diaRotulo(de) : `${diaRotulo(de)} a ${diaRotulo(ate).toLowerCase()}`}` : ''} />
      <div className="pagina">
        {rk.isLoading ? <Carregando /> : !x ? <Vazio texto="Não achei esta pessoa no período." /> : (
          <>
            <div className="ficha-topo">
              <span className="avatar">{iniciais(x.nome)}</span>
              <div className="grade3">
                <div className="cartao mini col"><small className="rotulo">Vendido</small><b>{moeda(x.vendido)}</b></div>
                <div className="cartao mini col"><small className="rotulo">Cupons</small><b>{num(x.cupons)}</b></div>
                <div className="cartao mini col"><small className="rotulo">Dias</small><b>{num(x.dias)}</b></div>
              </div>
            </div>
            <section className="cartao lista">
              <span className="linha-entre"><b className="t14">Posição em cada ranking</b><small className="sub">azul = melhores · vermelho = piores</small></span>
              {CARDS.map((card) => {
                const { ord, pos } = ordenar(card, lista, min);
                const i = ord.findIndex((o) => o.chave === chave);
                const n = ord.length;
                const tipo = i < 0 ? '' : n > 6 && i >= n - 3 ? 'ruim' : i < 3 ? 'bom' : '';
                const largura = i < 0 || n < 2 ? 0 : Math.max(3, Math.round(100 * (n - 1 - i) / (n - 1)));
                return (
                  <div key={card.id as string} className="linha-ficha">
                    {i < 0 ? <span className="pos">–</span> : <Pos n={pos[i]} tipo={tipo} />}
                    <span className="col cresce">
                      <span className="linha-entre"><b className="um">{card.titulo}</b><b className="num">{card.fmt(x[card.id] as number)}</b></span>
                      {i < 0 ? <small className="sub">fora deste ranking (menos de {min} cupons)</small> : (
                        <span className="linha-entre"><span className={`barra fina ${tipo === 'ruim' ? 'ruim' : ''}`}><i style={{ width: `${largura}%` }} /></span><small className="sub">{pos[i]}º de {n}</small></span>
                      )}
                    </span>
                  </div>
                );
              })}
            </section>
            {por === 'operadores' ? <Link to={`/olhar?op=${encodeURIComponent(x.nome)}`} className="cartao link-azul centro">{Icone.olho} Ver os momentos para olhar desta pessoa</Link> : null}
          </>
        )}
      </div>
    </>
  );
}
