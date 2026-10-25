import { useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { Folha, Icone } from './pecas';
import { ListaLocais, VERSAO } from '../telas/Entrada';
import { useOnline } from '../lib/rede';
import { escolherLocal, useLocal } from '../lib/local';
import { pendentes, useEu, useTriagem, useVisaoGeral } from '../lib/dados';
import { iniciais } from '../lib/cpf';
import { useCadastro } from '../lib/cadastro';

export function Shell(
  { children, aoSair, aoTrocarPin }:
  { children: ReactNode; aoSair: () => void; aoTrocarPin: () => void },
) {
  const online = useOnline();
  const local = useLocal();
  const eu = useEu();
  const visao = useVisaoGeral(local);
  const triagem = useTriagem();
  const { zerar } = useCadastro();
  const ir = useNavigate();
  const [folha, setFolha] = useState<'' | 'local' | 'conta'>('');

  const nome = eu.data?.full_name || eu.data?.username || '';
  const lt = visao.data?.leitores;
  const fila = pendentes(triagem.data, local).length;
  const lado = !online ? 'Sem sinal' : lt ? (lt.total ? `${lt.online} de ${lt.total} leitores` : 'sem leitor') : '…';
  const tudoNoAr = online && (!lt || !lt.total || lt.online === lt.total);

  return (
    <div className="app">
      <header className="cabecalho">
        <div className="cab-l1">
          <span className="marca"><span className={`viva${online ? '' : ' off'}`} />SightOps <small>Acesso</small></span>
          <button type="button" className="conta" aria-label="Conta e aparelho" onClick={() => setFolha('conta')}>
            {iniciais(nome)}
          </button>
        </div>
        <button type="button" className="seletor" onClick={() => setFolha('local')}>
          <span>
            <span className="rot">Local</span>
            <span className="val">{local || 'Escolher local'}</span>
          </span>
          <span className="lado"><span className={`ponto${tudoNoAr ? '' : ' off'}`} />{lado}{Icone.baixo}</span>
        </button>
      </header>

      <main className="conteudo">{children}</main>

      <nav className="barra-baixo" aria-label="Navegação do Acesso">
        <NavLink to="/" end className={({ isActive }) => (isActive ? 'ativo' : '')}>{Icone.casa}Início</NavLink>
        <NavLink to="/pessoas" className={({ isActive }) => (isActive ? 'ativo' : '')}>{Icone.pessoas}Pessoas</NavLink>
        <a href="#/cadastro/foto" aria-label="Cadastrar pessoa"
           onClick={(e) => { e.preventDefault(); zerar(); ir('/cadastro/foto'); }}>
          <span className="mais">{Icone.mais}</span>Cadastrar
        </a>
        <NavLink to="/triagem" className={({ isActive }) => (isActive ? 'ativo' : '')}>
          {fila > 0 ? <span className="contador">{fila > 99 ? '99+' : fila}</span> : null}
          {Icone.conversa}Triagem
        </NavLink>
        <NavLink to="/visitante" className={({ isActive }) => (isActive ? 'ativo' : '')}>{Icone.cracha}Visitante</NavLink>
      </nav>

      {folha === 'local' ? (
        <Folha titulo="Onde você está" sub="O local guia o resto do app e fica guardado no aparelho." aoFechar={() => setFolha('')}>
          <div className="folha-lista">
            <ListaLocais atual={local} aoEscolher={(s) => { escolherLocal(s); setFolha(''); ir('/'); }} />
          </div>
        </Folha>
      ) : null}

      {folha === 'conta' ? (
        <Folha titulo={nome || 'Conta'} sub={[eu.data?.username, eu.data?.tenant_name].filter(Boolean).join(' · ')}
               aoFechar={() => setFolha('')}>
          <div className="folha-corpo">
            <button type="button" className="btn2" onClick={() => { setFolha(''); aoTrocarPin(); }}>
              {Icone.cadeado}Trocar o PIN
            </button>
            <button type="button" className="btn2" onClick={() => { setFolha(''); aoSair(); }}>
              {Icone.sair}Sair deste aparelho
            </button>
            <p className="nota-centro" style={{ margin: '4px 0 0', fontSize: 12.5 }}>
              SightOps Acesso {VERSAO}. Sair apaga a sessão e o PIN deste celular.
            </p>
          </div>
        </Folha>
      ) : null}
    </div>
  );
}
