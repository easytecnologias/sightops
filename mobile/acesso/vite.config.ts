import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './': dentro do APK os arquivos sao lidos do proprio pacote, sem servidor.
export default defineConfig({
  plugins: [react()],
  base: './',
  server: {
    port: 5181,
    // No navegador (desenvolvimento) a API e a de producao, pelo proxy: evita CORS.
    proxy: {
      '/api': { target: 'https://sightops.easytecnologias.com.br', changeOrigin: true, secure: true },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
