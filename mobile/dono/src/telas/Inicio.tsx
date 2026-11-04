import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { diaRotulo, grave, hoje, moeda, mudarDia, num, useFiltro, useLojas, useMomentos, useResumo } from '../lib/pdv';
import { Carregando, Erro, Icone } from '../ui/pecas';
import { EscolherLoja } from './Comum';
import { LinhaMomento, semRota } from './Olhar';

const SEMANA = ['domingo', 'segunda', 'terça', 'quarta', 'quinta', 'sexta', 'sábado'];
const QUADRO: Record<string, [string, string]> = {
  em_venda: ['vendendo', 'q-venda'], livre: ['livre', 'q-livre'], parado: ['parado', 'q-parado'],
  sem_coletor: ['sem dados', 'q-sem'], desligado: ['desligado', 'q-livre'],
};

/** Hoje: em 5 segundos, se o dia esta normal e o que precisa de atencao. */
export function Inicio() {
  const { dia, setDia, loja } = useFiltro();
  const resumo = useResumo(dia, loja);
  const passada = useResumo(mudarDia(dia, -7), loja);
  const lojas = useLojas(dia);
  const mom = useMomentos(dia, loja);
  const ir = useNavigate();
  const [folhaLoja, setFolhaLoja] = useState(false);

  const r = resumo.data;
  const fechados = r?.cupons?.fechado || 0;
  const vendido = r?.vendido_centavos || 0;
  const antes = passada.data?.vendido_centavos || 0;
  const dSemana = SEMANA[new Date(`${dia}T12:00:00`).getDay()];
  const ehHoje = dia === hoje();
  // hoje o dia ainda nao acabou: compara com o dia inteiro da semana passada so como referencia
  const variacao = !ehHoje && antes ? Math.round(100 * (vendido - antes) / antes) : null;
  const graves = (mom.data?.momentos || []).filter(grave);
  const altas = graves.filter((m) => m.gravidade === 'alta').length;
  const caixas = (lojas.data?.lojas || []).filter((l) => !loja || l.nome === loja).flatMap((l) => l.caixas);
  const conta = (e: string) => caixas.filter((c) => c.estado === e).length;

  return (
    <>
      <section className="topo-azul">
        <div className="linha-entre">
          <div className="col"><span className="claro">{ehHoje ? 'Hoje' : diaRotulo(dia)}, {dSemana}</span><h1 className="um">{loja || 'Todas as lojas'}</h1></div>
          <button type="button" className="bt-vidro" onClick={() => setFolhaLoja(true)}>{Icone.loja}Loja{Icone.baixo}</button>
        </div>
        <div className="linha-entre">
          <div className="seg">
            <button type="button" className={ehHoje ? 'on' : ''} onClick={() => setDia(hoje())}>Hoje</button>
            <button type="button" className={dia === mudarDia(hoje(), -1) ? 'on' : ''} onClick={() => setDia(mudarDia(hoje(), -1))}>Ontem</button>
          </div>
          <label className="bt-vidro data">{Icone.calendario}
            <input type="date" value={dia} max={hoje()} onChange={(e) => e.target.value && setDia(e.target.value)} aria-label="Escolher o dia" /></label>
        </div>
      </section>

      <div className="pagina sobe">
        {resumo.isLoading ? <Carregando /> : resumo.error ? <Erro erro={resumo.error} aoTentar={() => resumo.refetch()} /> : (
          <Link to="/conta" className="cartao destaque">
            <span className="linha-entre"><span className="rotulo">{ehHoje ? 'Vendido até agora' : `Vendido · ${diaRotulo(dia).toLowerCase()}`}</span>
              {variacao !== null ? <span className={`selo ${variacao >= 0 ? 'verde-ok' : 'verm'}`}>{variacao >= 0 ? '+' : ''}{variacao}% vs {dSemana} passada</span> : <span className="link-azul">a conta ›</span>}</span>
            <strong className="grande">{moeda(vendido)}</strong>
            <span className="sub um">{num(fechados)} cupons · ticket {moeda(fechados ? vendido / fechados : 0)}
              {antes ? ` · ${dSemana} passada: ${moeda(antes)}${ehHoje ? ' no dia todo' : ''}` : ''}</span>
          </Link>
        )}

        {mom.isLoading ? null : mom.error ? (semRota(mom.error) ? null : <Erro erro={mom.error} aoTentar={() => mom.refetch()} />) : (
          <>
            <Link to="/olhar" className={`aviso-dia ${graves.length ? (altas ? 'alerta' : 'atencao') : 'normal'}`}>
              {graves.length ? Icone.olho : Icone.ok}
              <span className="col cresce">
                <b>{graves.length ? `${num(graves.length)} ${graves.length === 1 ? 'coisa' : 'coisas'} para olhar` : 'Dia dentro do normal'}</b>
                <small>{graves.length ? `${num(altas)} de gravidade alta · toque para ver todas` : 'nenhuma regra apontou algo grave'}</small>
              </span>
              {Icone.dir}
            </Link>
            {graves.length ? (
              <section className="cartao lista">
                {graves.slice(0, 3).map((m) => <LinhaMomento key={`${m.caixa_id}|${m.seq}|${m.regra}`} m={m} />)}
                {graves.length > 3 ? <Link to="/olhar" className="link-azul centro">Ver as {num(graves.length)}</Link> : null}
              </section>
            ) : null}
          </>
        )}

        {ehHoje && caixas.length ? (
          <section className="cartao">
            <span className="linha-entre"><b className="t14">Caixas agora</b>
              <small className="sub">{num(conta('em_venda'))} vendendo · {num(conta('livre'))} livres{conta('sem_coletor') ? ` · ${num(conta('sem_coletor'))} sem dados` : ''}</small></span>
            <div className="quadros">
              {caixas.map((c) => {
                const [txt, cls] = QUADRO[c.estado] || ['–', 'q-livre'];
                return (
                  <button type="button" key={c.id} className={`quadro ${cls}`} title={`${c.nome}: ${txt}`} onClick={() => ir(`/vivo/${encodeURIComponent(c.id)}`)}>
                    {String(c.numero || c.nome.replace(/\D+/g, '') || '?')}
                  </button>
                );
              })}
            </div>
            <span className="legenda"><span><i className="q-venda" />vendendo</span><span><i className="q-livre" />livre</span><span><i className="q-parado" />parado</span><span><i className="q-sem" />sem dados</span></span>
          </section>
        ) : null}
      </div>
      {folhaLoja ? <EscolherLoja aoFechar={() => setFolhaLoja(false)} /> : null}
    </>
  );
}
