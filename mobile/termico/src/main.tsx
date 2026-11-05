import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import '@fontsource/inter/400.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/800.css';
import '@fontsource/poppins/400.css';
import '@fontsource/poppins/600.css';
import '@fontsource/poppins/800.css';
import '@fontsource/montserrat/500.css';
import '@fontsource/montserrat/600.css';
import '@fontsource/montserrat/800.css';
import { App } from './App';
import { ErroApi } from './lib/api';
import { aplicarMarca } from './lib/marca';
import './estilos.css';

aplicarMarca();

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
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
