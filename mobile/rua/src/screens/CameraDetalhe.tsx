import { useNavigate, useParams } from 'react-router-dom';
import { chaveDa, estadoDa, siteDa, tituloDa, useCameras } from '../lib/dados';
import { useFoto } from '../lib/foto';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Titulo, Vazio } from '../ui/pecas';

function Ficha({ rot, val, mono }: { rot: string; val?: string | number | null; mono?: boolean }) {
  if (val === undefined || val === null || val === '') return null;
  return (
    <div className="ficha-linha">
      <span className="ficha-rot">{rot}</span>
      <span className={`ficha-val${mono ? ' mono' : ''}`}>{val}</span>
    </div>
  );
}

export function CameraDetalhe() {
  const { chave } = useParams();
  const ir = useNavigate();
  const q = useCameras();

  const cam = (q.data ?? []).find((c) => chaveDa(c) === chave);
  const foto = useFoto(cam?.snapshot_url);

  if (q.isPending && !q.data) return <Carregando />;
  if (!cam) {
    return (
      <Cartao>
        <Vazio>Camera nao encontrada no projeto baixado.</Vazio>
      </Cartao>
    );
  }

  const e = estadoDa(cam);
  const coord = [cam.lat, cam.lon].filter(Boolean).join(', ') || cam.physical_location || '';
  const temCoord = Boolean(cam.lat && cam.lon);

  return (
    <>
      <div className="linha-topo">
        <button type="button" className="voltar" onClick={() => ir(-1)} aria-label="Voltar">
          {Icone.volta}
        </button>
        <Titulo titulo={tituloDa(cam)} sub={siteDa(cam) || undefined} />
      </div>

      <Cartao>
        <div className="foto-caixa">
          {foto.estado === 'pronta' && foto.url ? (
            <img src={foto.url} alt={`Ultima imagem de ${tituloDa(cam)}`} />
          ) : (
            <div className="foto-vazia">
              {foto.estado === 'carregando' ? 'Carregando a imagem…'
                : foto.estado === 'sem-sinal' ? 'A foto precisa de sinal — ela nao cabe na copia do aparelho.'
                : foto.estado === 'sem-foto' ? 'Esta camera ainda nao tem foto no inventario.'
                : 'Nao consegui trazer a imagem agora.'}
            </div>
          )}
        </div>
        <div className="foto-pe">
          <span className={`selo ${e === 'online' ? 'verde' : e === 'offline' ? 'ambar' : 'cinza'}`}>
            {e === 'online' ? 'respondendo' : e === 'offline' ? 'fora do ar' : 'sem leitura'}
          </span>
          <span className="foto-quando">
            {cam.status_checked_at ? `medido ${desde(cam.status_checked_at)}` : 'sem data de medicao'}
          </span>
        </div>
      </Cartao>

      {cam.ocorrencia ? (
        <Cartao>
          <h2>Ocorrencia</h2>
          <div className="ocorrencia">
            {cam.ocorrencia}
            {cam.ocorrencia_em ? (
              <span className="ocorrencia-pe">
                {desde(cam.ocorrencia_em)}{cam.ocorrencia_por ? ` · ${cam.ocorrencia_por}` : ''}
              </span>
            ) : null}
          </div>
        </Cartao>
      ) : null}

      <Cartao>
        <h2>Identificacao</h2>
        <div className="ficha">
          <Ficha rot="IP" val={cam.ip} mono />
          <Ficha rot="MAC" val={cam.mac} mono />
          <Ficha rot="Fabricante" val={cam.fabricante} />
          <Ficha rot="Modelo" val={cam.modelo} />
        </div>
      </Cartao>

      <Cartao>
        <h2>Onde ela entra</h2>
        <div className="ficha">
          <Ficha rot="Site" val={siteDa(cam)} />
          <Ficha rot="Gravador" val={cam.recorder_host || 'nao vinculada'} mono={!!cam.recorder_host} />
          <Ficha rot="Canal" val={cam.recorder_channel ?? '—'} mono />
          <Ficha rot="Chegada" val={
            cam.inventory_mode === 'olt' ? 'Fibra (ONU)'
              : cam.inventory_mode === 'switch' ? 'Switch'
              : cam.inventory_mode ? 'Cabo direto' : undefined
          } />
        </div>
      </Cartao>

      <Cartao>
        <h2>Localizacao</h2>
        {coord ? (
          <>
            <div className="ficha">
              <Ficha rot="Coordenada" val={coord} mono />
            </div>
            {temCoord && (
              // Abre o mapa do proprio aparelho. E o unico jeito de a
              // coordenada guardada virar caminho ate o poste.
              <a className="item" target="_blank" rel="noreferrer"
                 href={`https://www.google.com/maps/search/?api=1&query=${cam.lat},${cam.lon}`}>
                <span className="ic">{Icone.pin}</span>
                <span className="corpo"><span className="t">Abrir no mapa</span></span>
                {Icone.seta}
              </a>
            )}
          </>
        ) : (
          <Vazio>Sem coordenada registrada.<br />Ela e capturada na instalacao.</Vazio>
        )}
      </Cartao>
    </>
  );
}
