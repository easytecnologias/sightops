import { useQuery } from '@tanstack/react-query';
import { obter } from './api';
import { ordenar } from './ordem';

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
  connector_id?: string;
  remote_connector_id?: string;
  /* Por onde a camera chega: ONU (fibra) e/ou switch e porta. */
  pon?: string;
  onu_id?: string;
  onu_name?: string;
  onu_serial?: string;
  switch_ip?: string;
  switch_name?: string;
  switch_port?: string;
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
  type?: string;
  status?: string;
  /** Calculado aqui: a API manda `status` ("online"/"offline"), nao `online`. */
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
      return ordenar((d.connectors ?? []).map((c) => ({ ...c, online: String(c.status ?? '').toLowerCase() === 'online' })), (c) => c.name, (c) => c.id);
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
      // Por gravador e canal, como o tecnico ve no gravador; sem canal, pelo nome.
      return ordenar([...vistas.values()], (c) => c.recorder_host, (c) => c.recorder_channel, tituloDa, (c) => c.ip);
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

/* ───────────────────────── monitoramento (o mesmo dado do Zabbix) ─────────────────────────
   /api/monitoring/entities?entity_type=X -> {entities:[...]}  (monitoring_service.list_entities)
   /api/monitoring/summary                -> {types, events}   (ultimos 20 eventos)
   /api/monitoring/onu-signals?entity_key -> {samples:[...]}    (historico de sinal da ONU) */

export type Entidade = {
  entity_key: string;
  entity_type: string;
  site?: string;
  display_name?: string;
  status?: string;          // up | down | unstable | unknown | maintenance
  last_checked_at?: string;
  last_changed_at?: string;
  detail_json?: string;
  connector_id?: string;
};

export type EventoMon = {
  entity_key: string; entity_type: string; from_status: string; to_status: string; message: string; created_at: string;
};

export function detalhe<T = Record<string, unknown>>(e: Entidade): T {
  try { return (e.detail_json ? JSON.parse(e.detail_json) : {}) as T; } catch { return {} as T; }
}

export const mesmoSite = (a?: string | null, b?: string | null) =>
  String(a ?? '').trim().toUpperCase() === String(b ?? '').trim().toUpperCase();

/** Entidades de um tipo. 2000 e o teto do servidor (camera passa de 1600 no parque). */
export function useEntidades(tipo: string) {
  return useQuery({
    queryKey: ['entidades', tipo],
    queryFn: async () => ordenar((await obter<{ entities?: Entidade[] }>(
      `/api/monitoring/entities?entity_type=${encodeURIComponent(tipo)}&limit=2000`)).entities ?? [],
      (e) => e.display_name, (e) => e.entity_key),
    staleTime: 60_000,
  });
}

export function useEventos() {
  return useQuery({
    queryKey: ['eventos'],
    queryFn: async () => (await obter<{ events?: EventoMon[] }>('/api/monitoring/summary')).events ?? [],
    staleTime: 60_000,
  });
}

export type AmostraSinal = { onu_rx?: number | string | null; olt_rx?: number | string | null; captured_at?: string; oper_status?: string };

export function useSinalOnu(entityKey?: string) {
  return useQuery({
    queryKey: ['sinal', entityKey],
    queryFn: async () => (await obter<{ samples?: AmostraSinal[] }>(
      `/api/monitoring/onu-signals?entity_key=${encodeURIComponent(entityKey!)}&limit=288`)).samples ?? [],
    enabled: !!entityKey,
  });
}

/* ───────────────────────── OLT ───────────────────────── */

export type Olt = {
  id: number; name?: string; host?: string; ip?: string; vendor?: string; model?: string; site?: string; active?: boolean;
  status?: string; last_test_status?: string; last_tested_at?: string; capability_label?: string; connector_id?: string;
};

/** IP da OLT: o cadastro chama de `host`. */
export const ipDaOlt = (o?: Olt) => String(o?.host || o?.ip || '');

export function useOlts() {
  return useQuery({
    queryKey: ['olts'],
    queryFn: async () => ordenar((await obter<{ items?: Olt[] }>('/api/olt/registry')).items ?? [], (o) => o.name, ipDaOlt),
    staleTime: 5 * 60_000,
  });
}

/* ───────────────────────── VLAN da ONU e de quem ela e ───────────────────────── */

type LinhaOlt = { olt_ip?: string; pon?: string | number; onu_id?: string | number; onu_serial?: string; vlan?: string | number };

/** VLANs vistas na ONU pela coleta da OLT (/api/olt/rows: uma linha por MAC
 *  atras da ONU; o modo compact NAO traz a vlan). Filtrado pelo site da ONU. */
export function useVlansOnu(site: string, oltIp: string, pon: string, onu: string, serial: string) {
  const q = useQuery({
    queryKey: ['olt-rows', site],
    queryFn: async () => (await obter<{ rows?: LinhaOlt[] }>(`/api/olt/rows?site=${encodeURIComponent(site)}`)).rows ?? [],
    enabled: !!site,
    staleTime: 5 * 60_000,
  });
  const ser = serial.toUpperCase();
  const vlans = new Set<string>();
  for (const r of q.data ?? []) {
    const mesma = ser ? String(r.onu_serial ?? '').toUpperCase() === ser
      : String(r.olt_ip ?? '') === oltIp && String(r.pon ?? '').split('/').pop() === pon && String(r.onu_id ?? '') === onu;
    if (!mesma) continue;
    for (const v of String(r.vlan ?? '').split(/[,\s]+/)) if (/^\d+$/.test(v)) vlans.add(v);
  }
  return { vlans: [...vlans].sort((a, b) => Number(a) - Number(b)), carregando: q.isPending && !!site };
}

type Rack = { provedores?: { nome?: string; vlans?: (number | string)[] }[] };

/** VLAN -> provedor, pelos provedores cadastrados nos racks do mapa
 *  (meta.racks das camadas; sem os pontos, que sao pesados). */
export function useProvedoresPorVlan() {
  return useQuery({
    queryKey: ['provedores-vlan'],
    queryFn: async () => {
      const layers = (await obter<{ layers?: { racks?: Record<string, Rack> }[] }>('/api/kmz/import/layers?include_features=false')).layers ?? [];
      const mapa: Record<string, string[]> = {};
      for (const l of layers) for (const r of Object.values(l.racks ?? {})) for (const pv of r.provedores ?? []) {
        const nome = String(pv.nome ?? '').trim();
        if (!nome) continue;
        for (const v of pv.vlans ?? []) {
          const lista = (mapa[String(v)] ??= []);
          if (!lista.includes(nome)) lista.push(nome);
        }
      }
      return mapa;
    },
    staleTime: 10 * 60_000,
  });
}

/* ───────────────────────── panico (so contagem e lista; NUNCA o campo de coacao) ───────────────────────── */

export type Incidente = {
  id: string; kind: string; status: string; opened_at: string; closed_at?: string; site?: string;
  member?: { full_name?: string; unit_name?: string };
};

export function useIncidentes(escopo: 'live' | 'history', ativo = true) {
  return useQuery({
    enabled: ativo,
    queryKey: ['incidentes', escopo],
    queryFn: async () => {
      const d = await obter<{ incidents?: (Incidente & Record<string, unknown>)[] }>(
        `/api/alert/incidents?scope=${escopo}&limit=100`);
      // So os campos que a tela usa: coacao (duress_at) nao entra nem na memoria do app.
      return (d.incidents ?? []).map((i) => ({
        id: i.id, kind: i.kind, status: i.status, opened_at: i.opened_at, closed_at: i.closed_at, site: i.site,
        member: { full_name: i.member?.full_name, unit_name: i.member?.unit_name },
      }) as Incidente);
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
