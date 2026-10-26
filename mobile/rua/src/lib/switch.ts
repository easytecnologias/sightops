import { useQuery } from '@tanstack/react-query';
import { enviar, obter } from './api';

/*
 * Portas do switch: o que a ultima "Coletar MACs" leu (GET /api/switch/rows).
 * `ports` = estado de cada porta (link, PoE, velocidade); `rows` = MACs vistos
 * em cada porta. E foto da ultima coleta, nao leitura ao vivo.
 */

export type PortaSw = {
  site?: string; switch_ip?: string; switch_name?: string; port?: string; port_id?: number | null;
  up?: boolean; bandwidth?: string; duplex?: string; poe_enabled?: boolean | null;
  poe_power_watts?: number | string | null; admin_enabled?: boolean | null;
};
export type MacSw = {
  site?: string; switch_ip?: string; switch_name?: string; port?: string; vlan?: string; mac?: string;
  port_role_guess?: string;
};

export function useSwitchPortas() {
  return useQuery({
    queryKey: ['switch-portas'],
    queryFn: async () => {
      const d = await obter<{ rows?: MacSw[]; ports?: PortaSw[] }>('/api/switch/rows');
      return { macs: d.rows ?? [], portas: d.ports ?? [] };
    },
    staleTime: 60_000,
  });
}

export const macNorm = (m?: string) => String(m ?? '').replace(/[^0-9a-f]/gi, '').toUpperCase();

/** Desliga e religa o PoE da porta: reinicia o que esta pendurado nela. */
export async function religarPoe(switchIp: string, site: string, porta: string) {
  await enviar('/api/switch/port/poe', { switch_ip: switchIp, site, port: porta, enabled: false });
  await new Promise((ok) => setTimeout(ok, 5000));
  await enviar('/api/switch/port/poe', { switch_ip: switchIp, site, port: porta, enabled: true });
}

/** Ordem natural das portas ("1", "2", ..., "10"; "GE1/0/2"). */
export function ordemPorta(a?: string, b?: string) {
  return String(a ?? '').localeCompare(String(b ?? ''), 'pt-BR', { numeric: true });
}
