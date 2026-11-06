import { useEffect, useRef, useState } from 'react';
import { tocar } from '../lib/aovivo';
import type { Camera } from '../lib/termico';
import { Foto } from './pecas';

/**
 * Video ao vivo por cima da foto de agora: abre na hora e o video assume quando
 * chega. O fluxo leve da camera nao tem o formato do sensor (704x576 de uma
 * imagem 16:9), entao quem manda no formato e a caixa, em `formatoDe`.
 */
export const formatoDe = (tipo: 'termica' | 'colorida') => (tipo === 'termica' ? '4 / 3' : '16 / 9');

export function VideoVivo({ cam, tipo, hd, aviso }: { cam: Camera; tipo: 'termica' | 'colorida'; hd?: boolean; aviso?: (t: string) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const [estado, setEstado] = useState('Conectando…');
  const { ip, connector_id: conector } = cam;
  useEffect(() => {
    if (!video.current) return;
    setEstado('Conectando…');
    const p = tocar(video.current, { ip, connector_id: conector, tipo, hd }, (t) => { setEstado(t); aviso?.(t); });
    return () => p.parar();
  }, [ip, conector, tipo, hd, aviso]);
  return (
    <>
      <Foto caminho={`/api/termico/cameras/${cam.id}/agora/${tipo}`} alt={cam.nome} />
      <video ref={video} className={`video-vivo ${estado ? '' : 'on'}`} autoPlay muted playsInline />
    </>
  );
}
