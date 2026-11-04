import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, ErroApi, obter, sair as sairDaApi } from './lib/api';
import { ProvedorFiltro } from './lib/pdv';
import { Shell } from './ui/Shell';
import { Abertura, Login } from './telas/Entrada';
import { Inicio } from './telas/Inicio';
import { Conta } from './telas/Conta';
import { Conferir } from './telas/Conferir';
import { Busca, CupomTela, Momento } from './telas/Cupom';
import { AoVivo, CaixaVivo } from './telas/AoVivo';
import { Ficha, Rankings } from './telas/Rankings';
import { Avisos } from './telas/Avisos';

type Etapa = 'abertura' | 'login' | 'dentro';

export function App() {
  const [etapa, setEtapa] = useState<Etapa>('abertura');
  const qc = useQueryClient();

  useEffect(() => {
    (async () => {
      const comeco = Date.now();
      const espera = () => new Promise((ok) => setTimeout(ok, Math.max(0, 700 - (Date.now() - comeco))));
      if (!(await carregarToken())) { await espera(); setEtapa('login'); return; }
      try {
        await obter('/api/auth/me');
      } catch (e) {
        if (e instanceof ErroApi && e.status === 401) { await sairDaApi(); await espera(); setEtapa('login'); return; }
        // sem rede: segue com a sessao guardada
      }
      await espera();
      setEtapa('dentro');
    })();
  }, []);

  // sessao vencida no meio do uso: volta ao login
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    const erro = ev.query.state.error;
    if (etapa === 'dentro' && erro instanceof ErroApi && erro.status === 401) {
      void sairDaApi().then(() => { qc.clear(); setEtapa('login'); });
    }
  }), [qc, etapa]);

  async function sair() {
    await sairDaApi();
    qc.clear();
    setEtapa('login');
  }

  if (etapa === 'abertura') return <Abertura />;
  if (etapa === 'login') return <Login aoEntrar={() => setEtapa('dentro')} />;
  return (
    <HashRouter>
      <ProvedorFiltro>
        <Shell>
          <Routes>
            <Route path="/" element={<Inicio aoSair={() => void sair()} />} />
            <Route path="/conta" element={<Conta />} />
            <Route path="/conferir" element={<Conferir />} />
            <Route path="/cupom/:caixa/:dia/:cupom" element={<CupomTela />} />
            <Route path="/momento/:caixa" element={<Momento />} />
            <Route path="/busca/:numero" element={<Busca />} />
            <Route path="/vivo" element={<AoVivo />} />
            <Route path="/vivo/:caixa" element={<CaixaVivo />} />
            <Route path="/rankings" element={<Rankings />} />
            <Route path="/ficha/:por/:chave" element={<Ficha />} />
            <Route path="/avisos" element={<Avisos />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Shell>
      </ProvedorFiltro>
    </HashRouter>
  );
}
