import { useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Icone } from './pecas';
import { useOnline } from '../lib/rede';

const ABAS = [
  { para: '/', rot: 'Dashboard', icone: Icone.grid },
  { para: '/site', rot: 'Site', icone: Icone.pin },
  { para: '/projeto', rot: 'Projeto', icone: Icone.pasta },
];

/* A gaveta e a barra lateral do SightOps: no celular ela abre pelo
   hamburguer, como o proprio app web faz em tela estreita. As acoes que
   mandam ordem a equipamento ficam marcadas -- nao escondidas. */
const MENU: ({ sec: string } | { para: string; rot: string; icone: ReactNode; sinal?: boolean })[] = [
  { sec: 'Consulta' },
  { para: '/', rot: 'Dashboard', icone: Icone.grid },
  { para: '/site', rot: 'Site', icone: Icone.pin },
  { para: '/projeto', rot: 'Projeto do site', icone: Icone.pasta },
  { sec: 'Implantacao' },
  { para: '/onu', rot: 'Ativar ONU', icone: Icone.onu, sinal: true },
  { para: '/ativar', rot: 'Ativar camera', icone: Icone.raio, sinal: true },
  { para: '/instalar', rot: 'Instalar camera', icone: Icone.camera, sinal: true },
  { sec: 'Ajustar' },
  { para: '/gravador', rot: 'Gravador', icone: Icone.gravador, sinal: true },
  { para: '/camera', rot: 'Camera', icone: Icone.engrenagem, sinal: true },
];

const TITULOS: Record<string, string> = {
  '/': 'Dashboard', '/site': 'Site', '/projeto': 'Projeto',
  '/onu': 'Ativar ONU', '/ativar': 'Ativar camera', '/instalar': 'Instalar camera',
  '/gravador': 'Gravador', '/camera': 'Camera',
};

export function Shell(
  { children, cliente, onSair }:
  { children: ReactNode; cliente: string; onSair: () => void },
) {
  const [gaveta, setGaveta] = useState(false);
  const online = useOnline();
  const local = useLocation();
  const ir = useNavigate();

  return (
    <div className="app">
      <header className="topbar">
        <button type="button" className="icon-button" aria-label="Abrir menu"
                onClick={() => setGaveta(true)}>
          {Icone.menu}
        </button>
        <span className="tb-titulo">{TITULOS[local.pathname] ?? 'SightOps'}</span>
        <span className={`chip ${online ? 'ok' : 'off'}`}>
          <i className={`ponto ${online ? 'ok' : 'off'}`} />
          {online ? 'Online' : 'Sem sinal'}
        </span>
      </header>

      <main className="scroll">{children}</main>

      <nav className="bottom" aria-label="Principal">
        {ABAS.map((a) => (
          <NavLink key={a.para} to={a.para} end={a.para === '/'}
                   className={({ isActive }) => (isActive ? 'ativo' : '')}>
            <span className="pill">{a.icone}</span>
            {a.rot}
          </NavLink>
        ))}
        <button type="button" onClick={() => setGaveta(true)}>
          <span className="pill">{Icone.menu}</span>
          Menu
        </button>
      </nav>

      {gaveta && (
        <>
          <div className="gaveta-fundo" onClick={() => setGaveta(false)} />
          <aside className="gaveta" aria-label="Menu">
            <div className="gaveta-topo">
              <span className="brand-mark">S</span>
              <div>
                <strong>SightOps</strong>
                <span>{cliente || 'Rua'}</span>
              </div>
            </div>
            <nav className="gaveta-nav">
              {MENU.map((it, i) =>
                'sec' in it ? (
                  <div key={`s${i}`} className="gaveta-sec">{it.sec}</div>
                ) : (
                  <button key={it.para} type="button" className="gaveta-item"
                          aria-current={local.pathname === it.para ? 'page' : undefined}
                          onClick={() => { setGaveta(false); ir(it.para); }}>
                    {it.icone}
                    <span>{it.rot}</span>
                    {it.sinal ? <span className="tag">exige sinal</span> : null}
                  </button>
                ),
              )}
            </nav>
            <div className="gaveta-pe">
              <div className="amb">
                <i className={`ponto ${online ? 'ok' : 'off'}`} />
                <span>Producao{cliente ? ` · ${cliente}` : ''}</span>
              </div>
              <button type="button" className="acao" onClick={onSair}>Sair</button>
            </div>
          </aside>
        </>
      )}
    </div>
  );
}
