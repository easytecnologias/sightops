import { useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { enviar } from '../lib/api';
import { chaveDa, detalhe, estadoDa, ipDaOlt, tituloDa, useCameras, useOlts, useSinalOnu, type AmostraSinal, type Entidade } from '../lib/dados';
import { Caminho, type Elo } from '../ui/Caminho';
import { LIMITE_RX, num, nomeEntidade, partesOnu, quando, rxDa, sinalBaixo, useSiteMonitor, type DetalheOnu } from '../lib/monitor';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { BotaoArmado, Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';
import { useAcoes } from '../lib/implantar';
import { useEu } from '../lib/dados';
import { useFiltro } from '../ui/Filtros';

const NOME_ACAO: Record<string, string> = {
  add_onu: 'ONU autorizada', add_onu_bridge: 'Serviço e VLAN configurados', reboot_onu: 'ONU reiniciada',
  delete_onu: 'Removida da OLT', find_onu: 'Procurada na OLT', onu_signal: 'Sinal lido na OLT',
};
const dbm = (v: number | null) => (v === null ? '—' : `${v.toFixed(1).replace('.', ',').replace('-', '−')} dBm`);

/* Lista de ONUs do site, com busca e filtro por OLT/PON (vem da Rede). */
export function ListaOnus() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const [param] = useSearchParams();
  const olt = param.get('olt') ?? '';
  const pon = param.get('pon') ?? '';
  const ir = useNavigate();

  const daPon = useMemo(() => m.onus.filter((e) => {
    const p = partesOnu(e.entity_key);
    return (!olt || p.oltIp === olt) && (!pon || p.pon === pon);
  }), [m.onus, olt, pon]);
  const nomeOlt = (ip: string) => {
    const o = m.olts.find((x) => String(detalhe<{ host?: string }>(x).host ?? '') === ip);
    return o ? nomeEntidade(o) : `OLT ${ip}`;
  };
  const { lista, barra } = useFiltro(daPon, {
    texto: (e) => [e.display_name, detalhe<DetalheOnu>(e).serial], dica: 'Serial ou nome', buscaInicial: param.get('q') ?? '',
    local: (e) => String(e.site ?? '').trim().toUpperCase(),
    situacao: (e) => (e.status !== 'up' ? 'fora' : sinalBaixo(e) ? 'atencao' : 'ok'), nomes: { atencao: 'Sinal baixo', ok: 'Normal' },
    extra: olt ? undefined : { rotulo: 'OLT', todos: 'Todas as OLTs', de: (e) => nomeOlt(partesOnu(e.entity_key).oltIp) },
  });

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
      {barra}
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
  const cams = useCameras();
  const ir = useNavigate();
  const toast = useToast();
  const [lendo, setLendo] = useState(false);
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  // Hooks das acoes ANTES dos returns abaixo (a ONU pode chegar depois).
  const eu = useEu();
  const podeRemover = ['admin', 'owner'].includes(String(eu.data?.role ?? '').toLowerCase());
  const [fazendo, setFazendo] = useState('');
  const acoes = useAcoes(partesOnu(key).oltIp);

  const e: Entidade | undefined = m.onus.find((x) => x.entity_key === key);
  if (m.carregando) return <Carregando />;
  if (!e) return <Cartao><Vazio>ONU não encontrada no monitoramento.</Vazio></Cartao>;

  const d = detalhe<DetalheOnu>(e);
  const p = partesOnu(key);
  const olt = (olts.data ?? []).find((o) => ipDaOlt(o) === p.oltIp);
  const rx = rxDa(e);
  const baixo = sinalBaixo(e);
  const serial = String(d.serial ?? '').toUpperCase();
  // Cameras atras desta ONU: pelo serial gravado na camera ou pela posicao PON/ONU.
  const atras = (cams.data ?? []).filter((c) => (serial && String(c.onu_serial ?? '').toUpperCase() === serial)
    || (c.pon && c.onu_id && String(c.pon).split('/').pop() === p.pon && String(c.onu_id) === p.onu && (!e.site || !c.site || c.site === e.site)));
  const con = m.conectores.find((c) => e.connector_id && c.connector_id === e.connector_id);
  const elos: Elo[] = [
    ...(con ? [{ tipo: 'conector' as const, titulo: `Conector ${nomeEntidade(con)}`, estado: con.status === 'up' ? 'ok' as const : 'ruim' as const }] : []),
    { tipo: 'olt', titulo: <>{olt?.name || `OLT ${p.oltIp}`} · PON <span className="mono">{p.pon}</span></>,
      onClick: () => ir(`/pon?olt=${encodeURIComponent(p.oltIp)}&pon=${encodeURIComponent(p.pon)}`) },
    { tipo: 'onu', titulo: `Esta ONU · ${p.onu}`, aqui: true, falha: e.status !== 'up',
      sub: num(d.distance_km) !== null ? `a ${String(num(d.distance_km)!.toFixed(1)).replace('.', ',')} km da OLT` : undefined,
      estado: e.status !== 'up' ? 'ruim' : baixo ? 'atencao' : 'ok' },
    ...atras.slice(0, 6).map((c) => ({
      tipo: (c.switch_ip ? 'switch' : 'camera') as Elo['tipo'],
      titulo: c.switch_ip ? `${c.switch_name || c.switch_ip} › ${tituloDa(c)}` : tituloDa(c),
      sub: c.switch_port ? `porta ${c.switch_port}` : undefined,
      estado: (estadoDa(c) === 'online' ? 'ok' : estadoDa(c) === 'offline' ? 'ruim' : 'sem') as Elo['estado'],
      onClick: () => ir(`/cameras/${chaveDa(c)}`),
    })),
  ];

  // Acoes na ONU. EQUIPAMENTO VIVO: reiniciar derruba o que esta atras dela
  // por ~1 min; remover desautoriza na OLT (so admin/dono, regra e_exclusao).
  const destaOnu = (acoes.data ?? []).filter((a) => String(a.pon ?? '') === p.pon && String(a.onu ?? '') === p.onu).slice(0, 5);
  const posicao = () => ({ olt_id: olt!.id, pon: Number(p.pon) || 0, onu: Number(p.onu) || 0, serial: d.serial || '',
    site: e!.site || site || '', olt_name: olt!.name || '', connector_id: olt!.connector_id || '', remote_connector_id: olt!.connector_id || '' });
  async function naOlt(qual: 'reboot' | 'delete') {
    if (!olt) { toast('Esta OLT não está cadastrada no SightOps.', true); return; }
    setFazendo(qual);
    try {
      const r = await enviar<{ ok?: boolean; error?: string; detail?: string }>(`/api/olt/${qual === 'reboot' ? 'reboot-onu' : 'delete-onu'}`, posicao());
      if (r.ok === false) throw new Error(String(r.error || r.detail || 'A OLT recusou.'));
      toast(qual === 'reboot' ? 'ONU reiniciando: volta em ~1 min.' : 'ONU removida da OLT.');
      void acoes.refetch();
      if (qual === 'delete') ir(-1);
    } catch (err) {
      toast(`${qual === 'reboot' ? 'Não reiniciou' : 'Não removeu'}: ${(err as Error).message}`, true);
    } finally {
      setFazendo('');
    }
  }

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

      <Caminho elos={elos} />

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

      <Cartao>
        <h2>Ações na ONU</h2>
        <div className="form-cartao">
          <BotaoArmado classe="btn2" rotulo={<>{Icone.atualizar}Reiniciar ONU</>} enviando="Mandando à OLT…"
                       armar={`Toque de novo: reiniciar a ONU ${p.onu} da PON ${p.pon}${atras.length ? ` (${atras.length} câmera${atras.length === 1 ? '' : 's'} caem por ~1 min)` : ''}`}
                       indo={fazendo === 'reboot'} desab={!olt || !!fazendo} onConfirmar={() => void naOlt('reboot')} />
          {podeRemover ? (
            <BotaoArmado classe="btn2 perigo" rotulo="Remover da OLT" enviando="Mandando à OLT…"
                         armar={`Toque de novo: desautorizar ${d.serial || `ONU ${p.onu}`}${atras.length ? ` — ${atras.length} câmera${atras.length === 1 ? '' : 's'} param` : ''}`}
                         indo={fazendo === 'delete'} desab={!olt || !!fazendo} onConfirmar={() => void naOlt('delete')} />
          ) : <span className="sub-tela">Remover da OLT: só administrador ou dono.</span>}
          {!olt ? <span className="sub-tela">Esta OLT não está cadastrada no SightOps: as ações não estão disponíveis.</span> : null}
        </div>
        {destaOnu.length ? (
          <>
            <span className="rot-secao" style={{ padding: '0 14px' }}>Feito nesta ONU</span>
            {destaOnu.map((a, i) => (
              <Item key={i} ponto={a.ok ? 'verde' : 'vermelho'} titulo={NOME_ACAO[String(a.action || '')] ?? String(a.action || '').replace(/_/g, ' ')}
                    sub={[a.created_at ? desde(a.created_at) : '', a.vlan ? `VLAN ${a.vlan}` : '', a.ok ? '' : (a.detail || 'falhou')].filter(Boolean).join(' · ')} />
            ))}
          </>
        ) : null}
      </Cartao>
    </>
  );
}
