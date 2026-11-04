import { useState, type FormEvent } from 'react';
import { entrar } from '../lib/api';

export const VERSAO = '1.0.0';

export function Logo({ tamanho = 72 }: { tamanho?: number }) {
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 100 100" aria-hidden="true">
      <rect width="100" height="100" rx="24" fill="#1971c2" />
      <circle cx="50" cy="52" r="24" fill="none" stroke="#fff" strokeWidth="7" />
      <circle cx="50" cy="52" r="9" fill="#a5d8ff" />
      <path d="M70 19a36 36 0 0 1 13 15" fill="none" stroke="#a5d8ff" strokeWidth="6" strokeLinecap="round" />
    </svg>
  );
}

export function Abertura() {
  return (
    <div className="abertura">
      <Logo tamanho={96} />
      <strong>SightOps PDV</strong>
      <span>Vendas, caixas e vídeo na sua mão</span>
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
    <form className="login" onSubmit={enviar}>
      <div className="login-topo">
        <Logo tamanho={64} />
        <h1>SightOps PDV</h1>
        <p>Entre com o mesmo usuário do SightOps.</p>
      </div>
      <label className="campo"><span>Usuário</span>
        <input autoComplete="username" autoCapitalize="none" value={usuario} onChange={(e) => setUsuario(e.target.value)} required /></label>
      <label className="campo"><span>Senha</span>
        <input type="password" autoComplete="current-password" value={senha} onChange={(e) => setSenha(e.target.value)} required /></label>
      {erro ? <p className="msg-erro">{erro}</p> : null}
      <button type="submit" className="btn" disabled={indo}>{indo ? 'Entrando…' : 'Entrar'}</button>
      <p className="versao">versão {VERSAO}</p>
    </form>
  );
}
