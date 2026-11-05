import { useState, type FormEvent } from 'react';
import { entrar } from '../lib/api';
import { MARCA } from '../lib/marca';
import { Logo } from '../ui/pecas';

export function Abertura() {
  return (
    <div className="abertura">
      <Logo tam={88} />
      <strong>{MARCA.nome}</strong>
      <span>{MARCA.slogan}</span>
    </div>
  );
}

export function Login({ aoEntrar }: { aoEntrar: () => void }) {
  const [usuario, setUsuario] = useState('');
  const [senha, setSenha] = useState('');
  const [erro, setErro] = useState('');
  const [indo, setIndo] = useState(false);

  async function enviar(ev: FormEvent) {
    ev.preventDefault();
    setErro('');
    setIndo(true);
    try {
      await entrar(usuario.trim(), senha);
      aoEntrar();
    } catch (e) {
      setErro((e as Error).message || 'Não foi possível entrar.');
    } finally {
      setIndo(false);
    }
  }

  return (
    <div className="entrada">
      <div className="entrada-topo">
        <Logo tam={80} />
        <h1>{MARCA.nome}</h1>
        <p>{MARCA.slogan}</p>
      </div>
      <form className="entrada-form" onSubmit={enviar}>
        <h2>Entrar</h2>
        <label className="campo"><span>Usuário</span>
          <input autoComplete="username" autoCapitalize="none" value={usuario} onChange={(e) => setUsuario(e.target.value)} required /></label>
        <label className="campo"><span>Senha</span>
          <input type="password" autoComplete="current-password" value={senha} onChange={(e) => setSenha(e.target.value)} required /></label>
        {erro ? <p className="msg-erro">{erro}</p> : null}
        <button type="submit" className="btn" disabled={indo}>{indo ? 'Entrando…' : 'Entrar'}</button>
        <p className="versao">tecnologia SightOps · versão {MARCA.versao}</p>
      </form>
    </div>
  );
}
