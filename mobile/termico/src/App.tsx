import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, ErroApi, obter, sair as sairDaApi } from './lib/api';
import { desligarAvisos, ligarAvisos } from './lib/aviso';
import { pegar, salvar } from './lib/storage';
import { SiteCtx } from './lib/termico';
import { Shell } from './ui/Shell';
import { SeletorUsina } from './ui/SeletorUsina';
import { Abertura, Login } from './telas/Entrada';
import { Inicio } from './telas/Inicio';
import { AlertaTela } from './telas/Alerta';
import { Ronda } from './telas/Ronda';
import { AoVivo } from './telas/AoVivo';
import { Automacoes } from './telas/Automacoes';
import { AutoEditar } from './telas/AutoEditar';
import { Usinas } from './telas/Usinas';
import { Conta } from './telas/Conta';

type Etapa = 'abertura' | 'login' | 'dentro';

export function App() {
  const [etapa, setEtapa] = useState<Etapa>('abertura');
  const [site, setSite] = useState('');
  const [seletor, setSeletor] = useState(false);
  const qc = useQueryClient();

  useEffect(() => {
    (async () => {
      setSite((await pegar('termico.site')) || '');
      if (!(await carregarToken())) { setEtapa('login'); return; }
      try {
        await obter('/api/auth/me');
      } catch (e) {
        if (e instanceof ErroApi && e.status === 401) { await desligarAvisos(); await sairDaApi(); setEtapa('login'); return; }
        // sem rede: segue com a sessao guardada
      }
      setEtapa('dentro');
    })();
  }, []);

  // sessao vencida no meio do uso: volta ao login
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    const erro = ev.query.state.error;
    if (etapa === 'dentro' && erro instanceof ErroApi && erro.status === 401) {
      void desligarAvisos().then(sairDaApi).then(() => { qc.clear(); setEtapa('login'); });
    }
  }), [qc, etapa]);

  useEffect(() => {
    if (etapa === 'dentro') void ligarAvisos(() => void qc.invalidateQueries({ queryKey: ['alertas'] }));
  }, [etapa, qc]);

  async function sair() {
    await desligarAvisos();
    await sairDaApi();
    qc.clear();
    setEtapa('login');
  }

  function escolher(s: string) {
    setSite(s);
    void salvar('termico.site', s);
  }

  if (etapa === 'abertura') return <Abertura />;
  if (etapa === 'login') return <Login aoEntrar={() => setEtapa('dentro')} />;
  return (
    <HashRouter>
      <SiteCtx.Provider value={{ site, escolher, abrirSeletor: () => setSeletor(true) }}>
        <Shell>
          <Routes>
            <Route path="/" element={<Inicio />} />
            <Route path="/vivo/:id" element={<AoVivo />} />
            <Route path="/alerta/:id" element={<AlertaTela />} />
            <Route path="/ronda" element={<Ronda />} />
            <Route path="/usinas" element={<Usinas />} />
            <Route path="/automacoes" element={<Automacoes />} />
            <Route path="/automacao/:id" element={<AutoEditar />} />
            <Route path="/conta" element={<Conta aoSair={() => void sair()} />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Shell>
        {seletor ? <SeletorUsina aoFechar={() => setSeletor(false)} /> : null}
      </SiteCtx.Provider>
    </HashRouter>
  );
}
