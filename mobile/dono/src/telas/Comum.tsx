import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { hm, moeda, SEM_LOJA, useCaixas, useFiltro, type Cupom } from '../lib/pdv';
import { tocar, type Player } from '../lib/video';
import { Icone } from '../ui/pecas';

/** Folha de baixo para escolher a loja (vale em todas as telas). */
export function EscolherLoja({ aoFechar }: { aoFechar: () => void }) {
  const { loja, setLoja } = useFiltro();
  const caixas = useCaixas();
  const lojas = [...new Set((caixas.data || []).map((c) => c.site || SEM_LOJA))].sort((a, b) => a.localeCompare(b, 'pt-BR'));
  const escolher = (l: string) => { setLoja(l); aoFechar(); };
  return (
    <div className="fundo-folha">
      <div className="folha" role="dialog" aria-label="Escolher a loja">
        <div className="linha-entre"><strong className="t15">Loja</strong><button type="button" className="link-azul" onClick={aoFechar}>Fechar</button></div>
        <button type="button" className={`opcao ${!loja ? 'on' : ''}`} onClick={() => escolher('')}>{Icone.loja}Todas as lojas</button>
        {lojas.map((l) => <button type="button" key={l} className={`opcao ${loja === l ? 'on' : ''}`} onClick={() => escolher(l)}>{Icone.loja}{l}</button>)}
      </div>
    </div>
  );
}

/** Uma linha de cupom que abre o cupom com o video. */
export function LinhaCupom({ k, txt, valor, ts, tipo }: { k: Cupom; txt?: string; valor?: string; ts?: string; tipo?: string }) {
  const qs = new URLSearchParams();
  if (ts) qs.set('ts', ts);
  if (tipo) qs.set('tipo', tipo);
  return (
    <Link to={`/cupom/${encodeURIComponent(k.caixa_id)}/${k.dia}/${encodeURIComponent(k.cupom)}${qs.toString() ? `?${qs}` : ''}`} className="linha">
      <span className="hora">{hm(ts || k.aberto_em)}</span>
      <span className="col cresce"><b>{k.cupom} · {k.caixa}</b><small className="sub um">{k.operador}{txt ? ` · ${txt}` : ''}</small></span>
      <span className="col dir">{valor ? <b className="verm">{valor}</b> : null}<small className="sub">total {moeda(k.total_centavos)}</small></span>
      <span className="play-azul">{Icone.playCirc}</span>
    </Link>
  );
}

/** Tela de video: registra o stream quando `chave` muda e para ao sair. */
export function Tela({ chave, registrar, vivo, aoTocar, rotulo }:
  { chave: string; registrar: (() => Promise<string>) | null; vivo: boolean; aoTocar?: (v: HTMLVideoElement) => void; rotulo?: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [aviso, setAviso] = useState('');
  useEffect(() => {
    const v = ref.current;
    if (!v || !registrar) return;
    let p: Player | null = tocar(v, registrar, setAviso, vivo);
    aoTocar?.(v);
    return () => { p?.parar(); p = null; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave]);
  return (
    <div className="tela-video">
      <video ref={ref} className={registrar ? '' : 'sem'} autoPlay muted playsInline controls={!vivo && !!registrar} />
      {!registrar ? <span className="tela-aviso">{Icone.playCirc}<span>Toque em ▶ para ver o vídeo aqui</span></span>
        : aviso ? <span className="tela-aviso">{aviso}</span> : null}
      {rotulo ? <span className="tela-rotulo">{rotulo}</span> : null}
    </div>
  );
}
