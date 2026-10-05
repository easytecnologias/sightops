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
  { icone: Icone.raio, titulo: 'Ativar camera', sub: 'Camera de fabrica, sem senha' },
  { icone: Icone.camera, titulo: 'Instalar camera', sub: 'Achar na rede, nomear e registrar' },
  { icone: Icone.gravador, titulo: 'Gravador', sub: 'Canais e troca de camera de canal' },
  { icone: Icone.engrenagem, titulo: 'Ajustar camera', sub: 'Trocar IP, titulo e reiniciar' },
];

export function Implantar() {
  const online = useOnline();

  return (
    <>
      <Titulo titulo="Implantar"
              sub="Comandos em equipamento vivo, pelo tunel do conector." />

      {!online && (
        <div className="faixa-alerta" style={{ background: 'var(--amber)' }}>
          <span className="bolha" style={{ background: 'var(--amber-forte)' }}>{Icone.aviso}</span>
          <span style={{ flexGrow: 1 }}>
            <span className="t">Sem sinal</span>
            <span className="s">Nada aqui funciona agora, e nao da para deixar na fila.</span>
          </span>
        </div>
      )}

      <Cartao>
        <h2>Acoes de campo</h2>
        <p className="sub-h2">Todas exigem sinal no momento do toque</p>
        {ACOES.map((a) => (
          <Item key={a.titulo} icone={a.icone} titulo={a.titulo} sub={a.sub}
                direita={<span className="selo cinza">em breve</span>} />
        ))}
      </Cartao>

      <Cartao>
        <h2>Por que nao offline</h2>
        <div style={{ padding: '0 14px 14px', fontSize: 13, color: 'var(--muted)' }}>
          Autorizar uma ONU, ativar uma camera ou mexer num canal de gravador sao
          ordens que so existem quando chegam ao equipamento. Guardar numa fila
          para enviar depois criaria o pior erro possivel: voce acreditar que
          autorizou e ir embora.
        </div>
      </Cartao>
    </>
  );
}
