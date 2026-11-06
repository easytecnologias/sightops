import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { enviar, obter } from '../lib/api';
import { avisosLigados, tokenDoAparelho } from '../lib/aviso';
import { MARCA } from '../lib/marca';
import { Icone, Logo } from '../ui/pecas';

export function Conta({ aoSair }: { aoSair: () => void }) {
  const eu = useQuery({ queryKey: ['eu'], queryFn: () => obter<{ username?: string; nome?: string; role?: string }>('/api/auth/me') });
  const [ligados, setLigados] = useState<boolean | null>(null);
  const [msg, setMsg] = useState('');
  const [ocupado, setOcupado] = useState(false);
  useEffect(() => { void avisosLigados().then(setLigados); }, []);

  async function testar() {
    setOcupado(true);
    setMsg('');
    try {
      const token = await tokenDoAparelho();
      if (!token) throw new Error('Este celular ainda não recebeu autorização para notificações.');
      await enviar('/api/termico/aparelhos/teste', { token });
      setMsg('Enviada. A sirene deve tocar em alguns segundos.');
    } catch (e) {
      setMsg((e as Error).message || 'Não deu para testar agora.');
    } finally {
      setOcupado(false);
    }
  }

  return (
    <>
      <header className="topo baixo"><span className="topo-anel" aria-hidden="true" /><small>{MARCA.empresa}</small><h1>Conta</h1></header>
      <div className="pagina">
        <section className="cartao status">
          <span className="ic-status">{Icone.conta}</span>
          <div className="cresce"><b>{eu.data?.nome || eu.data?.username || 'Sua conta'}</b><small>{eu.data?.username ? `usuário ${eu.data.username}` : MARCA.empresa}</small></div>
        </section>
        <section className="cartao conta-aviso">
          <div className="linha">
            <div className="cresce"><b>Notificações</b>
              <small>{ligados === null ? 'Conferindo…' : ligados ? 'Neste celular, com sirene' : 'Você não vai receber os alarmes'}</small></div>
            <span className={`etq ${ligados ? 'ok' : 'alerta'}`}>{ligados ? 'Ligadas' : 'Desligadas'}</span>
          </div>
          <button type="button" className="btn" disabled={ocupado} onClick={() => void testar()}>{ocupado ? 'Enviando…' : 'Testar notificação'}</button>
          {msg ? <small>{msg}</small> : null}
        </section>
        <section className="cartao status"><Logo /><div className="cresce"><b>{MARCA.nome}</b><small>versão {MARCA.versao} · tecnologia SightOps</small></div></section>
        <button type="button" className="btn2" onClick={aoSair}>Sair</button>
      </div>
    </>
  );
}
