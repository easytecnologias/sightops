import { useState, type FormEvent, type ReactNode } from 'react';
import { entrar } from '../lib/api';
import { conferirPin, criarPin, MAX_ERROS } from '../lib/pin';
import { mesmoSite, siteDoConector, useConectores, useEntidades } from '../lib/dados';
import { Carregando, Icone, Logo, Vazio, iniciais } from '../ui/pecas';
import { ordemNatural } from '../lib/ordem';

export const VERSAO = '2.0.5';

/* ─────────────────────────── B · Abertura ─────────────────────────── */
export function Abertura() {
  return (
    <div className="abertura">
      <Logo tamanho={112} />
      <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
        <span className="nome">SightOps</span>
        <span className="sub">Rua · aplicativo do técnico</span>
      </span>
      <span className="pe">
        <span className="barra-carga"><span /></span>
        Conferindo a conexão com o servidor…
      </span>
    </div>
  );
}

/* ─────────────────────────── C/D/E · Apresentacao ─────────────────────────── */
function Mini({ titulo, sub, desloca = 0, selo }: { titulo: string; sub: string; desloca?: number; selo?: string }) {
  return (
    <div className="mini" style={{ marginLeft: desloca }}>
      <span className="ok-redondo">{Icone.ok}</span>
      <span style={{ flex: 1, minWidth: 0 }}><b>{titulo}</b><span className="s">{sub}</span></span>
      {selo ? <span className="selo verde">{selo}</span> : null}
    </div>
  );
}

const SLIDES: { titulo: string; texto: string; vitrine: ReactNode }[] = [
  {
    titulo: 'O site inteiro no bolso',
    texto: 'Câmeras, gravadores, ONUs e conector com o estado de agora, o mesmo que vai para o Zabbix.',
    vitrine: (
      <>
        <Mini titulo="Câmeras 21 / 22" sub="1 sem vídeo" />
        <Mini titulo="ONUs 46 / 46" sub="1 com sinal baixo" desloca={18} />
        <Mini titulo="Conector" sub="online há 6 dias" desloca={36} selo="no ar" />
      </>
    ),
  },
  {
    titulo: 'Ache o problema antes de sair',
    texto: 'Consulte a ONU pelo serial ou nome: sinal de agora, histórico do dia e posição na OLT.',
    vitrine: (
      <>
        <Mini titulo="Apto 112 · RX −27,5 dBm" sub="caiu às 13h · PON 1/3" />
        <Mini titulo="Lido agora na OLT" sub="sinal de volta ao normal" desloca={18} />
      </>
    ),
  },
  {
    titulo: 'Saiba o que caiu e quando voltou',
    texto: 'Equipamento fora do ar e alertas de pânico do site, com o horário de cada mudança.',
    vitrine: (
      <>
        <Mini titulo="Garagem 2 sem vídeo" sub="desde 08:15" />
        <Mini titulo="Conector voltou" sub="ficou fora 4 min" desloca={18} selo="ok" />
      </>
    ),
  },
];

export function Apresentacao({ aoTerminar }: { aoTerminar: () => void }) {
  const [i, setI] = useState(0);
  const s = SLIDES[i];
  const ultimo = i === SLIDES.length - 1;
  return (
    <section className="tela-cheia apresentacao">
      <div className="topo">
        {!ultimo ? <button type="button" className="link cinza" onClick={aoTerminar}>Pular</button> : null}
      </div>
      <div className="vitrine">{s.vitrine}</div>
      <div>
        <h1>{s.titulo}</h1>
        <p>{s.texto}</p>
      </div>
      <div className="pe">
        <div className="pontos" aria-label={`Página ${i + 1} de ${SLIDES.length}`}>
          {SLIDES.map((_, n) => <i key={n} className={n === i ? 'on' : ''} />)}
        </div>
        <button type="button" className="btn" onClick={() => (ultimo ? aoTerminar() : setI(i + 1))}>
          {ultimo ? 'Começar' : 'Próximo'}
        </button>
      </div>
    </section>
  );
}

/* ─────────────────────────── F · Entrar ─────────────────────────── */
export function Login({ aoEntrar }: { aoEntrar: (querPin: boolean) => void }) {
  const [usuario, setUsuario] = useState('');
  const [senha, setSenha] = useState('');
  const [ver, setVer] = useState(false);
  const [pin, setPin] = useState(true);
  const [erro, setErro] = useState('');
  const [indo, setIndo] = useState(false);

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setErro('');
    setIndo(true);
    try {
      await entrar(usuario.trim(), senha);
      aoEntrar(pin);
    } catch (e) {
      setErro((e as Error).message || 'Não foi possível entrar.');
    } finally {
      setIndo(false);
    }
  }

  return (
    <section className="tela-cheia entrar">
      <div className="marca-grande">
        <Logo tamanho={64} />
        <b>SightOps</b>
        <span>Rua · aplicativo do técnico</span>
      </div>
      <form onSubmit={enviar}>
        <h1>Entrar</h1>
        <div className="campo">
          <label htmlFor="u">Usuário</label>
          <div className="caixa">
            <input id="u" value={usuario} onChange={(e) => setUsuario(e.target.value)}
                   autoComplete="username" autoCapitalize="none" spellCheck={false} required />
          </div>
        </div>
        <div className="campo">
          <label htmlFor="p">Senha</label>
          <div className="caixa">
            <input id="p" type={ver ? 'text' : 'password'} value={senha} onChange={(e) => setSenha(e.target.value)}
                   autoComplete="current-password" required />
            <button type="button" className="olho" aria-label={ver ? 'Esconder senha' : 'Mostrar senha'}
                    onClick={() => setVer(!ver)}>{ver ? Icone.olhoFechado : Icone.olho}</button>
          </div>
        </div>
        <label className="marcar">
          <input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} />
          Criar um PIN para desbloquear rápido
        </label>
        {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}
        <button type="submit" className="btn" disabled={indo || !usuario || !senha}>
          {indo ? 'Entrando…' : 'Entrar'}
        </button>
        <div className="nota-centro">Esqueceu a senha? Peça ao administrador da sua empresa no SightOps.</div>
        <div className="versao">Versão {VERSAO} · conexão protegida</div>
      </form>
    </section>
  );
}

/* ─────────────────────────── G · PIN ─────────────────────────── */
function Teclado({ aoDigito, aoApagar }: { aoDigito: (d: string) => void; aoApagar: () => void }) {
  return (
    <div className="teclado">
      {['1', '2', '3', '4', '5', '6', '7', '8', '9'].map((d) => (
        <button key={d} type="button" onClick={() => aoDigito(d)}>{d}</button>
      ))}
      <span />
      <button type="button" onClick={() => aoDigito('0')}>0</button>
      <button type="button" className="vazio" aria-label="Apagar dígito" onClick={aoApagar}>{Icone.apagar}</button>
    </div>
  );
}

function Bolas({ n, erro }: { n: number; erro: boolean }) {
  return (
    <div className={`bolas${erro ? ' erro' : ''}`} aria-label={`${n} de 4 dígitos digitados`}>
      {[0, 1, 2, 3].map((i) => <span key={i} className={i < n ? 'on' : ''} />)}
    </div>
  );
}

/** Desbloqueio: confere o PIN. 5 erros = sessao apagada, volta a pedir a senha. */
export function Pin(
  { nome, aoAbrir, aoEsquecer }: { nome: string; aoAbrir: () => void; aoEsquecer: () => void },
) {
  const [pin, setPin] = useState('');
  const [msg, setMsg] = useState('');
  const [erro, setErro] = useState(false);

  async function digitar(d: string) {
    if (pin.length >= 4) return;
    const novo = pin + d;
    setPin(novo);
    setErro(false);
    if (novo.length < 4) return;
    const r = await conferirPin(novo);
    if (r.ok) { aoAbrir(); return; }
    setErro(true);
    setPin('');
    if (r.restam <= 0) { aoEsquecer(); return; }
    setMsg(`PIN errado. ${r.restam} ${r.restam === 1 ? 'tentativa' : 'tentativas'} antes de pedir a senha.`);
  }

  const primeiro = (nome || '').trim().split(/\s+/)[0];
  return (
    <section className="tela-cheia pin">
      <span className="avatar-grande">{iniciais(nome)}</span>
      <div>
        <h1>{primeiro ? `Olá, ${primeiro}` : 'Olá'}</h1>
        <p>Digite o PIN para abrir</p>
      </div>
      <Bolas n={pin.length} erro={erro} />
      <span className="msg-erro" role="status">{msg}</span>
      <Teclado aoDigito={digitar} aoApagar={() => setPin(pin.slice(0, -1))} />
      <div className="pe">
        <button type="button" className="link" onClick={aoEsquecer}>Entrar com usuário e senha</button>
        <small>Depois de {MAX_ERROS} tentativas erradas, pede a senha de novo.</small>
      </div>
    </section>
  );
}

/** Criar PIN: digita duas vezes. "Agora não" segue sem PIN. */
export function CriarPin({ aoTerminar }: { aoTerminar: () => void }) {
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
    <section className="tela-cheia pin">
      <span className="avatar-grande">{Icone.cadeado}</span>
      <div>
        <h1>{primeiro ? 'Repita o PIN' : 'Crie um PIN'}</h1>
        <p>4 números para abrir o app sem digitar a senha</p>
      </div>
      <Bolas n={pin.length} erro={erro} />
      <span className="msg-erro" role="status">{msg}</span>
      <Teclado aoDigito={digitar} aoApagar={() => setPin(pin.slice(0, -1))} />
      <div className="pe">
        <button type="button" className="link" onClick={aoTerminar}>Agora não</button>
        <small>O PIN fica só neste aparelho. A senha continua valendo.</small>
      </div>
    </section>
  );
}

/* ─────────────────────────── I · Escolher site ─────────────────────────── */
export function ListaSites({ atual, aoEscolher }: { atual?: string | null; aoEscolher: (s: string) => void }) {
  const cons = useConectores();
  const cams = useEntidades('camera');
  const [busca, setBusca] = useState('');
  if (cons.isPending && !cons.data) return <Carregando />;
  if (cons.error && !cons.data) return <Vazio>{(cons.error as Error).message}</Vazio>;
  const porSite = new Map<string, boolean>();
  for (const c of cons.data ?? []) {
    const s = siteDoConector(c);
    if (s) porSite.set(s, (porSite.get(s) ?? false) || !!c.online);
  }
  const todos = [...porSite.keys()].sort(ordemNatural);
  const lista = todos.filter((s) => s.toUpperCase().includes(busca.trim().toUpperCase()));
  if (!todos.length) return <Vazio>Nenhum site com conector.<br />Conecte uma vez para baixar a lista.</Vazio>;
  return (
    <>
      {todos.length > 6 ? (
        <label className="busca" style={{ margin: '10px 16px 4px' }}>
          {Icone.busca}
          <input type="search" placeholder="Buscar site" aria-label="Buscar site" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </label>
      ) : null}
      {lista.map((s) => {
        const on = porSite.get(s);
        const n = (cams.data ?? []).filter((c) => mesmoSite(c.site, s)).length;
        return (
          <button key={s} type="button" className="item" onClick={() => aoEscolher(s)}>
            <span className="ic">{Icone.predio}</span>
            <span className="corpo">
              <span className="t">{s}</span>
              <span className="s">{n ? `${n} câmeras` : 'sem câmera no inventário'}</span>
            </span>
            {s === atual ? <span className="selo verde">atual</span>
              : <span className={`selo ${on ? 'verde' : 'ambar'}`}>{on ? 'online' : 'sem conector'}</span>}
          </button>
        );
      })}
    </>
  );
}

export function EscolherSite({ aoEscolher }: { aoEscolher: (s: string) => void }) {
  return (
    <section className="tela-cheia passo-tela" style={{ paddingLeft: 0, paddingRight: 0 }}>
      <div style={{ padding: '0 20px' }}>
        <h1>Onde você está?</h1>
        <p className="sub">O site guia o resto do app. Troca a qualquer hora no topo da tela.</p>
      </div>
      <div className="cartao" style={{ margin: '0 16px' }}>
        <ListaSites aoEscolher={aoEscolher} />
      </div>
    </section>
  );
}
