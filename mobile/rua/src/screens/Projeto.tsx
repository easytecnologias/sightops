import { useMemo, useState } from 'react';
import { estadoDa, siteDa, tituloDa, useCameras, type Camera, type Estado } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from './Site';
import { Badge, Carregando, Icone, Linha, PageHeading, Panel, PanelHeader, Procedencia, Vazio } from '../ui/pecas';

type Filtro = 'todas' | 'offline' | 'sem';

export function Projeto() {
  const online = useOnline();
  const { site, pronto } = useSite();
  const q = useCameras();
  const [filtro, setFiltro] = useState<Filtro>('todas');
  const [busca, setBusca] = useState('');

  const doSite = useMemo(() => {
    const todas = q.data ?? [];
    if (!site) return todas;
    return todas.filter((c) => siteDa(c).toLowerCase() === site.toLowerCase());
  }, [q.data, site]);

  const contagem = useMemo(() => ({
    todas: doSite.length,
    offline: doSite.filter((c) => estadoDa(c) === 'offline').length,
    sem: doSite.filter((c) => estadoDa(c) === 'sem').length,
  }), [doSite]);

  const lista = useMemo(() => {
    let l = doSite;
    if (filtro !== 'todas') l = l.filter((c) => estadoDa(c) === (filtro as Estado));
    const termo = busca.trim().toLowerCase();
    if (termo) {
      l = l.filter((c) => [c.titulo, c.title, c.ip, c.mac, c.modelo, c.recorder_channel]
        .some((v) => String(v ?? '').toLowerCase().includes(termo)));
    }
    return l;
  }, [doSite, filtro, busca]);

  // Agrupar por gravador: e como o tecnico pensa o site. Camera sem gravador
  // vai para um grupo proprio em vez de sumir no meio das outras.
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
      <PageHeading eyebrow="Consulta" titulo="Projeto do site"
                   sub={`${site ?? 'Todos os sites'} · ${doSite.length} cameras`} />

      <div className="barra-acao">
        <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
      </div>

      <div className="busca">
        {Icone.busca}
        <label htmlFor="q" className="so-leitor">Procurar</label>
        <input id="q" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder="Titulo, IP, MAC ou canal" autoCapitalize="none" spellCheck={false} />
      </div>

      <div className="abas">
        {([['todas', `Todas ${contagem.todas}`],
           ['offline', `Fora do ar ${contagem.offline}`],
           ['sem', `Sem leitura ${contagem.sem}`]] as const).map(([v, rot]) => (
          <button key={v} type="button" className="aba"
                  aria-pressed={filtro === v} onClick={() => setFiltro(v)}>
            {rot}
          </button>
        ))}
      </div>

      {grupos.length === 0 ? (
        <Panel><Vazio>Nada com esse filtro.</Vazio></Panel>
      ) : grupos.map(([host, cams]) => (
        <Panel key={host}>
          <PanelHeader
            titulo={host === '\u0000sem' ? 'Sem gravador' : host}
            sub={`${cams.length} camera${cams.length === 1 ? '' : 's'}`} />
          {cams.map((c, i) => {
            const e = estadoDa(c);
            return (
              <Linha key={`${c.ip}-${i}`} icone={Icone.camera}
                     titulo={tituloDa(c)}
                     sub={[c.ip, c.modelo].filter(Boolean).join(' · ')}
                     direita={
                       <Badge cor={e === 'online' ? 'green' : e === 'offline' ? 'red' : 'amber'}>
                         {c.recorder_channel ? `CH ${c.recorder_channel}`
                           : e === 'online' ? 'ok' : e === 'offline' ? 'fora' : '?'}
                       </Badge>
                     } />
            );
          })}
        </Panel>
      ))}
    </>
  );
}
