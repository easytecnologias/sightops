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
};

const PADRAO: Record<Situacao | 'todos', string> = { todos: 'Todos', fora: 'Fora do ar', atencao: 'Atenção', ok: 'No ar', livre: 'Livres' };

function contar<T>(itens: T[], chave: (x: T) => string) {
  const m = new Map<string, number>();
  for (const x of itens) { const k = chave(x) || '—'; m.set(k, (m.get(k) ?? 0) + 1); }
  return [...m.entries()].sort((a, b) => ordemNatural(a[0], b[0]));
}

export function useFiltro<T>(itens: T[], cfg: Config<T>): { lista: T[]; barra: ReactNode; ativo: boolean } {
  const [busca, setBusca] = useState(cfg.buscaInicial ?? '');
  const [local, setLocal] = useState('');
  const [extra, setExtra] = useState('');
  const [sit, setSit] = useState<Situacao | 'todos'>('todos');
  const nomes = { ...PADRAO, ...cfg.nomes };
  const t = busca.trim().toLowerCase();

  const locais = useMemo(() => (cfg.local ? contar(itens, cfg.local) : []), [itens]); // eslint-disable-line react-hooks/exhaustive-deps
  const doLocal = useMemo(() => (local && cfg.local ? itens.filter((x) => (cfg.local!(x) || '—') === local) : itens), [itens, local]); // eslint-disable-line react-hooks/exhaustive-deps
  const extras = useMemo(() => (cfg.extra ? contar(doLocal, cfg.extra.de) : []), [doLocal]); // eslint-disable-line react-hooks/exhaustive-deps
  const base = useMemo(() => doLocal.filter((x) => (!extra || !cfg.extra || (cfg.extra.de(x) || '—') === extra)
    && (!t || cfg.texto(x).some((v) => String(v ?? '').toLowerCase().includes(t)))), [doLocal, extra, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const conta = useMemo(() => {
    const c: Record<Situacao, number> = { ok: 0, atencao: 0, fora: 0, livre: 0 };
    if (cfg.situacao) for (const x of base) c[cfg.situacao(x)] += 1;
    return c;
  }, [base]); // eslint-disable-line react-hooks/exhaustive-deps
  const lista = useMemo(() => (sit === 'todos' || !cfg.situacao ? base : base.filter((x) => cfg.situacao!(x) === sit)), [base, sit]); // eslint-disable-line react-hooks/exhaustive-deps

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
            <select aria-label="Local" className="caixa-sel" value={local} onChange={(e) => { setLocal(e.target.value); setExtra(''); }}>
              <option value="">Todos os locais ({itens.length})</option>
              {locais.map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
            </select>
          ) : null}
          {cfg.extra && extras.length > 1 ? (
            <select aria-label={cfg.extra.rotulo} className="caixa-sel" value={extra} onChange={(e) => setExtra(e.target.value)}>
              <option value="">{cfg.extra.todos} ({doLocal.length})</option>
              {extras.map(([l, n]) => <option key={l} value={l}>{l} ({n})</option>)}
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
                {nomes[k]} {k === 'todos' ? base.length : conta[k]}
              </button>
            )) : null}
          {ativo ? <button type="button" className="aba limpar-aba" onClick={limpar}>Limpar</button> : null}
        </div>
      ) : null}
    </div>
  ) : null;

  return { lista, barra, ativo };
}

/** Situacao pelo status do monitoramento: down = fora, unstable = atencao. */
export const situacaoDoStatus = (status?: string, atencao = false): Situacao =>
  status === 'down' ? 'fora' : status === 'unstable' || atencao ? 'atencao' : status === 'up' ? 'ok' : 'atencao';
