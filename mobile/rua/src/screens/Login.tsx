import { useState, type FormEvent } from 'react';
import { entrar } from '../lib/api';

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
      // A recusa do servidor e mais util que qualquer resumo nosso; so o
      // caso "nem chegou la" precisa de traducao.
      const m = e instanceof Error ? e.message : '';
      setErro(m && m !== 'Failed to fetch' ? m : 'Sem conexao com o servidor.');
    } finally {
      setIndo(false);
    }
  }

  return (
    <section className="login">
      <div className="login-card">
        <div className="login-marca">
          <span className="brand-mark">S</span>
          <div>
            <strong>SightOps</strong>
            <span>Rua · aplicativo do tecnico</span>
          </div>
        </div>

        <form className="login-form" onSubmit={enviar}>
          <div className="campo">
            <label htmlFor="u">Usuario</label>
            <input id="u" value={usuario} onChange={(e) => setUsuario(e.target.value)}
                   autoComplete="username" autoCapitalize="none" spellCheck={false} required />
          </div>
          <div className="campo">
            <label htmlFor="p">Senha</label>
            <input id="p" type="password" value={senha} onChange={(e) => setSenha(e.target.value)}
                   autoComplete="current-password" required />
          </div>
          {erro ? <p className="login-erro">{erro}</p> : null}
          <button type="submit" className="acao-forte" disabled={indo}>
            {indo ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </section>
  );
}
