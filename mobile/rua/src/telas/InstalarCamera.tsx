import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { enviar, obter } from '../lib/api';
import { detalhe, ipDaOlt, mesmoSite, siteDoConector, useConectores, useEntidades, useOlts } from '../lib/dados';
import { gravadoresPorLocal, localPeloNome, useFiltroSite } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Cartao, EscolhaLocal, Icone, Item, Vazio } from '../ui/pecas';
import { OndeProcurar } from '../ui/OndeProcurar';
import { LerEtiqueta } from '../ui/LerEtiqueta';
import { ehMac } from '../lib/etiqueta';

/*
 * 6 · Instalar camera: achar na rede, ler, configurar, por no gravador e
 * registrar. As mesmas rotas e a mesma ordem da Implantacao CFTV da web
 * (deploy.js): lookup -> camera-xray -> apply-camera-ip -> recorder-login ->
 * save-camera-title -> recorder-add-camera -> commit-camera.
 * Senhas ficam so na memoria desta tela (nunca no cache do aparelho).
 */

type Achado = { ip?: string; address?: string; mac?: string; source?: string; host?: string; conflito_ip?: boolean;
  responde?: boolean; antigo?: boolean; estado?: string; ao_vivo?: boolean };
type Leitura = {
  titulo?: string;
  equipamento?: { fabricante?: string; modelo?: string; serial?: string; firmware?: string; mac?: string };
  rede?: { ip?: string; mac?: string; mascara?: string; gateway?: string };
  achados?: [string, string, string][];
};
type Canal = { channel: number | string; used?: boolean; title?: string; camera_ip?: string; ip?: string };
export type VemDaAtivacao = { ip?: string; mac?: string; senha?: string };

const n2 = (c: number | string) => String(c).padStart(2, '0');
const indoBusca = (aoVivo: string, vivos: Record<string, string>) =>
  aoVivo === 'perguntando' || Object.values(vivos).includes('testando');

function Passo({ n, titulo, feito, aberto, onEditar, children }: { n: number; titulo: string; feito?: string; aberto: boolean; onEditar?: () => void; children?: React.ReactNode }) {
  return (
    <section className={`cartao passo-instalar${aberto ? ' aberto' : ''}`}>
      <h2><span className={`n${feito ? ' ok' : ''}`}>{feito ? Icone.ok : n}</span>{titulo}
        {feito && !aberto && onEditar ? <button type="button" className="link" onClick={onEditar}>Mudar</button> : null}</h2>
      {feito && !aberto ? <p className="sub-h2 feito-txt">{feito}</p> : null}
      {aberto ? <div className="form-cartao">{children}</div> : null}
    </section>
  );
}

function useArmado(): [boolean, () => boolean] {
  const [armado, setArmado] = useState(false);
  const t = useRef<number>();
  useEffect(() => () => window.clearTimeout(t.current), []);
  return [armado, () => {
    if (!armado) { setArmado(true); window.clearTimeout(t.current); t.current = window.setTimeout(() => setArmado(false), 6000); return false; }
    window.clearTimeout(t.current); setArmado(false); return true;
  }];
}

export function InstalarCamera() {
  const online = useOnline();
  const { site } = useSite();
  const filtro = useFiltroSite(site);
  const cons = useConectores();
  const nvrs = useEntidades('nvr');
  const qc = useQueryClient();
  const ir = useNavigate();
  const veio = (useLocation().state ?? {}) as VemDaAtivacao;

  const conectores = (cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site));
  const [conId, setConId] = useState('');
  const conector = conectores.find((c) => c.id === conId) ?? conectores.find((c) => c.online) ?? conectores[0];
  const cid = conector?.id ?? '';
  const oltsQ = useOlts();
  const oltsDoSite = (oltsQ.data ?? []).filter((o) => filtro(o.site, o.connector_id));

  // 1 · achar
  const [busca, setBusca] = useState(veio.mac || veio.ip || '');
  const [achados, setAchados] = useState<Achado[] | null>(null);
  // Mesmo MAC com mais de um IP: o ARP do MikroTik guarda o IP velho ("failed")
  // e o agente nao manda esse status. Quem decide e o ping de agora.
  const [vivos, setVivos] = useState<Record<string, 'testando' | 'responde' | 'nao'>>({});
  // Busca por MAC tambem pergunta AGORA ao MikroTik (ARP+DHCP so desse MAC):
  // o inventario que o agente manda corta o ARP em 500 linhas.
  const [aoVivo, setAoVivo] = useState<'' | 'perguntando' | 'ok' | 'sem'>('');
  const [aoVivoMsg, setAoVivoMsg] = useState('');
  const buscaId = useRef(0);
  const [mostrarAntigos, setMostrarAntigos] = useState(false);
  // Enquanto o MikroTik nao responde e os pings nao voltam, a lista fica
  // escondida: o inventario traz o IP velho do DHCP e o tecnico tocava nele.
  const buscando = indoBusca(aoVivo, vivos);
  const naoResponde = (a: Achado) => vivos[a.ip || a.address || ''] === 'nao';
  const respondem = (achados ?? []).filter((a) => !naoResponde(a));
  const antigos = (achados ?? []).filter(naoResponde);
  const [segundos, setSegundos] = useState(0);
  useEffect(() => {
    if (!buscando) return;
    const t0 = Date.now(); setSegundos(0);
    const t = window.setInterval(() => setSegundos(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [buscando]);
  const rapidos = useRef<Achado[]>([]);
  const vivoFalhou = useRef(false);
  const [ip, setIp] = useState(veio.ip ?? '');
  const [mac, setMac] = useState(veio.mac ?? '');
  // 2 · ler
  const [usuario, setUsuario] = useState('admin');
  const [senha, setSenha] = useState(veio.senha ?? '');
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  // 3 · configurar
  const [titulo, setTitulo] = useState('');
  const [nomeOk, setNomeOk] = useState(false);
  // Como a camera chega a rede: e o inventario em que ela entra (o mesmo
  // seletor da Implantacao da web). Fibra pode dizer a OLT.
  const [modo, setModo] = useState<'basic' | 'olt' | 'switch'>('basic');
  const [oltId, setOltId] = useState('');
  // Posicao: "lat, lon" (o formato do commit-camera). E ela que poe a camera no mapa.
  const [posicao, setPosicao] = useState('');
  const [precisao, setPrecisao] = useState<number | null>(null);
  const [pegandoGps, setPegandoGps] = useState(false);
  const [novoIp, setNovoIp] = useState('');
  const [ipArmado, armarIp] = useArmado();
  // 4 · gravador
  const [gravHost, setGravHost] = useState('');
  const [semGravador, setSemGravador] = useState(false);
  const [canais, setCanais] = useState<Canal[] | null>(null);
  const [canal, setCanal] = useState('');
  const [gUser, setGUser] = useState('admin');
  const [gSenha, setGSenha] = useState('');
  const [pedeSenhaGrav, setPedeSenhaGrav] = useState(false);
  // 5 · registrar
  const [regArmado, armarReg] = useArmado();
  const [resultado, setResultado] = useState<{ ok: boolean; t: string }[] | null>(null);

  const [indo, setIndo] = useState('');
  const [erro, setErro] = useState('');

  const creds = useQuery({
    queryKey: ['credenciais-gravador'],
    queryFn: async () => (await obter<{ credenciais?: { host: string; port?: number | string; username?: string }[] }>('/api/deployments/recorder-credenciais')).credenciais ?? [],
    staleTime: 5 * 60_000,
  });
  const grupos = useMemo(() => gravadoresPorLocal((nvrs.data ?? []).filter((e) => filtro(e.site, e.connector_id)), site)
    .map(({ local, itens }) => ({
      local,
      itens: itens.map((e) => ({ nome: String(e.display_name ?? ''), host: String(detalhe<{ host?: string }>(e).host ?? ''), conector: e.connector_id ?? cid })),
    })), [nvrs.data, filtro, site, cid]);
  const gravadores = useMemo(() => grupos.flatMap((g) => g.itens), [grupos]);
  const grav = gravadores.find((g) => g.host === gravHost);
  // Local do gravador: o que o tecnico tocou; senao o do gravador ja escolhido,
  // o unico que houver, ou o que aparece no nome da camera.
  const [localEscolhido, setLocalEscolhido] = useState('');
  const localGrav = localEscolhido
    || grupos.find((g) => g.itens.some((i) => i.host === gravHost))?.local
    || (grupos.length === 1 ? grupos[0].local : localPeloNome(grupos.map((g) => g.local), titulo));
  const gravDoLocal = grupos.find((g) => g.local === localGrav)?.itens ?? [];
  const portaGrav = creds.data?.find((c) => c.host === gravHost)?.port;

  // Passo atual
  const passo = !ip ? 1 : !leitura ? 2 : !(nomeOk && titulo.trim()) ? 3 : (!semGravador && !canal) ? 4 : 5;
  const [vendoPasso, setVendoPasso] = useState(0);
  const aberto = (n: number) => (vendoPasso || passo) === n && !resultado;

  useEffect(() => { if (veio.mac || veio.ip) void procurar(veio.mac || veio.ip || ''); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function procurar(q = busca) {
    if (!cid || !q.trim()) return;
    const id = ++buscaId.current;
    const porMac = ehMac(q);
    rapidos.current = []; vivoFalhou.current = false;
    setIndo('procurar'); setErro(''); setAchados(null); setVivos({}); setAoVivo(porMac ? 'perguntando' : ''); setAoVivoMsg(''); setMostrarAntigos(false);
    if (porMac) void perguntarAoMikrotik(q.trim(), id);
    try {
      const d = await obter<{ matches?: Achado[] }>(`/api/deployments/lookup?connector_id=${encodeURIComponent(cid)}&query=${encodeURIComponent(q.trim())}`);
      if (id !== buscaId.current) return;
      const lista = d.matches ?? [];
      rapidos.current = lista;
      setAchados((atual) => atual ?? lista);   // a resposta ao vivo, se ja chegou, manda
      // Por MAC quem decide e a pergunta ao vivo (o ping daqui entraria na mesma
      // fila de jobs do MikroTik e a atrasaria); so pinga se ela falhar.
      if (porMac && !vivoFalhou.current) return;
      setVivos({});
      if (!porMac && lista.length === 1 && !lista[0].conflito_ip) escolher(lista[0]);
      else if (lista.length) testarVivos(lista, id);
    } catch (e) { setErro((e as Error).message); } finally { setIndo(''); }
  }

  async function perguntarAoMikrotik(q: string, id: number) {
    try {
      const d = await obter<{ respondeu?: boolean; matches?: Achado[]; detail?: string }>(
        `/api/deployments/lookup-live?connector_id=${encodeURIComponent(cid)}&mac=${encodeURIComponent(q)}`);
      if (id !== buscaId.current) return;
      if (!d.respondeu) { semAoVivo(d.detail || 'o MikroTik não respondeu', id); return; }
      const lista = d.matches ?? [];
      setAoVivo('ok');
      if (!lista.length) { setAoVivoMsg('O MikroTik não conhece esse MAC agora: a câmera está ligada e no cabo?'); setAchados([]); return; }
      setAchados(lista);
      setVivos(Object.fromEntries(lista.map((a) => [a.ip || a.address || '', a.responde ? 'responde' : 'nao'])));
      const vivo = lista.find((a) => a.responde);
      setAoVivoMsg(vivo ? `O MikroTik confirmou: ${vivo.ip} responde agora.` : 'O MikroTik vê esse MAC, mas nenhum IP respondeu ao ping.');
      if (vivo) escolher(vivo);
      else setIp('');
    } catch (e) {
      if (id === buscaId.current) semAoVivo((e as Error).message, id);
    }
  }

  /** Sem resposta ao vivo: volta ao inventario e testa cada IP pelo ping. */
  function semAoVivo(motivo: string, id: number) {
    vivoFalhou.current = true;
    setAoVivo('sem');
    setAoVivoMsg(`Sem consulta ao vivo (${motivo}): testei pelo ping os IPs que o SightOps já conhecia.`);
    if (rapidos.current.length) testarVivos(rapidos.current, id);
  }
  /** Pinga cada IP candidato pelo conector; o primeiro que responde e escolhido. */
  function testarVivos(lista: Achado[], id: number) {
    const ips = [...new Set(lista.map((a) => a.ip || a.address || '').filter(Boolean))];
    setVivos(Object.fromEntries(ips.map((x) => [x, 'testando' as const])));
    let escolhido = false;
    for (const alvo of ips) {
      obter<{ online?: boolean; reachable?: boolean }>(
        `/api/cameras/ping?ip=${encodeURIComponent(alvo)}&remote_connector_id=${encodeURIComponent(cid)}&force=1&timeout=2`)
        .then((r) => {
          const ok = !!(r.online || r.reachable);
          if (id !== buscaId.current) return;
          setVivos((v) => (v[alvo] === 'testando' ? { ...v, [alvo]: ok ? 'responde' : 'nao' } : v));
          if (ok && !escolhido) {
            escolhido = true;
            const a = lista.find((x) => (x.ip || x.address) === alvo);
            if (a) escolher(a);
          }
        })
        .catch(() => { if (id === buscaId.current) setVivos((v) => (v[alvo] === 'testando' ? { ...v, [alvo]: 'nao' } : v)); });
    }
  }

  function escolher(a: Achado) {
    setIp(a.ip || a.address || ''); setMac(a.mac || ''); setLeitura(null); setVendoPasso(0);
  }

  async function ler() {
    if (!senha) { setErro('Informe a senha da câmera.'); return; }
    setIndo('ler'); setErro('');
    try {
      const d = await enviar<Leitura>('/api/deployments/camera-xray', { ip, usuario: usuario.trim() || 'admin', senha, connector_id: cid });
      setLeitura(d);
      if (!titulo.trim() && d.titulo) setTitulo(d.titulo);
      if (!mac && (d.rede?.mac || d.equipamento?.mac)) setMac(d.rede?.mac || d.equipamento?.mac || '');
      if (d.rede?.ip && d.rede.ip !== ip) setIp(d.rede.ip);
      setVendoPasso(0);
    } catch (e) { setErro((e as Error).message); } finally { setIndo(''); }
  }

  function usarMinhaPosicao() {
    if (!navigator.geolocation) { setErro('Este aparelho não dá a localização.'); return; }
    setPegandoGps(true); setErro('');
    navigator.geolocation.getCurrentPosition((p) => {
      setPosicao(`${p.coords.latitude.toFixed(7)}, ${p.coords.longitude.toFixed(7)}`);
      setPrecisao(Math.round(p.coords.accuracy));
      setPegandoGps(false);
    }, (e) => {
      setPegandoGps(false);
      setErro(e.code === 1 ? 'A localização não foi liberada: libere nos ajustes do celular.' : 'Não consegui a posição agora. Tente de novo a céu aberto.');
    }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
  }
  const posValida = /^-?\d{1,2}(\.\d+)?\s*,\s*-?\d{1,3}(\.\d+)?$/.test(posicao.trim());

  async function trocarIp() {
    const alvo = novoIp.trim();
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(alvo)) { setErro('IP inválido.'); return; }
    if (!ipArmado) {
      try {
        const r = await obter<{ in_use?: boolean }>(`/api/deployments/ip-check?ip=${encodeURIComponent(alvo)}&connector_id=${encodeURIComponent(cid)}&site=${encodeURIComponent(site ?? '')}`);
        if (r.in_use) { setErro(`O IP ${alvo} já está em uso neste site.`); return; }
      } catch { /* sem conferencia: a camera recusa se colidir */ }
    }
    if (!armarIp()) return;
    setIndo('ip'); setErro('');
    try {
      await enviar('/api/deployments/apply-camera-ip', { ip, new_ip: alvo, usuario: usuario.trim() || 'admin', senha, connector_id: cid });
      setIp(alvo); setNovoIp('');
    } catch (e) { setErro((e as Error).message); } finally { setIndo(''); }
  }

  async function entrarGravador(host: string, comSenha = false) {
    setGravHost(host); setCanais(null); setCanal(''); setErro(''); setIndo('grav');
    try {
      const d = await enviar<{ channels?: Canal[] }>('/api/deployments/recorder-login', {
        recorder_type: 'nvr', recorder_host: host, recorder_http_port: creds.data?.find((c) => c.host === host)?.port ?? '',
        connector_id: gravadores.find((g) => g.host === host)?.conector || cid,
        ...(comSenha ? { recorder_user: gUser.trim() || 'admin', recorder_password: gSenha } : {}),
      });
      const lista = d.channels ?? [];
      setCanais(lista); setPedeSenhaGrav(false);
      const livre = lista.find((c) => !c.used);
      setCanal(livre ? String(livre.channel) : '');
      if (livre) setVendoPasso(4);
    } catch (e) {
      const m = (e as Error).message;
      if (/SEM_CREDENCIAL/.test(m) || /senha|credencial|401/i.test(m)) setPedeSenhaGrav(true);
      setErro(/SEM_CREDENCIAL/.test(m) ? 'Este gravador não tem senha salva: informe usuário e senha.' : m);
    } finally { setIndo(''); }
  }

  async function registrar() {
    if (!armarReg()) return;
    setIndo('registrar'); setErro('');
    const passos: { ok: boolean; t: string }[] = [];
    const t = titulo.trim();
    const base = {
      connector_id: cid, site: site ?? '', camera_mac: mac, camera_ip: ip, camera_title: t,
      camera_model: leitura?.equipamento?.modelo ?? '', camera_manufacturer: leitura?.equipamento?.fabricante ?? '',
      camera_user: usuario.trim() || 'admin', camera_password: senha, inventory_mode: modo,
      olt_id: modo === 'olt' && oltId ? Number(oltId) : null,
      location: posValida ? posicao.trim() : '',
      ...(semGravador || !gravHost ? {} : {
        recorder_type: 'nvr', recorder_host: gravHost, recorder_http_port: portaGrav ?? '', recorder_channel: canal,
        recorder_camera_ip: ip, recorder_title: t, recorder_channel_total: canais?.length || 32,
        ...(gSenha ? { recorder_user: gUser.trim() || 'admin', recorder_password: gSenha } : {}),
      }),
    };
    try {
      try {
        await enviar('/api/deployments/save-camera-title', { ip, title: t, usuario: base.camera_user, senha, connector_id: cid });
        passos.push({ ok: true, t: `Título “${t}” gravado na câmera` });
      } catch (e) { passos.push({ ok: false, t: `Título não gravado na câmera: ${(e as Error).message}` }); }
      if (!semGravador && gravHost) {
        try {
          const r = await enviar<{ channel?: number }>('/api/deployments/recorder-add-camera', base);
          passos.push({ ok: true, t: `Câmera no canal ${n2(r.channel ?? canal)} do ${grav?.nome || gravHost}` });
        } catch (e) { passos.push({ ok: false, t: `Não entrou no gravador: ${(e as Error).message}` }); }
      }
      try {
        await enviar('/api/deployments/commit-camera', base);
        passos.push({ ok: true, t: 'Registrada no inventário: aparece em Câmeras' });
        passos.push(posValida
          ? { ok: true, t: `Posição gravada: aparece no mapa${precisao ? ` (±${precisao} m)` : ''}` }
          : { ok: false, t: 'Sem posição: não aparece no mapa' });
        passos.push({ ok: true, t: 'Entra no Zabbix na próxima leitura do site (alguns minutos)' });
      } catch (e) { passos.push({ ok: false, t: `Não registrou no inventário: ${(e as Error).message}` }); }
      setResultado(passos);
      void qc.invalidateQueries({ queryKey: ['cameras'] });
      void qc.invalidateQueries({ queryKey: ['entidades', 'camera'] });
    } finally { setIndo(''); }
  }

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Instalar câmera</h1>
        <p className="sub-tela">Ler a câmera, configurar e pôr no gravador.</p>
      </div>
      <OndeProcurar conector={conector} so="todos" aoTrocarConector={(id) => { setConId(id); setAchados(null); setIp(''); setMac(''); setLeitura(null); }} />
      {!conectores.length ? <Cartao><Vazio>Este site não tem conector: toque em “Trocar” e escolha o site da câmera.</Vazio></Cartao> : null}
      {conector && !conector.online ? <div className="aviso ambar">{Icone.aviso}<span>O conector {conector.name} está fora do ar: nada aqui chega à câmera agora.</span></div> : null}

      <Passo n={1} titulo="Achar a câmera na rede" aberto={aberto(1)} onEditar={() => setVendoPasso(1)} feito={ip ? `${ip}${mac ? ` · ${mac}` : ''}` : undefined}>
        <div className="campo"><label htmlFor="bq">MAC da etiqueta ou IP</label>
          <form className="caixa" onSubmit={(e) => { e.preventDefault(); void procurar(); }}>
            <input id="bq" className="mono" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="aa:bb:cc:dd:ee:ff" autoCapitalize="none" spellCheck={false} enterKeyHint="search" />
          </form>
          <span className="ajuda">Por MAC, pergunta na hora ao MikroTik do site (ARP e DHCP) e testa qual IP responde.</span></div>
        <LerEtiqueta aoErro={setErro} aoLer={(m) => { setBusca(m); void procurar(m); }} />
        <button type="button" className="btn" disabled={!busca.trim() || indo === 'procurar' || buscando || !online} onClick={() => void procurar()}>
          {Icone.busca}{indo === 'procurar' || buscando ? 'Procurando…' : 'Procurar'}
        </button>
        {indo === 'procurar' || buscando ? (
          <p className="sub-tela">
            {aoVivo === 'perguntando' ? `Perguntando ao MikroTik agora… ${segundos} s (até ~40 s)` : `Testando quais IPs respondem… ${segundos} s`}
          </p>
        ) : (
          <>
            {aoVivoMsg ? <div className={`aviso ${respondem.length ? 'verde' : 'ambar'}`}>{Icone.aviso}<span>{aoVivoMsg}</span></div> : null}
            {achados ? (!achados.length ? <Vazio>Nada com esse MAC/IP no conector.</Vazio> : (
              <>
                {!respondem.length ? <Vazio>Nenhum IP respondeu agora. A câmera está ligada e no cabo?</Vazio> : null}
                {(mostrarAntigos ? achados : respondem).slice(0, 8).map((a, i) => {
                  const alvo = a.ip || a.address || '';
                  const v = vivos[alvo];
                  return (
                    <Item key={`${a.ip}-${a.mac}-${i}`} ponto={v === 'responde' ? 'verde' : v === 'nao' ? 'vermelho' : a.conflito_ip ? 'ambar' : undefined} icone={Icone.camera}
                          titulo={alvo || '—'}
                          sub={[a.mac, a.source, a.conflito_ip ? 'mesmo IP com outro MAC' : '', v === 'responde' ? 'responde agora' : v === 'nao' ? 'IP antigo, não responde' : ''].filter(Boolean).join(' · ')}
                          onClick={() => escolher(a)}
                          direita={ip === alvo ? <span className="selo verde">escolhida</span> : v === 'nao' ? <span className="selo vermelho">sem resposta</span> : Icone.seta} />
                  );
                })}
                {antigos.length && !mostrarAntigos ? (
                  <button type="button" className="link" onClick={() => setMostrarAntigos(true)}>
                    {antigos.length === 1 ? `Mostrar o IP antigo que não respondeu (${antigos[0].ip || antigos[0].address})` : `Mostrar ${antigos.length} IPs antigos que não responderam`}
                  </button>
                ) : null}
              </>
            )) : null}
          </>
        )}
      </Passo>

      <Passo n={2} titulo="Ler a câmera" aberto={aberto(2)} onEditar={() => setVendoPasso(2)}
             feito={leitura ? [leitura.equipamento?.fabricante, leitura.equipamento?.modelo, leitura.titulo ? `“${leitura.titulo}”` : ''].filter(Boolean).join(' · ') : undefined}>
        <div className="duas">
          <div className="campo"><label htmlFor="cu">Usuário</label><div className="caixa"><input id="cu" value={usuario} onChange={(e) => setUsuario(e.target.value)} autoCapitalize="none" /></div></div>
          <div className="campo"><label htmlFor="cs">Senha</label><div className="caixa"><input id="cs" type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="off" /></div></div>
        </div>
        <button type="button" className="btn" disabled={indo === 'ler' || !online} onClick={ler}>{indo === 'ler' ? 'Lendo a câmera pelo conector…' : 'Entrar na câmera'}</button>
      </Passo>

      {leitura ? (
        <Cartao>
          <div className="ficha">
            {[['Câmera', [leitura.equipamento?.fabricante, leitura.equipamento?.modelo].filter(Boolean).join(' ')], ['Serial', leitura.equipamento?.serial],
              ['Firmware', leitura.equipamento?.firmware], ['Rede', [ip, leitura.rede?.mascara, leitura.rede?.gateway ? `gw ${leitura.rede.gateway}` : ''].filter(Boolean).join(' · ')]]
              .filter(([, v]) => v).map(([k, v]) => (
                <div key={k} className="ficha-linha"><span className="ficha-rot">{k}</span><span className="ficha-val mono">{v}</span></div>
              ))}
          </div>
          {(leitura.achados ?? []).map((a, i) => <div key={i} className="ocorrencia"><b>{a[1]}</b> {a[2]}</div>)}
        </Cartao>
      ) : null}

      <Passo n={3} titulo="Configurar" aberto={aberto(3)} onEditar={() => setVendoPasso(3)} feito={nomeOk && titulo.trim() ? `${titulo.trim()} · ${ip} · ${modo === 'olt' ? 'fibra' : modo === 'switch' ? 'switch' : 'cabo direto'}${posValida ? ' · com posição' : ' · sem posição'}` : undefined}>
        <div className="campo"><label htmlFor="tit">Nome da câmera (vai na imagem, no gravador e no inventário)</label>
          <div className="caixa"><input id="tit" value={titulo} maxLength={40} onChange={(e) => setTitulo(e.target.value)} placeholder="Ex.: Portaria · Entrada" /></div></div>
        <div className="campo"><span className="lb">Como ela chega na rede</span>
          <div className="seg seg-3">
            <button type="button" aria-pressed={modo === 'basic'} onClick={() => setModo('basic')}>Cabo direto</button>
            <button type="button" aria-pressed={modo === 'olt'} onClick={() => setModo('olt')}>Fibra (ONU)</button>
            <button type="button" aria-pressed={modo === 'switch'} onClick={() => setModo('switch')}>Switch</button>
          </div>
          <span className="ajuda">{modo === 'olt' ? 'A câmera fica atrás de uma ONU: entra no inventário da fibra.'
            : modo === 'switch' ? 'Tem um switch no meio do caminho.' : 'Cabo de rede direto até o equipamento.'}</span>
        </div>
        {modo === 'olt' && oltsDoSite.length ? (
          <div className="campo"><label htmlFor="olt">OLT (opcional)</label>
            <select id="olt" className="caixa-sel" value={oltId} onChange={(e) => setOltId(e.target.value)}>
              <option value="">Não sei / deixar o SightOps achar</option>
              {oltsDoSite.map((o) => <option key={o.id} value={o.id}>{o.name || ipDaOlt(o)}</option>)}
            </select></div>
        ) : null}
        <div className="campo"><label htmlFor="pos">Onde ela fica (põe a câmera no mapa)</label>
          <div className="caixa"><input id="pos" className="mono" inputMode="decimal" value={posicao}
                 onChange={(e) => { setPosicao(e.target.value); setPrecisao(null); }} placeholder="-9.66, -35.73" /></div>
          {precisao !== null ? <span className="ajuda" style={precisao > 30 ? { color: 'var(--amber-txt)' } : undefined}>
            {precisao > 30 ? `Precisão de ±${precisao} m: chegue mais perto da câmera e pegue de novo.` : `Precisão de ±${precisao} m.`}</span>
            : <span className="ajuda">Fique embaixo da câmera e toque em “Usar minha posição”.</span>}
          {posicao.trim() && !posValida ? <span className="ajuda" style={{ color: 'var(--danger)' }}>Use o formato “latitude, longitude”.</span> : null}
        </div>
        <button type="button" className="btn2" disabled={pegandoGps} onClick={usarMinhaPosicao}>{Icone.pin}{pegandoGps ? 'Pegando o GPS…' : 'Usar minha posição'}</button>
        <details className="avancado">
          <summary>Trocar o IP da câmera (agora: {ip})</summary>
          <div className="form-cartao">
            <div className="campo"><label htmlFor="nip">IP novo (máscara e gateway ficam os da câmera)</label>
              <div className="caixa"><input id="nip" className="mono" inputMode="decimal" value={novoIp} onChange={(e) => setNovoIp(e.target.value)} placeholder={ip} /></div></div>
            <button type="button" className={`btn2${ipArmado ? ' armado' : ''}`} disabled={!novoIp.trim() || indo === 'ip' || !online} onClick={trocarIp}>
              {indo === 'ip' ? 'Aplicando na câmera…' : ipArmado ? `Toque de novo: ${ip} → ${novoIp.trim()}` : 'Aplicar IP novo'}
            </button>
          </div>
        </details>
        <button type="button" className="btn" disabled={!titulo.trim()} onClick={() => { setNomeOk(true); setVendoPasso(0); }}>Continuar</button>
      </Passo>

      <Passo n={4} titulo="Gravador e canal" aberto={aberto(4)} onEditar={() => { setSemGravador(false); setVendoPasso(4); }}
             feito={semGravador ? 'sem gravador (só inventário)' : canal ? `${grav?.nome || gravHost} · canal ${n2(canal)}` : undefined}>
        {!gravadores.length ? <Vazio>Nenhum gravador monitorado neste site.</Vazio> : (
          <>
            {grupos.length > 1 ? (
              <div className="campo"><span className="lb">Local</span>
                <EscolhaLocal locais={grupos.map((g) => ({ local: g.local, n: g.itens.length }))} valor={localGrav}
                              onEscolher={(l) => {
                                setLocalEscolhido(l);
                                if (l !== localGrav) { setGravHost(''); setCanais(null); setCanal(''); setPedeSenhaGrav(false); }
                              }} /></div>
            ) : null}
            {!localGrav ? <span className="ajuda">Escolha o local para ver os gravadores.</span> : gravDoLocal.map((g) => (
              <Item key={g.host} icone={Icone.gravador} titulo={g.nome || g.host} sub={g.host}
                    onClick={() => void entrarGravador(g.host)}
                    direita={gravHost === g.host ? <span className="selo verde">{indo === 'grav' ? 'entrando…' : 'escolhido'}</span> : Icone.seta} />
            ))}
          </>
        )}
        {pedeSenhaGrav ? (
          <div className="duas">
            <div className="campo"><label htmlFor="gu">Usuário do gravador</label><div className="caixa"><input id="gu" value={gUser} onChange={(e) => setGUser(e.target.value)} autoCapitalize="none" /></div></div>
            <div className="campo"><label htmlFor="gs">Senha</label><div className="caixa"><input id="gs" type="password" value={gSenha} onChange={(e) => setGSenha(e.target.value)} /></div></div>
          </div>
        ) : null}
        {pedeSenhaGrav ? <button type="button" className="btn2" disabled={!gSenha} onClick={() => void entrarGravador(gravHost, true)}>Entrar no gravador</button> : null}
        {canais ? (
          <div className="campo"><span className="lb">Canal</span>
            <div className="canais-grade">
              {canais.map((c) => (
                <button key={String(c.channel)} type="button" className={`canal-bt${c.used ? ' usado' : ''}`} disabled={!!c.used}
                        aria-pressed={canal === String(c.channel)} onClick={() => { setCanal(String(c.channel)); setVendoPasso(0); }}
                        title={c.used ? (c.title || c.camera_ip || c.ip || 'ocupado') : 'livre'}>{n2(c.channel)}</button>
              ))}
            </div>
            <span className="ajuda">{canais.filter((c) => !c.used).length} livres de {canais.length}.</span>
          </div>
        ) : null}
        <button type="button" className="link" onClick={() => { setSemGravador(true); setVendoPasso(0); }}>Registrar sem pôr em gravador</button>
      </Passo>

      {passo === 5 && !resultado ? (
        <>
          <Cartao>
            <h2>Ao registrar, o SightOps:</h2>
            <div className="lista-num">
              <span><i>1</i>Grava o nome “{titulo.trim()}” na câmera</span>
              {!semGravador ? <span><i>2</i>Põe a câmera no canal {n2(canal)} do {grav?.nome || gravHost}</span> : null}
              <span><i>{semGravador ? 2 : 3}</i>Registra no inventário ({modo === 'olt' ? 'fibra' : modo === 'switch' ? 'switch' : 'cabo direto'}) e no Zabbix</span>
            </div>
          </Cartao>
          <button type="button" className={`btn${regArmado ? ' armado' : ''}`} disabled={indo === 'registrar' || !online} onClick={registrar}>
            {indo === 'registrar' ? 'Registrando…' : regArmado ? <>{Icone.aviso}Toque de novo para registrar</> : <>{Icone.ok}Registrar câmera</>}
          </button>
        </>
      ) : null}

      {resultado ? (
        <Cartao>
          <h2>{resultado.every((r) => r.ok) ? 'Câmera instalada' : 'Instalada com pendências'}</h2>
          <div className="lista-quebra">{resultado.map((r, i) => <Item key={i} ponto={r.ok ? 'verde' : 'vermelho'} titulo={r.t} />)}</div>
          <div className="form-cartao">
            {posValida ? (
              <button type="button" className="btn" onClick={() => ir('/mapa', { state: { centro: posicao.split(',').map((x) => Number(x.trim())) } })}>{Icone.mapa}Ver no mapa</button>
            ) : null}
            <button type="button" className={posValida ? 'btn2' : 'btn'} onClick={() => ir('/cameras')}>Ver em Câmeras</button>
            <button type="button" className="btn2" onClick={() => ir('/implantar/instalar', { replace: true, state: {} })}>Instalar outra</button>
          </div>
        </Cartao>
      ) : null}

      {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}
    </>
  );
}
