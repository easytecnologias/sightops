import { useEffect, useMemo, useRef, useState } from 'react';
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  diaRotulo, hora, janelaVideo, moeda, MODO, num, SEM_LOJA, streamGravacao, textoEvento, useCaixas, useCupons, useDetalhe, useFiltro,
  type Detalhe,
} from '../lib/pdv';
import { Cabecalho, Carregando, Erro, Icone, Vazio } from '../ui/pecas';
import { LinhaCupom, Tela } from './Comum';

const ms = (ts: string) => new Date(String(ts).replace(' ', 'T')).getTime();
const EVENTOS_LINHA = ['CIT', 'DIT', 'DAS', 'CCV', 'CCG', 'SUP', 'SUPERVISOR', 'GER', 'GAV', 'FIN', 'TRC', 'FECHACUPOM', 'ITEMSEMCAD', 'CLIENTE'];
const COR: Record<string, string> = { CIT: 'l-verm', CCV: 'l-verm', CCG: 'l-verm', DIT: 'l-ambar', DAS: 'l-ambar', ITEMSEMCAD: 'l-ambar', SUP: 'l-ambar', SUPERVISOR: 'l-ambar', GER: 'l-ambar', GAV: 'l-ambar', FIN: 'l-azul', TRC: 'l-azul', FECHACUPOM: 'l-azul' };

type Alvo = { ts: string; rot: string; antes: number; n: number };
type LinhaR = { ts: string; tipo: string; txt: string; sub: string; valor: number };

/** O relogio do caixa acompanha o tempo realmente tocado do video. */
function useRelogio() {
  const inicio = useRef<number | null>(null);
  const [tocado, setTocado] = useState(0);
  const ultimo = useRef<number | null>(null);
  const zerar = () => { inicio.current = null; ultimo.current = null; setTocado(0); };
  const preso = useRef<{ v: HTMLVideoElement; fn: () => void } | null>(null);
  const ligar = (v: HTMLVideoElement) => {
    if (preso.current) preso.current.v.removeEventListener('timeupdate', preso.current.fn);
    const fn = () => {
      const t = v.currentTime;
      if (ultimo.current !== null) {
        const d = t - ultimo.current;
        if (d > 0 && d < 2) setTocado((x) => x + d);
      }
      ultimo.current = t;
    };
    v.addEventListener('timeupdate', fn);
    preso.current = { v, fn };
  };
  const agora = inicio.current === null ? null : inicio.current + tocado * 1000;
  return { inicio, agora, zerar, ligar };
}

function CupomVideo({ d, tsFoco, tipoFoco }: { d: Detalhe; tsFoco: string; tipoFoco: string }) {
  const k = d.cupom;
  const caixaId = d.caixa.id;
  const [alvo, setAlvo] = useState<Alvo | null>(null);
  const [inteiro, setInteiro] = useState(false);
  const [encerrado, setEncerrado] = useState('');
  const rel = useRelogio();
  const listaRef = useRef<HTMLDivElement>(null);

  const linha = d.linha_do_tempo || [];
  const foco = tsFoco ? linha.filter((e) => e.ts === tsFoco && e.tipo !== 'VIT')
    : tipoFoco ? linha.filter((e) => e.tipo === tipoFoco || (tipoFoco === 'DIT' && e.tipo === 'DAS')) : linha.filter((e) => ['CIT', 'DIT', 'DAS', 'CCV'].includes(e.tipo));
  const linhas: LinhaR[] = useMemo(() => [
    ...(d.itens || []).map((i) => ({ ts: i.ts, tipo: 'VIT', txt: i.descricao || i.codigo, sub: MODO[i.modo] || i.modo, valor: i.valor_centavos })),
    ...linha.filter((e) => EVENTOS_LINHA.includes(e.tipo)).map((e) => {
      const menos = ['CIT', 'DIT', 'DAS'].includes(e.tipo);
      return { ts: e.ts, tipo: e.tipo, txt: textoEvento(e), sub: '', valor: menos ? -Math.abs(e.valor_centavos || 0) : 0 };
    }),
  ].sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0)), [d]);  // eslint-disable-line react-hooks/exhaustive-deps
  const fim = linhas.find((l) => l.tipo === 'FECHACUPOM' || l.tipo === 'CCV');

  function ver(ts: string, rot: string, antes = 3, cheio = false) {
    setEncerrado('');
    rel.zerar();
    setInteiro(cheio);
    setAlvo((a) => ({ ts, rot, antes, n: (a?.n || 0) + 1 }));
  }

  // linha atual (verde/azul) e fim do video 5 s depois do fechamento
  const agora = rel.agora;
  let iAtual = -1;
  if (agora !== null) linhas.forEach((l, i) => { if (ms(l.ts) <= agora) iAtual = i; });
  useEffect(() => {
    if (!inteiro || agora === null) return;
    const el = listaRef.current?.querySelector('.atual');
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    if (fim && agora >= ms(fim.ts) + 5000) {
      setAlvo(null);
      setEncerrado(`Cupom ${fim.tipo === 'CCV' ? 'cancelado' : 'fechado'} às ${hora(fim.ts)} · vídeo encerrado`);
    }
  }, [iAtual, inteiro]);  // eslint-disable-line react-hooks/exhaustive-deps

  const passadas = agora === null ? linhas : linhas.slice(0, iAtual + 1);
  const somaPassada = passadas.reduce((t, l) => t + l.valor, 0);
  const fechou = agora === null || passadas.some((l) => l === fim);

  const registrar = alvo ? async () => {
    const j = await janelaVideo(caixaId, alvo.ts, alvo.antes);
    rel.inicio.current = ms(j.momento_caixa) - alvo.antes * 1000;
    return streamGravacao(j);
  } : null;

  const momento = (ts: string, rot: string, valor?: number) => (
    <button type="button" key={`${ts}${rot}`} className={`momento ${alvo?.ts === ts && !inteiro ? 'on' : ''}`} onClick={() => ver(ts, rot)}>
      <span className="hora">{hora(ts)}</span><span className="cresce um">{rot}</span>
      {valor ? <b>{moeda(valor)}</b> : null}<span className="play-azul">{Icone.play}</span>
    </button>
  );

  return (
    <>
      <div className="video-fixo">
        {encerrado ? (
          <div className="tela-video"><span className="tela-aviso">{encerrado}
            <button type="button" className="btn2 claro-bt" onClick={() => ver(k.aberto_em, 'o cupom inteiro', 5, true)}>{Icone.denovo}Ver de novo</button></span></div>
        ) : <Tela chave={alvo ? `${alvo.ts}|${alvo.n}` : ''} registrar={registrar} vivo={false} aoTocar={rel.ligar} />}
        {alvo ? <p className="vendo">Vendo: {alvo.rot} · às {hora(alvo.ts)}{agora !== null ? <span className="sub"> · relógio do caixa {new Date(agora).toTimeString().slice(0, 8)}</span> : null}</p> : null}
      </div>

      {inteiro ? (
        <div className="pagina" ref={listaRef}>
          <button type="button" className="link-azul" onClick={() => { setInteiro(false); setAlvo(null); }}>‹ Voltar ao resumo do cupom</button>
          <div className="cartao lista">
            {linhas.map((l, i) => (
              <button type="button" key={`${l.ts}${i}`} className={`linha-rep ${COR[l.tipo] || ''} ${i === iAtual ? 'atual' : ''} ${agora !== null && i > iAtual ? 'futura' : ''}`}
                onClick={() => ver(l.ts, l.txt, 3, true)}>
                <span className="hora">{hora(l.ts)}</span>
                <span className="cresce um">{l.txt}{l.sub ? <small className="sub"> {l.sub}</small> : null}</span>
                {l.valor ? <b>{l.valor < 0 ? '− ' : ''}{moeda(Math.abs(l.valor))}</b> : null}
              </button>
            ))}
          </div>
          <div className="rodape-rep">
            <span className="sub">{passadas.filter((l) => l.tipo === 'VIT').length} de {linhas.filter((l) => l.tipo === 'VIT').length} itens{fechou ? ' · total do cupom' : ''}</span>
            <strong>{moeda(fechou && k.situacao === 'fechado' ? k.total_centavos : somaPassada)}</strong>
          </div>
        </div>
      ) : (
        <div className="pagina">
          <section className="cartao">
            <span className="linha-entre"><b className="t15">Cupom {k.cupom}</b><span className={`selo ${k.situacao}`}>{k.situacao === 'aberto' ? 'em andamento' : k.situacao}</span></span>
            <span className="sub">{d.caixa.nome} · {k.operador} · {hora(k.aberto_em)}{k.fechado_em ? ` → ${hora(k.fechado_em)}` : ''} · {k.pagamento || 'sem pagamento'}</span>
            <span className="linha-entre"><span className="sub">{num((d.itens || []).length)} itens</span><strong className="t20">{moeda(k.total_centavos)}</strong></span>
          </section>
          {foco.length ? (
            <section className="cartao lista">
              <span className="rotulo ambar">O que conferir no vídeo</span>
              {foco.map((e) => momento(e.ts, textoEvento(e), e.valor_centavos ? Math.abs(e.valor_centavos) : 0))}
            </section>
          ) : null}
          <section className="cartao lista">
            {momento(k.aberto_em, 'Abertura do cupom')}
            {k.fechado_em ? momento(k.fechado_em, k.situacao === 'cancelado' ? 'Cancelamento do cupom' : 'Fechamento e pagamento') : null}
            <button type="button" className="momento destaque" onClick={() => ver(k.aberto_em, 'o cupom inteiro', 5, true)}>
              <span className="hora">{hora(k.aberto_em)}</span><span className="cresce">Ver o cupom inteiro, item a item</span><span className="play-azul">{Icone.play}</span>
            </button>
          </section>
        </div>
      )}
    </>
  );
}

export function CupomTela() {
  const { caixa = '', dia = '', cupom = '' } = useParams();
  const [qs] = useSearchParams();
  const det = useDetalhe(caixa, dia, cupom);
  return (
    <>
      <Cabecalho titulo={`Cupom ${cupom}`} sub={det.data ? `${det.data.caixa.nome} · ${diaRotulo(dia)}` : diaRotulo(dia)} />
      {det.isLoading ? <Carregando /> : det.error ? <div className="pagina"><Erro erro={det.error} aoTentar={() => det.refetch()} /></div>
        : det.data ? <CupomVideo d={det.data} tsFoco={qs.get('ts') || ''} tipoFoco={qs.get('tipo') || ''} /> : null}
    </>
  );
}

/** Evento fora de cupom (sangria, gaveta): so o video daquele segundo. */
export function Momento() {
  const { caixa = '' } = useParams();
  const [qs] = useSearchParams();
  const ts = qs.get('ts') || '';
  const rot = qs.get('rot') || 'Momento';
  const caixas = useCaixas();
  const cx = caixas.data?.find((c) => c.id === caixa);
  const [n, setN] = useState(0);
  return (
    <>
      <Cabecalho titulo={rot} sub={`${cx?.nome || ''} · ${hora(ts)}`} />
      <div className="video-fixo">
        <Tela chave={n ? `${ts}|${n}` : ''} vivo={false}
          registrar={n ? async () => streamGravacao(await janelaVideo(caixa, ts, 5)) : null} />
      </div>
      <div className="pagina">
        <button type="button" className="btn" onClick={() => setN(n + 1)}>{Icone.play} {n ? 'Ver de novo' : 'Ver o vídeo deste momento'}</button>
        <p className="nota">Começa 5 segundos antes do momento, no relógio do caixa.</p>
      </div>
    </>
  );
}

/** Busca pelo numero do cupom no dia e na loja escolhidos. */
export function Busca() {
  const { numero = '' } = useParams();
  const { dia, loja } = useFiltro();
  const caixas = useCaixas();
  const r = useCupons(dia, numero);
  const ir = useNavigate();
  const lojaDe = (id: string) => caixas.data?.find((c) => c.id === id)?.site || SEM_LOJA;
  let lista = (r.data || []).filter((k) => !loja || lojaDe(k.caixa_id) === loja);
  const exatos = lista.filter((k) => k.cupom.replace(/^0+/, '') === numero.replace(/^0+/, ''));
  if (exatos.length) lista = exatos;
  useEffect(() => {
    if (lista.length === 1 && exatos.length === 1) {
      const k = lista[0];
      ir(`/cupom/${encodeURIComponent(k.caixa_id)}/${k.dia}/${encodeURIComponent(k.cupom)}`, { replace: true });
    }
  }, [r.data]);  // eslint-disable-line react-hooks/exhaustive-deps
  if (!numero) return <Navigate to="/" replace />;
  return (
    <>
      <Cabecalho titulo={`Cupom ${numero}`} sub={`${diaRotulo(dia)} · ${loja || 'todas as lojas'}`} />
      <div className="pagina">
        {r.isLoading ? <Carregando texto="Procurando o cupom…" /> : r.error ? <Erro erro={r.error} />
          : lista.length ? <div className="cartao lista">{lista.map((k) => <LinhaCupom key={`${k.caixa_id}|${k.cupom}`} k={k} txt={`${k.itens} itens`} />)}</div>
          : <Vazio texto={`Nenhum cupom ${numero} em ${diaRotulo(dia).toLowerCase()}${loja ? ` na ${loja}` : ''}. Confira o número ou escolha outro dia no Início.`} />}
      </div>
    </>
  );
}
