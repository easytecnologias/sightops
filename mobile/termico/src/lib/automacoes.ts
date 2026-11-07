import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { atualizar, enviar, obter, pedirExcluir } from './api';

/** Automacoes "Se... entao..." e cenas de um toque (mesmo motor da tela web). */
export type Gatilho =
  | { tipo: 'pessoa' | 'offline'; camera_id: string }
  | { tipo: 'usina_offline'; site: string }
  | { tipo: 'horario'; hora: string; dias: number[] }
  | { tipo: 'sol'; evento: 'nascer' | 'por'; site: string; minutos: number }
  | { tipo: 'manual' };

export type Acao = {
  tipo: 'saida' | 'speed_preset' | 'speed_seguir' | 'aguardar' | 'avisar' | 'vigiar_usina' | 'executar_regra' | 'ligar_regra';
  ip?: string; connector_id?: string; nome?: string; site?: string;
  preset?: number; voltar_s?: number; saida?: number; segundos?: number;
  texto?: string; ligar?: boolean; regra_id?: string;
};

export type Regra = {
  id?: string; nome: string; ativo: boolean; modo: 'simular' | 'valer'; intervalo_s: number;
  origem_camera_id?: string; gatilhos: Gatilho[]; acoes: Acao[]; periodo: { de?: string; ate?: string }; cena?: boolean;
};

export type Equipamento = { ip: string; connector_id: string; nome: string; site: string; modelo: string; speed: boolean };
export type Execucao = { automacao_id: string; modo: string; ok: number; resposta: string; criado_at: string; acao: string };
type Lista = { automacoes: Regra[]; execucoes: Execucao[]; equipamentos: Equipamento[]; sites: string[] };

export function useAutomacoes() {
  return useQuery({ queryKey: ['automacoes'], queryFn: () => obter<Lista>('/api/automacoes'), refetchInterval: 30_000 });
}

// Criar e mudar e so de administrador (como na web); cena qualquer operador executa.
export function useEu() {
  return useQuery({ queryKey: ['eu'], queryFn: () => obter<{ role?: string; username?: string; nome?: string }>('/api/auth/me'), staleTime: 300_000 });
}
const RANK: Record<string, number> = { viewer: 10, operator: 20, admin: 30, owner: 40 };
export const ehAdmin = (role?: string) => (RANK[(role || '').toLowerCase()] || 0) >= 30;

function useAtualizar<T>(fn: (p: T) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: ['automacoes'] }) });
}
export const useSalvarRegra = () => useAtualizar((r: Regra) => (r.id
  ? atualizar<Regra>(`/api/automacoes/${encodeURIComponent(r.id)}`, r) : enviar<Regra>('/api/automacoes', r)));
export const useLigarRegra = () => useAtualizar((p: { id: string; ativo: boolean }) =>
  atualizar(`/api/automacoes/${encodeURIComponent(p.id)}/ligar`, { ativo: p.ativo }));
export const useExecutarCena = () => useAtualizar((id: string) => enviar(`/api/automacoes/cenas/${encodeURIComponent(id)}/executar`));
export const useTestarRegra = () => useAtualizar((id: string) => enviar(`/api/automacoes/${encodeURIComponent(id)}/testar`));
export const useExcluirRegra = () => useAtualizar((id: string) => pedirExcluir(`/api/automacoes/${encodeURIComponent(id)}`));

export const DIAS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];

export function textoGatilho(g: Gatilho, nomeCam: (id: string) => string): [string, string] {
  switch (g.tipo) {
    case 'pessoa': return ['Pessoa detectada', g.camera_id ? nomeCam(g.camera_id) : 'Qualquer câmera térmica'];
    case 'offline': return ['Câmera offline', g.camera_id ? nomeCam(g.camera_id) : 'Qualquer câmera'];
    case 'usina_offline': return ['Usina sem comunicação', g.site];
    case 'horario': return [`Às ${g.hora}`, g.dias.length === 7 ? 'Todos os dias' : g.dias.map((d) => DIAS[d]).join(', ')];
    case 'sol': return [g.evento === 'por' ? 'Pôr do sol' : 'Nascer do sol', `${g.site}${g.minutos ? ` · ${g.minutos > 0 ? '+' : ''}${g.minutos} min` : ''}`];
    default: return ['Toque no app', 'Cena: roda quando tocar'];
  }
}

export function textoAcao(a: Acao, nomeRegra: (id: string) => string): [string, string] {
  switch (a.tipo) {
    case 'speed_preset': return ['Apontar a speed', `${a.nome} · preset ${a.preset}${a.voltar_s ? ` · volta em ${a.voltar_s} s` : ''}`];
    case 'speed_seguir': return ['Speed segue o alarme', `${a.nome} · calibrada no computador`];
    case 'saida': return [a.segundos && a.segundos >= 60 ? 'Acender refletor' : 'Tocar sirene', `${a.nome} · saída ${a.saida} · ${a.segundos} s`];
    case 'aguardar': return ['Aguardar', `${a.segundos} segundos`];
    case 'avisar': return ['Avisar celulares', `"${a.texto}"`];
    case 'vigiar_usina': return [a.ligar ? 'Vigiar usina' : 'Desligar usina', a.site || ''];
    case 'executar_regra': return ['Executar cena', nomeRegra(a.regra_id || '')];
    default: return [a.ligar ? 'Ligar automação' : 'Desligar automação', nomeRegra(a.regra_id || '')];
  }
}

/** Icone e cor de cada tipo: a mesma linguagem nos cartoes, no editor e nas folhas. */
export const ICONE: Record<string, [string, string]> = {
  pessoa: ['al', 'M12 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM6 21v-2a6 6 0 0 1 12 0v2'],
  offline: ['cz', 'M2.5 8h11a2 2 0 0 1 2 2v6a2 2 0 0 1-2 2h-11zM15.5 10.5 21 7.5v9l-5.5-3M3 3l18 18'],
  usina_offline: ['cz', 'M2 8.8a15 15 0 0 1 20 0M5 12.4a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M3 3l18 18'],
  horario: ['vd', 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2'],
  sol: ['am', 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22'],
  manual: ['az', 'M8 13V5a2 2 0 0 1 4 0v6l5 1a2 2 0 0 1 1.6 2.3L17.5 21H9l-4-5'],
  speed_preset: ['az', 'M12 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM12 8a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM8 20h8M12 16v4'],
  speed_seguir: ['az', 'M12 4a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM12 2v4M12 18v4M2 12h4M18 12h4'],
  saida: ['al', 'M5 18v-6a7 7 0 0 1 14 0v6M3 18h18M12 2v2'],
  refletor: ['am', 'M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.6.6 1 1.4 1 2.5h6c0-1.1.4-1.9 1-2.5A6 6 0 0 0 12 3z'],
  aguardar: ['cz', 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2'],
  avisar: ['mr', 'M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9'],
  vigiar_usina: ['vd', 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4'],
  executar_regra: ['mr', 'M8 5v14l11-7z'],
  ligar_regra: ['cz', 'M13 2 4 14h7l-1 8 9-12h-7z'],
};
