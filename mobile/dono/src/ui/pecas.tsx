import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ErroApi } from '../lib/api';

const s = (d: ReactNode, tam = 20, extra = {}) => (
  <svg width={tam} height={tam} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...extra}>{d}</svg>
);

export const Icone = {
  casa: s(<><path d="m3 9 9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /><polyline points="9 22 9 12 15 12 15 22" /></>, 21),
  video: s(<><path d="m16 13 5.2 3.5a.5.5 0 0 0 .8-.4V7.9a.5.5 0 0 0-.8-.4L16 10.5" /><rect x="2" y="6" width="14" height="12" rx="2" /></>, 21),
  conferir: s(<><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></>, 21),
  trofeu: s(<><path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6" /><path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18" /><path d="M4 22h16" /><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22" /><path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22" /><path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" /></>, 21),
  sino: s(<><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></>, 21),
  voltar: s(<path d="m15 18-6-6 6-6" />, 22),
  dir: s(<path d="m9 18 6-6-6-6" />, 16),
  esq: s(<path d="m15 18-6-6 6-6" />, 16),
  baixo: s(<path d="m6 9 6 6 6-6" />, 14),
  busca: s(<><circle cx="11" cy="11" r="8" /><path d="m21 21-4.3-4.3" /></>, 18),
  calendario: s(<><rect width="18" height="18" x="3" y="4" rx="2" /><path d="M16 2v4" /><path d="M8 2v4" /><path d="M3 10h18" /></>, 15),
  loja: s(<><path d="m2 7 4.4-4.4A2 2 0 0 1 7.8 2h8.4a2 2 0 0 1 1.4.6L22 7" /><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8" /><path d="M2 7h20v3a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2z" /></>, 15),
  play: s(<polygon points="7 4 20 12 7 20 7 4" fill="currentColor" />, 16),
  playCirc: s(<><circle cx="12" cy="12" r="10" /><polygon points="10 8 16 12 10 16 10 8" /></>, 24),
  x: s(<><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6" /><path d="m9 9 6 6" /></>, 18),
  proibido: s(<><circle cx="12" cy="12" r="10" /><path d="m4.9 4.9 14.2 14.2" /></>, 18),
  pct: s(<><line x1="19" x2="5" y1="5" y2="19" /><circle cx="6.5" cy="6.5" r="2.5" /><circle cx="17.5" cy="17.5" r="2.5" /></>, 18),
  dinheiro: s(<><rect width="20" height="12" x="2" y="6" rx="2" /><circle cx="12" cy="12" r="2" /></>, 18),
  gaveta: s(<><rect width="20" height="5" x="2" y="3" rx="1" /><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8" /><path d="M10 12h4" /></>, 18),
  scan: s(<><path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" /><circle cx="12" cy="12" r="3" /></>, 18),
  relogio: s(<><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></>, 18),
  sair: s(<><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" x2="9" y1="12" y2="12" /></>, 18),
  monitor: s(<><rect width="20" height="14" x="2" y="3" rx="2" /><path d="M8 21h8" /><path d="M12 17v4" /></>, 18),
  olho: s(<><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" /></>, 21),
  equipe: s(<><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87" /><path d="M16 3.13a4 4 0 0 1 0 7.75" /></>, 21),
  mais: s(<><circle cx="12" cy="12" r="1" /><circle cx="19" cy="12" r="1" /><circle cx="5" cy="12" r="1" /></>, 21),
  teclado: s(<><rect width="20" height="16" x="2" y="4" rx="2" /><path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M8 12h.01M12 12h.01M16 12h.01M7 16h10" /></>, 18),
  ok: s(<><circle cx="12" cy="12" r="10" /><path d="m9 12 2 2 4-4" /></>, 18),
  conta: s(<><path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z" /><path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8" /></>, 18),
  denovo: s(<><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" /><path d="M3 3v5h5" /></>, 16),
};

export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return <div className="carregando"><span className="giro" />{texto}</div>;
}

export function Vazio({ texto }: { texto: string }) {
  return <p className="vazio">{texto}</p>;
}

export function Erro({ erro, aoTentar }: { erro: unknown; aoTentar?: () => void }) {
  const m = erro instanceof ErroApi ? erro.message : (erro as Error)?.message || 'Algo deu errado.';
  return (
    <div className="erro-caixa">
      <p>{m}</p>
      {aoTentar ? <button type="button" className="btn2" onClick={aoTentar}>Tentar de novo</button> : null}
    </div>
  );
}

/** Cabecalho branco com voltar (telas de detalhe). */
export function Cabecalho({ titulo, sub, direita }: { titulo: string; sub?: string; direita?: ReactNode }) {
  const ir = useNavigate();
  return (
    <header className="cab-simples">
      <button type="button" className="voltar" aria-label="Voltar" onClick={() => ir(-1)}>{Icone.voltar}</button>
      <div className="cab-txt"><strong>{titulo}</strong>{sub ? <small>{sub}</small> : null}</div>
      {direita}
    </header>
  );
}

/** Icone em fundo da propria cor. */
export function Ico({ cor, children }: { cor: 'azul' | 'verde' | 'verm' | 'ambar' | 'ciano'; children: ReactNode }) {
  return <span className={`ico ico-${cor}`}>{children}</span>;
}

export function Pos({ n, tipo }: { n: number; tipo: 'bom' | 'ruim' | '' }) {
  return <span className={`pos ${tipo}`}>{n}º</span>;
}
