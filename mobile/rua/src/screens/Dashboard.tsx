import { useResumo } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { Badge, Carregando, Icone, Kpi, Linha, PageHeading, Panel, PanelHeader, Procedencia, Vazio } from '../ui/pecas';

const n = (v: unknown, padrao: string = '—') =>
  typeof v === 'number' ? String(v) : padrao;

export function Dashboard() {
  const online = useOnline();
  const q = useResumo();

  if (q.isPending && !q.data) return <Carregando />;

  const inv = q.data?.inventory ?? {};
  const ip = inv.ip ?? {};
  const nvr = inv.nvr ?? {};
  const dvr = inv.dvr ?? {};
  const alertas = q.data?.alerts ?? [];
  const gravadores = (nvr.total ?? 0) + (dvr.total ?? 0);

  return (
    <>
      <PageHeading eyebrow="Central operacional" titulo="Dashboard"
                   sub="Disponibilidade e cobertura de todo o parque." />

      <div className="barra-acao">
        <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
        <button type="button" className="acao" onClick={() => q.refetch()}
                disabled={q.isFetching}>
          {Icone.atualizar}
          Atualizar
        </button>
      </div>

      {!q.data ? (
        <Panel>
          <Vazio>Sem dados e sem copia no aparelho.<br />Conecte uma vez para baixar.</Vazio>
        </Panel>
      ) : (
        <>
          <div className="metrics">
            <Kpi cor="green" icone={Icone.camera} rotulo="Cameras IP"
                 numero={n(ip.online)} sub={`de ${n(ip.total)} total`} />
            <Kpi cor="blue" icone={Icone.gravador} rotulo="Gravadores"
                 numero={gravadores} sub={`${n(dvr.total, '0')} DVR · ${n(nvr.total, '0')} NVR`} />
            <Kpi cor="red" icone={Icone.alerta} rotulo="Fora do ar"
                 numero={n(ip.offline, '0')} sub="cameras sem resposta" />
            <Kpi cor="amber" icone={Icone.alerta} rotulo="Sem leitura"
                 numero={n(ip.unknown, '0')} sub="nao deu para medir" />
            <Kpi cor="purple" icone={Icone.camera} rotulo="Sem snapshot"
                 numero={n(ip.missing_snapshot, '0')} sub="cameras sem foto" />
            <Kpi cor="cyan" icone={Icone.pin} rotulo="Sem local"
                 numero={n(ip.missing_local, '0')} sub="sem site definido" />
          </div>

          {alertas.length > 0 && (
            <>
              <hr className="sep" />
              <Panel variante="atencao">
                <PanelHeader titulo="Precisam de atencao" sub="Parque inteiro"
                             direita={<Badge cor="red">{alertas.length}</Badge>} />
                {alertas.map((a, i) => (
                  <Linha key={i} icone={Icone.alerta}
                         titulo={a.label ?? '—'}
                         direita={
                           <Badge cor={a.level === 'danger' ? 'red' : a.level === 'warning' ? 'amber' : 'gray'}>
                             {a.count ?? ''}
                           </Badge>
                         } />
                ))}
              </Panel>
            </>
          )}
        </>
      )}
    </>
  );
}
