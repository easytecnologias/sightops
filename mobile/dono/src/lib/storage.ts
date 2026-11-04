import { Preferences } from '@capacitor/preferences';
import { Capacitor } from '@capacitor/core';

/**
 * Guarda coisas pequenas e duraveis: token, site escolhido.
 *
 * No app nativo usa Preferences (SharedPreferences no Android, UserDefaults no
 * iOS), que sobrevive a limpeza de dados do webview. No navegador cai no
 * localStorage. Toda leitura e escrita e protegida: armazenamento pode estar
 * cheio ou bloqueado, e nenhuma tela pode morrer por causa disso.
 */
const nativo = Capacitor.isNativePlatform();

export async function pegar(chave: string): Promise<string | null> {
  try {
    if (nativo) return (await Preferences.get({ key: chave })).value ?? null;
    return localStorage.getItem(chave);
  } catch {
    return null;
  }
}

export async function salvar(chave: string, valor: string): Promise<void> {
  try {
    if (nativo) await Preferences.set({ key: chave, value: valor });
    else localStorage.setItem(chave, valor);
  } catch { /* cota cheia ou acesso negado: seguir sem guardar */ }
}

export async function apagar(chave: string): Promise<void> {
  try {
    if (nativo) await Preferences.remove({ key: chave });
    else localStorage.removeItem(chave);
  } catch { /* idem */ }
}
