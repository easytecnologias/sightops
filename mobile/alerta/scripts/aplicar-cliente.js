// Aplica a marca do cliente no projeto Android depois do `cap sync`:
// nome do app, identificador, versao, icone, tela de abertura e cor de fundo.
// Os PNGs vem de clientes/<cliente>/android-res/ (scripts/gerar-icones.py).
//
//   CLIENTE=rads node scripts/aplicar-cliente.js
const fs = require('fs');
const path = require('path');

const raiz = path.resolve(__dirname, '..');
const cliente = (process.env.CLIENTE || '').trim();
if (!cliente) { console.log('sem CLIENTE: projeto Android fica como esta (SightOps Alerta)'); process.exit(0); }
const pasta = path.join(raiz, 'clientes', cliente);
const cfg = JSON.parse(fs.readFileSync(path.join(pasta, 'cliente.json'), 'utf8'));
const res = path.join(raiz, 'android', 'app', 'src', 'main', 'res');

function copiarPasta(de, para) {
  for (const nome of fs.readdirSync(de)) {
    const a = path.join(de, nome);
    const b = path.join(para, nome);
    if (fs.statSync(a).isDirectory()) { fs.mkdirSync(b, { recursive: true }); copiarPasta(a, b); } else fs.copyFileSync(a, b);
  }
}

function xml(texto) {
  return String(texto).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Icone e abertura.
copiarPasta(path.join(pasta, 'android-res'), res);

// Fundo do icone adaptativo e da abertura do Android 12+.
fs.writeFileSync(path.join(res, 'values', 'ic_launcher_background.xml'),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${cfg.marca.cor}</color>\n</resources>\n`);

// Nome que aparece embaixo do icone.
fs.writeFileSync(path.join(res, 'values', 'strings.xml'), `<?xml version='1.0' encoding='utf-8'?>
<resources>
    <string name="app_name">${xml(cfg.appName)}</string>
    <string name="title_activity_main">${xml(cfg.appName)}</string>
    <string name="package_name">${xml(cfg.appId)}</string>
    <string name="custom_url_scheme">${xml(cfg.appId)}</string>
</resources>
`);

// Abertura no Android 12+: fundo da marca com o icone (sem isso fica branca).
const estilos = path.join(res, 'values', 'styles.xml');
let st = fs.readFileSync(estilos, 'utf8');
if (!st.includes('windowSplashScreenBackground')) {
  st = st.replace(
    '<item name="android:background">@drawable/splash</item>',
    '<item name="android:background">@drawable/splash</item>\n        <item name="windowSplashScreenBackground">@color/ic_launcher_background</item>\n        <item name="windowSplashScreenAnimatedIcon">@mipmap/ic_launcher_foreground</item>\n        <item name="postSplashScreenTheme">@style/AppTheme.NoActionBar</item>',
  );
  fs.writeFileSync(estilos, st);
}
// Barra de status (relogio, bateria) na cor da marca, emendando no cabecalho.
if (!st.includes('android:statusBarColor')) {
  st = st.replace(
    '<item name="android:background">@null</item>',
    '<item name="android:background">@null</item>\n        <item name="android:statusBarColor">@color/ic_launcher_background</item>\n        <item name="android:windowLightStatusBar">false</item>',
  );
  fs.writeFileSync(estilos, st);
}

// Identificador e versao (lidos pelo android/app/build.gradle).
fs.writeFileSync(path.join(raiz, 'android', 'cliente.properties'),
  `applicationId=${cfg.appId}\nversionCode=${cfg.versionCode}\nversionName=${cfg.versionName}\n`);

console.log(`android: ${cfg.appName} (${cfg.appId}) v${cfg.versionName} (${cfg.versionCode})`);
