import { useOnline } from '../lib/rede';
import { Badge, PageHeading, Panel, PanelHeader } from '../ui/pecas';

/**
 * Telas que mandam ordem a equipamento vivo.
 *
 * Elas aparecem no menu de proposito, mesmo antes de existirem. Esconder o que
 * ainda nao funciona faz o tecnico procurar; dizer "ainda nao" resolve a
 * duvida em um segundo. E deixa claro, desde ja, por que estas nunca vao
 * funcionar offline: o comando so existe no momento em que chega ao
 * equipamento.
 */
export function ExigeSinal({ titulo, descricao }: { titulo: string; descricao: string }) {
  const online = useOnline();
  return (
    <>
      <PageHeading eyebrow="Implantacao" titulo={titulo} sub={descricao} />

      <Panel variante="atencao">
        <PanelHeader
          titulo="Ainda nao neste aplicativo"
          sub="Use o SightOps no navegador por enquanto"
          direita={<Badge cor={online ? 'green' : 'amber'}>{online ? 'online' : 'sem sinal'}</Badge>} />
        <div className="panel-body">
          <p style={{ margin: 0, fontSize: 13.5 }}>
            Esta tela manda ordem para o equipamento no momento do toque, pelo tunel do
            conector.
          </p>
          <p style={{ margin: 0, fontSize: 12.5, color: 'var(--muted)' }}>
            Por isso ela nunca vai funcionar sem sinal, nem entrar numa fila para subir
            depois: o pior erro possivel seria voce achar que autorizou e ir embora.
          </p>
        </div>
      </Panel>
    </>
  );
}
