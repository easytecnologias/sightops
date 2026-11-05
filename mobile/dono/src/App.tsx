import { useEffect, useRef, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, ErroApi, obter, sair as sairDaApi } from './lib/api';
import { ProvedorFiltro } from './lib/pdv';
import { Shell } from './ui/Shell';
import { Abertura, Login } from './telas/Entrada';
import { CriarPin, PedirPin } from './telas/Desbloqueio';
import { apagarPin, temPin } from './lib/pin';
import { Inicio } from './telas/Inicio';
import { Conta } from './telas/Conta';
import { Conferir } from './telas/Conferir';
import { Busca, CupomTela, Momento } from './telas/Cupom';
import { AoVivo, CaixaVivo } from './telas/AoVivo';
import { Ficha, Rankings } from './telas/Rankings';
import { ParaOlhar } from './telas/Olhar';
import { Equipe } from './telas/Equipe';
import { Mais } from './telas/Mais';

type Etapa = 'abertura' | 'login' | 'pin' | 'criar-pin' | 'dentro';

/** Fora do app por mais que isso: ao voltar, pede o PIN de novo (M1). */
const GRACA_FUNDO_MS = 30_000;

export function App() {
  const [etapa, setEtapa] = useState<Etapa>('abertura');
  const [travado, setTravado] = useState(false);
  const saiuEm = useRef(0);
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
      setEtapa((await temPin()) ? 'pin' : 'criar-pin');
    })();
  }, []);

  // voltou do segundo plano: pede o PIN por cima das telas (sem perder onde estava)
  useEffect(() => {
    if (etapa !== 'dentro') return;
    const mudou = () => {
      if (document.visibilityState === 'hidden') { saiuEm.current = Date.now(); return; }
      if (saiuEm.current && Date.now() - saiuEm.current >= GRACA_FUNDO_MS) {
        void temPin().then((tem) => setTravado(tem));
      }
      saiuEm.current = 0;
    };
    document.addEventListener('visibilitychange', mudou);
    return () => document.removeEventListener('visibilitychange', mudou);
  }, [etapa]);

  // sessao vencida no meio do uso: volta ao login
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    const erro = ev.query.state.error;
    if (etapa === 'dentro' && erro instanceof ErroApi && erro.status === 401) {
      void sairDaApi().then(() => { qc.clear(); setEtapa('login'); });
    }
  }), [qc, etapa]);

  async function sair() {
    await sairDaApi();
    await apagarPin();
    qc.clear();
    setTravado(false);
    setEtapa('login');
  }

  async function depoisDoLogin() {
    setEtapa((await temPin()) ? 'dentro' : 'criar-pin');
  }

  if (etapa === 'abertura') return <Abertura />;
  if (etapa === 'login') return <Login aoEntrar={() => void depoisDoLogin()} />;
  if (etapa === 'pin') return <PedirPin aoAbrir={() => setEtapa('dentro')} aoEsquecer={() => void sair()} />;
  if (etapa === 'criar-pin') return <CriarPin aoTerminar={() => setEtapa('dentro')} aoSair={() => void sair()} />;
  return (
    <>
    {travado ? <PedirPin aoAbrir={() => setTravado(false)} aoEsquecer={() => void sair()} /> : null}
    <HashRouter>
      <ProvedorFiltro>
        <Shell>
          <Routes>
            <Route path="/" element={<Inicio />} />
            <Route path="/olhar" element={<ParaOlhar />} />
            <Route path="/equipe" element={<Equipe />} />
            <Route path="/mais" element={<Mais aoSair={() => void sair()} />} />
            <Route path="/conta" element={<Conta />} />
            <Route path="/conferir" element={<Conferir />} />
            <Route path="/cupom/:caixa/:dia/:cupom" element={<CupomTela />} />
            <Route path="/momento/:caixa" element={<Momento />} />
            <Route path="/busca/:numero" element={<Busca />} />
            <Route path="/vivo" element={<AoVivo />} />
            <Route path="/vivo/:caixa" element={<CaixaVivo />} />
            <Route path="/rankings" element={<Rankings />} />
            <Route path="/ficha/:por/:chave" element={<Ficha />} />
            <Route path="/avisos" element={<Navigate to="/olhar" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Shell>
      </ProvedorFiltro>
    </HashRouter>
    </>
  );
}
