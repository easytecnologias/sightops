import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { MARCA } from '../lib/marca';
import { hora, num, useAlertas, useCameras, useSite, type Alerta, type Situacao } from '../lib/termico';
import { Carregando, Erro, Foto, Icone, Logo } from '../ui/pecas';
import { alarmesHoje, Horas } from '../ui/Faixa';
import { VideoVivo } from '../ui/VideoVivo';

const FILTROS: [Situacao, string][] = [['novo', 'Novos'], ['visto', 'Vistos'], ['falso', 'Falsos']];
const ROTULO: Record<Situacao, [string, string]> = { novo: ['Novo', 'alerta'], visto: ['Visto', 'ok'], falso: ['Falso', 'aviso'] };

function Linha({ a }: { a: Alerta }) {
  return (
    <Link to={`/alerta/${a.id}`} className="cartao item">
      <div className="item-foto ferro"><Foto caminho={a.fotos.termico} alt="" /></div>
      <div className="cresce"><b>{a.camera_nome}</b><small>{a.site} · {hora(a.criado_at)}</small></div>
      <span className={`etq ${ROTULO[a.situacao][1]}`}>{ROTULO[a.situacao][0]}</span>
    </Link>
  );
}

export function Inicio() {
  const al = useAlertas();
  const cams = useCameras();
  const { site, abrirSeletor } = useSite();
  const [filtro, setFiltro] = useState<Situacao>('novo');

  const doSite = useMemo(() => (al.data?.alertas || []).filter((a) => !site || a.site === site), [al.data, site]);
  const camsSite = (cams.data?.cameras || []).filter((c) => !site || c.site === site);
  const ativas = camsSite.filter((c) => c.ativo);
  const lendo = ativas.filter((c) => c.leitura === 'ok').length;
  const ruim = ativas.length - lendo;
  const novos = doSite.filter((a) => a.situacao === 'novo');
  const conta = (s: Situacao) => doSite.filter((a) => a.situacao === s).length;
  const lista = doSite.filter((a) => a.situacao === filtro).slice(0, 8);
  const alarme = novos[0];
  const destaque = (alarme && camsSite.find((c) => c.id === alarme.camera_id)) || ativas.find((c) => c.leitura === 'ok' && !c.armado_de) || ativas.find((c) => c.leitura === 'ok') || ativas[0];
  const frase = alarme ? ['Pessoa detectada', `${alarme.camera_nome} · ${hora(alarme.criado_at)}`]
    : !ativas.length ? ['Nada sendo vigiado', 'Ligue uma usina na aba Usinas']
      : ruim ? ['Atenção na vigia', `${ruim} câmera${ruim === 1 ? '' : 's'} sem medição`]
        : ['Perímetro protegido', 'Nenhum alarme sem resposta'];

  return (
    <>
      <header className={`fx ${alarme ? 'al' : ''}`}>
        <div className="fx-top"><Logo tam={36} /><span className="fx-nome">{MARCA.nome}</span>
          <button type="button" className="fx-us" onClick={abrirSeletor}><span>{site || 'Todas as usinas'}</span>{Icone.baixo}</button></div>
        <div className="est"><span className="pul"><i /></span><div><b>{frase[0]}</b><small>{frase[1]}</small></div></div>
        <div className="mets">
          <div><span>Medindo</span><b>{lendo} <em>de {camsSite.length}</em></b></div>
          <div><span>Hoje</span><b>{alarmesHoje(doSite).length}</b></div>
          <div><span>Sem resposta</span><b>{novos.length}</b></div>
        </div>
        <Horas alertas={doSite} />
      </header>
      <div className="pagina">
        {destaque ? (
          <Link to={alarme ? `/alerta/${alarme.id}` : `/vivo/${destaque.id}`} className={`tl ferro ${alarme ? 'al' : ''}`} style={{ aspectRatio: '16 / 9' }} aria-label={`Abrir ${destaque.nome}`}>
            <VideoVivo cam={destaque} tipo="termica" />
            <span className="hu a1"><span className="vv" />AO VIVO</span>
            <span className="hu a2"><span className={`sl ${destaque.leitura === 'ok' ? 'ok' : ''}`}>{destaque.ativo ? 'Vigiando' : 'Só vídeo'}</span></span>
            <span className="hu a3">{destaque.nome}</span>
            {destaque.fundo_c === null ? null : <span className="hu a4">{num(destaque.fundo_c, 0)} °C</span>}
          </Link>
        ) : null}
        <div className="chips">
          {FILTROS.map(([s, nome]) => (
            <button key={s} type="button" className={filtro === s ? 'on' : ''} onClick={() => setFiltro(s)}>{nome} · {conta(s)}</button>
          ))}
        </div>
        {al.isLoading ? <Carregando /> : al.error ? <Erro erro={al.error} /> : null}
        {al.data && !lista.length ? <div className="vazio">{filtro === 'novo' ? 'Nenhum alarme sem resposta.' : 'Nada por aqui.'}</div> : null}
        {lista.map((a) => <Linha key={a.id} a={a} />)}
      </div>
    </>
  );
}
