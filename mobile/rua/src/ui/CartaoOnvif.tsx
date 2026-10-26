import { useState } from 'react';
import type { Camera } from '../lib/dados';
import { useEu } from '../lib/dados';
import { PERFIS_ONVIF, nomeOnvifValido, onvif, type EstadoOnvif } from '../lib/onvif';
import { useOnline } from '../lib/rede';
import { BotaoArmado, Cartao, Icone, Item, useToast } from './pecas';

/* Ficha da camera Hikvision: usuario ONVIF para gravador de outra marca.
   Ler e so leitura; preparar e apagar gravam na camera (toque duplo). */
export function CartaoOnvif({ cam }: { cam: Camera }) {
  const online = useOnline();
  const toast = useToast();
  const eu = useEu();
  const podeApagar = ['admin', 'owner'].includes(String(eu.data?.role ?? '').toLowerCase());
  const [estado, setEstado] = useState<EstadoOnvif | null>(null);
  const [indo, setIndo] = useState('');
  const [nome, setNome] = useState('onvif');
  const [senha, setSenha] = useState('');
  const [perfil, setPerfil] = useState('administrator');
  const [senhaAdmin, setSenhaAdmin] = useState('');
  const [pedeAdmin, setPedeAdmin] = useState(false);

  async function fazer(qual: string, acao: 'ler' | 'preparar' | 'apagar', extra: Record<string, unknown> = {}, ok = '') {
    setIndo(qual);
    try {
      const r = await onvif(cam, acao, extra, senhaAdmin);
      setEstado(r);
      if (ok) toast(r.passos?.length ? `${ok}: ${r.passos.join(', ')}` : ok);
    } catch (e) {
      const m = (e as Error).message;
      if (/senha/i.test(m)) setPedeAdmin(true);
      toast(m, true);
    } finally {
      setIndo('');
    }
  }

  const max = estado?.senha_max ?? 16;
  return (
    <Cartao>
      <h2>ONVIF</h2>
      <p className="sub-h2">Para pôr esta câmera em gravador de outra marca (Intelbras e afins): ONVIF ligado e um usuário ONVIF próprio.</p>
      {estado ? (
        <div className="ficha">
          <div className="ficha-linha"><span className="ficha-rot">ONVIF</span>
            <span className="ficha-val"><span className={`selo ${estado.onvif_ligado ? 'verde' : 'ambar'}`}>{estado.onvif_ligado ? 'ligado' : 'desligado'}</span></span></div>
        </div>
      ) : null}
      {estado ? (estado.usuarios.length ? estado.usuarios.map((u) => (
        <Item key={u.id} icone={Icone.usuario} titulo={u.nome}
              sub={PERFIS_ONVIF.find(([k]) => k === u.perfil)?.[1] ?? u.perfil}
              direita={podeApagar ? (
                <BotaoArmado classe="link perigo-link" rotulo="Apagar" armar="Toque de novo" enviando="…"
                             indo={indo === `ap-${u.id}`} desab={!online || !!indo}
                             onConfirmar={() => void fazer(`ap-${u.id}`, 'apagar', { id: u.id }, `Usuário ${u.nome} apagado`)} />
              ) : undefined} />
      )) : <p className="sub-tela" style={{ padding: '0 14px' }}>Nenhum usuário ONVIF nesta câmera.</p>) : null}

      <div className="form-cartao">
        <button type="button" className="btn2" disabled={!online || !!indo} onClick={() => void fazer('ler', 'ler')}>
          {Icone.busca}{indo === 'ler' ? 'Lendo a câmera…' : estado ? 'Ler de novo' : 'Ler ONVIF da câmera'}
        </button>
        <span className="rot-secao">Preparar para gravador</span>
        <div className="duas">
          <div className="campo"><label htmlFor="on-nome">Usuário ONVIF</label>
            <div className="caixa"><input id="on-nome" value={nome} autoCapitalize="none" onChange={(e) => setNome(e.target.value)} /></div></div>
          <div className="campo"><label htmlFor="on-senha">Senha (até {max})</label>
            <div className="caixa"><input id="on-senha" type="password" maxLength={max} value={senha} autoComplete="new-password" onChange={(e) => setSenha(e.target.value)} /></div></div>
        </div>
        <div className="seg">
          {PERFIS_ONVIF.map(([k, n]) => <button key={k} type="button" aria-pressed={perfil === k} onClick={() => setPerfil(k)}>{n}</button>)}
        </div>
        {pedeAdmin ? (
          <div className="campo"><label htmlFor="on-adm">Senha de admin da câmera</label>
            <div className="caixa"><input id="on-adm" type="password" value={senhaAdmin} autoComplete="off" onChange={(e) => setSenhaAdmin(e.target.value)} /></div></div>
        ) : null}
        <BotaoArmado rotulo="Ligar ONVIF e criar usuário" enviando="Gravando na câmera…"
                     armar={`Toque de novo: ONVIF ligado + usuário ${nome.trim()} (${PERFIS_ONVIF.find(([k]) => k === perfil)?.[1]})`}
                     indo={indo === 'prep'} desab={!online || !!indo || !nomeOnvifValido(nome) || !senha || senha.length > max}
                     onConfirmar={() => void fazer('prep', 'preparar', { nome: nome.trim(), senha_onvif: senha, perfil }, 'Pronto')} />
        <span className="ajuda">Se o usuário já existe, troca a senha e o perfil. O gravador entra com ele, na porta 80 (ONVIF).</span>
      </div>
    </Cartao>
  );
}
