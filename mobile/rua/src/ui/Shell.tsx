import { useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Icone, Item, Vazio } from './pecas';
import { useOnline } from '../lib/rede';
import { siteDoConector, useAlertas, useConectores } from '../lib/dados';
import { useSite } from '../lib/site';

const ABAS = [
  { para: '/', rot: 'Inicio', icone: Icone.casa },
  { para: '/cameras', rot: 'Cameras', icone: Icone.camera },
  { para: '/implantar', rot: 'Implantar', icone: Icone.implantar },
  { para: '/alertas', rot: 'Alertas', icone: Icone.alerta, sino: true },
  { para: '/rede', rot: 'Rede', icone: Icone.rede },
];

export function Shell(
  { children, operador, onSair }:
  { children: ReactNode; operador: string; onSair: () => void },
) {
  const online = useOnline();
  const { site, escolher } = useSite();
  const cons = useConectores();
  const alertas = useAlertas();
  const [folha, setFolha] = useState(false);
  const ir = useNavigate();

  const iniciais = (operador || '?').trim().slice(0, 2).toUpperCase();
  // Nunca o campo `duress`: coacao jamais aparece numa tela do aplicativo.
  const abertos = alertas.data?.open ?? 0;

  const sites = [...new Set((cons.data ?? []).map(siteDoConector).filter(Boolean))].sort();

  return (
    <div className="app">
      <header className="cabecalho">
        <div className="cab-l1">
          <span className="marca">
            <span className={`viva${online ? '' : ' off'}`} />
            SightOps
          </span>
          <button type="button" className="conta" aria-label="Conta do operador"
                  onClick={onSair} title="Sair">
            {iniciais}
          </button>
        </div>

        <button type="button" className="seletor" onClick={() => setFolha(true)}>
          <span>
            <span className="rot">Onde voce esta</span>
            <span className="val">{site ?? 'Escolher site'}</span>
          </span>
          <span className="lado">
            <span className={`ponto${online ? '' : ' off'}`} />
            {online ? 'Conector online' : 'Sem sinal'}
            {Icone.baixo}
          </span>
        </button>
      </header>

      <main className="conteudo">{children}</main>

      <nav className="barra-baixo" aria-label="Navegacao principal">
        {ABAS.map((a) => (
          <NavLink key={a.para} to={a.para} end={a.para === '/'}
                   className={({ isActive }) => (isActive ? 'ativo' : '')}>
            {a.sino && abertos > 0 ? <span className="sino" /> : null}
            {a.icone}
            {a.rot}
          </NavLink>
        ))}
      </nav>

      {folha && (
        <>
          <div className="folha-fundo" onClick={() => setFolha(false)} />
          <aside className="folha" aria-label="Escolher site">
            <div className="folha-topo">
              <h2>Onde voce esta</h2>
              <p>O site guia o resto do aplicativo e fica guardado no aparelho.</p>
            </div>
            <div className="folha-lista">
              {sites.length === 0 ? (
                <Vazio>Nenhum conector com site.<br />Conecte uma vez para baixar a lista.</Vazio>
              ) : sites.map((s) => (
                <Item key={s} icone={Icone.pin} titulo={s}
                      direita={s === site ? <span className="selo verde">atual</span> : Icone.seta}
                      onClick={() => { escolher(s); setFolha(false); ir('/'); }} />
              ))}
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
