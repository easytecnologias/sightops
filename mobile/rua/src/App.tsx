import { useEffect, useState } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { carregarToken, ErroApi, obter, sair as sairDaApi } from './lib/api';
import { apagar, pegar, salvar } from './lib/storage';
import { apagarPin, temPin } from './lib/pin';
import { useSite } from './lib/site';
import type { Usuario } from './lib/dados';
import { Shell } from './ui/Shell';
import { ProvedorToast } from './ui/pecas';
import { Abertura, Apresentacao, CriarPin, EscolherSite, Login, Pin } from './telas/Entrada';
import { Inicio } from './telas/Inicio';
import { Alertas } from './telas/Alertas';
import { Equipamentos } from './telas/Equipamentos';
import { Pon } from './telas/Pon';
import { Switch } from './telas/Switch';
import { ConsultarOnu, ListaOnus } from './telas/ConsultarOnu';
import { Conta } from './telas/Conta';
import { Cameras } from './screens/Cameras';
import { CameraDetalhe } from './screens/CameraDetalhe';
import { AoVivo } from './telas/AoVivo';
import { Mapa } from './telas/Mapa';
import { InstalarCamera } from './telas/InstalarCamera';
import { useLocation } from 'react-router-dom';

/** Cada entrada nesta rota (inclusive "Instalar outra") comeca do zero. */
function InstalarRota() {
  return <InstalarCamera key={useLocation().key} />;
}
import { Implantar } from './telas/Implantar';
import { OnuConfigurar, OnuEscolher, OnuPronta } from './telas/ImplantarOnu';
import { ProcurarOnu } from './telas/ProcurarOnu';
import { OnvifLote } from './telas/OnvifLote';
import { CameraAtivar } from './telas/ImplantarCamera';
import { GravadorCanais, Gravadores } from './telas/ImplantarGravador';
import { ProvedorImplantar } from './lib/implantar';

type Etapa = 'abertura' | 'apresentacao' | 'login' | 'pin' | 'criar-pin' | 'site' | 'dentro';

const VISTA_APRESENTACAO = 'rua.apresentacao';

function Dentro(
  { aoSair, aoTrocarPin, aoVerApresentacao }:
  { aoSair: () => void; aoTrocarPin: () => void; aoVerApresentacao: () => void },
) {
  return (
    <Routes>
      <Route path="/conta" element={<Conta aoSair={aoSair} aoTrocarPin={aoTrocarPin} aoVerApresentacao={aoVerApresentacao} />} />
      <Route path="*" element={
        <Shell>
          <Routes>
            <Route path="/" element={<Inicio />} />
            <Route path="/cameras" element={<Cameras />} />
            <Route path="/cameras/:chave" element={<CameraDetalhe />} />
            <Route path="/cameras/:chave/aovivo" element={<AoVivo />} />
            <Route path="/implantar" element={<Implantar />} />
            <Route path="/mapa" element={<Mapa />} />
            <Route path="/implantar/onu" element={<OnuEscolher />} />
            <Route path="/implantar/onu/procurar" element={<ProcurarOnu />} />
            <Route path="/implantar/onvif" element={<OnvifLote />} />
            <Route path="/implantar/onu/configurar" element={<OnuConfigurar />} />
            <Route path="/implantar/onu/pronta" element={<OnuPronta />} />
            <Route path="/implantar/camera" element={<CameraAtivar />} />
            <Route path="/implantar/instalar" element={<InstalarRota />} />
            <Route path="/implantar/gravador" element={<Gravadores />} />
            <Route path="/implantar/gravador/:host" element={<GravadorCanais />} />
            <Route path="/alertas" element={<Alertas />} />
            <Route path="/equipamentos" element={<Equipamentos />} />
            <Route path="/pon" element={<Pon />} />
            <Route path="/switch/:chave" element={<Switch />} />
            <Route path="/rede" element={<Navigate to="/equipamentos?f=rede" replace />} />
            <Route path="/onu" element={<ListaOnus />} />
            <Route path="/onu/:chave" element={<ConsultarOnu />} />
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
  const { escolher } = useSite();

  const buscarEu = () => qc.fetchQuery({
    queryKey: ['eu'], staleTime: 0,
    queryFn: async () => (await obter<{ user?: Usuario }>('/api/auth/me')).user ?? {},
  });

  /** Depois de entrar (ou desbloquear): os passos que faltam, em ordem. */
  async function seguir(depoisDoLogin = false, querPin = false) {
    if (depoisDoLogin && querPin && !(await temPin())) { setEtapa('criar-pin'); return; }
    if (!(await pegar('rua.site'))) { setEtapa('site'); return; }
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
        const eu = await buscarEu();
        setNome(eu.full_name || eu.username || '');
      } catch (e) {
        if (e instanceof ErroApi && e.status === 401) {
          await sairDaApi();
          await espera();
          setEtapa('login');
          return;
        }
        // Sem rede: abre com a copia guardada; as telas dizem de quando e o dado.
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

  // Sessao vencida no meio do uso: volta ao login.
  useEffect(() => qc.getQueryCache().subscribe((ev) => {
    const erro = ev.query.state.error;
    if (etapa === 'dentro' && erro instanceof ErroApi && erro.status === 401) {
      void sairDaApi().then(() => { qc.clear(); setEtapa('login'); });
    }
  }), [qc, etapa]);

  if (etapa === 'abertura') return <Abertura />;
  if (etapa === 'apresentacao') {
    return <Apresentacao aoTerminar={() => { void salvar(VISTA_APRESENTACAO, '1'); void temToken().then((t) => setEtapa(t ? 'dentro' : 'login')); }} />;
  }
  if (etapa === 'login') {
    return (
      <Login aoEntrar={async (querPin) => {
        try { const eu = await buscarEu(); setNome(eu.full_name || eu.username || ''); } catch { /* nome e enfeite */ }
        await seguir(true, querPin);
      }} />
    );
  }
  if (etapa === 'pin') return <Pin nome={nome} aoAbrir={() => void seguir()} aoEsquecer={() => void sair()} />;
  if (etapa === 'criar-pin') return <CriarPin aoTerminar={() => void seguir()} />;
  if (etapa === 'site') return <EscolherSite aoEscolher={(s) => { escolher(s); setEtapa('dentro'); }} />;

  return (
    <HashRouter>
      <ProvedorToast>
        <ProvedorImplantar>
        <Dentro
          aoSair={() => void sair()}
          aoTrocarPin={() => { void apagarPin().then(() => setEtapa('criar-pin')); }}
          aoVerApresentacao={() => { void apagar(VISTA_APRESENTACAO).then(() => setEtapa('apresentacao')); }}
        />
        </ProvedorImplantar>
      </ProvedorToast>
    </HashRouter>
  );
}

async function temToken(): Promise<boolean> {
  return !!(await carregarToken());
}
