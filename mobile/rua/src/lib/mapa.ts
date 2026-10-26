import { useQuery } from '@tanstack/react-query';
import { obter, remendar } from './api';

/*
 * Mapa de campo: o mesmo dado do mapa da web (frontend/js/mapaCaixas.js).
 * Caixas, cabos e CTOs moram no meta de cada camada KMZ
 * (GET /api/kmz/import/layers); cabo novo vai por
 * PATCH /api/kmz/import/layers/{id} {cabo:{...}} -- o servidor mede o traçado,
 * confere porta e camera repetida e atualiza o inventario da camera.
 */

export type Ponto = [number, number];   // [lat, lng]

export type Caixa = {
  id: string; ponto?: string; nome?: string; tipo?: 'switch' | 'onu' | 'passagem' | string;
  lat?: number | null; lng?: number | null; portas?: number; itens?: { tipo: string; qtd?: number }[];
  switch_vlan?: string | number;
};
export type Cabo = {
  id: string; caixa: string; camera?: { ponto?: string; ip?: string }; cto?: { ponto?: string; porta?: number | null };
  tipo?: string; porta?: number | null; caminho?: Ponto[]; metros?: number; metros_com_folga?: number;
};
type Feature = { geometry?: { type?: string; coordinates?: unknown }; properties?: { name?: string; Name?: string } };
export type Camada = {
  id: string; label: string; caixas: Record<string, Caixa>; cabos: Record<string, Cabo>;
  ctos?: Record<string, { id?: string; nome?: string; ponto?: string; lat?: number | null; lng?: number | null }>;
  features?: Feature[];
};

export const TIPOS_CABO: [string, string][] = [['utp6', 'UTP Cat6'], ['utp5e', 'UTP Cat5e'], ['drop', 'Fibra drop']];
export const LIMITE_UTP = 100;

export function useCamadas() {
  return useQuery({
    queryKey: ['camadas'],
    queryFn: async () => (await obter<{ layers?: Camada[] }>('/api/kmz/import/layers?include_features=true')).layers ?? [],
    staleTime: 5 * 60_000,
  });
}

const nomeDe = (f: Feature) => String(f.properties?.name ?? f.properties?.Name ?? '').trim();

/** Pontos nomeados da camada (o KMZ guarda [lng, lat]). */
export function pontosDa(c: Camada): { nome: string; p: Ponto }[] {
  const saida: { nome: string; p: Ponto }[] = [];
  for (const f of c.features ?? []) {
    if (f.geometry?.type !== 'Point') continue;
    const xy = f.geometry.coordinates as number[];
    if (Array.isArray(xy) && xy.length >= 2) saida.push({ nome: nomeDe(f), p: [Number(xy[1]), Number(xy[0])] });
  }
  return saida;
}

/** Linhas do KMZ (rotas desenhadas), em [lat, lng]. */
export function linhasDa(c: Camada): Ponto[][] {
  const saida: Ponto[][] = [];
  for (const f of c.features ?? []) {
    if (f.geometry?.type !== 'LineString') continue;
    const l = (f.geometry.coordinates as number[][]).map((xy) => [Number(xy[1]), Number(xy[0])] as Ponto);
    if (l.length > 1) saida.push(l);
  }
  return saida;
}

/** Posicao da caixa: a gravada, ou a do ponto do KMZ com o mesmo nome (caixas antigas). */
export function posicaoDaCaixa(cx: Caixa, c: Camada): Ponto | null {
  if (cx.lat != null && cx.lng != null) return [Number(cx.lat), Number(cx.lng)];
  const alvo = String(cx.ponto ?? '').trim().toLowerCase();
  const achado = pontosDa(c).find((x) => x.nome.toLowerCase() === alvo);
  return achado ? achado.p : null;
}

export function distancia(a: Ponto, b: Ponto): number {
  const R = 6371000;
  const rad = (g: number) => (g * Math.PI) / 180;
  const dLat = rad(b[0] - a[0]);
  const dLng = rad(b[1] - a[1]);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

export function metrosDo(caminho: Ponto[]): number {
  let m = 0;
  for (let i = 1; i < caminho.length; i++) m += distancia(caminho[i - 1], caminho[i]);
  return m;
}

export function cabosDaCaixa(c: Camada, cx: Caixa): Cabo[] {
  return Object.values(c.cabos ?? {}).filter((k) => k.caixa === cx.id && !k.cto);
}

export function portasLivres(c: Camada, cx: Caixa): number[] {
  const usadas = new Set(cabosDaCaixa(c, cx).map((k) => Number(k.porta)).filter(Boolean));
  return Array.from({ length: Number(cx.portas ?? 0) }, (_, i) => i + 1).filter((p) => !usadas.has(p));
}

export async function gravarCabo(camada: string, cabo: {
  caixa: string; camera: { ip?: string; ponto?: string }; tipo: string; porta?: number | null; caminho: Ponto[];
}): Promise<{ caixas: Record<string, Caixa>; cabos: Record<string, Cabo> }> {
  return remendar(`/api/kmz/import/layers/${encodeURIComponent(camada)}`, { cabo: { ...cabo, folga_pct: 10 } });
}
