import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { MARCA } from '../lib/marca';
import { haQuanto, hora, num, useAlertas, useCameras, useSite, type Alerta, type Situacao } from '../lib/termico';
import { Carregando, Erro, Foto, Icone, Logo } from '../ui/pecas';

const ROTULO: Record<Situacao, [string, string]> = { novo: ['Novo', 'alerta'], visto: ['Visto', 'ok'], falso: ['Falso', 'aviso'] };
const FILTROS: [Situacao, string][] = [['novo', 'Novos'], ['visto', 'Vistos'], ['falso', 'Falsos']];

function saudacao(): string {
  const h = new Date().getHours();
  return h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
}

function Destaque({ a }: { a: Alerta }) {
  const c = a.mancha?.caixa;
  return (
    <Link to={`/alerta/${a.id}`} className="destaque">
      <div className="destaque-foto">
        <Foto caminho={a.fotos.termico} alt="Imagem térmica do alerta" />
        {c ? <span className="caixa" style={{ left: `${c[0] * 100}%`, top: `${c[1] * 100}%`, width: `${c[2] * 100}%`, height: `${c[3] * 100}%` }} /> : null}
        <span className="selo alerta">{a.mancha?.teste ? 'TESTE' : `PESSOA · ${num(a.temp_c)} °C`}</span>
        <span className="selo escuro dir">{haQuanto(a.criado_at)}</span>
      </div>
      <div className="destaque-texto">
        <div className="cresce"><b>{a.camera_nome}</b><small>{a.site}</small></div>
        <span className="bt-abrir">Abrir</span>
      </div>
    </Link>
  );
}

export function Inicio() {
  const al = useAlertas();
  const cams = useCameras();
  const { site, abrirSeletor } = useSite();
  const [filtro, setFiltro] = useState<Situacao>('novo');

  const doSite = useMemo(() => (al.data?.alertas || []).filter((a) => !site || a.site === site), [al.data, site]);
  const camsSite = (cams.data?.cameras || []).filter((c) => !site || c.site === site);
  const vigiando = camsSite.filter((c) => c.ativo && c.leitura === 'ok').length;
  const semLeitura = camsSite.filter((c) => c.ativo && c.leitura === 'erro').length;
  const novos = doSite.filter((a) => a.situacao === 'novo');
  const conta = (s: Situacao) => doSite.filter((a) => a.situacao === s).length;
  const lista = doSite.filter((a) => a.situacao === filtro);
  const [primeiro, ...resto] = lista;

  return (
    <>
      <header className="topo">
        <span className="topo-anel" aria-hidden="true" />
        <div className="linha"><Logo /><span className="cresce topo-nome">{MARCA.nome}</span></div>
        <div>
          <small>{saudacao()}</small>
          <button type="button" className="bt-usina" onClick={abrirSeletor}>{site || 'Todas as usinas'}{Icone.baixo}</button>
        </div>
      </header>
      <div className="pagina sobe">
        <section className="cartao status">
          <span className="ic-status">{Icone.escudo}</span>
          <div className="cresce">
            <b>Vigiando {vigiando} câmera{vigiando === 1 ? '' : 's'}</b>
            <small>{semLeitura ? `${semLeitura} sem medição de temperatura` : 'leitura a cada 2 s'}</small>
          </div>
          <div className={`numero ${novos.length ? 'tem' : ''}`}><b>{novos.length}</b><small>novos</small></div>
        </section>

        <div className="chips">
          {FILTROS.map(([s, nome]) => (
            <button key={s} type="button" className={filtro === s ? 'on' : ''} onClick={() => setFiltro(s)}>{nome} · {conta(s)}</button>
          ))}
        </div>

        {al.isLoading ? <Carregando /> : al.error ? <Erro erro={al.error} /> : null}
        {al.data && !lista.length ? (
          <div className="vazio">{filtro === 'novo' ? 'Nenhum alerta sem resposta.' : 'Nada por aqui.'}</div>
        ) : null}

        {primeiro && filtro === 'novo' ? (
          <>
            <div className="titulo-agora"><i />Agora</div>
            <Destaque a={primeiro} />
          </>
        ) : null}
        {(filtro === 'novo' ? resto : lista).length ? <div className="titulo-sec">{filtro === 'novo' ? 'Hoje mais cedo' : 'Mais recentes primeiro'}</div> : null}
        {(filtro === 'novo' ? resto : lista).map((a) => (
          <Link key={a.id} to={`/alerta/${a.id}`} className="cartao item">
            <div className="item-foto"><Foto caminho={a.fotos.termico} alt="" /></div>
            <div className="cresce"><b>{a.camera_nome}</b><small>{a.site} · {hora(a.criado_at)}</small></div>
            <span className={`etq ${ROTULO[a.situacao][1]}`}>{ROTULO[a.situacao][0]}</span>
          </Link>
        ))}
      </div>
    </>
  );
}
