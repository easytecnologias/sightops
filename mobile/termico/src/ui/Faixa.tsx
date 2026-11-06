import type { Alerta } from '../lib/termico';

const eHoje = (iso: string) => new Date(iso).toDateString() === new Date().toDateString();
export const alarmesHoje = (l: Alerta[]) => l.filter((a) => !a.mancha?.teste && eHoje(a.criado_at));

/** Alarmes de hoje hora a hora; a noite fica mais escura. */
export function Horas({ alertas }: { alertas: Alerta[] }) {
  const n = Array<number>(24).fill(0);
  for (const a of alarmesHoje(alertas)) n[new Date(a.criado_at).getHours()] += 1;
  const maior = Math.max(1, ...n);
  return (
    <div>
      <div className="h24" role="img" aria-label="Alarmes de hoje por hora">
        {n.map((v, i) => <span key={i} className={i < 6 || i >= 18 ? 'n' : ''}><i style={{ height: `${Math.round((v / maior) * 100)}%` }} /></span>)}
      </div>
      <div className="h24r"><span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>23h</span></div>
    </div>
  );
}
