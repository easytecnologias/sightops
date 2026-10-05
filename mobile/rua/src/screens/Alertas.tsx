import { useAlertas } from '../lib/dados';
import { Cartao, Icone, Item, Pilula, Titulo, Vazio } from '../ui/pecas';

/**
 * Alertas abertos.
 *
 * So a CONTAGEM, por enquanto: a lista de incidentes precisa de endpoint
 * proprio e de cuidado com o que mostra. O campo `duress` (coacao) existe na
 * resposta e nunca e lido -- coacao e pedido de socorro silencioso, e exibir
 * que ele existe entrega quem o acionou.
 */
export function Alertas() {
  const q = useAlertas();
  const abertos = q.data?.open ?? 0;
  const novos = q.data?.novos ?? 0;

  return (
    <>
      <Titulo titulo="Alertas" sub="Panico aberto pelos operadores do cliente." />
      <Cartao>
        <h2>Agora</h2>
        {abertos === 0 ? (
          <Vazio>Nenhum alerta aberto.</Vazio>
        ) : (
          <>
            <Item ponto="vermelho" icone={Icone.alerta} titulo="Alertas abertos"
                  direita={<Pilula cor="vermelha">{abertos}</Pilula>} />
            <Item ponto={novos ? 'vermelho' : 'verde'} icone={Icone.aviso}
                  titulo="Ainda sem atendimento"
                  direita={<Pilula cor={novos ? 'vermelha' : 'verde'}>{novos}</Pilula>} />
          </>
        )}
      </Cartao>
      <Cartao>
        <h2>Atender</h2>
        <div style={{ padding: '0 14px 14px', fontSize: 13, color: 'var(--muted)' }}>
          O atendimento acontece no SightOps no navegador. Aqui o aplicativo
          avisa que existe alerta aberto para voce nao descobrir so no fim do dia.
        </div>
      </Cartao>
    </>
  );
}
