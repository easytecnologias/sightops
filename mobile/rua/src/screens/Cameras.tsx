import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { chaveDa, detalhe, estadoDa, siteDa, tituloDa, useCameras, useEntidades, type Camera, type Estado } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { useFiltroSite } from '../lib/monitor';
import { Carregando, Cartao, Icone, Item, Procedencia, Titulo, Vazio } from '../ui/pecas';
import { ordemNatural } from '../lib/ordem';

type Filtro = 'todas' | 'offline' | 'sem';

export function Cameras() {
  const online = useOnline();
  const { site, pronto } = useSite();
  const q = useCameras();
  const [filtro, setFiltro] = useState<Filtro>('todas');
  const [param] = useSearchParams();
  const [busca, setBusca] = useState(param.get('q') ?? '');
  const ir = useNavigate();
  const doSiteFn = useFiltroSite(site);
  const nvrs = useEntidades('nvr');
  const [local, setLocal] = useState(param.get('local') ?? '');
  const [grav, setGrav] = useState(param.get('gravador') ?? '');

  // Nome e local de cada gravador (pelo host), do mesmo cadastro do monitoramento.
  const gravPorHost = useMemo(() => {
    const m = new Map<string, { nome: string; local: string }>();
    for (const e of nvrs.data ?? []) {
      const host = String(detalhe<{ host?: string }>(e).host ?? '');
      if (!host) continue;
      const nome = String(e.display_name ?? '');
      const ja = m.get(host);
      if (!ja || ja.nome === host) m.set(host, { nome: nome || host, local: String(e.site ?? '').trim().toUpperCase() });
    }
    return m;
  }, [nvrs.data]);
  const localDa = (c: Camera) => gravPorHost.get(String(c.recorder_host ?? ''))?.local || siteDa(c).toUpperCase() || 'SEM LOCAL';
  const nomeGrav = (host: string) => gravPorHost.get(host)?.nome || host;

  const doSite = useMemo(() => {
    const todas = q.data ?? [];
    if (!site) return todas;
    return todas.filter((c) => doSiteFn(siteDa(c), c.remote_connector_id || c.connector_id));
  }, [q.data, site, doSiteFn]);

  // Locais e gravadores que existem neste site, com quantas cameras cada um.
  const locais = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of doSite) m.set(localDa(c), (m.get(localDa(c)) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => ordemNatural(a[0], b[0]));
  }, [doSite, gravPorHost]); // eslint-disable-line react-hooks/exhaustive-deps
  const doLocal = useMemo(() => (local ? doSite.filter((c) => localDa(c) === local) : doSite),
    [doSite, local, gravPorHost]); // eslint-disable-line react-hooks/exhaustive-deps
  const gravadores = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of doLocal) { const h = String(c.recorder_host ?? '').trim(); m.set(h, (m.get(h) ?? 0) + 1); }
    return [...m.entries()].map(([h, n]) => ({ host: h, nome: h ? nomeGrav(h) : 'Sem gravador', n }))
      .sort((a, b) => (a.host ? 0 : 1) - (b.host ? 0 : 1) || ordemNatural(a.nome, b.nome));
  }, [doLocal, gravPorHost]); // eslint-disable-line react-hooks/exhaustive-deps
  const doGrav = useMemo(() => (grav ? doLocal.filter((c) => (String(c.recorder_host ?? '').trim() || '-') === grav) : doLocal), [doLocal, grav]);

  const conta = useMemo(() => ({
    todas: doGrav.length,
    offline: doGrav.filter((c) => estadoDa(c) === 'offline').length,
    sem: doGrav.filter((c) => estadoDa(c) === 'sem').length,
  }), [doGrav]);

  const lista = useMemo(() => {
    let l = doGrav;
    if (filtro !== 'todas') l = l.filter((c) => estadoDa(c) === (filtro as Estado));
    const t = busca.trim().toLowerCase();
    if (t) {
      l = l.filter((c) => [c.titulo, c.title, c.ip, c.mac, c.modelo, c.recorder_channel, c.recorder_host && nomeGrav(String(c.recorder_host))]
        .some((v) => String(v ?? '').toLowerCase().includes(t)));
    }
    return l;
  }, [doGrav, filtro, busca, gravPorHost]); // eslint-disable-line react-hooks/exhaustive-deps
  const comFiltro = !!(local || grav || filtro !== 'todas' || busca.trim());

  // Agrupar por gravador: e como o tecnico pensa o site. Camera sem gravador
  // ganha grupo proprio em vez de sumir no meio das outras.
  const grupos = useMemo(() => {
    const m = new Map<string, Camera[]>();
    for (const c of lista) {
      const g = String(c.recorder_host ?? '').trim() || '\u0000sem';
      if (!m.has(g)) m.set(g, []);
      m.get(g)!.push(c);
    }
    // Pelo nome do gravador (o tecnico procura "JARDINS II - 03", nao o IP); sem gravador por ultimo.
    return [...m.entries()].sort((a, b) => (a[0] === '\u0000sem' ? 1 : 0) - (b[0] === '\u0000sem' ? 1 : 0)
      || ordemNatural(nomeGrav(a[0]), nomeGrav(b[0])));
  }, [lista, gravPorHost]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!pronto || (q.isPending && !q.data)) return <Carregando />;

  return (
    <>
      <div className="linha-topo">
        <Titulo titulo="Câmeras" sub={`${site ?? 'Todos os sites'} · ${doSite.length} no projeto`} />
        <span style={{ marginLeft: 'auto' }}>
          <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
        </span>
      </div>

      <div className="busca">
        {Icone.busca}
        <label htmlFor="q" className="so-leitor">Procurar</label>
        <input id="q" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder="Título, IP, MAC ou canal" autoCapitalize="none" spellCheck={false} />
      </div>

      <div className="filtros-duplos">
        {locais.length > 1 ? (
          <div className="campo"><label htmlFor="f-local">Local</label>
            <select id="f-local" className="caixa-sel" value={local} onChange={(e) => { setLocal(e.target.value); setGrav(''); }}>
              <option value="">Todos os locais ({doSite.length})</option>
              {locais.map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
            </select></div>
        ) : null}
        <div className="campo"><label htmlFor="f-grav">Gravador</label>
          <select id="f-grav" className="caixa-sel" value={grav} onChange={(e) => setGrav(e.target.value)}>
            <option value="">Todos os gravadores ({doLocal.length})</option>
            {gravadores.map((g) => <option key={g.host || '-'} value={g.host || '-'}>{g.nome} ({g.n})</option>)}
          </select></div>
        {comFiltro ? (
          <button type="button" className="link limpar" onClick={() => { setLocal(''); setGrav(''); setFiltro('todas'); setBusca(''); }}>Limpar filtros</button>
        ) : null}
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
          <h2>{host === '\u0000sem' ? 'Sem gravador' : nomeGrav(host)}</h2>
          <p className="sub-h2">{[host !== '\u0000sem' && nomeGrav(host) !== host ? host : '', `${cams.length} câmera${cams.length === 1 ? '' : 's'}`].filter(Boolean).join(' · ')}</p>
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
