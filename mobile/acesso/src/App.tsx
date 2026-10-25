import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, ErroApi, obter, sair as sairDaApi } from './lib/api';
import { pegar, salvar } from './lib/storage';
import { apagarPin, temPin } from './lib/pin';
import { carregarLocal } from './lib/local';
import type { Usuario } from './lib/dados';
import { ProvedorCadastro } from './lib/cadastro';
import { Shell } from './ui/Shell';
import { ProvedorToast } from './ui/pecas';
import {
  Abertura, Apresentacao, CriarPin, EscolherLocal, Login, Permissoes, Pin,
} from './telas/Entrada';
import { Inicio } from './telas/Inicio';
import { Pessoas } from './telas/Pessoas';
import { CadastroDados, CadastroFoto, CadastroPortas, CadastroPronto } from './telas/Cadastro';
import { Relatorios } from './telas/Relatorio';
import { Visitante } from './telas/Visitante';

type Etapa = 'abertura' | 'apresentacao' | 'login' | 'pin' | 'criar-pin' | 'permissoes' | 'local' | 'dentro';

const VISTA_APRESENTACAO = 'acesso.apresentacao';
const VISTA_PERMISSOES = 'acesso.permissoes';

function Dentro({ aoSair, aoTrocarPin }: { aoSair: () => void; aoTrocarPin: () => void }) {
  return (
    <Routes>
      {/* Cadastro em tela cheia, sem a barra de baixo (como no desenho). */}
      <Route path="/cadastro/foto" element={<CadastroFoto />} />
      <Route path="/cadastro/dados" element={<CadastroDados />} />
      <Route path="/cadastro/portas" element={<CadastroPortas />} />
      <Route path="/cadastro/pronto/:id" element={<CadastroPronto />} />
      <Route path="*" element={
        <Shell aoSair={aoSair} aoTrocarPin={aoTrocarPin}>
          <Routes>
            <Route path="/" element={<Inicio />} />
            <Route path="/pessoas" element={<Pessoas />} />
            <Route path="/relatorio" element={<Relatorios />} />
            <Route path="/visitante" element={<Visitante />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Shell>
      } />
    </Routes>
  );
}

export function App() {
  const [etapa, setEtapa] = useState<Etapa>('abertura');
  const [nome, setNome] = useState('');
  const qc = useQueryClient();

  /** Depois de entrar (ou desbloquear): os passos que faltam, em ordem. */
  async function seguir(depoisDoLogin = false, querPin = false) {
    if (depoisDoLogin && querPin && !(await temPin())) { setEtapa('criar-pin'); return; }
    if (!(await pegar(VISTA_PERMISSOES))) { setEtapa('permissoes'); return; }
    if (!(await carregarLocal())) { setEtapa('local'); return; }
    setEtapa('dentro');
  }

  useEffect(() => {
    (async () => {
      const comeco = Date.now();
      const espera = () => new Promise((ok) => setTimeout(ok, Math.max(0, 900 - (Date.now() - comeco))));
      const token = await carregarToken();
      if (!token) {
        await espera();
        setEtapa((await pegar(VISTA_APRESENTACAO)) ? 'login' : 'apresentacao');
        return;
      }
      try {
        const eu = await qc.fetchQuery({
          queryKey: ['eu'],
          queryFn: async () => (await obter<{ user?: Usuario }>('/api/auth/me')).user ?? {},
        });
        setNome(eu.full_name || eu.username || '');
      } catch (e) {
        if (e instanceof ErroApi && e.status === 401) {
          await sairDaApi();
          await espera();
          setEtapa('login');
          return;
        }
        // Sem rede: segue com a sessao guardada; as telas dizem que estao sem sinal.
      }
      await espera();
      if (await temPin()) setEtapa('pin');
      else await seguir();
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function sair() {
    await sairDaApi();
    await apagarPin();
    qc.clear();
    setEtapa('login');
  }

  // Sessao vencida no meio do uso: qualquer 401 volta ao login.
  useEffect(() => {
    return qc.getQueryCache().subscribe((ev) => {
      const erro = ev.query.state.error;
      if (etapa === 'dentro' && erro instanceof ErroApi && erro.status === 401) {
        void sairDaApi().then(() => { qc.clear(); setEtapa('login'); });
      }
    });
  }, [qc, etapa]);

  if (etapa === 'abertura') return <Abertura />;
  if (etapa === 'apresentacao') {
    return <Apresentacao aoTerminar={() => { void salvar(VISTA_APRESENTACAO, '1'); setEtapa('login'); }} />;
  }
  if (etapa === 'login') {
    return (
      <Login aoEntrar={async (querPin) => {
        try {
          const eu = await qc.fetchQuery({
            queryKey: ['eu'], staleTime: 0,
            queryFn: async () => (await obter<{ user?: Usuario }>('/api/auth/me')).user ?? {},
          });
          setNome(eu.full_name || eu.username || '');
        } catch { /* o nome e so enfeite */ }
        await seguir(true, querPin);
      }} />
    );
  }
  if (etapa === 'pin') {
    return <Pin nome={nome} aoAbrir={() => void seguir()} aoEsquecer={() => void sair()} />;
  }
  if (etapa === 'criar-pin') return <CriarPin aoTerminar={() => void seguir()} />;
  if (etapa === 'permissoes') {
    return <Permissoes aoTerminar={() => { void salvar(VISTA_PERMISSOES, '1'); void seguir(); }} />;
  }
  if (etapa === 'local') return <EscolherLocal aoTerminar={() => setEtapa('dentro')} />;

  return (
    <HashRouter>
      <ProvedorToast>
        <ProvedorCadastro>
          <Dentro aoSair={() => void sair()} aoTrocarPin={() => { void apagarPin().then(() => setEtapa('criar-pin')); }} />
        </ProvedorCadastro>
      </ProvedorToast>
    </HashRouter>
  );
}
