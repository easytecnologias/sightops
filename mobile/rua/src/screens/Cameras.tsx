import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { chaveDa, estadoDa, siteDa, tituloDa, useCameras, type Camera, type Estado } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Carregando, Cartao, Icone, Item, Procedencia, Titulo, Vazio } from '../ui/pecas';

type Filtro = 'todas' | 'offline' | 'sem';

export function Cameras() {
  const online = useOnline();
  const { site, pronto } = useSite();
  const q = useCameras();
  const [filtro, setFiltro] = useState<Filtro>('todas');
  const [busca, setBusca] = useState('');
  const ir = useNavigate();

  const doSite = useMemo(() => {
    const todas = q.data ?? [];
    if (!site) return todas;
    return todas.filter((c) => siteDa(c).toLowerCase() === site.toLowerCase());
  }, [q.data, site]);

  const conta = useMemo(() => ({
    todas: doSite.length,
    offline: doSite.filter((c) => estadoDa(c) === 'offline').length,
    sem: doSite.filter((c) => estadoDa(c) === 'sem').length,
  }), [doSite]);

  const lista = useMemo(() => {
    let l = doSite;
    if (filtro !== 'todas') l = l.filter((c) => estadoDa(c) === (filtro as Estado));
    const t = busca.trim().toLowerCase();
    if (t) {
      l = l.filter((c) => [c.titulo, c.title, c.ip, c.mac, c.modelo, c.recorder_channel]
        .some((v) => String(v ?? '').toLowerCase().includes(t)));
    }
    return l;
  }, [doSite, filtro, busca]);

  // Agrupar por gravador: e como o tecnico pensa o site. Camera sem gravador
  // ganha grupo proprio em vez de sumir no meio das outras.
  const grupos = useMemo(() => {
    const m = new Map<string, Camera[]>();
    for (const c of lista) {
      const g = String(c.recorder_host ?? '').trim() || '\u0000sem';
      if (!m.has(g)) m.set(g, []);
      m.get(g)!.push(c);
    }
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [lista]);

  if (!pronto || (q.isPending && !q.data)) return <Carregando />;

  return (
    <>
      <div className="linha-topo">
        <Titulo titulo="Cameras" sub={`${site ?? 'Todos os sites'} · ${doSite.length} no projeto`} />
        <span style={{ marginLeft: 'auto' }}>
          <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
        </span>
      </div>

      <div className="busca">
        {Icone.busca}
        <label htmlFor="q" className="so-leitor">Procurar</label>
        <input id="q" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder="Titulo, IP, MAC ou canal" autoCapitalize="none" spellCheck={false} />
      </div>

      <div className="abas">
        {([['todas', `Todas ${conta.todas}`],
           ['offline', `Fora do ar ${conta.offline}`],
           ['sem', `Sem leitura ${conta.sem}`]] as const).map(([v, rot]) => (
          <button key={v} type="button" className="aba"
                  aria-pressed={filtro === v} onClick={() => setFiltro(v)}>{rot}</button>
        ))}
      </div>

      {grupos.length === 0 ? (
        <Cartao><Vazio>Nada com esse filtro.</Vazio></Cartao>
      ) : grupos.map(([host, cams]) => (
        <Cartao key={host}>
          <h2>{host === '\u0000sem' ? 'Sem gravador' : host}</h2>
          <p className="sub-h2">{cams.length} camera{cams.length === 1 ? '' : 's'}</p>
          {cams.map((c, i) => {
            const e = estadoDa(c);
            return (
              <Item key={`${c.ip}-${i}`}
                    ponto={e === 'online' ? 'verde' : e === 'offline' ? 'vermelho' : 'ambar'}
                    titulo={tituloDa(c)}
                    sub={[c.ip, c.modelo].filter(Boolean).join(' · ')}
                    onClick={() => ir(`/cameras/${chaveDa(c)}`)}
                    direita={
                      <span className={`selo ${e === 'online' ? 'verde' : e === 'offline' ? 'ambar' : 'cinza'}`}>
                        {c.recorder_channel ? `CH ${c.recorder_channel}` : e === 'online' ? 'ok' : e === 'offline' ? 'fora' : '?'}
                      </span>
                    } />
            );
          })}
        </Cartao>
      ))}
    </>
  );
}
