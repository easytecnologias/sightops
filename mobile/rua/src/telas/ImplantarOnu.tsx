import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { enviar } from '../lib/api';
import { ipDaOlt, useEntidades, useOlts } from '../lib/dados';
import { useFiltroSite, partesOnu } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import {
  SERVICOS, baseOlt, ehEpon, ehVsol, pode, ponsDa, serialDa, useAcoes, useRascunhoOnu, vlanDoSite,
  type OltCompleta, type OnuDescoberta, type Servico,
} from '../lib/implantar';
import { Carregando, Cartao, Icone, Item, Vazio } from '../ui/pecas';

function Passos({ n }: { n: number }) {
  return (
    <div className="passos-claros" aria-label={`Passo ${n} de 3`}>
      {['Escolher', 'Configurar', 'Pronta'].map((t, i) => (
        <span key={t} className={i < n ? 'on' : ''}><span className="b" />{i + 1} · {t}</span>
      ))}
    </div>
  );
}

function Voltar({ para, rot }: { para: string | number; rot: string }) {
  const ir = useNavigate();
  return (
    <button type="button" className="volta-link" onClick={() => (typeof para === 'number' ? ir(para) : ir(para))}>
      {Icone.volta}{rot}
    </button>
  );
}

/** OLTs do site que sabem autorizar ONU. */
export function useOltsDoSite() {
  const { site } = useSite();
  const filtro = useFiltroSite(site);
  const q = useOlts();
  const lista = ((q.data ?? []) as OltCompleta[]).filter((o) => o.active !== false && filtro(o.site, o.connector_id));
  return { ...q, lista, site: site ?? '' };
}

/* 2 · Ativar ONU — escolher */
export function OnuEscolher() {
  const online = useOnline();
  const { lista, isPending, site } = useOltsDoSite();
  const { r, mudar, zerar } = useRascunhoOnu();
  const ir = useNavigate();
  const [buscando, setBuscando] = useState(false);
  const [erro, setErro] = useState('');
  const [achadas, setAchadas] = useState<OnuDescoberta[] | null>(null);
  const [livres, setLivres] = useState('');
  const [mac, setMac] = useState('');
  const [pon, setPon] = useState('');

  const olt = r.olt && lista.some((o) => o.id === r.olt!.id) ? r.olt : lista.length === 1 ? lista[0] : undefined;
  useEffect(() => { if (olt && r.olt?.id !== olt.id) zerar({ olt }); }, [olt?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const manual = ehEpon(olt);
  const autoriza = pode(olt, 'add_onu');

  async function procurar() {
    if (!olt) return;
    setBuscando(true); setErro(''); setAchadas(null);
    try {
      const d = await enviar<{ ok?: boolean; detail?: string; pons?: Record<string, { discovered?: OnuDescoberta[]; free_slots?: unknown[] }> }>(
        '/api/olt/discover-onus', { ...baseOlt(olt, site), pon: 'all' });
      if (d.ok === false) throw new Error(d.detail || 'A OLT não respondeu.');
      const pons = d.pons ?? {};
      const todas: OnuDescoberta[] = [];
      const resumo: string[] = [];
      Object.keys(pons).sort((a, b) => Number(a) - Number(b)).forEach((k) => {
        (pons[k]?.discovered ?? []).forEach((x) => todas.push({ ...x, pon: Number(x.pon ?? k) }));
        if (pons[k]?.free_slots) resumo.push(`PON ${k}: ${(pons[k].free_slots ?? []).length} livres`);
      });
      setAchadas(todas);
      setLivres(resumo.join(' · '));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setBuscando(false);
    }
  }

  function escolher(o: OnuDescoberta) {
    mudar({ onu: o, macManual: undefined, ponManual: undefined });
    ir('/implantar/onu/configurar');
  }

  function seguirManual() {
    const m = mac.trim();
    const p = Number(pon);
    if (!m || !p) { setErro('Informe o MAC da ONU e a PON.'); return; }
    mudar({ onu: undefined, macManual: m, ponManual: p });
    ir('/implantar/onu/configurar');
  }

  return (
    <>
      <Voltar para="/implantar" rot="Implantar" />
      <div>
        <h1 className="titulo-tela">Ativar ONU</h1>
        <p className="sub-tela">Autorizar ONU nova na PON, direto na OLT.</p>
      </div>
      <Passos n={1} />

      {isPending ? <Carregando /> : !lista.length ? (
        <Cartao><Vazio>Nenhuma OLT cadastrada neste site.<br />O cadastro da OLT é feito no SightOps pelo navegador.</Vazio></Cartao>
      ) : (
        <>
          {lista.length > 1 ? (
            <Cartao>
              <h2>OLT</h2>
              {lista.map((o) => (
                <Item key={o.id} icone={Icone.rede} titulo={o.name || ipDaOlt(o)}
                      sub={[o.capability_label || [o.vendor, o.model].filter(Boolean).join(' '), ipDaOlt(o)].filter(Boolean).join(' · ')}
                      onClick={() => { zerar({ olt: o }); setAchadas(null); setErro(''); }}
                      direita={olt?.id === o.id ? <span className="selo verde">escolhida</span> : Icone.seta} />
              ))}
            </Cartao>
          ) : olt ? (
            <div className="aviso neutro">{Icone.rede}<span><b>{olt.name}</b> · {olt.capability_label || [olt.vendor, olt.model].filter(Boolean).join(' ')}</span></div>
          ) : null}

          {olt && !autoriza ? (
            <div className="aviso ambar">{Icone.aviso}<span>{olt.capability_label || 'Esta OLT'} ainda não autoriza ONU pelo SightOps. {olt.capability_notes || ''}</span></div>
          ) : null}

          {olt && autoriza && !manual ? (
            <>
              <button type="button" className="btn" disabled={buscando || !online} onClick={procurar}>
                {Icone.busca}{buscando ? 'Consultando a OLT…' : achadas ? 'Procurar de novo' : 'Procurar ONUs novas'}
              </button>
              {!online ? <p className="sub-tela">Sem sinal: a busca precisa falar com a OLT agora.</p> : null}
              {achadas ? (
                <Cartao>
                  <h2>Não autorizadas</h2>
                  {livres ? <p className="sub-h2">{livres}</p> : null}
                  {!achadas.length ? <Vazio>Nenhuma ONU nova na OLT.<br />Confira se a ONU está ligada e com a fibra conectada.</Vazio>
                    : achadas.map((o, i) => (
                      <Item key={`${serialDa(o)}-${i}`} icone={Icone.onu} titulo={serialDa(o) || '(sem serial)'}
                            sub={[`PON ${o.pon}`, [o.vendor, o.model].filter(Boolean).join(' '), o.time_discovered ? `vista ${o.time_discovered}` : ''].filter(Boolean).join(' · ')}
                            onClick={() => escolher(o)} direita={Icone.seta} />
                    ))}
                </Cartao>
              ) : null}
            </>
          ) : null}

          {olt && autoriza && manual ? (
            <Cartao>
              <h2>ONU pelo MAC</h2>
              <p className="sub-h2">Esta OLT não lista as ONUs novas: digite o MAC da etiqueta.</p>
              <div className="form-cartao">
                <div className="campo"><label htmlFor="mac">MAC da ONU</label>
                  <div className="caixa"><input id="mac" className="mono" value={mac} onChange={(e) => setMac(e.target.value)} placeholder="00:00:00:00:00:00" autoCapitalize="characters" spellCheck={false} /></div></div>
                <div className="campo"><span className="lb">PON</span>
                  <div className="seg">{Array.from({ length: ponsDa(olt) }, (_, i) => String(i + 1)).map((p) => (
                    <button key={p} type="button" aria-pressed={pon === p} onClick={() => setPon(p)}>{p}</button>))}</div></div>
                <button type="button" className="btn" onClick={seguirManual}>Continuar</button>
              </div>
            </Cartao>
          ) : null}

          {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}
        </>
      )}
    </>
  );
}

/* 3 · Ativar ONU — configurar */
export function OnuConfigurar() {
  const online = useOnline();
  const { site } = useOltsDoSite();
  const { r, mudar } = useRascunhoOnu();
  const acoes = useAcoes(ipDaOlt(r.olt));
  const ir = useNavigate();
  const [armado, setArmado] = useState(false);
  const [indo, setIndo] = useState(false);
  const [erro, setErro] = useState('');
  const timer = useRef<number>();

  const olt = r.olt;
  const epon = ehEpon(olt);
  const vsol = ehVsol(olt);
  const serial = r.onu ? serialDa(r.onu) : r.macManual ?? '';
  const pon = r.onu?.pon ?? r.ponManual ?? 0;
  const padrao = vlanDoSite(acoes.data);

  useEffect(() => { if (!r.vlan && padrao) mudar({ vlan: String(padrao) }); }, [padrao]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => window.clearTimeout(timer.current), []);

  if (!olt || !serial) {
    return <Cartao><Vazio>Escolha a ONU primeiro.<br /><button type="button" className="link" onClick={() => ir('/implantar/onu')}>Voltar</button></Vazio></Cartao>;
  }

  const vlan = Number(r.vlan);
  const precisaVlan = !vsol && !(epon && r.vlanModeEpon === 'transparent');

  async function autorizar() {
    setErro('');
    if (precisaVlan && !(vlan > 0 && vlan < 4095)) { setErro('Informe a VLAN (1 a 4094).'); return; }
    if (!armado) {
      setArmado(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setArmado(false), 6000);
      return;
    }
    window.clearTimeout(timer.current);
    setArmado(false);
    setIndo(true);
    const base = baseOlt(olt!, site);
    let corpo: Record<string, unknown>;
    if (vsol) {
      corpo = { ...base, pon, serno_id: 0, vlan: 0, serial };
    } else if (epon) {
      const porta = Number(r.portaEpon) || 1;
      corpo = {
        ...base, pon, serno_id: 0, serial, description: r.descricao.trim(),
        vlan: precisaVlan ? vlan : 0, vlan_mode: r.vlanModeEpon,
        services: precisaVlan ? [{ service: 'downlink', vlan, port: porta }] : [],
      };
    } else {
      const o = r.onu!;
      corpo = {
        ...base, pon, serno_id: Number(o.serno_id ?? 0), onu_model: o.model || '', serial,
        serial_raw: o.serial_raw || serial, vendor: o.vendor || '', description: r.descricao.trim(),
        service: r.servico, vlan, services: [{ service: r.servico, vlan }], tag_mode: r.tagMode, terminal: r.terminal,
      };
    }
    try {
      const res = await enviar<Record<string, unknown> & { ok?: boolean }>('/api/olt/add-onu', corpo);
      mudar({ resultado: { ...res, _pedido: corpo } });
    } catch (e) {
      mudar({ resultado: { ok: false, error: (e as Error).message, _pedido: corpo } });
    } finally {
      setIndo(false);
      ir('/implantar/onu/pronta', { replace: true });
    }
  }

  return (
    <>
      <Voltar para="/implantar/onu" rot="Escolher ONU" />
      <div>
        <h1 className="titulo-tela">Configurar ONU</h1>
        <p className="sub-tela mono">{[serial, r.onu?.model].filter(Boolean).join(' · ')}</p>
      </div>
      <Passos n={2} />

      {!vsol ? (
        <div className="campo">
          <label htmlFor="desc">Onde ela fica (vira o nome no Zabbix)</label>
          <div className="caixa"><input id="desc" value={r.descricao} onChange={(e) => mudar({ descricao: e.target.value })} placeholder="Ex.: Apto 304 · Bloco B" maxLength={60} /></div>
        </div>
      ) : null}

      {epon ? (
        <div className="campo"><span className="lb">VLAN na porta da ONU</span>
          <div className="seg">
            <button type="button" aria-pressed={r.vlanModeEpon === 'tag'} onClick={() => mudar({ vlanModeEpon: 'tag' })}>Tag · VLAN fixa</button>
            <button type="button" aria-pressed={r.vlanModeEpon === 'transparent'} onClick={() => mudar({ vlanModeEpon: 'transparent' })}>Transparente</button>
          </div></div>
      ) : null}

      {precisaVlan ? (
        <div className={epon ? 'duas' : ''}>
          <div className="campo">
            <label htmlFor="vlan">VLAN</label>
            <div className="caixa"><input id="vlan" className="mono" inputMode="numeric" value={r.vlan} onChange={(e) => mudar({ vlan: e.target.value.replace(/\D/g, '') })} placeholder="100" /></div>
            {padrao ? <span className="ajuda">Última usada nesta OLT: {padrao}</span> : null}
          </div>
          {epon ? (
            <div className="campo"><label htmlFor="porta">Porta da ONU</label>
              <div className="caixa"><input id="porta" className="mono" inputMode="numeric" value={r.portaEpon} onChange={(e) => mudar({ portaEpon: e.target.value.replace(/\D/g, '') })} /></div></div>
          ) : null}
        </div>
      ) : null}

      {!epon && !vsol ? (
        <details className="avancado">
          <summary>Serviço, modo VLAN e tipo</summary>
          <div className="form-cartao">
            <div className="campo"><label htmlFor="serv">Serviço</label>
              <select id="serv" className="caixa-sel" value={r.servico} onChange={(e) => mudar({ servico: e.target.value as Servico })}>
                {SERVICOS.map(([v, n]) => <option key={v} value={v}>{n}</option>)}
              </select></div>
            <div className="campo"><span className="lb">Modo VLAN</span>
              <div className="seg">
                <button type="button" aria-pressed={r.tagMode === 'tagged'} onClick={() => mudar({ tagMode: 'tagged' })}>Tagged</button>
                <button type="button" aria-pressed={r.tagMode === 'untagged'} onClick={() => mudar({ tagMode: 'untagged' })}>Untagged</button>
              </div></div>
            <div className="campo"><span className="lb">Tipo</span>
              <div className="seg">
                <button type="button" aria-pressed={r.terminal === 'onu'} onClick={() => mudar({ terminal: 'onu' })}>ONU</button>
                <button type="button" aria-pressed={r.terminal === 'ont'} onClick={() => mudar({ terminal: 'ont' })}>ONT</button>
              </div></div>
          </div>
        </details>
      ) : null}

      <Cartao>
        <div className="ficha">
          <div className="ficha-linha"><span className="ficha-rot">OLT</span><span className="ficha-val">{olt.name || ipDaOlt(olt)}</span></div>
          <div className="ficha-linha"><span className="ficha-rot">Posição</span><span className="ficha-val mono">PON {pon} · posição a OLT escolhe</span></div>
          {precisaVlan ? <div className="ficha-linha"><span className="ficha-rot">Serviço</span><span className="ficha-val">{epon ? `porta ${r.portaEpon || 1} · VLAN ${r.vlan || '—'}` : `${SERVICOS.find((s) => s[0] === r.servico)?.[1]} · VLAN ${r.vlan || '—'} · ${r.tagMode}`}</span></div> : null}
          <div className="ficha-linha"><span className="ficha-rot">Monitoramento</span><span className="ficha-val">entra no Zabbix na próxima leitura da OLT</span></div>
        </div>
      </Cartao>

      <div className="aviso ambar">{Icone.aviso}
        <span>Isto autoriza a ONU <b>agora</b>, direto na OLT. Se o sinal cair no meio, nada fica na fila: a tela diz o que chegou.</span>
      </div>
      {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}

      <button type="button" className={`btn${armado ? ' armado' : ''}`} disabled={indo || !online} onClick={autorizar}>
        {indo ? 'Autorizando na OLT…' : armado ? <>{Icone.aviso}Toque de novo para autorizar</> : <>{Icone.ok}Autorizar na OLT</>}
      </button>
      {!online ? <p className="sub-tela" style={{ textAlign: 'center' }}>Sem sinal agora: o comando precisa chegar à OLT na hora.</p> : null}
    </>
  );
}

/* 4 · Ativar ONU — pronta (ou o que falhou) */
export function OnuPronta() {
  const { site } = useOltsDoSite();
  const { r, mudar, zerar } = useRascunhoOnu();
  const onus = useEntidades('onu');
  const qc = useQueryClient();
  const ir = useNavigate();
  const [indo, setIndo] = useState(false);
  const res = r.resultado;

  useEffect(() => { void qc.invalidateQueries({ queryKey: ['acoes'] }); }, [qc]);

  const posicao = res ? (res.slot ?? res.onu ?? res.onu_id) : undefined;
  const ponFinal = res ? (res.pon ?? r.onu?.pon ?? r.ponManual) : undefined;
  const ent = useMemo(() => (onus.data ?? []).find((e) => {
    const p = partesOnu(e.entity_key);
    return p.oltIp === ipDaOlt(r.olt) && String(p.pon) === String(ponFinal) && String(p.onu) === String(posicao);
  }), [onus.data, r.olt, ponFinal, posicao]);

  if (!res || !r.olt) return <Cartao><Vazio>Nada autorizado ainda.<br /><button type="button" className="link" onClick={() => ir('/implantar/onu')}>Ativar ONU</button></Vazio></Cartao>;

  const ok = res.ok !== false;
  const podeBridge = !ok && Number.isInteger(res.slot as number);
  const avisos = ((res.avisos as string[] | undefined) ?? []).filter(Boolean);

  async function tentarBridge() {
    const pedido = (res!._pedido ?? {}) as Record<string, unknown>;
    setIndo(true);
    try {
      const novo = await enviar<Record<string, unknown> & { ok?: boolean }>('/api/olt/add-onu-bridge', {
        ...baseOlt(r.olt!, site), pon: res!.pon ?? pedido.pon, onu: res!.slot,
        service: pedido.service, vlan: pedido.vlan, services: pedido.services, tag_mode: pedido.tag_mode, terminal: pedido.terminal,
      });
      mudar({
        resultado: novo.ok !== false
          ? { ...novo, ok: true, _pedido: pedido }
          : { ...res!, error: novo.error ?? novo.detail ?? 'a OLT recusou de novo', failed_at: novo.failed_at ?? res!.failed_at },
      });
    } catch (e) {
      mudar({ resultado: { ...res!, error: (e as Error).message } });
    } finally {
      setIndo(false);
    }
  }

  return (
    <>
      <Passos n={3} />
      <div className="cabeca-resultado">
        <span className={`marca-grande ${ok ? 'ok' : 'falhou'}`}>{ok ? Icone.ok : Icone.aviso}</span>
        <h1 className="titulo-tela">{ok ? 'ONU autorizada' : podeBridge ? 'Autorizada, mas sem serviço' : 'Não autorizou'}</h1>
        <p className="sub-tela mono">{[r.onu ? serialDa(r.onu) : r.macManual, r.descricao].filter(Boolean).join(' · ')}</p>
      </div>

      <Cartao>
        <div className="ficha">
          <div className="ficha-linha"><span className="ficha-rot">OLT</span><span className="ficha-val">{r.olt.name || ipDaOlt(r.olt)}</span></div>
          <div className="ficha-linha"><span className="ficha-rot">Posição</span><span className="ficha-val mono">{ponFinal ? `PON ${ponFinal}` : '—'}{posicao !== undefined && posicao !== null ? ` · ONU ${posicao}` : ''}</span></div>
          {ok ? (
            <div className="ficha-linha"><span className="ficha-rot">Zabbix</span><span className="ficha-val">
              {ent ? <span className="selo verde">no Zabbix</span> : 'aparece na próxima leitura da OLT (alguns minutos)'}
            </span></div>
          ) : (
            <>
              {res.failed_at ? <div className="ficha-linha"><span className="ficha-rot">Parou em</span><span className="ficha-val mono">{String(res.failed_at)}</span></div> : null}
              <div className="ficha-linha"><span className="ficha-rot">Erro</span><span className="ficha-val">{String(res.error || res.detail || 'a OLT recusou')}</span></div>
            </>
          )}
        </div>
      </Cartao>

      {avisos.length ? <div className="aviso ambar">{Icone.aviso}<span>{avisos.join(' ')}</span></div> : null}
      {podeBridge ? (
        <>
          <div className="aviso ambar">{Icone.aviso}<span>A ONU já foi autorizada na OLT; só falta o serviço/VLAN. Dá para tentar só essa parte, sem autorizar de novo.</span></div>
          <button type="button" className="btn" disabled={indo} onClick={tentarBridge}>{indo ? 'Aplicando na OLT…' : 'Tentar aplicar serviço/VLAN de novo'}</button>
        </>
      ) : null}

      <div className="pe-fixo">
        {ok && ent ? <button type="button" className="btn2" onClick={() => ir(`/onu/${encodeURIComponent(ent.entity_key)}`)}>{Icone.onu}Consultar esta ONU</button> : null}
        <button type="button" className={ok ? 'btn' : 'btn2'} onClick={() => { zerar({ olt: r.olt, vlan: r.vlan }); ir('/implantar/onu', { replace: true }); }}>Ativar outra ONU</button>
        <button type="button" className="btn2" onClick={() => ir('/implantar', { replace: true })}>Voltar a Implantar</button>
      </div>
    </>
  );
}
