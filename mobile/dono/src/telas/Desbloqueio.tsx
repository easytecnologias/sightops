import { useState } from 'react';
import { conferirPin, criarPin, MAX_ERROS } from '../lib/pin';
import { Logo } from './Entrada';
import './desbloqueio.css';

/*
 * PIN do app do dono (backlog M1). Mesmo comportamento do app Rua
 * (mobile/rua/src/telas/Entrada.tsx), com as cores do PDV.
 * Aqui o PIN e obrigatorio: nao ha "Agora nao". Quem esqueceu sai e entra com a senha.
 */

const apagarIcone = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 5H9l-6 7 6 7h12a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1z" />
    <path d="m17 9-5 6M12 9l5 6" />
  </svg>
);

function Teclado({ aoDigito, aoApagar }: { aoDigito: (d: string) => void; aoApagar: () => void }) {
  return (
    <div className="desbloq-teclado">
      {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
        <button key={d} type="button" onClick={() => aoDigito(d)}>{d}</button>
      ))}
      <span />
      <button type="button" onClick={() => aoDigito('0')}>0</button>
      <button type="button" className="vazio" aria-label="Apagar dígito" onClick={aoApagar}>{apagarIcone}</button>
    </div>
  );
}

function Bolas({ n, erro }: { n: number; erro: boolean }) {
  return (
    <div className={`desbloq-bolas${erro ? ' erro' : ''}`} aria-label={`${n} de 4 dígitos digitados`}>
      {[0, 1, 2, 3].map((i) => <span key={i} className={i < n ? 'on' : ''} />)}
    </div>
  );
}

/** Desbloqueio: confere o PIN. 5 erros = sessao apagada, volta a pedir a senha. */
export function PedirPin({ aoAbrir, aoEsquecer }: { aoAbrir: () => void; aoEsquecer: () => void }) {
  const [pin, setPin] = useState('');
  const [msg, setMsg] = useState('');
  const [erro, setErro] = useState(false);
  const [conferindo, setConferindo] = useState(false);

  async function digitar(d: string) {
    if (conferindo || pin.length >= 4) return;
    const novo = pin + d;
    setPin(novo);
    setErro(false);
    if (novo.length < 4) return;
    setConferindo(true);
    const r = await conferirPin(novo);
    setConferindo(false);
    if (r.ok) { aoAbrir(); return; }
    setErro(true);
    setPin('');
    if (r.restam <= 0) { aoEsquecer(); return; }
    setMsg(`PIN errado. ${r.restam} ${r.restam === 1 ? 'tentativa' : 'tentativas'} antes de pedir a senha.`);
  }

  return (
    <section className="desbloq" role="dialog" aria-modal="true" aria-label="Digite o PIN">
      <div className="desbloq-topo">
        <Logo tamanho={56} />
        <h1>SightOps PDV</h1>
        <p>Digite o PIN para abrir</p>
      </div>
      <Bolas n={pin.length} erro={erro} />
      <span className="desbloq-msg" role="status">{msg}</span>
      <Teclado aoDigito={(d) => void digitar(d)} aoApagar={() => setPin(pin.slice(0, -1))} />
      <div className="desbloq-pe">
        <button type="button" onClick={aoEsquecer}>Esqueci o PIN · entrar com a senha</button>
        <small>Depois de {MAX_ERROS} tentativas erradas, pede a senha de novo.</small>
      </div>
    </section>
  );
}

/** Criar PIN (primeiro uso ou depois de entrar com a senha): digita duas vezes. */
export function CriarPin({ aoTerminar, aoSair }: { aoTerminar: () => void; aoSair: () => void }) {
  const [primeiro, setPrimeiro] = useState('');
  const [pin, setPin] = useState('');
  const [msg, setMsg] = useState('');
  const [erro, setErro] = useState(false);

  async function digitar(d: string) {
    if (pin.length >= 4) return;
    const novo = pin + d;
    setPin(novo);
    setErro(false);
    if (novo.length < 4) return;
    if (!primeiro) {
      setTimeout(() => { setPrimeiro(novo); setPin(''); setMsg(''); }, 150);
      return;
    }
    if (novo !== primeiro) {
      setErro(true);
      setPrimeiro('');
      setPin('');
      setMsg('Os dois PINs não batem. Comece de novo.');
      return;
    }
    await criarPin(novo);
    aoTerminar();
  }

  return (
    <section className="desbloq" role="dialog" aria-modal="true" aria-label="Crie um PIN">
      <div className="desbloq-topo">
        <Logo tamanho={56} />
        <h1>{primeiro ? 'Repita o PIN' : 'Crie um PIN'}</h1>
        <p>4 números para abrir o app. Ele protege as vendas e o vídeo se o celular ficar desbloqueado.</p>
      </div>
      <Bolas n={pin.length} erro={erro} />
      <span className="desbloq-msg" role="status">{msg}</span>
      <Teclado aoDigito={(d) => void digitar(d)} aoApagar={() => setPin(pin.slice(0, -1))} />
      <div className="desbloq-pe">
        <button type="button" onClick={aoSair}>Sair da conta</button>
        <small>O PIN fica só neste aparelho. A senha continua valendo.</small>
      </div>
    </section>
  );
}
