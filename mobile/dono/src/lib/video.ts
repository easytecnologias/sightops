import { Capacitor } from '@capacitor/core';
import { SERVIDOR, obter } from './api';

/*
 * Video pelo go2rtc do SightOps (o mesmo player do app Rua): MSE direto no
 * WebSocket. O app nao tem o cookie da web, entao pede um bilhete curto
 * (/api/auth/video-ticket) e poe no endereco (&t=).
 * `vivo`: ao vivo corta o atraso e pula para o fim; gravacao toca em ordem.
 */

const CODECS = ['avc1.640029', 'avc1.64002A', 'avc1.640033', 'hvc1.1.6.L153.B0'];

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

async function enderecoWs(stream: string): Promise<string> {
  const base = (Capacitor.isNativePlatform() ? SERVIDOR : location.origin).replace(/^http/, 'ws');
  let t = '';
  try {
    t = (await obter<{ ticket?: string }>(`/api/auth/video-ticket?src=${encodeURIComponent(stream)}`)).ticket ?? '';
  } catch { /* no navegador o cookie basta */ }
  return `${base}/go2rtc/api/ws?src=${encodeURIComponent(stream)}${t ? `&t=${encodeURIComponent(t)}` : ''}`;
}

export type Player = { parar: () => void };

/** Liga o player num <video>. `registrar` devolve o nome do stream no go2rtc. */
export function tocar(
  video: HTMLVideoElement, registrar: () => Promise<string>, aviso: (t: string) => void, vivo: boolean,
): Player {
  const M = classeMse();
  const gerenciado = !!M && (window as unknown as { ManagedMediaSource?: unknown }).ManagedMediaSource === M;
  let geracao = 0;
  let ws: WebSocket | null = null;
  let religar: number | undefined;
  let tentativas = 0;
  let parado = false;
  let stream = '';

  function desmontar() {
    window.clearTimeout(religar);
    if (ws) { try { ws.close(); } catch { /* ja fechado */ } ws = null; }
    try { video.pause(); } catch { /* sem video */ }
    video.removeAttribute('src');
    video.srcObject = null;
    video.load();
  }

  function agendar() {
    if (!vivo && tentativas > 2) { aviso('A gravação parou. Toque em ▶ de novo.'); return; }
    religar = window.setTimeout(conectar, Math.min(4000 * 1.6 ** tentativas++, 30000));
  }

  async function conectar() {
    const minha = ++geracao;
    desmontar();
    if (parado) return;
    if (!M) { aviso('Este aparelho não toca este vídeo.'); return; }
    aviso(vivo ? 'Conectando…' : 'Abrindo a gravação…');
    let url: string;
    try {
      // gravacao: o mesmo stream (re-registrar recomecaria do inicio)
      if (!stream || vivo) stream = await registrar();
      url = await enderecoWs(stream);
    } catch (e) {
      if (minha !== geracao || parado) return;
      aviso((e as Error).message || 'Erro ao abrir o vídeo');
      if (vivo) agendar();
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
        if (vivo) {
          const ini = fim - 15;
          if (ini > ini0) { sb.remove(ini0, ini); ms.setLiveSeekableRange?.(ini, fim); }
          if (video.currentTime < ini || video.currentTime > fim) video.currentTime = fim - 2;
          video.playbackRate = fim - video.currentTime > 4 ? 1.3 : 1;
        } else {
          if (video.currentTime < ini0) video.currentTime = ini0;
          const ini = video.currentTime - 120;  // guarda 2 min para tras
          if (ini > ini0 + 5) sb.remove(ini0, ini);
        }
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
          aviso(`Erro no vídeo: ${msg.value ?? ''}`);
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
  return { parar() { parado = true; geracao++; desmontar(); } };
}
