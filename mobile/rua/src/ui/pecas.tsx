import type { ReactNode } from 'react';

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
  sair: P('<path d="M15 4h3a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1h-3"/><path d="M10 16 6 12l4-4"/><path d="M6 12h9"/>'),
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
export function Carregando() {
  return <div className="carregando">Carregando…</div>;
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
