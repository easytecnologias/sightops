import { useEffect, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { chaveDa, siteDa, tituloDa, useCameras, estadoDa } from '../lib/dados';
import { tocar, type Player } from '../lib/aovivo';
import { useOnline } from '../lib/rede';
import { Carregando, Cartao, Icone, Vazio } from '../ui/pecas';

/* 11 · Camera ao vivo */
export function AoVivo() {
  const { chave = '' } = useParams();
  const cams = useCameras();
  const online = useOnline();
  const ir = useNavigate();
  const video = useRef<HTMLVideoElement>(null);
  const caixa = useRef<HTMLDivElement>(null);
  const player = useRef<Player | null>(null);
  const [qualidade, setQualidade] = useState<0 | 1>(1);   // 1 = SD (substream), 0 = HD
  const [estado, setEstado] = useState('Conectando…');
  const [senha, setSenha] = useState('');
  const [comSenha, setComSenha] = useState<string | null>(null);
  // Tela cheia do proprio app, nao a do navegador: no WebView do Android a
  // requestFullscreen deixava os botoes em cima da barra de navegacao do
  // sistema (os toques nao chegavam) e o voltar nao saia dela.
  const [cheia, setCheia] = useState(false);
  const [girada, setGirada] = useState(false);

  const cam = (cams.data ?? []).find((c) => `${c.ip ?? ''}|${c.mac ?? ''}` === chave || chaveDa(c) === chave);

  useEffect(() => {
    if (!cam?.ip || !video.current || !online) return;
    player.current = tocar(video.current, {
      ip: cam.ip, conector: cam.remote_connector_id || cam.connector_id || '', fabricante: cam.fabricante, modelo: cam.modelo,
      usuario: comSenha !== null ? 'admin' : '', senha: comSenha ?? '',
    }, qualidade, setEstado);
    return () => { player.current?.parar(); player.current = null; };
    // Qualidade troca sem recriar (trocarQualidade); senha nova recria.
  }, [cam?.ip, online, comSenha]); // eslint-disable-line react-hooks/exhaustive-deps

  function mudarQualidade(q: 0 | 1) { setQualidade(q); player.current?.trocarQualidade(q); }

  // Entrar poe um passo no historico: o voltar do Android (que volta o
  // historico do WebView) sai da tela cheia em vez de sair da camera.
  function entrarTelaCheia() {
    window.history.pushState({ telaCheia: true }, '');
    setCheia(true);
  }
  function sairTelaCheia() {
    if ((window.history.state as { telaCheia?: boolean } | null)?.telaCheia) window.history.back();
    else { setCheia(false); setGirada(false); }
  }
  useEffect(() => {
    if (!cheia) return;
    const aoVoltar = () => { setCheia(false); setGirada(false); };
    const aoTeclar = (ev: KeyboardEvent) => { if (ev.key === 'Escape') sairTelaCheia(); };
    window.addEventListener('popstate', aoVoltar);
    window.addEventListener('keydown', aoTeclar);
    document.body.classList.add('com-tela-cheia');
    return () => {
      window.removeEventListener('popstate', aoVoltar);
      window.removeEventListener('keydown', aoTeclar);
      document.body.classList.remove('com-tela-cheia');
    };
  }, [cheia]); // eslint-disable-line react-hooks/exhaustive-deps

  if (cams.isPending && !cams.data) return <Carregando />;
  if (!cam) return <Cartao><Vazio>Câmera não encontrada.</Vazio></Cartao>;
  const e = estadoDa(cam);

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir(-1)}>{Icone.volta}Voltar</button>
      <div className="linha-topo">
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 className="titulo-tela">{tituloDa(cam)}</h1>
          <p className="sub-tela mono">{[cam.ip, [cam.fabricante, cam.modelo].filter(Boolean).join(' ')].filter(Boolean).join(' · ')}</p>
        </div>
        <span className={`selo ${e === 'online' ? 'verde' : e === 'offline' ? 'ambar' : 'cinza'}`}>{e === 'online' ? 'no ar' : e === 'offline' ? 'fora do ar' : 'sem leitura'}</span>
      </div>

      <div className={`video-caixa${cheia ? ' cheia' : ''}${cheia && girada ? ' girada' : ''}`} ref={caixa}>
        <video ref={video} playsInline muted autoPlay />
        {estado && estado !== 'senha' ? <div className="video-estado">{online ? estado : 'Sem sinal: o vídeo precisa de internet agora.'}</div> : null}
        {!estado ? <span className="ao-vivo"><i />AO VIVO</span> : null}
        {cheia ? (
          // Na tela cheia tudo fica no alto, longe da barra de navegacao do Android.
          <div className="video-topo">
            <button type="button" className="video-sair" onClick={sairTelaCheia}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>Sair
            </button>
            <span className="video-qualidade" role="group" aria-label="Qualidade">
              <button type="button" aria-pressed={qualidade === 1} onClick={() => mudarQualidade(1)}>SD</button>
              <button type="button" aria-pressed={qualidade === 0} onClick={() => mudarQualidade(0)}>HD</button>
            </span>
            <button type="button" className="video-sair" aria-pressed={girada} onClick={() => setGirada(!girada)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>{girada ? 'Em pé' : 'Deitar'}
            </button>
          </div>
        ) : (
          <>
            <span className="video-qualidade" role="group" aria-label="Qualidade">
              <button type="button" aria-pressed={qualidade === 1} onClick={() => mudarQualidade(1)}>SD</button>
              <button type="button" aria-pressed={qualidade === 0} onClick={() => mudarQualidade(0)}>HD</button>
            </span>
            <button type="button" className="video-btn" aria-label="Tela cheia" onClick={entrarTelaCheia}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /></svg>
            </button>
          </>
        )}
      </div>
      <p className="sub-tela">{qualidade === 1 ? 'Qualidade baixa: gasta pouco dado no 4G. HD com um toque.' : 'HD gasta bem mais dado; em link fraco pode travar.'}</p>

      {estado === 'senha' ? (
        <Cartao>
          <h2>Senha da câmera</h2>
          <p className="sub-h2">O servidor não tem a senha certa desta câmera.</p>
          <div className="form-cartao">
            <div className="campo"><label htmlFor="sv">Senha (usuário admin)</label>
              <div className="caixa"><input id="sv" type="password" value={senha} onChange={(ev) => setSenha(ev.target.value)} autoComplete="off" /></div></div>
            <button type="button" className="btn" disabled={!senha} onClick={() => setComSenha(senha)}>Ver ao vivo</button>
          </div>
        </Cartao>
      ) : null}

      <Cartao>
        <div className="ficha">
          <div className="ficha-linha"><span className="ficha-rot">Gravador</span><span className="ficha-val mono">{cam.recorder_host ? `${cam.recorder_host}${cam.recorder_channel ? ` · canal ${cam.recorder_channel}` : ''}` : 'não vinculada'}</span></div>
          <div className="ficha-linha"><span className="ficha-rot">Site</span><span className="ficha-val">{siteDa(cam) || '—'}</span></div>
        </div>
      </Cartao>
      <button type="button" className="btn2" onClick={() => ir(`/cameras/${chaveDa(cam)}`)}>{Icone.engrenagem}Ficha e ajustes da câmera</button>
    </>
  );
}
