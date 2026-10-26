import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { enviar } from '../lib/api';
import { mesmoSite, siteDoConector, useConectores } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { Carregando, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';

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

function faixa(texto: string): string[] {
  const t = texto.trim();
  if (!t) return [];
  if (/^\d+\.\d+\.\d+\.\d+$/.test(t)) return [t];
  const m = t.match(/^(\d+\.\d+\.\d+)\.(\d+)\s*-\s*(?:\d+\.\d+\.\d+\.)?(\d+)$/);
  if (!m) return [];
  const a = parseInt(m[2], 10); const b = parseInt(m[3], 10);
  if (b < a || b - a > 254) return [];
  return Array.from({ length: b - a + 1 }, (_, i) => `${m[1]}.${a + i}`);
}

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

  const visiveis = useMemo(() => (lista ?? []).filter((d) => verTodas || podeAtivar(d)), [lista, verTodas]);

  async function varrer() {
    if (!con?.id) return;
    setVarrendo(true); setErro(''); setResultados(null);
    try {
      const d = await enviar<{ devices?: Dispositivo[]; scanned?: number; aviso?: string; detail?: string; source?: string }>(
        '/api/deployments/activation/scan', { connector_id: con.id, ips: faixa(range), marca });
      const devs = d.devices ?? [];
      setLista(devs);
      setVerTodas(!devs.some(podeAtivar));
      const pend = devs.filter(podeAtivar).length;
      setResumo(devs.length
        ? `${devs.length} responderam de ${d.scanned ?? '?'} endereços · ${pend} de fábrica · origem: ${d.source === 'manual' ? 'faixa digitada' : 'ARP/DHCP do MikroTik'}`
        : (d.detail || 'Nenhuma câmera respondeu.'));
      if (d.aviso) toast(d.aviso);
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setVarrendo(false);
    }
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

      {!conectores.length ? (
        <Cartao><Vazio>Este site não tem conector MikroTik.<br />A ativação sai pelo MikroTik do site.</Vazio></Cartao>
      ) : (
        <>
          {conectores.length > 1 ? (
            <div className="chips">{conectores.map((c) => (
              <button key={c.id} type="button" className="aba" aria-pressed={con?.id === c.id} onClick={() => setConId(c.id ?? '')}>{c.name}</button>))}</div>
          ) : null}
          {con && !con.online ? <div className="aviso ambar">{Icone.aviso}<span>O conector {con.name} está fora do ar: não dá para varrer agora.</span></div> : null}

          <div className="campo"><span className="lb">Marca</span>
            <div className="seg">
              {(['todas', 'intelbras', 'hikvision'] as const).map((m) => (
                <button key={m} type="button" aria-pressed={marca === m} onClick={() => setMarca(m)}>{m === 'todas' ? 'Todas' : m === 'intelbras' ? 'Intelbras' : 'Hikvision'}</button>))}
            </div></div>
          <details className="avancado">
            <summary>Faixa de IP (opcional)</summary>
            <div className="form-cartao">
              <div className="campo"><label htmlFor="faixa">Faixa ou IP</label>
                <div className="caixa"><input id="faixa" className="mono" value={range} onChange={(e) => setRange(e.target.value)} placeholder="192.168.1.100-200" inputMode="decimal" /></div>
                <span className="ajuda">Vazio: usa o que o MikroTik enxerga (ARP/DHCP).</span></div>
            </div>
          </details>

          <button type="button" className="btn" disabled={varrendo || !online || !con?.online} onClick={varrer}>
            {Icone.busca}{varrendo ? 'Varrendo o site…' : lista ? 'Varrer de novo' : 'Varrer o site'}
          </button>

          {lista ? (
            <Cartao>
              <h2 style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                {verTodas ? 'Câmeras que responderam' : 'De fábrica'}
                <button type="button" className="link" onClick={() => setVerTodas(!verTodas)}>{verTodas ? 'só de fábrica' : 'ver todas'}</button>
              </h2>
              <p className="sub-h2">{resumo}</p>
              {!visiveis.length ? <Vazio>Nenhuma câmera de fábrica.</Vazio> : visiveis.map((d) => {
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
