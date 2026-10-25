/* Vocabulario por tipo de local: o mesmo do painel web (frontend/acesso/
   acesso.js AP_VOCAB e pessoas.js PS_TIPOS). Escola fala de aluno e turma;
   condominio de morador e unidade; empresa de colaborador e setor. */
export type TipoLocal = 'escola' | 'condominio' | 'empresa' | 'evento';

type Vocab = {
  nome: string;
  grupo: string;
  exemploGrupo: string;
  dentro: string;
  contato: string;
  tipos: [string, string][];
  nomes: Record<string, string>;
};

export const VOCAB: Record<TipoLocal, Vocab> = {
  escola: {
    nome: 'Escola', grupo: 'Turma', exemploGrupo: 'Ex.: 4º Ano', dentro: 'Presentes', contato: 'Responsável',
    tipos: [['student', 'Aluno'], ['employee', 'Funcionário'], ['visitor', 'Visitante']],
    nomes: { student: 'Aluno', employee: 'Funcionário', visitor: 'Visitante', resident: 'Morador' },
  },
  condominio: {
    nome: 'Condomínio', grupo: 'Unidade', exemploGrupo: 'Ex.: A01, Bloco C 06', dentro: 'Dentro agora', contato: 'Contato',
    tipos: [['resident', 'Morador'], ['employee', 'Funcionário'], ['contractor', 'Prestador'], ['visitor', 'Visitante']],
    nomes: { student: 'Morador', resident: 'Morador', employee: 'Funcionário', visitor: 'Visitante', contractor: 'Prestador' },
  },
  empresa: {
    nome: 'Empresa', grupo: 'Setor', exemploGrupo: 'Ex.: Financeiro', dentro: 'No prédio', contato: 'Contato',
    tipos: [['employee', 'Colaborador'], ['contractor', 'Prestador'], ['visitor', 'Visitante']],
    nomes: { student: 'Colaborador', employee: 'Colaborador', resident: 'Colaborador', contractor: 'Prestador', visitor: 'Visitante' },
  },
  evento: {
    nome: 'Evento', grupo: 'Credencial', exemploGrupo: 'Ex.: VIP, Imprensa', dentro: 'No evento', contato: 'Contato',
    tipos: [['participant', 'Participante'], ['staff', 'Equipe'], ['visitor', 'Convidado']],
    nomes: { student: 'Participante', participant: 'Participante', staff: 'Equipe', employee: 'Equipe', resident: 'Participante', visitor: 'Convidado' },
  },
};

const EQUIVALE: Record<TipoLocal, Record<string, string>> = {
  escola: { resident: 'student', participant: 'student', staff: 'employee', contractor: 'employee' },
  condominio: { student: 'resident', participant: 'resident', staff: 'employee' },
  empresa: { student: 'employee', resident: 'employee', participant: 'employee', staff: 'employee' },
  evento: { student: 'participant', resident: 'participant', employee: 'staff', contractor: 'staff' },
};

export function vocab(t?: string): Vocab {
  return VOCAB[t as TipoLocal] || VOCAB.escola;
}

/** Tipo gravado antigo que nao existe neste local vira o equivalente. */
export function tipoNoLocal(tipo: string, local: string): string {
  const v = vocab(local);
  if (v.tipos.some(([t]) => t === tipo)) return tipo;
  const eq = (EQUIVALE[local as TipoLocal] || {})[tipo];
  return eq && v.tipos.some(([t]) => t === eq) ? eq : v.tipos[0][0];
}

export function nomeTipo(tipo: string, local: string): string {
  return vocab(local).nomes[tipo] || tipo || '';
}
