// Copia o app web (frontend/alerta/) para www/ e aplica o cliente.
//
// Uma fonte so: o mesmo codigo roda no navegador (simulacao) e no APK. Aqui so
// entra o que e exclusivo do APK: o endereco da API (no APK o app nao esta no
// mesmo dominio do SightOps) e, com CLIENTE, a marca do contratante (nome,
// logo, cores, fonte) de clientes/<cliente>/cliente.json.
//
//   CLIENTE=rads npm run apk
//   ALERTA_API_BASE=https://outro.servidor/v3-api npm run apk   (opcional)
const fs = require('fs');
const path = require('path');

const raiz = path.resolve(__dirname, '..');
const src = path.resolve(raiz, '../../frontend/alerta');
const out = path.resolve(raiz, 'www');
const cliente = (process.env.CLIENTE || '').trim();
const cfg = cliente
  ? JSON.parse(fs.readFileSync(path.join(raiz, 'clientes', cliente, 'cliente.json'), 'utf8'))
  : null;
const API_BASE = process.env.ALERTA_API_BASE || (cfg && cfg.apiBase) || 'https://sightops.easytecnologias.com.br/v3-api';

fs.rmSync(out, { recursive: true, force: true });
fs.mkdirSync(out, { recursive: true });
for (const name of fs.readdirSync(src)) {
  fs.copyFileSync(path.join(src, name), path.join(out, name));
}

let cabeca = '';
let config = `window.ALERTA_API_BASE = ${JSON.stringify(API_BASE)};`;
if (cfg) {
  const pastaCliente = path.join(raiz, 'clientes', cliente);
  const marca = path.join(out, 'marca');
  fs.mkdirSync(path.join(marca, 'fontes'), { recursive: true });
  fs.copyFileSync(path.join(pastaCliente, 'logo-branco.svg'), path.join(marca, 'logo-branco.svg'));
  // Fonte dentro do APK: abre igual sem internet.
  const faces = (cfg.fontes || []).map((f) => {
    const nome = path.basename(f.arquivo);
    fs.copyFileSync(path.join(pastaCliente, f.arquivo), path.join(marca, 'fontes', nome));
    return `@font-face { font-family: '${f.familia}'; font-weight: ${f.peso}; font-style: normal; font-display: swap; src: url('fontes/${nome}') format('truetype'); }`;
  });
  fs.writeFileSync(path.join(marca, 'marca.css'), faces.join('\n') + '\n');
  cabeca = '<link rel="stylesheet" href="marca/marca.css">\n  ';
  // Slogan da abertura do APK ("Alerta · <slogan do cliente>").
  const marcaApp = Object.assign({}, cfg.marca, cfg.slogan ? { slogan: `Alerta · ${cfg.slogan}` } : {});
  config += ` window.ALERTA_MARCA = ${JSON.stringify(marcaApp)};`;
}

const indexPath = path.join(out, 'index.html');
let html = fs.readFileSync(indexPath, 'utf8');
const marker = '<script src="app.js';
if (!html.includes(marker)) throw new Error('index.html sem <script src="app.js"> -- nao sei onde injetar a config');
if (!html.includes('</head>')) throw new Error('index.html sem </head>');
html = html.replace(marker, `<script>${config}</script>\n  ${marker}`);
if (cabeca) html = html.replace('</head>', `  ${cabeca}</head>`);
// Abertura com logo e slogan: so no APK de cliente (no navegador nao aparece).
if (cfg) {
  const ab = 'id="abertura" hidden';
  if (!html.includes(ab)) throw new Error('index.html sem a abertura (id="abertura" hidden)');
  html = html.replace(ab, 'id="abertura"');
}
fs.writeFileSync(indexPath, html);

// Identificador e nome do app no Capacitor (o cap sync leva para o Android).
const capPath = path.join(raiz, 'capacitor.config.json');
const cap = JSON.parse(fs.readFileSync(capPath, 'utf8'));
cap.appId = cfg ? cfg.appId : 'br.com.easytecnologias.sightopsalerta';
cap.appName = cfg ? cfg.appName : 'SightOps Alerta';
// WebView transparente ate a pagina desenhar: aparece o fundo da janela (cor da
// marca com o emblema) em vez de branco.
cap.android = Object.assign({}, cap.android);
if (cfg) cap.android.backgroundColor = '#00000000'; else delete cap.android.backgroundColor;
fs.writeFileSync(capPath, JSON.stringify(cap, null, 2) + '\n');

console.log(`www/ pronto (${fs.readdirSync(out).length} itens) -> API ${API_BASE}${cfg ? ` · cliente ${cliente} (${cfg.appName})` : ''}`);
