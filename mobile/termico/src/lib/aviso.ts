import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { enviar } from './api';
import { apagar, pegar, salvar } from './storage';

/**
 * Notificacao com o app fechado (Firebase). O canal "alarme" tem o mesmo nome
 * que o servidor manda em termico_avisos.py: importancia maxima, com sirene.
 * O Android nao deixa mudar o som de um canal ja criado: som novo, canal novo.
 */
const CHAVE = 'termico.aparelho';
let ligado = false;

export const tokenDoAparelho = (): Promise<string | null> => pegar(CHAVE);

export async function avisosLigados(): Promise<boolean> {
  if (!Capacitor.isNativePlatform()) return false;
  return (await PushNotifications.checkPermissions()).receive === 'granted';
}

export async function ligarAvisos(aoChegar: () => void): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  const p = await PushNotifications.requestPermissions();
  if (p.receive !== 'granted') return;
  if (!ligado) {
    ligado = true;
    await PushNotifications.deleteChannel({ id: 'alertas' }).catch(() => undefined);
    await PushNotifications.createChannel({
      id: 'alarme', name: 'Alarme de pessoa', description: 'Pessoa detectada pelo calor, com sirene',
      importance: 5, visibility: 1, vibration: true, sound: 'sirene.wav',
    });
    await PushNotifications.addListener('registration', (t) => {
      void salvar(CHAVE, t.value);
      void enviar('/api/termico/aparelhos', { token: t.value, plataforma: Capacitor.getPlatform() }).catch(() => undefined);
    });
    await PushNotifications.addListener('pushNotificationReceived', () => aoChegar());
    await PushNotifications.addListener('pushNotificationActionPerformed', (a) => {
      const id = (a.notification.data as { alerta_id?: string })?.alerta_id;
      if (id) window.location.hash = `#/alerta/${encodeURIComponent(id)}`;
    });
  }
  // A cada login: o aparelho passa a ser da conta que entrou.
  await PushNotifications.register();
}

/**
 * Saiu da conta ou a sessao venceu: este celular para de receber. O unregister
 * cancela o token no Google e vale mesmo sem rede para o servidor ou com a
 * sessao vencida: o proximo envio volta como desinstalado e a linha some.
 */
export async function desligarAvisos(): Promise<void> {
  if (!Capacitor.isNativePlatform()) return;
  const token = await pegar(CHAVE);
  if (token) {
    try {
      await enviar('/api/termico/aparelhos/sair', { token });
      await apagar(CHAVE);
    } catch { /* o unregister abaixo resolve */ }
  }
  await PushNotifications.removeAllListeners().catch(() => undefined);
  await PushNotifications.unregister().catch(() => undefined);
  ligado = false;
}
