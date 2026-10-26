/* Ordem crescente em todo o app. A API devolve na ordem do banco (que muda a
   cada leitura); toda lista sai daqui em ordem natural: "CH 3" antes de
   "CH 14", 100.65.10.6 antes de 100.65.10.51, JARDINS I antes de JARDINS II. */

const coletor = new Intl.Collator('pt-BR', { numeric: true, sensitivity: 'base' });

export const ordemNatural = (a: unknown, b: unknown) => coletor.compare(String(a ?? ''), String(b ?? ''));

/** Copia ordenada por uma ou mais chaves (a seguinte desempata a anterior). */
export function ordenar<T>(lista: T[], ...chaves: ((x: T) => unknown)[]) {
  return [...lista].sort((a, b) => {
    for (const k of chaves) {
      const r = ordemNatural(k(a), k(b));
      if (r) return r;
    }
    return 0;
  });
}
