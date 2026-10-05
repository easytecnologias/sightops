import { useQuery } from '@tanstack/react-query';
import { obter } from './api';

/* Formas que a API devolve. Conferidas uma a uma no backend:
   /api/cameras -> {cameras:[...]} e aceita mode=basico (nao "basic")
   /api/connectors -> {connectors:[...]}
   /api/auth/me -> {ok, user:{...}}                                        */

export type Camera = {
  ip?: string;
  mac?: string;
  titulo?: string;
  title?: string;
  fabricante?: string;
  modelo?: string;
  site?: string;
  site_name?: string;
  local?: string;
  status?: string;
  recorder_host?: string;
  recorder_channel?: string | number;
  physical_location?: string;
  lat?: string;
  lon?: string;
  snapshot_url?: string;
  status_checked_at?: string;
  ocorrencia?: string;
  ocorrencia_em?: string;
  ocorrencia_por?: string;
  inventory_mode?: string;
};

/** Chave de uma camera na navegacao. IP sozinho repete entre sites; com o
 *  MAC junto o endereco deixa de ser ambiguo. */
export function chaveDa(c: Camera): string {
  return encodeURIComponent(`${c.ip ?? ''}|${c.mac ?? ''}`);
}

export type Conector = {
  id?: string;
  name?: string;
  site?: string;
  client?: string;
  online?: boolean;
};

export type Resumo = {
  inventory?: {
    ip?: Record<string, number>;
    nvr?: Record<string, number>;
    dvr?: Record<string, number>;
  };
  sites?: unknown;
  alerts?: { level?: string; label?: string; count?: number }[];
  generated_at?: string;
};

export type Usuario = {
  username?: string;
  full_name?: string;
  role?: string;
  tenant?: string;
  tenant_name?: string;
};

/** Estado de verdade da camera. "unknown" NAO e offline: e o sistema
 *  admitindo que nao conseguiu medir (conector caido, leitura velha).
 *  Misturar os dois manda tecnico a campo atras de equipamento que funciona. */
export type Estado = 'online' | 'offline' | 'sem';

export function estadoDa(c: Camera): Estado {
  const s = String(c.status ?? '').toLowerCase();
  if (s === 'online') return 'online';
  if (!s || s === 'unknown' || s === 'desconhecido') return 'sem';
  return 'offline';
}

export function siteDa(c: Camera): string {
  return String(c.site || c.site_name || c.local || '').trim();
}

export function siteDoConector(c: Conector): string {
  return String(c.site || c.client || c.name || '').trim();
}

export function tituloDa(c: Camera): string {
  return String(c.titulo || c.title || '').trim() || '(sem titulo)';
}

/* ───────────────────────────── consultas ───────────────────────────── */

export function useResumo() {
  return useQuery({
    queryKey: ['resumo'],
    queryFn: () => obter<Resumo>('/api/dashboard/summary'),
  });
}

export function useConectores() {
  return useQuery({
    queryKey: ['conectores'],
    queryFn: async () => {
      const d = await obter<{ connectors?: Conector[] }>('/api/connectors');
      return d.connectors ?? [];
    },
  });
}

/**
 * Todas as cameras, de todos os modos de inventario.
 *
 * `olt`, `basico` e `switch` sao TRES VISTAS da mesma camera, nao tres listas
 * que se somam: concatenar direto conta a mesma camera ate tres vezes. A
 * chave ip+mac deduplica, como o dashboard do app web ja faz.
 */
export function useCameras() {
  return useQuery({
    queryKey: ['cameras'],
    queryFn: async () => {
      const modos = ['olt', 'basico', 'switch'];
      const partes = await Promise.all(
        modos.map((m) =>
          obter<{ cameras?: Camera[] }>(`/api/cameras?mode=${encodeURIComponent(m)}`)
            .catch(() => ({ cameras: [] as Camera[] })),
        ),
      );
      const vistas = new Map<string, Camera>();
      for (const p of partes) {
        for (const c of p.cameras ?? []) {
          const chave = `${c.ip ?? ''}|${c.mac ?? ''}`;
          if (!vistas.has(chave)) vistas.set(chave, c);
        }
      }
      return [...vistas.values()];
    },
  });
}

export function useEu() {
  return useQuery({
    queryKey: ['eu'],
    queryFn: async () => {
      const d = await obter<{ user?: Usuario }>('/api/auth/me');
      return d.user ?? ({} as Usuario);
    },
    retry: false,
  });
}

export type ResumoAlerta = { open?: number; new?: number; latest_new_id?: string };

/**
 * Contagem de alertas abertos, para o sino da barra de baixo.
 *
 * O endpoint tambem devolve `duress` (coacao). Esse campo NUNCA e lido aqui e
 * nao pode aparecer em tela nenhuma: coacao e um pedido de socorro silencioso,
 * e mostrar que ele existe entrega quem o acionou.
 */
export function useAlertas() {
  return useQuery({
    queryKey: ['alertas'],
    queryFn: async () => {
      const d = await obter<ResumoAlerta>('/api/alert/summary');
      return { open: d.open ?? 0, novos: d.new ?? 0 };
    },
    // O sino precisa estar certo agora, nao daqui a dois minutos.
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
