import { useNavigate } from 'react-router-dom';
import { chaveDa, estadoDa, siteDa, useAlertas, useCameras, useResumo } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Bloco, Carregando, Cartao, Icone, Item, Pilula, Procedencia, Vazio } from '../ui/pecas';

export function Inicio() {
  const online = useOnline();
  const { site } = useSite();
  const resumo = useResumo();
  const cams = useCameras();
  const alertas = useAlertas();
  const ir = useNavigate();

  if (resumo.isPending && !resumo.data && cams.isPending && !cams.data) return <Carregando />;

  const inv = resumo.data?.inventory ?? {};
  const ip = inv.ip ?? {};
  const gravTotal = (inv.nvr?.total ?? 0) + (inv.dvr?.total ?? 0);
  const gravOff = (inv.nvr?.offline ?? 0) + (inv.dvr?.offline ?? 0);

  // Numeros do SITE escolhido, nao do parque: quem esta no poste quer saber
  // deste lugar. O parque inteiro fica nos alertas abaixo.
  const noSite = (cams.data ?? []).filter((c) => !site || siteDa(c).toLowerCase() === site.toLowerCase());
  const siteOn = noSite.filter((c) => estadoDa(c) === 'online').length;
  const siteOff = noSite.filter((c) => estadoDa(c) === 'offline').length;
  const siteSem = noSite.filter((c) => estadoDa(c) === 'sem').length;

  const avisos = resumo.data?.alerts ?? [];
  const abertos = alertas.data?.open ?? 0;

  return (
    <>
      {abertos > 0 && (
        <button type="button" className="faixa-alerta" onClick={() => ir('/alertas')}>
          <span className="bolha">{Icone.alerta}</span>
          <span style={{ flexGrow: 1, textAlign: 'left' }}>
            <span className="t">
              {abertos === 1 ? 'Alerta aberto' : `${abertos} alertas abertos`}
            </span>
            <span className="s">
              {(alertas.data?.novos ?? 0) > 0 ? `${alertas.data?.novos} sem atendimento` : 'em atendimento'}
            </span>
          </span>
          {Icone.seta}
        </button>
      )}

      <div className="linha-topo">
        <Procedencia buscando={cams.isFetching || resumo.isFetching}
                     atualizadoEm={Math.max(cams.dataUpdatedAt, resumo.dataUpdatedAt)}
                     online={online} />
        <button type="button" className="acao" disabled={resumo.isFetching}
                onClick={() => { void resumo.refetch(); void cams.refetch(); }}>
          {Icone.atualizar}
          Atualizar
        </button>
      </div>

      <div className="mosaico">
        <Bloco rotulo={site ? `Cameras · ${site}` : 'Cameras'}
               numero={noSite.length}
               onClick={() => ir('/cameras')}
               pes={<>
                 <b className="verde">{siteOn} online</b>
                 {siteOff > 0 ? <b className="vermelho">{siteOff} offline</b> : null}
                 {siteSem > 0 ? <b className="ambar">{siteSem} sem ler</b> : null}
               </>} />

        <Bloco rotulo="Gravadores" numero={gravTotal}
               pes={<>
                 <b className="verde">{gravTotal - gravOff} online</b>
                 {gravOff > 0 ? <b className="vermelho">{gravOff} offline</b> : null}
               </>} />

        <Bloco rotulo="Parque" numero={ip.total ?? '—'}
               pes={<>
                 <b className="verde">{ip.online ?? 0} online</b>
                 {(ip.offline ?? 0) > 0 ? <b className="vermelho">{ip.offline} offline</b> : null}
               </>} />

        <Bloco rotulo="Sem foto" numero={ip.missing_snapshot ?? 0}
               pes={<b className="ambar">cameras sem snapshot</b>} />
      </div>

      <Cartao>
        <h2>Precisa de atencao</h2>
        <p className="sub-h2">Parque inteiro, nao so este site</p>
        {avisos.length === 0 ? (
          <Vazio>Nada pendente agora.</Vazio>
        ) : avisos.map((a, i) => (
          <Item key={i}
                ponto={a.level === 'danger' ? 'vermelho' : a.level === 'warning' ? 'ambar' : 'verde'}
                titulo={a.label ?? '—'}
                direita={
                  <Pilula cor={a.level === 'danger' ? 'vermelha' : a.level === 'warning' ? 'ambar' : 'cinza'}>
                    {a.count ?? ''}
                  </Pilula>
                } />
        ))}
      </Cartao>

      {siteOff + siteSem > 0 && (
        <Cartao>
          <h2>Precisa de visita</h2>
          <p className="sub-h2">{site ?? 'Todos os sites'} · fora do ar e sem leitura</p>
          {noSite
            .filter((c) => estadoDa(c) !== 'online')
            .slice(0, 8)
            .map((c, i) => (
              <Item key={`${c.ip}-${i}`}
                    ponto={estadoDa(c) === 'offline' ? 'vermelho' : 'ambar'}
                    titulo={c.titulo || c.title || c.ip || '—'}
                    sub={[c.ip, c.recorder_channel ? `CH ${c.recorder_channel}` : null]
                      .filter(Boolean).join(' · ')}
                    onClick={() => ir(`/cameras/${chaveDa(c)}`)} />
            ))}
        </Cartao>
      )}
    </>
  );
}
