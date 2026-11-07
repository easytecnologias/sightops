import { useState } from 'react';
import { Sino } from './Alertas';
import { Link, useNavigate } from 'react-router-dom';
import { ehAdmin, ICONE, textoAcao, textoGatilho, useAutomacoes, useEu, useExecutarCena, useLigarRegra, type Regra } from '../lib/automacoes';
import { natural, useCameras, useSite } from '../lib/termico';
import { Carregando, Erro, Icone } from '../ui/pecas';

export function IcAuto({ tipo, peq }: { tipo: string; peq?: boolean }) {
  const [cor, d] = ICONE[tipo] || ICONE.manual;
  return <span className={`ic ${cor} ${peq ? 'peq' : ''}`} aria-hidden="true"><svg viewBox="0 0 24 24"><path d={d} /></svg></span>;
}

const tipoIcone = (r: Regra) => {
  const a = r.acoes[0];
  if (!a) return 'manual';
  return a.tipo === 'saida' && (a.segundos || 0) >= 60 ? 'refletor' : a.tipo;
};

/** Cenas de um toque e automacoes "Se... entao...", no modelo dos apps de casa inteligente. */
export function Automacoes() {
  const lista = useAutomacoes();
  const cams = useCameras();
  const eu = useEu();
  const admin = ehAdmin(eu.data?.role);
  const nav = useNavigate();
  const { site, abrirSeletor } = useSite();
  const [aba, setAba] = useState<'cenas' | 'automacoes'>('cenas');
  const [rodou, setRodou] = useState('');
  const cena = useExecutarCena();
  const ligar = useLigarRegra();

  const nomeCam = (id: string) => cams.data?.cameras.find((c) => c.id === id)?.nome || 'câmera removida';
  const nomeRegra = (id: string) => lista.data?.automacoes.find((r) => r.id === id)?.nome || 'outra automação';
  const daUsina = (r: Regra) => !site || r.acoes.some((a) => a.site === site) || r.gatilhos.some((g) => 'site' in g && g.site === site);
  const regras = (lista.data?.automacoes || []).filter(daUsina).sort((a, b) => natural(a.nome, b.nome));
  const cenas = regras.filter((r) => r.cena);
  const autos = regras.filter((r) => !r.cena);

  function executar(r: Regra) {
    setRodou('');
    cena.mutate(r.id || '', { onSuccess: () => setRodou(`${r.nome}: ${r.modo === 'valer' ? 'executando' : 'simulada, nada foi acionado'}`) });
  }

  return (
    <>
      <header className="fx">
        <div className="fx-top"><span className="fx-nome grande">Automações</span><Sino />
          <button type="button" className="fx-us" onClick={abrirSeletor}><span>{site || 'Todas as usinas'}</span>{Icone.baixo}</button></div>
        <div className="alternar vidro" role="tablist" aria-label="Tipo">
          <button type="button" role="tab" aria-selected={aba === 'cenas'} className={aba === 'cenas' ? 'on' : ''} onClick={() => setAba('cenas')}>Cenas</button>
          <button type="button" role="tab" aria-selected={aba === 'automacoes'} className={aba === 'automacoes' ? 'on' : ''} onClick={() => setAba('automacoes')}>Automações</button>
        </div>
      </header>
      <div className="pagina com-fab">
        {lista.isLoading ? <Carregando /> : lista.error ? <Erro erro={lista.error} /> : null}
        {rodou ? <div className="cartao aviso-ok">{rodou}</div> : null}
        {cena.error ? <p className="msg-erro">{(cena.error as Error).message}</p> : null}
        {aba === 'cenas' ? (
          cenas.length ? (
            <div className="cenas">
              {cenas.map((r) => (
                <div key={r.id} className="cena">
                  <IcAuto tipo={tipoIcone(r)} />
                  <span><b>{r.nome}</b><small>{r.acoes.length} ação(ões){r.modo === 'valer' ? '' : ' · simulando'}</small></span>
                  <button type="button" className="play" aria-label={`Executar ${r.nome}`} disabled={cena.isPending} onClick={() => executar(r)}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z" /></svg></button>
                  {admin ? <Link to={`/automacao/${r.id}`} className="cena-editar" aria-label={`Editar ${r.nome}`}>Editar</Link> : null}
                </div>
              ))}
            </div>
          ) : <div className="vazio">Nenhuma cena ainda.{admin ? ' Toque em + para criar, por exemplo "Acender refletores".' : ''}</div>
        ) : autos.length ? autos.map((r) => {
          const [g1, g2] = textoGatilho(r.gatilhos[0], nomeCam);
          const [a1] = r.acoes[0] ? textoAcao(r.acoes[0], nomeRegra) : ['Sem ação'];
          return (
            <article key={r.id} className={`au ${r.ativo ? '' : 'off'}`}>
              <div className="au-top">
                <Link to={admin ? `/automacao/${r.id}` : '#'} className="au-nome"><b>{r.nome}</b></Link>
                <span className={`tag ${r.modo === 'valer' ? 'vl' : ''}`}>{r.modo === 'valer' ? 'Valendo' : 'Simular'}</span>
                <button type="button" role="switch" aria-checked={r.ativo} aria-label={`Ligar ${r.nome}`} className={`cv ${r.ativo ? '' : 'off'}`}
                  disabled={!admin || ligar.isPending} onClick={() => ligar.mutate({ id: r.id || '', ativo: !r.ativo })}><i /></button>
              </div>
              <div className="au-fl"><IcAuto tipo={r.gatilhos[0].tipo} peq /><i>→</i><IcAuto tipo={tipoIcone(r)} peq />
                <span className="t">{g1} · {g2} → {a1}{r.acoes.length > 1 ? ` e mais ${r.acoes.length - 1}` : ''}</span></div>
            </article>
          );
        }) : <div className="vazio">Nenhuma automação ainda.{admin ? ' Toque em + para criar.' : ''}</div>}
        {!admin && eu.data ? <small className="bloco">Só administrador cria ou muda automações. Cenas você pode executar.</small> : null}
      </div>
      {admin ? (
        <button type="button" className="fab" aria-label="Nova automação" onClick={() => nav(`/automacao/nova?cena=${aba === 'cenas' ? 1 : 0}`)}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg></button>
      ) : null}
    </>
  );
}
