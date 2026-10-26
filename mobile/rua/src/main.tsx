import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient } from '@tanstack/react-query';
import { PersistQueryClientProvider } from '@tanstack/react-query-persist-client';
import { createSyncStoragePersister } from '@tanstack/query-sync-storage-persister';
import { App } from './App';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import '@fontsource/ibm-plex-sans/700.css';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './estilos.css';

/**
 * O cache do React Query E a camada offline deste aplicativo.
 *
 * `gcTime` de 7 dias e `staleTime` de 2 minutos: no poste o tecnico abre a
 * tela e tem que ver ALGUMA coisa na hora, mesmo que seja de ontem -- e a
 * tela diz de quando e. Buscar de novo em segundo plano cuida do resto
 * quando o sinal existe.
 */
const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 2 * 60 * 1000,
      gcTime: 7 * 24 * 60 * 60 * 1000,
      // Sem rede, insistir so gasta bateria: o erro volta rapido e a tela
      // mostra o que ja estava guardado.
      retry: (tentativa, erro) => {
        const st = (erro as { status?: number })?.status;
        if (st === 401 || st === 403 || st === 404) return false;
        return navigator.onLine && tentativa < 2;
      },
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      networkMode: 'offlineFirst',
    },
  },
});

const persistidor = createSyncStoragePersister({
  storage: window.localStorage,
  key: 'rua.cache',
  // Falha de escrita (cota) nao pode derrubar o app: o cache e conveniencia.
  throttleTime: 1500,
});

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <PersistQueryClientProvider
      client={cliente}
      persistOptions={{ persister: persistidor, maxAge: 7 * 24 * 60 * 60 * 1000 }}
    >
      <App />
    </PersistQueryClientProvider>
  </React.StrictMode>,
);
