import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { hora, natural, num, useAlertas, useCameras } from '../lib/termico';
import { Carregando, Erro, Foto, Icone } from '../ui/pecas';
import { formatoDe, VideoVivo } from '../ui/VideoVivo';

/** Uma camera ao vivo: termica ou colorida, SD ou HD, e as outras da usina logo abaixo. */
export function AoVivo() {
  const { id } = useParams();
  const nav = useNavigate();
  const cams = useCameras();
  const al = useAlertas();
  const [tipo, setTipo] = useState<'termica' | 'colorida'>('termica');
  const [hd, setHd] = useState(false);
  const [cheia, setCheia] = useState(false);
  const [aviso, setAviso] = useState('Conectando…');
  const cam = cams.data?.cameras.find((c) => c.id === id);

  if (cams.isLoading) return <Carregando />;
  if (cams.error) return <Erro erro={cams.error} />;
  if (!cam) return <div className="vazio">Câmera não encontrada.</div>;

  const vizinhas = (cams.data?.cameras || []).filter((c) => c.site === cam.site && c.id !== cam.id).sort((a, b) => natural(a.nome, b.nome));
  const alarmes = (al.data?.alertas || []).filter((a) => a.camera_id === cam.id).slice(0, 3);
  const lendo = cam.ativo && cam.leitura === 'ok';
  return (
    <>
      <div className={`vivo ${cheia ? 'cheia' : ''}`}>
        <div className="vivo-quadro" style={{ aspectRatio: formatoDe(tipo) }}>
          <VideoVivo key={cam.id} cam={cam} tipo={tipo} hd={hd} aviso={setAviso} />
          {aviso ? <span className="vivo-aviso">{aviso}</span> : null}
        </div>
        <div className="vivo-topo">
          <button type="button" className="bt-redondo" aria-label="Voltar" onClick={() => (cheia ? setCheia(false) : nav(-1))}>{Icone.voltar}</button>
          <span className="vivo-marca"><i />AO VIVO</span>
        </div>
        <div className="vivo-base">
          <div className="alternar" role="tablist" aria-label="Qualidade">
            <button type="button" role="tab" aria-selected={!hd} className={hd ? '' : 'on'} onClick={() => setHd(false)}>SD</button>
            <button type="button" role="tab" aria-selected={hd} className={hd ? 'on' : ''} onClick={() => setHd(true)}>HD</button>
          </div>
          <button type="button" className="bt-redondo escuro" aria-label={cheia ? 'Sair da tela cheia' : 'Tela cheia'} onClick={() => setCheia(!cheia)}>{Icone.cheia}</button>
        </div>
      </div>
      <div className="pagina">
        <section className="cartao vivo-info">
          <div className="linha">
            <div className="cresce"><h2>{cam.nome}</h2><small>{cam.site}</small></div>
            <span className={`etq ${lendo ? 'ok' : cam.ativo ? 'alerta' : 'aviso'}`}>{lendo ? 'Vigiando' : cam.ativo ? 'Sem medição' : 'Só vídeo'}</span>
          </div>
          <div className="alternar largo" role="tablist" aria-label="Imagem">
            <button type="button" role="tab" aria-selected={tipo === 'termica'} className={tipo === 'termica' ? 'on' : ''} onClick={() => setTipo('termica')}>Térmica</button>
            <button type="button" role="tab" aria-selected={tipo === 'colorida'} className={tipo === 'colorida' ? 'on' : ''} onClick={() => setTipo('colorida')}>Colorida</button>
          </div>
          {cam.fundo_c === null ? null : <small>Temperatura da cena: <b>{num(cam.fundo_c, 0)} °C</b></small>}
          {hd ? <small>HD gasta bem mais internet da usina. Se travar, volte para SD.</small> : null}
        </section>
        {alarmes.length ? <div className="titulo-sec">Últimos alarmes desta câmera</div> : null}
        {alarmes.map((a) => (
          <Link key={a.id} to={`/alerta/${a.id}`} className="cartao item">
            <div className="item-foto"><Foto caminho={a.fotos.termico} alt="" /></div>
            <div className="cresce"><b>{a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada'}</b><small>{hora(a.criado_at)}</small></div>
            {Icone.seta}
          </Link>
        ))}
        {vizinhas.length ? <div className="titulo-sec">Outras câmeras de {cam.site}</div> : null}
        {vizinhas.length ? (
          <div className="fita">
            {vizinhas.map((c) => (
              <Link key={c.id} to={`/vivo/${c.id}`} replace className="fita-item">
                <Foto caminho={`/api/termico/cameras/${c.id}/agora/termica`} alt={c.nome} recarregar={15000} />
                <span>{c.nome}</span>
              </Link>
            ))}
          </div>
        ) : null}
      </div>
    </>
  );
}
