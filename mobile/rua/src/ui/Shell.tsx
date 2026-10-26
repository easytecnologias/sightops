import { useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Folha, Icone, iniciais } from './pecas';
import { useOnline } from '../lib/rede';
import { mesmoSite, siteDoConector, useConectores, useEu, useIncidentes } from '../lib/dados';
import { useSite } from '../lib/site';
import { ListaSites } from '../telas/Entrada';

const ABAS = [
  { para: '/', rot: 'Início', icone: Icone.casa },
  { para: '/cameras', rot: 'Câmeras', icone: Icone.camera },
  { para: '/implantar', rot: 'Implantar', icone: Icone.implantar },
  { para: '/alertas', rot: 'Alertas', icone: Icone.alerta, sino: true },
  { para: '/rede', rot: 'Rede', icone: Icone.rede },
];

export function Shell({ children }: { children: ReactNode }) {
  const online = useOnline();
  const { site, escolher } = useSite();
  const cons = useConectores();
  const eu = useEu();
  const panico = useIncidentes('live');
  const [folha, setFolha] = useState(false);
  const ir = useNavigate();

  const nome = eu.data?.full_name || eu.data?.username || '';
  // Conector do site escolhido: e por ele que todo comando chega ao equipamento.
  const conDoSite = (cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site));
  const conOn = conDoSite.some((c) => c.online);
  const abertos = (panico.data ?? []).filter((p) => p.status !== 'closed' && (!site || !p.site || mesmoSite(p.site, site))).length;
  const lado = !online ? 'Sem sinal' : !conDoSite.length ? 'sem conector' : conOn ? 'Conector online' : 'Conector fora';

  return (
    <div className="app">
      <header className="cabecalho">
        <div className="cab-l1">
          <span className="marca"><span className={`viva${online ? '' : ' off'}`} />SightOps</span>
          <button type="button" className="conta" aria-label="Conta e aparelho" onClick={() => ir('/conta')}>{iniciais(nome)}</button>
        </div>
        <button type="button" className="seletor" onClick={() => setFolha(true)}>
          <span>
            <span className="rot">Onde você está</span>
            <span className="val">{site ?? 'Escolher site'}</span>
          </span>
          <span className="lado"><span className={`ponto${online && conOn ? '' : ' off'}`} />{lado}{Icone.baixo}</span>
        </button>
      </header>

      <main className="conteudo">{children}</main>

      <nav className="barra-baixo" aria-label="Navegação principal">
        {ABAS.map((a) => (
          <NavLink key={a.para} to={a.para} end={a.para === '/'} className={({ isActive }) => (isActive ? 'ativo' : '')}>
            {a.sino && abertos > 0 ? <span className="sino" /> : null}
            {a.icone}
            {a.rot}
          </NavLink>
        ))}
      </nav>

      {folha ? (
        <Folha titulo="Onde você está" sub="O site guia o resto do app e fica guardado no aparelho." aoFechar={() => setFolha(false)}>
          <div className="folha-lista">
            <ListaSites atual={site} aoEscolher={(s) => { escolher(s); setFolha(false); ir('/'); }} />
          </div>
        </Folha>
      ) : null}
    </div>
  );
}
