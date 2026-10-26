import { useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { detalhe, ipDaOlt, mesmoSite, siteDoConector, useConectores, useOlts, type Entidade } from '../lib/dados';
import { nomeEntidade, partesOnu, rxDa, sinalBaixo, useSiteMonitor } from '../lib/monitor';
import { rompimentos } from '../lib/rompimento';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio } from '../ui/pecas';
import { situacaoDoStatus, useFiltro, type Situacao } from '../ui/Filtros';
import { sitCamera, useCamerasDoSite } from '../screens/Cameras';

type Familia = 'rede' | 'cftv' | 'acesso';
type Pon = { pon: string; total: number; up: number; down: number; baixo: number };
const localDe = (site?: string | null) => String(site ?? '').trim().toUpperCase();

const dbm = (v: number) => `${v.toFixed(1).replace('.', ',').replace('-', '−')} dBm`;

/* Equipamentos do site em tres familias, como no menu da web. */
export function Equipamentos() {
  const [param, setParam] = useSearchParams();
  const f = (param.get('f') as Familia) || 'rede';
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const trocar = (x: Familia) => setParam({ f: x }, { replace: true });

  return (
    <>
      <div className="seg-familia" role="tablist" aria-label="Família">
        {([['rede', 'Rede'], ['cftv', 'CFTV'], ['acesso', 'Acesso']] as [Familia, string][]).map(([k, n]) => (
          <button key={k} type="button" role="tab" aria-selected={f === k} onClick={() => trocar(k)}>{n}</button>
        ))}
      </div>
      {m.carregando ? <Carregando /> : f === 'rede' ? <Rede /> : f === 'cftv' ? <Cftv /> : <Acesso />}
    </>
  );
}

/* Rede: o caminho do sinal de cima para baixo -- conector, OLT e PONs, switches. */
function Rede() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const cons = useConectores();
  const olts = useOlts();
  const ir = useNavigate();

  const porOlt = useMemo(() => {
    const mapa = new Map<string, Map<string, Pon>>();
    for (const e of m.onus) {
      const { oltIp, pon } = partesOnu(e.entity_key);
      if (!mapa.has(oltIp)) mapa.set(oltIp, new Map());
      const pons = mapa.get(oltIp)!;
      const p = pons.get(pon) ?? { pon, total: 0, up: 0, down: 0, baixo: 0 };
      p.total += 1;
      if (e.status === 'up') p.up += 1; else p.down += 1;
      if (sinalBaixo(e)) p.baixo += 1;
      pons.set(pon, p);
    }
    return mapa;
  }, [m.onus]);
  const roms = rompimentos(m.onus);

  const conectores = (cons.data ?? []).filter((c) => !site || mesmoSite(siteDoConector(c), site));
  const oltsDoSite = (olts.data ?? []).filter((o) => porOlt.has(ipDaOlt(o)) || (site && mesmoSite(o.site, site)));
  const semCadastro = [...porOlt.keys()].filter((ip) => !oltsDoSite.some((o) => ipDaOlt(o) === ip));

  // Um no por equipamento, para uma barra de filtro so na tela inteira.
  type No = { tipo: 'Conector' | 'OLT' | 'Switch'; chave: string; nome: string; ip: string; local: string; sit: Situacao };
  const sitOlt = (ip: string): Situacao => {
    const ent = m.olts.find((e) => detalhe<{ host?: string }>(e).host === ip);
    if (ent?.status === 'down') return 'fora';
    const pons = [...(porOlt.get(ip)?.values() ?? [])];
    return pons.some((p) => p.down || p.baixo) ? 'atencao' : 'ok';
  };
  const nos: No[] = [
    ...conectores.map((c) => ({ tipo: 'Conector' as const, chave: `c:${c.id}`, nome: c.name || siteDoConector(c), ip: '', local: localDe(siteDoConector(c)), sit: (c.online ? 'ok' : 'fora') as Situacao })),
    ...oltsDoSite.map((o) => ({ tipo: 'OLT' as const, chave: `o:${ipDaOlt(o)}`, nome: o.name || ipDaOlt(o), ip: ipDaOlt(o), local: localDe(o.site), sit: sitOlt(ipDaOlt(o)) })),
    ...semCadastro.map((ip) => ({ tipo: 'OLT' as const, chave: `o:${ip}`, nome: `OLT ${ip}`, ip, local: '', sit: sitOlt(ip) })),
    ...m.switches.map((e) => ({ tipo: 'Switch' as const, chave: `s:${e.entity_key}`, nome: nomeEntidade(e), ip: String(detalhe<{ ip?: string }>(e).ip ?? ''), local: localDe(e.site), sit: situacaoDoStatus(e.status) })),
  ];
  const { lista: vistos, barra, ativo } = useFiltro(nos, {
    texto: (n) => [n.nome, n.ip], local: (n) => n.local, situacao: (n) => n.sit, dica: 'Nome ou IP',
    nomes: { atencao: 'ONU com problema' }, extra: { rotulo: 'Tipo', todos: 'Todos os tipos', de: (n) => n.tipo },
  });
  const ve = new Set(vistos.map((n) => n.chave));

  function mediaRx(ip: string): string {
    const l = m.onus.filter((e) => partesOnu(e.entity_key).oltIp === ip).map(rxDa).filter((v): v is number => v !== null);
    return l.length ? `média ${dbm(l.reduce((a, b) => a + b, 0) / l.length)}` : '';
  }

  function cartaoOlt(ip: string, nome: string, sub: string) {
    const pons = [...(porOlt.get(ip)?.values() ?? [])].sort((a, b) => a.pon.localeCompare(b.pon, 'pt-BR', { numeric: true }));
    const maior = Math.max(1, ...pons.map((p) => p.total));
    const total = pons.reduce((a, p) => a + p.total, 0);
    return (
      <Cartao key={ip || nome}>
        <div className="item">
          <span className="fam-ic rede">{Icone.olt}</span>
          <span className="corpo"><span className="s rot-mini">OLT</span><span className="t">{nome}</span></span>
          <span className="mono" style={{ fontSize: 13, color: 'var(--muted)' }}>{total} ONUs</span>
        </div>
        {sub ? <p className="sub-h2" style={{ marginTop: 0 }}>{sub}</p> : null}
        {!pons.length ? <Vazio>Nenhuma ONU deste site nesta OLT.</Vazio> : pons.map((p) => {
          const rom = roms.some((r) => r.oltIp === ip && r.pon === p.pon);
          return (
            <button key={p.pon} type="button" className={`item pon-linha${p.baixo || p.down ? ' com-problema' : ''}`}
                    onClick={() => ir(`/pon?olt=${encodeURIComponent(ip)}&pon=${encodeURIComponent(p.pon)}`)}>
              <span className="pon mono">{p.pon}</span>
              <span className="corpo">
                <span className="barra-pon" aria-hidden="true">
                  <span style={{ width: `${(100 * (p.up - p.baixo)) / maior}%`, background: 'var(--primary)' }} />
                  <span style={{ width: `${(100 * p.baixo) / maior}%`, background: 'var(--amber)' }} />
                  <span style={{ width: `${(100 * p.down) / maior}%`, background: 'var(--danger)' }} />
                </span>
              </span>
              {p.down ? <b className="pon-fora">{rom ? 'rompimento?' : `${p.down} fora`}</b>
                : p.baixo ? <b className="pon-baixo">{p.baixo} baixo</b>
                  : <span className="mono pon-n">{p.total}</span>}
              {Icone.seta}
            </button>
          );
        })}
      </Cartao>
    );
  }

  return (
    <>
      <p className="sub-tela">O caminho do sinal, de cima para baixo.</p>
      {barra}
      {ativo && !vistos.length ? <Cartao><Vazio>Nada com esse filtro.</Vazio></Cartao> : null}

      {ativo && !conectores.some((c) => ve.has(`c:${c.id}`)) ? null : (
      <Cartao>
        {!conectores.length ? <Vazio>Nenhum conector neste site.</Vazio> : conectores.filter((c) => ve.has(`c:${c.id}`)).map((c, i) => {
          const ent: Entidade | undefined = m.conectores.find((e) => e.connector_id === c.id) ?? m.conectores[i];
          return (
            <div key={c.id ?? i} className="item">
              <span className="fam-ic ok">{Icone.conector}</span>
              <span className="corpo"><span className="s rot-mini">Conector</span><span className="t">{c.name || siteDoConector(c)}</span></span>
              <span className={`selo ${c.online ? 'verde' : 'vermelho'}`}>
                {c.online ? 'online' : 'fora'}{ent?.last_changed_at ? ` ${desde(ent.last_changed_at)}` : ''}
              </span>
            </div>
          );
        })}
      </Cartao>
      )}

      <div className="ramo">
        {olts.isPending && !olts.data ? <Carregando /> : null}
        {oltsDoSite.filter((o) => ve.has(`o:${ipDaOlt(o)}`)).map((o) => cartaoOlt(ipDaOlt(o), o.name || ipDaOlt(o) || 'OLT',
          [o.capability_label || [o.vendor, o.model].filter(Boolean).join(' '), mediaRx(ipDaOlt(o))].filter(Boolean).join(' · ')))}
        {semCadastro.filter((ip) => ve.has(`o:${ip}`)).map((ip) => cartaoOlt(ip, `OLT ${ip}`, 'OLT sem cadastro no SightOps'))}

        {ativo && !m.switches.some((x) => ve.has(`s:${x.entity_key}`)) ? null : (
        <Cartao>
          <h2>Switches{m.switches.length ? ` · ${m.switches.length}` : ''}</h2>
          {!m.switches.length ? <Vazio>Nenhum switch monitorado neste site.</Vazio> : m.switches.filter((x) => ve.has(`s:${x.entity_key}`)).map((s) => {
            const d = detalhe<{ ip?: string; model?: string; modelo?: string; ports_total?: number; ports_up?: number }>(s);
            return (
              <Item key={s.entity_key} icone={Icone.switch} titulo={nomeEntidade(s)}
                    sub={[d.model || d.modelo, d.ports_total ? `${d.ports_up ?? 0}/${d.ports_total} portas ligadas` : ''].filter(Boolean).join(' · ')}
                    onClick={() => ir(`/switch/${encodeURIComponent(s.entity_key)}`)}
                    direita={s.status === 'up' ? Icone.seta : <span className="selo vermelho">fora</span>} />
            );
          })}
        </Cartao>
        )}
      </div>
    </>
  );
}

/* CFTV: gravadores e o que esta sem video. */
function Cftv() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const ir = useNavigate();
  // Numeros de camera da MESMA fonte e regra da tela Cameras (inventario):
  // o que esta escrito aqui e o que aparece ao abrir.
  const { cameras } = useCamerasDoSite();
  const fora = cameras.filter((c) => sitCamera(c) === 'fora').length;
  const semLeitura = cameras.filter((c) => sitCamera(c) === 'atencao').length;
  const noAr = cameras.length - fora - semLeitura;

  const sitNvr = (e: Entidade): Situacao => {
    const d = detalhe<{ canais_sem_imagem?: number; canais_offline?: number }>(e);
    return e.status !== 'up' ? 'fora' : Number(d.canais_sem_imagem ?? 0) + Number(d.canais_offline ?? 0) ? 'atencao' : 'ok';
  };
  const { lista: nvrs, barra } = useFiltro(m.nvrs, {
    texto: (e) => [nomeEntidade(e), detalhe<{ host?: string }>(e).host], dica: 'Gravador: nome ou IP', unidade: 'gravadores',
    local: (e) => localDe(e.site), situacao: sitNvr, nomes: { atencao: 'Com canal sem vídeo', ok: 'Tudo ok' },
  });

  return (
    <>
      <Cartao>
        <button type="button" className="item" onClick={() => ir('/cameras')}>
          <span className="fam-ic cftv">{Icone.camera}</span>
          <span className="corpo"><span className="t">Câmeras · {cameras.length}</span>
            <span className="s">{noAr} no ar{fora ? ` · ${fora} fora do ar` : ''}{semLeitura ? ` · ${semLeitura} sem leitura` : ''}</span></span>
          {Icone.seta}
        </button>
        {fora ? (
          <button type="button" className="item" onClick={() => ir('/cameras?sit=fora')}>
            <span className="ponto" style={{ background: 'var(--danger)' }} />
            <span className="corpo"><span className="t">Ver as {fora} fora do ar</span><span className="s">com filtro de local e gravador</span></span>
            {Icone.seta}
          </button>
        ) : null}
      </Cartao>

      <span className="rot-secao">Gravadores · {m.nvrs.length}</span>
      {barra}
      <Cartao>
        {!m.nvrs.length ? <Vazio>Nenhum gravador neste site.</Vazio> : !nvrs.length ? <Vazio>Nenhum gravador com esse filtro.</Vazio> : nvrs.map((e) => {
          const d = detalhe<{ host?: string; canais_sem_imagem?: number; canais_offline?: number; canais_total?: number }>(e);
          const sem = Number(d.canais_sem_imagem ?? 0) + Number(d.canais_offline ?? 0);
          return (
            <Item key={e.entity_key} ponto={e.status !== 'up' ? 'vermelho' : sem ? 'ambar' : 'verde'} titulo={nomeEntidade(e)}
                  sub={[d.host, e.status !== 'up' ? 'fora do ar' : sem ? `${sem} canais sem vídeo` : 'todos os canais com vídeo'].filter(Boolean).join(' · ')}
                  onClick={d.host ? () => ir(`/implantar/gravador/${encodeURIComponent(d.host!)}`) : undefined}
                  direita={d.host ? Icone.seta : undefined} />
          );
        })}
      </Cartao>
    </>
  );
}

/* Acesso: leitores e portoes do site. */
function Acesso() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const { lista, barra } = useFiltro(m.acessos, {
    texto: (e) => [nomeEntidade(e), detalhe<{ host?: string }>(e).host, detalhe<{ model?: string }>(e).model],
    local: (e) => localDe(e.site), situacao: (e) => situacaoDoStatus(e.status), dica: 'Nome, IP ou modelo',
  });
  return (
    <>
    {barra}
    <Cartao>
      <h2>Leitores{m.acessos.length ? ` · ${lista.length}${lista.length !== m.acessos.length ? ` de ${m.acessos.length}` : ''}` : ''}</h2>
      {!m.acessos.length ? <Vazio>Nenhum leitor de acesso neste site.</Vazio> : !lista.length ? <Vazio>Nada com esse filtro.</Vazio> : lista.map((e) => {
        const d = detalhe<{ host?: string; model?: string; last_seen_at?: string }>(e);
        return (
          <Item key={e.entity_key} ponto={e.status === 'up' ? 'verde' : 'vermelho'} titulo={nomeEntidade(e)}
                sub={[d.model, d.host, e.status !== 'up' && d.last_seen_at ? `visto ${desde(d.last_seen_at)}` : ''].filter(Boolean).join(' · ')} />
        );
      })}
    </Cartao>
    </>
  );
}
