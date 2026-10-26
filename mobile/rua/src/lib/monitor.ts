import { useMemo } from 'react';
import { detalhe, mesmoSite, siteDoConector, useConectores, useEntidades, useEventos, type Entidade, type EventoMon } from './dados';
import { ordemNatural } from './ordem';

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

/**
 * Conectores do site escolhido. Um conector pode atender varios sub-sites
 * (PERUCABA tem JARDINS I, RESERVA, INTERBLOCOS...): filtrar so pelo nome do
 * site deixaria a tela vazia. Equipamento do site = mesmo nome OU mesmo conector.
 */
export function useFiltroSite(site: string | null) {
  const cons = useConectores();
  return useMemo(() => {
    const ids = new Set((cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site)).map((c) => String(c.id ?? '')).filter(Boolean));
    // Equipamento de conector que nao existe mais (apagado/trocado) fica de
    // fora: o 5c2897... do PERUCABA deixou 387 cameras paradas desde 23/09
    // com site "PERUCABA", que entravam em contagens e listas pelo nome.
    const existe = new Set((cons.data ?? []).map((c) => String(c.id ?? '')).filter(Boolean));
    const orfao = (conector?: string | null) => !!conector && existe.size > 0 && !existe.has(String(conector));
    return (siteDoItem?: string | null, conector?: string | null) =>
      !orfao(conector) && (!site || mesmoSite(siteDoItem, site) || (!!conector && ids.has(String(conector))));
  }, [cons.data, site]);
}


/**
 * Gravadores do site separados por local (o sub-site do cadastro: JARDINS I,
 * RESERVA...), em ordem de nome. O mesmo host cadastrado duas vezes (uma so
 * com o IP no nome) aparece uma vez, a que tem nome.
 */
export function gravadoresPorLocal(lista: Entidade[], site: string | null) {
  const porHost = new Map<string, Entidade>();
  for (const e of lista) {
    const host = String(detalhe<{ host?: string }>(e).host ?? '');
    if (!host) continue;
    const ja = porHost.get(host);
    const temNome = (x: Entidade) => !!x.display_name && x.display_name !== host;
    if (!ja || (!temNome(ja) && temNome(e))) porHost.set(host, e);
  }
  const grupos = new Map<string, Entidade[]>();
  for (const e of porHost.values()) {
    const local = String(e.site || site || '').trim().toUpperCase() || 'SEM LOCAL';
    grupos.set(local, [...(grupos.get(local) ?? []), e]);
  }
  return [...grupos.entries()].sort(([a], [b]) => ordemNatural(a, b))
    .map(([local, itens]) => ({ local, itens: itens.sort((a, b) => ordemNatural(String(a.display_name ?? ''), String(b.display_name ?? ''))) }));
}

/**
 * Local sugerido pelo nome da camera: o que aparece primeiro nele e, empatado,
 * o mais longo ("JARDINS II - Q12" -> JARDINS II, nao JARDINS I;
 * "RESERVA PERUCABA - 03" -> RESERVA).
 */
export function localPeloNome(locais: string[], nome: string) {
  const n = nome.toUpperCase();
  return locais.map((l) => ({ l, i: n.indexOf(l) })).filter((x) => x.i >= 0)
    .sort((a, b) => a.i - b.i || b.l.length - a.l.length)[0]?.l ?? '';
}

/** O mesmo gravador cadastrado duas vezes (uma so com o IP no nome) fica uma vez, a que tem nome. */
function semGravadorRepetido(lista: Entidade[]) {
  const nomeado = new Set(lista.filter((e) => e.display_name && e.display_name !== detalhe<{ host?: string }>(e).host)
    .map((e) => detalhe<{ host?: string }>(e).host));
  return lista.filter((e) => {
    const host = detalhe<{ host?: string }>(e).host;
    return !(host && e.display_name === host && nomeado.has(host));
  });
}

/** Entidades do site, por tipo, e o que precisa de atencao. */
export function useSiteMonitor(site: string | null) {
  const doSiteFn = useFiltroSite(site);
  const cams = useEntidades('camera');
  const nvrs = useEntidades('nvr');
  const onus = useEntidades('onu');
  const cons = useEntidades('connector');
  const sws = useEntidades('switch');
  const olts = useEntidades('olt');
  const acessos = useEntidades('access_device');
  const swp = useEntidades('switch_provedor');
  const eventos = useEventos();

  return useMemo(() => {
    const doSite = (l?: Entidade[]) => (l ?? []).filter((e) => doSiteFn(e.site, e.connector_id));
    const r = {
      cameras: doSite(cams.data), nvrs: semGravadorRepetido(doSite(nvrs.data)), onus: doSite(onus.data),
      conectores: doSite(cons.data), switches: doSite([...(sws.data ?? []), ...(swp.data ?? [])]), olts: doSite(olts.data), acessos: doSite(acessos.data),
    };
    const todas = [...r.conectores, ...r.olts, ...r.nvrs, ...r.switches, ...r.cameras, ...r.onus, ...r.acessos];
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
  }, [doSiteFn, cams, nvrs, onus, cons, sws, olts, acessos, swp, eventos]);
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
