import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { enviar } from '../lib/api';
import { detalhe, mesmoSite, siteDa, siteDoConector, useCameras, useConectores, useEntidades } from '../lib/dados';
import { useFiltroSite } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';
import { useFiltro } from '../ui/Filtros';
import { OndeProcurar } from '../ui/OndeProcurar';
import { ordenar } from '../lib/ordem';

/* 5 · Ativar camera de fabrica — as mesmas rotas da web (cameraActivation.js). */

type Dispositivo = {
  ip: string; mac?: string; model?: string; firmware?: string; vendor?: string;
  needs_activation?: boolean; pode_tentar?: boolean; estado_indefinido?: boolean; travada?: boolean;
  init_status?: number; needs_email?: boolean; needs_phone?: boolean; pwd_reset_way?: unknown;
};
type ResultadoAtivacao = { ip: string; mac?: string; ok: boolean; error?: string; warning?: string; pos_ativacao?: { reinicio?: { ok?: boolean } } };

const podeAtivar = (d: Dispositivo) => !!(d.needs_activation || d.pode_tentar);
const ehHik = (d: Dispositivo) => String(d.vendor ?? '').toLowerCase() === 'hikvision';

function estado(d: Dispositivo): [string, string] {
  if (d.travada) return ['travada', 'cinza'];
  if (d.needs_activation) return ['de fábrica', 'ambar'];
  if (d.estado_indefinido) return ['indefinido', 'cinza'];
  if (d.init_status === 2) return ['já ativada', 'verde'];
  return ['modelo antigo', 'cinza'];
}

const MAX_IPS = 2048;         // teto da busca manual (o servidor sonda 256 por vez)
const LOTE = 256;

const ipNum = (ip: string) => ip.split('.').reduce((n, o) => n * 256 + Number(o), 0);
const numIp = (n: number) => [24, 16, 8, 0].map((d) => Math.floor(n / 2 ** d) % 256).join('.');
const ipValido = (ip: string) => /^\d{1,3}(\.\d{1,3}){3}$/.test(ip) && ip.split('.').every((o) => Number(o) <= 255);

/**
 * Expande o que o tecnico digitou: "10.10.10.0/24", "10.10.10.1-254",
 * "10.10.10.1-10.10.10.50", IP solto, ou varios separados por virgula/espaco.
 */
export function expandir(texto: string): { ips: string[]; erro: string } {
  const ips = new Set<string>();
  for (const pedaco of texto.split(/[\s,;]+/).filter(Boolean)) {
    const cidr = pedaco.match(/^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/);
    const faixa = pedaco.match(/^(\d{1,3}(?:\.\d{1,3}){3})-(\d{1,3}(?:\.\d{1,3}){3}|\d{1,3})$/);
    if (cidr && ipValido(cidr[1])) {
      const bits = Number(cidr[2]);
      if (bits < 21 || bits > 32) return { ips: [], erro: `Rede ${pedaco} grande demais: use /21 ou menor (ex.: /24).` };
      const tam = 2 ** (32 - bits);
      const base = ipNum(cidr[1]) - (ipNum(cidr[1]) % tam);
      // Sem o endereco de rede e o de broadcast quando a rede tem mais de 2.
      for (let i = tam > 2 ? 1 : 0; i < (tam > 2 ? tam - 1 : tam); i++) ips.add(numIp(base + i));
    } else if (faixa && ipValido(faixa[1])) {
      const fimTxt = faixa[2].includes('.') ? faixa[2] : faixa[1].replace(/\d+$/, faixa[2]);
      if (!ipValido(fimTxt)) return { ips: [], erro: `Faixa inválida: ${pedaco}` };
      const ini = ipNum(faixa[1]);
      const fim = ipNum(fimTxt);
      if (fim < ini) return { ips: [], erro: `Faixa ao contrário: ${pedaco}` };
      for (let n = ini; n <= fim && ips.size <= MAX_IPS; n++) ips.add(numIp(n));
    } else if (ipValido(pedaco)) {
      ips.add(pedaco);
    } else {
      return { ips: [], erro: `Não entendi “${pedaco}”. Use 10.10.10.0/24, 10.10.10.1-50 ou um IP.` };
    }
    if (ips.size > MAX_IPS) return { ips: [], erro: `Mais de ${MAX_IPS} endereços: divida a busca.` };
  }
  return { ips: [...ips], erro: '' };
}

/** IP de fabrica comum, que nao aparece no ARP enquanto a camera nao "fala". */
const FABRICA: [string, string][] = [['192.168.1.108', 'fábrica Intelbras'], ['192.168.1.64', 'fábrica Hikvision']];

export function CameraAtivar() {
  const online = useOnline();
  const { site } = useSite();
  const cons = useConectores();
  const toast = useToast();
  const ir = useNavigate();
  // A ativacao sai pelo MikroTik do site (conector RouterOS).
  const conectores = (cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site)
    && String(c.type ?? '').toLowerCase() === 'routeros');
  const [conId, setConId] = useState('');
  const con = conectores.find((c) => c.id === conId) ?? conectores[0];

  const [marca, setMarca] = useState<'todas' | 'intelbras' | 'hikvision'>('todas');
  const [range, setRange] = useState('');
  const [varrendo, setVarrendo] = useState(false);
  const [lista, setLista] = useState<Dispositivo[] | null>(null);
  const [resumo, setResumo] = useState('');
  const [verTodas, setVerTodas] = useState(false);
  const [alvo, setAlvo] = useState<Dispositivo | null>(null);

  // formulario
  const [senha, setSenha] = useState('');
  const [senha2, setSenha2] = useState('');
  const [email, setEmail] = useState('');
  const [perguntas, setPerguntas] = useState([{ id: 1, r: '' }, { id: 2, r: '' }, { id: 3, r: '' }]);
  const [dhcp, setDhcp] = useState(true);
  const [ativando, setAtivando] = useState(false);
  const [erro, setErro] = useState('');
  const [resultados, setResultados] = useState<ResultadoAtivacao[] | null>(null);
  // A senha recem-criada segue (so em memoria) para o Instalar, sem redigitar.
  const [senhaUsada, setSenhaUsada] = useState('');

  const doTipo = useMemo(() => (lista ?? []).filter((d) => verTodas || podeAtivar(d)), [lista, verTodas]);
  const { lista: visiveis, barra: barraLista } = useFiltro(doTipo, {
    texto: (d) => [d.ip, d.mac, d.model, d.vendor], dica: 'IP, MAC ou modelo',
    extra: { rotulo: 'Fabricante', todos: 'Todos os fabricantes', de: (d) => d.vendor || 'sem fabricante' },
  });

  const [progresso, setProgresso] = useState('');
  const [origem, setOrigem] = useState<'arp' | 'faixa' | ''>('');

  // Redes do site: as /24 onde ja ha camera (inventario + monitoramento).
  // E nelas que a camera nova costuma cair -- e o que o tecnico digitaria.
  const filtro = useFiltroSite(site);
  const cams = useCameras();
  const entCams = useEntidades('camera');
  const redes = useMemo(() => {
    const conta = new Map<string, number>();
    const somar = (ip?: string) => {
      if (!ip || !ipValido(ip)) return;
      const r = `${ip.split('.').slice(0, 3).join('.')}.0/24`;
      conta.set(r, (conta.get(r) ?? 0) + 1);
    };
    for (const c of cams.data ?? []) if (filtro(siteDa(c), c.remote_connector_id || c.connector_id)) somar(c.ip);
    for (const e of entCams.data ?? []) if (filtro(e.site, e.connector_id)) somar(detalhe<{ ip?: string }>(e).ip);
    return [...conta.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
  }, [cams.data, entCams.data, filtro]);
  const pedido = useMemo(() => expandir(range), [range]);

  async function sondar(ips: string[], tipo: 'arp' | 'faixa') {
    if (!con?.id) return;
    setVarrendo(true); setErro(''); setResultados(null); setOrigem(tipo);
    const achados = new Map<string, Dispositivo>();
    let sondados = 0;
    try {
      // Sem faixa: uma chamada (o servidor usa ARP/DHCP + IP de fabrica).
      // Com faixa: lotes de 256, que e o que o servidor sonda por vez.
      const lotes: string[][] = tipo === 'arp' ? [[]]
        : Array.from({ length: Math.ceil(ips.length / LOTE) }, (_, i) => ips.slice(i * LOTE, (i + 1) * LOTE));
      for (let i = 0; i < lotes.length; i++) {
        if (lotes.length > 1) setProgresso(`Sondando ${Math.min((i + 1) * LOTE, ips.length)} de ${ips.length}…`);
        const d = await enviar<{ devices?: Dispositivo[]; scanned?: number; aviso?: string; detail?: string }>(
          '/api/deployments/activation/scan', { connector_id: con.id, ips: lotes[i], marca });
        for (const dev of d.devices ?? []) achados.set(dev.ip, dev);
        sondados += d.scanned ?? lotes[i].length;
        if (d.aviso) toast(d.aviso);
        setLista(ordenar([...achados.values()], (x) => x.ip));
      }
      const devs = ordenar([...achados.values()], (x) => x.ip);
      setVerTodas(!devs.some(podeAtivar));
      const pend = devs.filter(podeAtivar).length;
      setResumo(`${devs.length} responderam de ${sondados} endereços · ${pend} de fábrica · ${tipo === 'arp' ? 'pelo ARP/DHCP do MikroTik' : 'na faixa pedida'}`);
    } catch (e) {
      setErro((e as Error).message);
      setLista([...achados.values()]);
    } finally {
      setVarrendo(false); setProgresso('');
    }
  }

  function varrer() { void sondar([], 'arp'); }
  function procurarFaixa() {
    if (pedido.erro || !pedido.ips.length) { setErro(pedido.erro || 'Digite uma rede, faixa ou IP.'); return; }
    void sondar(pedido.ips, 'faixa');
  }
  function varrerRedesDoSite() {
    const texto = redes.map(([r]) => r).join(', ');
    setRange(texto);
    void sondar(expandir(texto).ips, 'faixa');
  }
  function adicionar(t: string) {
    setRange((r) => (r.split(/[\s,;]+/).includes(t) ? r : [r.trim(), t].filter(Boolean).join(', ')));
  }

  async function ativar() {
    if (!alvo || !con?.id) return;
    setErro('');
    const hik = ehHik(alvo);
    if (!senha) { setErro('Defina a senha da câmera.'); return; }
    if (senha !== senha2) { setErro('As duas senhas não batem.'); return; }
    if (hik && senha.length > 15) { setErro('Na Hikvision a senha vai até 15 caracteres.'); return; }
    if (alvo.needs_email && !email.trim()) { setErro('Este modelo exige e-mail de recuperação.'); return; }
    if (hik) {
      if (perguntas.some((p) => !p.r.trim())) { setErro('A Hikvision exige as 3 respostas de recuperação.'); return; }
      if (new Set(perguntas.map((p) => p.id)).size !== 3) { setErro('As 3 perguntas têm de ser diferentes.'); return; }
    }
    setAtivando(true);
    try {
      const d = await enviar<{ activated?: number; failed?: number; results?: ResultadoAtivacao[] }>('/api/deployments/activation/run', {
        connector_id: con.id, usuario: 'admin', senha, email: email.trim(), site: site ?? '',
        perguntas: hik ? perguntas.map((p) => ({ id: p.id, resposta: p.r.trim() })) : [],
        dhcp: hik && dhcp,
        targets: [{ ip: alvo.ip, mac: alvo.mac, model: alvo.model, vendor: alvo.vendor, pwd_reset_way: alvo.pwd_reset_way }],
      });
      setResultados((d.results ?? []).map((r) => ({ ...r, mac: r.mac || alvo.mac })));
      setSenhaUsada(senha);
      setAlvo(null);
      setSenha(''); setSenha2('');
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setAtivando(false);
    }
  }

  if (cons.isPending && !cons.data) return <Carregando />;

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Ativar câmera</h1>
        <p className="sub-tela">Câmera de fábrica (sem senha), pela rede do site.</p>
      </div>

      <OndeProcurar conector={con} aoTrocarConector={(id) => { setConId(id); setLista(null); setResultados(null); setRange(''); }} />

      {!conectores.length ? (
        <Cartao><Vazio>Este site não tem conector MikroTik.<br />Toque em “Trocar” e escolha o site onde a câmera está.</Vazio></Cartao>
      ) : (
        <>
          {con && !con.online ? <div className="aviso ambar">{Icone.aviso}<span>O conector {con.name} está fora do ar: não dá para varrer agora.</span></div> : null}

          <div className="campo"><span className="lb">Marca</span>
            <div className="seg">
              {(['todas', 'intelbras', 'hikvision'] as const).map((m) => (
                <button key={m} type="button" aria-pressed={marca === m} onClick={() => setMarca(m)}>{m === 'todas' ? 'Todas' : m === 'intelbras' ? 'Intelbras' : 'Hikvision'}</button>))}
            </div></div>
          <button type="button" className="btn" disabled={varrendo || !online || !con?.online} onClick={varrer}>
            {Icone.busca}{varrendo && origem === 'arp' ? 'Varrendo o site…' : 'Varrer o site (ARP/DHCP)'}
          </button>
          <p className="sub-tela">Rápido, mas só vê o que o MikroTik já listou: câmera recém-ligada ou com IP fixo pode não estar lá.</p>

          <Cartao>
            <h2>Procurar numa rede</h2>
            <div className="form-cartao">
              {redes.length ? (
                <div className="campo"><span className="lb">Redes deste site</span>
                  <div className="chips chips-quebra">
                    {redes.map(([r, n]) => (
                      <button key={r} type="button" className="aba" aria-pressed={range.includes(r)} onClick={() => adicionar(r)}>
                        <span className="mono">{r}</span> · {n} {n === 1 ? 'câmera' : 'câmeras'}
                      </button>
                    ))}
                  </div></div>
              ) : null}
              <div className="chips chips-quebra">
                {FABRICA.map(([ip, n]) => (
                  <button key={ip} type="button" className="aba" aria-pressed={range.includes(ip)} onClick={() => adicionar(ip)}><span className="mono">{ip}</span> · {n}</button>
                ))}
              </div>
              <div className="campo"><label htmlFor="faixa">Rede, faixa ou IP</label>
                <div className="caixa"><input id="faixa" className="mono" value={range} onChange={(e) => setRange(e.target.value)}
                       placeholder="10.10.10.0/24 ou 10.10.10.1-50" inputMode="text" autoCapitalize="none" autoCorrect="off" spellCheck={false} /></div>
                <span className="ajuda" style={pedido.erro && range.trim() ? { color: 'var(--danger)' } : undefined}>
                  {range.trim() ? (pedido.erro || `${pedido.ips.length} endereços${pedido.ips.length > LOTE ? ` em ${Math.ceil(pedido.ips.length / LOTE)} lotes` : ''}`)
                    : 'Aceita /24, faixa com traço, IP solto ou vários separados por vírgula.'}
                </span></div>
              <button type="button" className="btn2" disabled={varrendo || !online || !con?.online || !range.trim() || !!pedido.erro} onClick={procurarFaixa}>
                {Icone.busca}{varrendo && origem === 'faixa' ? (progresso || 'Sondando…') : 'Procurar nesta faixa'}
              </button>
            </div>
          </Cartao>

          {lista && origem === 'arp' && !varrendo && !lista.some(podeAtivar) && redes.length ? (
            <div className="aviso ambar">{Icone.aviso}
              <span>Nenhuma câmera de fábrica no ARP/DHCP. Se ela acabou de ser ligada, ainda não está lá.{' '}
                <button type="button" className="link" onClick={varrerRedesDoSite}>Varrer as {redes.length} redes do site</button>
              </span>
            </div>
          ) : null}

          {lista ? (
            <Cartao>
              <h2 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                {verTodas ? 'Câmeras que responderam' : 'De fábrica'}
                <button type="button" className="link" onClick={() => setVerTodas(!verTodas)}>{verTodas ? 'só de fábrica' : 'ver todas'}</button>
              </h2>
              <p className="sub-h2">{resumo}</p>
              {doTipo.length > 3 ? <div style={{ padding: '0 14px 10px' }}>{barraLista}</div> : null}
              {!visiveis.length ? <Vazio>{doTipo.length ? 'Nenhuma com esse filtro.' : 'Nenhuma câmera de fábrica.'}</Vazio> : visiveis.map((d) => {
                const [txt, cor] = estado(d);
                return (
                  <Item key={d.mac || d.ip} icone={Icone.raio} titulo={d.ip}
                        sub={[d.model, d.vendor, d.mac].filter(Boolean).join(' · ')}
                        onClick={podeAtivar(d) ? () => { setAlvo(d); setErro(''); setResultados(null); } : undefined}
                        direita={<span className={`selo ${cor}`}>{txt}</span>} />
                );
              })}
            </Cartao>
          ) : null}

          {alvo ? (
            <Cartao>
              <h2>Ativar {alvo.ip}</h2>
              <p className="sub-h2">{[alvo.model, alvo.vendor].filter(Boolean).join(' · ')} · usuário admin</p>
              <div className="form-cartao">
                <div className="campo"><label htmlFor="s1">Senha nova</label>
                  <div className="caixa"><input id="s1" type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="new-password" /></div></div>
                <div className="campo"><label htmlFor="s2">Repita a senha</label>
                  <div className="caixa"><input id="s2" type="password" value={senha2} onChange={(e) => setSenha2(e.target.value)} autoComplete="new-password" /></div>
                  <span className="ajuda">A senha fica guardada no cofre do site para o gravador usar.</span></div>
                <div className="campo"><label htmlFor="em">E-mail de recuperação {alvo.needs_email ? '' : '(opcional)'}</label>
                  <div className="caixa"><input id="em" type="email" inputMode="email" autoCapitalize="none" value={email} onChange={(e) => setEmail(e.target.value)} /></div></div>
                {ehHik(alvo) ? (
                  <>
                    {perguntas.map((p, i) => (
                      <div key={i} className="campo">
                        <label htmlFor={`q${i}`}>Pergunta de recuperação {i + 1}</label>
                        <select id={`q${i}`} className="caixa-sel" value={p.id}
                                onChange={(e) => setPerguntas(perguntas.map((x, j) => (j === i ? { ...x, id: Number(e.target.value) } : x)))}>
                          {Array.from({ length: 15 }, (_, n) => n + 1).map((n) => <option key={n} value={n}>Pergunta {n}</option>)}
                        </select>
                        <div className="caixa"><input aria-label={`Resposta ${i + 1}`} placeholder="Resposta" value={p.r}
                                                      onChange={(e) => setPerguntas(perguntas.map((x, j) => (j === i ? { ...x, r: e.target.value } : x)))} /></div>
                      </div>
                    ))}
                    <label className="chave-linha"><span>Pegar IP por DHCP depois de ativar (reinicia a câmera)</span>
                      <input type="checkbox" className="chave" checked={dhcp} onChange={(e) => setDhcp(e.target.checked)} /></label>
                  </>
                ) : null}
                <div className="aviso ambar">{Icone.aviso}<span>Isto grava a senha <b>agora</b> na câmera. Anote a senha: ela não aparece de novo aqui.</span></div>
                <div className="acoes-duplas">
                  <button type="button" className="btn2" onClick={() => setAlvo(null)}>Cancelar</button>
                  <button type="button" className="btn" disabled={ativando || !online} onClick={ativar}>{ativando ? 'Ativando…' : 'Ativar câmera'}</button>
                </div>
              </div>
            </Cartao>
          ) : null}

          {resultados ? (
            <Cartao>
              <h2>Resultado</h2>
              {resultados.map((r) => (
                <Item key={r.ip} ponto={r.ok ? 'verde' : 'vermelho'} titulo={r.ip}
                      sub={r.ok
                        ? ['ativada', r.warning, r.pos_ativacao?.reinicio?.ok ? 'reiniciando para pegar IP do site (~1 min)' : ''].filter(Boolean).join(' · ')
                        : r.error || 'falhou'}
                      direita={<span className={`selo ${r.ok ? 'verde' : 'vermelho'}`}>{r.ok ? 'ok' : 'erro'}</span>} />
              ))}
              {resultados.filter((r) => r.ok).map((r) => (
                <div key={`i-${r.ip}`} className="form-cartao">
                  <button type="button" className="btn" onClick={() => ir('/implantar/instalar', { state: { ip: r.ip, mac: r.mac, senha: senhaUsada } })}>
                    {Icone.camera}Instalar {r.ip}: nome e gravador
                  </button>
                </div>
              ))}
            </Cartao>
          ) : null}

          {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}
        </>
      )}
    </>
  );
}
