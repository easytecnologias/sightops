import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { moeda, useFiltro, useLojas } from '../lib/pdv';
import { Ico, Icone } from '../ui/pecas';
import { VERSAO } from './Entrada';

function Atalho({ to, ic, cor, titulo, sub }: { to: string; ic: ReactNode; cor: 'azul' | 'verde' | 'verm' | 'ambar' | 'ciano'; titulo: string; sub: string }) {
  return (
    <Link to={to} className="linha">
      <Ico cor={cor}>{ic}</Ico>
      <span className="col cresce"><b>{titulo}</b><small className="sub um">{sub}</small></span>
      {Icone.dir}
    </Link>
  );
}

/** Mais: a busca do cupom e o resto do app. */
export function Mais({ aoSair }: { aoSair: () => void }) {
  const { dia } = useFiltro();
  const lojas = useLojas(dia);
  const ir = useNavigate();
  const [numero, setNumero] = useState('');
  const l = lojas.data?.lojas || [];
  const semDados = l.flatMap((x) => x.caixas).filter((c) => c.estado === 'sem_coletor');

  function buscar(ev: FormEvent) {
    ev.preventDefault();
    const n = numero.trim();
    if (n) ir(`/busca/${encodeURIComponent(n)}`);
  }

  return (
    <>
      <section className="topo-azul baixo">
        <div className="linha-entre">
          <div className="col"><span className="claro">SightOps PDV</span><h1>Mais</h1></div>
          <button type="button" className="bt-vidro" onClick={aoSair}>{Icone.sair}Sair</button>
        </div>
        <form className="busca" role="search" onSubmit={buscar}>
          <label>{Icone.busca}<input type="search" inputMode="numeric" placeholder="Nº do cupom" aria-label="Número do cupom"
            value={numero} onChange={(e) => setNumero(e.target.value)} /></label>
          <button type="submit">Abrir</button>
        </form>
      </section>
      <div className="pagina">
        <section className="cartao lista">
          <Atalho to="/conta" ic={Icone.conta} cor="verde" titulo="Conta do dia" sub="do valor passado no caixa ao vendido" />
          <Atalho to="/conferir" ic={Icone.conferir} cor="ambar" titulo="Cancelamentos, descontos e sangrias" sub="um a um, com o vídeo" />
          <Atalho to="/vivo" ic={Icone.monitor} cor={semDados.length ? 'verm' : 'azul'} titulo="Caixas e coleta"
            sub={semDados.length ? `${semDados.map((c) => c.nome).slice(0, 3).join(', ')} sem dados` : 'todos os caixas mandando dados'} />
          <Atalho to="/rankings" ic={Icone.trofeu} cor="azul" titulo="Rankings" sub="operadores e caixas em cada indicador" />
        </section>
        {l.length > 1 ? (
          <section className="cartao lista">
            <span className="rotulo">Comparar lojas · hoje</span>
            {[...l].sort((a, b) => b.vendido_centavos - a.vendido_centavos).map((x) => (
              <Link key={x.nome} to={`/vivo?loja=${encodeURIComponent(x.nome)}`} className="linha">
                <Ico cor="azul">{Icone.loja}</Ico>
                <span className="col cresce"><b className="um">{x.nome}</b><small className="sub">{x.coletando} de {x.n_caixas} caixas · {x.cupons} cupons</small></span>
                <b className="num">{moeda(x.vendido_centavos)}</b>
              </Link>
            ))}
          </section>
        ) : null}
        <p className="nota">Em breve: marcar procede / não procede, resumo da semana em PDF e aviso no celular.</p>
        <p className="nota">versão {VERSAO}</p>
      </div>
    </>
  );
}
