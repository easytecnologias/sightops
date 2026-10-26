import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ErroApi, enviar, obter } from '../lib/api';
import { chaveDa, detalhe, useCameras, useEntidades, useEu, type Entidade } from '../lib/dados';
import { gravadoresPorLocal, useFiltroSite } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';
import { useFiltro, type Situacao } from '../ui/Filtros';
import { ordenar } from '../lib/ordem';

/* 7 · Gravador — canais. Rotas da web (gravador-canais.js): recorder-xray (le),
   recorder-buscar-cameras (le), recorder-macs (le), recorder-edit (ESCREVE). */

type DetalheNvr = { host?: string; model?: string; canais_total?: number; canais_offline?: number; canais_sem_imagem?: number; canais_sem_imagem_lista?: number[] };
type Canal = { canal: number; nome?: string; ip?: string; protocolo?: string; online?: boolean; ativo?: boolean; codec?: string; resolucao?: string; fps?: string | number; perda_video?: boolean | null };
type RaioX = { canais?: Canal[]; total_canais?: number; modelo?: string; model?: string };
type Achada = { ip: string; mac?: string; modelo?: string; fabricante?: string; no_gravador?: boolean };

const n2 = (c: number) => String(c).padStart(2, '0');
const macLimpo = (v?: string) => String(v ?? '').toLowerCase().replace(/[^0-9a-f]/g, '');

/** Gravadores do site, pelo monitoramento (traz host, modelo e canais sem imagem). */
function useGravadoresDoSite() {
  const { site } = useSite();
  const filtro = useFiltroSite(site);
  const q = useEntidades('nvr');
  const grupos = useMemo(() => gravadoresPorLocal((q.data ?? []).filter((e) => filtro(e.site, e.connector_id)), site),
    [q.data, filtro, site]);
  return { ...q, grupos };
}

export function Gravadores() {
  const { grupos, isPending } = useGravadoresDoSite();
  const ir = useNavigate();
  const todos = useMemo(() => grupos.flatMap((g) => g.itens.map((e) => ({ e, local: g.local }))), [grupos]);
  const { lista, barra } = useFiltro(todos, {
    texto: ({ e }) => [e.display_name, detalhe<DetalheNvr>(e).host, detalhe<DetalheNvr>(e).model], dica: 'Nome, IP ou modelo',
    local: (x) => x.local,
    situacao: ({ e }) => {
      const d = detalhe<DetalheNvr>(e);
      return e.status !== 'up' ? 'fora' : Number(d.canais_sem_imagem ?? 0) + Number(d.canais_offline ?? 0) ? 'atencao' : 'ok';
    },
    nomes: { atencao: 'Com câmera sem vídeo', ok: 'Tudo ok' },
  });
  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Gravador</h1>
        <p className="sub-tela">Canais e troca de câmera de canal.</p>
      </div>
      {isPending ? <Carregando /> : (
        <>
        {barra}
        <Cartao>
          {!grupos.length ? <Vazio>Nenhum gravador monitorado neste site.</Vazio>
            : !lista.length ? <Vazio>Nada com esse filtro.</Vazio> : lista.map(({ e }) => {
            const d = detalhe<DetalheNvr>(e);
            const sem = Number(d.canais_sem_imagem ?? 0) + Number(d.canais_offline ?? 0);
            return (
              <Item key={e.entity_key} ponto={e.status !== 'up' ? 'vermelho' : sem ? 'ambar' : 'verde'} icone={Icone.gravador}
                    titulo={String(e.display_name ?? d.host)}
                    sub={[d.host, d.model, d.canais_total ? `${d.canais_total} canais` : ''].filter(Boolean).join(' · ')}
                    onClick={() => ir(`/implantar/gravador/${encodeURIComponent(d.host ?? '')}?c=${encodeURIComponent(e.connector_id ?? '')}`)}
                    direita={e.status !== 'up' ? <span className="selo vermelho">fora</span>
                      : sem ? <span className="selo ambar">{sem} sem vídeo</span> : <span className="selo verde">ok</span>} />
            );
          })}
        </Cartao>
        </>
      )}
    </>
  );
}

function BotaoArmado({ rotulo, armar, indo, desab, onConfirmar, classe = 'btn' }:
  { rotulo: string; armar: string; indo?: boolean; desab?: boolean; onConfirmar: () => void; classe?: string }) {
  const [armado, setArmado] = useState(false);
  const t = useRef<number>();
  useEffect(() => () => window.clearTimeout(t.current), []);
  return (
    <button type="button" className={`${classe}${armado ? ' armado' : ''}`} disabled={indo || desab}
            onClick={() => {
              if (!armado) { setArmado(true); window.clearTimeout(t.current); t.current = window.setTimeout(() => setArmado(false), 6000); return; }
              window.clearTimeout(t.current); setArmado(false); onConfirmar();
            }}>
      {indo ? 'Enviando ao gravador…' : armado ? armar : rotulo}
    </button>
  );
}

export function GravadorCanais() {
  const { host = '' } = useParams();
  const [param] = useSearchParams();
  const online = useOnline();
  const { site } = useSite();
  const doSite = useGravadoresDoSite();
  const lista = doSite.grupos.flatMap((g) => g.itens);
  const toast = useToast();
  const ir = useNavigate();
  const ent: Entidade | undefined = lista.find((e) => detalhe<DetalheNvr>(e).host === host);
  // Sem ?c= (atalho do Inicio, da ficha da camera...) vale o conector do
  // cadastro do gravador: sem conector o servidor nao chega pelo IP virtual.
  const conector = param.get('c') || ent?.connector_id || '';
  const dn = ent ? detalhe<DetalheNvr>(ent) : {};

  const [cred, setCred] = useState<{ user: string; senha: string } | null>(null);
  const [tentativa, setTentativa] = useState(0);
  const [userIn, setUserIn] = useState('admin');
  const [senhaIn, setSenhaIn] = useState('');
  // Porta HTTP do gravador: os NVD 7132 do PERUCABA respondem em 8081..8088,
  // nao na 80. Sem ela todo pedido ia para a 80, era recusado, e a tela dizia
  // "o gravador respondeu, mas nao devolveu nada util" em todos eles.
  const creds = useQuery({
    queryKey: ['credenciais-gravador'],
    queryFn: async () => (await obter<{ credenciais?: { host: string; port?: number | string }[] }>('/api/deployments/recorder-credenciais')).credenciais ?? [],
    staleTime: 5 * 60_000,
  });
  const porta = creds.data?.find((c) => c.host === host)?.port;
  const base = () => ({ recorder_host: host, connector_id: conector, site: site ?? '',
    ...(porta ? { recorder_http_port: porta } : {}),
    ...(cred ? { recorder_user: cred.user, recorder_password: cred.senha } : {}) });

  const rx = useQuery({
    // Senha NUNCA na chave: o cache do app e gravado no aparelho.
    queryKey: ['raiox', host, conector, porta ?? '', tentativa],
    queryFn: () => enviar<RaioX>('/api/deployments/recorder-xray', { ...base(), fase: 'essencial' }),
    enabled: !creds.isPending && (!!param.get('c') || !doSite.isPending),
    retry: false,
    staleTime: 60_000,
  });
  const semCred = rx.error instanceof ErroApi && (rx.error.status === 428 || /SEM_CREDENCIAL/.test(rx.error.message));

  const [busca, setBusca] = useState<{ carregando: boolean; erro: string; cams: Achada[] } | null>(null);
  const [macs, setMacs] = useState<Record<string, string>>({});
  const [trabalhando, setTrabalhando] = useState('');
  // Menu do canal: o que o tecnico faz no campo (ver, renomear, trocar IP,
  // cadastrar camera em canal livre, excluir). Tudo vai ao gravador de verdade.
  const [menuCanal, setMenuCanal] = useState(0);
  const [modo, setModo] = useState<'' | 'renomear' | 'ip' | 'cadastrar'>('');
  const [form, setForm] = useState({ nome: '', ip: '', user: 'admin', senha: '' });
  const eu = useEu();
  const podeExcluir = ['admin', 'owner'].includes(String(eu.data?.role ?? '').toLowerCase());
  const cams = useCameras();
  const abrirMenu = (c: Canal) => {
    setMenuCanal(menuCanal === c.canal ? 0 : c.canal);
    setModo(c.ip ? '' : 'cadastrar');
    setForm({ nome: c.nome || '', ip: c.ip || '', user: 'admin', senha: '' });
  };
  const ipValido = (v: string) => /^(\d{1,3})(\.\d{1,3}){3}$/.test(v.trim()) && v.trim().split('.').every((x) => Number(x) <= 255);
  const [senhaCam, setSenhaCam] = useState('');
  const [pedirSenhaCam, setPedirSenhaCam] = useState('');

  const canais = useMemo(() => {
    const lidos = rx.data?.canais ?? [];
    const total = Math.max(Number(rx.data?.total_canais ?? 0), Number(dn.canais_total ?? 0), ...lidos.map((c) => c.canal));
    const por = new Map(lidos.map((c) => [c.canal, c]));
    return Array.from({ length: total }, (_, i) => por.get(i + 1) ?? { canal: i + 1 });
  }, [rx.data, dn.canais_total]);
  const semLista = new Set((dn.canais_sem_imagem_lista ?? []).map(Number));
  const estado = (c: Canal): 'livre' | 'sem' | 'ok' | '?' =>
    !c.ip ? 'livre' : (c.online === false || semLista.has(c.canal) || c.perda_video === true) ? 'sem' : c.online === true ? 'ok' : '?';
  const livres = canais.filter((c) => !c.ip);
  const { lista: canaisVistos, barra: barraCanais } = useFiltro(canais, {
    texto: (c) => [c.nome, c.ip, `canal ${c.canal}`, n2(c.canal)], dica: 'Nome, IP ou número do canal',
    situacao: (c): Situacao => ({ livre: 'livre', sem: 'fora', ok: 'ok', '?': 'atencao' } as const)[estado(c)],
    nomes: { todos: 'Todos', fora: 'Sem imagem', ok: 'Com imagem', atencao: 'Sem leitura', livre: 'Livres' },
  });

  async function procurar() {
    setBusca({ carregando: true, erro: '', cams: [] });
    try {
      const ips = canais.map((c) => c.ip).filter(Boolean).join(',');
      const [b, m] = await Promise.all([
        enviar<{ cameras?: Achada[] }>('/api/deployments/recorder-buscar-cameras', { ...base(), marca: 'auto' }),
        ips ? obter<{ macs?: Record<string, string> }>(`/api/deployments/recorder-macs?ips=${encodeURIComponent(ips)}`) : Promise.resolve({ macs: {} }),
      ]);
      setMacs(m.macs ?? {});
      setBusca({ carregando: false, erro: '', cams: ordenar(b.cameras ?? [], (x) => x.ip) });
    } catch (e) {
      setBusca({ carregando: false, erro: (e as Error).message, cams: [] });
    }
  }

  // Canal sem imagem cuja camera (pelo MAC do inventario) responde em outro IP.
  const mudaram = useMemo(() => {
    const achadas = busca?.cams ?? [];
    const porMac = new Map(achadas.filter((a) => macLimpo(a.mac)).map((a) => [macLimpo(a.mac), a]));
    return canais.filter((c) => c.ip && estado(c) === 'sem').map((c) => {
      const mac = macs[c.ip!] ?? '';
      const a = macLimpo(mac) ? porMac.get(macLimpo(mac)) : undefined;
      return a && a.ip !== c.ip ? { canal: c, mac, ip: a.ip } : null;
    }).filter((x): x is { canal: Canal; mac: string; ip: string } => !!x);
  }, [busca, macs, canais]); // eslint-disable-line react-hooks/exhaustive-deps
  const fora = (busca?.cams ?? []).filter((a) => a.ip && !a.no_gravador && !canais.some((c) => c.ip === a.ip) && !mudaram.some((m) => m.ip === a.ip));

  async function editar(chave: string, corpo: Record<string, unknown>, ok: string) {
    setTrabalhando(chave);
    try {
      const r = await enviar<{ online?: boolean; aviso?: string }>('/api/deployments/recorder-edit', { ...base(), ...corpo });
      toast(r.online === false ? `${ok}, mas a câmera ainda não conectou: ${r.aviso || 'confira a senha'}` : ok, r.online === false);
      setPedirSenhaCam(''); setSenhaCam('');
      void rx.refetch();
      return true;
    } catch (e) {
      const msg = (e as Error).message;
      if (/senha da camera/i.test(msg)) setPedirSenhaCam(chave);
      toast(msg, true);
      return false;
    } finally {
      setTrabalhando('');
    }
  }

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar/gravador')}>{Icone.volta}Gravadores</button>
      <div>
        <h1 className="titulo-tela">{String(ent?.display_name ?? host)}</h1>
        <p className="sub-tela mono">{[host, dn.model || rx.data?.modelo, ent?.last_checked_at ? `lido ${desde(ent.last_checked_at)}` : ''].filter(Boolean).join(' · ')}</p>
      </div>

      {semCred || cred ? (
        !rx.data ? (
          <Cartao>
            <h2>Senha do gravador</h2>
            <p className="sub-h2">Não há senha salva deste gravador no SightOps.</p>
            <div className="form-cartao">
              <div className="campo"><label htmlFor="gu">Usuário</label><div className="caixa"><input id="gu" value={userIn} onChange={(e) => setUserIn(e.target.value)} autoCapitalize="none" /></div></div>
              <div className="campo"><label htmlFor="gs">Senha</label><div className="caixa"><input id="gs" type="password" value={senhaIn} onChange={(e) => setSenhaIn(e.target.value)} /></div></div>
              <button type="button" className="btn" disabled={!senhaIn || rx.isFetching} onClick={() => { setCred({ user: userIn.trim() || 'admin', senha: senhaIn }); setTentativa((t) => t + 1); }}>
                {rx.isFetching ? 'Entrando…' : 'Entrar no gravador'}
              </button>
              {cred && rx.error ? <div className="aviso vermelho">{Icone.aviso}<span>{(rx.error as Error).message}</span></div> : null}
            </div>
          </Cartao>
        ) : null
      ) : rx.isPending ? <Carregando texto="Lendo o gravador pelo conector…" />
        : rx.error ? <div className="aviso vermelho">{Icone.aviso}<span>Não consegui ler o gravador: {(rx.error as Error).message}</span></div> : null}

      {rx.data ? (
        <>
          <div className="mosaico">
            <div className="bloco"><span className="rot">Com câmera</span><span className="num">{canais.length - livres.length}</span></div>
            <div className="bloco"><span className="rot">Sem imagem</span><span className={`num${canais.some((c) => estado(c) === 'sem') ? ' vermelho' : ''}`}>{canais.filter((c) => estado(c) === 'sem').length}</span></div>
          </div>

          <button type="button" className="btn2" disabled={busca?.carregando || !online} onClick={procurar}>
            {Icone.busca}{busca?.carregando ? 'Procurando na rede do gravador…' : 'Procurar câmeras na rede'}
          </button>
          {busca?.erro ? <div className="aviso vermelho">{Icone.aviso}<span>{busca.erro}</span></div> : null}

          {mudaram.map((m) => {
            const chave = `apontar-${m.canal.canal}`;
            return (
              <Cartao key={chave}>
                <h2>Canal {n2(m.canal.canal)}{m.canal.nome ? ` · ${m.canal.nome}` : ''}</h2>
                <p className="sub-h2">Sem imagem porque a câmera mudou de IP: o gravador tenta <span className="mono">{m.canal.ip}</span>, e a câmera com o mesmo MAC responde em <b className="mono">{m.ip}</b>.</p>
                <div className="form-cartao">
                  {pedirSenhaCam === chave ? (
                    <div className="campo"><label htmlFor={`sc${chave}`}>Senha da câmera (não há senha salva)</label>
                      <div className="caixa"><input id={`sc${chave}`} type="password" value={senhaCam} onChange={(e) => setSenhaCam(e.target.value)} /></div></div>
                  ) : null}
                  <BotaoArmado rotulo={`Apontar canal ${n2(m.canal.canal)} para ${m.ip}`} armar={`Toque de novo: canal ${n2(m.canal.canal)} → ${m.ip}`}
                               indo={trabalhando === chave} desab={!!trabalhando || !online}
                               onConfirmar={() => void editar(chave, {
                                 acao: 'editar', canal: m.canal.canal, nome: m.canal.nome || '', camera_ip: m.ip, camera_mac: m.mac,
                                 camera_password: senhaCam, protocolo: m.canal.protocolo || '',
                                 antes: { ip: m.canal.ip, nome: m.canal.nome || '', mac: m.mac, protocolo: m.canal.protocolo || '' },
                               }, `Canal ${n2(m.canal.canal)} apontado para ${m.ip}`)} />
                </div>
              </Cartao>
            );
          })}
          {busca && !busca.carregando && !busca.erro && !mudaram.length && canais.some((c) => estado(c) === 'sem') ? (
            <div className="aviso neutro">{Icone.aviso}<span>Nenhum canal sem imagem tem a câmera em outro IP. Pode ser câmera desligada, cabo ou PoE.</span></div>
          ) : null}

          {fora.length ? (
            <Cartao>
              <h2>Na rede, fora de canal</h2>
              <p className="sub-h2">{livres.length ? `${livres.length} ${livres.length === 1 ? 'canal livre' : 'canais livres'} · primeiro: ${n2(livres[0].canal)}` : 'Nenhum canal livre neste gravador'}</p>
              {fora.map((a) => {
                const chave = `add-${a.ip}`;
                return (
                  <div key={a.ip} className="item item-coluna">
                    <span className="corpo"><span className="t mono">{a.ip}</span><span className="s">{[a.fabricante, a.modelo, a.mac].filter(Boolean).join(' · ') || '—'}</span></span>
                    {livres.length ? (
                      <>
                        {pedirSenhaCam === chave ? (
                          <div className="campo" style={{ width: '100%' }}><label htmlFor={`sa${a.ip}`}>Senha da câmera</label>
                            <div className="caixa"><input id={`sa${a.ip}`} type="password" value={senhaCam} onChange={(e) => setSenhaCam(e.target.value)} /></div></div>
                        ) : null}
                        <BotaoArmado classe="btn2" rotulo={`Pôr no canal ${n2(livres[0].canal)}`} armar={`Toque de novo: ${a.ip} → canal ${n2(livres[0].canal)}`}
                                     indo={trabalhando === chave} desab={!!trabalhando || !online}
                                     onConfirmar={() => void editar(chave, {
                                       acao: 'adicionar', canal: livres[0].canal, nome: a.modelo ? `${a.modelo}` : `Canal ${n2(livres[0].canal)}`,
                                       camera_ip: a.ip, camera_mac: a.mac || '', camera_password: senhaCam,
                                     }, `${a.ip} posta no canal ${n2(livres[0].canal)}`)} />
                      </>
                    ) : null}
                  </div>
                );
              })}
            </Cartao>
          ) : null}

          <Cartao>
            <h2>Canais</h2>
            <div style={{ padding: '0 14px 10px' }}>{barraCanais}</div>
            {!canaisVistos.length ? <Vazio>Nenhum canal com esse filtro.</Vazio> : null}
            {canaisVistos.map((c) => {
              const e = estado(c);
              return (
                <div key={c.canal} className={`item item-coluna${e === 'sem' ? ' linha-ruim' : ''}`}>
                  <button type="button" className="canal-linha" aria-expanded={menuCanal === c.canal} onClick={() => abrirMenu(c)}>
                    <span className="mono canal-n">{n2(c.canal)}</span>
                    <span className="corpo">
                      <span className="t">{c.nome || (c.ip ? '(sem nome)' : 'livre')}</span>
                      <span className="s mono">{[c.ip, [c.codec, c.resolucao].filter(Boolean).join(' ')].filter(Boolean).join(' · ') || '—'}</span>
                    </span>
                    <span className={`selo ${e === 'ok' ? 'verde' : e === 'sem' ? 'vermelho' : 'cinza'}`}>{e === 'ok' ? 'ok' : e === 'sem' ? 'sem imagem' : e === 'livre' ? 'livre' : 'sem leitura'}</span>
                    {Icone.seta}
                  </button>
                  {menuCanal === c.canal ? (
                    <div className="menu-canal">
                      {c.ip && !modo ? (
                        <div className="acoes-menu">
                          {(() => {
                            const cam = (cams.data ?? []).find((x) => x.ip === c.ip);
                            return cam ? <button type="button" className="btn2" onClick={() => ir(`/cameras/${chaveDa(cam)}/aovivo`)}>{Icone.olho}Ver ao vivo</button> : null;
                          })()}
                          <button type="button" className="btn2" onClick={() => setModo('renomear')}>Renomear</button>
                          <button type="button" className="btn2" onClick={() => setModo('ip')}>Trocar IP</button>
                          {podeExcluir ? (
                            <BotaoArmado classe="btn2 perigo" rotulo="Excluir do gravador" armar={`Toque de novo: tirar ${c.ip} do canal ${n2(c.canal)}`}
                                         indo={trabalhando === `exc-${c.canal}`} desab={!online}
                                         onConfirmar={async () => { if (await editar(`exc-${c.canal}`, { acao: 'excluir', canal: c.canal, antes: { nome: c.nome || '', ip: c.ip || '' } }, `Canal ${n2(c.canal)} esvaziado`)) setMenuCanal(0); }} />
                          ) : <span className="sub-tela">Excluir: só administrador ou dono.</span>}
                        </div>
                      ) : null}

                      {modo === 'renomear' ? (
                        <div className="form-menu">
                          <div className="campo"><label htmlFor={`nm${c.canal}`}>Nome no gravador</label>
                            <div className="caixa"><input id={`nm${c.canal}`} value={form.nome} maxLength={60} onChange={(ev) => setForm({ ...form, nome: ev.target.value })} /></div></div>
                          <div className="acoes-duplas">
                            <button type="button" className="btn2" onClick={() => setModo('')}>Voltar</button>
                            <button type="button" className="btn" disabled={!!trabalhando || !online || !form.nome.trim() || form.nome.trim() === c.nome}
                                    onClick={async () => { if (await editar(`ren-${c.canal}`, { acao: 'renomear', canal: c.canal, nome: form.nome.trim(), antes: { nome: c.nome || '', ip: c.ip || '' } }, `Canal ${n2(c.canal)} renomeado`)) setModo(''); }}>
                              {trabalhando === `ren-${c.canal}` ? 'Salvando…' : 'Salvar nome'}
                            </button>
                          </div>
                        </div>
                      ) : null}

                      {modo === 'ip' || modo === 'cadastrar' ? (
                        <div className="form-menu">
                          <span className="sub-tela">{modo === 'ip'
                            ? `O canal ${n2(c.canal)} passa a buscar a câmera no IP novo. Use quando a câmera mudou de IP ou foi trocada.`
                            : `Cadastrar uma câmera no canal ${n2(c.canal)}, que está livre.`}</span>
                          <div className="campo"><label htmlFor={`ip${c.canal}`}>IP da câmera</label>
                            <div className="caixa"><input id={`ip${c.canal}`} className="mono" inputMode="decimal" value={form.ip} onChange={(ev) => setForm({ ...form, ip: ev.target.value })} placeholder="10.10.9.50" /></div></div>
                          {modo === 'cadastrar' ? (
                            <div className="campo"><label htmlFor={`cn${c.canal}`}>Nome</label>
                              <div className="caixa"><input id={`cn${c.canal}`} value={form.nome} maxLength={60} onChange={(ev) => setForm({ ...form, nome: ev.target.value })} placeholder={`Canal ${n2(c.canal)}`} /></div></div>
                          ) : null}
                          <div className="duas">
                            <div className="campo"><label htmlFor={`cu${c.canal}`}>Usuário da câmera</label>
                              <div className="caixa"><input id={`cu${c.canal}`} value={form.user} autoCapitalize="none" onChange={(ev) => setForm({ ...form, user: ev.target.value })} /></div></div>
                            <div className="campo"><label htmlFor={`cs${c.canal}`}>Senha</label>
                              <div className="caixa"><input id={`cs${c.canal}`} type="password" value={form.senha} autoComplete="off" onChange={(ev) => setForm({ ...form, senha: ev.target.value })} placeholder="a salva, se houver" /></div></div>
                          </div>
                          {form.ip.trim() && !ipValido(form.ip) ? <span className="sub-tela" style={{ color: 'var(--danger)' }}>IP inválido.</span> : null}
                          {modo === 'ip' && form.ip.trim() === (c.ip || '') ? <span className="sub-tela">Digite o IP novo.</span> : null}
                          <div className="acoes-duplas">
                            <button type="button" className="btn2" onClick={() => (c.ip ? setModo('') : setMenuCanal(0))}>{c.ip ? 'Voltar' : 'Cancelar'}</button>
                            <BotaoArmado rotulo={modo === 'ip' ? 'Trocar IP' : 'Cadastrar'}
                                         armar={modo === 'ip' ? `Toque de novo: canal ${n2(c.canal)} → ${form.ip.trim()}` : `Toque de novo: ${form.ip.trim()} no canal ${n2(c.canal)}`}
                                         indo={trabalhando === `ed-${c.canal}`}
                                         desab={!online || !ipValido(form.ip) || (modo === 'ip' && form.ip.trim() === (c.ip || ''))}
                                         onConfirmar={async () => {
                                           const ok = await editar(`ed-${c.canal}`, {
                                             acao: modo === 'ip' ? 'editar' : 'adicionar', canal: c.canal, camera_ip: form.ip.trim(),
                                             nome: (form.nome.trim() || c.nome || `Canal ${n2(c.canal)}`),
                                             camera_user: form.user.trim() || 'admin', ...(form.senha ? { camera_password: form.senha } : {}),
                                             antes: { nome: c.nome || '', ip: c.ip || '' },
                                           }, modo === 'ip' ? `Canal ${n2(c.canal)} agora em ${form.ip.trim()}` : `${form.ip.trim()} cadastrada no canal ${n2(c.canal)}`);
                                           if (ok) { setModo(''); setMenuCanal(0); }
                                         }} />
                          </div>
                        </div>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              );
            })}
          </Cartao>
          <p className="sub-tela" style={{ textAlign: 'center' }}>Toque no canal para ver, renomear, trocar IP, cadastrar ou excluir. Tudo muda o gravador do cliente na hora. Desfazer fica no Histórico do gravador, no SightOps pelo navegador.</p>
        </>
      ) : null}
    </>
  );
}
