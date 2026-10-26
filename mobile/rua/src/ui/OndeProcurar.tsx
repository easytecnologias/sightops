import { useState } from 'react';
import { siteDoConector, useConectores, type Conector } from '../lib/dados';
import { useSite } from '../lib/site';
import { Cartao, Folha, Icone, Item, Vazio } from './pecas';

/**
 * "Onde procurar": o site e o conector (MikroTik) por onde a busca sai.
 *
 * A ativacao e o Instalar usavam o site do topo da tela sem dizer -- e o
 * tecnico nao tinha como escolher ali, como faz na web. Agora o site fica a
 * vista e troca aqui mesmo (troca tambem o site do app inteiro).
 */
export function OndeProcurar(
  { conector, aoTrocarConector, so = 'routeros' }:
  { conector?: Conector; aoTrocarConector: (id: string) => void; so?: 'routeros' | 'todos' },
) {
  const { site, escolher } = useSite();
  const cons = useConectores();
  const [aberto, setAberto] = useState(false);

  const validos = (cons.data ?? []).filter((c) => so === 'todos' || String(c.type ?? '').toLowerCase() === 'routeros');
  const porSite = new Map<string, Conector[]>();
  for (const c of validos) {
    const s = siteDoConector(c);
    if (!s) continue;
    porSite.set(s, [...(porSite.get(s) ?? []), c]);
  }
  const sites = [...porSite.keys()].sort((a, b) => a.localeCompare(b, 'pt-BR'));

  return (
    <>
      <Cartao>
        <button type="button" className="item onde-procurar" onClick={() => setAberto(true)}>
          <span className="ic">{Icone.predio}</span>
          <span className="corpo">
            <span className="s">Onde procurar</span>
            <span className="t">{site || 'Escolher o site'}</span>
            <span className="s">{conector ? `${conector.name || conector.id} · ${conector.online ? 'online' : 'fora do ar'}` : 'sem conector MikroTik neste site'}</span>
          </span>
          <span className="link">Trocar</span>
        </button>
      </Cartao>

      {aberto ? (
        <Folha titulo="Onde procurar" sub="A busca sai pelo MikroTik do site escolhido." aoFechar={() => setAberto(false)}>
          <div className="folha-lista">
            {!sites.length ? <Vazio>Nenhum site com conector MikroTik.</Vazio> : sites.map((s) => (
              porSite.get(s)!.map((c) => (
                <Item key={`${s}-${c.id}`} ponto={c.online ? 'verde' : 'ambar'} icone={Icone.predio}
                      titulo={porSite.get(s)!.length > 1 ? `${s} · ${c.name}` : s}
                      sub={`${c.name || c.id} · ${c.online ? 'online' : 'fora do ar'}`}
                      onClick={() => { escolher(s); aoTrocarConector(c.id ?? ''); setAberto(false); }}
                      direita={conector?.id === c.id ? <span className="selo verde">atual</span> : Icone.seta} />
              ))
            ))}
          </div>
        </Folha>
      ) : null}
    </>
  );
}
