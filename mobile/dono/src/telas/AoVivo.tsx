import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { hm, hora, moeda, MODO, num, streamAoVivo, textoAlerta, useCaixas, useCupomVivo, useFiltro, useVivo } from '../lib/pdv';
import { Cabecalho, Carregando, Erro, Icone, Vazio } from '../ui/pecas';
import { EscolherLoja, Tela } from './Comum';

const ESTADO: Record<string, [string, string]> = {
  em_venda: ['vendendo', 'verde'], livre: ['livre', 'cinza'], parado: ['parado', 'ambar'], sem_coletor: ['sem coletor', 'verm'],
};

export function AoVivo() {
  const [qs] = useSearchParams();
  const { loja: lojaFiltro } = useFiltro();
  const loja = qs.get('loja') || lojaFiltro;
  const vivo = useVivo(loja);
  const [folha, setFolha] = useState(false);
  const r = vivo.data;
  return (
    <>
      <section className="topo-azul baixo">
        <div className="linha-entre">
          <div className="col"><span className="ao-vivo"><i />Ao vivo</span><h1>{r?.loja?.nome || 'Caixas'}</h1></div>
          {(r?.lojas?.length || 0) > 1 ? <button type="button" className="bt-vidro" onClick={() => setFolha(true)}>{Icone.loja}Trocar loja{Icone.baixo}</button> : null}
        </div>
        {r?.loja ? <span className="claro">{moeda(r.loja.vendido_centavos)} hoje · {num(r.loja.cupons)} cupons · {r.loja.coletando} de {r.loja.n_caixas} caixas coletando</span> : null}
      </section>
      <div className="pagina">
        {vivo.isLoading ? <Carregando /> : vivo.error ? <Erro erro={vivo.error} aoTentar={() => vivo.refetch()} /> : !r?.caixas.length ? <Vazio texto="Nenhum caixa nesta loja." /> : (
          <>
            <div className="grade2">
              {r.caixas.map((c) => {
                const [txt, cor] = ESTADO[c.estado] || ['–', 'cinza'];
                return (
                  <Link key={c.id} to={`/vivo/${encodeURIComponent(c.id)}`} className={`cartao caixa borda-${cor}`}>
                    <span className="linha-entre"><b>{c.nome}</b><span className={`selo ${cor}`}>{c.estado === 'parado' && c.parado_min ? `parado ${c.parado_min} min` : txt}</span></span>
                    <small className="sub um">{c.cupom?.operador || c.operador || '–'}</small>
                    {c.cupom?.aberto ? <span className="sub">cupom {c.cupom.cupom} · {c.cupom.itens} itens · <b>{moeda(c.cupom.total_centavos)}</b></span>
                      : <span className="sub">{num(c.cupons)} cupons · {moeda(c.vendido_centavos)}</span>}
                    <span className="link-azul">{Icone.video} ver ao vivo</span>
                  </Link>
                );
              })}
            </div>
            {r.alertas?.length ? (
              <section className="cartao lista">
                <span className="rotulo">Acontecendo agora</span>
                {r.alertas.map((a) => (
                  <Link key={`${a.caixa_id}${a.ts}`} className="linha" to={a.cupom ? `/cupom/${encodeURIComponent(a.caixa_id)}/${a.ts.slice(0, 10)}/${encodeURIComponent(a.cupom)}?ts=${encodeURIComponent(a.ts)}` : `/momento/${encodeURIComponent(a.caixa_id)}?ts=${encodeURIComponent(a.ts)}&rot=${encodeURIComponent(textoAlerta(a))}`}>
                    <span className="hora">{hm(a.ts)}</span>
                    <span className="col cresce"><b>{a.caixa}</b><small className="sub um">{textoAlerta(a)}</small></span>
                    <span className="play-azul">{Icone.playCirc}</span>
                  </Link>
                ))}
              </section>
            ) : null}
          </>
        )}
      </div>
      {folha ? <EscolherLoja aoFechar={() => setFolha(false)} /> : null}
    </>
  );
}

/** Um caixa: video ao vivo e o cupom que esta passando. */
export function CaixaVivo() {
  const { caixa = '' } = useParams();
  const caixas = useCaixas();
  const cx = caixas.data?.find((c) => c.id === caixa);
  const cv = useCupomVivo(caixa);
  const k = cv.data?.cupom;
  const temVideo = !!(cx?.gravador_host && cx?.gravador_canal);
  return (
    <>
      <Cabecalho titulo={cx?.nome || 'Caixa'} sub="ao vivo" />
      <div className="video-fixo">
        {temVideo ? <Tela chave={caixa} vivo registrar={() => streamAoVivo(cx!)} rotulo="● AO VIVO" />
          : <div className="tela-video"><span className="tela-aviso">{caixas.isLoading ? 'Carregando…' : 'Este caixa ainda não tem câmera configurada.'}</span></div>}
      </div>
      <div className="pagina">
        {cv.isLoading ? <Carregando /> : !k ? <Vazio texto="Nenhum cupom ainda hoje." /> : (
          <section className="cartao lista">
            <span className="linha-entre"><b className="t15">{k.situacao === 'aberto' ? 'Cupom passando' : 'Último cupom'} {k.cupom}</b>
              <span className={`selo ${k.situacao}`}>{k.situacao === 'aberto' ? 'em andamento' : k.situacao}</span></span>
            <span className="sub">{k.operador} · aberto {hora(k.aberto_em)}</span>
            {(cv.data?.itens || []).slice(0, 12).map((i) => (
              <div key={`${i.seq}${i.ts}`} className="linha-item">
                <span className="hora">{hora(i.ts)}</span>
                <span className="cresce um">{i.descricao || i.codigo}<small className={`modo ${i.modo}`}>{MODO[i.modo] || i.modo}</small></span>
                <b>{moeda(i.valor_centavos)}</b>
              </div>
            ))}
            <span className="linha-entre"><span className="sub">{num(k.itens)} itens</span><strong className="t20 azul">{moeda(k.total_centavos)}</strong></span>
          </section>
        )}
      </div>
    </>
  );
}
