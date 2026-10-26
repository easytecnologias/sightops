import { useMemo, useState, type ReactNode } from 'react';
import { ordemNatural } from '../lib/ordem';
import { Icone } from './pecas';

/* Barra de filtro igual em toda tela com lista: busca, local (sub-site do
   cadastro), situacao e um seletor extra opcional (OLT, tipo...). Cada opcao
   mostra quantos itens tem; "Limpar filtros" aparece quando algo esta ligado. */

export type Situacao = 'ok' | 'atencao' | 'fora' | 'livre';

type Extra<T> = { rotulo: string; todos: string; de: (x: T) => string };

type Config<T> = {
  /** Textos onde a busca procura (nome, IP, MAC, serial...). */
  texto: (x: T) => unknown[];
  /** Local do item; com um local so, o seletor nem aparece. */
  local?: (x: T) => string;
  /** Situacao do item; sem isto, nao ha abas de situacao. */
  situacao?: (x: T) => Situacao;
  /** Nomes das abas de situacao nesta tela (ex.: atencao = "Sinal baixo"). */
  nomes?: Partial<Record<Situacao | 'todos', string>>;
  extra?: Extra<T>;
  dica?: string;
  /** Busca ja preenchida (ex.: ?q= no endereco). */
  buscaInicial?: string;
  /** Filtros ja ligados ao abrir (vindos do endereco). */
  inicial?: { local?: string; extra?: string; sit?: Situacao };
  /** O que esta sendo contado ("gravadores", "ONUs"): aparece no "Mostrando N de M". */
  unidade?: string;
};

const PADRAO: Record<Situacao | 'todos', string> = { todos: 'Todos', fora: 'Fora do ar', atencao: 'Atenção', ok: 'No ar', livre: 'Livres' };

function contar<T>(itens: T[], chave: (x: T) => string) {
  const m = new Map<string, number>();
  for (const x of itens) { const k = chave(x) || '—'; m.set(k, (m.get(k) ?? 0) + 1); }
  return [...m.entries()].sort((a, b) => ordemNatural(a[0], b[0]));
}

export function useFiltro<T>(itens: T[], cfg: Config<T>): { lista: T[]; barra: ReactNode; ativo: boolean; estado: { busca: string; local: string; extra: string } } {
  const [busca, setBusca] = useState(cfg.buscaInicial ?? '');
  const [local, setLocal] = useState(cfg.inicial?.local ?? '');
  const [extra, setExtra] = useState(cfg.inicial?.extra ?? '');
  const [sit, setSit] = useState<Situacao | 'todos'>(cfg.inicial?.sit ?? 'todos');
  const nomes = { ...PADRAO, ...cfg.nomes };
  const t = busca.trim().toLowerCase();

  // Cada contagem considera TODOS os outros filtros ligados: o numero ao lado
  // de uma opcao e exatamente o que aparece ao toca-la. Antes cada seletor
  // contava sozinho (local ignorava o tipo, o tipo ignorava a busca...) e os
  // numeros nao batiam com a lista.
  const deLocal = (x: T) => (cfg.local ? cfg.local(x) || '—' : '');
  const deExtra = (x: T) => (cfg.extra ? cfg.extra.de(x) || '—' : '');
  const passa = (x: T, sem?: 'local' | 'extra' | 'sit') =>
    (sem === 'local' || !local || deLocal(x) === local)
    && (sem === 'extra' || !extra || deExtra(x) === extra)
    && (sem === 'sit' || sit === 'todos' || !cfg.situacao || cfg.situacao(x) === sit)
    && (!t || cfg.texto(x).some((v) => String(v ?? '').toLowerCase().includes(t)));

  const paraLocal = useMemo(() => itens.filter((x) => passa(x, 'local')), [itens, extra, sit, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const paraExtra = useMemo(() => itens.filter((x) => passa(x, 'extra')), [itens, local, sit, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const paraSit = useMemo(() => itens.filter((x) => passa(x, 'sit')), [itens, local, extra, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const lista = useMemo(() => itens.filter((x) => passa(x)), [itens, local, extra, sit, t]); // eslint-disable-line react-hooks/exhaustive-deps

  // Opcoes: todas as que existem na lista inteira (para o seletor nao sumir),
  // com a contagem do momento -- a escolhida aparece mesmo com 0.
  const opcoes = (todas: [string, number][], agora: [string, number][]) => {
    const n = new Map(agora);
    return todas.map(([k]) => [k, n.get(k) ?? 0] as [string, number]);
  };
  const locais = useMemo(() => (cfg.local ? opcoes(contar(itens, deLocal), contar(paraLocal, deLocal)) : []), [itens, paraLocal]); // eslint-disable-line react-hooks/exhaustive-deps
  const extras = useMemo(() => (cfg.extra ? opcoes(contar(itens, deExtra), contar(paraExtra, deExtra)) : []), [itens, paraExtra]); // eslint-disable-line react-hooks/exhaustive-deps
  const conta = useMemo(() => {
    const c: Record<Situacao, number> = { ok: 0, atencao: 0, fora: 0, livre: 0 };
    if (cfg.situacao) for (const x of paraSit) c[cfg.situacao(x)] += 1;
    return c;
  }, [paraSit]); // eslint-disable-line react-hooks/exhaustive-deps

  const ativo = !!(t || local || extra || sit !== 'todos');
  const limpar = () => { setBusca(''); setLocal(''); setExtra(''); setSit('todos'); };

  const barra = itens.length ? (
    <div className="filtros">
      <div className="busca">
        {Icone.busca}
        <input aria-label="Procurar" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder={cfg.dica ?? 'Procurar'} autoCapitalize="none" spellCheck={false} />
      </div>
      {locais.length > 1 || extras.length > 1 ? (
        <div className="filtros-duplos">
          {locais.length > 1 ? (
            <select aria-label="Local" className="caixa-sel" value={local} onChange={(e) => setLocal(e.target.value)}>
              <option value="">Todos os locais ({paraLocal.length})</option>
              {locais.filter(([l, n]) => n || l === local).map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
            </select>
          ) : null}
          {cfg.extra && extras.length > 1 ? (
            <select aria-label={cfg.extra.rotulo} className="caixa-sel" value={extra} onChange={(e) => setExtra(e.target.value)}>
              <option value="">{cfg.extra.todos} ({paraExtra.length})</option>
              {extras.filter(([l, n]) => n || l === extra).map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
            </select>
          ) : null}
        </div>
      ) : null}
      {cfg.situacao || ativo ? (
        <div className="abas" role="group" aria-label="Situação">
          {cfg.situacao ? (['todos', 'fora', 'atencao', 'ok', 'livre'] as const)
            .filter((k) => k === 'todos' || k === sit || conta[k] > 0)
            .map((k) => (
              <button key={k} type="button" className="aba" aria-pressed={sit === k} onClick={() => setSit(k)}>
                {nomes[k]} {k === 'todos' ? paraSit.length : conta[k]}
              </button>
            )) : null}
          {ativo ? <button type="button" className="aba limpar-aba" onClick={limpar}>Limpar</button> : null}
        </div>
      ) : null}
      {ativo ? <p className="sub-tela" style={{ margin: 0 }}>Mostrando {lista.length} de {itens.length}{cfg.unidade ? ` ${cfg.unidade}` : ''}.</p> : null}
    </div>
  ) : null;

  return { lista, barra, ativo, estado: { busca: t, local, extra } };
}

/** Situacao pelo status do monitoramento: down = fora, unstable = atencao. */
export const situacaoDoStatus = (status?: string, atencao = false): Situacao =>
  status === 'down' ? 'fora' : status === 'unstable' || atencao ? 'atencao' : status === 'up' ? 'ok' : 'atencao';
