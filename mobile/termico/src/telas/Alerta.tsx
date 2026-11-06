import { useRef, useState, type PointerEvent } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { hora, num, useAlertas, useResponder, type Alerta } from '../lib/termico';
import { Carregando, Erro, Foto, Icone } from '../ui/pecas';

const MOTIVOS: [string, string][] = [['animal', 'Animal'], ['sol', 'Reflexo do sol'], ['equipe', 'Equipe da usina'], ['mato', 'Vento ou mato'], ['veiculo', 'Veículo'], ['outro', 'Outro']];

function Regua({ a }: { a: Alerta }) {
  if (a.temp_c === null || a.fundo_c === null) return null;
  const min = Math.floor(Math.min(a.temp_c, a.fundo_c) / 10) * 10 - 10;
  const max = Math.ceil(Math.max(a.temp_c, a.fundo_c) / 10) * 10 + 10;
  const pos = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  const fria = a.temp_c < a.fundo_c;
  return (
    <section className="cartao regua" aria-label="Régua de calor">
      <div className="linha"><span className="titulo-sec">Régua de calor</span><b>diferença <em>{num(Math.abs(a.dif_c ?? 0))} °C</em></b></div>
      <div className="regua-area">
        <div className="regua-barra" />
        <div className="pino pessoa" style={{ left: pos(a.temp_c) }}><span>Pessoa {num(a.temp_c, 0)} °C</span><i /></div>
        <div className="pino fundo" style={{ left: pos(a.fundo_c) }}><span>Fundo {num(a.fundo_c, 0)} °C</span><i /></div>
        <div className="regua-fim"><span>{min} °C</span><span>{max} °C</span></div>
      </div>
      <small>{fria ? 'Ao sol, a pessoa aparece mais fria que o chão.' : 'A pessoa aparece mais quente que o fundo.'}</small>
    </section>
  );
}

function Deslizar({ aoConfirmar, ocupado }: { aoConfirmar: () => void; ocupado: boolean }) {
  const trilho = useRef<HTMLDivElement>(null);
  const [x, setX] = useState(0);
  const inicio = useRef<number | null>(null);
  const curso = () => (trilho.current ? trilho.current.clientWidth - 56 : 1);
  function move(e: PointerEvent) {
    if (inicio.current === null) return;
    setX(Math.max(0, Math.min(curso(), e.clientX - inicio.current)));
  }
  function solta() {
    if (inicio.current === null) return;
    inicio.current = null;
    if (x >= curso() * 0.85) aoConfirmar();
    setX(0);
  }
  return (
    <div className="deslizar" ref={trilho}>
      <span>{ocupado ? 'Salvando…' : 'Deslize para dar Ciente'}</span>
      <button type="button" className="botao-d" style={{ transform: `translateX(${x}px)` }} aria-label="Dar Ciente"
        onPointerDown={(e) => { inicio.current = e.clientX - x; e.currentTarget.setPointerCapture(e.pointerId); }}
        onPointerMove={move} onPointerUp={solta} onPointerCancel={() => { inicio.current = null; setX(0); }}
        onKeyDown={(e) => { if (e.key === 'Enter') aoConfirmar(); }}>{Icone.seta}</button>
    </div>
  );
}

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

export function AlertaTela() {
  const { id } = useParams();
  const nav = useNavigate();
  const al = useAlertas();
  const responder = useResponder();
  const [modo, setModo] = useState<'termico' | 'visivel'>('termico');
  const [falso, setFalso] = useState(false);
  const a = al.data?.alertas.find((x) => x.id === id);

  if (al.isLoading) return <Carregando />;
  if (al.error) return <Erro erro={al.error} />;
  if (!a) return <div className="vazio">Alerta não encontrado. <Link to="/">Voltar</Link></div>;

  const c = a.mancha?.caixa;
  const caminho = modo === 'termico' ? a.fotos.termico : a.fotos.visivel;
  return (
    <>
      <div className="alerta-foto">
        <Foto caminho={caminho} alt={modo === 'termico' ? 'Imagem térmica do alerta' : 'Imagem colorida do alerta'} />
        {c ? <span className="caixa" style={{ left: `${c[0] * 100}%`, top: `${c[1] * 100}%`, width: `${c[2] * 100}%`, height: `${c[3] * 100}%` }} /> : null}
        <div className="alerta-barra">
          <button type="button" className="bt-redondo" aria-label="Voltar" onClick={() => nav(-1)}>{Icone.voltar}</button>
          <div className="alternar" role="tablist">
            <button type="button" role="tab" aria-selected={modo === 'termico'} className={modo === 'termico' ? 'on' : ''} onClick={() => setModo('termico')}>Térmica</button>
            <button type="button" role="tab" aria-selected={modo === 'visivel'} className={modo === 'visivel' ? 'on' : ''} onClick={() => setModo('visivel')}>Colorida</button>
          </div>
        </div>
      </div>
      <div className="pagina folha-alerta">
        <div className="linha">
          <div className="cresce"><h1>{a.mancha?.teste ? 'Alarme de teste' : 'Pessoa detectada'}</h1><small>{a.camera_nome} · {a.site} · {hora(a.criado_at)}</small></div>
          {a.situacao === 'novo' ? <span className="etq alerta">Novo</span> : <span className={`etq ${a.situacao === 'falso' ? 'aviso' : 'ok'}`}>{a.situacao === 'falso' ? 'Falso alarme' : 'Ciente'}</span>}
        </div>
        <Regua a={a} />
        <Link className="btn2" to={`/vivo/${a.camera_id}`}>Ver ao vivo</Link>
        {a.situacao === 'novo' ? (
          <>
            <Deslizar ocupado={responder.isPending} aoConfirmar={() => responder.mutate({ id: a.id, tipo: 'ciente' })} />
            <button type="button" className="btn2 aviso" onClick={() => setFalso(true)}>Falso alarme</button>
            {responder.error ? <p className="msg-erro">{(responder.error as Error).message}</p> : null}
          </>
        ) : (
          <div className="cartao resposta"><small>Respondido por</small><b>{a.visto_por || '—'} às {hora(a.visto_at)}</b>
            {a.comentario ? <small>“{a.comentario}”</small> : null}</div>
        )}
      </div>
      {falso ? <FolhaFalso a={a} aoFechar={() => setFalso(false)} /> : null}
    </>
  );
}
