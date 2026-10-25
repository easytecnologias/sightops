import { useState, type FormEvent, type ReactNode } from 'react';
import { entrar } from '../lib/api';
import { conferirPin, criarPin, MAX_ERROS } from '../lib/pin';
import { iniciais } from '../lib/cpf';
import { escolherLocal } from '../lib/local';
import { useVisaoGeral } from '../lib/dados';
import { vocab } from '../lib/vocab';
import { Carregando, Icone, Logo, Vazio } from '../ui/pecas';

export const VERSAO = '1.1.0';

/* ─────────────────────────── B · Abertura ─────────────────────────── */
export function Abertura() {
  return (
    <div className="abertura">
      <Logo tamanho={112} />
      <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
        <span className="nome">SightOps</span>
        <span className="sub">Acesso · cadastro e portaria</span>
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
    titulo: 'Cadastre pelo celular',
    texto: 'Foto do rosto, dados e portas em três passos. A pessoa entra pelo leitor facial, sem cartão.',
    vitrine: (
      <>
        <Mini titulo="Foto boa para o leitor" sub="rosto inteiro, boa luz" />
        <Mini titulo="CPF conferido" sub="não repete ninguém" desloca={18} />
        <Mini titulo="Enviado aos leitores" sub="entrada e portão" desloca={36} selo="4/4" />
      </>
    ),
  },
  {
    titulo: 'Frequência na mão',
    texto: 'Quem veio, quem faltou e em que dias, por turma. Mande o PDF pelo WhatsApp ou e-mail.',
    vitrine: (
      <>
        <Mini titulo="5º Ano · 96%" sub="31 alunos · 4 faltas" />
        <Mini titulo="8º Ano · 91%" sub="28 alunos · 2 com 3+ faltas" desloca={18} />
        <Mini titulo="PDF da frequência" sub="pronto para enviar" desloca={36} selo="PDF" />
      </>
    ),
  },
  {
    titulo: 'Portaria ao vivo',
    texto: 'Veja quem passa em cada leitor e abra ou feche a porta pelo celular.',
    vitrine: (
      <>
        <Mini titulo="Entrou · Catraca 1" sub="07:42" />
        <Mini titulo="Entrou · Catraca 2" sub="07:41" desloca={18} />
        <Mini titulo="Saiu · Portão" sub="07:35" desloca={36} />
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
        <span>Acesso · cadastro e portaria</span>
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
        <div className="nota-centro">Esqueceu a senha? Peça ao administrador do SightOps na sua empresa.</div>
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

/* ─────────────────────────── H · Permissoes ─────────────────────────── */
export function Permissoes({ aoTerminar }: { aoTerminar: () => void }) {
  const [camera, setCamera] = useState<'' | 'ok' | 'negada'>('');

  async function pedirCamera() {
    try {
      const f = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      f.getTracks().forEach((t) => t.stop());
      setCamera('ok');
    } catch {
      setCamera('negada');
    }
  }

  return (
    <section className="tela-cheia passo-tela">
      <div>
        <h1>Antes de começar</h1>
        <p className="sub">O app pede só o que usa. Dá para mudar depois nos ajustes do celular.</p>
      </div>
      <div className="perm">
        <span className="ic">{Icone.camera}</span>
        <span style={{ flex: 1 }}>
          <b>Câmera do celular</b>
          <span className="s">Tira a foto do rosto que abre a catraca. A foto vai direto para o SightOps, não fica na galeria.</span>
          {camera === 'ok' ? <span className="feito">{Icone.ok}Permitido</span>
            : camera === 'negada' ? <span className="feito nao">{Icone.aviso}Negada · dá para usar fotos da galeria</span>
              : <button type="button" className="acao" onClick={pedirCamera}>Permitir câmera</button>}
        </span>
      </div>
      <div className="perm">
        <span className="ic">{Icone.cadeado}</span>
        <span style={{ flex: 1 }}>
          <b>Dados das pessoas</b>
          <span className="s">Nome, CPF e foto ficam no servidor do SightOps, no seu cliente. O celular guarda só a sessão e o PIN.</span>
        </span>
      </div>
      <div className="pe-fixo">
        <button type="button" className="btn" onClick={aoTerminar}>Continuar</button>
        {camera === '' ? <button type="button" className="link cinza" onClick={aoTerminar}>Agora não</button> : null}
      </div>
    </section>
  );
}

/* ─────────────────────────── I · Escolher local ─────────────────────────── */
export function ListaLocais({ atual, aoEscolher }: { atual?: string; aoEscolher: (s: string) => void }) {
  const v = useVisaoGeral('');
  const [busca, setBusca] = useState('');
  if (v.isLoading) return <Carregando />;
  if (v.error) return <Vazio>{(v.error as Error).message}</Vazio>;
  const leitores = v.data?.leitores?.lista ?? [];
  const locais = (v.data?.perfil?.locais ?? []).filter((l) => l.site.toUpperCase().includes(busca.trim().toUpperCase()));
  if (!(v.data?.perfil?.locais ?? []).length) {
    return <Vazio>Nenhum local com controle de acesso neste cliente.<br />Peça ao administrador para cadastrar os leitores.</Vazio>;
  }
  return (
    <>
      {(v.data?.perfil?.locais?.length ?? 0) > 6 ? (
        <label className="busca" style={{ margin: '10px 16px 4px' }}>
          {Icone.busca}
          <input type="search" placeholder="Buscar local" aria-label="Buscar local" value={busca} onChange={(e) => setBusca(e.target.value)} />
        </label>
      ) : null}
      {locais.map((l) => {
        const deste = leitores.filter((d) => d.site.toUpperCase() === l.site.toUpperCase());
        const on = deste.filter((d) => d.status.toLowerCase() === 'online').length;
        return (
          <button key={l.site} type="button" className="item" onClick={() => aoEscolher(l.site)}>
            <span className="ic-local">{Icone.predio}</span>
            <span className="corpo">
              <span className="t">{l.site}</span>
              <span className="s">{vocab(l.tipo).nome} · {deste.length ? `${on} de ${deste.length} leitores no ar` : 'sem leitor'}</span>
            </span>
            {l.site === atual ? <span className="selo verde">atual</span>
              : deste.length && on < deste.length ? <span className="selo ambar">{deste.length - on} fora</span>
                : <span className="seta">{Icone.seta}</span>}
          </button>
        );
      })}
    </>
  );
}

export function EscolherLocal({ aoTerminar }: { aoTerminar: () => void }) {
  return (
    <section className="tela-cheia passo-tela" style={{ paddingLeft: 0, paddingRight: 0 }}>
      <div style={{ padding: '0 20px' }}>
        <h1>Onde você está?</h1>
        <p className="sub">O local guia o resto do app. Troca a qualquer hora no topo da tela.</p>
      </div>
      <div className="cartao" style={{ margin: '0 16px' }}>
        <ListaLocais aoEscolher={(s) => { escolherLocal(s); aoTerminar(); }} />
      </div>
    </section>
  );
}
