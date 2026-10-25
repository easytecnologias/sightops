/** "ha 6 d", "ha 12 min". Usado para dizer a idade do dado em cache e o
 *  tempo que um equipamento esta fora -- nos dois casos o que importa e a
 *  ordem de grandeza, nao o relogio. */
export function desde(ms: number | string | null | undefined): string {
  if (!ms) return '—';
  const t = typeof ms === 'string' ? new Date(ms).getTime() : ms;
  if (!t || Number.isNaN(t)) return '—';
  const min = Math.floor((Date.now() - t) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `ha ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `ha ${h} h`;
  const d = Math.floor(h / 24);
  return `ha ${d} d`;
}

/** Forma curta para badge: "6 d", "2 h", "12 min". */
export function curto(ms: number | string | null | undefined): string {
  const s = desde(ms);
  return s.startsWith('ha ') ? s.slice(3) : s;
}
