import { useRef, useState, type ReactNode } from 'react';
import { useIsFetching, useQueryClient } from '@tanstack/react-query';
import { Icone } from './pecas';

const LIMIAR = 70;   // px puxados para soltar e atualizar

/** Busca de novo tudo o que esta na tela (e o que estiver guardado). */
export function useAtualizarTudo() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ refetchType: 'active' });
}

/**
 * Area rolavel com "puxar para atualizar". So arma quando a lista ja esta no
 * topo, para nao brigar com a rolagem; no mapa fica desligada (arrastar e
 * mover o mapa).
 */
export function AreaPuxar({ children, desligado }: { children: ReactNode; desligado?: boolean }) {
  const atualizar = useAtualizarTudo();
  const buscando = useIsFetching() > 0;
  const area = useRef<HTMLElement>(null);
  const inicio = useRef<number | null>(null);
  const [puxado, setPuxado] = useState(0);
  const [pedido, setPedido] = useState(false);

  return (
    <main ref={area} className="conteudo"
          onTouchStart={(ev) => { inicio.current = !desligado && (area.current?.scrollTop ?? 0) <= 0 ? ev.touches[0].clientY : null; }}
          onTouchMove={(ev) => {
            if (inicio.current === null) return;
            const dy = ev.touches[0].clientY - inicio.current;
            setPuxado(dy > 0 ? Math.min(dy * 0.5, 110) : 0);
          }}
          onTouchEnd={() => {
            if (puxado >= LIMIAR) { setPedido(true); void Promise.resolve(atualizar()).finally(() => setPedido(false)); }
            inicio.current = null; setPuxado(0);
          }}>
      {puxado > 0 || pedido ? (
        <div className="puxar" style={{ height: pedido ? 44 : puxado }} role="status">
          <span className={pedido || buscando ? 'girando' : ''} style={{ transform: pedido ? undefined : `rotate(${puxado * 3}deg)` }}>{Icone.atualizar}</span>
          {pedido ? 'Atualizando…' : puxado >= LIMIAR ? 'Solte para atualizar' : 'Puxe para atualizar'}
        </div>
      ) : null}
      {children}
    </main>
  );
}
