import { useEffect, useState } from 'react';
import { estadoDa, siteDa, siteDoConector, tituloDa, useCameras, useConectores, type Camera } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { pegar, salvar } from '../lib/storage';
import { Badge, Carregando, Icone, Kpi, Linha, PageHeading, Panel, PanelHeader, Procedencia, Vazio } from '../ui/pecas';

const CHAVE_SITE = 'rua.site';

/** O site escolhido vale para o app inteiro e sobrevive a fechar o
 *  aplicativo: o tecnico passa o dia no mesmo lugar. */
export function useSite() {
  const [site, setSite] = useState<string | null>(null);
  const [pronto, setPronto] = useState(false);

  useEffect(() => {
    pegar(CHAVE_SITE).then((v) => { setSite(v); setPronto(true); });
  }, []);

  const escolher = (s: string) => { setSite(s); void salvar(CHAVE_SITE, s); };
  return { site, escolher, pronto };
}

export function Site() {
  const online = useOnline();
  const { site, escolher, pronto } = useSite();
  const cams = useCameras();
  const cons = useConectores();
  const [trocando, setTrocando] = useState(false);

  if (!pronto) return <Carregando />;

  if (!site || trocando) {
    const sites = [...new Set((cons.data ?? []).map(siteDoConector).filter(Boolean))].sort();
    return (
      <>
        <PageHeading eyebrow="Campo" titulo="Onde voce esta"
                     sub="Escolha o site para o resto do aplicativo se situar." />
        <Panel>
          {cons.isPending && !cons.data ? <Carregando /> : null}
          {sites.length === 0 && !cons.isPending ? (
            <Vazio>Nenhum conector com site.<br />Conecte uma vez para baixar a lista.</Vazio>
          ) : (
            sites.map((s) => (
              <Linha key={s} icone={Icone.pin} titulo={s} direita={Icone.seta}
                     onClick={() => { escolher(s); setTrocando(false); }} />
            ))
          )}
        </Panel>
      </>
    );
  }

  if (cams.isPending && !cams.data) return <Carregando />;

  const doSite = (cams.data ?? []).filter((c) => siteDa(c).toLowerCase() === site.toLowerCase());
  const online_ = doSite.filter((c) => estadoDa(c) === 'online');
  const fora = doSite.filter((c) => estadoDa(c) === 'offline');
  const sem = doSite.filter((c) => estadoDa(c) === 'sem');
  const visita: Camera[] = [...fora, ...sem];

  return (
    <>
      <PageHeading eyebrow="Campo" titulo={site}
                   sub="O que esta de pe aqui e o que precisa de visita." />

      <div className="barra-acao">
        <Procedencia buscando={cams.isFetching} atualizadoEm={cams.dataUpdatedAt} online={online} />
        <button type="button" className="acao" onClick={() => setTrocando(true)}>
          Trocar de site
        </button>
      </div>

      <div className="metrics">
        <Kpi cor="green" icone={Icone.camera} rotulo="Respondendo"
             numero={online_.length} sub={`de ${doSite.length} no site`} />
        <Kpi cor="red" icone={Icone.alerta} rotulo="Fora do ar"
             numero={fora.length} sub={fora.length ? 'precisa de visita' : 'nenhuma'} />
        <Kpi cor="amber" icone={Icone.alerta} rotulo="Sem leitura"
             numero={sem.length} sub={sem.length ? 'conector ou rede' : 'nenhuma'} />
        <Kpi cor="blue" icone={Icone.pasta} rotulo="No projeto"
             numero={doSite.length} sub="cameras cadastradas" />
      </div>

      <hr className="sep" />

      <Panel variante={visita.length ? 'atencao' : undefined}>
        <PanelHeader titulo="Precisam de visita" sub="Fora do ar e sem leitura"
                     direita={<Badge cor={visita.length ? 'red' : 'green'}>{visita.length}</Badge>} />
        {visita.length === 0 ? (
          <Vazio>Tudo respondendo neste site.</Vazio>
        ) : (
          visita.map((c, i) => (
            <Linha key={`${c.ip}-${i}`} icone={Icone.camera}
                   titulo={tituloDa(c)}
                   sub={[c.ip, c.recorder_channel ? `CH ${c.recorder_channel}` : null]
                     .filter(Boolean).join(' · ')}
                   direita={
                     <Badge cor={estadoDa(c) === 'offline' ? 'red' : 'amber'}>
                       {estadoDa(c) === 'offline' ? 'fora' : 'sem ler'}
                     </Badge>
                   } />
          ))
        )}
      </Panel>
    </>
  );
}
