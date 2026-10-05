import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

// base './' porque o mesmo build roda em DOIS lugares: servido em
// https://.../v3/rua/ no navegador e a partir do sistema de arquivos dentro
// do APK/IPA. Caminho absoluto quebraria o segundo caso.
export default defineConfig({
  plugins: [react()],
  base: './',
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5180,
    // Em desenvolvimento o app roda em localhost e a API em producao; o proxy
    // evita CORS e mantem o mesmo caminho absoluto /api/... do build final.
    proxy: {
      '/api': {
        target: 'https://sightops.easytecnologias.com.br',
        changeOrigin: true,
        secure: true,
      },
    },
  },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
});
