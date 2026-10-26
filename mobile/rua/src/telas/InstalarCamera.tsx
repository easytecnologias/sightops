import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { enviar, obter } from '../lib/api';
import { detalhe, mesmoSite, siteDoConector, useConectores, useEntidades } from '../lib/dados';
import { useFiltroSite } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Cartao, Icone, Item, Vazio } from '../ui/pecas';

/*
 * 6 · Instalar camera: achar na rede, ler, configurar, por no gravador e
 * registrar. As mesmas rotas e a mesma ordem da Implantacao CFTV da web
 * (deploy.js): lookup -> camera-xray -> apply-camera-ip -> recorder-login ->
 * save-camera-title -> recorder-add-camera -> commit-camera.
 * Senhas ficam so na memoria desta tela (nunca no cache do aparelho).
 */

type Achado = { ip?: string; address?: string; mac?: string; source?: string; host?: string; conflito_ip?: boolean };
type Leitura = {
  titulo?: string;
  equipamento?: { fabricante?: string; modelo?: string; serial?: string; firmware?: string; mac?: string };
  rede?: { ip?: string; mac?: string; mascara?: string; gateway?: string };
  achados?: [string, string, string][];
};
type Canal = { channel: number | string; used?: boolean; title?: string; camera_ip?: string; ip?: string };
export type VemDaAtivacao = { ip?: string; mac?: string; senha?: string };

const n2 = (c: number | string) => String(c).padStart(2, '0');

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
  const conector = conectores.find((c) => c.online) ?? conectores[0];
  const cid = conector?.id ?? '';

  // 1 · achar
  const [busca, setBusca] = useState(veio.mac || veio.ip || '');
  const [achados, setAchados] = useState<Achado[] | null>(null);
  const [ip, setIp] = useState(veio.ip ?? '');
  const [mac, setMac] = useState(veio.mac ?? '');
  // 2 · ler
  const [usuario, setUsuario] = useState('admin');
  const [senha, setSenha] = useState(veio.senha ?? '');
  const [leitura, setLeitura] = useState<Leitura | null>(null);
  // 3 · configurar
  const [titulo, setTitulo] = useState('');
  const [nomeOk, setNomeOk] = useState(false);
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
  const gravadores = useMemo(() => (nvrs.data ?? []).filter((e) => filtro(e.site, e.connector_id))
    .map((e) => ({ nome: String(e.display_name ?? ''), host: String(detalhe<{ host?: string }>(e).host ?? ''), conector: e.connector_id ?? cid }))
    .filter((g) => g.host), [nvrs.data, filtro, cid]);
  const grav = gravadores.find((g) => g.host === gravHost);
  const portaGrav = creds.data?.find((c) => c.host === gravHost)?.port;

  // Passo atual
  const passo = !ip ? 1 : !leitura ? 2 : !(nomeOk && titulo.trim()) ? 3 : (!semGravador && !canal) ? 4 : 5;
  const [vendoPasso, setVendoPasso] = useState(0);
  const aberto = (n: number) => (vendoPasso || passo) === n && !resultado;

  useEffect(() => { if (veio.mac || veio.ip) void procurar(veio.mac || veio.ip || ''); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function procurar(q = busca) {
    if (!cid || !q.trim()) return;
    setIndo('procurar'); setErro(''); setAchados(null);
    try {
      const d = await obter<{ matches?: Achado[] }>(`/api/deployments/lookup?connector_id=${encodeURIComponent(cid)}&query=${encodeURIComponent(q.trim())}`);
      setAchados(d.matches ?? []);
      if ((d.matches ?? []).length === 1 && !d.matches![0].conflito_ip) escolher(d.matches![0]);
    } catch (e) { setErro((e as Error).message); } finally { setIndo(''); }
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
      camera_user: usuario.trim() || 'admin', camera_password: senha, inventory_mode: 'basic',
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
        passos.push({ ok: true, t: 'Entra no Zabbix na próxima leitura do site (alguns minutos)' });
      } catch (e) { passos.push({ ok: false, t: `Não registrou no inventário: ${(e as Error).message}` }); }
      setResultado(passos);
      void qc.invalidateQueries({ queryKey: ['cameras'] });
      void qc.invalidateQueries({ queryKey: ['entidades', 'camera'] });
    } finally { setIndo(''); }
  }

  if (!conectores.length) return <Cartao><Vazio>Este site não tem conector: não há como alcançar a câmera.</Vazio></Cartao>;

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Instalar câmera</h1>
        <p className="sub-tela">Ler a câmera, configurar e pôr no gravador.</p>
      </div>
      {conector && !conector.online ? <div className="aviso ambar">{Icone.aviso}<span>O conector {conector.name} está fora do ar: nada aqui chega à câmera agora.</span></div> : null}

      <Passo n={1} titulo="Achar a câmera na rede" aberto={aberto(1)} onEditar={() => setVendoPasso(1)} feito={ip ? `${ip}${mac ? ` · ${mac}` : ''}` : undefined}>
        <div className="campo"><label htmlFor="bq">MAC da etiqueta ou IP</label>
          <form className="caixa" onSubmit={(e) => { e.preventDefault(); void procurar(); }}>
            <input id="bq" className="mono" value={busca} onChange={(e) => setBusca(e.target.value)} placeholder="aa:bb:cc:dd:ee:ff" autoCapitalize="none" spellCheck={false} enterKeyHint="search" />
          </form>
          <span className="ajuda">Procura no DHCP, ARP e vizinhos do MikroTik do site.</span></div>
        <button type="button" className="btn" disabled={!busca.trim() || indo === 'procurar' || !online} onClick={() => void procurar()}>
          {Icone.busca}{indo === 'procurar' ? 'Procurando no MikroTik…' : 'Procurar'}
        </button>
        {achados ? (!achados.length ? <Vazio>Nada com esse MAC/IP no conector.</Vazio> : achados.slice(0, 8).map((a, i) => (
          <Item key={`${a.ip}-${a.mac}-${i}`} ponto={a.conflito_ip ? 'ambar' : undefined} icone={Icone.camera}
                titulo={a.ip || a.address || '—'} sub={[a.mac, a.source, a.conflito_ip ? 'mesmo IP com outro MAC' : ''].filter(Boolean).join(' · ')}
                onClick={() => escolher(a)} direita={ip === (a.ip || a.address) ? <span className="selo verde">escolhida</span> : Icone.seta} />
        ))) : null}
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

      <Passo n={3} titulo="Configurar" aberto={aberto(3)} onEditar={() => setVendoPasso(3)} feito={nomeOk && titulo.trim() ? `${titulo.trim()} · ${ip}` : undefined}>
        <div className="campo"><label htmlFor="tit">Nome da câmera (vai na imagem, no gravador e no inventário)</label>
          <div className="caixa"><input id="tit" value={titulo} maxLength={40} onChange={(e) => setTitulo(e.target.value)} placeholder="Ex.: Portaria · Entrada" /></div></div>
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
        {!gravadores.length ? <Vazio>Nenhum gravador monitorado neste site.</Vazio> : gravadores.map((g) => (
          <Item key={g.host} icone={Icone.gravador} titulo={g.nome || g.host} sub={g.host}
                onClick={() => void entrarGravador(g.host)}
                direita={gravHost === g.host ? <span className="selo verde">{indo === 'grav' ? 'entrando…' : 'escolhido'}</span> : Icone.seta} />
        ))}
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
              <span><i>{semGravador ? 2 : 3}</i>Registra no inventário e no Zabbix</span>
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
            <button type="button" className="btn" onClick={() => ir('/cameras')}>Ver em Câmeras</button>
            <button type="button" className="btn2" onClick={() => ir('/implantar/instalar', { replace: true, state: {} })}>Instalar outra</button>
          </div>
        </Cartao>
      ) : null}

      {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}
    </>
  );
}
