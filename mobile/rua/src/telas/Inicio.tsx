import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { chaveDa, detalhe, mesmoSite, siteDa, useCameras, type Entidade } from '../lib/dados';
import {
  TIPO_NOME, horaCurta, nomeEntidade, rxDa, sinalBaixo, useSiteMonitor, type DetalheCamera, type DetalheOnu,
} from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Procedencia, Vazio, useToast } from '../ui/pecas';
import { useLeitorEtiqueta } from '../ui/LerEtiqueta';
import { horaDe, rompimentos } from '../lib/rompimento';

const fmtRx = (v: number | null) => (v === null ? '' : `${v.toFixed(1).replace('.', ',').replace('-', '−')} dBm`);

/** Para onde vai o toque numa entidade: ONU abre a consulta; camera, a ficha. */
export function useAbrirEntidade() {
  const ir = useNavigate();
  const cams = useCameras();
  return (e: Entidade) => {
    if (e.entity_type === 'onu') { ir(`/onu/${encodeURIComponent(e.entity_key)}`); return; }
    if (e.entity_type === 'camera') {
      const ip = detalhe<DetalheCamera>(e).ip;
      const c = (cams.data ?? []).find((x) => x.ip === ip && (!e.site || mesmoSite(siteDa(x), e.site)))
        ?? (cams.data ?? []).find((x) => x.ip === ip);
      if (c) { ir(`/cameras/${chaveDa(c)}`); return; }
      ir(`/cameras?q=${encodeURIComponent(ip ?? nomeEntidade(e))}`);
      return;
    }
    if (e.entity_type === 'switch' || e.entity_type === 'switch_provedor') { ir(`/switch/${encodeURIComponent(e.entity_key)}`); return; }
    if (e.entity_type === 'nvr' || e.entity_type === 'dvr') {
      const host = String(detalhe<{ host?: string }>(e).host ?? '');
      if (host) { ir(`/implantar/gravador/${encodeURIComponent(host)}`); return; }
    }
    ir('/equipamentos?f=rede');
  };
}

export function subEntidade(e: Entidade): string {
  if (e.entity_type === 'onu') {
    const d = detalhe<DetalheOnu>(e);
    const rx = rxDa(e);
    if (e.status === 'down') return [d.offline_reason || 'fora do ar', e.last_changed_at ? `desde ${horaCurta(e.last_changed_at)}` : ''].filter(Boolean).join(' · ');
    return [rx !== null ? `RX ${fmtRx(rx)}` : '', d.pon ? `PON ${d.pon}` : ''].filter(Boolean).join(' · ');
  }
  const d = detalhe<DetalheCamera>(e);
  return [TIPO_NOME[e.entity_type] || e.entity_type, d.ip,
    e.last_changed_at ? `desde ${horaCurta(e.last_changed_at)} · ${desde(e.last_changed_at)}` : ''].filter(Boolean).join(' · ');
}

/* 13 · Inicio do site: o site por familia (Rede, CFTV, Acesso) e so o que precisa do tecnico. */
export function Inicio() {
  const online = useOnline();
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const cams = useCameras();
  const abrir = useAbrirEntidade();
  const ir = useNavigate();
  const toast = useToast();
  const [busca, setBusca] = useState('');
  const etiqueta = useLeitorEtiqueta((mac) => setBusca(mac), (msg) => toast(msg, true));

  const achados = useMemo(() => {
    const t = busca.trim().toLowerCase();
    if (t.length < 2) return [];
    const tMac = t.replace(/[^0-9a-f]/g, '');
    // MAC da etiqueta: acha a camera no inventario e cai na entidade pelo IP.
    const ipsPorMac = tMac.length >= 6
      ? new Set((cams.data ?? []).filter((c) => String(c.mac ?? '').toLowerCase().replace(/[^0-9a-f]/g, '').includes(tMac)).map((c) => c.ip))
      : new Set<string | undefined>();
    return [...m.cameras, ...m.onus, ...m.nvrs, ...m.switches, ...m.olts, ...m.acessos].filter((e) => {
      const d = detalhe<DetalheCamera & DetalheOnu & { host?: string }>(e);
      if (d.ip && ipsPorMac.has(d.ip)) return true;
      return [e.display_name, d.ip, d.serial, d.host].some((v) => String(v ?? '').toLowerCase().includes(t));
    }).slice(0, 12);
  }, [busca, m, cams.data]);

  if (m.carregando) return <Carregando />;

  const up = (l: Entidade[]) => l.filter((e) => e.status === 'up').length;
  const fora = (l: Entidade[]) => l.filter((e) => e.status === 'down').length;
  const onuBaixo = m.onus.filter(sinalBaixo).length;
  const redeFora = fora(m.onus) + fora(m.olts) + fora(m.switches) + fora(m.conectores);
  const camFora = m.cameras.filter((e) => e.status !== 'up').length + fora(m.nvrs);
  const acFora = fora(m.acessos);
  const roms = rompimentos(m.onus);
  const nomesOlt = new Map(m.olts.map((o) => [String(detalhe<{ host?: string }>(o).host ?? ''), nomeEntidade(o)]));
  // As ONUs de um rompimento ja aparecem no cartao dele: nao repetem na lista.
  const jaNoRompimento = new Set(roms.flatMap((r) => r.onus.map((e) => e.entity_key)));
  const atencao = m.atencao.filter((e) => !jaNoRompimento.has(e.entity_key));

  const selo = (n: number, txt: string, baixo = 0) => (n
    ? <span className="selo vermelho">{n} {txt}</span>
    : baixo ? <span className="selo ambar">{baixo} sinal baixo</span>
      : <span className="selo verde">tudo ok</span>);

  return (
    <>
      <label className="busca">
        {Icone.busca}
        <input type="search" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder="Câmera, ONU, serial, MAC ou IP" aria-label="Buscar câmera, ONU, serial, MAC ou IP"
               autoCapitalize="none" spellCheck={false} />
        <button type="button" className="busca-etiqueta" aria-label="Ler etiqueta com a câmera"
                disabled={!!etiqueta.estado} onClick={() => void etiqueta.ler()}>{Icone.etiqueta}</button>
      </label>
      {etiqueta.estado === 'baixando' ? <p className="sub-tela">Baixando o leitor de etiqueta (só na 1ª vez)…</p> : null}

      {busca.trim().length >= 2 ? (
        <Cartao>
          <h2>Encontrados</h2>
          {!achados.length ? <Vazio>Nada com “{busca.trim()}” neste site.</Vazio> : achados.map((e) => (
            <Item key={e.entity_key} ponto={e.status === 'up' ? (sinalBaixo(e) ? 'ambar' : 'verde') : 'vermelho'}
                  titulo={nomeEntidade(e)} sub={subEntidade(e)} onClick={() => abrir(e)} direita={Icone.seta} />
          ))}
        </Cartao>
      ) : null}

      <div className="linha-topo">
        <span style={{ fontWeight: 700, fontSize: 16, flex: 1 }}>Agora no site</span>
        <Procedencia buscando={m.buscando} atualizadoEm={m.atualizadoEm} online={online} />
      </div>

      <Cartao>
        <button type="button" className="familia" onClick={() => ir('/equipamentos?f=rede')}>
          <span className="fam-ic rede">{Icone.olt}</span>
          <span className="corpo">
            <span className="t">Rede</span>
            <span className="s">{[m.olts.length ? `${m.olts.length} OLT` : '', `${up(m.onus)}/${m.onus.length} ONUs`, m.switches.length ? `${m.switches.length} ${m.switches.length === 1 ? 'switch' : 'switches'}` : ''].filter(Boolean).join(' · ')}</span>
          </span>
          {selo(redeFora, 'fora', onuBaixo)}{Icone.seta}
        </button>
        <button type="button" className="familia" onClick={() => ir('/equipamentos?f=cftv')}>
          <span className="fam-ic cftv">{Icone.camera}</span>
          <span className="corpo">
            <span className="t">CFTV</span>
            <span className="s">{up(m.cameras)}/{m.cameras.length} câmeras · {m.nvrs.length} gravadores</span>
          </span>
          {selo(camFora, 'sem vídeo')}{Icone.seta}
        </button>
        {m.acessos.length ? (
          <button type="button" className="familia" onClick={() => ir('/equipamentos?f=acesso')}>
            <span className="fam-ic acesso">{Icone.porta}</span>
            <span className="corpo">
              <span className="t">Acesso</span>
              <span className="s">{up(m.acessos)}/{m.acessos.length} leitores</span>
            </span>
            {selo(acFora, 'fora')}{Icone.seta}
          </button>
        ) : null}
      </Cartao>

      {roms.length || atencao.length ? <h2 className="titulo-secao">Precisa de você</h2> : null}

      {roms.slice(0, 2).map((r) => (
        <button key={`${r.oltIp}|${r.pon}|${r.quando}`} type="button" className="cartao-rompimento"
                onClick={() => ir(`/pon?olt=${encodeURIComponent(r.oltIp)}&pon=${encodeURIComponent(r.pon)}`)}>
          <span className="rot-rompimento">{Icone.triangulo}Provável rompimento</span>
          <b>{r.onus.length} ONUs da PON {r.pon} caíram juntas às {horaDe(r.quando)}</b>
          <span className="s">{nomesOlt.get(r.oltIp) || `OLT ${r.oltIp}`}{r.los ? ' · perda de sinal (LOS)' : ''}. Fibra ou splitter no trecho comum.</span>
        </button>
      ))}

      {atencao.length ? (
        <Cartao>
          {atencao.slice(0, 3).map((e) => (
            <Item key={e.entity_key} ponto={e.status === 'up' ? 'ambar' : 'vermelho'}
                  titulo={e.entity_type === 'onu' && e.status === 'up' ? `${nomeEntidade(e)} · sinal baixo` : nomeEntidade(e)}
                  sub={subEntidade(e)} onClick={() => abrir(e)} direita={Icone.seta} />
          ))}
          {atencao.length > 3 ? (
            <button type="button" className="item ver-todos" onClick={() => ir('/alertas')}>Ver todos ({atencao.length})</button>
          ) : null}
        </Cartao>
      ) : !roms.length ? (
        <Cartao><Vazio>Tudo no ar neste site.</Vazio></Cartao>
      ) : null}
    </>
  );
}
