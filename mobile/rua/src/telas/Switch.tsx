import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { chaveDa, detalhe, tituloDa, useCameras, type Camera } from '../lib/dados';
import { nomeEntidade, useSiteMonitor } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { macNorm, ordemPorta, religarPoe, useSwitchPortas, type PortaSw } from '../lib/switch';
import { desde } from '../lib/tempo';
import { Caminho, type Elo } from '../ui/Caminho';
import { Carregando, Cartao, Icone, Vazio, useToast } from '../ui/pecas';
import { useFiltro } from '../ui/Filtros';

type DetSw = { ip?: string; model?: string; modelo?: string; firmware?: string; versao?: string; ports_total?: number; ports_up?: number; poe_watts?: number; last_poll?: string; lido_em?: string };

/* Ficha do switch: as portas, o que esta em cada uma e religar o PoE. */
export function Switch() {
  const { chave = '' } = useParams();
  const key = decodeURIComponent(chave);
  const { site } = useSite();
  const m = useSiteMonitor(null);
  const sw = useSwitchPortas();
  const cams = useCameras();
  const online = useOnline();
  const toast = useToast();
  const ir = useNavigate();
  const [sel, setSel] = useState<string | null>(null);
  const [religando, setReligando] = useState(false);

  const e = m.switches.find((x) => x.entity_key === key);
  const d = e ? detalhe<DetSw>(e) : {};
  const ip = String(d.ip ?? '');

  const portas = useMemo(() => (sw.data?.portas ?? [])
    .filter((p) => p.switch_ip === ip)
    .sort((a, b) => ordemPorta(a.port, b.port)), [sw.data, ip]);

  // O que esta em cada porta: camera do inventario pelo MAC visto nela, ou pelo cadastro switch_port.
  const camPorPorta = useMemo(() => {
    const porMac = new Map((cams.data ?? []).filter((c) => c.mac).map((c) => [macNorm(c.mac), c]));
    const saida = new Map<string, Camera[]>();
    for (const r of sw.data?.macs ?? []) {
      if (r.switch_ip !== ip || !r.port) continue;
      const c = porMac.get(macNorm(r.mac));
      if (c) saida.set(r.port, [...(saida.get(r.port) ?? []).filter((x) => x !== c), c]);
    }
    for (const c of cams.data ?? []) {
      const cc = c as Camera & { switch_ip?: string; switch_port?: string };
      if (cc.switch_ip === ip && cc.switch_port && !saida.get(cc.switch_port)?.includes(c)) {
        saida.set(cc.switch_port, [...(saida.get(cc.switch_port) ?? []), c]);
      }
    }
    return saida;
  }, [sw.data, cams.data, ip]);
  const macsPorPorta = useMemo(() => {
    const s = new Map<string, number>();
    for (const r of sw.data?.macs ?? []) if (r.switch_ip === ip && r.port) s.set(r.port, (s.get(r.port) ?? 0) + 1);
    return s;
  }, [sw.data, ip]);
  const { lista: portasVistas, barra } = useFiltro(portas, {
    texto: (x) => [`porta ${x.port}`, x.port, ...(camPorPorta.get(x.port ?? '') ?? []).flatMap((c) => [tituloDa(c), c.ip, c.mac])],
    dica: 'Porta, câmera, IP ou MAC',
    situacao: (x) => (x.up ? 'ok' : (camPorPorta.get(x.port ?? '') ?? []).length ? 'fora' : 'atencao'),
    nomes: { todos: 'Todas', ok: 'Ligadas', fora: 'Caiu', atencao: 'Vazias' },
  });

  if (m.carregando) return <Carregando />;
  if (!e) return <Cartao><Vazio>Switch não encontrado no monitoramento.</Vazio></Cartao>;

  const p: PortaSw | undefined = portas.find((x) => x.port === sel) ?? undefined;
  const camsSel = p?.port ? camPorPorta.get(p.port) ?? [] : [];
  const uplink = p?.port ? (macsPorPorta.get(p.port) ?? 0) >= 32 : false;
  const con = m.conectores.find((c) => e.connector_id && c.connector_id === e.connector_id) ?? m.conectores.find((c) => c.site === e.site);

  async function religar() {
    if (!p?.port) return;
    const quem = camsSel.length ? camsSel.map(tituloDa).join(', ') : 'o que estiver ligado nela';
    if (!window.confirm(`Desligar e religar o PoE da porta ${p.port}?\n\n${quem} vai reiniciar (fica uns 2 minutos sem vídeo).`)) return;
    setReligando(true);
    try {
      await religarPoe(ip, e!.site || site || '', p.port);
      toast(`PoE da porta ${p.port} religado. A câmera volta em 1 a 2 minutos.`);
    } catch (err) {
      toast(`Não consegui religar: ${(err as Error).message}`, true);
    } finally {
      setReligando(false);
    }
  }

  const elos: Elo[] = [
    ...(con ? [{ tipo: 'conector' as const, titulo: `Conector ${nomeEntidade(con)}`, estado: con.status === 'up' ? 'ok' as const : 'ruim' as const }] : []),
    { tipo: 'switch', titulo: 'Este switch', aqui: true, estado: e.status === 'up' ? 'ok' : 'ruim' },
  ];

  return (
    <>
      <div className="linha-topo">
        <button type="button" className="voltar" onClick={() => ir(-1)} aria-label="Voltar">{Icone.volta}</button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 className="titulo-tela">{nomeEntidade(e)}</h1>
          <p className="sub-tela mono">{[ip, d.model || d.modelo].filter(Boolean).join(' · ')}</p>
        </div>
        <span className={`selo ${e.status === 'up' ? 'verde' : 'vermelho'}`}>{e.status === 'up' ? 'online' : 'fora'}</span>
      </div>

      <div className="numeros-3">
        <div><span>Portas ligadas</span><b>{d.ports_up ?? '—'}<small>/{d.ports_total ?? '—'}</small></b></div>
        <div><span>PoE</span><b>{d.poe_watts != null ? `${String(d.poe_watts).replace('.', ',')} W` : '—'}</b></div>
        <div><span>Lido</span><b style={{ fontSize: 15 }}>{desde(d.last_poll || d.lido_em)}</b></div>
      </div>

      <Cartao>
        <h2>Portas</h2>
        {sw.isPending ? <Carregando /> : !portas.length ? (
          <Vazio>Ainda não há leitura das portas deste switch. Rode “Coletar MACs” no SightOps web (Implantação › Switch).</Vazio>
        ) : (
          <>
            <div style={{ padding: '0 14px 10px' }}>{barra}</div>
            {!portasVistas.length ? <Vazio>Nenhuma porta com esse filtro.</Vazio> : null}
            <div className="portas-sw">
              {portasVistas.map((x) => {
                const c = camPorPorta.get(x.port ?? '') ?? [];
                const rot = (macsPorPorta.get(x.port ?? '') ?? 0) >= 32 ? 'uplink' : c.length ? (c.length > 1 ? `${c.length} cam` : 'câm') : x.up ? 'ligada' : 'vazia';
                return (
                  <button key={x.port} type="button" aria-pressed={sel === x.port}
                          className={`porta-sw ${x.up ? 'up' : c.length ? 'caiu' : 'vazia'}`}
                          onClick={() => setSel(sel === x.port ? null : x.port ?? null)}
                          aria-label={`Porta ${x.port}: ${c.map(tituloDa).join(', ') || rot}`}>
                    <span className="n">{x.port}</span><span className="l">{x.up || !c.length ? rot : 'caiu'}</span>
                  </button>
                );
              })}
            </div>
            <p className="sub-tela" style={{ padding: '0 14px 12px', margin: 0 }}>Toque numa porta para ver o que está nela.</p>
          </>
        )}
      </Cartao>

      {p ? (
        <Cartao>
          <h2>Porta {p.port} · {p.up ? 'ligada' : camsSel.length ? 'sem link' : 'vazia'}</h2>
          <div className="ficha">
            {camsSel.map((c) => (
              <button key={chaveDa(c)} type="button" className="ficha-linha ficha-link" onClick={() => ir(`/cameras/${chaveDa(c)}`)}>
                <span className="ficha-rot">Câmera</span><span className="ficha-val">{tituloDa(c)} ›</span>
              </button>
            ))}
            {!camsSel.length ? <div className="ficha-linha"><span className="ficha-rot">Ligado</span><span className="ficha-val">{uplink ? 'uplink (muitos MACs)' : `${macsPorPorta.get(p.port ?? '') ?? 0} MAC(s) vistos`}</span></div> : null}
            <div className="ficha-linha"><span className="ficha-rot">PoE</span><span className="ficha-val mono">{p.poe_enabled === false ? 'desligado' : p.poe_power_watts != null ? `${String(p.poe_power_watts).replace('.', ',')} W` : '—'}</span></div>
            <div className="ficha-linha"><span className="ficha-rot">Velocidade</span><span className="ficha-val mono">{p.up ? (p.bandwidth || '—') : 'sem link'}</span></div>
          </div>
          {p.port_id != null && !uplink ? (
            <div style={{ padding: '0 14px 14px' }}>
              <button type="button" className="btn" disabled={religando || !online} onClick={() => void religar()}>
                {Icone.raio}{religando ? 'Religando…' : 'Religar PoE desta porta'}
              </button>
            </div>
          ) : null}
        </Cartao>
      ) : null}

      <Caminho elos={elos} />
    </>
  );
}
