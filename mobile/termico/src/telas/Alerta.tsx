import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { hora, num, useAlertas, useCameras, useResponder, type Alerta } from '../lib/termico';
import { Carregando, Erro, Foto, Icone, Video } from '../ui/pecas';
import { formatoDe, VideoVivo } from '../ui/VideoVivo';

const MOTIVOS: [string, string][] = [['animal', 'Animal'], ['sol', 'Reflexo do sol'], ['equipe', 'Equipe da usina'], ['mato', 'Vento ou mato'], ['veiculo', 'Veículo'], ['outro', 'Outro']];

function FolhaFalso({ a, aoFechar }: { a: Alerta; aoFechar: () => void }) {
  const [motivo, setMotivo] = useState('');
  const [comentario, setComentario] = useState('');
  const responder = useResponder();
  return (
    <div className="fundo-folha">
      <section className="folha" role="dialog" aria-label="Por que foi falso alarme?">
        <span className="alca" />
        <div><h2>Por que foi falso alarme?</h2><small>{a.camera_nome} · {a.site} · {hora(a.criado_at)}</small></div>
        <div className="motivos">
          {MOTIVOS.map(([k, nome]) => (
            <button key={k} type="button" className={motivo === k ? 'on' : ''} aria-pressed={motivo === k} onClick={() => setMotivo(k)}>{nome}</button>
          ))}
        </div>
        <label className="campo"><span>Comentário (opcional)</span>
          <input maxLength={500} value={comentario} onChange={(e) => setComentario(e.target.value)} /></label>
        {responder.error ? <p className="msg-erro">{(responder.error as Error).message}</p> : null}
        <div className="dois">
          <button type="button" className="btn2" onClick={aoFechar}>Cancelar</button>
          <button type="button" className="btn" disabled={!motivo || responder.isPending}
            onClick={() => responder.mutate({ id: a.id, tipo: 'falso', motivo, comentario }, { onSuccess: aoFechar })}>Confirmar</button>
        </div>
      </section>
    </div>
  );
}

function Cronologia({ a }: { a: Alerta }) {
  const passos: [string, string, string][] = [[hora(a.criado_at), a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada', 'al']];
  if (a.situacao !== 'novo') passos.push([hora(a.visto_at), `${a.situacao === 'falso' ? 'Falso alarme' : 'Ciente'} por ${a.visto_por || '—'}`, 'ok']);
  return (
    <section className="cartao crono">
      {passos.map(([h, t, c]) => <div key={t} className="ev"><time>{h}</time><s><i className={c} /></s><b>{t}</b></div>)}
      {a.comentario ? <small>“{a.comentario}”</small> : null}
    </section>
  );
}

export function AlertaTela() {
  const { id } = useParams();
  const nav = useNavigate();
  const al = useAlertas();
  const cams = useCameras();
  const responder = useResponder();
  const [modo, setModo] = useState<'termica' | 'colorida'>('termica');
  const [falso, setFalso] = useState(false);
  const a = al.data?.alertas.find((x) => x.id === id);

  if (al.isLoading) return <Carregando />;
  if (al.error) return <Erro erro={al.error} />;
  if (!a) return <div className="vazio">Alerta não encontrado. <Link to="/">Voltar</Link></div>;

  const cam = cams.data?.cameras.find((c) => c.id === a.camera_id);
  const teste = !!a.mancha?.teste;
  const caixa = a.mancha?.caixa;
  const novo = a.situacao === 'novo';
  return (
    <>
      <div className="vivo">
        <div className={`vivo-quadro ${modo === 'termica' ? 'ferro' : ''}`} style={{ aspectRatio: formatoDe(modo) }}>
          {cam ? <VideoVivo cam={cam} tipo={modo} /> : <Foto caminho={modo === 'termica' ? a.fotos.termico : a.fotos.visivel} alt="Imagem do alarme" />}
          {caixa && modo === 'termica' ? <span className="mira" style={{ left: `${(caixa[0] - .02) * 100}%`, top: `${(caixa[1] - .02) * 100}%`, width: `${(caixa[2] + .04) * 100}%`, height: `${(caixa[3] + .04) * 100}%` }}><i /><i /><i /><i /></span> : null}
          <span className="hu a3">{a.camera_nome}</span>
        </div>
        <div className="vivo-topo">
          <button type="button" className="bt-redondo escuro" aria-label="Voltar" onClick={() => nav(-1)}>{Icone.voltar}</button>
          <div className="alternar" role="tablist" aria-label="Imagem">
            <button type="button" role="tab" aria-selected={modo === 'termica'} className={modo === 'termica' ? 'on' : ''} onClick={() => setModo('termica')}>Térmica</button>
            <button type="button" role="tab" aria-selected={modo === 'colorida'} className={modo === 'colorida' ? 'on' : ''} onClick={() => setModo('colorida')}>Colorida</button>
          </div>
        </div>
      </div>
      <section className={`fx reto ${novo ? 'al' : ''}`}>
        <div className="est"><span className="pul pequeno"><i /></span><div><b>{teste ? 'Alarme de teste' : 'Pessoa detectada'}</b><small>{a.site} · {hora(a.criado_at)}{novo ? '' : a.situacao === 'falso' ? ' · falso alarme' : ' · ciente'}</small></div></div>
      </section>
      <div className={`pagina ${novo ? 'com-acoes' : ''}`}>
        {teste ? null : (
          <div className="tres">
            <div className="m"><span>Mancha</span><b>{num(a.temp_c)} °C</b></div>
            <div className="m"><span>Fundo</span><b>{num(a.fundo_c)} °C</b></div>
            <div className="m"><span>Contraste</span><b>{a.mancha?.contraste == null ? '—' : `${num(a.mancha.contraste)} °C`}</b></div>
          </div>
        )}
        <Cronologia a={a} />
        <div className="titulo-sec">Momento do disparo</div>
        <div className="dois-fotos">
          <div className="tl ferro"><Foto caminho={a.fotos.termico} alt="Imagem térmica do alarme" />{caixa ? <span className="caixa" style={{ left: `${caixa[0] * 100}%`, top: `${caixa[1] * 100}%`, width: `${caixa[2] * 100}%`, height: `${caixa[3] * 100}%` }} /> : null}</div>
          <div className="tl"><Foto caminho={a.fotos.visivel} alt="Imagem colorida do alarme" /></div>
        </div>
        {a.videos?.termico ? <Video caminho={a.videos.termico} legenda="Térmica, depois do alarme" /> : null}
        {a.videos?.visivel ? <Video caminho={a.videos.visivel} legenda="Colorida, depois do alarme" /> : null}
        {responder.error ? <p className="msg-erro">{(responder.error as Error).message}</p> : null}
      </div>
      {novo ? (
        <div className="acoes">
          <button type="button" className="btn2" onClick={() => setFalso(true)}>Falso alarme</button>
          <button type="button" className="btn destaque-bt" disabled={responder.isPending} onClick={() => responder.mutate({ id: a.id, tipo: 'ciente' })}>{responder.isPending ? 'Salvando…' : 'Dar Ciente'}</button>
        </div>
      ) : null}
      {falso ? <FolhaFalso a={a} aoFechar={() => setFalso(false)} /> : null}
    </>
  );
}
