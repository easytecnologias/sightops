import { detalhe, type Entidade } from './dados';
import { partesOnu, quando, type DetalheOnu } from './monitor';

/**
 * Provavel rompimento: duas ou mais ONUs da mesma PON que cairam juntas
 * (ate 3 min de diferenca). Uma ONU sozinha caindo e cliente desligando a
 * tomada; varias no mesmo minuto e fibra ou splitter no caminho comum.
 */
export type Rompimento = {
  oltIp: string; pon: string; quando: number; onus: Entidade[]; los: boolean;
};

const JANELA = 3 * 60_000;

export function rompimentos(onus: Entidade[]): Rompimento[] {
  const porPon = new Map<string, Entidade[]>();
  for (const e of onus) {
    if (e.status !== 'down') continue;
    const p = partesOnu(e.entity_key);
    const k = `${p.oltIp}|${p.pon}`;
    porPon.set(k, [...(porPon.get(k) ?? []), e]);
  }
  const saida: Rompimento[] = [];
  for (const [k, lista] of porPon) {
    const [oltIp, pon] = k.split('|');
    const comHora = lista
      .map((e) => ({ e, t: quando(e.last_changed_at) ?? 0 }))
      .filter((x) => x.t > 0)
      .sort((a, b) => a.t - b.t);
    let grupo: { e: Entidade; t: number }[] = [];
    const fechar = () => {
      if (grupo.length >= 2) {
        const es = grupo.map((x) => x.e);
        saida.push({
          oltIp, pon, quando: grupo[0].t, onus: es,
          los: es.some((e) => /los/i.test(String(detalhe<DetalheOnu>(e).offline_reason ?? ''))),
        });
      }
    };
    for (const x of comHora) {
      if (grupo.length && x.t - grupo[0].t > JANELA) { fechar(); grupo = []; }
      grupo.push(x);
    }
    fechar();
  }
  return saida.sort((a, b) => b.onus.length - a.onus.length || b.quando - a.quando);
}

export const horaDe = (t: number) => new Date(t).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
