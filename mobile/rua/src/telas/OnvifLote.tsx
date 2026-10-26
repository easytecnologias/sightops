import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { tituloDa, type Camera } from '../lib/dados';
import { PERFIS_ONVIF, ehHikvision, nomeOnvifValido, onvif } from '../lib/onvif';
import { useOnline } from '../lib/rede';
import { useCamerasDoSite } from '../screens/Cameras';
import { useFiltro } from '../ui/Filtros';
import { BotaoArmado, Cartao, Icone, Item, Vazio, useToast } from '../ui/pecas';

type Resultado = { ok: boolean; texto: string };

/* Implantar > Usuario ONVIF: o mesmo usuario em varias cameras Hikvision do
   site (camera em gravador de outra marca). Uma camera por vez, com o
   resultado de cada uma. EQUIPAMENTO VIVO. */
export function OnvifLote() {
  const online = useOnline();
  const toast = useToast();
  const ir = useNavigate();
  const { cameras, localDa, gravadorDa } = useCamerasDoSite();
  const hik = useMemo(() => cameras.filter(ehHikvision), [cameras]);
  const { lista, barra } = useFiltro(hik, {
    texto: (c) => [tituloDa(c), c.ip, c.modelo], dica: 'Nome ou IP', unidade: 'câmeras Hikvision',
    local: localDa, extra: { rotulo: 'Gravador', todos: 'Todos os gravadores', de: gravadorDa },
  });
  const [marcadas, setMarcadas] = useState<Set<string>>(new Set());
  const [nome, setNome] = useState('onvif');
  const [senha, setSenha] = useState('');
  const [perfil, setPerfil] = useState('administrator');
  const [senhaAdmin, setSenhaAdmin] = useState('');
  const [rodando, setRodando] = useState('');
  const [resultados, setResultados] = useState<Record<string, Resultado>>({});

  const alternar = (ip: string) => setMarcadas((m) => { const n = new Set(m); if (n.has(ip)) n.delete(ip); else n.add(ip); return n; });
  const todasVisiveis = lista.length > 0 && lista.every((c) => marcadas.has(c.ip ?? ''));

  async function aplicar() {
    const alvo = hik.filter((c) => marcadas.has(c.ip ?? ''));
    let ok = 0;
    for (const [i, c] of alvo.entries()) {
      setRodando(`${i + 1} de ${alvo.length}: ${tituloDa(c)}`);
      try {
        const r = await onvif(c, 'preparar', { nome: nome.trim(), senha_onvif: senha, perfil }, senhaAdmin);
        setResultados((m) => ({ ...m, [c.ip!]: { ok: true, texto: (r.passos ?? []).join(', ') || 'pronto' } }));
        ok += 1;
      } catch (e) {
        setResultados((m) => ({ ...m, [c.ip!]: { ok: false, texto: (e as Error).message } }));
      }
    }
    setRodando('');
    toast(ok === alvo.length ? `Usuário ${nome.trim()} em ${ok} câmera(s).` : `${ok} de ${alvo.length} ok — veja as que falharam.`, ok !== alvo.length);
  }

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Usuário ONVIF</h1>
        <p className="sub-tela">Câmera Hikvision em gravador de outra marca: liga o ONVIF e cria o usuário, em várias de uma vez.</p>
      </div>
      {barra}
      <Cartao>
        <div className="linha-secao" style={{ padding: '0 14px' }}>
          <span className="rot-secao">{marcadas.size} marcada(s)</span>
          <button type="button" className="link" disabled={!lista.length} onClick={() => setMarcadas((m) => {
            const n = new Set(m);
            for (const c of lista) { if (todasVisiveis) n.delete(c.ip ?? ''); else n.add(c.ip ?? ''); }
            return n;
          })}>{todasVisiveis ? 'Desmarcar estas' : `Marcar estas ${lista.length}`}</button>
        </div>
        {!hik.length ? <Vazio>Nenhuma câmera Hikvision cadastrada neste site.</Vazio> : !lista.length ? <Vazio>Nada com esse filtro.</Vazio>
          : lista.slice(0, 200).map((c: Camera) => {
            const r = resultados[c.ip ?? ''];
            return (
              <Item key={c.ip} ponto={r ? (r.ok ? 'verde' : 'vermelho') : undefined}
                    // A linha inteira marca/desmarca; a caixa so mostra (sem evento proprio,
                    // senao o toque nela contava duas vezes).
                    icone={<input type="checkbox" checked={marcadas.has(c.ip ?? '')} readOnly tabIndex={-1} aria-hidden="true"
                                  style={{ width: 22, height: 22, pointerEvents: 'none' }} />}
                    titulo={tituloDa(c)}
                    sub={[c.ip, localDa(c), r?.texto].filter(Boolean).join(' · ')}
                    onClick={() => alternar(c.ip ?? '')} />
            );
          })}
      </Cartao>
      <Cartao>
        <h2>Aplicar nas marcadas</h2>
        <div className="form-cartao">
          <div className="duas">
            <div className="campo"><label htmlFor="ol-nome">Usuário ONVIF</label>
              <div className="caixa"><input id="ol-nome" value={nome} autoCapitalize="none" onChange={(e) => setNome(e.target.value)} /></div></div>
            <div className="campo"><label htmlFor="ol-senha">Senha (até 16)</label>
              <div className="caixa"><input id="ol-senha" type="password" maxLength={16} value={senha} autoComplete="new-password" onChange={(e) => setSenha(e.target.value)} /></div></div>
          </div>
          <div className="seg">
            {PERFIS_ONVIF.map(([k, n]) => <button key={k} type="button" aria-pressed={perfil === k} onClick={() => setPerfil(k)}>{n}</button>)}
          </div>
          <div className="campo"><label htmlFor="ol-adm">Senha de admin das câmeras</label>
            <div className="caixa"><input id="ol-adm" type="password" value={senhaAdmin} placeholder="vazio = a salva de cada câmera / do site" autoComplete="off" onChange={(e) => setSenhaAdmin(e.target.value)} /></div></div>
          {rodando ? <p className="sub-tela">Aplicando {rodando}…</p> : null}
          <BotaoArmado rotulo={`Aplicar em ${marcadas.size} câmera(s)`} enviando="Gravando nas câmeras…"
                       armar={`Toque de novo: ONVIF + usuário ${nome.trim()} em ${marcadas.size} câmera(s)`}
                       indo={!!rodando} desab={!online || !marcadas.size || !nomeOnvifValido(nome) || !senha || senha.length > 16}
                       onConfirmar={() => void aplicar()} />
          <span className="ajuda">Liga o ONVIF onde estiver desligado e cria o usuário; se já existe, troca a senha e o perfil. Muda as câmeras na hora.</span>
        </div>
      </Cartao>
    </>
  );
}
