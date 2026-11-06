import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { tocar } from '../lib/aovivo';
import { num, useCameras } from '../lib/termico';
import { Carregando, Erro, Icone } from '../ui/pecas';

/** Video ao vivo de uma camera: termica ou colorida, no fluxo leve. */
export function AoVivo() {
  const { id } = useParams();
  const nav = useNavigate();
  const cams = useCameras();
  const cam = cams.data?.cameras.find((c) => c.id === id);
  const video = useRef<HTMLVideoElement>(null);
  const [tipo, setTipo] = useState<'termica' | 'colorida'>('termica');
  const [aviso, setAviso] = useState('Conectando…');
  const ip = cam?.ip;
  const conector = cam?.connector_id ?? '';

  useEffect(() => {
    if (!video.current || !ip) return;
    const p = tocar(video.current, { ip, connector_id: conector, tipo }, setAviso);
    return () => p.parar();
  }, [ip, conector, tipo]);

  if (cams.isLoading) return <Carregando />;
  if (cams.error) return <Erro erro={cams.error} />;
  if (!cam) return <div className="vazio">Câmera não encontrada.</div>;
  return (
    <>
      <div className="vivo-video">
        <video ref={video} autoPlay muted playsInline />
        {aviso ? <span className="vivo-aviso">{aviso}</span> : null}
        <span className="selo alerta">AO VIVO</span>
        <div className="alerta-barra">
          <button type="button" className="bt-redondo" aria-label="Voltar" onClick={() => nav(-1)}>{Icone.voltar}</button>
          <div className="alternar" role="tablist">
            <button type="button" role="tab" aria-selected={tipo === 'termica'} className={tipo === 'termica' ? 'on' : ''} onClick={() => setTipo('termica')}>Térmica</button>
            <button type="button" role="tab" aria-selected={tipo === 'colorida'} className={tipo === 'colorida' ? 'on' : ''} onClick={() => setTipo('colorida')}>Colorida</button>
          </div>
        </div>
      </div>
      <div className="pagina">
        <h1>{cam.nome}</h1>
        <small>{cam.site}{cam.fundo_c === null ? '' : ` · cena a ${num(cam.fundo_c, 0)} °C`}</small>
      </div>
    </>
  );
}
