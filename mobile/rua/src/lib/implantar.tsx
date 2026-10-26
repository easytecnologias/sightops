import { createContext, useContext, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { obter } from './api';
import type { Olt } from './dados';

/*
 * Implantar: tudo aqui manda ordem a equipamento vivo pelo tunel do conector.
 * Nada vai para fila offline: o comando so existe quando chega ao equipamento.
 * As rotas sao as mesmas da tela de Implantacao da web (frontend/js/deploy.js,
 * cameraActivation.js, gravador-canais.js), com os mesmos campos.
 */

/* ───────────────────────── OLT: familia e capacidade ───────────────────────── */

export type OltCompleta = Olt & {
  driver?: string; capabilities?: Record<string, boolean>; capability_notes?: string; host?: string;
};

/** 4840E (EPON) nao lista ONU nao autorizada de forma confiavel: MAC digitado. */
export const ehEpon = (o?: OltCompleta) => String(o?.driver ?? '').toLowerCase() === 'intelbras_4840e';
export const ehVsol = (o?: OltCompleta) => String(o?.driver ?? '').toLowerCase() === 'vsol_epon';
export const pode = (o: OltCompleta | undefined, cap: string) => !!o?.capabilities?.[cap];
export const ponsDa = (o?: OltCompleta) => (ehEpon(o) ? 4 : 8);

export type OnuDescoberta = {
  pon: number; serno_id?: number; serial?: string; onu_serial?: string; onu_mac?: string; mac?: string;
  serial_raw?: string; model?: string; vendor?: string; time_discovered?: string;
};

export function serialDa(d: OnuDescoberta): string {
  return String(d.serial || d.onu_serial || d.onu_mac || d.mac || '').trim();
}

/** Dados que vao em toda chamada de OLT: o servidor completa credencial e conector pelo olt_id. */
export function baseOlt(o: OltCompleta, site: string) {
  return {
    olt_id: o.id, olt_ip: o.ip || o.host || '', olt_name: o.name || '', site: o.site || site,
    olt_vendor: o.vendor || '', olt_model: o.model || '',
    connector_id: o.connector_id || '', remote_connector_id: o.connector_id || '',
  };
}

/* ───────────────────────── historico de acoes (OLT e gravador) ───────────────────────── */

export type AcaoFeita = {
  action: string; ok: number | boolean; pon?: number | string; onu?: number | string; serial?: string;
  vlan?: string; detail?: string; site?: string; olt_name?: string; olt_ip?: string; created_at?: string;
};

export function useAcoes(oltIp = '') {
  return useQuery({
    queryKey: ['acoes', oltIp],
    queryFn: async () => (await obter<{ actions?: AcaoFeita[] }>(
      `/api/olt/onu-actions?limit=60${oltIp ? `&olt_ip=${encodeURIComponent(oltIp)}` : ''}`)).actions ?? [],
    staleTime: 30_000,
  });
}

/** VLAN usada na ultima ONU autorizada com sucesso nesta OLT: o padrao do site. */
export function vlanDoSite(acoes: AcaoFeita[] | undefined): number | null {
  const a = (acoes ?? []).find((x) => x.action === 'add_onu' && x.ok && x.vlan);
  const n = Number(String(a?.vlan ?? '').match(/\d+/)?.[0] ?? '');
  return Number.isFinite(n) && n > 0 ? n : null;
}

export const NOME_ACAO: Record<string, string> = {
  add_onu: 'ONU autorizada', add_onu_bridge: 'Serviço/VLAN aplicado', delete_onu: 'ONU excluída', reboot_onu: 'ONU reiniciada',
  onu_signal: 'Sinal lido', recorder_editar: 'Canal do gravador trocado', recorder_adicionar: 'Câmera posta no gravador',
  recorder_renomear: 'Canal renomeado', recorder_excluir: 'Canal excluído',
};

/* ───────────────────────── rascunho da ONU entre os 3 passos ───────────────────────── */

export type Servico = 'downlink' | 'iptv' | 'tls' | 'management' | 'voice' | 'other';
export const SERVICOS: [Servico, string][] = [
  ['downlink', 'Internet / dados'], ['iptv', 'IPTV / multicast'], ['tls', 'TLS / transparente'],
  ['management', 'Gerência'], ['voice', 'Voz'], ['other', 'Outro serviço'],
];

export type RascunhoOnu = {
  olt?: OltCompleta;
  onu?: OnuDescoberta;          // GPON: a escolhida na descoberta
  macManual?: string;            // EPON/VSOL sem descoberta
  ponManual?: number;
  descricao: string;
  vlan: string;
  servico: Servico;
  tagMode: 'tagged' | 'untagged';      // GPON
  terminal: 'onu' | 'ont';             // GPON
  vlanModeEpon: 'tag' | 'transparent'; // EPON
  portaEpon: string;
  resultado?: Record<string, unknown> & { ok?: boolean };
};

export const ONU_VAZIA: RascunhoOnu = {
  descricao: '', vlan: '', servico: 'downlink', tagMode: 'tagged', terminal: 'onu', vlanModeEpon: 'tag', portaEpon: '1',
};

type Ctx = { r: RascunhoOnu; mudar: (m: Partial<RascunhoOnu>) => void; zerar: (m?: Partial<RascunhoOnu>) => void };
const CtxOnu = createContext<Ctx | null>(null);

export function ProvedorImplantar({ children }: { children: ReactNode }) {
  const [r, setR] = useState<RascunhoOnu>(ONU_VAZIA);
  return (
    <CtxOnu.Provider value={{
      r, mudar: (m) => setR((a) => ({ ...a, ...m })), zerar: (m = {}) => setR({ ...ONU_VAZIA, ...m }),
    }}>{children}</CtxOnu.Provider>
  );
}
export function useRascunhoOnu(): Ctx {
  const c = useContext(CtxOnu);
  if (!c) throw new Error('fora do ProvedorImplantar');
  return c;
}
