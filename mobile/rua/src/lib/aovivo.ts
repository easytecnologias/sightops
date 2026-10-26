import { Capacitor } from '@capacitor/core';
import { SERVIDOR, enviar, obter } from './api';

/*
 * Ao vivo: o mesmo player da web (frontend/js/liveStream.js) -- MSE direto no
 * WebSocket do go2rtc, sem WebRTC. Diferenca do app: ele nao tem o cookie de
 * sessao que o nginx confere no WebSocket, entao pede um bilhete curto
 * (/api/auth/video-ticket, 60 s, preso ao stream) e o poe no endereco: `&t=`.
 */

const CODECS = ['avc1.640029', 'avc1.64002A', 'avc1.640033', 'hvc1.1.6.L153.B0'];

export class SenhaNecessaria extends Error {}

function classeMse(): typeof MediaSource | null {
  const w = window as unknown as { ManagedMediaSource?: typeof MediaSource };
  if (w.ManagedMediaSource) return w.ManagedMediaSource;
  return typeof MediaSource !== 'undefined' ? MediaSource : null;
}

function codecs(M: typeof MediaSource): string {
  return CODECS.filter((c) => { try { return M.isTypeSupported(`video/mp4; codecs="${c}"`); } catch { return false; } }).join();
}

function juntar(bufs: ArrayBuffer[]): Uint8Array<ArrayBuffer> {
  const total = bufs.reduce((n, b) => n + b.byteLength, 0);
  const out = new Uint8Array(new ArrayBuffer(total));
  let o = 0;
  for (const b of bufs) { out.set(new Uint8Array(b), o); o += b.byteLength; }
  return out;
}

export type Alvo = { ip: string; conector?: string; usuario?: string; senha?: string; fabricante?: string; modelo?: string };

/** Registra a camera no go2rtc (idempotente) e devolve o nome do stream. */
async function registrar(a: Alvo, subtipo: 0 | 1): Promise<string> {
  const r = await enviar<{ ok?: boolean; error?: string; stream_name?: string }>(
    `/api/maintenance/stream_register/${encodeURIComponent(a.ip)}`,
    { user: a.usuario || '', password: a.senha || '', subtype: subtipo, vendor: a.fabricante || '', model: a.modelo || '', remote_connector_id: a.conector || '' });
  if (r.ok === false) {
    if (r.error === 'credential_required') throw new SenhaNecessaria('credential_required');
    throw new Error(r.error || 'Não consegui registrar o vídeo.');
  }
  if (!r.stream_name) throw new Error('O servidor não devolveu o vídeo.');
  return r.stream_name;
}

async function enderecoWs(stream: string): Promise<string> {
  const base = (Capacitor.isNativePlatform() ? SERVIDOR : location.origin).replace(/^http/, 'ws');
  let t = '';
  try {
    t = (await obter<{ ticket?: string }>(`/api/auth/video-ticket?src=${encodeURIComponent(stream)}`)).ticket ?? '';
  } catch {
    // Servidor ainda sem a rota do bilhete: no navegador o cookie basta.
  }
  return `${base}/go2rtc/api/ws?src=${encodeURIComponent(stream)}${t ? `&t=${encodeURIComponent(t)}` : ''}`;
}

export type Player = { trocarQualidade: (s: 0 | 1) => void; parar: () => void };

/**
 * Liga o player num <video>. `aviso` recebe o estado em texto ('' = tocando,
 * 'senha' = a camera pede senha).
 */
export function tocar(video: HTMLVideoElement, alvo: Alvo, subtipoInicial: 0 | 1, aviso: (t: string) => void): Player {
  const M = classeMse();
  const gerenciado = !!M && (window as unknown as { ManagedMediaSource?: unknown }).ManagedMediaSource === M;
  let subtipo = subtipoInicial;
  let geracao = 0;
  let ws: WebSocket | null = null;
  let religar: number | undefined;
  let tentativas = 0;
  let parado = false;

  function desmontar() {
    window.clearTimeout(religar);
    if (ws) { try { ws.close(); } catch { /* ja fechado */ } ws = null; }
    try { video.pause(); } catch { /* sem video */ }
    video.removeAttribute('src');
    video.srcObject = null;
    video.load();
  }

  function agendar() {
    religar = window.setTimeout(conectar, Math.min(4000 * 1.6 ** tentativas++, 30000));
  }

  async function conectar() {
    const minha = ++geracao;
    desmontar();
    if (parado) return;
    if (!M) { aviso('Este aparelho não toca vídeo ao vivo.'); return; }
    aviso('Conectando…');
    let url: string;
    try {
      url = await enderecoWs(await registrar(alvo, subtipo));
    } catch (e) {
      if (minha !== geracao || parado) return;
      if (e instanceof SenhaNecessaria) { aviso('senha'); return; }
      aviso((e as Error).message || 'Erro ao abrir o vídeo');
      agendar();
      return;
    }
    if (minha !== geracao || parado) return;

    const sock = new WebSocket(url);
    sock.binaryType = 'arraybuffer';
    ws = sock;
    let ms: MediaSource | null = null;
    let sb: SourceBuffer | null = null;
    let fila: ArrayBuffer[] = [];

    const fimAtualizacao = () => {
      if (!sb || !ms) return;
      if (!sb.updating && fila.length) {
        const m = juntar(fila); fila = [];
        try { sb.appendBuffer(m); } catch { /* o proximo quadro corrige */ }
      }
      if (!sb.updating && sb.buffered.length) {
        const fim = sb.buffered.end(sb.buffered.length - 1);
        const ini0 = sb.buffered.start(0);
        const ini = fim - 15;
        if (ini > ini0) { sb.remove(ini0, ini); ms.setLiveSeekableRange?.(ini, fim); }
        if (video.currentTime < ini || video.currentTime > fim) video.currentTime = fim - 2;
        video.playbackRate = fim - video.currentTime > 4 ? 1.3 : 1;
      }
    };

    sock.onopen = () => {
      if (minha !== geracao) return;
      aviso('Aguardando vídeo…');
      ms = new M();
      if (gerenciado) { (video as HTMLVideoElement & { disableRemotePlayback: boolean }).disableRemotePlayback = true; video.srcObject = ms as unknown as MediaStream; }
      else video.src = URL.createObjectURL(ms);
      ms.addEventListener('sourceopen', () => {
        if (minha !== geracao) return;
        if (!gerenciado) URL.revokeObjectURL(video.src);
        sock.send(JSON.stringify({ type: 'mse', value: codecs(M) }));
      }, { once: true });
    };

    sock.onmessage = (ev) => {
      if (minha !== geracao) return;
      if (typeof ev.data === 'string') {
        let msg: { type?: string; value?: string };
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (msg.type === 'mse' && ms && msg.value) {
          tentativas = 0;
          sb = ms.addSourceBuffer(msg.value);
          sb.mode = 'segments';
          sb.addEventListener('updateend', fimAtualizacao);
          aviso('');
          video.play().catch(() => {});
        } else if (msg.type === 'error') {
          aviso(/401|unauthorized|authorization failed/i.test(String(msg.value ?? '')) ? 'senha' : `Erro no vídeo: ${msg.value}`);
        }
        return;
      }
      if (!sb) return;
      if (sb.updating || fila.length) fila.push(ev.data as ArrayBuffer);
      else { try { sb.appendBuffer(ev.data as ArrayBuffer); } catch { /* idem */ } }
    };

    sock.onclose = () => { if (minha === geracao && !parado) { aviso('Reconectando…'); agendar(); } };
    sock.onerror = () => { if (minha === geracao) aviso('Erro de conexão'); };
  }

  void conectar();
  return {
    trocarQualidade(s) { if (s !== subtipo) { subtipo = s; tentativas = 0; void conectar(); } },
    parar() { parado = true; geracao++; desmontar(); },
  };
}
