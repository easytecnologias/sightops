import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';

/* Pecas do desenho "SightOps Mobile": cartao de 14px, mosaico de numeros sem
   icone, item de lista com ponto de estado e pilula de contagem. */

const P = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       dangerouslySetInnerHTML={{ __html: d }} />
);

export const Icone = {
  casa: P('<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>'),
  camera: P('<rect x="3" y="6" width="13" height="12" rx="2"/><path d="m16 10 5-3v10l-5-3"/>'),
  implantar: P('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z"/>'),
  alerta: P('<path d="M6 16v-5a6 6 0 0 1 12 0v5"/><path d="M4 16h16v3H4z"/><path d="M12 2v2"/>'),
  rede: P('<circle cx="12" cy="5" r="2"/><circle cx="5" cy="19" r="2"/><circle cx="19" cy="19" r="2"/><path d="M12 7v5m0 0-6 5m6-5 6 5"/>'),
  seta: P('<path d="m9 6 6 6-6 6"/>'),
  baixo: P('<path d="m6 9 6 6 6-6"/>'),
  busca: P('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  atualizar: P('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>'),
  aviso: P('<circle cx="12" cy="12" r="9"/><path d="M12 8.5v5"/><path d="M12 16.8h.01"/>'),
  pin: P('<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z"/><circle cx="12" cy="10" r="2.4"/>'),
  gravador: P('<rect x="3" y="5" width="18" height="6" rx="1.6"/><rect x="3" y="13" width="18" height="6" rx="1.6"/><path d="M6.5 8h.01M6.5 16h.01"/>'),
  onu: P('<path d="M5 12a7 7 0 0 1 14 0"/><path d="M8.5 12a3.5 3.5 0 0 1 7 0"/><circle cx="12" cy="17" r="1.6"/>'),
  raio: P('<path d="M13 3 5 13.5h6L10.5 21 19 10.5h-6Z"/>'),
  engrenagem: P('<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M21 12h-2.5M5.5 12H3"/>'),
  volta: P('<path d="m15 6-6 6 6 6"/>'),
  ok: P('<path d="M5 12l5 5 9-10"/>'),
  x: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  olho: P('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  olhoFechado: P('<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 4.2-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
  apagar: P('<path d="M9 5h11v14H9l-6-7z"/><path d="m12 9 5 6M17 9l-5 6"/>'),
  cadeado: P('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  predio: P('<path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 21v-5h6v5"/>'),
  switch: P('<rect x="3" y="8" width="18" height="8" rx="1.6"/><path d="M7 12h.01M11 12h.01M15 12h.01"/>'),
  mapa: P('<path d="M9 4 3 6v14l6-2 6 2 6-2V4l-6 2z"/><path d="M9 4v14M15 6v14"/>'),
  sair: P('<path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3"/><path d="M10 16 6 12l4-4"/><path d="M6 12h9"/>'),
  olt: P('<path d="M4.9 16.1C1 12.2 1 5.8 4.9 1.9"/><path d="M7.8 4.7a6.14 6.14 0 0 0-.8 7.5"/><circle cx="12" cy="9" r="2"/><path d="M16.2 4.8c2 2 2.26 5.11.8 7.47"/><path d="M19.1 1.9a9.96 9.96 0 0 1 0 14.1"/><path d="M9.5 18h5"/><path d="m8 22 4-11 4 11"/>'),
  caixa: P('<path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/>'),
  conector: P('<path d="M12 22v-5"/><path d="M9 8V2"/><path d="M15 8V2"/><path d="M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8Z"/>'),
  porta: P('<path d="M13 4h3a2 2 0 0 1 2 2v14"/><path d="M2 20h3"/><path d="M13 20h9"/><path d="M10 12v.01"/><path d="M13 4.562v16.157a1 1 0 0 1-1.242.97L5 20V5.562a2 2 0 0 1 1.515-1.94l4-1A2 2 0 0 1 13 4.561Z"/>'),
  equipamentos: P('<rect width="20" height="8" x="2" y="2" rx="2"/><rect width="20" height="8" x="2" y="14" rx="2"/><path d="M6 6h.01"/><path d="M6 18h.01"/>'),
  mais: P('<path d="M5 12h14"/><path d="M12 5v14"/>'),
  ir: P('<polygon points="3 11 22 2 13 21 11 13 3 11"/>'),
  etiqueta: P('<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>'),
  reiniciar: P('<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>'),
  rota: P('<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>'),
  camadas: P('<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>'),
  triangulo: P('<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>'),
};

export function Cartao({ children }: { children: ReactNode }) {
  return <section className="cartao">{children}</section>;
}

export function Bloco(
  { rotulo, numero, pes, onClick }:
  { rotulo: string; numero: ReactNode; pes?: ReactNode; onClick?: () => void },
) {
  const miolo = (
    <>
      <span className="rot">{rotulo}</span>
      <span className="num">{numero}</span>
      {pes ? <span className="pes">{pes}</span> : null}
    </>
  );
  return onClick
    ? <button type="button" className="bloco" onClick={onClick}>{miolo}</button>
    : <div className="bloco">{miolo}</div>;
}

export function Item(
  { ponto, icone, titulo, sub, direita, onClick }:
  { ponto?: 'vermelho' | 'ambar' | 'verde'; icone?: ReactNode; titulo: string;
    sub?: string; direita?: ReactNode; onClick?: () => void },
) {
  const cores = { vermelho: 'var(--danger)', ambar: 'var(--amber)', verde: 'var(--primary)' };
  const miolo = (
    <>
      {ponto ? <span className="ponto" style={{ background: cores[ponto] }} /> : null}
      {icone ? <span className="ic">{icone}</span> : null}
      <span className="corpo">
        <span className="t">{titulo}</span>
        {sub ? <span className="s mono">{sub}</span> : null}
      </span>
      {direita}
    </>
  );
  // Item que faz algo e <button>; item que so informa e <div>. Um <div> com
  // onClick o teclado e o leitor de tela nunca alcancam.
  return onClick
    ? <button type="button" className="item" onClick={onClick}>{miolo}</button>
    : <div className="item">{miolo}</div>;
}

export function Pilula({ cor, children }: { cor: 'vermelha' | 'ambar' | 'verde' | 'cinza'; children: ReactNode }) {
  return <span className={`pilula ${cor}`}>{children}</span>;
}

export function Vazio({ children }: { children: ReactNode }) {
  return <div className="vazio">{children}</div>;
}
export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return <div className="carregando">{texto}</div>;
}

export function Titulo({ titulo, sub }: { titulo: string; sub?: string }) {
  return (
    <div>
      <h1 className="titulo-tela">{titulo}</h1>
      {sub ? <p className="sub-tela">{sub}</p> : null}
    </div>
  );
}

/**
 * Procedencia do dado.
 *
 * Toda tela de consulta diz se o que esta na frente veio agora ou da copia
 * guardada, e de quando. Dado velho sem aviso e pior que tela vazia: o tecnico
 * decide com o passado sem saber que esta decidindo com o passado.
 */
export function Procedencia(
  { buscando, atualizadoEm, online }:
  { buscando: boolean; atualizadoEm?: number; online: boolean },
) {
  if (buscando) return <span className="selo cinza">buscando…</span>;
  if (!atualizadoEm) return <span className="selo cinza">sem dados</span>;
  if (online && Date.now() - atualizadoEm < 120_000) return <span className="selo verde">agora</span>;
  const q = new Date(atualizadoEm).toLocaleString('pt-BR', {
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit',
  });
  return <span className="selo ambar">{online ? `de ${q}` : `no aparelho · ${q}`}</span>;
}

/** Lente com o ponto verde de "no ar": o icone do app. */
export function Logo({ tamanho = 64 }: { tamanho?: number }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 100 100" aria-hidden="true">
      <circle cx="50" cy="52" r="24" fill="none" stroke="#ffffff" strokeWidth="7" />
      <circle cx="50" cy="52" r="9" fill="#3fd09a" />
      <path d="M70 19a36 36 0 0 1 13 15" fill="none" stroke="#3fd09a" strokeWidth="6" strokeLinecap="round" />
    </svg>
  );
}

export function iniciais(nome: string): string {
  const p = String(nome || '').trim().split(/\s+/).filter(Boolean);
  if (!p.length) return '?';
  return ((p[0][0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase();
}

/** Folha de baixo com titulo e X. O fundo nao fecha ao toque (so o X). */
export function Folha(
  { titulo, sub, aoFechar, children }:
  { titulo: string; sub?: string; aoFechar: () => void; children: ReactNode },
) {
  return (
    <>
      <div className="folha-fundo" />
      <aside className="folha" role="dialog" aria-label={titulo}>
        <div className="folha-topo">
          <div><h2>{titulo}</h2>{sub ? <p>{sub}</p> : null}</div>
          <button type="button" className="fechar" aria-label="Fechar" onClick={aoFechar}>{Icone.x}</button>
        </div>
        {children}
      </aside>
    </>
  );
}

type Toast = { texto: string; erro?: boolean } | null;
const CtxToast = createContext<(texto: string, erro?: boolean) => void>(() => {});
export function ProvedorToast({ children }: { children: ReactNode }) {
  const [t, setT] = useState<Toast>(null);
  const timer = useRef<number>();
  const mostrar = useCallback((texto: string, erro = false) => {
    setT({ texto, erro });
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setT(null), erro ? 6000 : 3500);
  }, []);
  return (
    <CtxToast.Provider value={mostrar}>
      {children}
      {t ? <div className={`toast${t.erro ? ' erro' : ''}`} role="status">{t.texto}</div> : null}
    </CtxToast.Provider>
  );
}
export const useToast = () => useContext(CtxToast);
