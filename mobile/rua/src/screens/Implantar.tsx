import { useOnline } from '../lib/rede';
import { Cartao, Icone, Item, Titulo } from '../ui/pecas';

/**
 * Hub de implantacao.
 *
 * Tudo aqui manda ordem a equipamento vivo pelo tunel do conector, e por isso
 * NADA aqui pode entrar numa fila para subir depois: o comando so existe no
 * momento em que chega ao equipamento. As acoes aparecem mesmo antes de
 * existirem -- esconder o que falta faz o tecnico procurar; dizer "ainda nao"
 * resolve a duvida em um segundo.
 */
const ACOES = [
  { icone: Icone.onu, titulo: 'Ativar ONU', sub: 'Autorizar ONU nova na PON' },
  { icone: Icone.raio, titulo: 'Ativar câmera', sub: 'Câmera de fábrica, sem senha' },
  { icone: Icone.camera, titulo: 'Instalar câmera', sub: 'Achar na rede, nomear e registrar' },
  { icone: Icone.gravador, titulo: 'Gravador', sub: 'Canais e troca de câmera de canal' },
  { icone: Icone.engrenagem, titulo: 'Ajustar câmera', sub: 'Trocar IP, título e reiniciar' },
];

export function Implantar() {
  const online = useOnline();

  return (
    <>
      <Titulo titulo="Implantar"
              sub="Comandos em equipamento vivo, pelo túnel do conector." />

      {!online && (
        <div className="faixa-alerta" style={{ background: 'var(--amber)' }}>
          <span className="bolha" style={{ background: 'var(--amber-forte)' }}>{Icone.aviso}</span>
          <span style={{ flexGrow: 1 }}>
            <span className="t">Sem sinal</span>
            <span className="s">Nada aqui funciona agora, e não dá para deixar na fila.</span>
          </span>
        </div>
      )}

      <Cartao>
        <h2>Ações de campo</h2>
        <p className="sub-h2">Todas exigem sinal no momento do toque</p>
        {ACOES.map((a) => (
          <Item key={a.titulo} icone={a.icone} titulo={a.titulo} sub={a.sub}
                direita={<span className="selo cinza">em breve</span>} />
        ))}
      </Cartao>

      <Cartao>
        <h2>Por que não offline</h2>
        <div style={{ padding: '0 14px 14px', fontSize: 13, color: 'var(--muted)' }}>
          Autorizar uma ONU, ativar uma câmera ou mexer num canal de gravador são
          ordens que só existem quando chegam ao equipamento. Guardar numa fila
          para enviar depois criaria o pior erro possível: você acreditar que
          autorizou e ir embora.
        </div>
      </Cartao>
    </>
  );
}
