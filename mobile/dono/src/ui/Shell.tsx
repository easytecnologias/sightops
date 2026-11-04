import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import { Icone } from './pecas';
import { useOnline } from '../lib/rede';

/** Barra de baixo com as 5 abas e o aviso de sem sinal. */
export function Shell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const cls = ({ isActive }: { isActive: boolean }) => (isActive ? 'ativo' : '');
  return (
    <div className="app">
      {!online ? <div className="sem-sinal">Sem sinal: mostrando o que já foi carregado.</div> : null}
      <main className="conteudo">{children}</main>
      <nav className="barra-baixo" aria-label="Menu">
        <NavLink to="/" end className={cls}>{Icone.casa}Início</NavLink>
        <NavLink to="/vivo" className={cls}>{Icone.video}Ao vivo</NavLink>
        <NavLink to="/conferir" className={cls}>{Icone.conferir}Conferir</NavLink>
        <NavLink to="/rankings" className={cls}>{Icone.trofeu}Rankings</NavLink>
        <NavLink to="/avisos" className={cls}>{Icone.sino}Avisos</NavLink>
      </nav>
    </div>
  );
}
