// Ajusta o projeto Android depois do `cap sync`. Idempotente: rodar de novo
// nao duplica nada.
//  - permissao de CAMERA (a foto do rosto usa getUserMedia no WebView; o
//    Capacitor pede a permissao em tempo de uso, mas ela precisa estar no manifesto);
//  - cor da marca no icone adaptativo, na abertura e na barra de status.
const fs = require('fs');
const path = require('path');

const raiz = path.resolve(__dirname, '..');
const main = path.join(raiz, 'android', 'app', 'src', 'main');
const res = path.join(main, 'res');
const ESCURO = '#13252d';

// Manifesto: camera opcional (aparelho sem camera ainda instala e usa a galeria).
const manif = path.join(main, 'AndroidManifest.xml');
let m = fs.readFileSync(manif, 'utf8');
if (!m.includes('android.permission.CAMERA')) {
  m = m.replace('<uses-permission android:name="android.permission.INTERNET" />',
    '<uses-permission android:name="android.permission.INTERNET" />\n'
    + '    <uses-permission android:name="android.permission.CAMERA" />\n'
    + '    <uses-feature android:name="android.hardware.camera" android:required="false" />');
  fs.writeFileSync(manif, m);
}

// Mapa: "onde estou" e a distancia ate a caixa (so com o app aberto).
m = fs.readFileSync(manif, 'utf8');
if (!m.includes('ACCESS_FINE_LOCATION')) {
  m = m.replace('<uses-permission android:name="android.permission.INTERNET" />',
    '<uses-permission android:name="android.permission.INTERNET" />\n'
    + '    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />\n'
    + '    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />\n'
    + '    <uses-feature android:name="android.hardware.location.gps" android:required="false" />');
  fs.writeFileSync(manif, m);
}

fs.writeFileSync(path.join(res, 'values', 'ic_launcher_background.xml'),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${ESCURO}</color>\n</resources>\n`);

fs.mkdirSync(path.join(res, 'drawable'), { recursive: true });
fs.writeFileSync(path.join(res, 'drawable', 'abertura_fundo.xml'), `<?xml version="1.0" encoding="utf-8"?>
<layer-list xmlns:android="http://schemas.android.com/apk/res/android">
    <item android:drawable="@color/ic_launcher_background" />
    <item><bitmap android:gravity="center" android:src="@drawable/abertura_emblema" /></item>
</layer-list>
`);

const estilos = path.join(res, 'values', 'styles.xml');
let st = fs.readFileSync(estilos, 'utf8');
if (!st.includes('windowSplashScreenBackground')) {
  st = st.replace('<item name="android:background">@drawable/splash</item>',
    '<item name="android:background">@drawable/splash</item>\n'
    + '        <item name="windowSplashScreenBackground">@color/ic_launcher_background</item>\n'
    + '        <item name="windowSplashScreenAnimatedIcon">@mipmap/ic_launcher_foreground</item>\n'
    + '        <item name="postSplashScreenTheme">@style/AppTheme.NoActionBar</item>');
}
// Fundo escuro com o emblema enquanto o WebView desenha (antes ficava branco)
// e barra de status escura, emendando no cabecalho.
if (!st.includes('abertura_fundo')) {
  st = st.replace('<item name="android:background">@null</item>',
    '<item name="android:background">@null</item>\n'
    + '        <item name="android:windowBackground">@drawable/abertura_fundo</item>\n'
    + '        <item name="android:statusBarColor">@color/ic_launcher_background</item>\n'
    + '        <item name="android:navigationBarColor">#ffffff</item>\n'
    + '        <item name="android:windowLightStatusBar">false</item>');
}
fs.writeFileSync(estilos, st);
console.log('android preparado: camera, cores e abertura');
