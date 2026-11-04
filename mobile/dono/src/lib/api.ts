import { Capacitor } from '@capacitor/core';
import { pegar, salvar, apagar } from './storage';

/**
 * Cliente da API do SightOps (mesmo do app Acesso).
 * Dentro do APK o endereco e completo; no navegador passa pelo proxy do Vite.
 * O CapacitorHttp faz as chamadas pelo lado nativo, sem CORS.
 */
export const SERVIDOR = 'https://sightops.easytecnologias.com.br';
export const API_BASE = Capacitor.isNativePlatform() ? SERVIDOR : '';

const CHAVE_TOKEN = 'pdv.token';
let _token: string | null = null;

export async function carregarToken(): Promise<string | null> {
  _token = await pegar(CHAVE_TOKEN);
  return _token;
}

export class ErroApi extends Error {
  status: number;
  constructor(mensagem: string, status: number) {
    super(mensagem);
    this.name = 'ErroApi';
    this.status = status;
  }
}

function cabecalhos(json: boolean): Headers {
  const h = new Headers();
  if (json) h.set('Content-Type', 'application/json');
  if (_token) h.set('Authorization', `Bearer ${_token}`);
  return h;
}

async function detalhe(res: Response): Promise<string> {
  const d = await res.json().catch(() => ({}));
  const t = (d as { detail?: unknown })?.detail;
  if (typeof t === 'string' && t) return t;
  if (res.status === 403) return 'Seu usuário não tem permissão para isto.';
  if (res.status === 428) return 'O gravador não tem senha guardada no SightOps.';
  return `Erro ${res.status} no servidor.`;
}

async function pedir<T>(metodo: string, caminho: string, corpo?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_BASE + caminho, {
      method: metodo,
      credentials: 'same-origin',
      headers: cabecalhos(corpo !== undefined),
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ErroApi('Sem conexão com o servidor.', 0);
  }
  if (res.status === 401) throw new ErroApi('Sessão expirada. Entre de novo.', 401);
  if (!res.ok) throw new ErroApi(await detalhe(res), res.status);
  return (await res.json()) as T;
}

export const obter = <T,>(c: string) => pedir<T>('GET', c);
export const enviar = <T,>(c: string, corpo: unknown = {}) => pedir<T>('POST', c, corpo);

export async function entrar(usuario: string, senha: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(API_BASE + '/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: usuario, password: senha, label: 'app-pdv' }),
    });
  } catch {
    throw new ErroApi('Sem conexão com o servidor.', 0);
  }
  if (!res.ok) {
    const m = await detalhe(res);
    throw new ErroApi(res.status === 401 ? 'Usuário ou senha incorretos.' : m, res.status);
  }
  const d = (await res.json()) as { access_token?: string; token?: string };
  _token = d.access_token || d.token || null;
  if (!_token) throw new ErroApi('O servidor não devolveu a sessão.', 500);
  await salvar(CHAVE_TOKEN, _token);
}

export async function sair(): Promise<void> {
  try { await fetch(API_BASE + '/api/auth/logout', { method: 'POST', headers: cabecalhos(false) }); } catch { /* sem rede */ }
  _token = null;
  await apagar(CHAVE_TOKEN);
}
