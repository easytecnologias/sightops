import { createContext, useContext, useState, type ReactNode } from 'react';
import { enviar, obter, trocar } from './api';
import { cpfValido, digitos } from './cpf';
import type { ListaPessoas, Pessoa } from './dados';
import type { Foto } from '../ui/Camera';

/**
 * Rascunho do cadastro, vivo entre os tres passos (foto, dados, portas).
 * Editar alguem existente usa o mesmo rascunho, com `existente` preenchido.
 */
export type Rascunho = {
  existente?: Pessoa;
  foto?: Foto;
  tipo: string;
  nome: string;
  cpf: string;
  matricula: string;
  turma: string;
  responsavel: string;
  telefone: string;
  whatsapp: boolean;
  email: string;
  avisaEmail: boolean;
  notas: string;
  grupos: string[];
};

export const RASCUNHO_VAZIO: Rascunho = {
  tipo: '', nome: '', cpf: '', matricula: '', turma: '', responsavel: '', telefone: '',
  whatsapp: true, email: '', avisaEmail: true, notas: '', grupos: [],
};

export function rascunhoDe(p: Pessoa): Rascunho {
  return {
    existente: p, tipo: p.tipo, nome: p.nome, cpf: p.cpf, matricula: p.matricula, turma: p.turma,
    responsavel: p.responsavel, telefone: p.telefone, whatsapp: p.whatsapp,
    email: p.email, avisaEmail: p.avisa_email, notas: p.notas, grupos: [...p.grupos],
  };
}

type Ctx = { r: Rascunho; mudar: (m: Partial<Rascunho>) => void; zerar: (base?: Partial<Rascunho>) => void };
const CtxCadastro = createContext<Ctx | null>(null);

export function ProvedorCadastro({ children }: { children: ReactNode }) {
  const [r, setR] = useState<Rascunho>(RASCUNHO_VAZIO);
  const mudar = (m: Partial<Rascunho>) => setR((a) => ({ ...a, ...m }));
  const zerar = (base: Partial<Rascunho> = {}) => setR({ ...RASCUNHO_VAZIO, ...base });
  return <CtxCadastro.Provider value={{ r, mudar, zerar }}>{children}</CtxCadastro.Provider>;
}
export function useCadastro(): Ctx {
  const c = useContext(CtxCadastro);
  if (!c) throw new Error('fora do ProvedorCadastro');
  return c;
}

/** Ja existe alguem com este CPF ou matricula: o app abre essa pessoa. */
export class ErroDuplicado extends Error {
  pessoa: Pessoa;
  campo: 'CPF' | 'matrícula';
  constructor(pessoa: Pessoa, campo: 'CPF' | 'matrícula') {
    super(`${campo === 'CPF' ? 'Este CPF' : 'Esta matrícula'} já é de ${pessoa.nome}.`);
    this.pessoa = pessoa;
    this.campo = campo;
  }
}

/** Confere os campos com as mesmas regras do cadastro da web. Devolve o erro ou ''. */
export function conferir(r: Rascunho, cpfOpcional: boolean): Record<string, string> {
  const e: Record<string, string> = {};
  if (r.nome.trim().replace(/\s+/g, ' ').length < 3) e.nome = 'Informe o nome completo.';
  const cpf = digitos(r.cpf);
  const semCpfOk = cpfOpcional || !!r.existente?.id_controladora;
  if (!cpf && !semCpfOk) e.cpf = 'Informe o CPF.';
  else if (cpf && !cpfValido(cpf)) e.cpf = 'CPF inválido. Confira os 11 dígitos.';
  if (r.tipo === 'student' && !r.matricula.trim()) e.matricula = 'Informe a matrícula do aluno.';
  if (r.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(r.email.trim())) e.email = 'E-mail inválido.';
  return e;
}

/**
 * Antes de criar: procura CPF e matricula no cliente inteiro.
 *
 * Sem `id`, o servidor (save_person) casa por CPF/matricula e faz UPDATE
 * COMPLETO de quem ja existe -- gravaria por cima de outra pessoa sem avisar.
 * Por isso a busca e aqui, antes, e a tela oferece abrir quem ja existe.
 */
export async function procurarDuplicado(r: Rascunho): Promise<void> {
  if (r.existente) return;
  const cpf = digitos(r.cpf);
  const mat = r.tipo === 'student' ? r.matricula.trim() : '';
  if (!cpf && !mat) return;
  const todos = await obter<ListaPessoas>('/api/access-control/painel/pessoas');
  const porCpf = cpf ? todos.pessoas.find((p) => digitos(p.cpf) === cpf) : undefined;
  if (porCpf) throw new ErroDuplicado(porCpf, 'CPF');
  const porMat = mat ? todos.pessoas.find((p) => p.matricula === mat) : undefined;
  if (porMat) throw new ErroDuplicado(porMat, 'matrícula');
}

export type Resultado = { id: string; avisos: string[] };

/**
 * Grava na mesma ordem do painel web (frontend/acesso/pessoas.js psSalvar):
 * 1. POST /people   2. POST /people/{id}/face-photo   3. PUT /painel/pessoas/{id}/grupos
 * O envio aos leitores e feito pelo servidor em segundo plano.
 */
export async function salvar(r: Rascunho, site: string): Promise<Resultado> {
  await procurarDuplicado(r);
  const p = r.existente;
  const corpo: Record<string, unknown> = {
    id: p?.id || '',
    full_name: r.nome.trim().replace(/\s+/g, ' '),
    person_type: r.tipo,
    document_id: digitos(r.cpf),
    enrollment_code: r.tipo === 'student' ? r.matricula.trim() : (p?.matricula || ''),
    class_name: r.turma.trim(),
    site: p?.site || site,
    controller_user_id: p?.id_controladora || '',
    guardian_name: r.responsavel.trim(),
    guardian_phone: digitos(r.telefone),
    whatsapp_enabled: r.whatsapp,
    active: p ? p.ativo : true,
    notes: r.notas.trim(),
  };
  // E-mail vai sempre: o servidor faz UPDATE de tudo, e o campo esta na tela.
  corpo.guardian_email = r.email.trim();
  corpo.email_enabled = r.avisaEmail;

  const salvo = await enviar<{ person?: { id?: string } }>('/api/access-control/people', corpo);
  const id = salvo.person?.id;
  if (!id) throw new Error('O servidor não devolveu a pessoa salva.');
  const avisos: string[] = [];

  if (r.foto) {
    const fd = new FormData();
    fd.append('file', r.foto.blob, 'rosto.jpg');
    try { await enviar(`/api/access-control/people/${encodeURIComponent(id)}/face-photo`, fd); } catch (e) {
      avisos.push(`A foto não foi aceita: ${(e as Error).message}`);
    }
  }

  const antes = [...(p?.grupos ?? [])].sort().join();
  const agora = [...r.grupos].sort().join();
  if (agora !== antes && (r.grupos.length || p)) {
    try {
      const g = await trocar<{ falhas_remocao?: { leitor: string; erro: string }[] }>(
        `/api/access-control/painel/pessoas/${encodeURIComponent(id)}/grupos`, { grupos: r.grupos });
      for (const f of g.falhas_remocao ?? []) avisos.push(`Não consegui tirar do leitor ${f.leitor}: ${f.erro}`);
    } catch (e) {
      avisos.push(`As portas não foram gravadas: ${(e as Error).message}`);
    }
  }
  return { id, avisos };
}
