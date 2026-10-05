import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, obter, sair as sairDaApi } from './lib/api';
import { useEu } from './lib/dados';
import { Shell } from './ui/Shell';
import { Carregando } from './ui/pecas';
import { Login } from './screens/Login';
import { Inicio } from './screens/Inicio';
import { Cameras } from './screens/Cameras';
import { Implantar } from './screens/Implantar';
import { Alertas } from './screens/Alertas';
import { Rede } from './screens/Rede';

function Dentro({ aoSair }: { aoSair: () => void }) {
  const eu = useEu();
  const operador = eu.data?.full_name || eu.data?.username || '';

  return (
    <Shell operador={operador} onSair={aoSair}>
      <Routes>
        <Route path="/" element={<Inicio />} />
        <Route path="/cameras" element={<Cameras />} />
        <Route path="/implantar" element={<Implantar />} />
        <Route path="/alertas" element={<Alertas />} />
        <Route path="/rede" element={<Rede />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

export function App() {
  // 'checando' existe porque ler o token e assincrono (Preferences no app
  // nativo). Sem esse estado a tela de login pisca antes de o app descobrir
  // que a sessao ja estava viva.
  const [estado, setEstado] = useState<'checando' | 'fora' | 'dentro'>('checando');
  const qc = useQueryClient();

  useEffect(() => {
    (async () => {
      await carregarToken();
      try {
        await qc.fetchQuery({
          queryKey: ['eu'],
          queryFn: async () => (await obter<{ user?: unknown }>('/api/auth/me')).user ?? {},
        });
        setEstado('dentro');
      } catch {
        // Sem rede o /me falha mesmo com sessao boa. Havendo copia guardada o
        // app abre offline: e exatamente para isso que o cache existe.
        const temCache = qc.getQueryData(['resumo']) || qc.getQueryData(['cameras']);
        setEstado(temCache ? 'dentro' : 'fora');
      }
    })();
  }, [qc]);

  async function sair() {
    await sairDaApi();
    qc.clear();
    setEstado('fora');
  }

  if (estado === 'checando') return <Carregando />;
  if (estado === 'fora') return <Login aoEntrar={() => setEstado('dentro')} />;

  return (
    <HashRouter>
      <Dentro aoSair={sair} />
    </HashRouter>
  );
}
