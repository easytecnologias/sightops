import { Network } from '@capacitor/network';
import { Capacitor } from '@capacitor/core';
import { useEffect, useState } from 'react';

/**
 * Estado da conexao.
 *
 * `navigator.onLine` do navegador so sabe dizer que existe UMA interface de
 * rede ativa -- no celular ele continua `true` com o 4G sem alcance nenhum.
 * O plugin do Capacitor le o estado real do sistema. No navegador fica o
 * fallback, que ja e melhor que nada.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState<boolean>(navigator.onLine);

  useEffect(() => {
    let vivo = true;

    if (Capacitor.isNativePlatform()) {
      Network.getStatus().then((s) => { if (vivo) setOnline(s.connected); });
      const p = Network.addListener('networkStatusChange', (s) => setOnline(s.connected));
      return () => { vivo = false; p.then((h) => h.remove()); };
    }

    const sobe = () => setOnline(true);
    const cai = () => setOnline(false);
    window.addEventListener('online', sobe);
    window.addEventListener('offline', cai);
    return () => {
      vivo = false;
      window.removeEventListener('online', sobe);
      window.removeEventListener('offline', cai);
    };
  }, []);

  return online;
}
