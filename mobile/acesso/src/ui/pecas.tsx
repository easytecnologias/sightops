import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { imagem } from '../lib/api';
import { iniciais } from '../lib/cpf';

/* Icones de traco (mesmos do desenho). */
const P = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       dangerouslySetInnerHTML={{ __html: d }} />
);

export const Icone = {
  casa: P('<path d="M3 10.5 12 3l9 7.5V21h-6v-6H9v6H3z"/>'),
  pessoas: P('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6 6 0 0 1 3.5 6"/>'),
  mais: P('<path d="M12 5v14M5 12h14"/>'),
  conversa: P('<path d="M4 5h16v11H9l-5 4z"/>'),
  cracha: P('<rect x="4" y="3" width="16" height="18" rx="2"/><circle cx="12" cy="10" r="3"/><path d="M8 17a4 4 0 0 1 8 0"/>'),
  seta: P('<path d="m9 6 6 6-6 6"/>'),
  baixo: P('<path d="m6 9 6 6 6-6"/>'),
  volta: P('<path d="m15 6-6 6 6 6"/>'),
  x: P('<path d="M6 6l12 12M18 6 6 18"/>'),
  ok: P('<path d="M5 12l5 5 9-10"/>'),
  busca: P('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  aviso: P('<circle cx="12" cy="12" r="9"/><path d="M12 8.5v5"/><path d="M12 16.8h.01"/>'),
  camera: P('<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>'),
  galeria: P('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-8 8"/>'),
  virar: P('<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><path d="M9.5 13.5a2.5 2.5 0 0 0 4.6 1.3M14.5 12.5a2.5 2.5 0 0 0-4.6-1.3"/>'),
  pessoa: P('<circle cx="12" cy="9" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  predio: P('<path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 21v-5h6v5"/>'),
  olho: P('<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>'),
  olhoFechado: P('<path d="M3 3l18 18"/><path d="M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.2M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.6 9.6 0 0 0 4.2-1"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'),
  apagar: P('<path d="M9 5h11v14H9l-6-7z"/><path d="m12 9 5 6M17 9l-5 6"/>'),
  sair: P('<path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3"/><path d="M10 16 6 12l4-4"/><path d="M6 12h9"/>'),
  cadeado: P('<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>'),
  porta: P('<path d="M5 21V4a1 1 0 0 1 1-1h12a1 1 0 0 1 1 1v17"/><path d="M3 21h18"/><path d="M14 12h.01"/>'),
};

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

const CORES_AV = [
  ['#e7f5ff', '#174f86'], ['#f3e8ff', '#6b2fa3'], ['#fff4e6', '#a34700'], ['#dff5ec', '#06694b'], ['#fde8ef', '#9c2350'],
];
function corDe(nome: string) {
  let h = 0;
  for (const c of nome) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return CORES_AV[h % CORES_AV.length];
}

/* Fotos ja baixadas nesta sessao: a lista de pessoas rola e volta sem pedir de novo. */
const _fotos = new Map<string, string>();

/** Avatar: a foto do rosto quando existe, senao as iniciais. */
export function Avatar(
  { nome, pessoaId, temFoto, versao, pequeno, semFoto }:
  { nome: string; pessoaId?: string; temFoto?: boolean; versao?: string; pequeno?: boolean; semFoto?: boolean },
) {
  const chave = pessoaId && temFoto ? `${pessoaId}|${versao || ''}` : '';
  const [url, setUrl] = useState<string | null>(chave ? _fotos.get(chave) ?? null : null);
  useEffect(() => {
    if (!chave || _fotos.has(chave)) { setUrl(chave ? _fotos.get(chave) ?? null : null); return; }
    let vivo = true;
    imagem(`/api/access-control/people/${encodeURIComponent(pessoaId!)}/face-photo`)
      .then((b) => { const u = URL.createObjectURL(b); _fotos.set(chave, u); if (vivo) setUrl(u); })
      .catch(() => { /* sem foto ou sem rede: ficam as iniciais */ });
    return () => { vivo = false; };
  }, [chave, pessoaId]);

  const cls = `av${pequeno ? ' p' : ''}`;
  if (semFoto && !url) return <span className={`${cls} sem`} aria-hidden="true">+</span>;
  if (url) return <span className={cls}><img src={url} alt="" /></span>;
  const [fundo, letra] = corDe(nome || '?');
  return <span className={cls} style={{ background: fundo, color: letra }} aria-hidden="true">{nome ? iniciais(nome) : '?'}</span>;
}

export function Folha(
  { titulo, sub, aoFechar, children }:
  { titulo: string; sub?: string; aoFechar: () => void; children: ReactNode },
) {
  return (
    <>
      {/* Fundo nao fecha ao toque: so o X (quem digitava perdia o que escreveu). */}
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

export function Vazio({ children }: { children: ReactNode }) {
  return <div className="vazio">{children}</div>;
}
export function Carregando({ texto = 'Carregando…' }: { texto?: string }) {
  return <div className="carregando">{texto}</div>;
}

/* Aviso rapido no rodape (salvou, falhou). */
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

/** Hora curta de um texto "AAAA-MM-DD HH:MM:SS" (hora local do servidor). */
export function hora(txt: string): string {
  const m = /(\d{2}):(\d{2})/.exec(String(txt || '').slice(10));
  return m ? `${m[1]}:${m[2]}` : '';
}
