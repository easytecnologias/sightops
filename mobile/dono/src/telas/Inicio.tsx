import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { diaRotulo, hoje, moeda, mudarDia, num, useFiltro, useLojas, useResumo } from '../lib/pdv';
import { Carregando, Erro, Ico, Icone } from '../ui/pecas';
import { EscolherLoja } from './Comum';

export function Inicio({ aoSair }: { aoSair: () => void }) {
  const { dia, setDia, loja } = useFiltro();
  const resumo = useResumo(dia, loja);
  const lojas = useLojas(dia);
  const ir = useNavigate();
  const [numero, setNumero] = useState('');
  const [folhaLoja, setFolhaLoja] = useState(false);

  function buscar(ev: FormEvent) {
    ev.preventDefault();
    const n = numero.trim();
    if (n) ir(`/busca/${encodeURIComponent(n)}`);
  }

  const r = resumo.data;
  const c = r?.conferencia;
  const saiu = c ? c.cupons_cancelados + c.itens_cancelados + c.descontos + c.abertos + c.sem_cupom : 0;
  const fechados = r?.cupons?.fechado || 0;
  const ev = r?.eventos || {};
  const listaLojas = (lojas.data?.lojas || []).filter((l) => !loja || l.nome === loja);
  const rede = lojas.data?.rede?.vendido_centavos || 0;

  return (
    <>
      <section className="topo-azul">
        <div className="linha-entre">
          <div className="col"><strong className="t15">Ponto de venda</strong><span className="claro">{loja || 'Todas as lojas'}</span></div>
          <button type="button" className="bt-vidro" onClick={aoSair} aria-label="Sair">{Icone.sair}</button>
        </div>
        <form className="busca" role="search" onSubmit={buscar}>
          <label>{Icone.busca}<input type="search" inputMode="numeric" placeholder="Digite o nº do cupom" aria-label="Número do cupom"
            value={numero} onChange={(e) => setNumero(e.target.value)} /></label>
          <button type="submit">Abrir</button>
        </form>
        <div className="linha-entre">
          <div className="seg">
            <button type="button" className={dia === hoje() ? 'on' : ''} onClick={() => setDia(hoje())}>Hoje</button>
            <button type="button" className={dia === mudarDia(hoje(), -1) ? 'on' : ''} onClick={() => setDia(mudarDia(hoje(), -1))}>Ontem</button>
          </div>
          <label className="bt-vidro data">{Icone.calendario}
            <input type="date" value={dia} max={hoje()} onChange={(e) => e.target.value && setDia(e.target.value)} aria-label="Escolher o dia" /></label>
          <button type="button" className="bt-vidro" onClick={() => setFolhaLoja(true)}>{Icone.loja}{Icone.baixo}</button>
        </div>
      </section>

      <div className="pagina sobe">
        {resumo.isLoading ? <Carregando /> : resumo.error ? <Erro erro={resumo.error} aoTentar={() => resumo.refetch()} /> : (
          <Link to="/conta" className="cartao destaque">
            <span className="linha-entre"><span className="rotulo">Vendido · {diaRotulo(dia).toLowerCase()}</span><span className="link-azul">Ver a conta ›</span></span>
            <strong className="grande">{moeda(r?.vendido_centavos)}</strong>
            <span className="sub">{num(fechados)} cupons · ticket {moeda(fechados ? (r?.vendido_centavos || 0) / fechados : 0)}
              {saiu ? <> · <b className="verm">− {moeda(saiu)}</b> em cancelamentos e descontos</> : null}</span>
          </Link>
        )}

        {listaLojas.length ? (
          <section className="cartao">
            <div className="linha-entre"><strong className="t14">Lojas</strong><span className="sub">parte da venda</span></div>
            {[...listaLojas].sort((a, b) => b.vendido_centavos - a.vendido_centavos).map((l, i) => {
              const p = rede ? Math.round(100 * l.vendido_centavos / rede) : 0;
              return (
                <button type="button" key={l.nome} className="loja-linha" onClick={() => ir(`/vivo?loja=${encodeURIComponent(l.nome)}`)}>
                  <span className="linha-entre"><span><b>{i + 1}º {l.nome}</b> <small className="sub">· {l.coletando}/{l.n_caixas} caixas</small></span><b>{moeda(l.vendido_centavos)}</b></span>
                  <span className="barra"><i style={{ width: `${Math.max(2, p)}%` }} /></span>
                </button>
              );
            })}
          </section>
        ) : null}

        <div className="linha-entre"><strong className="t14">Para conferir</strong><Link to="/conferir" className="link-azul">Ver tudo</Link></div>
        <div className="grade2">
          <Link to="/conferir?t=cancelados" className="cartao mini"><Ico cor="verm">{Icone.x}</Ico><span className="col"><b className="t17">{num((ev.CIT || 0))}</b><small className="sub">itens cancelados</small></span></Link>
          <Link to="/conferir?t=descontos" className="cartao mini"><Ico cor="ambar">{Icone.pct}</Ico><span className="col"><b className="t17">{moeda((c?.desc_item || 0) + (c?.desc_subtotal || 0)).replace(/,\d\d$/, '')}</b><small className="sub">em descontos</small></span></Link>
          <Link to="/conferir?t=sangrias" className="cartao mini"><Ico cor="azul">{Icone.dinheiro}</Ico><span className="col"><b className="t17">{num(ev.SGR || 0)}</b><small className="sub">sangrias</small></span></Link>
          <Link to="/conferir?t=gaveta" className="cartao mini"><Ico cor="ciano">{Icone.gaveta}</Ico><span className="col"><b className="t17">{num(ev.GAV || 0)}</b><small className="sub">gaveta aberta</small></span></Link>
        </div>
      </div>
      {folhaLoja ? <EscolherLoja aoFechar={() => setFolhaLoja(false)} /> : null}
    </>
  );
}
