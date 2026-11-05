import { useMemo, useState } from 'react';
import { Icone } from './pecas';
import { natural, useAlertas, useCameras, useSite } from '../lib/termico';

/** Escolher usina: busca, todas e a lista em ordem natural com os novos de cada. */
export function SeletorUsina({ aoFechar }: { aoFechar: () => void }) {
  const { site, escolher } = useSite();
  const [q, setQ] = useState('');
  const cams = useCameras();
  const al = useAlertas();

  const usinas = useMemo(() => {
    const m = new Map<string, { nome: string; cams: number; novos: number }>();
    for (const c of cams.data?.cameras || []) {
      const u = m.get(c.site) || { nome: c.site, cams: 0, novos: 0 };
      u.cams += 1; u.novos += c.pendentes;
      m.set(c.site, u);
    }
    return [...m.values()].sort((a, b) => natural(a.nome, b.nome));
  }, [cams.data]);
  const lista = usinas.filter((u) => u.nome.toLowerCase().includes(q.trim().toLowerCase()));
  const pick = (s: string) => { escolher(s); aoFechar(); };

  return (
    <div className="fundo-folha">
      <section className="folha" role="dialog" aria-label="Escolher usina">
        <span className="alca" />
        <div className="linha"><h2>Escolher usina</h2>
          <button type="button" className="bt-redondo" aria-label="Fechar" onClick={aoFechar}>{Icone.fechar}</button></div>
        <label className="busca"><span className="oculto">Buscar usina</span>
          <input type="search" placeholder="Buscar usina" value={q} onChange={(e) => setQ(e.target.value)} /></label>
        <button type="button" className={`item-usina ${site === '' ? 'on' : ''}`} onClick={() => pick('')}>
          <span className="ic-usina">{Icone.casa}</span><span className="cresce"><b>Todas as usinas</b></span>
          {al.data?.por_situacao?.novo ? <span className="etq alerta">{al.data.por_situacao.novo} novos</span> : null}
        </button>
        <div className="rolavel">
          {lista.map((u) => (
            <button key={u.nome} type="button" className={`item-usina ${site === u.nome ? 'on' : ''}`} onClick={() => pick(u.nome)}>
              <span className="ic-usina">{Icone.sol}</span>
              <span className="cresce"><b>{u.nome}</b><small>{u.cams} câmera{u.cams === 1 ? '' : 's'}</small></span>
              {u.novos ? <span className="etq alerta">{u.novos} novo{u.novos === 1 ? '' : 's'}</span> : null}
            </button>
          ))}
          {!lista.length ? <div className="vazio">Nenhuma usina encontrada.</div> : null}
        </div>
      </section>
    </div>
  );
}
