import { useNavigate, useParams } from 'react-router-dom';
import { chaveDa, estadoDa, siteDa, tituloDa, useCameras } from '../lib/dados';
import { useFoto } from '../lib/foto';
import { desde } from '../lib/tempo';
import { Carregando, Cartao, Icone, Titulo, Vazio, useToast } from '../ui/pecas';
import { useState } from 'react';
import { detalhe, type Camera, type Entidade } from '../lib/dados';
import { nomeEntidade, partesOnu, sinalBaixo, useSiteMonitor, type DetalheOnu } from '../lib/monitor';
import { religarPoe } from '../lib/switch';
import { useOnline } from '../lib/rede';
import { Caminho, type Elo } from '../ui/Caminho';

const est = (e?: Entidade): Elo['estado'] => (!e ? 'sem' : e.status === 'up' ? (sinalBaixo(e) ? 'atencao' : 'ok') : e.status === 'down' ? 'ruim' : 'sem');

/** Conector -> OLT/PON -> ONU -> switch e porta -> camera -> gravador. O primeiro elo fora do ar e onde o sinal parou. */
function useCaminhoCamera(cam: Camera | undefined) {
  const m = useSiteMonitor(null);
  const ir = useNavigate();
  if (!cam) return [];
  const elos: Elo[] = [];
  const conId = cam.remote_connector_id || cam.connector_id;
  const con = m.conectores.find((c) => conId && c.connector_id === conId);
  if (con) elos.push({ tipo: 'conector', titulo: `Conector ${nomeEntidade(con)}`, estado: est(con) });
  const serial = String(cam.onu_serial ?? '').toUpperCase();
  const onu = serial ? m.onus.find((e) => String(detalhe<DetalheOnu>(e).serial ?? '').toUpperCase() === serial) : undefined;
  if (onu) {
    const p = partesOnu(onu.entity_key);
    const olt = m.olts.find((o) => String(detalhe<{ host?: string }>(o).host ?? '') === p.oltIp);
    elos.push({ tipo: 'olt', titulo: <>{olt ? nomeEntidade(olt) : `OLT ${p.oltIp}`} · PON <span className="mono">{p.pon}</span></>,
      estado: est(olt), onClick: () => ir(`/pon?olt=${encodeURIComponent(p.oltIp)}&pon=${encodeURIComponent(p.pon)}`) });
    elos.push({ tipo: 'onu', titulo: `ONU ${nomeEntidade(onu)}`, estado: est(onu), onClick: () => ir(`/onu/${encodeURIComponent(onu.entity_key)}`) });
  } else if (cam.pon || cam.onu_name) {
    elos.push({ tipo: 'onu', titulo: `ONU ${cam.onu_name || ''}`.trim(), sub: cam.pon ? `PON ${cam.pon}${cam.onu_id ? ` · ONU ${cam.onu_id}` : ''}` : undefined, estado: 'sem' });
  }
  if (cam.switch_ip) {
    const sw = m.switches.find((e) => detalhe<{ ip?: string }>(e).ip === cam.switch_ip);
    elos.push({ tipo: 'switch', titulo: `${sw ? nomeEntidade(sw) : cam.switch_name || cam.switch_ip}${cam.switch_port ? ` · porta ${cam.switch_port}` : ''}`,
      estado: est(sw), onClick: sw ? () => ir(`/switch/${encodeURIComponent(sw.entity_key)}`) : undefined });
  }
  const e = estadoDa(cam);
  elos.push({ tipo: 'camera', titulo: 'Esta câmera', aqui: true, estado: e === 'online' ? 'ok' : e === 'offline' ? 'ruim' : 'sem' });
  if (cam.recorder_host) {
    const nvr = m.nvrs.find((x) => detalhe<{ host?: string }>(x).host === cam.recorder_host);
    elos.push({ tipo: 'gravador', titulo: `${nvr ? nomeEntidade(nvr) : cam.recorder_host}${cam.recorder_channel ? ` · canal ${cam.recorder_channel}` : ''}`,
      estado: nvr ? est(nvr) : undefined,
      onClick: () => ir(`/implantar/gravador/${encodeURIComponent(cam.recorder_host!)}`) });
  }
  const i = elos.findIndex((x) => x.estado === 'ruim');
  if (i >= 0) elos[i] = { ...elos[i], falha: true, sub: elos[i].sub ?? 'o sinal parou aqui' };
  return elos;
}
import { AjustarCamera } from '../telas/AjustarCamera';

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

  // O roteador entrega o parametro ja DECODIFICADO ("ip|mac"); chaveDa devolve
  // codificado. Comparar so com chaveDa nunca casava: toda ficha dizia "nao encontrada".
  const cam = (q.data ?? []).find((c) => `${c.ip ?? ''}|${c.mac ?? ''}` === chave || chaveDa(c) === chave);
  const foto = useFoto(cam?.snapshot_url);
  const elos = useCaminhoCamera(cam);
  const online = useOnline();
  const toast = useToast();
  const [religando, setReligando] = useState(false);

  if (q.isPending && !q.data) return <Carregando />;
  if (!cam) {
    return (
      <Cartao>
        <Vazio>Câmera não encontrada no projeto baixado.</Vazio>
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
            <img src={foto.url} alt={`Última imagem de ${tituloDa(cam)}`} />
          ) : (
            <div className="foto-vazia">
              {foto.estado === 'carregando' ? 'Carregando a imagem…'
                : foto.estado === 'sem-sinal' ? 'A foto precisa de sinal — ela não cabe na cópia do aparelho.'
                : foto.estado === 'sem-foto' ? 'Esta câmera ainda não tem foto no inventário.'
                : 'Não consegui trazer a imagem agora.'}
            </div>
          )}
        </div>
        <div className="foto-pe">
          <span className={`selo ${e === 'online' ? 'verde' : e === 'offline' ? 'ambar' : 'cinza'}`}>
            {e === 'online' ? 'respondendo' : e === 'offline' ? 'fora do ar' : 'sem leitura'}
          </span>
          <span className="foto-quando">
            {cam.status_checked_at ? `medido ${desde(cam.status_checked_at)}` : 'sem data de medição'}
          </span>
        </div>
      </Cartao>

      <Caminho elos={elos} titulo="Caminho · onde está o problema" />

      {cam.switch_ip && cam.switch_port && e !== 'online' ? (
        <button type="button" className="btn" disabled={religando || !online} onClick={async () => {
          if (!window.confirm(`Desligar e religar o PoE da porta ${cam.switch_port} do switch ${cam.switch_name || cam.switch_ip}?

A câmera reinicia e volta em 1 a 2 minutos.`)) return;
          setReligando(true);
          try { await religarPoe(cam.switch_ip!, siteDa(cam), cam.switch_port!); toast('PoE religado. A câmera volta em 1 a 2 minutos.'); }
          catch (err) { toast(`Não consegui religar: ${(err as Error).message}`, true); }
          finally { setReligando(false); }
        }}>{Icone.raio}{religando ? 'Religando…' : `Religar PoE (porta ${cam.switch_port})`}</button>
      ) : null}

      {cam.ocorrencia ? (
        <Cartao>
          <h2>Ocorrência</h2>
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

      {cam.ip ? (
        <button type="button" className="btn" onClick={() => ir(`/cameras/${chaveDa(cam)}/aovivo`)}>
          {Icone.camera}Ver ao vivo
        </button>
      ) : null}

      <AjustarCamera cam={cam} />

      <Cartao>
        <h2>Identificação</h2>
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
          <Ficha rot="Gravador" val={cam.recorder_host || 'não vinculada'} mono={!!cam.recorder_host} />
          <Ficha rot="Canal" val={cam.recorder_channel ?? '—'} mono />
          <Ficha rot="Chegada" val={
            cam.inventory_mode === 'olt' ? 'Fibra (ONU)'
              : cam.inventory_mode === 'switch' ? 'Switch'
              : cam.inventory_mode ? 'Cabo direto' : undefined
          } />
        </div>
      </Cartao>

      <Cartao>
        <h2>Localização</h2>
        {coord ? (
          <>
            <div className="ficha">
              <Ficha rot="Coordenada" val={coord} mono />
            </div>
            {temCoord && (
              // "Abrir no mapa" fica no app: o Mapa do SightOps centrado na
              // camera, com caixas e cabos. O Google Maps so para a rota.
              <>
                <button type="button" className="item" onClick={() => ir('/mapa', { state: { centro: [Number(cam.lat), Number(cam.lon)], camera: chaveDa(cam), nome: tituloDa(cam) } })}>
                  <span className="ic">{Icone.pin}</span>
                  <span className="corpo"><span className="t">Abrir no mapa</span><span className="s">Mapa do SightOps, com caixas e cabos</span></span>
                  {Icone.seta}
                </button>
                <a className="item" target="_blank" rel="noreferrer"
                   href={`https://www.google.com/maps/dir/?api=1&destination=${cam.lat},${cam.lon}`}>
                  <span className="ic">{Icone.mapa}</span>
                  <span className="corpo"><span className="t">Como chegar</span><span className="s">rota no Google Maps</span></span>
                  {Icone.seta}
                </a>
              </>
            )}
          </>
        ) : (
          <Vazio>Sem coordenada registrada.<br />Ela é capturada na instalação.</Vazio>
        )}
      </Cartao>
    </>
  );
}
