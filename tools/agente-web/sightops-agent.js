#!/usr/bin/env node
/*
 * SightOps Agent -- acesso web direto a cameras/NVRs atras do tunel isolado.
 *
 * Roda no PC do usuario. O navegador (frontend do SightOps) fala com ele em
 * http://127.0.0.1:47600 e pede pra abrir um dispositivo; o agente sobe uma
 * porta local (127.0.0.1:porta_aleatoria) e canaliza cada conexao TCP por um
 * WebSocket seguro ate a ponte do app (/ws/web-tunnel/<ip>), que alcanca o
 * dispositivo pelo IP virtual do conector. Assim a UI abre DIRETA, sem
 * reconstrucao de HTML e sem porta publica exposta.
 *
 * Zero dependencias: usa http/net nativos e o WebSocket embutido do Node 18+.
 *
 * modo=ip (v1.2.0): o equipamento abre num IP de loopback so dele
 * (127.77.0.N) e na MESMA porta dele -- http://127.77.0.N/ sem ":porta".
 * Camera UNV monta "ws://" + location.host + ":" + porta: com a porta no
 * endereco virava ws://127.0.0.1:19743:19743 e a pagina ficava branca depois
 * do login. IP proprio tambem separa os cookies (cookie nao olha porta: dois
 * equipamentos em 127.0.0.1 brigavam pela sessao). Sem modo=ip, porta
 * aleatoria em 127.0.0.1 como antes (o Ruijie precisa dela: sem ":" no
 * endereco ele pula para https).
 */
'use strict';

const http = require('http');
const net = require('net');

// WebSocket: global (Node com --experimental-websocket / Node 21+) ou pacote 'ws'.
let WS = (typeof WebSocket !== 'undefined') ? WebSocket : null;
if (!WS) { try { WS = require('ws'); } catch (_) { /* sem ws */ } }
if (!WS) {
  console.error('WebSocket indisponivel. Rode com: node --experimental-websocket sightops-agent.js  (ou instale o pacote ws)');
  process.exit(1);
}

const CONTROL_HOST = '127.0.0.1';
const CONTROL_PORT = Number(process.env.SIGHTOPS_AGENT_PORT || 47600); // porta fixa que o frontend procura
const IDLE_MS = 10 * 60 * 1000;       // fecha o forward apos 10 min ocioso
const VERSION = '1.2.0';

// forwards ativos: chave "wsbase|ip|port|modo" -> { server, host, localPort, lastUsed, key, token }
const forwards = new Map();

// modo=ip: um IP de loopback por equipamento (Windows atende 127.0.0.0/8 inteiro)
const ipsLoopback = new Map();   // "wsbase|ip" -> "127.77.x.y"
let proximoIp = 2;
function ipLoopback(wsbase, ip) {
  const k = `${wsbase}|${ip}`;
  if (!ipsLoopback.has(k)) {
    const n = proximoIp++;
    ipsLoopback.set(k, `127.77.${(n >> 8) & 255}.${n & 255}`);
  }
  return ipsLoopback.get(k);
}

function urlLocal(host, porta) {
  return porta === 80 ? `http://${host}/` : `http://${host}:${porta}/`;
}

function log(...a) { console.log(new Date().toISOString(), ...a); }

function fwdKey(wsbase, ip, port, modo) { return `${wsbase}|${ip}|${port}|${modo}`; }

// Sobe (ou reaproveita) um forward local -> WS bridge -> dispositivo.
// Resolve { host, localPort }.
function ensureForward(wsbase, ip, port, token, modo) {
  return new Promise((resolve, reject) => {
    const key = fwdKey(wsbase, ip, port, modo);
    const existing = forwards.get(key);
    if (existing) {
      existing.lastUsed = Date.now();
      existing.token = token; // token novo a cada clique: o antigo pode ter vencido
      return resolve({ host: existing.host, localPort: existing.localPort });
    }

    const server = net.createServer((sock) => {
      const entry = forwards.get(key);
      if (entry) entry.lastUsed = Date.now();
      const tk = (entry && entry.token) || token;
      const url = `${wsbase}/ws/web-tunnel/${encodeURIComponent(ip)}`
        + `?token=${encodeURIComponent(tk)}&port=${encodeURIComponent(port)}`;
      let ws;
      try { ws = new WS(url); } catch (e) { sock.destroy(); return; }
      ws.binaryType = 'arraybuffer';
      const pending = [];
      let open = false, bytesFromDev = 0;
      log(`conexao nova -> abrindo tunel WS pra ${ip}:${port}`);
      ws.onopen = () => {
        open = true;
        log(`tunel WS CONECTADO -> ${ip}:${port}`);
        for (const chunk of pending) ws.send(chunk);
        pending.length = 0;
      };
      ws.onmessage = (ev) => {
        try {
          const buf = Buffer.from(ev.data instanceof ArrayBuffer ? ev.data : ev.data);
          bytesFromDev += buf.length;
          sock.write(buf);
        } catch (_) {}
      };
      ws.onclose = (ev) => {
        log(`tunel WS fechado (code=${ev && ev.code}) apos ${bytesFromDev} bytes do dispositivo`);
        try { sock.end(); } catch (_) {}
      };
      ws.onerror = (ev) => {
        log(`tunel WS ERRO: ${(ev && (ev.message || ev.error && ev.error.message)) || 'ver code no fechamento'}`);
        try { sock.destroy(); } catch (_) {}
      };
      sock.on('data', (data) => {
        if (entry) entry.lastUsed = Date.now();
        if (open) { try { ws.send(data); } catch (_) {} }
        else pending.push(data);
      });
      sock.on('close', () => { try { ws.close(); } catch (_) {} });
      sock.on('error', () => { try { ws.close(); } catch (_) {} });
    });

    const host = modo === 'ip' ? ipLoopback(wsbase, ip) : CONTROL_HOST;
    const pronto = () => {
      const localPort = server.address().port;
      forwards.set(key, { server, host, localPort, lastUsed: Date.now(), key, token });
      log(`forward aberto: ${host}:${localPort} -> ${ip}:${port} (via ${wsbase}, modo=${modo || 'porta'})`);
      resolve({ host, localPort });
    };
    if (modo === 'ip') {
      // mesma porta do equipamento; ocupada (ou sem permissao) -> qualquer uma
      server.once('error', (e) => {
        log(`porta ${port} em ${host} indisponivel (${e.code}); usando outra`);
        server.on('error', (e2) => reject(e2));
        server.listen(0, host, pronto);
      });
      server.listen(Number(port) || 80, host, () => { server.removeAllListeners('error'); server.on('error', () => {}); pronto(); });
    } else {
      server.on('error', (e) => reject(e));
      server.listen(0, host, pronto);
    }
  });
}

// Faxina periodica dos forwards ociosos.
setInterval(() => {
  const now = Date.now();
  for (const [key, e] of forwards) {
    if (now - e.lastUsed > IDLE_MS) {
      try { e.server.close(); } catch (_) {}
      forwards.delete(key);
      log(`forward fechado (ocioso): ${key}`);
    }
  }
}, 60 * 1000).unref();

function sendJson(res, code, obj, origin) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': origin || '*',
    'Access-Control-Allow-Headers': 'Content-Type',
    // PNA: navegador HTTPS -> 127.0.0.1 exige este header (Chrome/Edge).
    'Access-Control-Allow-Private-Network': 'true',
    'Cache-Control': 'no-store',
  });
  res.end(body);
}

const control = http.createServer(async (req, res) => {
  const origin = req.headers.origin || '*';
  if (req.method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': origin,
      'Access-Control-Allow-Headers': 'Content-Type',
      'Access-Control-Allow-Methods': 'GET, OPTIONS',
      // PNA: responde ao preflight Access-Control-Request-Private-Network.
      'Access-Control-Allow-Private-Network': 'true',
    });
    return res.end();
  }
  let u;
  try { u = new URL(req.url, `http://${CONTROL_HOST}:${CONTROL_PORT}`); }
  catch (_) { return sendJson(res, 400, { ok: false, error: 'url invalida' }, origin); }

  if (u.pathname === '/health') {
    return sendJson(res, 200, { ok: true, agent: 'sightops', version: VERSION }, origin);
  }

  if (u.pathname === '/open') {
    const wsbase = (u.searchParams.get('wsbase') || '').replace(/\/+$/, '');
    const ip = u.searchParams.get('ip') || '';
    const port = u.searchParams.get('port') || '80';
    const token = u.searchParams.get('token') || '';
    const modo = u.searchParams.get('modo') === 'ip' ? 'ip' : '';
    if (!/^wss?:\/\//i.test(wsbase) || !ip || !token) {
      return sendJson(res, 400, { ok: false, error: 'faltam wsbase/ip/token' }, origin);
    }
    try {
      const f = await ensureForward(wsbase, ip, port, token, modo);
      return sendJson(res, 200, { ok: true, url: urlLocal(f.host, f.localPort), port: f.localPort, host: f.host, modo: modo || 'porta' }, origin);
    } catch (e) {
      return sendJson(res, 502, { ok: false, error: String(e && e.message || e) }, origin);
    }
  }

  return sendJson(res, 404, { ok: false, error: 'nao encontrado' }, origin);
});

control.on('error', (e) => {
  if (e && e.code === 'EADDRINUSE') {
    log(`porta ${CONTROL_PORT} ja em uso -- o agente ja esta rodando? saindo.`);
    process.exit(0);
  }
  log('erro no controle:', e && e.message || e);
  process.exit(1);
});

control.listen(CONTROL_PORT, CONTROL_HOST, () => {
  log(`SightOps Agent v${VERSION} ouvindo em http://${CONTROL_HOST}:${CONTROL_PORT}`);
});
