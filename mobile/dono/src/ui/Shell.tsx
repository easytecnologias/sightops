import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { Icone } from './pecas';
import { useOnline } from '../lib/rede';
import { grave, hoje, useFiltro, useMomentos } from '../lib/pdv';

/** Barra de baixo com as 5 abas, o numero do que ha para olhar hoje e o aviso de sem sinal. */
export function Shell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const { loja } = useFiltro();
  const mom = useMomentos(hoje(), loja);
  const pendentes = (mom.data?.momentos || []).filter(grave).length;
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? 'ativo' : '');
  return (
    <div className="app">
      <main className="conteudo">{children}</main>
      {!online ? <div className="sem-sinal">Sem sinal: mostrando o que já foi carregado.</div> : null}
      <nav className="barra-baixo" aria-label="Menu">
        <NavLink to="/" end className={cls}>{Icone.casa}Hoje</NavLink>
        <NavLink to="/olhar" className={cls}><span className="com-bolinha">{Icone.olho}{pendentes ? <b className="bolinha">{pendentes > 99 ? '99+' : pendentes}</b> : null}</span>Para olhar</NavLink>
        <NavLink to="/vivo" className={cls}>{Icone.video}Ao vivo</NavLink>
        <NavLink to="/equipe" className={cls}>{Icone.equipe}Equipe</NavLink>
        <NavLink to="/mais" className={cls}>{Icone.mais}Mais</NavLink>
      </nav>
    </div>
  );
}
