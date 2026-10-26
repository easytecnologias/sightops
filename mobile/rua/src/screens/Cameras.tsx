import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { chaveDa, detalhe, estadoDa, siteDa, tituloDa, useCameras, useEntidades, type Camera } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { useFiltroSite } from '../lib/monitor';
import { Carregando, Cartao, Item, Procedencia, Titulo, Vazio } from '../ui/pecas';
import { useFiltro, type Situacao } from '../ui/Filtros';
import { ordemNatural } from '../lib/ordem';

const SEM_GRAVADOR = 'Sem gravador';

/**
 * Cameras do site, do inventario (a mesma fonte e a mesma regra em toda tela
 * que mostra numero de camera), com o nome e o local do gravador de cada uma.
 * O local vem do cadastro do gravador; sem gravador, do site da camera.
 */
export function useCamerasDoSite() {
  const { site } = useSite();
  const q = useCameras();
  const nvrs = useEntidades('nvr');
  const doSiteFn = useFiltroSite(site);

  const gravPorHost = useMemo(() => {
    const m = new Map<string, { nome: string; local: string }>();
    for (const e of nvrs.data ?? []) {
      const host = String(detalhe<{ host?: string }>(e).host ?? '');
      if (!host || !doSiteFn(e.site, e.connector_id)) continue;
      const nome = String(e.display_name ?? '');
      const ja = m.get(host);
      if (!ja || ja.nome === host) m.set(host, { nome: nome || host, local: String(e.site ?? '').trim().toUpperCase() });
    }
    return m;
  }, [nvrs.data, doSiteFn]);

  const cameras = useMemo(() => (q.data ?? []).filter((c) => !site || doSiteFn(siteDa(c), c.remote_connector_id || c.connector_id)),
    [q.data, site, doSiteFn]);
  const localDa = (c: Camera) => gravPorHost.get(String(c.recorder_host ?? ''))?.local || siteDa(c).toUpperCase() || 'SEM LOCAL';
  const gravadorDa = (c: Camera) => {
    const h = String(c.recorder_host ?? '').trim();
    return h ? gravPorHost.get(h)?.nome || h : SEM_GRAVADOR;
  };
  return { q, cameras, localDa, gravadorDa };
}

export const sitCamera = (c: Camera): Situacao => {
  const e = estadoDa(c);
  return e === 'online' ? 'ok' : e === 'offline' ? 'fora' : 'atencao';
};

export function Cameras() {
  const online = useOnline();
  const { site, pronto } = useSite();
  const { q, cameras, localDa, gravadorDa } = useCamerasDoSite();
  const [param] = useSearchParams();
  const ir = useNavigate();

  const { lista, barra } = useFiltro(cameras, {
    texto: (c) => [c.titulo, c.title, c.ip, c.mac, c.modelo, c.recorder_channel, gravadorDa(c)],
    dica: 'Título, IP, MAC, canal ou gravador', buscaInicial: param.get('q') ?? '',
    local: localDa,
    extra: { rotulo: 'Gravador', todos: 'Todos os gravadores', de: gravadorDa },
    situacao: sitCamera, nomes: { todos: 'Todas', ok: 'No ar', atencao: 'Sem leitura' }, unidade: 'câmeras',
    inicial: { local: param.get('local') ?? undefined, extra: param.get('gravador') ?? undefined, sit: (param.get('sit') as Situacao) ?? undefined },
  });

  // Agrupar por gravador, pelo nome (o tecnico procura "JARDINS II - 03", nao o IP); sem gravador por ultimo.
  const grupos = useMemo(() => {
    const m = new Map<string, Camera[]>();
    for (const c of lista) m.set(gravadorDa(c), [...(m.get(gravadorDa(c)) ?? []), c]);
    return [...m.entries()].sort((a, b) => (a[0] === SEM_GRAVADOR ? 1 : 0) - (b[0] === SEM_GRAVADOR ? 1 : 0) || ordemNatural(a[0], b[0]));
  }, [lista]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!pronto || (q.isPending && !q.data)) return <Carregando />;

  return (
    <>
      <div className="linha-topo">
        <Titulo titulo="Câmeras" sub={`${site ?? 'Todos os sites'} · ${cameras.length} no projeto`} />
        <span style={{ marginLeft: 'auto' }}>
          <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
        </span>
      </div>

      {barra}

      {grupos.length === 0 ? (
        <Cartao><Vazio>Nada com esse filtro.</Vazio></Cartao>
      ) : grupos.map(([nome, cams]) => {
        const host = String(cams[0].recorder_host ?? '');
        return (
          <Cartao key={nome}>
            <h2>{nome}</h2>
            <p className="sub-h2">{[host && host !== nome ? host : '', `${cams.length} câmera${cams.length === 1 ? '' : 's'}`].filter(Boolean).join(' · ')}</p>
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
        );
      })}
    </>
  );
}
