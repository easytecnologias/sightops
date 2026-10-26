import { useMemo } from 'react';
import { detalhe, mesmoSite, useEntidades, useEventos, type Entidade, type EventoMon } from './dados';

/* Leitura do monitoramento por site: o que o tecnico precisa ver ao chegar. */

export const LIMITE_RX = -27;   // dBm: abaixo disto a ONU esta com sinal baixo

export type DetalheOnu = {
  onu_rx?: string | number | null; olt_rx?: string | number | null; onu_tx?: string | number | null;
  distance_km?: string | number | null; temperatura?: string | number | null;
  offline_reason?: string; serial?: string; pon?: number | string;
};
export type DetalheCamera = { ip?: string; model?: string; status_lido?: string; onu?: { olt_name?: string; pon?: string; onu_id?: string } };

export function num(v: unknown): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = Number(String(v).replace(',', '.'));
  return Number.isFinite(n) ? n : null;
}

/** "onu:<hash>|<olt_ip>|<pon>|<onu>" -> partes. */
export function partesOnu(key: string): { oltIp: string; pon: string; onu: string } {
  const p = key.split('|');
  return { oltIp: p[1] ?? '', pon: p[2] ?? '', onu: p[3] ?? '' };
}

export function rxDa(e: Entidade): number | null {
  return num(detalhe<DetalheOnu>(e).onu_rx);
}
export function sinalBaixo(e: Entidade): boolean {
  const rx = rxDa(e);
  return e.status === 'up' && rx !== null && rx < LIMITE_RX;
}

export function nomeEntidade(e: Entidade): string {
  return String(e.display_name || e.entity_key).trim();
}

export const TIPO_NOME: Record<string, string> = {
  camera: 'câmera', nvr: 'gravador', dvr: 'gravador', onu: 'ONU', olt: 'OLT', connector: 'conector',
  switch: 'switch', switch_provedor: 'switch', access_device: 'leitor', access_point: 'Wi-Fi', link: 'link', windows: 'PC',
};

/** Entidades do site, por tipo, e o que precisa de atencao. */
export function useSiteMonitor(site: string | null) {
  const cams = useEntidades('camera');
  const nvrs = useEntidades('nvr');
  const onus = useEntidades('onu');
  const cons = useEntidades('connector');
  const sws = useEntidades('switch');
  const olts = useEntidades('olt');
  const eventos = useEventos();

  return useMemo(() => {
    const doSite = (l?: Entidade[]) => (l ?? []).filter((e) => !site || mesmoSite(e.site, site));
    const r = {
      cameras: doSite(cams.data), nvrs: doSite(nvrs.data), onus: doSite(onus.data),
      conectores: doSite(cons.data), switches: doSite(sws.data), olts: doSite(olts.data),
    };
    const todas = [...r.conectores, ...r.olts, ...r.nvrs, ...r.switches, ...r.cameras, ...r.onus];
    const chaves = new Set(todas.map((e) => e.entity_key));
    const atencao = todas
      .filter((e) => e.status === 'down' || e.status === 'unstable' || (e.entity_type === 'onu' && sinalBaixo(e)))
      .sort((a, b) => String(b.last_changed_at ?? '').localeCompare(String(a.last_changed_at ?? '')));
    const mudancas: EventoMon[] = (eventos.data ?? []).filter((ev) => chaves.has(ev.entity_key));
    const carregando = cams.isPending && !cams.data;
    const atualizadoEm = Math.max(cams.dataUpdatedAt, onus.dataUpdatedAt, cons.dataUpdatedAt);
    const buscando = cams.isFetching || onus.isFetching || cons.isFetching;
    const recarregar = () => { void cams.refetch(); void nvrs.refetch(); void onus.refetch(); void cons.refetch(); void eventos.refetch(); };
    return { ...r, atencao, mudancas, carregando, atualizadoEm, buscando, recarregar };
  }, [site, cams, nvrs, onus, cons, sws, olts, eventos]);
}

/** Quanto tempo desde um texto de data do servidor (com ou sem fuso). */
export function quando(txt?: string | null): number | null {
  if (!txt) return null;
  const t = new Date(String(txt).replace(' ', 'T')).getTime();
  return Number.isNaN(t) ? null : t;
}

export function horaCurta(txt?: string | null): string {
  const t = quando(txt);
  if (!t) return '';
  return new Date(t).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}
