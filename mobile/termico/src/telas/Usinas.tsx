import { useMemo } from 'react';
import { natural, num, useAlertas, useArmar, useCameras, type Alerta, type Camera } from '../lib/termico';
import { Carregando, Erro } from '../ui/pecas';

const NOITE_FIM = (6 / 24) * 100;
const NOITE_INI = (18 / 24) * 100;
const pct = (d: Date) => ((d.getHours() + d.getMinutes() / 60) / 24) * 100;

function Dia({ alertas, ligada }: { alertas: Alerta[]; ligada: boolean }) {
  const agora = new Date();
  const hoje = alertas.filter((a) => new Date(a.criado_at).toDateString() === agora.toDateString());
  return (
    <div>
      <div className={`dia ${ligada ? 'on' : ''}`}>
        <span className="noite" style={{ left: 0, width: `${NOITE_FIM}%` }} />
        <span className="noite" style={{ left: `${NOITE_INI}%`, right: 0 }} />
        {hoje.map((a) => <span key={a.id} className="marca" style={{ left: `${pct(new Date(a.criado_at))}%` }} />)}
        <span className="agora" style={{ left: `${pct(agora)}%` }} />
      </div>
      <div className="dia-horas"><span>00h</span><span>06h</span><span>12h</span><span>18h</span><span>24h</span></div>
    </div>
  );
}

function Usina({ nome, cams, alertas }: { nome: string; cams: Camera[]; alertas: Alerta[] }) {
  const armar = useArmar();
  const ligada = cams.some((c) => c.ativo);
  const semLeitura = cams.filter((c) => c.ativo && c.leitura === 'erro').length;
  const hoje = alertas.filter((a) => new Date(a.criado_at).toDateString() === new Date().toDateString()).length;
  const fundos = cams.map((c) => c.fundo_c).filter((v): v is number => v !== null);
  return (
    <section className="cartao usina">
      <div className="linha">
        <div className="cresce"><h2>{nome}</h2>
          <small>{cams.length} câmera{cams.length === 1 ? '' : 's'}{fundos.length ? ` · cena ${num(Math.max(...fundos), 0)} °C` : ''}</small></div>
        <button type="button" role="switch" aria-checked={ligada} aria-label={`Armar ${nome}`} className={`chave ${ligada ? 'on' : ''}`}
          disabled={armar.isPending} onClick={() => armar.mutate({ cameras: cams, ligar: !ligada })}><i /></button>
      </div>
      <div className="tres">
        <div className="m"><span>Situação</span><b>{armar.isPending ? 'Salvando…' : ligada ? 'Vigiando' : 'Desligada'}</b></div>
        <div className="m"><span>Medindo</span><b>{cams.filter((c) => c.ativo && c.leitura === 'ok').length} de {cams.length}</b></div>
        <div className="m"><span>Alarmes hoje</span><b>{hoje}</b></div>
      </div>
      {semLeitura ? <p className="msg-erro">{semLeitura} sem medição: nessas não há alerta de pessoa.</p> : null}
      <Dia alertas={alertas} ligada={ligada} />
      {armar.error ? <p className="msg-erro">{(armar.error as Error).message}</p> : null}
    </section>
  );
}

export function Usinas() {
  const cams = useCameras();
  const al = useAlertas();
  const usinas = useMemo(() => {
    const m = new Map<string, Camera[]>();
    for (const c of cams.data?.cameras || []) m.set(c.site, [...(m.get(c.site) || []), c]);
    return [...m.entries()].sort((a, b) => natural(a[0], b[0]));
  }, [cams.data]);
  return (
    <>
      <header className="fx">
        <div className="fx-top"><span className="fx-nome grande">Usinas</span></div>
        <div className="mets">
          <div><span>Usinas</span><b>{usinas.length}</b></div>
          <div><span>Medindo</span><b>{(cams.data?.cameras || []).filter((c) => c.ativo && c.leitura === 'ok').length} <em>de {(cams.data?.cameras || []).length}</em></b></div>
          <div><span>Sem resposta</span><b>{(al.data?.alertas || []).filter((a) => a.situacao === 'novo').length}</b></div>
        </div>
      </header>
      <div className="pagina">
        {cams.isLoading ? <Carregando /> : cams.error ? <Erro erro={cams.error} /> : null}
        {cams.data && !usinas.length ? <div className="vazio">Nenhuma câmera no Alerta Térmico ainda.</div> : null}
        {usinas.map(([nome, lista]) => <Usina key={nome} nome={nome} cams={lista} alertas={(al.data?.alertas || []).filter((a) => a.site === nome)} />)}
      </div>
    </>
  );
}
