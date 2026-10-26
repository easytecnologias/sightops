import { enviar } from './api';
import type { Camera } from './dados';

/* Usuario ONVIF de camera Hikvision (para por em gravador de outra marca).
   Servidor: /api/deployments/camera-onvif (app/services/camera_onvif.py), que
   fala ISAPI pelo conector e confere cada escrita relendo a camera. */

export type UsuarioOnvif = { id: string; nome: string; perfil: string };
export type EstadoOnvif = { onvif_ligado: boolean; usuarios: UsuarioOnvif[]; senha_max?: number; passos?: string[] };
export type AcaoOnvif = 'ler' | 'preparar' | 'apagar' | 'ligar' | 'desligar';

export const PERFIS_ONVIF: [string, string][] = [
  ['administrator', 'Administrador'], ['operator', 'Operador'], ['mediaUser', 'Só vídeo'],
];

export const ehHikvision = (c: Camera) => /hik/i.test(String(c.fabricante ?? ''));

/** Chama a camera. `senhaAdmin` vazia = a senha salva da camera (MAC) ou do site. */
export async function onvif(c: Camera, acao: AcaoOnvif, extra: Record<string, unknown> = {}, senhaAdmin = ''): Promise<EstadoOnvif> {
  try {
    return await enviar<EstadoOnvif>('/api/deployments/camera-onvif', {
      ip: c.ip, mac: c.mac ?? '', site: c.site || c.local || '',
      connector_id: c.remote_connector_id || c.connector_id || '',
      ...(senhaAdmin ? { usuario: 'admin', senha: senhaAdmin } : {}),
      acao, ...extra,
    });
  } catch (e) {
    const m = (e as Error).message;
    throw new Error(/SEM_SENHA_CAMERA/.test(m) ? 'Sem senha de admin salva para esta câmera: informe a senha.' : m);
  }
}

export const nomeOnvifValido = (n: string) => /^[A-Za-z0-9_.\-@]{1,32}$/.test(n.trim());
