import { useState } from 'react';
import { Link } from 'react-router-dom';
import { num, natural, useCameras, useSite } from '../lib/termico';
import { Carregando, Erro, Foto, Icone } from '../ui/pecas';

/** Fotos das cameras a cada 5 s; tocar numa abre o video ao vivo. */
export function Ronda() {
  const cams = useCameras();
  const { site, abrirSeletor } = useSite();
  const [modo, setModo] = useState<'termica' | 'colorida'>('termica');
  const lista = (cams.data?.cameras || []).filter((c) => !site || c.site === site).sort((a, b) => natural(a.nome, b.nome));
  return (
    <>
      <header className="topo baixo">
        <span className="topo-anel" aria-hidden="true" />
        <small>Ronda · toque para ver ao vivo</small>
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
        {cams.data && !lista.length ? <div className="vazio">Nenhuma câmera térmica nesta usina.</div> : null}
        <div className="mosaico">
          {lista.map((c) => (
            <Link key={c.id} to={`/vivo/${c.id}`} className={`mosaico-item ${c.pendentes ? 'tem' : ''}`}>
              <Foto caminho={`/api/termico/cameras/${c.id}/agora/${modo}`} alt={c.nome} recarregar={5000} />
              {c.pendentes ? <span className="selo alerta">{c.pendentes} novo{c.pendentes === 1 ? '' : 's'}</span> : null}
              <span className="mosaico-nome"><b>{c.nome}</b><i>{c.fundo_c === null ? '' : `${num(c.fundo_c, 0)} °C`}</i></span>
            </Link>
          ))}
        </div>
      </div>
    </>
  );
}
