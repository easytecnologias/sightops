import { MARCA } from '../lib/marca';
import { Logo } from '../ui/pecas';

export function Conta({ aoSair }: { aoSair: () => void }) {
  return (
    <>
      <header className="topo baixo"><span className="topo-anel" aria-hidden="true" /><small>{MARCA.empresa}</small><h1>Conta</h1></header>
      <div className="pagina">
        <section className="cartao status"><Logo /><div className="cresce"><b>{MARCA.nome}</b><small>versão {MARCA.versao} · tecnologia SightOps</small></div></section>
        <button type="button" className="btn2" onClick={aoSair}>Sair</button>
      </div>
    </>
  );
}
