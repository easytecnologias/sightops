import { useEffect, useRef, useState } from 'react';
import { Icone } from './pecas';

/**
 * Camera do rosto.
 *
 * Visor ao vivo (getUserMedia) com o oval onde o rosto deve caber: e o
 * enquadramento que o leitor facial aceita. A foto sai recortada em 3:4 e
 * reduzida a 720 px de largura em JPEG -- o leitor nao precisa de mais que
 * isso, e foto de 4 MB pelo 4G e o que faz o cadastro "travar".
 *
 * A unica checagem feita aqui e a de luz, medida de verdade no quadro. Se o
 * rosto esta bom quem decide e o leitor quando recebe a foto; a tela de envio
 * mostra se ele aceitou ou recusou.
 */
export type Foto = { blob: Blob; url: string };

const LARGURA = 720;

async function reduzir(origem: CanvasImageSource, w: number, h: number, espelhar: boolean): Promise<Foto> {
  // Recorte central 3:4 (retrato), igual ao oval do visor.
  let cw = w;
  let ch = Math.round((w * 4) / 3);
  if (ch > h) { ch = h; cw = Math.round((h * 3) / 4); }
  const sx = Math.round((w - cw) / 2);
  const sy = Math.round((h - ch) / 2);
  const ow = Math.min(LARGURA, cw);
  const oh = Math.round((ow * 4) / 3);
  const c = document.createElement('canvas');
  c.width = ow;
  c.height = oh;
  const g = c.getContext('2d')!;
  if (espelhar) { g.translate(ow, 0); g.scale(-1, 1); }
  g.drawImage(origem, sx, sy, cw, ch, 0, 0, ow, oh);
  const blob = await new Promise<Blob>((ok, falha) =>
    c.toBlob((b) => (b ? ok(b) : falha(new Error('foto'))), 'image/jpeg', 0.86));
  return { blob, url: URL.createObjectURL(blob) };
}

export async function fotoDeArquivo(arq: File): Promise<Foto> {
  const url = URL.createObjectURL(arq);
  try {
    const img = new Image();
    await new Promise((ok, falha) => { img.onload = ok; img.onerror = falha; img.src = url; });
    return await reduzir(img, img.naturalWidth, img.naturalHeight, false);
  } finally {
    URL.revokeObjectURL(url);
  }
}

export function Camera(
  { titulo, sub, passo, aoFechar, aoTirar }:
  { titulo: string; sub: string; passo?: number; aoFechar: () => void; aoTirar: (f: Foto) => void },
) {
  const video = useRef<HTMLVideoElement>(null);
  const arquivo = useRef<HTMLInputElement>(null);
  const [frente, setFrente] = useState(true);
  const [erro, setErro] = useState('');
  const [pronta, setPronta] = useState(false);
  const [luz, setLuz] = useState<'boa' | 'fraca' | 'forte' | ''>('');

  useEffect(() => {
    let fluxo: MediaStream | null = null;
    let vivo = true;
    setPronta(false);
    setErro('');
    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error('sem camera');
        fluxo = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: frente ? 'user' : 'environment', width: { ideal: 1280 }, height: { ideal: 1280 } },
          audio: false,
        });
        if (!vivo) { fluxo.getTracks().forEach((t) => t.stop()); return; }
        const v = video.current!;
        v.srcObject = fluxo;
        await v.play();
        setPronta(true);
      } catch (e) {
        const nome = (e as { name?: string })?.name;
        setErro(nome === 'NotAllowedError'
          ? 'A câmera não foi liberada. Libere nos ajustes do celular ou escolha uma foto da galeria.'
          : 'Não consegui abrir a câmera. Escolha uma foto da galeria.');
      }
    })();
    return () => { vivo = false; fluxo?.getTracks().forEach((t) => t.stop()); };
  }, [frente]);

  // Luz: media de brilho de um quadro pequeno, duas vezes por segundo.
  useEffect(() => {
    if (!pronta) return;
    const c = document.createElement('canvas');
    c.width = 32; c.height = 32;
    const g = c.getContext('2d', { willReadFrequently: true });
    const id = window.setInterval(() => {
      const v = video.current;
      if (!g || !v || !v.videoWidth) return;
      g.drawImage(v, v.videoWidth * 0.25, v.videoHeight * 0.2, v.videoWidth * 0.5, v.videoHeight * 0.6, 0, 0, 32, 32);
      const d = g.getImageData(0, 0, 32, 32).data;
      let soma = 0;
      for (let i = 0; i < d.length; i += 4) soma += 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
      const media = soma / (d.length / 4);
      setLuz(media < 60 ? 'fraca' : media > 215 ? 'forte' : 'boa');
    }, 500);
    return () => window.clearInterval(id);
  }, [pronta]);

  async function tirar() {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    aoTirar(await reduzir(v, v.videoWidth, v.videoHeight, frente));
  }

  async function daGaleria(ev: React.ChangeEvent<HTMLInputElement>) {
    const arq = ev.target.files?.[0];
    ev.target.value = '';
    if (!arq) return;
    try { aoTirar(await fotoDeArquivo(arq)); } catch { setErro('Não consegui ler essa imagem. Tente outra.'); }
  }

  const textoLuz = luz === 'fraca' ? 'Pouca luz — procure um lugar mais claro'
    : luz === 'forte' ? 'Luz forte demais — saia do contraluz' : 'Rosto inteiro dentro do oval, olhando de frente';

  return (
    <div className="camera" role="dialog" aria-label={titulo}>
      <div className="cab">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <button type="button" className="redondo" aria-label="Fechar câmera" onClick={aoFechar}>{Icone.x}</button>
          <span style={{ flex: 1 }}>
            <b style={{ display: 'block', fontSize: 17 }}>{titulo}</b>
            <span style={{ display: 'block', fontSize: 12.5, color: 'var(--escuro-txt)' }}>{sub}</span>
          </span>
        </div>
        {passo ? (
          <div className="passos" aria-hidden="true">
            {[1, 2, 3].map((n) => <span key={n} className={n <= passo ? 'on' : ''} />)}
          </div>
        ) : null}
      </div>

      <div className="visor">
        <video ref={video} className={frente ? 'espelho' : ''} playsInline muted />
        <svg className="mascara" viewBox="0 0 300 400" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <defs>
            <mask id="furo"><rect width="300" height="400" fill="#fff" /><ellipse cx="150" cy="190" rx="92" ry="122" fill="#000" /></mask>
          </defs>
          <rect width="300" height="400" fill="#0b1519" opacity=".55" mask="url(#furo)" />
          <ellipse cx="150" cy="190" rx="92" ry="122" fill="none"
                   stroke={luz && luz !== 'boa' ? '#ffd38a' : '#3fd09a'} strokeWidth="3.5" />
        </svg>
        {pronta && luz ? (
          <span className="dicas">
            <span className={`dica${luz === 'boa' ? '' : ' ruim'}`}>
              <i>{luz === 'boa' ? Icone.ok : Icone.aviso}</i>{luz === 'boa' ? 'Boa luz' : luz === 'fraca' ? 'Pouca luz' : 'Contraluz'}
            </span>
          </span>
        ) : null}
        {pronta ? <span className={`rodape${luz && luz !== 'boa' ? ' ruim' : ''}`}>{textoLuz}</span> : null}
        {erro ? <div className="falha">{erro}</div> : null}
        {!pronta && !erro ? <div className="falha">Abrindo a câmera…</div> : null}
      </div>

      <div className="controles">
        <button type="button" className="redondo" aria-label="Escolher foto da galeria" onClick={() => arquivo.current?.click()}>
          {Icone.galeria}
        </button>
        <button type="button" className="disparo" aria-label="Tirar foto" disabled={!pronta} onClick={tirar}><span /></button>
        <button type="button" className="redondo" aria-label="Virar câmera" onClick={() => setFrente((f) => !f)}>
          {Icone.virar}
        </button>
        <input ref={arquivo} type="file" accept="image/*" hidden onChange={daGaleria} />
      </div>
    </div>
  );
}
