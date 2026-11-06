import { createContext, useContext } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { atualizar, enviar, obter } from './api';

export type Situacao = 'novo' | 'visto' | 'falso';
export type Alerta = {
  id: string; camera_id: string; site: string; camera_nome: string; criado_at: string; situacao: Situacao;
  temp_c: number | null; fundo_c: number | null; dif_c: number | null;
  mancha: { pontos?: number; caixa?: [number, number, number, number]; teste?: boolean; contraste?: number };
  fotos: { termico: string; visivel: string };
  videos?: { termico: string; visivel: string };
  visto_por: string; visto_at: string; motivo_falso: string; comentario: string;
};
export type ListaAlertas = { alertas: Alerta[]; total: number; por_situacao: Record<string, number>; por_site: Record<string, number> };
export type Camera = {
  id: string; ip: string; connector_id: string; site: string; nome: string; modelo: string; ativo: boolean; armado_de: string; armado_ate: string;
  armado_agora: boolean; leitura: string; leitura_erro: string; leitura_at: string; fundo_c: number | null; pendentes: number;
};

export function useAlertas() {
  return useQuery({ queryKey: ['alertas'], queryFn: () => obter<ListaAlertas>('/api/termico/alertas?limite=200'), refetchInterval: 10_000 });
}
export function useCameras() {
  return useQuery({ queryKey: ['cameras'], queryFn: () => obter<{ cameras: Camera[] }>('/api/termico/cameras'), refetchInterval: 30_000 });
}

export function useResponder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (p: { id: string; tipo: 'ciente' | 'falso'; motivo?: string; comentario?: string }) =>
      enviar<Alerta>(`/api/termico/alertas/${encodeURIComponent(p.id)}/${p.tipo}`, { motivo: p.motivo, comentario: p.comentario }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['alertas'] }),
  });
}

export function useArmar() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (p: { cameras: Camera[]; ligar: boolean }) => {
      for (const c of p.cameras) await atualizar(`/api/termico/cameras/${encodeURIComponent(c.id)}`, { ativo: p.ligar });
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['cameras'] }),
  });
}

/** Usina escolhida ('' = todas). Vale para o app inteiro. */
export const SiteCtx = createContext<{ site: string; escolher: (s: string) => void; abrirSeletor: () => void }>({
  site: '', escolher: () => undefined, abrirSeletor: () => undefined,
});
export const useSite = () => useContext(SiteCtx);

export const natural = (a: string, b: string) => a.localeCompare(b, 'pt', { numeric: true, sensitivity: 'base' });
export const num = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—'
  : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }));
export const hora = (s: string) => { try { return new Date(s).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; } };
export function haQuanto(s: string): string {
  const min = Math.floor((Date.now() - new Date(s).getTime()) / 60000);
  if (min < 1) return 'agora';
  if (min < 60) return `há ${min} min`;
  const h = Math.floor(min / 60);
  return h < 24 ? `há ${h} h` : `há ${Math.floor(h / 24)} d`;
}
