import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { chaveDa, detalhe, mesmoSite, siteDa, useCameras, type Entidade } from '../lib/dados';
import {
  TIPO_NOME, horaCurta, nomeEntidade, rxDa, sinalBaixo, useSiteMonitor, type DetalheCamera, type DetalheOnu,
} from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Procedencia, Vazio } from '../ui/pecas';

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
    ir('/rede');
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

/* 13 · Inicio do site */
export function Inicio() {
  const online = useOnline();
  const { site } = useSite();
  const m = useSiteMonitor(site);
  const abrir = useAbrirEntidade();
  const ir = useNavigate();
  const [busca, setBusca] = useState('');

  const achados = useMemo(() => {
    const t = busca.trim().toLowerCase();
    if (t.length < 2) return [];
    return [...m.cameras, ...m.onus, ...m.nvrs].filter((e) => {
      const d = detalhe<DetalheCamera & DetalheOnu>(e);
      return [e.display_name, d.ip, d.serial].some((v) => String(v ?? '').toLowerCase().includes(t));
    }).slice(0, 12);
  }, [busca, m.cameras, m.onus, m.nvrs]);

  if (m.carregando) return <Carregando />;

  const up = (l: Entidade[]) => l.filter((e) => e.status === 'up').length;
  const camDown = m.cameras.filter((e) => e.status !== 'up').length;
  const onuBaixo = m.onus.filter(sinalBaixo).length;
  const onuDown = m.onus.filter((e) => e.status === 'down').length;
  const con = m.conectores[0];

  return (
    <>
      <label className="busca">
        {Icone.busca}
        <input type="search" value={busca} onChange={(e) => setBusca(e.target.value)}
               placeholder="Câmera, ONU, serial ou IP" aria-label="Buscar câmera, ONU, serial ou IP"
               autoCapitalize="none" spellCheck={false} />
      </label>

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

      <div className="mosaico">
        <button type="button" className="bloco" onClick={() => ir('/cameras')}>
          <span className="rot">Câmeras</span>
          <span className="num">{up(m.cameras)}<small> / {m.cameras.length}</small></span>
          <span className="pes">{camDown ? <b className="vermelho">{camDown} sem vídeo</b> : <b className="verde">todas no ar</b>}</span>
        </button>
        <div className="bloco">
          <span className="rot">Gravadores</span>
          <span className="num">{up(m.nvrs)}<small> / {m.nvrs.length}</small></span>
          <span className="pes">{m.nvrs.length - up(m.nvrs) ? <b className="vermelho">{m.nvrs.length - up(m.nvrs)} fora</b> : <b className="verde">{m.nvrs.length ? 'no ar' : 'nenhum'}</b>}</span>
        </div>
        <button type="button" className="bloco" onClick={() => ir('/onu')}>
          <span className="rot">ONUs</span>
          <span className="num">{up(m.onus)}<small> / {m.onus.length}</small></span>
          <span className="pes">
            {onuDown ? <b className="vermelho">{onuDown} fora</b> : null}
            {onuBaixo ? <b className="ambar">{onuBaixo} sinal baixo</b> : null}
            {!onuDown && !onuBaixo ? <b className="verde">{m.onus.length ? 'sinal bom' : 'nenhuma'}</b> : null}
          </span>
        </button>
        <button type="button" className="bloco" onClick={() => ir('/rede')}>
          <span className="rot">Conector</span>
          <span className="num" style={{ fontSize: 20 }}>{!con ? '—' : con.status === 'up' ? 'online' : 'fora'}</span>
          <span className="pes">{con?.last_changed_at
            ? <b className={con.status === 'up' ? 'verde' : 'vermelho'}>{con.status === 'up' ? 'no ar' : 'caiu'} {desde(con.last_changed_at)}</b>
            : <b className="ambar">sem leitura</b>}</span>
        </button>
      </div>

      <Cartao>
        <h2>Precisa de atenção</h2>
        {!m.atencao.length ? <Vazio>Tudo no ar neste site.</Vazio> : m.atencao.slice(0, 8).map((e) => (
          <Item key={e.entity_key} ponto={e.status === 'up' ? 'ambar' : 'vermelho'}
                titulo={e.entity_type === 'onu' && e.status === 'up' ? `${nomeEntidade(e)} · sinal baixo` : nomeEntidade(e)}
                sub={subEntidade(e)} onClick={() => abrir(e)} direita={Icone.seta} />
        ))}
        {m.atencao.length > 8 ? (
          <button type="button" className="item" onClick={() => ir('/alertas')}>
            <span className="corpo"><span className="t">Ver todos ({m.atencao.length})</span></span>{Icone.seta}
          </button>
        ) : null}
      </Cartao>

      <Cartao>
        <h2>Últimas mudanças</h2>
        {!m.mudancas.length ? <Vazio>Nenhuma mudança recente neste site.</Vazio> : m.mudancas.slice(0, 5).map((ev, i) => (
          <Item key={`${ev.entity_key}-${i}`} titulo={ev.message.split(':')[0] || ev.entity_key}
                sub={`${ev.from_status} → ${ev.to_status} · ${horaCurta(ev.created_at)} · ${desde(ev.created_at)}`}
                direita={<span className={`selo ${ev.to_status === 'up' ? 'verde' : ev.to_status === 'down' ? 'ambar' : 'cinza'}`}>
                  {ev.to_status === 'up' ? 'voltou' : ev.to_status === 'down' ? 'caiu' : 'instável'}</span>} />
        ))}
      </Cartao>
    </>
  );
}
