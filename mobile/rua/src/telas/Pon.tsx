import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { detalhe } from '../lib/dados';
import { nomeEntidade, num, partesOnu, rxDa, sinalBaixo, useSiteMonitor, type DetalheOnu } from '../lib/monitor';
import { horaDe, rompimentos } from '../lib/rompimento';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio } from '../ui/pecas';

type Filtro = 'todas' | 'fora' | 'baixo';
const dbm = (v: number | null) => (v === null ? '—' : v.toFixed(1).replace('.', ',').replace('-', '−'));

/* OLT > PON: as ONUs de uma PON, problema primeiro. */
export function Pon() {
  const [param] = useSearchParams();
  const olt = param.get('olt') ?? '';
  const pon = param.get('pon') ?? '';
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const ir = useNavigate();
  const [filtro, setFiltro] = useState<Filtro>('todas');

  const todas = useMemo(() => m.onus.filter((e) => {
    const p = partesOnu(e.entity_key);
    return p.oltIp === olt && p.pon === pon;
  }).sort((a, b) => {
    const pa = a.status !== 'up' ? 0 : sinalBaixo(a) ? 1 : 2;
    const pb = b.status !== 'up' ? 0 : sinalBaixo(b) ? 1 : 2;
    return pa - pb || String(a.display_name).localeCompare(String(b.display_name), 'pt-BR', { numeric: true });
  }), [m.onus, olt, pon]);

  if (m.carregando) return <Carregando />;

  const fora = todas.filter((e) => e.status !== 'up');
  const baixo = todas.filter(sinalBaixo);
  const rxs = todas.map(rxDa).filter((v): v is number => v !== null);
  const media = rxs.length ? rxs.reduce((a, b) => a + b, 0) / rxs.length : null;
  const rom = rompimentos(todas)[0];
  const nomeOlt = m.olts.find((o) => String(detalhe<{ host?: string }>(o).host ?? '') === olt);
  const lista = filtro === 'fora' ? fora : filtro === 'baixo' ? baixo : todas;

  return (
    <>
      <div className="linha-topo">
        <button type="button" className="voltar" onClick={() => ir(-1)} aria-label="Voltar">{Icone.volta}</button>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p className="sub-tela" style={{ margin: 0 }}>{nomeOlt ? nomeEntidade(nomeOlt) : `OLT ${olt}`}</p>
          <h1 className="titulo-tela">PON <span className="mono">{pon}</span></h1>
        </div>
        {fora.length ? <span className="selo vermelho">{fora.length} fora</span> : <span className="selo verde">tudo no ar</span>}
      </div>

      <div className="numeros-3">
        <div><span>ONUs</span><b>{todas.length}</b></div>
        <div><span>Sinal médio</span><b className="mono">{dbm(media)}</b></div>
        <div><span>Sinal baixo</span><b>{baixo.length}</b></div>
      </div>

      {rom ? (
        <div className="cartao-rompimento estatico">
          <span className="rot-rompimento">{Icone.triangulo}Provável rompimento</span>
          <b>As {rom.onus.length} caíram juntas às {horaDe(rom.quando)}</b>
          <span className="s">{rom.los ? 'Motivo LOS (perda de sinal). ' : ''}Procure no trecho de fibra ou splitter que elas têm em comum.</span>
        </div>
      ) : null}

      <div className="abas" role="group" aria-label="Mostrar">
        <button type="button" className="aba" aria-pressed={filtro === 'todas'} onClick={() => setFiltro('todas')}>Todas {todas.length}</button>
        <button type="button" className="aba" aria-pressed={filtro === 'fora'} onClick={() => setFiltro('fora')}>Fora {fora.length}</button>
        <button type="button" className="aba" aria-pressed={filtro === 'baixo'} onClick={() => setFiltro('baixo')}>Sinal baixo {baixo.length}</button>
      </div>

      <Cartao>
        {!lista.length ? <Vazio>Nenhuma ONU aqui.</Vazio> : lista.slice(0, 200).map((e) => {
          const d = detalhe<DetalheOnu>(e);
          const rx = rxDa(e);
          const dist = num(d.distance_km);
          return (
            <Item key={e.entity_key} ponto={e.status !== 'up' ? 'vermelho' : sinalBaixo(e) ? 'ambar' : 'verde'}
                  titulo={`${nomeEntidade(e)} · ONU ${partesOnu(e.entity_key).onu}`}
                  sub={e.status !== 'up'
                    ? [d.offline_reason || 'fora do ar', e.last_changed_at ? desde(e.last_changed_at) : ''].filter(Boolean).join(' · ')
                    : [d.serial, dist !== null ? `${dist.toFixed(1).replace('.', ',')} km` : ''].filter(Boolean).join(' · ')}
                  onClick={() => ir(`/onu/${encodeURIComponent(e.entity_key)}`)}
                  direita={e.status !== 'up' ? <b className="pon-fora">fora</b>
                    : <span className={`mono ${sinalBaixo(e) ? 'pon-baixo' : 'pon-n'}`}>{dbm(rx)}</span>} />
          );
        })}
      </Cartao>
    </>
  );
}
