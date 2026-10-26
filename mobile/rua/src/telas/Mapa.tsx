import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { chaveDa, estadoDa, siteDa, tituloDa, useCameras, type Camera } from '../lib/dados';
import { useFiltroSite } from '../lib/monitor';
import {
  LIMITE_UTP, TIPOS_CABO, cabosDaCaixa, distancia, gravarCabo, linhasDa, metrosDo, portasLivres, posicaoDaCaixa,
  pontosDa, useCamadas, type Caixa, type Camada, type Ponto,
} from '../lib/mapa';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Carregando, Icone, Item, Vazio, useToast } from '../ui/pecas';
import { useFiltro } from '../ui/Filtros';
import { pegar, salvar } from '../lib/storage';
import { ordemNatural } from '../lib/ordem';

/* 8 · Mapa do site, 9 · caixa CFTV, 10 · desenhar cabo */

type Sel = { camada: Camada; caixa: Caixa; pos: Ponto };
type Desenho = { porta: number | null; tipo: string; caminho: Ponto[]; camera?: Camera };

const COR_ESTADO = { online: '#087f5b', offline: '#c92a2a', sem: '#8a979f' };
const fmtM = (m: number) => `${Math.round(m)} m`;

export function Mapa() {
  const { site } = useSite();
  const filtro = useFiltroSite(site);
  const camadas = useCamadas();
  const cams = useCameras();
  const online = useOnline();
  const toast = useToast();
  const qc = useQueryClient();
  const ir = useNavigate();
  // Vindo da ficha da camera ou do Instalar: abre centrado nela e a marca.
  const vindo = (useLocation().state as { centro?: number[]; camera?: string; nome?: string } | null) ?? null;
  const pedido = vindo?.centro;

  const divMapa = useRef<HTMLDivElement>(null);
  const mapa = useRef<L.Map | null>(null);
  const grupo = useRef<L.LayerGroup | null>(null);
  const eu = useRef<L.CircleMarker | null>(null);
  const [satelite, setSatelite] = useState(false);
  const fundo = useRef<L.TileLayer | null>(null);
  const [minhaPos, setMinhaPos] = useState<Ponto | null>(null);
  const [sel, setSel] = useState<Sel | null>(null);
  const [aberta, setAberta] = useState(false);
  const [desenho, setDesenho] = useState<Desenho | null>(null);
  const [gravando, setGravando] = useState(false);
  // Camadas que o tecnico liga e desliga (ficam como estao ao trocar de aba).
  const [ver, setVer] = useState({ cabos: true, caixas: true, cameras: true, rotas: true });
  const alternar = (k: keyof typeof ver) => setVer((v) => ({ ...v, [k]: !v[k] }));
  const centrado = useRef(false);
  // Para onde o mapa deve olhar enquanto a tela ainda se ajusta (o cabecalho
  // encolhe ao abrir o Mapa). Sem isto o setView era calculado com o tamanho
  // errado e a camera pedida ficava fora do lugar. Arrastar o mapa solta.
  const alvo = useRef<{ p: Ponto; z: number } | null>(null);
  const [destaque, setDestaque] = useState<{ p: Ponto; nome: string } | null>(
    pedido && pedido.length === 2 && pedido.every(Number.isFinite) ? { p: [pedido[0], pedido[1]], nome: vindo?.nome ?? '' } : null);
  const [painel, setPainel] = useState<'' | 'camadas' | 'procurar'>('');
  // Mapas (KMZ) escondidos do site e de fora do site mostrados, por site, guardados no aparelho.
  const [ocultas, setOcultas] = useState<string[]>([]);
  const [extras, setExtras] = useState<string[]>([]);
  const chaveCamadas = `rua.mapa.camadas.${site ?? ''}`;
  useEffect(() => {
    void pegar(chaveCamadas).then((v) => {
      try { const d = JSON.parse(v ?? '{}'); setOcultas(d.ocultas ?? []); setExtras(d.extras ?? []); } catch { /* sem escolha guardada */ }
    });
  }, [chaveCamadas]);
  const guardarCamadas = (o: string[], x: string[]) => { setOcultas(o); setExtras(x); void salvar(chaveCamadas, JSON.stringify({ ocultas: o, extras: x })); };

  // Cameras do site com coordenada (o inventario guarda lat/lon).
  const camerasSite = useMemo(() => (cams.data ?? []).filter((c) => filtro(siteDa(c), c.remote_connector_id || c.connector_id)
    && Number.isFinite(Number(c.lat)) && Number.isFinite(Number(c.lon)) && c.lat && c.lon), [cams.data, filtro]);
  const centro: Ponto | null = useMemo(() => {
    if (!camerasSite.length) return null;
    const s = camerasSite.reduce((a, c) => [a[0] + Number(c.lat), a[1] + Number(c.lon)], [0, 0]);
    return [s[0] / camerasSite.length, s[1] / camerasSite.length];
  }, [camerasSite]);

  // Camadas do site: as que tem caixa ou ponto a ate 3 km das cameras do site.
  const doSite = useMemo(() => (camadas.data ?? []).filter((c) => {
    if (!centro) return true;
    const pts = [...Object.values(c.caixas ?? {}).map((cx) => posicaoDaCaixa(cx, c)).filter((p): p is Ponto => !!p), ...pontosDa(c).map((x) => x.p)];
    return pts.some((p) => distancia(p, centro) < 3000);
  }), [camadas.data, centro]);

  const outras = useMemo(() => (camadas.data ?? []).filter((c) => !doSite.includes(c)).sort((a, b) => ordemNatural(a.label, b.label)), [camadas.data, doSite]);
  const visiveis = useMemo(() => [...doSite.filter((c) => !ocultas.includes(c.id)), ...outras.filter((c) => extras.includes(c.id))],
    [doSite, outras, ocultas, extras]);
  const conta = useMemo(() => ({
    cabos: visiveis.reduce((a, c) => a + Object.keys(c.cabos ?? {}).length, 0),
    caixas: visiveis.reduce((a, c) => a + Object.keys(c.caixas ?? {}).length + Object.keys(c.ctos ?? {}).length, 0),
    cameras: camerasSite.length,
    rotas: visiveis.reduce((a, c) => a + linhasDa(c).length, 0),
  }), [visiveis, camerasSite]);

  // Liga o mapa uma vez.
  useEffect(() => {
    if (!divMapa.current || mapa.current) return;
    const m = L.map(divMapa.current, { zoomControl: false, attributionControl: true }).setView([-9.76, -36.67], 15);
    mapa.current = m;
    grupo.current = L.layerGroup().addTo(m);
    // A tela muda de tamanho depois de criada: recalcula e volta ao alvo.
    const ro = new ResizeObserver(() => {
      m.invalidateSize({ animate: false });
      if (alvo.current) m.setView(alvo.current.p, alvo.current.z, { animate: false });
    });
    ro.observe(divMapa.current);
    m.on('dragstart', () => { alvo.current = null; });
    return () => { ro.disconnect(); m.remove(); mapa.current = null; };
  }, []);

  // Fundo: mapa ou satelite (os mesmos servidores do mapa da web).
  useEffect(() => {
    const m = mapa.current;
    if (!m) return;
    fundo.current?.remove();
    fundo.current = satelite
      ? L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', { maxZoom: 20, maxNativeZoom: 18, attribution: '© Esri' })
      : L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 20, maxNativeZoom: 19, subdomains: 'abc', attribution: '© OpenStreetMap' });
    fundo.current.addTo(m);
  }, [satelite]);

  // GPS: onde o tecnico esta (so com o app aberto).
  useEffect(() => {
    if (!navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition((p) => setMinhaPos([p.coords.latitude, p.coords.longitude]), () => {}, { enableHighAccuracy: true, maximumAge: 10000 });
    return () => navigator.geolocation.clearWatch(id);
  }, []);
  useEffect(() => {
    const m = mapa.current;
    if (!m || !minhaPos) return;
    if (!eu.current) eu.current = L.circleMarker(minhaPos, { radius: 7, color: '#fff', weight: 3, fillColor: '#1971c2', fillOpacity: 1 }).addTo(m);
    else eu.current.setLatLng(minhaPos);
  }, [minhaPos]);

  // Centraliza no site na primeira vez.
  useEffect(() => {
    const m = mapa.current;
    if (!m || centrado.current) return;
    const ponto = (pedido && pedido.length === 2 && pedido.every(Number.isFinite) ? [pedido[0], pedido[1]] as Ponto : null) ?? centro ?? (doSite[0] ? Object.values(doSite[0].caixas).map((cx) => posicaoDaCaixa(cx, doSite[0])).find(Boolean) : null);
    if (ponto) { olharPara(ponto, pedido ? 19 : 17); centrado.current = true; }
  }, [centro, doSite, pedido]); // eslint-disable-line react-hooks/exhaustive-deps

  function olharPara(p: Ponto, z: number) {
    const m = mapa.current;
    if (!m) return;
    alvo.current = { p, z };
    m.invalidateSize({ animate: false });
    m.setView(p, z, { animate: false });
  }

  // Desenha tudo. Refaz quando os dados, a selecao ou o cabo em desenho mudam.
  useEffect(() => {
    const m = mapa.current;
    const g = grupo.current;
    if (!m || !g) return;
    g.clearLayers();
    for (const c of visiveis) {
      if (ver.rotas) for (const l of linhasDa(c)) L.polyline(l, { color: '#7a8790', weight: 2, opacity: 0.6, dashArray: '6 6', interactive: false }).addTo(g);
      for (const k of ver.cabos ? Object.values(c.cabos ?? {}) : []) {
        if (!k.caminho || k.caminho.length < 2) continue;
        const destaque = sel && k.caixa === sel.caixa.id;
        L.polyline(k.caminho, { color: k.cto ? '#0b6fa4' : '#1971c2', weight: destaque ? 4 : 2.5, opacity: sel && !destaque ? 0.45 : 0.9, dashArray: k.cto ? '7 5' : undefined, interactive: false }).addTo(g);
      }
      for (const cto of ver.caixas ? Object.values(c.ctos ?? {}) : []) {
        if (cto.lat == null || cto.lng == null) continue;
        L.marker([Number(cto.lat), Number(cto.lng)], { icon: L.divIcon({ className: '', html: `<span class="mk-cto" title="${cto.nome ?? cto.ponto ?? 'CTO'}"></span>`, iconSize: [16, 16] }), interactive: false }).addTo(g);
      }
      for (const cx of ver.caixas || desenho ? Object.values(c.caixas ?? {}) : []) {
        const p = posicaoDaCaixa(cx, c);
        if (!p) continue;
        const ativa = sel?.caixa.id === cx.id;
        L.marker(p, {
          icon: L.divIcon({ className: '', html: `<span class="mk-cx${ativa ? ' on' : ''}">${cx.tipo === 'onu' ? 'ONU' : 'CX'}</span><span class="mk-rot">${cx.nome || cx.ponto || ''}</span>`, iconSize: [28, 28], iconAnchor: [14, 14] }),
          keyboard: true, bubblingMouseEvents: false,
        }).on('click', () => { if (!desenho) { setSel({ camada: c, caixa: cx, pos: p }); setAberta(false); } }).addTo(g);
      }
    }
    for (const cam of ver.cameras || desenho ? camerasSite : []) {
      const e = estadoDa(cam);
      const p: Ponto = [Number(cam.lat), Number(cam.lon)];
      L.circleMarker(p, { radius: 9, color: '#fff', weight: 2.5, fillColor: COR_ESTADO[e], fillOpacity: 1, bubblingMouseEvents: false })
        .on('click', () => {
          // Ja tinha camera: troca a ponta final; senao, a camera fecha o traçado.
          if (desenho) setDesenho((d) => (d ? { ...d, camera: cam, caminho: d.camera ? [...d.caminho.slice(0, -1), p] : [...d.caminho, p] } : d));
          else ir(`/cameras/${chaveDa(cam)}`);
        })
        .bindTooltip(tituloDa(cam), { direction: 'top', offset: [0, -8] })
        .addTo(g);
    }
    if (destaque) {
      L.circleMarker(destaque.p, { radius: 19, color: '#d9480f', weight: 3, fill: false, interactive: false }).addTo(g);
      if (destaque.nome) {
        L.marker(destaque.p, { icon: L.divIcon({ className: '', html: `<span class="mk-destaque">${destaque.nome.replace(/</g, '&lt;')}</span>`, iconSize: [0, 0], iconAnchor: [0, 42] }), interactive: false }).addTo(g);
      }
    }
    if (desenho && desenho.caminho.length) {
      L.polyline(desenho.caminho, { color: '#d9480f', weight: 3.5 }).addTo(g);
      desenho.caminho.forEach((p, i) => { if (i > 0) L.circleMarker(p, { radius: 5, color: '#d9480f', weight: 2.5, fillColor: '#fff', fillOpacity: 1, interactive: false }).addTo(g); });
    }
  }, [visiveis, camerasSite, sel, desenho, ir, ver, destaque]);

  // Toque no mapa durante o desenho = nova curva (antes da camera escolhida).
  useEffect(() => {
    const m = mapa.current;
    if (!m) return;
    const clique = (ev: L.LeafletMouseEvent) => {
      setDesenho((d) => {
        if (!d) return d;
        const novo: Ponto = [ev.latlng.lat, ev.latlng.lng];
        if (d.camera) return { ...d, caminho: [...d.caminho.slice(0, -1), novo, d.caminho[d.caminho.length - 1]] };
        return { ...d, caminho: [...d.caminho, novo] };
      });
    };
    m.on('click', clique);
    return () => { m.off('click', clique); };
  }, []);

  type Achado = { tipo: 'Câmera' | 'Caixa'; nome: string; ip: string; p: Ponto; estado?: string };
  const achaveis = useMemo<Achado[]>(() => [
    ...camerasSite.map((c) => ({ tipo: 'Câmera' as const, nome: tituloDa(c), ip: c.ip ?? '', p: [Number(c.lat), Number(c.lon)] as Ponto, estado: estadoDa(c) })),
    ...visiveis.flatMap((c) => Object.values(c.caixas ?? {}).flatMap((cx): Achado[] => {
      const p = posicaoDaCaixa(cx, c);
      return p ? [{ tipo: 'Caixa', nome: cx.nome || cx.ponto || 'Caixa', ip: '', p }] : [];
    })),
  ].sort((a, b) => ordemNatural(a.nome, b.nome)), [camerasSite, visiveis]);
  const busca = useFiltro(achaveis, {
    texto: (x) => [x.nome, x.ip], dica: 'Nome ou IP da câmera, nome da caixa', unidade: 'no mapa',
    extra: { rotulo: 'Tipo', todos: 'Câmeras e caixas', de: (x) => x.tipo },
    situacao: (x) => (x.tipo === 'Caixa' ? 'livre' : x.estado === 'online' ? 'ok' : x.estado === 'offline' ? 'fora' : 'atencao'),
    nomes: { livre: 'Caixas', ok: 'Câmera no ar', fora: 'Câmera fora', atencao: 'Sem leitura' },
  });
  function irPara(x: { p: Ponto; nome: string }) {
    setDestaque({ p: x.p, nome: x.nome });
    olharPara(x.p, 19);
    setPainel('');
  }

  function centrarEmMim() {
    if (minhaPos) { alvo.current = null; mapa.current?.setView(minhaPos, 18); }
    else toast('Sem localização: libere a localização do app nos ajustes do celular.', true);
  }

  function comecarCabo(porta: number | null) {
    if (!sel) return;
    setDesenho({ porta, tipo: 'utp6', caminho: [sel.pos] });
    setAberta(false);
  }

  function desfazer() {
    setDesenho((d) => {
      if (!d) return d;
      if (d.camera) return { ...d, camera: undefined, caminho: d.caminho.slice(0, -1) };
      return d.caminho.length > 1 ? { ...d, caminho: d.caminho.slice(0, -1) } : d;
    });
  }

  async function concluir() {
    if (!sel || !desenho?.camera) return;
    setGravando(true);
    try {
      await gravarCabo(sel.camada.id, {
        caixa: sel.caixa.id, camera: { ip: desenho.camera.ip, ponto: tituloDa(desenho.camera) },
        tipo: desenho.tipo, porta: desenho.porta, caminho: desenho.caminho,
      });
      toast(`Cabo gravado: ${sel.caixa.nome || sel.caixa.ponto} → ${tituloDa(desenho.camera)}`);
      setDesenho(null);
      await qc.invalidateQueries({ queryKey: ['camadas'] });
      setAberta(true);
    } catch (e) {
      toast((e as Error).message, true);
    } finally {
      setGravando(false);
    }
  }

  const estadoCam = (ip?: string) => {
    const c = (cams.data ?? []).find((x) => x.ip === ip);
    return c ? estadoDa(c) : 'sem';
  };
  const cabosSel = sel ? cabosDaCaixa(sel.camada, sel.caixa) : [];
  const ctoSel = sel ? Object.values(sel.camada.cabos ?? {}).find((k) => k.caixa === sel.caixa.id && k.cto) : undefined;
  const okSel = cabosSel.filter((k) => estadoCam(k.camera?.ip) === 'online').length;
  const ruimSel = cabosSel.filter((k) => estadoCam(k.camera?.ip) === 'offline').length;
  const livres = sel ? portasLivres(sel.camada, sel.caixa) : [];
  const metros = desenho ? metrosDo(desenho.caminho) : 0;
  const utp = desenho?.tipo.startsWith('utp');

  return (
    <div className="mapa-tela">
      <div ref={divMapa} className="mapa-leaflet" />
      {camadas.isPending ? <div className="mapa-carregando"><Carregando texto="Baixando o mapa do site…" /></div> : null}

      {!desenho ? (
        <div className="camadas-mapa" role="group" aria-label="Mapa">
          <button type="button" className="com-icone" aria-expanded={painel === 'camadas'} onClick={() => setPainel(painel === 'camadas' ? '' : 'camadas')}>
            {Icone.camadas}Camadas{ocultas.length || extras.length || Object.values(ver).some((v) => !v) ? ' •' : ''}
          </button>
          <button type="button" className="com-icone" aria-expanded={painel === 'procurar'} onClick={() => setPainel(painel === 'procurar' ? '' : 'procurar')}>
            {Icone.busca}Procurar
          </button>
          {destaque ? <button type="button" className="com-icone" onClick={() => olharPara(destaque.p, 19)}>{Icone.pin}{destaque.nome ? destaque.nome.slice(0, 18) : 'Ponto'}</button> : null}
        </div>
      ) : (
        <button type="button" className="pilula-mapa" style={{ left: 12, top: 12 }} onClick={() => { setDesenho(null); setAberta(true); }}>{Icone.x}Cancelar</button>
      )}

      <div className={`fabs${desenho ? '' : ' abaixo'}`}>
        <button type="button" className="fab" aria-label="Centralizar em mim" onClick={centrarEmMim}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="7" /><circle cx="12" cy="12" r="2.5" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3" /></svg>
        </button>
        <button type="button" className="fab" aria-label={satelite ? 'Mapa' : 'Satélite'} aria-pressed={satelite} onClick={() => setSatelite(!satelite)}>{Icone.mapa}</button>
      </div>

      {painel ? <div className="fundo-mapa" onClick={() => setPainel('')} aria-hidden="true" /> : null}
      {painel === 'camadas' ? (
        <section className="folha-mapa alta" aria-label="Camadas do mapa">
          <span className="alca" aria-hidden="true" />
          <div className="cab-folha">
            <b className="tit-folha" style={{ flex: 1 }}>Camadas</b>
            <button type="button" className="fechar" aria-label="Fechar" onClick={() => setPainel('')}>{Icone.x}</button>
          </div>
          <span className="rot-secao">Fundo</span>
          <div className="seg">
            <button type="button" aria-pressed={!satelite} onClick={() => setSatelite(false)}>Mapa</button>
            <button type="button" aria-pressed={satelite} onClick={() => setSatelite(true)}>Satélite</button>
          </div>
          <span className="rot-secao">Mostrar</span>
          <div className="lista-camadas">
            {([['cameras', 'Câmeras'], ['caixas', 'Caixas e CTOs'], ['cabos', 'Cabos'], ['rotas', 'Rotas e traçados']] as [keyof typeof ver, string][]).map(([k, n]) => (
              <label key={k} className="linha-camada">
                <input type="checkbox" checked={ver[k]} onChange={() => alternar(k)} />
                <span className="corpo">{n}</span><span className="mono sub-tela">{conta[k]}</span>
              </label>
            ))}
          </div>
          <span className="rot-secao">Mapas deste site · {doSite.length}</span>
          <div className="lista-camadas">
            {!doSite.length ? <span className="sub-tela">Nenhum mapa (KMZ) perto das câmeras deste site.</span> : doSite.map((c) => (
              <label key={c.id} className="linha-camada">
                <input type="checkbox" checked={!ocultas.includes(c.id)}
                       onChange={() => guardarCamadas(ocultas.includes(c.id) ? ocultas.filter((x) => x !== c.id) : [...ocultas, c.id], extras)} />
                <span className="corpo">{c.label || 'Mapa sem nome'}
                <span className="mono sub-tela linha-sub">{[
                  `${pontosDa(c).length} pontos`,
                  Object.keys(c.caixas ?? {}).length ? `${Object.keys(c.caixas ?? {}).length} cx` : '',
                  Object.keys(c.cabos ?? {}).length ? `${Object.keys(c.cabos ?? {}).length} cabos` : '',
                ].filter(Boolean).join(' · ')}</span></span>
              </label>
            ))}
          </div>
          {outras.length ? (
            <details className="outros-mapas">
              <summary>Mapas de outros lugares · {outras.length}{extras.length ? ` (${extras.length} ligados)` : ''}</summary>
              <div className="lista-camadas">
                {outras.map((c) => (
                  <label key={c.id} className="linha-camada">
                    <input type="checkbox" checked={extras.includes(c.id)}
                           onChange={() => guardarCamadas(ocultas, extras.includes(c.id) ? extras.filter((x) => x !== c.id) : [...extras, c.id])} />
                    <span className="corpo">{c.label || 'Mapa sem nome'}</span>
                  </label>
                ))}
              </div>
            </details>
          ) : null}
        </section>
      ) : null}
      {painel === 'procurar' ? (
        <section className="folha-mapa alta" aria-label="Procurar no mapa">
          <span className="alca" aria-hidden="true" />
          <div className="cab-folha">
            <b className="tit-folha" style={{ flex: 1 }}>Procurar no mapa</b>
            <button type="button" className="fechar" aria-label="Fechar" onClick={() => setPainel('')}>{Icone.x}</button>
          </div>
          {!achaveis.length ? <Vazio>Nenhuma câmera com coordenada nem caixa nos mapas ligados.</Vazio> : busca.barra}
          <div>
            {busca.lista.slice(0, 80).map((x, i) => (
              <Item key={`${x.tipo}-${x.nome}-${i}`} icone={x.tipo === 'Câmera' ? Icone.camera : Icone.pin}
                    ponto={x.tipo === 'Câmera' ? (x.estado === 'online' ? 'verde' : x.estado === 'offline' ? 'vermelho' : 'ambar') : undefined}
                    titulo={x.nome} sub={[x.tipo, x.ip, minhaPos ? `a ${fmtM(distancia(minhaPos, x.p))} de você` : ''].filter(Boolean).join(' · ')}
                    onClick={() => irPara(x)} direita={Icone.seta} />
            ))}
            {busca.lista.length > 80 ? <p className="sub-tela">Mostrando 80 de {busca.lista.length}: refine a busca.</p> : null}
          </div>
        </section>
      ) : null}

      {desenho ? (
        <div className="dica-mapa" role="status">Toque no mapa para fazer uma curva. Toque na câmera para terminar.</div>
      ) : null}

      {!camadas.isPending && !visiveis.length && !painel && !sel ? (
        <div className="folha-mapa"><b>{doSite.length ? 'Todos os mapas deste site estão desligados.' : 'Nenhum mapa neste site.'}</b>
          <span className="sub-tela">{doSite.length ? 'Ligue em Camadas.' : 'O mapa (KMZ) é importado no SightOps pelo navegador. Em Camadas dá para ligar mapas de outros lugares.'}</span></div>
      ) : null}

      {sel && !desenho ? (
        <section className={`folha-mapa${aberta ? ' alta' : ''}`} aria-label="Caixa selecionada">
          <span className="alca" aria-hidden="true" />
          <div className="cab-folha">
            <div style={{ minWidth: 0, flex: 1 }}>
              <b className="tit-folha">{sel.caixa.nome || sel.caixa.ponto}</b>
              <span className="sub-tela">{sel.caixa.tipo === 'onu' ? 'Caixa com ONU' : sel.caixa.tipo === 'passagem' ? 'Caixa de passagem' : 'Com switch'}{sel.caixa.portas ? ` · ${sel.caixa.portas} portas · ${cabosSel.filter((k) => k.porta).length} em uso` : ''}</span>
            </div>
            <button type="button" className="fechar" aria-label="Fechar" onClick={() => { setSel(null); setAberta(false); }}>{Icone.x}</button>
          </div>
          <div className="chips">
            {minhaPos ? <span className="selo cinza">a {fmtM(distancia(minhaPos, sel.pos))} de você</span> : null}
            {okSel ? <span className="selo verde">{okSel} {okSel === 1 ? 'câmera ok' : 'câmeras ok'}</span> : null}
            {ruimSel ? <span className="selo vermelho">{ruimSel} sem vídeo</span> : null}
            {ctoSel?.cto?.ponto ? <span className="selo azul">fibra da {ctoSel.cto.ponto}{ctoSel.cto.porta ? ` · porta ${ctoSel.cto.porta}` : ''}</span> : null}
          </div>

          {aberta && Number(sel.caixa.portas) > 0 ? (
            <>
              <span className="rot-secao">Portas</span>
              <div className="portas">
                {Array.from({ length: Number(sel.caixa.portas) }, (_, i) => i + 1).map((p) => {
                  const k = cabosSel.find((x) => Number(x.porta) === p);
                  const est = k ? estadoCam(k.camera?.ip) : null;
                  return (
                    <button key={p} type="button" className={`porta${!k ? ' livre' : est === 'offline' ? ' falha' : ''}`}
                            onClick={() => (!k ? comecarCabo(p) : undefined)} aria-label={k ? `Porta ${p}: ${k.camera?.ponto || k.camera?.ip}` : `Porta ${p} livre: ligar câmera`}>
                      <span className="n">P{p}{k ? <span className="d" style={{ background: est ? COR_ESTADO[est] : '#8a979f' }} /> : null}</span>
                      <span className="l">{k ? (k.camera?.ponto || k.camera?.ip) : 'livre'}</span>
                    </button>
                  );
                })}
              </div>
              {cabosSel.length ? (
                <span className="sub-tela">{cabosSel.length} cabos · <b>{fmtM(cabosSel.reduce((a, k) => a + Number(k.metros_com_folga ?? k.metros ?? 0), 0))}</b> no total</span>
              ) : null}
            </>
          ) : null}

          <div className="acoes-duplas">
            <button type="button" className="btn" onClick={() => (aberta ? comecarCabo(livres[0] ?? null) : setAberta(true))} disabled={aberta && !online}>
              {aberta ? (livres.length ? `Ligar câmera na P${livres[0]}` : 'Ligar câmera') : 'Abrir caixa'}
            </button>
            <button type="button" className="btn2" onClick={() => (aberta ? setAberta(false) : comecarCabo(livres[0] ?? null))}>
              {aberta ? 'Fechar' : 'Desenhar cabo'}
            </button>
          </div>
        </section>
      ) : null}

      {desenho && sel ? (
        <section className="folha-mapa" aria-label="Cabo em desenho">
          <span className="alca" aria-hidden="true" />
          <div>
            <b className="tit-folha">{sel.caixa.nome || sel.caixa.ponto}{desenho.porta ? ` · P${desenho.porta}` : ''} → {desenho.camera ? tituloDa(desenho.camera) : 'toque na câmera'}</b>
            {Number(sel.caixa.portas) > 0 ? (
              <div className="chips" style={{ marginTop: 6 }}>
                {livres.map((p) => <button key={p} type="button" className="aba" aria-pressed={desenho.porta === p} onClick={() => setDesenho({ ...desenho, porta: p })}>P{p}</button>)}
              </div>
            ) : null}
          </div>
          <div className="chips" role="group" aria-label="Tipo de cabo">
            {TIPOS_CABO.map(([v, n]) => <button key={v} type="button" className="aba" aria-pressed={desenho.tipo === v} onClick={() => setDesenho({ ...desenho, tipo: v })}>{n}</button>)}
          </div>
          <div>
            <div className="metros-linha">
              <b className="mono">{fmtM(metros * 1.1)}</b>
              <span className="sub-tela">traçado + 10% de folga</span>
              {utp ? <span className="sub-tela limite">limite {LIMITE_UTP} m</span> : null}
            </div>
            {utp ? <div className="barra-metros"><span style={{ width: `${Math.min(100, (metros * 1.1 / LIMITE_UTP) * 100)}%`, background: metros * 1.1 > LIMITE_UTP ? 'var(--danger)' : 'var(--primary)' }} /></div> : null}
            {utp && metros * 1.1 > LIMITE_UTP ? <span className="sub-tela" style={{ color: 'var(--danger)' }}>Passa de {LIMITE_UTP} m: UTP não garante o sinal nessa distância.</span> : null}
          </div>
          <div className="acoes-duplas">
            <button type="button" className="btn2" disabled={desenho.caminho.length < 2} onClick={desfazer}>Desfazer curva</button>
            <button type="button" className="btn" disabled={!desenho.camera || gravando || !online} onClick={concluir}>{gravando ? 'Gravando…' : 'Concluir cabo'}</button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
