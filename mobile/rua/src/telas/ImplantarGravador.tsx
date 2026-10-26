import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ErroApi, enviar, obter } from '../lib/api';
import { detalhe, useEntidades, type Entidade } from '../lib/dados';
import { useFiltroSite } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';

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
  return { ...q, lista: (q.data ?? []).filter((e) => filtro(e.site, e.connector_id)) };
}

export function Gravadores() {
  const { lista, isPending } = useGravadoresDoSite();
  const ir = useNavigate();
  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Gravador</h1>
        <p className="sub-tela">Canais e troca de câmera de canal.</p>
      </div>
      {isPending ? <Carregando /> : (
        <Cartao>
          {!lista.length ? <Vazio>Nenhum gravador monitorado neste site.</Vazio> : lista.map((e) => {
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
  const conector = param.get('c') ?? '';
  const online = useOnline();
  const { site } = useSite();
  const { lista } = useGravadoresDoSite();
  const toast = useToast();
  const ir = useNavigate();
  const ent: Entidade | undefined = lista.find((e) => detalhe<DetalheNvr>(e).host === host);
  const dn = ent ? detalhe<DetalheNvr>(ent) : {};

  const [cred, setCred] = useState<{ user: string; senha: string } | null>(null);
  const [tentativa, setTentativa] = useState(0);
  const [userIn, setUserIn] = useState('admin');
  const [senhaIn, setSenhaIn] = useState('');
  const base = () => ({ recorder_host: host, connector_id: conector, site: site ?? '',
    ...(cred ? { recorder_user: cred.user, recorder_password: cred.senha } : {}) });

  const rx = useQuery({
    // Senha NUNCA na chave: o cache do app e gravado no aparelho.
    queryKey: ['raiox', host, conector, tentativa],
    queryFn: () => enviar<RaioX>('/api/deployments/recorder-xray', { ...base(), fase: 'essencial' }),
    retry: false,
    staleTime: 60_000,
  });
  const semCred = rx.error instanceof ErroApi && (rx.error.status === 428 || /SEM_CREDENCIAL/.test(rx.error.message));

  const [busca, setBusca] = useState<{ carregando: boolean; erro: string; cams: Achada[] } | null>(null);
  const [macs, setMacs] = useState<Record<string, string>>({});
  const [trabalhando, setTrabalhando] = useState('');
  const [renomeando, setRenomeando] = useState(0);
  const [novoNome, setNovoNome] = useState('');
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

  async function procurar() {
    setBusca({ carregando: true, erro: '', cams: [] });
    try {
      const ips = canais.map((c) => c.ip).filter(Boolean).join(',');
      const [b, m] = await Promise.all([
        enviar<{ cameras?: Achada[] }>('/api/deployments/recorder-buscar-cameras', { ...base(), marca: 'auto' }),
        ips ? obter<{ macs?: Record<string, string> }>(`/api/deployments/recorder-macs?ips=${encodeURIComponent(ips)}`) : Promise.resolve({ macs: {} }),
      ]);
      setMacs(m.macs ?? {});
      setBusca({ carregando: false, erro: '', cams: b.cameras ?? [] });
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
            {canais.map((c) => {
              const e = estado(c);
              const chave = `ren-${c.canal}`;
              return (
                <div key={c.canal} className={`item item-coluna${e === 'sem' ? ' linha-ruim' : ''}`}>
                  <span className="canal-linha">
                    <span className="mono canal-n">{n2(c.canal)}</span>
                    <span className="corpo">
                      <span className="t">{c.nome || (c.ip ? '(sem nome)' : 'livre')}</span>
                      <span className="s mono">{[c.ip, [c.codec, c.resolucao].filter(Boolean).join(' ')].filter(Boolean).join(' · ') || '—'}</span>
                    </span>
                    <span className={`selo ${e === 'ok' ? 'verde' : e === 'sem' ? 'vermelho' : 'cinza'}`}>{e === 'ok' ? 'ok' : e === 'sem' ? 'sem imagem' : e === 'livre' ? 'livre' : 'sem leitura'}</span>
                  </span>
                  {c.ip && renomeando === c.canal ? (
                    <span className="renomear">
                      <span className="caixa"><input aria-label={`Novo nome do canal ${c.canal}`} value={novoNome} maxLength={60} onChange={(ev) => setNovoNome(ev.target.value)} /></span>
                      <button type="button" className="btn2" onClick={() => setRenomeando(0)}>Cancelar</button>
                      <button type="button" className="btn" disabled={!!trabalhando || !novoNome.trim() || novoNome.trim() === c.nome}
                              onClick={async () => { if (await editar(chave, { acao: 'renomear', canal: c.canal, nome: novoNome.trim(), antes: { nome: c.nome || '', ip: c.ip || '' } }, `Canal ${n2(c.canal)} renomeado`)) setRenomeando(0); }}>
                        {trabalhando === chave ? 'Salvando…' : 'Salvar'}
                      </button>
                    </span>
                  ) : c.ip ? (
                    <button type="button" className="link" style={{ alignSelf: 'flex-start' }} onClick={() => { setRenomeando(c.canal); setNovoNome(c.nome || ''); }}>Renomear</button>
                  ) : null}
                </div>
              );
            })}
          </Cartao>
          <p className="sub-tela" style={{ textAlign: 'center' }}>Apontar, pôr câmera e renomear mudam o gravador do cliente na hora. Desfazer fica no Histórico do gravador, no SightOps pelo navegador.</p>
        </>
      ) : null}
    </>
  );
}
