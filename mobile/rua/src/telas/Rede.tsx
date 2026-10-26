import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ipDaOlt, siteDoConector, mesmoSite, useConectores, useOlts, type Entidade } from '../lib/dados';
import { partesOnu, rxDa, sinalBaixo, useSiteMonitor } from '../lib/monitor';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio } from '../ui/pecas';

type Pon = { pon: string; total: number; up: number; down: number; baixo: number; nomesBaixo: string[] };

/* 15 · Rede — conector e OLT: o caminho ate cada equipamento do site. */
export function Rede() {
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const cons = useConectores();
  const olts = useOlts();
  const ir = useNavigate();
  const [busca, setBusca] = useState('');

  // ONUs do site agrupadas por OLT (ip) e PON.
  const porOlt = useMemo(() => {
    const mapa = new Map<string, Map<string, Pon>>();
    for (const e of m.onus) {
      const { oltIp, pon } = partesOnu(e.entity_key);
      if (!mapa.has(oltIp)) mapa.set(oltIp, new Map());
      const pons = mapa.get(oltIp)!;
      const p = pons.get(pon) ?? { pon, total: 0, up: 0, down: 0, baixo: 0, nomesBaixo: [] };
      p.total += 1;
      if (e.status === 'up') p.up += 1; else p.down += 1;
      if (sinalBaixo(e)) { p.baixo += 1; p.nomesBaixo.push(String(e.display_name ?? '')); }
      pons.set(pon, p);
    }
    return mapa;
  }, [m.onus]);

  const conectores = (cons.data ?? []).filter((c) => !site || mesmoSite(siteDoConector(c), site));
  const oltsDoSite = (olts.data ?? []).filter((o) => porOlt.has(ipDaOlt(o)) || (site && mesmoSite(o.site, site)));
  const semCadastro = [...porOlt.keys()].filter((ip) => !oltsDoSite.some((o) => ipDaOlt(o) === ip));

  function buscar(ev: FormEvent) {
    ev.preventDefault();
    if (busca.trim()) ir(`/onu?q=${encodeURIComponent(busca.trim())}`);
  }

  function mediaRx(ip: string): string {
    const l = m.onus.filter((e) => partesOnu(e.entity_key).oltIp === ip).map(rxDa).filter((v): v is number => v !== null);
    if (!l.length) return '';
    return `sinal médio ${(l.reduce((a, b) => a + b, 0) / l.length).toFixed(1).replace('.', ',').replace('-', '−')} dBm`;
  }

  function cartaoOlt(ip: string, nome: string, sub: string, estado?: string) {
    const pons = [...(porOlt.get(ip)?.values() ?? [])].sort((a, b) => a.pon.localeCompare(b.pon, 'pt-BR', { numeric: true }));
    const maior = Math.max(1, ...pons.map((p) => p.total));
    const on = estado === 'up' || estado === 'ok' || estado === 'online';
    return (
      <Cartao key={ip || nome}>
        <h2 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {nome}
          {estado ? <span className={`selo ${on ? 'verde' : 'ambar'}`}>{on ? 'online' : estado === 'unknown' ? 'sem leitura' : 'fora'}</span> : null}
        </h2>
        <p className="sub-h2">{sub}</p>
        {!pons.length ? <Vazio>Nenhuma ONU deste site nesta OLT.</Vazio> : pons.map((p) => (
          <button key={p.pon} type="button" className="item pon-linha" onClick={() => ir(`/onu?olt=${encodeURIComponent(ip)}&pon=${encodeURIComponent(p.pon)}`)}
                  style={p.baixo || p.down ? { background: '#fffbf0' } : undefined}>
            <span className="pon mono">{p.pon}</span>
            <span className="corpo">
              <span className="barra-pon" aria-hidden="true">
                <span style={{ width: `${(100 * (p.up - p.baixo)) / maior}%`, background: 'var(--primary)' }} />
                <span style={{ width: `${(100 * p.baixo) / maior}%`, background: 'var(--amber)' }} />
                <span style={{ width: `${(100 * p.down) / maior}%`, background: 'var(--danger)' }} />
              </span>
              {p.baixo || p.down ? (
                <span className="s" style={{ color: 'var(--amber-txt)', fontWeight: 600 }}>
                  {[p.down ? `${p.down} fora` : '', p.baixo ? `${p.baixo} sinal baixo${p.baixo === 1 ? ` · ${p.nomesBaixo[0]}` : ''}` : ''].filter(Boolean).join(' · ')}
                </span>
              ) : null}
            </span>
            <span className="mono" style={{ fontSize: 12.5 }}>{p.total} ONUs</span>
            {Icone.seta}
          </button>
        ))}
      </Cartao>
    );
  }

  if (m.carregando) return <Carregando />;

  return (
    <>
      <div>
        <h1 className="titulo-tela">Rede</h1>
        <p className="sub-tela">O caminho até cada equipamento do site</p>
      </div>

      <form className="busca" onSubmit={buscar}>
        {Icone.busca}
        <input type="search" value={busca} onChange={(e) => setBusca(e.target.value)} enterKeyHint="search"
               placeholder="Consultar ONU por serial ou nome" aria-label="Consultar ONU por serial ou nome"
               autoCapitalize="none" spellCheck={false} />
      </form>

      <Cartao>
        {!conectores.length ? <Vazio>Nenhum conector neste site.</Vazio> : conectores.map((c, i) => {
          const ent: Entidade | undefined = m.conectores.find((e) => e.connector_id === c.id) ?? m.conectores[i];
          return (
            <Item key={c.id ?? i} icone={Icone.rede} titulo={c.name || siteDoConector(c)}
                  sub={ent?.last_changed_at ? `${c.online ? 'online' : 'fora'} ${desde(ent.last_changed_at)}` : undefined}
                  direita={<span className={`selo ${c.online ? 'verde' : 'ambar'}`}>{c.online ? 'online' : 'sem sinal'}</span>} />
          );
        })}
      </Cartao>

      {olts.isPending && !olts.data ? <Carregando /> : null}
      {oltsDoSite.map((o) => cartaoOlt(ipDaOlt(o), o.name || ipDaOlt(o) || 'OLT',
        [o.capability_label || [o.vendor, o.model].filter(Boolean).join(' '), `${(porOlt.get(ipDaOlt(o)) ? [...porOlt.get(ipDaOlt(o))!.values()].reduce((a, p) => a + p.total, 0) : 0)} ONUs`, mediaRx(ipDaOlt(o))].filter(Boolean).join(' · '),
        o.status || o.last_test_status))}
      {semCadastro.map((ip) => cartaoOlt(ip, `OLT ${ip}`, 'OLT sem cadastro no SightOps'))}

      {m.switches.length ? (
        <Cartao>
          <h2>Switches</h2>
          {m.switches.map((s) => (
            <Item key={s.entity_key} icone={Icone.switch} titulo={String(s.display_name ?? s.entity_key)}
                  direita={<span className={`selo ${s.status === 'up' ? 'verde' : 'ambar'}`}>{s.status === 'up' ? 'online' : 'fora'}</span>} />
          ))}
        </Cartao>
      ) : null}
    </>
  );
}
