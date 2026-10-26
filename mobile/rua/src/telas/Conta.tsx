import { useNavigate } from 'react-router-dom';
import { useEu } from '../lib/dados';
import { Icone, iniciais } from '../ui/pecas';
import { VERSAO } from './Entrada';

/* 12 · Conta e aparelho */
export function Conta(
  { aoSair, aoTrocarPin, aoVerApresentacao }:
  { aoSair: () => void; aoTrocarPin: () => void; aoVerApresentacao: () => void },
) {
  const eu = useEu();
  const ir = useNavigate();
  const nome = eu.data?.full_name || eu.data?.username || '';
  return (
    <section className="tela-cheia" style={{ padding: 0, background: 'var(--bg)' }}>
      <header className="topo-conta">
        <button type="button" className="link" style={{ color: 'var(--mint)', alignSelf: 'flex-start', marginLeft: -6 }} onClick={() => ir(-1)}>
          <span style={{ display: 'inline-flex', width: 20, height: 20 }}>{Icone.volta}</span>Voltar
        </button>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span className="avatar-conta">{iniciais(nome)}</span>
          <span>
            <span style={{ display: 'block', fontWeight: 700, fontSize: 18 }}>{nome || '—'}</span>
            <span style={{ display: 'block', fontSize: 13, color: 'var(--escuro-txt)' }}>
              {[eu.data?.username, eu.data?.tenant_name].filter(Boolean).join(' · ')}
            </span>
          </span>
        </div>
      </header>
      <main className="conteudo">
        <span className="rot-secao">Segurança</span>
        <section className="cartao">
          <button type="button" className="item" onClick={aoTrocarPin}>
            <span className="corpo"><span className="t">Trocar o PIN</span><span className="s">4 números para abrir sem a senha</span></span>{Icone.seta}
          </button>
        </section>
        <span className="rot-secao">Sobre</span>
        <section className="cartao">
          <div className="item"><span className="corpo"><span className="t">Versão</span></span><span className="mono">{VERSAO}</span></div>
          <button type="button" className="item" onClick={aoVerApresentacao}>
            <span className="corpo"><span className="t">Ver a apresentação de novo</span></span>{Icone.seta}
          </button>
        </section>
        <button type="button" className="btn2 sair" onClick={aoSair}>{Icone.sair}Sair deste aparelho</button>
        <p className="sub-tela" style={{ textAlign: 'center' }}>Sair apaga a sessão e o PIN deste celular.</p>
      </main>
    </section>
  );
}
