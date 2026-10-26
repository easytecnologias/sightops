import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { enviar, obter } from '../lib/api';
import type { Camera } from '../lib/dados';
import { useOnline } from '../lib/rede';
import { Cartao, Icone, useToast } from '../ui/pecas';

/*
 * 6 · Ajustar camera: titulo (OSD), IP e reinicio, direto na camera pelo
 * conector (vnat). Mesmas rotas da web: save-camera-title, apply-camera-ip
 * (le mascara/gateway da propria camera, nunca chuta) e activation/reboot.
 * Precisa da senha da camera: o servidor nao a devolve.
 */
type Acao = '' | 'titulo' | 'ip' | 'reiniciar';

export function AjustarCamera({ cam }: { cam: Camera }) {
  const online = useOnline();
  const toast = useToast();
  const qc = useQueryClient();
  const [aberto, setAberto] = useState<Acao>('');
  const [senha, setSenha] = useState('');
  const [titulo, setTitulo] = useState(String(cam.titulo || cam.title || ''));
  const [novoIp, setNovoIp] = useState('');
  const [aviso, setAviso] = useState('');
  const [armado, setArmado] = useState(false);
  const [indo, setIndo] = useState(false);
  const t = useRef<number>();
  useEffect(() => () => window.clearTimeout(t.current), []);

  const conector = cam.remote_connector_id || cam.connector_id || '';
  const ip = cam.ip ?? '';

  function abrir(a: Acao) { setAberto(aberto === a ? '' : a); setArmado(false); setAviso(''); }

  async function conferirIp() {
    setAviso('');
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(novoIp.trim())) { setAviso('IP inválido.'); return false; }
    try {
      const r = await obter<{ in_use?: boolean; matches?: unknown[] }>(
        `/api/deployments/ip-check?ip=${encodeURIComponent(novoIp.trim())}&connector_id=${encodeURIComponent(conector)}&site=${encodeURIComponent(String(cam.site ?? ''))}`);
      if (r.in_use) { setAviso(`O IP ${novoIp.trim()} já está em uso na rede deste site.`); return false; }
    } catch { /* sem conferencia: segue, a camera recusa se colidir */ }
    return true;
  }

  async function executar() {
    if (!senha) { setAviso('Informe a senha da câmera.'); return; }
    if (aberto === 'titulo' && !titulo.trim()) { setAviso('Informe o título.'); return; }
    if (aberto === 'ip' && !armado && !(await conferirIp())) return;
    if (!armado) {
      setArmado(true); window.clearTimeout(t.current);
      t.current = window.setTimeout(() => setArmado(false), 6000);
      return;
    }
    window.clearTimeout(t.current); setArmado(false); setIndo(true); setAviso('');
    try {
      if (aberto === 'titulo') {
        await enviar('/api/deployments/save-camera-title', { ip, title: titulo.trim(), usuario: 'admin', senha, connector_id: conector });
        toast(`Título gravado na câmera: ${titulo.trim()}`);
      } else if (aberto === 'ip') {
        await enviar('/api/deployments/apply-camera-ip', { ip, new_ip: novoIp.trim(), usuario: 'admin', senha, connector_id: conector });
        toast(`A câmera vai responder em ${novoIp.trim()}. Se ela está num gravador, aponte o canal (Implantar › Gravador).`);
      } else if (aberto === 'reiniciar') {
        const r = await enviar<{ rebooted?: number; results?: { ok?: boolean; error?: string }[] }>('/api/deployments/activation/reboot', {
          connector_id: conector, senha, targets: [{ ip, vendor: String(cam.fabricante ?? '').toLowerCase() }],
        });
        if (!r.rebooted) throw new Error(r.results?.[0]?.error || 'a câmera não aceitou reiniciar');
        toast('Câmera reiniciando: volta em cerca de 1 minuto.');
      }
      setAberto('');
      void qc.invalidateQueries({ queryKey: ['cameras'] });
    } catch (e) {
      setAviso((e as Error).message);
    } finally {
      setIndo(false);
    }
  }

  const rotulo = aberto === 'titulo' ? 'Gravar título na câmera' : aberto === 'ip' ? 'Trocar o IP agora' : 'Reiniciar a câmera';

  return (
    <Cartao>
      <h2>Ajustar câmera</h2>
      <p className="sub-h2">Muda a câmera de verdade, pelo conector. Precisa da senha dela.</p>
      <div className="acoes-tres">
        <button type="button" className="btn2" aria-pressed={aberto === 'titulo'} onClick={() => abrir('titulo')}>Título</button>
        <button type="button" className="btn2" aria-pressed={aberto === 'ip'} onClick={() => abrir('ip')}>Trocar IP</button>
        <button type="button" className="btn2" aria-pressed={aberto === 'reiniciar'} onClick={() => abrir('reiniciar')}>Reiniciar</button>
      </div>
      {aberto ? (
        <div className="form-cartao">
          {aberto === 'titulo' ? (
            <div className="campo"><label htmlFor="tit">Título (aparece na imagem e no gravador)</label>
              <div className="caixa"><input id="tit" value={titulo} maxLength={40} onChange={(e) => setTitulo(e.target.value)} /></div></div>
          ) : null}
          {aberto === 'ip' ? (
            <div className="campo"><label htmlFor="nip">IP novo (máscara e gateway ficam os da câmera)</label>
              <div className="caixa"><input id="nip" className="mono" inputMode="decimal" value={novoIp} onChange={(e) => { setNovoIp(e.target.value); setArmado(false); }} placeholder={ip} /></div></div>
          ) : null}
          <div className="campo"><label htmlFor="cs">Senha da câmera (usuário admin)</label>
            <div className="caixa"><input id="cs" type="password" value={senha} onChange={(e) => setSenha(e.target.value)} autoComplete="off" /></div></div>
          {aberto === 'ip' ? <div className="aviso ambar">{Icone.aviso}<span>Depois de trocar, a câmera só responde no IP novo. Se ele estiver fora da rede dela, ela some e só volta no local.</span></div> : null}
          {aviso ? <div className="aviso vermelho">{Icone.aviso}<span>{aviso}</span></div> : null}
          <button type="button" className={`btn${armado ? ' armado' : ''}`} disabled={indo || !online} onClick={executar}>
            {indo ? 'Enviando à câmera…' : armado ? <>{Icone.aviso}Toque de novo para confirmar</> : rotulo}
          </button>
        </div>
      ) : null}
    </Cartao>
  );
}
