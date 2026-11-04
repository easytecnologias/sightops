import { createContext, createElement, useContext, useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { enviar, obter } from './api';

/* ───────────── formatos ───────────── */
export const moeda = (c: number | null | undefined) =>
  c === null || c === undefined ? '–' : (Number(c) / 100).toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
export const num = (n: number | null | undefined) => Number(n || 0).toLocaleString('pt-BR');
export const dec = (n: number | null | undefined) =>
  n === null || n === undefined ? '–' : Number(n).toLocaleString('pt-BR', { maximumFractionDigits: 1 });
export const pct = (parte: number, todo: number) =>
  todo ? `${(100 * parte / todo).toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%` : '–';
export const hora = (ts?: string | null) => String(ts || '').slice(11, 19);
export const hm = (ts?: string | null) => String(ts || '').slice(11, 16);
export const plural = (n: number, um: string, varios: string) => `${num(n)} ${n === 1 ? um : varios}`;
export function tempo(s: number | null | undefined) {
  if (s === null || s === undefined) return '–';
  const m = Math.floor(s / 60), r = Math.round(s % 60);
  return m ? `${m} min ${String(r).padStart(2, '0')} s` : `${r} s`;
}
export function hoje() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function mudarDia(dia: string, delta: number) {
  const d = new Date(`${dia}T12:00:00`);
  d.setDate(d.getDate() + delta);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
export function diaRotulo(dia: string) {
  if (dia === hoje()) return 'Hoje';
  if (dia === mudarDia(hoje(), -1)) return 'Ontem';
  const [a, m, d] = dia.split('-');
  return `${d}/${m}/${a}`;
}
export function iniciais(nome: string) {
  const p = String(nome || '').trim().split(/\s+/).filter(Boolean);
  return ((p[0]?.[0] || '') + (p.length > 1 ? p[p.length - 1][0] : '')).toUpperCase() || '?';
}
export const SEM_LOJA = 'Sem loja definida';

/* ───────────── filtro do app: dia e loja (valem em todas as telas) ───────────── */
type Filtro = { dia: string; loja: string; setDia: (d: string) => void; setLoja: (l: string) => void };
const CtxFiltro = createContext<Filtro | null>(null);
export function ProvedorFiltro({ children }: { children: ReactNode }) {
  const [dia, setDia] = useState(hoje());
  const [loja, setLoja] = useState('');
  return createElement(CtxFiltro.Provider, { value: { dia, loja, setDia: (d) => setDia(d > hoje() ? hoje() : d), setLoja } }, children);
}
export function useFiltro(): Filtro {
  const f = useContext(CtxFiltro);
  if (!f) throw new Error('sem filtro');
  return f;
}

/* ───────────── tipos ───────────── */
export type Caixa = { id: string; nome: string; numero: number; site: string; connector_id: string; gravador_host: string; gravador_canal: number; ativo: number; ultimo_contato?: string };
export type Cupom = { caixa_id: string; caixa: string; dia: string; cupom: string; operador: string; aberto_em: string; fechado_em: string; situacao: string; itens: number; itens_cancelados: number; digitados: number; menu: number; total_centavos: number; pagamento: string };
export type Evento = { seq?: number; ts: string; tipo: string; cupom?: string; operador?: string; codigo?: string; descricao?: string; valor_centavos?: number };
export type Item = { seq: number; ts: string; codigo: string; descricao: string; quant: number; valor_centavos: number; modo: string };
export type Detalhe = { caixa: Caixa; cupom: Cupom; itens: Item[]; linha_do_tempo: Evento[] };
export type Conferencia = { passado: number; cupons_cancelados: number; abertos: number; itens_cancelados: number; descontos: number; sem_cupom: number; desc_item: number; desc_subtotal: number; desc_outros: number };
export type Desconto = { caixa_id: string; caixa: string; ts: string; cupom: string; operador: string; tipo: 'item' | 'subtotal'; produto: string; codigo: string; valor_centavos: number };
export type Resumo = { dia: string; itens: number; modos: Record<string, { n: number; centavos: number }>; cupons: Record<string, number>; vendido_centavos: number; eventos: Record<string, number>; conferencia?: Conferencia; descontos?: Desconto[]; lojas?: string[] };
export type CaixaLoja = { id: string; nome: string; numero: number; estado: string; parado_min?: number; cupons: number; vendido_centavos: number; operador?: string };
export type Loja = { nome: string; caixas: CaixaLoja[]; n_caixas: number; coletando: number; cupons: number; vendido_centavos: number; itens: number; bipados: number; cancelados: number; sem_cadastro: number; revisar: number; cancelados_por_mil: number };
export type Alerta = { caixa_id: string; caixa: string; loja: string; ts: string; tipo: string; cupom: string; codigo: string; descricao: string; valor_centavos: number };
export type Lojas = { dia: string; hoje: boolean; lojas: Loja[]; rede: Loja; alertas: Alerta[] };
export type Rank = { chave: string; nome: string; loja: string; outros: string[]; dias: number; cupons: number; vendido: number; itens: number; digitados: number; ticket: number; itens_por_cupom: number; tempo_mediano_s: number | null; seg_por_item: number | null; horas_atendendo: number; vendido_por_hora: number | null; pct_digitado: number; cancelados_por_mil: number; itens_cancelados: number; valor_cancelado: number; cupons_cancelados: number; descontos: number; sem_cadastro: number; sangrias: number; valor_sangrias: number; gaveta_fora: number };
export type Rankings = { de: string; ate: string; lojas: string[]; minimo_cupons: number; operadores: Rank[]; caixas: Rank[] };
export type EventoDia = { caixa_id: string; caixa: string; ts: string; cupom: string; operador: string; codigo: string; descricao: string; valor_centavos: number; situacao: string | null; total_centavos: number | null; operador_cupom: string | null };
export type CaixaVivo = CaixaLoja & { cupom: { cupom: string; situacao: string; aberto: boolean; operador: string; aberto_em: string; itens: number; total_centavos: number }; ultimos: { ts: string; descricao: string; valor_centavos: number; modo: string }[] };
export type Vivo = { dia: string; lojas: string[]; loja: Loja | null; caixas: CaixaVivo[]; alertas: Alerta[] };

/* ───────────── dados ───────────── */
const q = encodeURIComponent;
export const useCaixas = () => useQuery({ queryKey: ['caixas'], staleTime: 300_000,
  queryFn: async () => (await obter<{ caixas: Caixa[] }>('/api/pdv/caixas')).caixas || [] });
export const useResumo = (dia: string, loja: string) => useQuery({ queryKey: ['resumo', dia, loja], refetchInterval: dia === hoje() ? 30_000 : false,
  queryFn: () => obter<Resumo>(`/api/pdv/resumo?dia=${dia}&loja=${q(loja)}`) });
export const useLojas = (dia: string) => useQuery({ queryKey: ['lojas', dia], refetchInterval: dia === hoje() ? 30_000 : false,
  queryFn: () => obter<Lojas>(`/api/pdv/lojas?dia=${dia}`) });
export const useCupons = (dia: string, texto = '', ligado = true) => useQuery({ queryKey: ['cupons', dia, texto], enabled: ligado,
  queryFn: async () => (await obter<{ cupons: Cupom[] }>(`/api/pdv/cupons?dia=${dia}&texto=${q(texto)}&limite=5000`)).cupons || [] });
export const useEventos = (dia: string, tipo: string, ligado = true) => useQuery({ queryKey: ['eventos', dia, tipo], enabled: ligado,
  queryFn: async () => (await obter<{ eventos: EventoDia[] }>(`/api/pdv/eventos?dia=${dia}&tipo=${tipo}`)).eventos || [] });
export const useDetalhe = (caixa: string, dia: string, cupom: string) => useQuery({ queryKey: ['cupom', caixa, dia, cupom],
  queryFn: () => obter<Detalhe>(`/api/pdv/cupons/${q(caixa)}/${dia}/${q(cupom)}`) });
export const useRankings = (de: string, ate: string, loja: string) => useQuery({ queryKey: ['rankings', de, ate, loja], staleTime: 120_000,
  queryFn: () => obter<Rankings>(`/api/pdv/rankings?de=${de}&ate=${ate}&loja=${q(loja)}`) });
export const useVivo = (loja: string) => useQuery({ queryKey: ['vivo', loja], refetchInterval: 4000,
  queryFn: () => obter<Vivo>(`/api/pdv/ao-vivo-loja?loja=${q(loja)}`) });
export const useCupomVivo = (caixa: string) => useQuery({ queryKey: ['cupomVivo', caixa], refetchInterval: 2500,
  queryFn: () => obter<{ cupom: Cupom | null; itens: Item[] }>(`/api/pdv/ao-vivo/${q(caixa)}`) });

/* ───────────── video ───────────── */
export type Janela = { host: string; canal: number; connector_id: string; inicio: string; momento_caixa: string };
/** Gravacao do caixa a partir de `ts` (horario do caixa), `antes` segundos antes. */
export async function janelaVideo(caixa: string, ts: string, antes: number): Promise<Janela> {
  const j = await obter<Janela>(`/api/pdv/video/${q(caixa)}?ts=${q(ts)}&antes=${antes}&depois=45`);
  if (!j?.host) throw new Error('Este caixa ainda não tem gravador e canal configurados.');
  return j;
}
export async function streamGravacao(j: Janela): Promise<string> {
  const r = await enviar<{ stream_name?: string; detail?: string }>('/api/nvr/driver/playback',
    { host: j.host, http_port: 80, canal: j.canal, inicio: j.inicio, connector_id: j.connector_id });
  if (!r.stream_name) throw new Error(r.detail || 'Não consegui abrir a gravação.');
  return r.stream_name;
}
export async function streamAoVivo(c: Caixa): Promise<string> {
  const r = await enviar<{ stream_name?: string; detail?: string }>('/api/deployments/recorder-live-stream',
    { recorder_host: c.gravador_host, canal: Number(c.gravador_canal), connector_id: c.connector_id, alta: 0 });
  if (!r.stream_name) throw new Error(r.detail || 'Não consegui abrir o vídeo.');
  return r.stream_name;
}

/* ───────────── nomes ───────────── */
export const MODO: Record<string, string> = { scanner: 'bipado', manual: 'digitado', menu: 'menu', outro: 'outro', sem_tecla: 'sem tecla' };
export const EVENTO: Record<string, string> = {
  ABRECUPOM: 'Cupom aberto', VIT: 'Item', CIT: 'Item cancelado', SBT: 'Subtotal', FIN: 'Pagamento', TRC: 'Troco',
  FECHACUPOM: 'Cupom fechado', CCV: 'Cupom cancelado', CCG: 'Cancelamento de cupom anterior', SUP: 'Liberação de supervisor',
  SUPERVISOR: 'Supervisor', GER: 'Tecla de gerente', GAV: 'Gaveta aberta', SGR: 'Sangria', DIT: 'Desconto no item',
  DST: 'Subtotal com desconto', DAS: 'Desconto no subtotal', ITEMSEMCAD: 'Código sem cadastro', CLIENTE: 'Cliente identificado',
};
export function textoEvento(e: Evento) {
  const nome = EVENTO[e.tipo] || e.tipo;
  const desc = ['CIT', 'DIT', 'FIN', 'SUPERVISOR', 'ITEMSEMCAD', 'SGR'].includes(e.tipo) && (e.descricao || e.codigo) ? ` · ${e.descricao || e.codigo}` : '';
  return nome + desc;
}
export function textoAlerta(a: Alerta) {
  const v = a.valor_centavos ? ` ${moeda(a.valor_centavos)}` : '';
  switch (a.tipo) {
    case 'CIT': return `Item cancelado: ${a.descricao || a.codigo || '?'}${v}`;
    case 'CCV': return `Cupom ${a.cupom} cancelado${v}`;
    case 'CCG': return `Cupom anterior cancelado${v}`;
    case 'ITEMSEMCAD': return `Código sem cadastro: ${a.codigo || '?'}`;
    case 'DST': return `Desconto no subtotal do cupom ${a.cupom}`;
    case 'SGR': return `Sangria${v}`;
    default: return a.tipo;
  }
}
