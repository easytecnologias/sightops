import { useNavigate } from 'react-router-dom';
import { detalhe, ipDaOlt, mesmoSite, siteDoConector, useConectores } from '../lib/dados';
import { horaCurta, quando, useSiteMonitor } from '../lib/monitor';
import { NOME_ACAO, useAcoes, useRascunhoOnu } from '../lib/implantar';
import { useOnline } from '../lib/rede';
import { useSite } from '../lib/site';
import { useOltsDoSite } from './ImplantarOnu';
import { Cartao, Icone, Item, Vazio } from '../ui/pecas';

/* 1 · Hub Implantar: comandos em equipamento vivo, pelo tunel do conector. */
export function Implantar() {
  const online = useOnline();
  const { site } = useSite();
  const cons = useConectores();
  const m = useSiteMonitor(site);
  const acoes = useAcoes();
  const olts = useOltsDoSite();
  const { zerar } = useRascunhoOnu();
  const ir = useNavigate();

  const doSite = (cons.data ?? []).filter((c) => site && mesmoSite(siteDoConector(c), site));
  const tunel = doSite.some((c) => c.online);
  const semVideo = m.nvrs.reduce((n, e) => {
    const d = detalhe<{ canais_sem_imagem?: number; canais_offline?: number }>(e);
    return n + Number(d.canais_sem_imagem ?? 0) + Number(d.canais_offline ?? 0);
  }, 0);
  const hoje = new Date(); hoje.setHours(0, 0, 0, 0);
  // Acao do site: pela OLT/gravador do site (o log guarda o IP em olt_ip) ou pelo nome.
  const equipamentos = new Set([...olts.lista.map(ipDaOlt), ...m.nvrs.map((e) => String(detalhe<{ host?: string }>(e).host ?? ''))].filter(Boolean));
  const feitas = (acoes.data ?? []).filter((a) => a.action !== 'onu_signal' && (quando(a.created_at) ?? 0) >= hoje.getTime()
    && (!site || equipamentos.has(String(a.olt_ip ?? '')) || mesmoSite(a.site, site)));

  return (
    <>
      <div className="linha-titulo">
        <div>
          <h1 className="titulo-tela">Implantar</h1>
          <p className="sub-tela">Comandos em equipamento vivo, pelo túnel do conector.</p>
        </div>
      </div>

      {!online ? (
        <div className="aviso ambar">{Icone.aviso}<span><b>Sem sinal</b> · nada aqui funciona agora, e não dá para deixar na fila.</span></div>
      ) : !doSite.length ? (
        <div className="aviso ambar">{Icone.aviso}<span>Este site não tem conector: os comandos não têm por onde chegar ao equipamento.</span></div>
      ) : tunel ? (
        <div className="aviso verde">{Icone.onu}<span><b>Túnel ativo</b> · as ações abaixo chegam ao equipamento agora</span></div>
      ) : (
        <div className="aviso vermelho">{Icone.aviso}<span><b>Conector fora do ar</b> · os comandos não chegam até ele voltar.</span></div>
      )}

      <Cartao>
        <h2>Ações de campo</h2>
        <p className="sub-h2">Todas exigem sinal no momento do toque</p>
        <Item icone={Icone.onu} titulo="Ativar ONU" sub="Autorizar ONU nova na PON"
              onClick={() => { zerar(); ir('/implantar/onu'); }} direita={Icone.seta} />
        <Item icone={Icone.raio} titulo="Ativar câmera" sub="Câmera de fábrica, sem senha"
              onClick={() => ir('/implantar/camera')} direita={Icone.seta} />
        <Item icone={Icone.gravador} titulo="Gravador" sub="Canais e troca de câmera de canal"
              onClick={() => ir('/implantar/gravador')}
              direita={semVideo ? <span className="selo vermelho">{semVideo} sem vídeo</span> : Icone.seta} />
        <Item icone={Icone.engrenagem} titulo="Ajustar câmera" sub="Trocar título, IP e reiniciar"
              onClick={() => ir('/cameras')} direita={Icone.seta} />
      </Cartao>

      <Cartao>
        <h2>Feito hoje</h2>
        <p className="sub-h2">O que o SightOps mandou aos equipamentos hoje</p>
        {!feitas.length ? <Vazio>Nada feito hoje ainda.</Vazio> : feitas.slice(0, 10).map((a, i) => (
          <Item key={`${a.created_at}-${i}`} ponto={a.ok ? 'verde' : 'vermelho'}
                titulo={`${a.ok ? NOME_ACAO[a.action] ?? a.action : `Falhou: ${NOME_ACAO[a.action] ?? a.action}`}${a.action.startsWith('recorder') ? '' : a.pon ? ` · PON ${a.pon}${a.onu ? `/${a.onu}` : ''}` : ''}`}
                sub={[a.serial, a.vlan ? `VLAN ${a.vlan}` : '', horaCurta(a.created_at)].filter(Boolean).join(' · ')} />
        ))}
      </Cartao>
    </>
  );
}
