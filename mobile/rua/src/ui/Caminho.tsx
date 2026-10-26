import type { ReactNode } from 'react';
import { Icone } from './pecas';

/*
 * O caminho ate o equipamento: conector -> OLT/PON -> ONU -> switch e porta
 * -> camera -> canal do gravador. Aparece igual em toda ficha, para o tecnico
 * ver de cara onde o sinal parou. Cada elo leva a ficha daquele equipamento.
 */

export type Elo = {
  tipo: 'conector' | 'olt' | 'cto' | 'onu' | 'switch' | 'camera' | 'gravador';
  titulo: ReactNode;
  sub?: string;
  estado?: 'ok' | 'ruim' | 'atencao' | 'sem';
  /** O equipamento desta ficha. */
  aqui?: boolean;
  /** O elo onde o sinal parou: ganha destaque. */
  falha?: boolean;
  onClick?: () => void;
};

const ICONE: Record<Elo['tipo'], ReactNode> = {
  conector: Icone.conector, olt: Icone.olt, cto: Icone.caixa, onu: Icone.onu,
  switch: Icone.switch, camera: Icone.camera, gravador: Icone.gravador,
};

export function Caminho({ elos, titulo = 'Caminho' }: { elos: Elo[]; titulo?: string }) {
  const lista = elos.filter(Boolean);
  if (!lista.length) return null;
  return (
    <section className="caminho" aria-label={titulo}>
      <span className="caminho-tit">{titulo}</span>
      <div className="caminho-lista">
        <span className="caminho-fio" aria-hidden="true" />
        {lista.map((e, i) => {
          const miolo = (
            <>
              <span className={`elo-no ${e.tipo}${e.falha ? ' falha' : ''}${e.aqui ? ' aqui' : ''}`}>{ICONE[e.tipo]}</span>
              <span className="elo-corpo">
                <span className={`elo-t${e.aqui ? ' forte' : ''}`}>{e.titulo}</span>
                {e.sub ? <span className="elo-s">{e.sub}</span> : null}
              </span>
              {e.estado ? <span className={`elo-ponto ${e.estado}`} aria-label={NOME_ESTADO[e.estado]} /> : null}
            </>
          );
          const cls = `elo${e.falha ? ' falha' : ''}`;
          return e.onClick
            ? <button key={i} type="button" className={cls} onClick={e.onClick}>{miolo}</button>
            : <div key={i} className={cls}>{miolo}</div>;
        })}
      </div>
    </section>
  );
}

const NOME_ESTADO = { ok: 'no ar', ruim: 'fora do ar', atencao: 'com problema', sem: 'sem leitura' };
