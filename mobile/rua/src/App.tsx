import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, obter, sair as sairDaApi } from './lib/api';
import { useEu } from './lib/dados';
import { Shell } from './ui/Shell';
import { Carregando } from './ui/pecas';
import { Login } from './screens/Login';
import { Dashboard } from './screens/Dashboard';
import { Site } from './screens/Site';
import { Projeto } from './screens/Projeto';
import { ExigeSinal } from './screens/ExigeSinal';

function Dentro({ aoSair }: { aoSair: () => void }) {
  const eu = useEu();
  const cliente = eu.data?.tenant_name || eu.data?.tenant || eu.data?.username || '';

  return (
    <Shell cliente={cliente} onSair={aoSair}>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/site" element={<Site />} />
        <Route path="/projeto" element={<Projeto />} />
        <Route path="/onu" element={
          <ExigeSinal titulo="Ativar ONU" descricao="Autorizar ONU nova na PON, pela OLT." />} />
        <Route path="/ativar" element={
          <ExigeSinal titulo="Ativar camera" descricao="Camera de fabrica, ainda sem senha." />} />
        <Route path="/instalar" element={
          <ExigeSinal titulo="Instalar camera" descricao="Achar na rede, nomear e registrar." />} />
        <Route path="/gravador" element={
          <ExigeSinal titulo="Gravador" descricao="Canais e troca de camera de canal." />} />
        <Route path="/camera" element={
          <ExigeSinal titulo="Camera" descricao="Trocar IP, titulo e reiniciar." />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  );
}

export function App() {
  // 'checando' existe porque ler o token e async (Preferences no nativo).
  // Sem esse estado o app pisca a tela de login antes de descobrir que a
  // sessao esta viva.
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
        // Sem rede o /me falha mesmo com sessao boa. Se ha dado em cache, o
        // app abre offline: e justamente para isso que o cache existe.
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
