import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { hora, natural, useAlertas, useSite, type Alerta, type Situacao } from '../lib/termico';
import { Carregando, Erro, Foto, Icone } from '../ui/pecas';

const ROTULO: Record<Situacao, [string, string]> = { novo: ['Novo', 'alerta'], visto: ['Ciente', 'ok'], falso: ['Falso', 'aviso'] };

/** Sininho no topo de todas as telas: alarmes sem resposta em destaque. */
export function Sino() {
  const al = useAlertas();
  const { site } = useSite();
  const n = (al.data?.alertas || []).filter((a) => a.situacao === 'novo' && (!site || a.site === site)).length;
  return (
    <Link to="/alertas" className="sino" aria-label={n ? `Alarmes: ${n} sem resposta` : 'Alarmes'}>
      {Icone.sino}{n ? <span className="sino-n">{n > 99 ? '99+' : n}</span> : null}
    </Link>
  );
}

function dia(iso: string): string {
  const d = new Date(iso);
  const hoje = new Date();
  const ontem = new Date(Date.now() - 864e5);
  if (d.toDateString() === hoje.toDateString()) return 'Hoje';
  if (d.toDateString() === ontem.toDateString()) return 'Ontem';
  return d.toLocaleDateString('pt-BR', { weekday: 'long', day: '2-digit', month: '2-digit' });
}

/** Lista de todos os alarmes, por dia, com filtro de situacao e de usina. */
export function Alertas() {
  const al = useAlertas();
  const nav = useNavigate();
  const { site, abrirSeletor } = useSite();
  const [filtro, setFiltro] = useState<Situacao | ''>('');
  const doSite = useMemo(() => (al.data?.alertas || []).filter((a) => !site || a.site === site), [al.data, site]);
  const conta = (s: Situacao) => doSite.filter((a) => a.situacao === s).length;
  const lista = doSite.filter((a) => !filtro || a.situacao === filtro);
  const grupos = useMemo(() => {
    const m = new Map<string, Alerta[]>();
    for (const a of lista) m.set(dia(a.criado_at), [...(m.get(dia(a.criado_at)) || []), a]);
    return [...m.entries()];
  }, [lista]);

  return (
    <>
      <header className="fx">
        <div className="fx-top">
          <button type="button" className="bt-redondo escuro" aria-label="Voltar" onClick={() => nav(-1)}>{Icone.voltar}</button>
          <span className="fx-nome grande">Alarmes</span>
          <button type="button" className="fx-us" onClick={abrirSeletor}><span>{site || 'Todas as usinas'}</span>{Icone.baixo}</button>
        </div>
        <div className="mets">
          <div><span>Sem resposta</span><b>{conta('novo')}</b></div>
          <div><span>Ciente</span><b>{conta('visto')}</b></div>
          <div><span>Falsos</span><b>{conta('falso')}</b></div>
        </div>
      </header>
      <div className="pagina">
        <div className="chips">
          {([['', 'Todos'], ['novo', 'Novos'], ['visto', 'Ciente'], ['falso', 'Falsos']] as [Situacao | '', string][]).map(([s, nome]) => (
            <button key={nome} type="button" className={filtro === s ? 'on' : ''} onClick={() => setFiltro(s)}>{nome}</button>
          ))}
        </div>
        {al.isLoading ? <Carregando /> : al.error ? <Erro erro={al.error} /> : null}
        {al.data && !lista.length ? <div className="vazio">{filtro === 'novo' ? 'Nenhum alarme sem resposta.' : 'Nenhum alarme por aqui.'}</div> : null}
        {grupos.map(([nome, itens]) => (
          <section key={nome} className="grupo">
            <div className="linha"><span className="titulo-sec cresce">{nome}</span><small>{itens.length}</small></div>
            {[...itens].sort((a, b) => natural(b.criado_at, a.criado_at)).map((a) => (
              <Link key={a.id} to={`/alerta/${a.id}`} className="cartao item">
                <div className="item-foto ferro"><Foto caminho={a.fotos.termico} alt="" /></div>
                <div className="cresce"><b>{a.mancha?.teste ? 'Alarme de teste' : a.camera_nome}</b><small>{a.site} · {hora(a.criado_at)}</small></div>
                <span className={`etq ${ROTULO[a.situacao][1]}`}>{ROTULO[a.situacao][0]}</span>
              </Link>
            ))}
          </section>
        ))}
      </div>
    </>
  );
}
