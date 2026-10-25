import { useQuery } from '@tanstack/react-query';
import { obter } from './api';
import { useLocal } from './local';

/* Formas que a API devolve, conferidas no backend:
   /api/auth/me                            -> {user}
   /api/access-control/painel/visao-geral  -> {perfil, leitores, pessoas, fotos}  (access_control_painel.visao_geral)
   /api/access-control/painel/ao-vivo      -> {resumo, passagens}                 (access_control_painel.ao_vivo)
   /api/access-control/painel/pessoas      -> {pessoas, grupos, perfil, sites}    (access_control_pessoas.pessoas)
   /api/access-control/whatsapp/triage     -> {items, summary}                    (access_control_whatsapp_inbound) */

export type Usuario = { username?: string; full_name?: string; role?: string; tenant_name?: string };

export type Local = { site: string; tipo: string; origem?: string };
export type Perfil = { tipo: string; locais: Local[] };

export type Leitor = { id: string; nome: string; site: string; status: string; visto?: string };

export type VisaoGeral = {
  perfil: Perfil;
  leitores: { total: number; online: number; lista: Leitor[] };
  pessoas: { total: number; ativas: number };
  fotos: { ok: number; falhou: number; pendente: number };
};

export type Passagem = {
  id: string; hora: string; tipo: string; porta: string; pessoa_id: string;
  nome: string; turma: string; tipo_pessoa: string; tem_foto: boolean;
};
export type AoVivo = {
  resumo: { total?: number; entries?: number; exits?: number; inside_now?: number };
  passagens: Passagem[];
};

export type SituacaoLeitor = { leitor_id: string; leitor: string; status: string; erro: string; quando: string };
export type Pessoa = {
  id: string; nome: string; tipo: string; cpf: string; matricula: string; turma: string; site: string;
  id_controladora: string; responsavel: string; telefone: string; whatsapp: boolean; ativo: boolean;
  email: string; avisa_email: boolean; notas: string; tem_foto: boolean; foto_em: string;
  grupos: string[]; leitores: SituacaoLeitor[]; ultima: string;
};
export type Grupo = {
  id: string; nome: string; site: string; ativo: boolean; membros: number;
  leitores: { id: string; nome: string }[];
};
export type ListaPessoas = { pessoas: Pessoa[]; grupos: Grupo[]; perfil: Perfil; sites: string[] };

export type ItemTriagem = {
  id: string; status: string; reasons: string[]; from_name: string; from_number: string;
  raw_text: string; photo_base64?: string; photo_url?: string; created_at: string;
  suggested: {
    full_name?: string; person_type?: string; document_id?: string; enrollment_code?: string;
    class_name?: string; site?: string; guardian_name?: string; guardian_phone?: string; group_name?: string;
  };
};
export type Triagem = { items: ItemTriagem[]; summary: { ready: number; review: number; duplicate: number } };

const q = (site: string) => (site ? `?site=${encodeURIComponent(site)}` : '');

export function useEu() {
  return useQuery({
    queryKey: ['eu'],
    queryFn: async () => (await obter<{ user?: Usuario }>('/api/auth/me')).user ?? {},
    retry: false,
  });
}

/** Sem local: todos os locais do cliente, com o tipo de cada um e os leitores. */
export function useVisaoGeral(site = '') {
  return useQuery({
    queryKey: ['visao', site],
    queryFn: () => obter<VisaoGeral>(`/api/access-control/painel/visao-geral${q(site)}`),
  });
}

export function useAoVivo() {
  const site = useLocal();
  return useQuery({
    queryKey: ['aovivo', site],
    queryFn: () => obter<AoVivo>(
      `/api/access-control/painel/ao-vivo?limit=15${site ? `&site=${encodeURIComponent(site)}` : ''}`),
    refetchInterval: 20_000,
    staleTime: 10_000,
  });
}

export function usePessoas() {
  const site = useLocal();
  return useQuery({
    queryKey: ['pessoas', site],
    queryFn: () => obter<ListaPessoas>(`/api/access-control/painel/pessoas${q(site)}`),
  });
}

export function useTriagem() {
  return useQuery({
    queryKey: ['triagem'],
    queryFn: () => obter<Triagem>('/api/access-control/whatsapp/triage'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

/** Itens que ainda pedem decisao, do local escolhido (ou sem local definido). */
export function pendentes(t: Triagem | undefined, site: string): ItemTriagem[] {
  return (t?.items ?? []).filter((i) =>
    ['ready', 'review', 'duplicate'].includes(i.status)
    && (!site || !i.suggested?.site || i.suggested.site.toUpperCase() === site.toUpperCase()));
}

export function tipoDoLocal(perfil: Perfil | undefined, site: string): string {
  const l = perfil?.locais?.find((x) => x.site.toUpperCase() === site.toUpperCase());
  if (l) return l.tipo;
  return perfil?.tipo && perfil.tipo !== 'misto' ? perfil.tipo : 'escola';
}

/** Resumo dos leitores de uma pessoa: "4/4 leitores", "3/4 · enviando". */
export function resumoLeitores(p: Pessoa): { texto: string; cor: 'verde' | 'ambar' | 'cinza' | 'vermelho' } {
  const total = p.leitores.length;
  if (!p.tem_foto) return { texto: 'sem foto', cor: 'ambar' };
  if (!total) return { texto: 'sem leitor', cor: 'cinza' };
  const ok = p.leitores.filter((l) => l.status === 'ok').length;
  const falhou = p.leitores.filter((l) => l.status === 'failed').length;
  if (falhou) return { texto: `${ok}/${total} · ${falhou} recusou`, cor: 'vermelho' };
  if (ok < total) return { texto: `${ok}/${total} · enviando`, cor: 'cinza' };
  return { texto: `${ok}/${total} leitores`, cor: 'verde' };
}
