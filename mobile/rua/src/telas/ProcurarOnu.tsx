import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { enviar } from '../lib/api';
import { ipDaOlt } from '../lib/dados';
import { baseOlt } from '../lib/implantar';
import { useSiteMonitor } from '../lib/monitor';
import { useOnline } from '../lib/rede';
import { Cartao, Icone, Item, Vazio } from '../ui/pecas';
import { useOltsDoSite } from './ImplantarOnu';

type Achada = { olt: string; oltIp: string; pon?: number | string; onu?: number | string; serial?: string; model?: string; oper_status?: string };

/* Procurar ONU ja autorizada pelo serial (ou MAC, na EPON) em todas as OLTs
   do site. So leitura na OLT (find_onu). Achando, abre a ficha da ONU, onde
   ficam sinal, reiniciar e remover. */
export function ProcurarOnu() {
  const { lista: olts, site } = useOltsDoSite();
  const m = useSiteMonitor(site || null);
  const online = useOnline();
  const ir = useNavigate();
  const [serial, setSerial] = useState('');
  const [indo, setIndo] = useState(false);
  const [achadas, setAchadas] = useState<Achada[] | null>(null);
  const [falhas, setFalhas] = useState<string[]>([]);

  async function procurar() {
    const s = serial.trim();
    if (!s) return;
    setIndo(true); setAchadas(null); setFalhas([]);
    const ok: Achada[] = [];
    const erro: string[] = [];
    // Uma OLT por vez: a OLT atende poucas sessoes de terminal ao mesmo tempo.
    for (const o of olts) {
      try {
        const r = await enviar<{ ok?: boolean; error?: string; pon?: number; onu?: number; serial?: string; model?: string; oper_status?: string }>(
          '/api/olt/find-onu', { ...baseOlt(o, site), serial: s });
        if (r.ok !== false) ok.push({ olt: o.name || ipDaOlt(o), oltIp: ipDaOlt(o), pon: r.pon, onu: r.onu, serial: r.serial, model: r.model, oper_status: r.oper_status });
      } catch (e) {
        erro.push(`${o.name || ipDaOlt(o)}: ${(e as Error).message}`);
      }
    }
    setAchadas(ok); setFalhas(erro); setIndo(false);
  }

  // A ficha da ONU e a do monitoramento (onu|olt|pon|onu): a mesma do Zabbix.
  const fichaDa = (a: Achada) => m.onus.find((e) => e.entity_key.split('|')[1] === a.oltIp
    && e.entity_key.split('|')[2] === String(a.pon) && e.entity_key.split('|')[3] === String(a.onu));

  return (
    <>
      <button type="button" className="volta-link" onClick={() => ir('/implantar')}>{Icone.volta}Implantar</button>
      <div>
        <h1 className="titulo-tela">Procurar ONU</h1>
        <p className="sub-tela">Pelo serial (GPON) ou MAC (EPON), em {olts.length === 1 ? 'a OLT' : `todas as ${olts.length} OLTs`} do site. Só consulta, não muda nada.</p>
      </div>
      <Cartao>
        <div className="form-cartao">
          <div className="campo"><label htmlFor="sn">Serial ou MAC da etiqueta</label>
            <form className="caixa" onSubmit={(ev) => { ev.preventDefault(); void procurar(); }}>
              <input id="sn" className="mono" value={serial} onChange={(ev) => setSerial(ev.target.value.toUpperCase())}
                     placeholder="ITBS1234ABCD" autoCapitalize="characters" spellCheck={false} enterKeyHint="search" />
            </form></div>
          <button type="button" className="btn" disabled={!serial.trim() || indo || !online || !olts.length} onClick={() => void procurar()}>
            {Icone.busca}{indo ? 'Perguntando às OLTs…' : 'Procurar'}
          </button>
          {!olts.length ? <span className="sub-tela">Nenhuma OLT cadastrada neste site.</span> : null}
        </div>
      </Cartao>

      {achadas ? (
        <Cartao>
          {!achadas.length ? <Vazio>Nenhuma OLT do site tem ONU autorizada com esse serial.<br />Se ela é nova, use Ativar ONU.</Vazio> : achadas.map((a, i) => {
            const ficha = fichaDa(a);
            return (
              <Item key={i} icone={Icone.onu} ponto={a.oper_status ? (/up|online|working/i.test(a.oper_status) ? 'verde' : 'vermelho') : undefined}
                    titulo={`${a.olt} · PON ${a.pon} · ONU ${a.onu}`}
                    sub={[a.serial, a.model, a.oper_status, ficha ? '' : 'ainda sem ficha no monitoramento'].filter(Boolean).join(' · ')}
                    onClick={ficha ? () => ir(`/onu/${encodeURIComponent(ficha.entity_key)}`) : undefined}
                    direita={ficha ? Icone.seta : undefined} />
            );
          })}
          {falhas.length ? <p className="sub-tela" style={{ padding: '6px 14px', color: 'var(--danger)' }}>Não consegui perguntar a: {falhas.join(' · ')}</p> : null}
        </Cartao>
      ) : null}
    </>
  );
}
