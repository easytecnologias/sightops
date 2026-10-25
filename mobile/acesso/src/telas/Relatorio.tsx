import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { obter } from '../lib/api';
import { useLocal } from '../lib/local';
import { useCatalogo } from '../lib/dados';
import { compartilharPdf } from '../lib/pdf';
import { Carregando, Icone, Vazio, hora, useToast } from '../ui/pecas';

/* Relatorios do local, os mesmos do painel web (access_control_relatorios):
   Frequencia/Presenca detalhada aqui; os outros com o resumo e o PDF completo. */

type PessoaFreq = { id: string; nome: string; grupo: string; presencas: number; faltas: number; dias_falta: string[]; pct: number | null };
type GrupoFreq = { grupo: string; pessoas: number; presencas: number; faltas: number; pct: number | null; vieram: number; criticos: number };
type PessoaDia = { id: string; nome: string; grupo: string; chegou: string; saiu: string; minutos: number | null; dentro: boolean };
type Relatorio = {
  id: string; nome: string; pergunta: string; motor: string; de?: string; ate?: string; dia?: string;
  resumo: Record<string, number | string | null | Record<string, unknown>>;
  grupos?: GrupoFreq[]; pessoas?: (PessoaFreq & PessoaDia)[]; dias_fora?: { dia: string; motivo: string }[];
  faltas_alerta?: number; fora_leitor?: { nome: string; grupo: string }[]; nao_vieram?: { nome: string; grupo: string }[];
  portas?: { porta: string; passagens: number }[];
};

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const br = (s?: string) => (s ? s.slice(0, 10).split('-').reverse().join('/') : '');
function diasAtras(n: number) { const d = new Date(); d.setDate(d.getDate() - n); return iso(d); }
function inicioMes() { const d = new Date(); d.setDate(1); return iso(d); }

const PERIODOS: [string, string, () => [string, string]][] = [
  ['7', '7 dias', () => [diasAtras(7), diasAtras(1)]],
  ['30', '30 dias', () => [diasAtras(30), diasAtras(1)]],
  ['mes', 'Este mês', () => [inicioMes(), iso(new Date())]],
];
const DIAS: [string, string, () => string][] = [
  ['hoje', 'Hoje', () => iso(new Date())],
  ['ontem', 'Ontem', () => diasAtras(1)],
];

function corPct(p: number | null | undefined) {
  if (p === null || p === undefined) return 'var(--muted)';
  return p >= 90 ? 'var(--primary)' : p >= 75 ? 'var(--amber)' : 'var(--danger)';
}

function Barra({ pct }: { pct: number | null }) {
  return (
    <span className="barra-pct" aria-hidden="true">
      <span style={{ width: `${Math.max(0, Math.min(100, pct ?? 0))}%`, background: corPct(pct) }} />
    </span>
  );
}

export function Relatorios() {
  const local = useLocal();
  const cat = useCatalogo();
  const toast = useToast();
  const [rid, setRid] = useState('');
  const [periodo, setPeriodo] = useState('30');
  const [dia, setDia] = useState('hoje');
  const [grupo, setGrupo] = useState('');
  const [quem, setQuem] = useState('');
  const [baixando, setBaixando] = useState(false);

  const lista = cat.data?.relatorios ?? [];
  const atual = lista.find((r) => r.id === rid) ?? lista[0];
  useEffect(() => { setGrupo(''); }, [atual?.id, local]);

  const motor = atual?.motor ?? '';
  const [de, ate] = (PERIODOS.find((p) => p[0] === periodo) ?? PERIODOS[1])[2]();
  const diaIso = (DIAS.find((d) => d[0] === dia) ?? DIAS[0])[2]();
  const params = new URLSearchParams({ site: local });
  if (motor === 'diario') params.set('dia', diaIso);
  else if (motor !== 'cadastro') { params.set('de', de); params.set('ate', ate); }
  if (motor === 'presenca') { if (grupo) params.set('grupo', grupo); if (quem) params.set('quem', quem); }
  const qs = params.toString();

  const rel = useQuery({
    queryKey: ['relatorio', atual?.id, qs],
    queryFn: () => obter<Relatorio>(`/api/access-control/painel/relatorios/r/${encodeURIComponent(atual!.id)}?${qs}`),
    enabled: !!atual && !!local,
    staleTime: 120_000,
  });

  async function pdf() {
    if (!atual) return;
    setBaixando(true);
    try {
      await compartilharPdf(`/api/access-control/painel/relatorios/r/${encodeURIComponent(atual.id)}/pdf?${qs}`,
        `${atual.nome}-${local}-${motor === 'diario' ? diaIso : ate}`, `${atual.nome} · ${local}`);
    } catch (e) {
      toast(`Não consegui gerar o PDF: ${(e as Error).message}`, true);
    } finally {
      setBaixando(false);
    }
  }

  if (!local) return <Vazio>Escolha um local no topo: cada relatório é de um local.</Vazio>;
  if (cat.isLoading) return <Carregando />;
  if (cat.error) return <Vazio>{(cat.error as Error).message}</Vazio>;
  if (!atual) return <Vazio>Nenhum relatório para este local.</Vazio>;

  const r = rel.data;
  const g = cat.data?.vocab?.grupo || 'Turma';

  return (
    <>
      <div className="linha-titulo">
        <div>
          <h1 className="titulo-tela">Relatório</h1>
          <p className="sub-tela">{atual.pergunta}</p>
        </div>
      </div>

      <div className="chips" role="group" aria-label="Relatório">
        {lista.map((x) => (
          <button key={x.id} type="button" className="chip" aria-pressed={x.id === atual.id} onClick={() => setRid(x.id)}>{x.nome}</button>
        ))}
      </div>

      {motor === 'diario' ? (
        <div className="seg" role="group" aria-label="Dia">
          {DIAS.map(([k, n]) => <button key={k} type="button" aria-pressed={dia === k} onClick={() => setDia(k)}>{n}</button>)}
        </div>
      ) : motor !== 'cadastro' ? (
        <div className="seg" role="group" aria-label="Período">
          {PERIODOS.map(([k, n]) => <button key={k} type="button" aria-pressed={periodo === k} onClick={() => setPeriodo(k)}>{n}</button>)}
        </div>
      ) : null}

      {motor === 'presenca' && (cat.data?.quem?.length ?? 0) > 1 ? (
        <div className="chips" role="group" aria-label="Quem">
          {cat.data!.quem.map((x, i) => (
            <button key={x.id} type="button" className="chip" aria-pressed={quem ? quem === x.id : i === 0} onClick={() => setQuem(x.id)}>{x.nome}</button>
          ))}
        </div>
      ) : null}

      {rel.isLoading ? <Carregando texto="Montando o relatório…" /> : rel.error ? <Vazio>{(rel.error as Error).message}</Vazio> : r ? (
        <>
          {r.de || r.dia ? <span className="periodo">{r.dia ? br(r.dia) : `${br(r.de)} a ${br(r.ate)}`}</span> : null}

          {r.motor === 'presenca' ? (
            <Frequencia r={r} grupo={grupo} rotGrupo={g} aoGrupo={setGrupo} />
          ) : r.motor === 'diario' ? (
            <Diario r={r} />
          ) : (
            <Resumo r={r} />
          )}

          <button type="button" className="btn2" disabled={baixando} onClick={pdf}>
            {Icone.pdf}{baixando ? 'Gerando PDF…' : 'Compartilhar PDF'}
          </button>
        </>
      ) : null}
    </>
  );
}

function Frequencia({ r, grupo, rotGrupo, aoGrupo }: { r: Relatorio; grupo: string; rotGrupo: string; aoGrupo: (g: string) => void }) {
  const s = r.resumo as Record<string, number | null>;
  const alerta = r.faltas_alerta ?? 3;
  return (
    <>
      <div className="blocos">
        <div className="bloco"><span className="rot">Frequência</span><span className="num" style={{ color: corPct(s.pct) }}>{s.pct ?? '—'}{s.pct !== null ? '%' : ''}</span></div>
        <div className="bloco"><span className="rot">Dias contados</span><span className="num">{s.dias ?? 0}</span></div>
        <div className="bloco"><span className="rot">{alerta}+ faltas</span><span className={`num${s.criticos ? ' ambar' : ''}`}>{s.criticos ?? 0}</span></div>
      </div>

      {!s.dias ? <div className="aviso neutro">{Icone.aviso}<span>Nenhum dia contado no período (fim de semana, feriado ou leitor fora do ar).</span></div> : null}

      {grupo ? (
        <>
          <button type="button" className="btn2" onClick={() => aoGrupo('')}>{Icone.volta}Todas as {rotGrupo.toLowerCase()}s</button>
          <section className="cartao">
            <h2>{grupo}<span className="selo cinza">{(r.pessoas ?? []).length} pessoas</span></h2>
            {(r.pessoas ?? []).map((p) => (
              <div key={p.id} className="item">
                <span className="corpo">
                  <span className="t">{p.nome}</span>
                  <span className="s">{p.presencas} presenças · {p.faltas} faltas{p.dias_falta.length ? ` · ${p.dias_falta.slice(-3).map(br).map((d) => d.slice(0, 5)).join(', ')}` : ''}</span>
                </span>
                <span className="pct" style={{ color: corPct(p.pct) }}>{p.pct ?? '—'}{p.pct !== null ? '%' : ''}</span>
              </div>
            ))}
          </section>
        </>
      ) : (
        <>
          <section className="cartao">
            <h2>Por {rotGrupo.toLowerCase()}</h2>
            {!(r.grupos ?? []).length ? <Vazio>Ninguém no período.</Vazio> : (r.grupos ?? []).map((x) => (
              <button key={x.grupo} type="button" className="item item-pct" onClick={() => aoGrupo(x.grupo)}>
                <span className="corpo">
                  <span className="t">{x.grupo}</span>
                  <span className="s">{x.pessoas} pessoas · {x.faltas} faltas{x.criticos ? ` · ${x.criticos} com ${alerta}+` : ''}</span>
                  <Barra pct={x.pct} />
                </span>
                <span className="pct" style={{ color: corPct(x.pct) }}>{x.pct ?? '—'}{x.pct !== null ? '%' : ''}</span>
                <span className="seta">{Icone.seta}</span>
              </button>
            ))}
          </section>
          {(r.pessoas ?? []).some((p) => p.faltas >= alerta) ? (
            <section className="cartao">
              <h2>Mais faltas</h2>
              {(r.pessoas ?? []).filter((p) => p.faltas >= alerta).slice(0, 15).map((p) => (
                <div key={p.id} className="item">
                  <span className="corpo"><span className="t">{p.nome}</span><span className="s">{p.grupo} · {p.presencas} presenças</span></span>
                  <span className="selo vermelho">{p.faltas} faltas</span>
                </div>
              ))}
            </section>
          ) : null}
        </>
      )}
      {(r.fora_leitor ?? []).length ? (
        <div className="aviso ambar">{Icone.aviso}<span>{r.fora_leitor!.length} fora dos leitores não entram na conta (não tinham como passar).</span></div>
      ) : null}
    </>
  );
}

function Diario({ r }: { r: Relatorio }) {
  const s = r.resumo as Record<string, number | null>;
  const pessoas = r.pessoas ?? [];
  const tempo = (m: number | null) => (m === null || m === undefined ? '' : `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`);
  return (
    <>
      <div className="blocos">
        <div className="bloco"><span className="rot">Pessoas</span><span className="num">{s.pessoas ?? 0}</span></div>
        <div className="bloco"><span className="rot">Passagens</span><span className="num">{s.passagens ?? 0}</span></div>
        <div className="bloco"><span className="rot">Não vieram</span><span className={`num${s.nao_vieram ? ' ambar' : ''}`}>{s.nao_vieram ?? 0}</span></div>
      </div>
      <section className="cartao">
        <h2>Quem passou</h2>
        {!pessoas.length ? <Vazio>Ninguém passou neste dia.</Vazio> : pessoas.slice(0, 150).map((p) => (
          <div key={p.id || p.nome} className="item">
            <span className="corpo">
              <span className="t">{p.nome}</span>
              <span className="s">{[p.grupo, p.chegou ? `chegou ${hora(p.chegou)}` : '', p.saiu ? `saiu ${hora(p.saiu)}` : '', tempo(p.minutos)].filter(Boolean).join(' · ')}</span>
            </span>
            {p.dentro ? <span className="selo verde">dentro</span> : null}
          </div>
        ))}
        {pessoas.length > 150 ? <Vazio>Mostrando 150 de {pessoas.length}. O PDF tem todos.</Vazio> : null}
      </section>
    </>
  );
}

const NOMES: Record<string, string> = {
  passagens: 'Passagens', dias_com_movimento: 'Dias com movimento', media_dia: 'Média por dia', pico: 'Pico de gente dentro',
  enviados: 'Avisos enviados', lidos: 'Lidos', entregues: 'Entregues', falhas: 'Falharam', pessoas_avisadas: 'Pessoas avisadas',
  sem_numero: 'Sem número', pessoas: 'Pessoas', grupos: 'Grupos', sem_foto: 'Sem foto', fora_leitor: 'Fora dos leitores',
  parados: 'Sem passar há 30 dias',
};

function Resumo({ r }: { r: Relatorio }) {
  const itens = Object.entries(r.resumo).filter(([k, v]) => NOMES[k] && (typeof v === 'number'));
  return (
    <>
      <section className="cartao">
        <h2>Resumo</h2>
        {itens.map(([k, v]) => (
          <div key={k} className="item"><span className="corpo"><span className="t">{NOMES[k]}</span></span><span className="pct">{(v as number).toLocaleString('pt-BR')}</span></div>
        ))}
      </section>
      {(r.portas ?? []).length ? (
        <section className="cartao">
          <h2>Portas mais usadas</h2>
          {r.portas!.map((p) => (
            <div key={p.porta} className="item"><span className="corpo"><span className="t">{p.porta}</span></span><span className="pct">{p.passagens.toLocaleString('pt-BR')}</span></div>
          ))}
        </section>
      ) : null}
      <div className="aviso neutro">{Icone.aviso}<span>O PDF traz o relatório completo, com gráficos e a lista de cada dia.</span></div>
    </>
  );
}
