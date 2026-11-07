import { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  DIAS, ehAdmin, textoAcao, textoGatilho, useAutomacoes, useEu, useExcluirRegra, useSalvarRegra, useTestarRegra,
  type Acao, type Equipamento, type Gatilho, type Regra,
} from '../lib/automacoes';
import { natural, useCameras } from '../lib/termico';
import { Carregando, Icone } from '../ui/pecas';
import { IcAuto } from './Automacoes';

const NOVA = (cena: boolean): Regra => ({
  nome: '', ativo: true, modo: 'simular', intervalo_s: 120, periodo: {},
  gatilhos: cena ? [{ tipo: 'manual' }] : [], acoes: [],
});

const GATILHOS: [Gatilho['tipo'], string][] = [
  ['pessoa', 'Pessoa detectada'], ['offline', 'Câmera offline'], ['usina_offline', 'Usina sem comunicação'],
  ['horario', 'Horário'], ['sol', 'Pôr ou nascer do sol'], ['manual', 'Toque no app'],
];
const ACOES: [string, string][] = [
  ['speed_preset', 'Apontar a speed'], ['sirene', 'Tocar sirene'], ['refletor', 'Acender refletor'], ['avisar', 'Avisar celulares'],
  ['aguardar', 'Aguardar'], ['vigiar_usina', 'Vigiar ou desligar usina'], ['executar_regra', 'Executar cena'], ['ligar_regra', 'Ligar outra automação'],
];

/** Folha que sobe: fecha so por Cancelar (clicar fora perderia o que foi escolhido). */
function Folha({ titulo, children, aoFechar, aoUsar, podeUsar, rotulo }: {
  titulo: string; children: React.ReactNode; aoFechar: () => void; aoUsar: () => void; podeUsar: boolean; rotulo: string;
}) {
  return (
    <div className="fundo-folha">
      <section className="folha" role="dialog" aria-label={titulo}>
        <span className="alca" />
        <h2>{titulo}</h2>
        <div className="folha-corpo">{children}</div>
        <div className="dois">
          <button type="button" className="btn2" onClick={aoFechar}>Cancelar</button>
          <button type="button" className="btn" disabled={!podeUsar} onClick={aoUsar}>{rotulo}</button>
        </div>
      </section>
    </div>
  );
}

function Campo({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return <label className="campo"><span>{rotulo}</span>{children}</label>;
}

function FolhaGatilho({ inicial, sites, aoUsar, aoFechar }: { inicial?: Gatilho; sites: string[]; aoUsar: (g: Gatilho) => void; aoFechar: () => void }) {
  const cams = useCameras();
  const lista = [...(cams.data?.cameras || [])].sort((a, b) => natural(`${a.site} ${a.nome}`, `${b.site} ${b.nome}`));
  const [g, setG] = useState<Gatilho>(inicial || { tipo: 'pessoa', camera_id: '' });
  const escolher = (tipo: Gatilho['tipo']) => setG(
    tipo === 'pessoa' || tipo === 'offline' ? { tipo, camera_id: '' }
      : tipo === 'usina_offline' ? { tipo, site: sites[0] || '' }
        : tipo === 'horario' ? { tipo, hora: '18:00', dias: [0, 1, 2, 3, 4, 5, 6] }
          : tipo === 'sol' ? { tipo, evento: 'por', site: sites[0] || '', minutos: 0 } : { tipo });
  const pronto = g.tipo === 'usina_offline' || g.tipo === 'sol' ? !!g.site : g.tipo === 'horario' ? /^\d\d:\d\d$/.test(g.hora) && g.dias.length > 0 : true;
  return (
    <Folha titulo="Quando acontecer…" aoFechar={aoFechar} aoUsar={() => aoUsar(g)} podeUsar={pronto} rotulo="Usar este gatilho">
      <div className="grade">
        {GATILHOS.map(([t, nome]) => (
          <button key={t} type="button" className={`op ${g.tipo === t ? 'on' : ''}`} aria-pressed={g.tipo === t} onClick={() => escolher(t)}><IcAuto tipo={t} />{nome}</button>
        ))}
      </div>
      {g.tipo === 'pessoa' || g.tipo === 'offline' ? (
        <Campo rotulo="Em qual câmera?"><select value={g.camera_id} onChange={(e) => setG({ ...g, camera_id: e.target.value })}>
          <option value="">Qualquer câmera térmica</option>
          {lista.map((c) => <option key={c.id} value={c.id}>{c.site} · {c.nome}</option>)}
        </select></Campo>
      ) : null}
      {g.tipo === 'usina_offline' || g.tipo === 'sol' ? (
        <Campo rotulo="Qual usina?"><select value={g.site} onChange={(e) => setG({ ...g, site: e.target.value })}>
          {sites.map((s) => <option key={s}>{s}</option>)}</select></Campo>
      ) : null}
      {g.tipo === 'sol' ? (
        <div className="dois">
          <Campo rotulo="Quando"><select value={g.evento} onChange={(e) => setG({ ...g, evento: e.target.value as 'por' | 'nascer' })}>
            <option value="por">Pôr do sol</option><option value="nascer">Nascer do sol</option></select></Campo>
          <Campo rotulo="Minutos (− antes, + depois)"><input type="number" min={-180} max={180} value={g.minutos} onChange={(e) => setG({ ...g, minutos: Number(e.target.value) })} /></Campo>
        </div>
      ) : null}
      {g.tipo === 'horario' ? (
        <>
          <Campo rotulo="Hora"><input type="time" value={g.hora} onChange={(e) => setG({ ...g, hora: e.target.value })} /></Campo>
          <div className="dias" role="group" aria-label="Dias da semana">
            {DIAS.map((d, i) => {
              const on = g.dias.includes(i);
              return <button key={d} type="button" aria-pressed={on} className={on ? 'on' : ''}
                onClick={() => setG({ ...g, dias: on ? g.dias.filter((x) => x !== i) : [...g.dias, i].sort() })}>{d}</button>;
            })}
          </div>
        </>
      ) : null}
    </Folha>
  );
}

function FolhaAcao({ inicial, equip, sites, regras, aoUsar, aoFechar }: {
  inicial?: Acao; equip: Equipamento[]; sites: string[]; regras: Regra[]; aoUsar: (a: Acao) => void; aoFechar: () => void;
}) {
  const tipoInicial = !inicial ? 'speed_preset' : inicial.tipo === 'saida' ? ((inicial.segundos || 0) >= 60 ? 'refletor' : 'sirene') : inicial.tipo;
  const [t, setT] = useState(tipoInicial);
  const [a, setA] = useState<Acao>(inicial || { tipo: 'speed_preset', preset: 1, voltar_s: 60 });
  const speeds = equip.filter((e) => e.speed);
  const alvos = t === 'speed_preset' ? speeds : equip;
  const escolher = (novo: string) => {
    setT(novo);
    const base: Record<string, Acao> = {
      speed_preset: { tipo: 'speed_preset', preset: 1, voltar_s: 60 }, sirene: { tipo: 'saida', saida: 1, segundos: 30 },
      refletor: { tipo: 'saida', saida: 1, segundos: 120 }, avisar: { tipo: 'avisar', texto: '', site: '' }, aguardar: { tipo: 'aguardar', segundos: 5 },
      vigiar_usina: { tipo: 'vigiar_usina', site: sites[0] || '', ligar: true }, executar_regra: { tipo: 'executar_regra', regra_id: '' },
      ligar_regra: { tipo: 'ligar_regra', regra_id: '', ligar: true },
    };
    setA(base[novo]);
  };
  const precisaEquip = a.tipo === 'speed_preset' || a.tipo === 'saida';
  const pronto = precisaEquip ? !!a.ip : a.tipo === 'avisar' ? !!a.texto?.trim() : a.tipo.endsWith('_regra') ? !!a.regra_id : true;
  const num = (k: keyof Acao, rot: string, min: number, max: number) => (
    <Campo rotulo={rot}><input type="number" min={min} max={max} value={Number(a[k] ?? 0)} onChange={(e) => setA({ ...a, [k]: Number(e.target.value) })} /></Campo>
  );
  return (
    <Folha titulo="Então fazer…" aoFechar={aoFechar} aoUsar={() => aoUsar(a)} podeUsar={pronto} rotulo={inicial ? 'Usar' : 'Adicionar ação'}>
      <div className="grade">
        {ACOES.map(([k, nome]) => (
          <button key={k} type="button" className={`op ${t === k ? 'on' : ''}`} aria-pressed={t === k} onClick={() => escolher(k)}>
            <IcAuto tipo={k === 'sirene' ? 'saida' : k} />{nome}</button>
        ))}
      </div>
      {precisaEquip ? (
        <Campo rotulo={a.tipo === 'speed_preset' ? 'Qual speed?' : 'Equipamento com a saída de alarme'}>
          <select value={`${a.ip || ''}|${a.connector_id || ''}`} onChange={(e) => {
            const [ip, cid] = e.target.value.split('|');
            const eq = equip.find((x) => x.ip === ip && x.connector_id === cid);
            setA({ ...a, ip, connector_id: cid, nome: eq?.nome, site: eq?.site });
          }}>
            <option value="|">Escolha…</option>
            {alvos.map((e) => <option key={`${e.ip}|${e.connector_id}`} value={`${e.ip}|${e.connector_id}`}>{e.site} · {e.nome}</option>)}
          </select></Campo>
      ) : null}
      {a.tipo === 'speed_preset' ? <div className="dois">{num('preset', 'Preset', 1, 300)}{num('voltar_s', 'Voltar depois de (s)', 0, 3600)}</div> : null}
      {a.tipo === 'saida' ? <div className="dois">{num('saida', 'Saída', 1, 16)}{num('segundos', 'Ligada por (s)', 1, 600)}</div> : null}
      {a.tipo === 'aguardar' ? num('segundos', 'Segundos', 1, 600) : null}
      {a.tipo === 'avisar' ? (
        <>
          <Campo rotulo="Mensagem"><input maxLength={160} value={a.texto || ''} onChange={(e) => setA({ ...a, texto: e.target.value })} placeholder="Ex.: Refletores acesos no Rodoanel" /></Campo>
          <Campo rotulo="Quem recebe"><select value={a.site || ''} onChange={(e) => setA({ ...a, site: e.target.value })}>
            <option value="">Todos com acesso ao módulo</option>{sites.map((s) => <option key={s} value={s}>Quem vê {s}</option>)}</select></Campo>
        </>
      ) : null}
      {a.tipo === 'vigiar_usina' ? (
        <div className="dois">
          <Campo rotulo="Usina"><select value={a.site} onChange={(e) => setA({ ...a, site: e.target.value })}>{sites.map((s) => <option key={s}>{s}</option>)}</select></Campo>
          <Campo rotulo="Fazer"><select value={a.ligar ? '1' : '0'} onChange={(e) => setA({ ...a, ligar: e.target.value === '1' })}>
            <option value="1">Vigiar</option><option value="0">Desligar</option></select></Campo>
        </div>
      ) : null}
      {a.tipo === 'executar_regra' || a.tipo === 'ligar_regra' ? (
        <Campo rotulo={a.tipo === 'executar_regra' ? 'Qual cena?' : 'Qual automação?'}>
          <select value={a.regra_id} onChange={(e) => setA({ ...a, regra_id: e.target.value })}>
            <option value="">Escolha…</option>
            {regras.filter((r) => (a.tipo === 'executar_regra' ? r.cena : !r.cena)).map((r) => <option key={r.id} value={r.id}>{r.nome}</option>)}
          </select></Campo>
      ) : null}
      {a.tipo === 'ligar_regra' ? (
        <Campo rotulo="Fazer"><select value={a.ligar ? '1' : '0'} onChange={(e) => setA({ ...a, ligar: e.target.value === '1' })}>
          <option value="1">Ligar</option><option value="0">Desligar</option></select></Campo>
      ) : null}
    </Folha>
  );
}

/** Editor "Se... entao...": gatilhos, acoes em ordem, periodo e modo. */
export function AutoEditar() {
  const { id } = useParams();
  const [busca] = useSearchParams();
  const nav = useNavigate();
  const lista = useAutomacoes();
  const cams = useCameras();
  const eu = useEu();
  const salvar = useSalvarRegra();
  const testar = useTestarRegra();
  const excluir = useExcluirRegra();
  const [r, setR] = useState<Regra | null>(null);
  const [folha, setFolha] = useState<{ tipo: 'gatilho' | 'acao'; i: number } | null>(null);
  const [msg, setMsg] = useState('');

  useEffect(() => {
    if (r || !lista.data) return;
    const achada = lista.data.automacoes.find((x) => x.id === id);
    setR(achada ? JSON.parse(JSON.stringify(achada)) as Regra : NOVA(busca.get('cena') === '1'));
  }, [lista.data, id, r, busca]);

  if (lista.isLoading || !r) return <Carregando />;
  const admin = ehAdmin(eu.data?.role);
  const nomeCam = (cid: string) => cams.data?.cameras.find((c) => c.id === cid)?.nome || 'câmera removida';
  const nomeRegra = (rid: string) => lista.data?.automacoes.find((x) => x.id === rid)?.nome || 'outra automação';
  const sites = lista.data?.sites || [];
  const outras = (lista.data?.automacoes || []).filter((x) => x.id !== r.id);
  const cena = r.gatilhos.length > 0 && r.gatilhos.every((g) => g.tipo === 'manual');

  function trocar<T>(lista: T[], i: number, item: T) { const c = [...lista]; if (i < 0) c.push(item); else c[i] = item; return c; }
  function guardar() {
    setMsg('');
    salvar.mutate({ ...r!, nome: r!.nome.trim() }, {
      onSuccess: (salva) => { setMsg('Salvo.'); setR(JSON.parse(JSON.stringify(salva)) as Regra); if (!r!.id) nav(`/automacao/${(salva as Regra).id}`, { replace: true }); },
    });
  }

  return (
    <>
      <header className="fx">
        <div className="fx-top">
          <button type="button" className="bt-redondo escuro" aria-label="Voltar" onClick={() => nav(-1)}>{Icone.voltar}</button>
          <span className="fx-nome">{r.id ? r.nome : cena ? 'Nova cena' : 'Nova automação'}</span>
        </div>
      </header>
      <div className="pagina com-acoes">
        <label className="campo"><span>Nome</span><input maxLength={120} value={r.nome} disabled={!admin} placeholder={cena ? 'Ex.: Acender refletores' : 'Ex.: Speed olha a cerca'}
          onChange={(e) => setR({ ...r, nome: e.target.value })} /></label>
        {!cena ? (
          <div className="bloco2">
            <div className="bloco-cab"><b>Se</b><small>qualquer um destes</small></div>
            {r.gatilhos.map((g, i) => {
              const [t1, t2] = textoGatilho(g, nomeCam);
              return (
                <div key={i} className="item2">
                  <IcAuto tipo={g.tipo} />
                  <button type="button" className="t" disabled={!admin} onClick={() => setFolha({ tipo: 'gatilho', i })}><b>{t1}</b><small>{t2}</small></button>
                  {admin ? <button type="button" className="tirar" aria-label={`Tirar ${t1}`} onClick={() => setR({ ...r, gatilhos: r.gatilhos.filter((_, j) => j !== i) })}>{Icone.fechar}</button> : null}
                </div>
              );
            })}
            {admin ? <button type="button" className="mais" onClick={() => setFolha({ tipo: 'gatilho', i: -1 })}>+ Adicionar gatilho</button> : null}
          </div>
        ) : <small className="bloco">Cena: roda quando alguém toca nela.</small>}
        <div className="bloco2">
          <div className="bloco-cab"><b>Então</b><small>na ordem</small></div>
          {r.acoes.map((a, i) => {
            const [t1, t2] = textoAcao(a, nomeRegra);
            return (
              <div key={i} className="item2">
                <IcAuto tipo={a.tipo === 'saida' && (a.segundos || 0) >= 60 ? 'refletor' : a.tipo} />
                <button type="button" className="t" disabled={!admin || a.tipo === 'speed_seguir'} onClick={() => setFolha({ tipo: 'acao', i })}><b>{t1}</b><small>{t2}</small></button>
                {admin ? <button type="button" className="tirar" aria-label={`Tirar ${t1}`} onClick={() => setR({ ...r, acoes: r.acoes.filter((_, j) => j !== i) })}>{Icone.fechar}</button> : null}
              </div>
            );
          })}
          {admin ? <button type="button" className="mais" onClick={() => setFolha({ tipo: 'acao', i: -1 })}>+ Adicionar ação</button> : null}
        </div>
        {!cena ? (
          <div className="bloco2">
            <div className="bloco-cab"><b>Período em que vale</b><small>vazio = sempre</small></div>
            <div className="dois">
              <label className="campo"><span>Das</span><input type="time" disabled={!admin} value={r.periodo.de || ''} onChange={(e) => setR({ ...r, periodo: { ...r.periodo, de: e.target.value } })} /></label>
              <label className="campo"><span>Até</span><input type="time" disabled={!admin} value={r.periodo.ate || ''} onChange={(e) => setR({ ...r, periodo: { ...r.periodo, ate: e.target.value } })} /></label>
            </div>
          </div>
        ) : null}
        <div className="bloco2">
          <div className="bloco-cab"><b>Modo</b></div>
          <div className="alternar largo" role="group" aria-label="Modo">
            <button type="button" disabled={!admin} className={r.modo === 'simular' ? 'on' : ''} onClick={() => setR({ ...r, modo: 'simular' })}>Simular</button>
            <button type="button" disabled={!admin} className={r.modo === 'valer' ? 'on' : ''} onClick={() => setR({ ...r, modo: 'valer' })}>Valendo</button>
          </div>
          <small className="bloco">{r.modo === 'valer' ? 'Valendo: aciona os equipamentos de verdade.' : 'Simular: registra o que faria, sem acionar nada.'}</small>
        </div>
        {r.id && admin ? <button type="button" className="btn2 aviso" disabled={excluir.isPending}
          onClick={() => { if (window.confirm(`Excluir ${r.nome}?`)) excluir.mutate(r.id!, { onSuccess: () => nav('/automacoes', { replace: true }) }); }}>Excluir</button> : null}
        {msg ? <p className="msg-ok">{msg}</p> : null}
        {salvar.error || testar.error || excluir.error ? <p className="msg-erro">{((salvar.error || testar.error || excluir.error) as Error).message}</p> : null}
      </div>
      {admin ? (
        <div className="acoes">
          <button type="button" className="btn2" disabled={!r.id || testar.isPending} onClick={() => testar.mutate(r.id!, { onSuccess: () => setMsg(r.modo === 'valer' ? 'Executando de verdade.' : 'Simulado: veja o histórico na web.') })}>Testar agora</button>
          <button type="button" className="btn destaque-bt" disabled={salvar.isPending || !r.nome.trim() || !r.acoes.length || (!cena && !r.gatilhos.length)} onClick={guardar}>{salvar.isPending ? 'Salvando…' : 'Salvar'}</button>
        </div>
      ) : null}
      {folha?.tipo === 'gatilho' ? (
        <FolhaGatilho inicial={folha.i >= 0 ? r.gatilhos[folha.i] : undefined} sites={sites} aoFechar={() => setFolha(null)}
          aoUsar={(g) => { setR({ ...r, gatilhos: trocar(r.gatilhos, folha.i, g) }); setFolha(null); }} />
      ) : null}
      {folha?.tipo === 'acao' ? (
        <FolhaAcao inicial={folha.i >= 0 ? r.acoes[folha.i] : undefined} equip={lista.data?.equipamentos || []} sites={sites} regras={outras}
          aoFechar={() => setFolha(null)} aoUsar={(a) => { setR({ ...r, acoes: trocar(r.acoes, folha.i, a) }); setFolha(null); }} />
      ) : null}
    </>
  );
}
