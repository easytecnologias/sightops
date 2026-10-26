import { useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { enviar } from '../lib/api';
import { detalhe, useOlts, useSinalOnu, type AmostraSinal, type Entidade } from '../lib/dados';
import { LIMITE_RX, num, nomeEntidade, partesOnu, quando, rxDa, sinalBaixo, useSiteMonitor, type DetalheOnu } from '../lib/monitor';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';

const dbm = (v: number | null) => (v === null ? '—' : `${v.toFixed(1).replace('.', ',').replace('-', '−')} dBm`);

/* Lista de ONUs do site, com busca e filtro por OLT/PON (vem da Rede). */
export function ListaOnus() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const [param] = useSearchParams();
  const [busca, setBusca] = useState(param.get('q') ?? '');
  const olt = param.get('olt') ?? '';
  const pon = param.get('pon') ?? '';
  const ir = useNavigate();

  const lista = useMemo(() => {
    const t = busca.trim().toLowerCase();
    return m.onus.filter((e) => {
      const p = partesOnu(e.entity_key);
      if (olt && p.oltIp !== olt) return false;
      if (pon && p.pon !== pon) return false;
      if (!t) return true;
      const d = detalhe<DetalheOnu>(e);
      return [e.display_name, d.serial].some((v) => String(v ?? '').toLowerCase().includes(t));
    }).sort((a, b) => {
      const pa = a.status !== 'up' ? 0 : sinalBaixo(a) ? 1 : 2;
      const pb = b.status !== 'up' ? 0 : sinalBaixo(b) ? 1 : 2;
      return pa - pb || String(a.display_name).localeCompare(String(b.display_name), 'pt-BR', { numeric: true });
    });
  }, [m.onus, busca, olt, pon]);

  if (m.carregando) return <Carregando />;
  return (
    <>
      <div className="linha-topo">
        <button type="button" className="voltar" onClick={() => ir(-1)} aria-label="Voltar">{Icone.volta}</button>
        <div>
          <h1 className="titulo-tela">ONUs</h1>
          <p className="sub-tela">{pon ? `PON ${pon} · ` : ''}{lista.length} de {m.onus.length} no site</p>
        </div>
      </div>
      <label className="busca">
        {Icone.busca}
        <input type="search" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="Serial ou nome"
               aria-label="Buscar ONU por serial ou nome" autoCapitalize="none" spellCheck={false} />
      </label>
      <Cartao>
        {!lista.length ? <Vazio>Nenhuma ONU encontrada.</Vazio> : lista.slice(0, 150).map((e) => {
          const d = detalhe<DetalheOnu>(e);
          const rx = rxDa(e);
          return (
            <Item key={e.entity_key} ponto={e.status !== 'up' ? 'vermelho' : sinalBaixo(e) ? 'ambar' : 'verde'}
                  titulo={nomeEntidade(e)}
                  sub={[d.serial, e.status !== 'up' ? (d.offline_reason || 'fora do ar') : rx !== null ? `RX ${dbm(rx)}` : ''].filter(Boolean).join(' · ')}
                  onClick={() => ir(`/onu/${encodeURIComponent(e.entity_key)}`)} direita={Icone.seta} />
          );
        })}
      </Cartao>
    </>
  );
}

function Grafico({ amostras }: { amostras: AmostraSinal[] }) {
  // Ultimas 24 h, da mais antiga para a mais nova.
  const corte = Date.now() - 24 * 3600 * 1000;
  const pts = amostras
    .map((a) => ({ t: quando(a.captured_at) ?? 0, v: num(a.onu_rx) }))
    .filter((p): p is { t: number; v: number } => p.t >= corte && p.v !== null)
    .sort((a, b) => a.t - b.t);
  if (pts.length < 2) return <Vazio>Sem histórico de sinal nas últimas 24 h.</Vazio>;
  const vs = pts.map((p) => p.v);
  const min = Math.min(...vs, LIMITE_RX - 1);
  const max = Math.max(...vs, LIMITE_RX + 1);
  const W = 326; const H = 84;
  const x = (t: number) => ((t - pts[0].t) / Math.max(1, pts[pts.length - 1].t - pts[0].t)) * W;
  const y = (v: number) => H - 4 - ((v - min) / Math.max(0.1, max - min)) * (H - 8);
  const linha = pts.map((p) => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ');
  const hora = (t: number) => new Date(t).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  return (
    <div style={{ padding: '0 14px 12px' }}>
      <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
           aria-label={`Sinal RX nas últimas 24 horas, de ${dbm(vs[0])} a ${dbm(vs[vs.length - 1])}`}>
        <line x1="0" y1={y(LIMITE_RX)} x2={W} y2={y(LIMITE_RX)} stroke="#b86b00" strokeWidth="1.2" strokeDasharray="4 4" />
        <polyline fill="none" stroke="#1971c2" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round" points={linha} />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--muted)', marginTop: 2 }}>
        <span>{hora(pts[0].t)}</span><span style={{ color: 'var(--amber-txt)', fontWeight: 600 }}>limite −27 dBm</span><span>agora</span>
      </div>
    </div>
  );
}

type Leitura = Record<string, unknown> & { ok?: boolean; error?: string };

/** Campos de sinal que cada fabricante devolve com nomes diferentes. */
function camposLeitura(r: Leitura): [string, string][] {
  const nomes: [RegExp, string][] = [
    [/^(onu_)?rx(_power)?$|rx_power|onu_rx/i, 'Recebe (RX)'], [/^(onu_)?tx(_power)?$|tx_power|onu_tx/i, 'Envia (TX)'],
    [/olt_rx/i, 'OLT recebe'], [/dist/i, 'Distância'], [/temp/i, 'Temperatura'], [/oper|status|state/i, 'Estado'],
  ];
  const saida: [string, string][] = [];
  const vistos = new Set<string>();
  for (const [k, v] of Object.entries(r)) {
    if (v === null || v === undefined || v === '' || typeof v === 'object' || k === 'ok') continue;
    const n = nomes.find(([re]) => re.test(k));
    if (!n || vistos.has(n[1])) continue;
    vistos.add(n[1]);
    saida.push([n[1], String(v)]);
  }
  return saida;
}

/* 16 · Consultar ONU */
export function ConsultarOnu() {
  const { chave = '' } = useParams();
  const key = decodeURIComponent(chave);
  const { site } = useSite();
  const m = useSiteMonitor(null);
  const olts = useOlts();
  const sinal = useSinalOnu(key);
  const ir = useNavigate();
  const toast = useToast();
  const [lendo, setLendo] = useState(false);
  const [leitura, setLeitura] = useState<Leitura | null>(null);

  const e: Entidade | undefined = m.onus.find((x) => x.entity_key === key);
  if (m.carregando) return <Carregando />;
  if (!e) return <Cartao><Vazio>ONU não encontrada no monitoramento.</Vazio></Cartao>;

  const d = detalhe<DetalheOnu>(e);
  const p = partesOnu(key);
  const olt = (olts.data ?? []).find((o) => o.ip === p.oltIp);
  const rx = rxDa(e);
  const baixo = sinalBaixo(e);

  async function lerAgora() {
    if (!olt) { toast('Esta OLT não está cadastrada no SightOps: não dá para ler ao vivo.', true); return; }
    setLendo(true);
    setLeitura(null);
    try {
      // Somente leitura na OLT (onu_signal): nenhum comando de configuracao.
      const r = await enviar<Leitura>('/api/olt/onu-signal', {
        olt_id: olt.id, pon: Number(p.pon) || 0, onu: Number(p.onu) || 0, serial: d.serial || '', site: e!.site || site || '',
      });
      if (r.ok === false) throw new Error(String(r.error || 'A OLT não devolveu a leitura.'));
      setLeitura(r);
      void sinal.refetch();
    } catch (err) {
      toast(`Não consegui ler na OLT: ${(err as Error).message}`, true);
    } finally {
      setLendo(false);
    }
  }

  return (
    <>
      <div className="linha-topo">
        <button type="button" className="voltar" onClick={() => ir(-1)} aria-label="Voltar">{Icone.volta}</button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 className="titulo-tela">{nomeEntidade(e)}</h1>
          <p className="sub-tela mono">{[d.serial, e.site].filter(Boolean).join(' · ')}</p>
        </div>
        <span className={`selo ${e.status !== 'up' ? 'ambar' : baixo ? 'ambar' : 'verde'}`}>
          {e.status !== 'up' ? 'fora do ar' : baixo ? 'sinal baixo' : 'sinal bom'}
        </span>
      </div>

      <div className="mosaico">
        <div className="bloco" style={baixo ? { borderColor: 'var(--amber-borda)', background: '#fffbf0' } : undefined}>
          <span className="rot">Recebe (RX)</span><span className={`num mono${baixo ? ' ambar' : ''}`} style={{ fontSize: 19 }}>{dbm(rx)}</span>
        </div>
        <div className="bloco"><span className="rot">Envia (TX)</span><span className="num mono" style={{ fontSize: 19 }}>{dbm(num(d.onu_tx))}</span></div>
        <div className="bloco"><span className="rot">Distância</span><span className="num mono" style={{ fontSize: 19 }}>{num(d.distance_km) !== null ? `${Math.round(num(d.distance_km)! * 1000)} m` : '—'}</span></div>
        <div className="bloco">
          <span className="rot">{e.status === 'up' ? 'Online' : 'Fora'}</span>
          <span className="num mono" style={{ fontSize: 19 }}>{e.last_changed_at ? desde(e.last_changed_at) : '—'}</span>
        </div>
      </div>

      <Cartao>
        <h2>Sinal nas últimas 24 h</h2>
        {sinal.isPending ? <Carregando /> : <Grafico amostras={sinal.data ?? []} />}
      </Cartao>

      <Cartao>
        <div className="ficha">
          <div className="ficha-linha"><span className="ficha-rot">OLT · posição</span><span className="ficha-val mono">{olt?.name || p.oltIp} · PON {p.pon} · ONU {p.onu}</span></div>
          {e.status !== 'up' && d.offline_reason ? <div className="ficha-linha"><span className="ficha-rot">Motivo</span><span className="ficha-val">{d.offline_reason}</span></div> : null}
          {num(d.temperatura) !== null ? <div className="ficha-linha"><span className="ficha-rot">Temperatura</span><span className="ficha-val">{d.temperatura} °C</span></div> : null}
          <div className="ficha-linha"><span className="ficha-rot">Zabbix</span><span className="ficha-val">{e.status === 'up' ? (baixo ? 'no ar, sinal abaixo de −27 dBm' : 'no ar') : 'fora do ar'}{e.last_checked_at ? ` · lido ${desde(e.last_checked_at)}` : ''}</span></div>
        </div>
      </Cartao>

      {leitura ? (
        <Cartao>
          <h2>Lido agora na OLT</h2>
          <div className="ficha">
            {camposLeitura(leitura).map(([k, v]) => (
              <div key={k} className="ficha-linha"><span className="ficha-rot">{k}</span><span className="ficha-val mono">{v}</span></div>
            ))}
            {!camposLeitura(leitura).length ? <div className="ficha-linha"><span className="ficha-val">A OLT respondeu, mas sem campos de sinal.</span></div> : null}
          </div>
        </Cartao>
      ) : null}

      <button type="button" className="btn2" disabled={lendo} onClick={lerAgora}>
        {Icone.atualizar}{lendo ? 'Lendo na OLT…' : 'Ler de novo na OLT'}
      </button>
      <p className="sub-tela" style={{ textAlign: 'center' }}>A leitura só consulta a OLT pelo conector; não muda nada na ONU.</p>
    </>
  );
}
