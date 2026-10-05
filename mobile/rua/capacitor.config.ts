import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'br.com.easytecnologias.sightops.rua',
  appName: 'SightOps Rua',
  webDir: 'dist',
  android: { allowMixedContent: false },
  ios: { contentInset: 'always' },
  server: {
    // O app embarcado fala com a API por HTTPS absoluto; sem isto o
    // webview trataria /api/... como caminho do proprio pacote.
    androidScheme: 'https',
  },
};

export default config;
