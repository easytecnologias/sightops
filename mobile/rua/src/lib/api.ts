import { Capacitor } from '@capacitor/core';
import { pegar, salvar, apagar } from './storage';

/**
 * Cliente da API do SightOps.
 *
 * A API vive na RAIZ do servidor (`/api/...`), nao sob `/v3/`. Servido em
 * `/v3/rua/` o caminho absoluto resolve certo sozinho; dentro do APK/IPA nao
 * existe servidor nenhum por tras, entao ali e preciso o endereco completo.
 * Sem essa distincao o fetch do app nativo pediria um arquivo do proprio
 * pacote e receberia o index.html com status 200 -- uma falha que nao parece
 * falha.
 */
export const SERVIDOR = 'https://sightops.easytecnologias.com.br';
export const API_BASE = Capacitor.isNativePlatform() ? SERVIDOR : '';

const CHAVE_TOKEN = 'rua.token';

let _token: string | null = null;

export async function carregarToken(): Promise<string | null> {
  _token = await pegar(CHAVE_TOKEN);
  return _token;
}
export function tokenAtual(): string | null {
  return _token;
}

/** Erro que carrega o status: a tela decide o que dizer a partir dele. */
export class ErroApi extends Error {
  status: number;
  constructor(mensagem: string, status: number) {
    super(mensagem);
    this.name = 'ErroApi';
    this.status = status;
  }
}

type Opcoes = RequestInit & { semAuth?: boolean };

async function bruto(caminho: string, opts: Opcoes = {}): Promise<Response> {
  const { semAuth, ...resto } = opts;
  const headers = new Headers(resto.headers);
  if (!(resto.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  if (_token && !semAuth) headers.set('Authorization', `Bearer ${_token}`);
  return fetch(API_BASE + caminho, { credentials: 'same-origin', ...resto, headers });
}

/** GET que devolve JSON. Lanca ErroApi: o React Query distingue
 *  "nao deu" (usa cache) de "sessao caiu" (manda para o login). */
export async function obter<T>(caminho: string): Promise<T> {
  const res = await bruto(caminho);
  if (res.status === 401) throw new ErroApi('sessao expirada', 401);
  if (!res.ok) throw new ErroApi(`HTTP ${res.status}`, res.status);
  return (await res.json()) as T;
}

export async function enviar<T>(caminho: string, corpo: unknown): Promise<T> {
  const res = await bruto(caminho, { method: 'POST', body: JSON.stringify(corpo) });
  if (res.status === 401) throw new ErroApi('sessao expirada', 401);
  if (!res.ok) {
    const detalhe = await res.json().catch(() => ({}));
    throw new ErroApi((detalhe as any)?.detail || `HTTP ${res.status}`, res.status);
  }
  return (await res.json()) as T;
}

export async function entrar(usuario: string, senha: string): Promise<void> {
  const res = await bruto('/api/auth/login', {
    method: 'POST',
    semAuth: true,
    body: JSON.stringify({ username: usuario, password: senha }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new ErroApi((err as any)?.detail || 'Usuario ou senha invalidos', res.status);
  }
  const dados = (await res.json()) as { access_token?: string; token?: string };
  // O token e guardado alem do cookie porque no app nativo a origem e outra
  // e o cookie de sessao do navegador nao acompanha.
  _token = dados.access_token || dados.token || null;
  if (_token) await salvar(CHAVE_TOKEN, _token);
}

export async function sair(): Promise<void> {
  try { await bruto('/api/auth/logout', { method: 'POST' }); } catch { /* sem rede: segue */ }
  _token = null;
  await apagar(CHAVE_TOKEN);
}
