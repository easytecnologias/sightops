import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ErroApi } from '../lib/api';
import { destinoMomento, diaRotulo, GRAV, grave, hm, hoje, moeda, mudarDia, num, useFiltro, useMomentos, type Momento } from '../lib/pdv';
import { Carregando, Erro, Ico, Icone, Vazio } from '../ui/pecas';
import { EscolherLoja } from './Comum';

/** Icone e cor de cada regra. */
export const REGRA_ICONE: Record<string, [JSX.Element, 'verm' | 'ambar' | 'azul' | 'ciano']> = {
  gaveta_sem_venda: [Icone.gaveta, 'verm'], cupom_cancelado: [Icone.proibido, 'verm'], item_cancelado: [Icone.x, 'ambar'],
  sem_cadastro_digitado: [Icone.scan, 'ambar'], digitado_fora_padrao: [Icone.teclado, 'ambar'], cupom_parado: [Icone.relogio, 'azul'],
};

/** Uma linha de momento: o que a regra pegou, onde, quem e a gravidade. Abre o video no horario. */
export function LinhaMomento({ m, comLoja = false }: { m: Momento; comLoja?: boolean }) {
  const [ic, cor] = REGRA_ICONE[m.regra] || [Icone.relogio, 'ambar'];
  return (
    <Link to={destinoMomento(m)} className="linha">
      <Ico cor={m.gravidade === 'alta' ? 'verm' : cor}>{ic}</Ico>
      <span className="col cresce">
        <b className="um">{m.titulo}</b>
        <small className="sub um">{m.caixa}{comLoja ? ` · ${m.loja}` : ''}{m.operador ? ` · ${m.operador}` : ''}{m.valor_centavos ? ` · ${moeda(m.valor_centavos)}` : ''}</small>
        <small className="sub um">{m.detalhe}</small>
      </span>
      <span className="col dir"><small className="sub num">{hm(m.ts)}</small><span className={`grav ${m.gravidade}`}>{GRAV[m.gravidade]}</span></span>
    </Link>
  );
}

/** O servidor ainda sem a rota (publicacao pendente) nao pode parecer "dia normal". */
export function semRota(erro: unknown) {
  return erro instanceof ErroApi && erro.status === 404;
}

type Filtro = 'graves' | 'alta' | 'media' | 'todos';

/** Para olhar: so o que uma regra apontou, mais grave primeiro, com o motivo escrito. */
export function ParaOlhar() {
  const { dia, setDia, loja } = useFiltro();
  const [qs] = useSearchParams();
  const op = qs.get('op') || '';
  const r = useMomentos(dia, loja);
  const [filtro, setFiltro] = useState<Filtro>('graves');
  const [regra, setRegra] = useState('');
  const [folha, setFolha] = useState(false);
  const todos = (r.data?.momentos || []).filter((m) => !op || m.operador === op);
  const porFiltro = todos.filter((m) => filtro === 'todos' || (filtro === 'graves' ? grave(m) : m.gravidade === filtro));
  const contaRegra = new Map<string, number>();
  porFiltro.forEach((m) => contaRegra.set(m.regra, (contaRegra.get(m.regra) || 0) + 1));
  const lista = porFiltro.filter((m) => !regra || m.regra === regra);
  const g = r.data?.gravidades;
  const variasLojas = (r.data?.lojas?.length || 0) > 1 && !loja;
  const nomes = r.data?.regras || {};

  return (
    <>
      <section className="topo-azul baixo">
        <div className="linha-entre">
          <div className="col"><span className="claro">{diaRotulo(dia)} · {loja || 'todas as lojas'}</span><h1>Para olhar</h1></div>
          {g ? <div className="col dir"><strong className="t20">{num(g.alta + g.media)}</strong><span className="claro">alta ou média</span></div> : null}
        </div>
        {op ? <span className="claro">Só os momentos de <b className="branco">{op}</b> · <Link to="/olhar" className="branco">ver todos</Link></span> : null}
        <div className="linha-entre">
          <div className="seg">
            <button type="button" className={dia === hoje() ? 'on' : ''} onClick={() => setDia(hoje())}>Hoje</button>
            <button type="button" className={dia === mudarDia(hoje(), -1) ? 'on' : ''} onClick={() => setDia(mudarDia(hoje(), -1))}>Ontem</button>
          </div>
          <label className="bt-vidro data">{Icone.calendario}
            <input type="date" value={dia} max={hoje()} onChange={(e) => e.target.value && setDia(e.target.value)} aria-label="Escolher o dia" /></label>
          <button type="button" className="bt-vidro" onClick={() => setFolha(true)} aria-label="Escolher a loja">{Icone.loja}{Icone.baixo}</button>
        </div>
        <div className="seg largo">
          {([['graves', 'Graves'], ['alta', `Alta ${g ? g.alta : ''}`], ['media', `Média ${g ? g.media : ''}`], ['todos', 'Todos']] as [Filtro, string][]).map(([k, rot]) => (
            <button type="button" key={k} className={filtro === k ? 'on' : ''} onClick={() => { setFiltro(k); setRegra(''); }}>{rot}</button>
          ))}
        </div>
      </section>
      <div className="pagina">
        {contaRegra.size > 1 ? (
          <div className="chips-rolam">
            <button type="button" className={`chip ${!regra ? 'on' : ''}`} onClick={() => setRegra('')}>Todas <b>{num(porFiltro.length)}</b></button>
            {[...contaRegra.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => (
              <button type="button" key={k} className={`chip ${regra === k ? 'on' : ''}`} onClick={() => setRegra(k)}>{nomes[k] || k} <b>{num(n)}</b></button>
            ))}
          </div>
        ) : null}
        {r.isLoading ? <Carregando texto="Procurando o que olhar…" />
          : r.error ? (semRota(r.error) ? <Vazio texto="O servidor ainda não tem os momentos para olhar. Eles chegam com a próxima atualização do SightOps." /> : <Erro erro={r.error} aoTentar={() => r.refetch()} />)
          : !lista.length ? (
            <div className="cartao vazio-ok">{Icone.ok}<span>{todos.length ? 'Nada com esse filtro.' : 'Nada fora do normal neste dia.'}</span></div>
          ) : (
            <div className="cartao lista">{lista.map((m) => <LinhaMomento key={`${m.caixa_id}|${m.seq}|${m.regra}`} m={m} comLoja={variasLojas} />)}</div>
          )}
        <p className="nota">Regras sobre os dados do próprio caixa. O vídeo é a prova: toque para ver o momento.</p>
      </div>
      {folha ? <EscolherLoja aoFechar={() => setFolha(false)} /> : null}
    </>
  );
}
