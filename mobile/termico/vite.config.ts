import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// A marca entra no build: CLIENTE=mega npm run build. Sem CLIENTE, a padrao.
const cliente = (process.env.CLIENTE || 'sightops').trim();
const cfg = JSON.parse(readFileSync(resolve(__dirname, 'clientes', cliente, 'cliente.json'), 'utf8'));

// base './': dentro do APK os arquivos sao lidos do proprio pacote, sem servidor.
export default defineConfig({
  plugins: [react()],
  base: './',
  define: { __CLIENTE__: JSON.stringify({ ...cfg.marca, slogan: cfg.slogan, versao: cfg.versionName }) },
  server: {
    port: 5184,
    // No navegador (desenvolvimento) a API e a de producao, pelo proxy: evita CORS.
    proxy: {
      '/api': { target: 'https://sightops.easytecnologias.com.br', changeOrigin: true, secure: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
