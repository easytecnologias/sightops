import type { ReactNode } from 'react';

/* As pecas visuais do SightOps, traduzidas para o celular. Os nomes e as
   medidas vem de frontend/styles.css do app web -- page-heading, panel,
   badge, metric-icon. Nao e um tema novo: e o mesmo produto noutra tela. */

export function PageHeading(
  { eyebrow, titulo, sub }: { eyebrow: string; titulo: string; sub?: string },
) {
  return (
    <div className="page-heading">
      <p className="eyebrow">{eyebrow}</p>
      <h1>{titulo}</h1>
      {sub ? <p>{sub}</p> : null}
    </div>
  );
}

export function Panel(
  { children, variante }: { children: ReactNode; variante?: 'atencao' | 'fila' },
) {
  return <section className={`panel${variante ? ' ' + variante : ''}`}>{children}</section>;
}

export function PanelHeader(
  { titulo, sub, direita }: { titulo: string; sub?: string; direita?: ReactNode },
) {
  return (
    <div className="panel-header">
      <div>
        <h2>{titulo}</h2>
        {sub ? <p>{sub}</p> : null}
      </div>
      {direita}
    </div>
  );
}

export type Cor = 'green' | 'red' | 'amber' | 'blue' | 'gray';

export function Badge({ cor, children }: { cor: Cor; children: ReactNode }) {
  return <span className={`badge badge-${cor}`}>{children}</span>;
}

export function Kpi(
  { cor, icone, rotulo, numero, sub }:
  { cor: string; icone: ReactNode; rotulo: string; numero: ReactNode; sub?: string },
) {
  return (
    <div className="kpi">
      <span className={`metric-icon ${cor}`}>{icone}</span>
      <span style={{ minWidth: 0, flex: 1 }}>
        <span className="rot">{rotulo}</span>
        <span className="num">{numero}</span>
        {sub ? <span className="sub">{sub}</span> : null}
      </span>
    </div>
  );
}

export function Linha(
  { icone, titulo, sub, direita, onClick }:
  { icone: ReactNode; titulo: string; sub?: string; direita?: ReactNode; onClick?: () => void },
) {
  const conteudo = (
    <>
      <span className="mi">{icone}</span>
      <span style={{ minWidth: 0 }}>
        <span className="t">{titulo}</span>
        {sub ? <span className="s mono">{sub}</span> : null}
      </span>
      {direita}
    </>
  );
  // Linha que faz alguma coisa e <button>; linha que so informa e <div>.
  // Um <div> com onClick o teclado e o leitor de tela nunca alcancam.
  return onClick
    ? <button type="button" className="linha" onClick={onClick}>{conteudo}</button>
    : <div className="linha">{conteudo}</div>;
}

export function Vazio({ children }: { children: ReactNode }) {
  return <div className="vazio">{children}</div>;
}

export function Carregando() {
  return <div className="carregando">Carregando…</div>;
}

/**
 * Selo de procedencia do dado.
 *
 * Toda tela de consulta mostra se o que esta na frente veio agora ou da copia
 * guardada, e de quando. Dado velho sem aviso e pior que tela vazia: o tecnico
 * decide com ele sem saber que esta decidindo com o passado.
 */
export function Procedencia(
  { buscando, atualizadoEm, online }:
  { buscando: boolean; atualizadoEm?: number; online: boolean },
) {
  if (buscando) return <Badge cor="gray">buscando…</Badge>;
  if (!atualizadoEm) return <Badge cor="gray">sem dados</Badge>;
  const fresco = online && Date.now() - atualizadoEm < 120_000;
  if (fresco) return <Badge cor="green">agora</Badge>;
  const quando = new Date(atualizadoEm).toLocaleString('pt-BR', {
    hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit',
  });
  return <Badge cor="amber">{online ? `de ${quando}` : `no aparelho · ${quando}`}</Badge>;
}

/* Icones: SVG de traco, como o lucide que o app web usa. */
const P = (d: string) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.9}
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
       dangerouslySetInnerHTML={{ __html: d }} />
);

export const Icone = {
  grid: P('<rect x="3" y="3" width="7" height="8" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="11" width="7" height="10" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/>'),
  pin: P('<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z"/><circle cx="12" cy="10" r="2.4"/>'),
  pasta: P('<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10l2 2.5h6.5A1.5 1.5 0 0 1 20 8v10a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18Z"/>'),
  camera: P('<rect x="3" y="6.5" width="18" height="12" rx="2"/><circle cx="12" cy="12.5" r="3.2"/>'),
  gravador: P('<rect x="3" y="5" width="18" height="6" rx="1.6"/><rect x="3" y="13" width="18" height="6" rx="1.6"/><path d="M6.5 8h.01M6.5 16h.01"/>'),
  onu: P('<path d="M5 12a7 7 0 0 1 14 0"/><path d="M8.5 12a3.5 3.5 0 0 1 7 0"/><circle cx="12" cy="17" r="1.6"/>'),
  raio: P('<path d="M13 3 5 13.5h6L10.5 21 19 10.5h-6Z"/>'),
  engrenagem: P('<circle cx="12" cy="12" r="3"/><path d="M12 3v2.5M12 18.5V21M21 12h-2.5M5.5 12H3"/>'),
  alerta: P('<circle cx="12" cy="12" r="9"/><path d="M12 8.5v5"/><path d="M12 16.8h.01"/>'),
  busca: P('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>'),
  menu: P('<path d="M4 7h16M4 12h16M4 17h16"/>'),
  seta: P('<path d="m9 6 6 6-6 6"/>'),
  atualizar: P('<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/>'),
};
