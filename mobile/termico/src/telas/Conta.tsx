import { useEffect, useState } from 'react';
import { Sino } from './Alertas';
import { enviar } from '../lib/api';
import { useEu } from '../lib/automacoes';
import { avisosLigados, tokenDoAparelho } from '../lib/aviso';
import { MARCA } from '../lib/marca';
import { pegar, salvar } from '../lib/storage';
import { Logo } from '../ui/pecas';

export function Conta({ aoSair }: { aoSair: () => void }) {
  const eu = useEu();
  const [ligados, setLigados] = useState<boolean | null>(null);
  const [msg, setMsg] = useState('');
  const [ocupado, setOcupado] = useState(false);
  const [hd, setHd] = useState(false);
  useEffect(() => { void avisosLigados().then(setLigados); void pegar('termico.hd').then((v) => setHd(v === '1')); }, []);
  const mudarHd = (v: boolean) => { setHd(v); void salvar('termico.hd', v ? '1' : '0'); };

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
      <header className="fx">
        <div className="fx-top"><Logo tam={36} /><span className="fx-nome grande">Conta</span><Sino /></div>
        <div className="est"><div><b>{eu.data?.display_name || eu.data?.nome || eu.data?.username || 'Sua conta'}</b><small>{MARCA.empresa}</small></div></div>
      </header>
      <div className="pagina">
        <section className="cartao conta-aviso">
          <div className="linha">
            <div className="cresce"><b>Notificações</b>
              <small>{ligados === null ? 'Conferindo…' : ligados ? 'Neste celular, com sirene' : 'Você não vai receber os alarmes'}</small></div>
            <span className={`etq ${ligados ? 'ok' : 'alerta'}`}>{ligados ? 'Ligadas' : 'Desligadas'}</span>
          </div>
          <button type="button" className="btn" disabled={ocupado} onClick={() => void testar()}>{ocupado ? 'Enviando…' : 'Testar notificação'}</button>
          {msg ? <small>{msg}</small> : null}
        </section>
        <section className="cartao conta-aviso">
          <div><b>Qualidade do vídeo</b><small className="bloco">SD gasta menos a internet da usina</small></div>
          <div className="alternar largo" role="group" aria-label="Qualidade padrão">
            <button type="button" className={hd ? '' : 'on'} onClick={() => mudarHd(false)}>SD</button>
            <button type="button" className={hd ? 'on' : ''} onClick={() => mudarHd(true)}>HD</button>
          </div>
        </section>
        <section className="cartao status"><Logo /><div className="cresce"><b>{MARCA.nome}</b><small>versão {MARCA.versao} · tecnologia SightOps</small></div></section>
        <button type="button" className="btn2" onClick={aoSair}>Sair</button>
      </div>
    </>
  );
}
