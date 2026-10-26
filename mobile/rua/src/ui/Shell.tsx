import { useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { Folha, Icone, iniciais } from './pecas';
import { AreaPuxar } from './Puxar';
import { useOnline } from '../lib/rede';
import { mesmoSite, siteDoConector, useConectores, useEu, useIncidentes } from '../lib/dados';
import { useSiteMonitor } from '../lib/monitor';
import { useSite } from '../lib/site';
import { ListaSites } from '../telas/Entrada';
import { MenuImplantar } from '../telas/Implantar';

/* Barra de baixo: Inicio, Mapa, (+) Implantar, Equipamentos, Alertas.
   O mapa e aba fixa; o (+) abre o menu de implantar em folha. */
const ABAS_ESQ = [
  { para: '/', rot: 'Início', icone: Icone.casa },
  { para: '/mapa', rot: 'Mapa', icone: Icone.mapa },
];
const ABAS_DIR = [
  { para: '/equipamentos', rot: 'Equipamentos', icone: Icone.equipamentos, tambem: ['/cameras', '/onu', '/rede', '/switch', '/pon'] },
  { para: '/alertas', rot: 'Alertas', icone: Icone.alerta, sino: true },
];

export function Shell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const { site, escolher } = useSite();
  const cons = useConectores();
  const eu = useEu();
  const panico = useIncidentes('live');
  const m = useSiteMonitor(site);
  const [folha, setFolha] = useState(false);
  const [menu, setMenu] = useState(false);
  const ir = useNavigate();
  const { pathname } = useLocation();

  const nome = eu.data?.full_name || eu.data?.username || '';
  const conDoSite = (cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site));
  const conOn = conDoSite.some((c) => c.online);
  const abertos = (panico.data ?? []).filter((p) => p.status !== 'closed' && (!site || !p.site || mesmoSite(p.site, site))).length
    + m.atencao.length;
  const lado = !online ? 'Sem sinal' : !conDoSite.length ? 'sem conector' : conOn ? 'Conector online' : 'Conector fora';
  // No mapa o cabecalho encolhe: o mapa precisa da tela.
  const noMapa = pathname === '/mapa';

  const aba = (a: { para: string; rot: string; icone: ReactNode; sino?: boolean; tambem?: string[] }) => (
    <NavLink key={a.para} to={a.para} end={a.para === '/'}
             className={({ isActive }) => (isActive || a.tambem?.some((p) => pathname.startsWith(p)) ? 'ativo' : '')}>
      {a.sino && abertos > 0 ? <span className="sino-num">{abertos > 99 ? '99+' : abertos}</span> : null}
      {a.icone}
      {a.rot}
    </NavLink>
  );

  return (
    <div className="app">
      <header className={`cabecalho${noMapa ? ' fino' : ''}`}>
        <div className="cab-l1">
          <span className="marca"><span className={`viva${online ? '' : ' off'}`} />SightOps</span>
          {noMapa ? (
            <button type="button" className="seletor-curto" onClick={() => setFolha(true)}>
              <span className={`ponto${online && conOn ? '' : ' off'}`} />{site ?? 'Escolher site'}{Icone.baixo}
            </button>
          ) : null}
          <button type="button" className="conta" aria-label="Conta e aparelho" onClick={() => ir('/conta')}>{iniciais(nome)}</button>
        </div>
        {!noMapa ? (
          <button type="button" className="seletor" onClick={() => setFolha(true)}>
            <span>
              <span className="rot">Site</span>
              <span className="val">{site ?? 'Escolher site'}</span>
            </span>
            <span className="lado"><span className={`ponto${online && conOn ? '' : ' off'}`} />{lado}{Icone.baixo}</span>
          </button>
        ) : null}
      </header>

      <AreaPuxar desligado={noMapa}>{children}</AreaPuxar>

      <nav className="barra-baixo" aria-label="Navegação principal">
        {ABAS_ESQ.map(aba)}
        <button type="button" className="botao-mais" aria-label="Implantar" onClick={() => setMenu(true)}>
          <span>{Icone.mais}</span>
        </button>
        {ABAS_DIR.map(aba)}
      </nav>

      {folha ? (
        <Folha titulo="Site" sub="O site guia o resto do app e fica guardado no aparelho." aoFechar={() => setFolha(false)}>
          <div className="folha-lista">
            <ListaSites atual={site} aoEscolher={(s) => { escolher(s); setFolha(false); ir('/'); }} />
          </div>
        </Folha>
      ) : null}

      {menu ? (
        <Folha titulo="O que você vai fazer?" aoFechar={() => setMenu(false)}>
          <MenuImplantar aoEscolher={() => setMenu(false)} />
        </Folha>
      ) : null}
    </div>
  );
}
