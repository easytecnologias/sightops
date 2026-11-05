import { useEffect, useState, type ReactNode } from 'react';
import { fotoUrl } from '../lib/api';
import { MARCA } from '../lib/marca';

const S = ({ children, tam = 22 }: { children: ReactNode; tam?: number }) => (
  <svg width={tam} height={tam} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{children}</svg>
);

export const Icone = {
  casa: <S><path d="M3 10.5 12 3l9 7.5" /><path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" /></S>,
  video: <S><rect x="2.5" y="6" width="13" height="12" rx="3" /><path d="M15.5 10.5 21 7.5v9l-5.5-3" /></S>,
  sol: <S><circle cx="12" cy="12" r="4" /><path d="M12 2v2.5M12 19.5V22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2 12h2.5M19.5 12H22M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8" /></S>,
  conta: <S><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></S>,
  voltar: <S><path d="M15 18l-6-6 6-6" /></S>,
  baixo: <S tam={16}><path d="M6 9l6 6 6-6" /></S>,
  fechar: <S tam={16}><path d="M6 6l12 12M18 6 6 18" /></S>,
  escudo: <S><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /><path d="M9 12l2 2 4-4" /></S>,
  seta: <S><path d="M9 6l6 6-6 6" /></S>,
  ok: <S><path d="M5 12l5 5 9-10" /></S>,
};

export function Logo({ tam = 34 }: { tam?: number }) {
  return <span className="logo" style={{ width: tam, height: tam, fontSize: tam * 0.38, borderRadius: tam * 0.3 }}>{MARCA.sigla}</span>;
}

/** Imagem protegida por token. `recarregar` (ms) atualiza sozinha: ronda. */
export function Foto({ caminho, alt, posicao, recarregar }: { caminho: string; alt: string; posicao?: string; recarregar?: number }) {
  const [url, setUrl] = useState('');
  const [erro, setErro] = useState(false);
  useEffect(() => {
    let vivo = true;
    let t = 0;
    async function buscar() {
      if (!caminho) { setErro(true); return; }
      try {
        const u = await fotoUrl(caminho);
        if (vivo) { setUrl(u); setErro(false); }
      } catch {
        if (vivo) setErro(true);
      }
      if (vivo && recarregar) t = window.setTimeout(buscar, recarregar);
    }
    void buscar();
    return () => { vivo = false; clearTimeout(t); };
  }, [caminho, recarregar]);
  if (url) return <img className="foto" src={url} alt={alt} style={posicao ? { objectPosition: posicao } : undefined} />;
  return <div className="foto-vazia">{erro ? 'Sem imagem' : 'Carregando…'}</div>;
}

export function Carregando() { return <div className="vazio">Carregando…</div>; }
export function Erro({ erro }: { erro: unknown }) { return <div className="vazio erro">{(erro as Error)?.message || 'Não deu para carregar.'}</div>; }
