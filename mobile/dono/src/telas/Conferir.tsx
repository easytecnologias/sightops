import { useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  diaRotulo, hm, moeda, num, SEM_LOJA, useCaixas, useCupons, useEventos, useFiltro, useResumo, type Cupom,
} from '../lib/pdv';
import { Carregando, Erro, Icone, Vazio } from '../ui/pecas';
import { EscolherLoja, LinhaCupom } from './Comum';

const ABAS: [string, string][] = [
  ['cancelados', 'Cancelados'], ['descontos', 'Descontos'], ['cupons_cancelados', 'Cupom cancelado'],
  ['sangrias', 'Sangrias'], ['gaveta', 'Gaveta'], ['semcad', 'Sem cadastro'],
];
const EV: Record<string, string> = { sangrias: 'SGR', gaveta: 'GAV', semcad: 'ITEMSEMCAD' };

type LinhaV = { chave: string; caixaId: string; cupom: string; html: JSX.Element; valor: number };

export function Conferir() {
  const [qs, setQs] = useSearchParams();
  const aba = ABAS.some((a) => a[0] === qs.get('t')) ? qs.get('t')! : 'cancelados';
  const { dia, loja } = useFiltro();
  const [pdv, setPdv] = useState('');
  const [folhaLoja, setFolhaLoja] = useState(false);
  const [numero, setNumero] = useState('');
  const ir = useNavigate();
  const caixas = useCaixas();
  const cupons = useCupons(dia);
  const resumo = useResumo(dia, loja);
  const evTipo = EV[aba] || '';
  const eventos = useEventos(dia, evTipo || 'SGR', !!evTipo);

  const daLoja = useMemo(() => new Set((caixas.data || []).filter((c) => !loja || (c.site || SEM_LOJA) === loja).map((c) => c.id)), [caixas.data, loja]);
  const pdvs = (caixas.data || []).filter((c) => daLoja.has(c.id)).sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', { numeric: true }));
  const porChave = useMemo(() => new Map((cupons.data || []).map((k) => [`${k.caixa_id}|${k.cupom}`, k])), [cupons.data]);

  let linhas: LinhaV[] = [];
  let carregando = cupons.isLoading;
  let erro: unknown = cupons.error;
  if (aba === 'cancelados' || aba === 'cupons_cancelados') {
    const f = aba === 'cancelados' ? (k: Cupom) => k.itens_cancelados > 0 : (k: Cupom) => k.situacao === 'cancelado';
    linhas = (cupons.data || []).filter(f).map((k) => ({
      chave: `${k.caixa_id}|${k.cupom}`, caixaId: k.caixa_id, cupom: k.cupom, valor: 0,
      html: <LinhaCupom key={`${k.caixa_id}|${k.cupom}`} k={k} tipo={aba === 'cancelados' ? 'CIT' : 'CCV'}
        txt={aba === 'cancelados' ? `${k.itens_cancelados} ${k.itens_cancelados === 1 ? 'item cancelado' : 'itens cancelados'}` : `${k.itens} itens`} />,
    }));
  } else if (aba === 'descontos') {
    carregando = carregando || resumo.isLoading;
    erro = erro || resumo.error;
    const grupos = new Map<string, { v: number; n: number; prods: string[]; ts: string; tipo: string }>();
    for (const d of resumo.data?.descontos || []) {
      const ch = `${d.caixa_id}|${d.cupom}`;
      const g = grupos.get(ch) || { v: 0, n: 0, prods: [], ts: d.ts, tipo: d.tipo === 'item' ? 'DIT' : 'DAS' };
      g.v += d.valor_centavos; g.n += 1;
      if (d.ts < g.ts) { g.ts = d.ts; g.tipo = d.tipo === 'item' ? 'DIT' : 'DAS'; }
      if (d.produto && !g.prods.includes(d.produto)) g.prods.push(d.produto);
      grupos.set(ch, g);
    }
    linhas = [...grupos.entries()].map(([ch, g]) => {
      const k = porChave.get(ch);
      if (!k) return null;
      return { chave: ch, caixaId: k.caixa_id, cupom: k.cupom, valor: g.v,
        html: <LinhaCupom key={ch} k={k} tipo={g.tipo} valor={`− ${moeda(g.v)}`}
          txt={`${g.n} ${g.n === 1 ? 'desconto' : 'descontos'}${g.prods.length ? ` · ${g.prods.slice(0, 2).join(', ')}` : ' no subtotal'}`} /> };
    }).filter(Boolean) as LinhaV[];
  } else {
    carregando = eventos.isLoading;
    erro = eventos.error;
    linhas = (eventos.data || []).map((e) => {
      const nome = { SGR: 'Sangria', GAV: 'Gaveta aberta', ITEMSEMCAD: 'Código sem cadastro' }[evTipo] || '';
      const rot = `${nome}${e.codigo && evTipo === 'ITEMSEMCAD' ? ` · ${e.codigo}` : ''}`;
      const k = e.cupom ? porChave.get(`${e.caixa_id}|${e.cupom}`) : undefined;
      const ch = `${e.caixa_id}|${e.ts}`;
      if (k) return { chave: ch, caixaId: e.caixa_id, cupom: e.cupom, valor: e.valor_centavos, html: <LinhaCupom key={ch} k={k} ts={e.ts} txt={rot} valor={e.valor_centavos ? moeda(e.valor_centavos) : ''} /> };
      const op = e.operador && e.operador !== '?' ? e.operador : '';
      return { chave: ch, caixaId: e.caixa_id, cupom: e.cupom || '', valor: e.valor_centavos,
        html: (
          <Link key={ch} to={`/momento/${encodeURIComponent(e.caixa_id)}?ts=${encodeURIComponent(e.ts)}&rot=${encodeURIComponent(`${rot}${e.valor_centavos ? ` · ${moeda(e.valor_centavos)}` : ''}`)}`} className="linha">
            <span className="hora">{hm(e.ts)}</span>
            <span className="col cresce"><b>{e.caixa}{op ? ` · ${op}` : ''}</b><small className="sub um">{rot} · fora de cupom</small></span>
            <span className="col dir">{e.valor_centavos ? <b>{moeda(e.valor_centavos)}</b> : null}</span>
            <span className="play-azul">{Icone.playCirc}</span>
          </Link>
        ) };
    });
  }
  const nBusca = numero.trim().replace(/^0+/, '');
  linhas = linhas.filter((l) => daLoja.has(l.caixaId) && (!pdv || l.caixaId === pdv)
    && (!nBusca || l.cupom.replace(/^0+/, '').includes(nBusca)));
  const soma = linhas.reduce((t, l) => t + l.valor, 0);

  return (
    <>
      <section className="topo-azul baixo">
        <div className="linha-entre">
          <div className="col"><span className="claro">{diaRotulo(dia)} · {loja || 'todas as lojas'}</span><h1>Conferir</h1></div>
          <span className="claro"><b className="t17 branco">{num(linhas.length)}</b> {aba === 'sangrias' || aba === 'gaveta' || aba === 'semcad' ? 'registros' : 'cupons'}</span>
        </div>
        <div className="abas-rolam" role="tablist">
          {ABAS.map(([id, rot]) => (
            <button type="button" role="tab" key={id} aria-selected={aba === id} className={aba === id ? 'on' : ''} onClick={() => setQs({ t: id }, { replace: true })}>{rot}</button>
          ))}
        </div>
      </section>
      <form className="busca-num" role="search" onSubmit={(ev) => { ev.preventDefault(); if (numero.trim()) ir(`/busca/${encodeURIComponent(numero.trim())}`); }}>
        <label>{Icone.busca}<input type="search" inputMode="numeric" placeholder="Nº do cupom" aria-label="Número do cupom"
          value={numero} onChange={(e) => setNumero(e.target.value)} /></label>
        <button type="submit">Abrir</button>
      </form>
      <div className="filtros">
        <button type="button" className="chip" onClick={() => setFolhaLoja(true)}>{Icone.loja}{loja || 'Todas as lojas'}{Icone.baixo}</button>
        <label className="chip">
          <select value={pdv} onChange={(e) => setPdv(e.target.value)} aria-label="PDV">
            <option value="">Todos os PDVs</option>
            {pdvs.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}
          </select>{Icone.baixo}
        </label>
        {soma ? <span className="sub dir-auto">{aba === 'descontos' ? '− ' : ''}{moeda(soma)}</span> : null}
      </div>
      <div className="pagina lista-cheia">
        {carregando ? <Carregando /> : erro ? <Erro erro={erro} /> : linhas.length ? <div className="cartao lista">{linhas.map((l) => l.html)}</div>
          : nBusca ? <div className="col" style={{ alignItems: 'center', gap: 10 }}><Vazio texto={`O cupom ${numero.trim()} não está nesta lista.`} />
              <button type="button" className="btn2" onClick={() => ir(`/busca/${encodeURIComponent(numero.trim())}`)}>{Icone.busca} Procurar em todos os cupons do dia</button></div>
          : <Vazio texto="Nada aqui neste dia." />}
      </div>
      {folhaLoja ? <EscolherLoja aoFechar={() => setFolhaLoja(false)} /> : null}
    </>
  );
}
