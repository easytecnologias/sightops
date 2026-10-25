import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-sans/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import { App } from './App';
import { ErroApi } from './lib/api';
import './estilos.css';

/* Tudo aqui mexe em cadastro de gente e em leitor de porta: o dado tem que ser
   o de agora. Sem cache em disco -- so o da sessao, para a tela nao piscar. */
const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      retry: (tentativa, erro) => {
        const s = (erro as ErroApi)?.status;
        if (s === 401 || s === 403 || s === 404) return false;
        return tentativa < 2;
      },
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
});

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={cliente}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
);
