import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { natural, num, useCameras, useSite, type Camera } from '../lib/termico';
import { Carregando, Erro, Foto, Icone } from '../ui/pecas';
import { formatoDe, VideoVivo } from '../ui/VideoVivo';

// Cada video e um fluxo saindo do link da usina: os seguintes ficam em foto.
const MAX_VIDEOS = 6;

function Tile({ c, tipo, video }: { c: Camera; tipo: 'termica' | 'colorida'; video: boolean }) {
  const lendo = c.ativo && c.leitura === 'ok';
  return (
    <Link to={`/vivo/${c.id}`} className={`mosaico-item ${c.pendentes ? 'tem' : ''}`} style={{ aspectRatio: formatoDe(tipo) }}>
      {video ? <VideoVivo cam={c} tipo={tipo} /> : <Foto caminho={`/api/termico/cameras/${c.id}/agora/${tipo}`} alt={c.nome} recarregar={15000} />}
      {c.pendentes ? <span className="selo alerta">{c.pendentes} novo{c.pendentes === 1 ? '' : 's'}</span>
        : <span className={`bolinha ${lendo ? 'ok' : c.ativo ? 'ruim' : ''}`} aria-label={lendo ? 'Vigiando' : c.ativo ? 'Sem medição' : 'Só vídeo'} />}
      <span className="mosaico-nome"><b>{c.nome}</b><i>{c.fundo_c === null ? '' : `${num(c.fundo_c, 0)} °C`}</i></span>
    </Link>
  );
}

/** Mosaico ao vivo por usina; tocar abre a camera grande. */
export function Ronda() {
  const cams = useCameras();
  const { site, abrirSeletor } = useSite();
  const [modo, setModo] = useState<'termica' | 'colorida'>('termica');
  const grupos = useMemo(() => {
    const m = new Map<string, Camera[]>();
    for (const c of cams.data?.cameras || []) if (!site || c.site === site) m.set(c.site, [...(m.get(c.site) || []), c]);
    return [...m.entries()].sort((a, b) => natural(a[0], b[0])).map(([nome, l]) => [nome, [...l].sort((a, b) => natural(a.nome, b.nome))] as const);
  }, [cams.data, site]);
  let videos = 0;
  return (
    <>
      <header className="topo baixo">
        <span className="topo-anel" aria-hidden="true" />
        <small>Ao vivo · toque para ampliar</small>
        <div className="linha">
          <button type="button" className="bt-usina cresce" onClick={abrirSeletor}>{site || 'Todas as usinas'}{Icone.baixo}</button>
          <div className="alternar claro" role="tablist">
            <button type="button" role="tab" className={modo === 'termica' ? 'on' : ''} onClick={() => setModo('termica')}>Térmica</button>
            <button type="button" role="tab" className={modo === 'colorida' ? 'on' : ''} onClick={() => setModo('colorida')}>Cor</button>
          </div>
        </div>
      </header>
      <div className="pagina">
        {cams.isLoading ? <Carregando /> : cams.error ? <Erro erro={cams.error} /> : null}
        {cams.data && !grupos.length ? <div className="vazio">Nenhuma câmera térmica nesta usina.</div> : null}
        {grupos.map(([nome, lista]) => (
          <section key={nome} className="grupo">
            <div className="linha"><span className="titulo-sec cresce">{nome}</span>
              <small>{lista.filter((c) => c.ativo && c.leitura === 'ok').length} de {lista.length} vigiando</small></div>
            <div className="mosaico">
              {lista.map((c) => <Tile key={`${c.id}-${modo}`} c={c} tipo={modo} video={videos++ < MAX_VIDEOS} />)}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
