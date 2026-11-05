import type { ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { Icone } from './pecas';
import { useOnline } from '../lib/rede';

const ABAS = [
  { para: '/', nome: 'Início', icone: Icone.casa },
  { para: '/ronda', nome: 'Ao vivo', icone: Icone.video },
  { para: '/usinas', nome: 'Usinas', icone: Icone.sol },
  { para: '/conta', nome: 'Conta', icone: Icone.conta },
];

/** Barra flutuante: o item ativo e uma pilula na cor da marca, com o nome. */
export function Shell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const { pathname } = useLocation();
  const semBarra = pathname.startsWith('/alerta/');
  return (
    <div className="app">
      <main className="conteudo">{children}</main>
      {!online ? <div className="sem-sinal">Sem sinal: mostrando o que já foi carregado.</div> : null}
      {semBarra ? null : (
        <div className="barra-fundo">
          <nav className="barra" aria-label="Menu">
            {ABAS.map((a) => (
              <NavLink key={a.para} to={a.para} end={a.para === '/'} aria-label={a.nome}
                className={({ isActive }) => (isActive ? 'ativo' : '')}>
                {({ isActive }) => <>{a.icone}{isActive ? a.nome : null}</>}
              </NavLink>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}
