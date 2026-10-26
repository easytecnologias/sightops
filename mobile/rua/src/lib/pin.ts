import { pegar, salvar, apagar } from './storage';

/**
 * PIN de desbloqueio rapido.
 *
 * O PIN NAO substitui a senha no servidor: ele so destrava a sessao que ja esta
 * guardada no aparelho. Fica guardado como hash com sal, nunca em texto. Depois
 * de 5 erros o app esquece a sessao e pede usuario e senha de novo.
 */
const CHAVE = 'rua.pin';
const CHAVE_ERROS = 'rua.pin.erros';
export const MAX_ERROS = 5;

async function hash(pin: string, sal: string): Promise<string> {
  const dados = new TextEncoder().encode(`${sal}:${pin}`);
  const d = await crypto.subtle.digest('SHA-256', dados);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export async function temPin(): Promise<boolean> {
  return !!(await pegar(CHAVE));
}

export async function criarPin(pin: string): Promise<void> {
  const sal = [...crypto.getRandomValues(new Uint8Array(12))].map((b) => b.toString(16)).join('');
  await salvar(CHAVE, `${sal}$${await hash(pin, sal)}`);
  await salvar(CHAVE_ERROS, '0');
}

export async function apagarPin(): Promise<void> {
  await apagar(CHAVE);
  await apagar(CHAVE_ERROS);
}

/** true = certo. Devolve tambem quantas tentativas sobram. */
export async function conferirPin(pin: string): Promise<{ ok: boolean; restam: number }> {
  const guardado = (await pegar(CHAVE)) || '';
  const [sal, h] = guardado.split('$');
  if (!sal || !h) return { ok: false, restam: 0 };
  if ((await hash(pin, sal)) === h) {
    await salvar(CHAVE_ERROS, '0');
    return { ok: true, restam: MAX_ERROS };
  }
  const erros = Number((await pegar(CHAVE_ERROS)) || '0') + 1;
  await salvar(CHAVE_ERROS, String(erros));
  return { ok: false, restam: Math.max(0, MAX_ERROS - erros) };
}
