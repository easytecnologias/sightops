// Aplica a marca do cliente no projeto Android. Idempotente.
//   CLIENTE=mega node scripts/preparar-android.cjs
// Identificador, nome, versao e cores vem de clientes/<cliente>/cliente.json.
const fs = require('fs');
const path = require('path');

const raiz = path.resolve(__dirname, '..');
const cliente = (process.env.CLIENTE || 'sightops').trim();
const cfg = JSON.parse(fs.readFileSync(path.join(raiz, 'clientes', cliente, 'cliente.json'), 'utf8'));
const app = path.join(raiz, 'android', 'app');
const main = path.join(app, 'src', 'main');
const res = path.join(main, 'res');
const xml = (t) => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

const capPath = path.join(raiz, 'capacitor.config.json');
const cap = JSON.parse(fs.readFileSync(capPath, 'utf8'));
cap.appId = cfg.appId;
cap.appName = cfg.appName;
fs.writeFileSync(capPath, JSON.stringify(cap, null, 2) + '\n');

const gradlePath = path.join(app, 'build.gradle');
let g = fs.readFileSync(gradlePath, 'utf8');
g = g.replace(/namespace\s*=?\s*"[^"]+"/, `namespace = "${cfg.appId}"`)
  .replace(/applicationId "[^"]+"/, `applicationId "${cfg.appId}"`)
  .replace(/versionCode \d+/, `versionCode ${cfg.versionCode}`)
  .replace(/versionName "[^"]+"/, `versionName "${cfg.versionName}"`);
fs.writeFileSync(gradlePath, g);

// MainActivity no pacote do cliente (a pasta acompanha o identificador).
const java = path.join(main, 'java');
function acharMain(d) {
  for (const n of fs.readdirSync(d)) {
    const p = path.join(d, n);
    if (fs.statSync(p).isDirectory()) { const r = acharMain(p); if (r) return r; } else if (n === 'MainActivity.java') return p;
  }
  return null;
}
const antigo = acharMain(java);
const novoDir = path.join(java, ...cfg.appId.split('.'));
fs.mkdirSync(novoDir, { recursive: true });
const novo = path.join(novoDir, 'MainActivity.java');
const fonte = fs.readFileSync(antigo, 'utf8').replace(/^package [^;]+;/m, `package ${cfg.appId};`);
fs.writeFileSync(novo, fonte);
if (path.resolve(antigo) !== path.resolve(novo)) {
  fs.rmSync(antigo);
  for (let d = path.dirname(antigo); d !== java && fs.readdirSync(d).length === 0; d = path.dirname(d)) fs.rmdirSync(d);
}

fs.writeFileSync(path.join(res, 'values', 'strings.xml'), `<?xml version='1.0' encoding='utf-8'?>
<resources>
    <string name="app_name">${xml(cfg.appName)}</string>
    <string name="title_activity_main">${xml(cfg.appName)}</string>
    <string name="package_name">${xml(cfg.appId)}</string>
    <string name="custom_url_scheme">${xml(cfg.appId)}</string>
</resources>
`);
fs.writeFileSync(path.join(res, 'values', 'ic_launcher_background.xml'),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${cfg.marca.cor}</color>\n</resources>\n`);
console.log(`android preparado: ${cfg.appName} (${cfg.appId}) ${cfg.versionName}`);
