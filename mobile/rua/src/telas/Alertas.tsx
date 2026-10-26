import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { detalhe, mesmoSite, useIncidentes, type Entidade } from '../lib/dados';
import { TIPO_NOME, horaCurta, nomeEntidade, quando, sinalBaixo, useSiteMonitor, type DetalheCamera } from '../lib/monitor';
import { ordenar } from '../lib/ordem';
import { useFiltro } from '../ui/Filtros';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio } from '../ui/pecas';
import { subEntidade, useAbrirEntidade } from './Inicio';

const maiuscula = (x: string) => x.charAt(0).toUpperCase() + x.slice(1);
const tipoDe = (t: string) => maiuscula(TIPO_NOME[t] ?? t);
const localDe = (e?: Entidade) => String(e?.site ?? '').trim().toUpperCase() || 'SEM LOCAL';

const STATUS_PANICO: Record<string, string> = {
  new: 'novo', acknowledged: 'visto', dispatched: 'equipe a caminho', arrived: 'equipe no local', closed: 'encerrado',
};

/* 17 · Alertas: panico do site + equipamento. O campo de coacao nunca chega aqui (lib/dados). */
export function Alertas() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const [aba, setAba] = useState<'abertos' | 'historico'>('abertos');
  const live = useIncidentes('live');
  const hist = useIncidentes('history', aba === 'historico');
  const abrir = useAbrirEntidade();
  const ir = useNavigate();

  const panicos = (aba === 'abertos' ? live.data : hist.data) ?? [];
  const doSite = panicos.filter((p) => !site || !p.site || mesmoSite(p.site, site));
  const abertos = doSite.filter((p) => p.status !== 'closed');
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);

  // Filtros: cada aba tem a sua barra e conta so o que ela mostra; cada numero
  // considera os outros filtros ligados (ver ui/Filtros).
  const [ordem, setOrdem] = useState<'recente' | 'nome'>('recente');
  const porChave = useMemo(() => new Map([...m.conectores, ...m.olts, ...m.nvrs, ...m.switches, ...m.cameras, ...m.onus, ...m.acessos]
    .map((e) => [e.entity_key, e] as const)), [m]);
  const fAbertos = useFiltro(m.atencao, {
    texto: (e) => [nomeEntidade(e), detalhe<DetalheCamera>(e).ip], dica: 'Nome ou IP', unidade: 'alertas de equipamento',
    local: (e) => localDe(e), extra: { rotulo: 'Tipo', todos: 'Todos os tipos', de: (e) => tipoDe(e.entity_type) },
    situacao: (e) => (e.status === 'down' ? 'fora' : 'atencao'), nomes: { fora: 'Fora do ar', atencao: 'Instável ou sinal baixo' },
  });
  const comEnt = useMemo(() => m.mudancas.map((ev) => ({ ev, e: porChave.get(ev.entity_key) })), [m.mudancas, porChave]);
  const fHist = useFiltro(comEnt, {
    texto: ({ ev, e }) => [ev.message, e ? detalhe<DetalheCamera>(e).ip : ''], dica: 'Nome ou IP', unidade: 'mudanças',
    local: ({ e }) => localDe(e), extra: { rotulo: 'Tipo', todos: 'Todos os tipos', de: ({ ev }) => tipoDe(ev.entity_type) },
    situacao: ({ ev }) => (ev.to_status === 'up' ? 'ok' : 'fora'), nomes: { ok: 'Voltou', fora: 'Caiu' },
  });
  const atencao = fAbertos.lista;
  const equipamentos = ordem === 'nome' ? ordenar(atencao, (e) => nomeEntidade(e)) : atencao;
  const mudancas = fHist.lista.map((x) => x.ev);
  // "Resolvidos hoje" obedece a barra de Abertos (mesmo local, tipo e busca).
  const fa = fAbertos.estado;
  const voltaram = comEnt.filter(({ ev, e }) => ev.to_status === 'up' && (quando(ev.created_at) ?? 0) >= hoje.getTime()
    && (!fa.local || localDe(e) === fa.local) && (!fa.extra || tipoDe(ev.entity_type) === fa.extra)
    && (!fa.busca || [ev.message, e ? detalhe<DetalheCamera>(e).ip : ''].some((v) => String(v ?? '').toLowerCase().includes(fa.busca))))
    .map((x) => x.ev);

  if (m.carregando) return <Carregando />;

  return (
    <>
      <h1 className="titulo-tela">Alertas</h1>
      <div className="abas" role="group" aria-label="Mostrar">
        <button type="button" className="aba" aria-pressed={aba === 'abertos'} onClick={() => setAba('abertos')}>
          Abertos · {m.atencao.length + abertos.length}
        </button>
        <button type="button" className="aba" aria-pressed={aba === 'historico'} onClick={() => setAba('historico')}>Histórico</button>
      </div>

      {aba === 'abertos' ? fAbertos.barra : fHist.barra}

      {aba === 'abertos' ? (
        <>
          {abertos.length ? (
            <Cartao>
              <h2>Pânico</h2>
              {abertos.map((p) => (
                <Item key={p.id} ponto="vermelho" icone={Icone.alerta}
                      titulo={p.member?.full_name || 'Alerta de pânico'}
                      sub={[p.member?.unit_name, `aberto ${horaCurta(p.opened_at)} · ${desde(p.opened_at)}`].filter(Boolean).join(' · ')}
                      direita={<span className="selo ambar">{STATUS_PANICO[p.status] ?? p.status}</span>} />
              ))}
              <p className="sub-h2" style={{ paddingTop: 8 }}>O atendimento é feito no SightOps pelo navegador.</p>
            </Cartao>
          ) : (
            <div className="aviso neutro"><span className="selo verde">pânico</span><span>Nenhum alerta de pânico aberto neste site.</span></div>
          )}

          <div className="linha-secao">
            <span className="rot-secao">Equipamento · {fAbertos.ativo ? `${atencao.length} de ${m.atencao.length}` : m.atencao.length}</span>
            <div className="abas abas-mini" role="group" aria-label="Ordenar">
              <button type="button" className="aba" aria-pressed={ordem === 'recente'} onClick={() => setOrdem('recente')}>Mais recentes</button>
              <button type="button" className="aba" aria-pressed={ordem === 'nome'} onClick={() => setOrdem('nome')}>Nome A–Z</button>
            </div>
          </div>
          <Cartao>
            {!m.atencao.length ? <Vazio>Nenhum equipamento fora do ar.</Vazio> : !equipamentos.length ? <Vazio>Nada com esse filtro.</Vazio> : equipamentos.map((e) => (
              <Item key={e.entity_key} ponto={e.status === 'up' ? 'ambar' : 'vermelho'}
                    titulo={e.entity_type === 'onu' ? (sinalBaixo(e) ? `${nomeEntidade(e)} com sinal baixo` : nomeEntidade(e)) : `${nomeEntidade(e)} ${e.status === 'unstable' ? 'instável' : e.entity_type === 'camera' ? 'sem vídeo' : 'fora do ar'}`}
                    sub={e.entity_type === 'onu' ? subEntidade(e) : [detalhe<DetalheCamera>(e).ip, e.last_changed_at ? `desde ${horaCurta(e.last_changed_at)}` : ''].filter(Boolean).join(' · ')}
                    onClick={() => abrir(e)}
                    direita={<span className={`selo ${e.status === 'up' ? 'ambar' : 'vermelho'}`}>{TIPO_NOME[e.entity_type] ?? e.entity_type}</span>} />
            ))}
          </Cartao>

          {voltaram.length ? (
            <>
              <span className="rot-secao">Resolvidos hoje</span>
              <Cartao>
                {voltaram.map((ev, i) => (
                  <Item key={`${ev.entity_key}-${i}`} titulo={ev.message.split(':')[0]}
                        sub={`voltou ${horaCurta(ev.created_at)}`} direita={<span className="selo verde">voltou</span>} />
                ))}
              </Cartao>
            </>
          ) : null}
        </>
      ) : (
        <>
          <Cartao>
            <h2>Mudanças de equipamento</h2>
            {!mudancas.length ? <Vazio>{m.mudancas.length ? 'Nada com esse filtro.' : 'Sem mudanças recentes neste site.'}</Vazio> : mudancas.map((ev, i) => (
              <Item key={`${ev.entity_key}-${i}`} titulo={ev.message.split(':')[0]}
                    sub={`${ev.from_status} → ${ev.to_status} · ${new Date(quando(ev.created_at) ?? 0).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}`}
                    direita={<span className={`selo ${ev.to_status === 'up' ? 'verde' : 'ambar'}`}>{ev.to_status === 'up' ? 'voltou' : 'caiu'}</span>} />
            ))}
          </Cartao>
          <Cartao>
            <h2>Pânico</h2>
            {hist.isPending && !hist.data ? <Carregando /> : !doSite.length ? <Vazio>Nenhum alerta de pânico neste site.</Vazio> : doSite.slice(0, 30).map((p) => (
              <Item key={p.id} ponto={p.status === 'closed' ? 'verde' : 'vermelho'} titulo={p.member?.full_name || 'Alerta de pânico'}
                    sub={new Date(quando(p.opened_at) ?? 0).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                    direita={<span className={`selo ${p.status === 'closed' ? 'verde' : 'ambar'}`}>{STATUS_PANICO[p.status] ?? p.status}</span>} />
            ))}
          </Cartao>
          <button type="button" className="btn2" onClick={() => ir('/')}>{Icone.volta}Voltar ao início</button>
        </>
      )}
    </>
  );
}
