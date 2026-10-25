import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useLocal } from '../lib/local';
import { tipoDoLocal, usePessoas } from '../lib/dados';
import { mascaraCpf } from '../lib/cpf';
import { vocab } from '../lib/vocab';
import { conferir, ErroDuplicado, RASCUNHO_VAZIO, rascunhoDe, salvar, useCadastro, type Rascunho } from '../lib/cadastro';
import { Camera, type Foto } from '../ui/Camera';
import { Icone, useToast } from '../ui/pecas';

/* AC8 · Visitante rapido: foto, nome, documento e portas numa tela so. */
export function Visitante() {
  const local = useLocal();
  const pessoas = usePessoas();
  const { zerar, mudar } = useCadastro();
  const qc = useQueryClient();
  const toast = useToast();
  const ir = useNavigate();
  const tipoLocal = tipoDoLocal(pessoas.data?.perfil, local);
  const v = vocab(tipoLocal);
  const rotulo = v.nomes.visitor || 'Visitante';
  const condo = tipoLocal === 'condominio';

  const [foto, setFoto] = useState<Foto | undefined>();
  const [camera, setCamera] = useState(false);
  const [nome, setNome] = useState('');
  const [cpf, setCpf] = useState('');
  const [quem, setQuem] = useState('');
  const [grupos, setGrupos] = useState<string[]>([]);
  const [erros, setErros] = useState<Record<string, string>>({});
  const [falha, setFalha] = useState('');
  const [dup, setDup] = useState<ErroDuplicado | null>(null);
  const [indo, setIndo] = useState(false);

  const lista = useMemo(() => (pessoas.data?.grupos ?? [])
    .filter((g) => g.ativo && (!g.site || g.site.toUpperCase() === local.toUpperCase())), [pessoas.data, local]);

  async function liberar() {
    const r: Rascunho = {
      ...RASCUNHO_VAZIO, tipo: 'visitor', nome, cpf, foto, grupos,
      notas: quem.trim() ? `Visita: ${quem.trim()}` : '', whatsapp: false,
    };
    const e = conferir(r, condo);
    setErros(e); setFalha(''); setDup(null);
    if (Object.keys(e).length) return;
    setIndo(true);
    try {
      const res = await salvar(r, local);
      await qc.invalidateQueries({ queryKey: ['pessoas'] });
      if (res.avisos.length) toast(res.avisos.join(' · '), true);
      zerar(r);
      ir(`/cadastro/pronto/${encodeURIComponent(res.id)}`);
    } catch (err) {
      if (err instanceof ErroDuplicado) setDup(err);
      else setFalha((err as Error).message || 'Não foi possível liberar.');
    } finally {
      setIndo(false);
    }
  }

  if (camera) {
    return (
      <Camera titulo={`Foto do ${rotulo.toLowerCase()}`} sub="Entra pelo leitor facial, sem cartão"
              aoFechar={() => setCamera(false)}
              aoTirar={(f) => { if (foto) URL.revokeObjectURL(foto.url); setFoto(f); setCamera(false); }} />
    );
  }

  return (
    <>
      <div>
        <h1 className="titulo-tela">{rotulo}</h1>
        <p className="sub-tela">Cadastro rápido de quem vem uma vez</p>
      </div>

      <button type="button" className="cartao-link" onClick={() => setCamera(true)}>
        <span className="foto-mini" style={{ width: 48, height: 48 }}>
          {foto ? <img src={foto.url} alt="Foto tirada" /> : Icone.camera}
        </span>
        <span className="corpo">
          <span className="t">{foto ? 'Foto pronta' : 'Tirar foto do rosto'}</span>
          <span className="s">{foto ? 'Toque para tirar outra' : 'Entra pelo leitor sem cartão'}</span>
        </span>
        <span className="seta">{Icone.seta}</span>
      </button>

      <div className={`campo${erros.nome ? ' ruim' : ''}`}>
        <label htmlFor="vn">Nome</label>
        <div className="caixa"><input id="vn" value={nome} autoCapitalize="words" onChange={(e) => setNome(e.target.value)} /></div>
        {erros.nome ? <span className="ajuda">{erros.nome}</span> : null}
      </div>
      <div className={`campo${erros.cpf ? ' ruim' : ''}`}>
        <label htmlFor="vd">{condo ? 'CPF (opcional)' : 'CPF'}</label>
        <div className="caixa">
          <input id="vd" className="mono" inputMode="numeric" value={mascaraCpf(cpf)} placeholder="000.000.000-00"
                 onChange={(e) => setCpf(e.target.value)} />
        </div>
        {erros.cpf ? <span className="ajuda">{erros.cpf}</span> : null}
      </div>
      <div className="campo">
        <label htmlFor="vq">Vem falar com</label>
        <div className="caixa">
          <input id="vq" value={quem} placeholder={tipoLocal === 'escola' ? 'Ex.: Coordenação pedagógica' : 'Ex.: Apto 304'}
                 onChange={(e) => setQuem(e.target.value)} />
        </div>
      </div>

      <span className="rot-secao">Por onde entra</span>
      {lista.length ? (
        <section className="cartao">
          {lista.map((g) => {
            const on = grupos.includes(g.id);
            return (
              <button key={g.id} type="button" className="opcao" aria-pressed={on}
                      onClick={() => setGrupos(on ? grupos.filter((x) => x !== g.id) : [...grupos, g.id])}>
                <span className="cx" aria-hidden="true">{on ? Icone.ok : null}</span>
                <span className="corpo">
                  <span className="t">{g.nome}</span>
                  <span className="s">{g.leitores.map((l) => l.nome).join(', ') || 'nenhum leitor'}</span>
                </span>
              </button>
            );
          })}
        </section>
      ) : (
        <div className="aviso ambar">{Icone.aviso}<span>Este local não tem grupo de acesso: o cadastro fica salvo, mas não vai a nenhum leitor.</span></div>
      )}

      <div className="aviso neutro">{Icone.aviso}
        <span>O acesso não sai sozinho dos leitores. Quando a visita terminar, peça ao administrador para desativar no painel.</span>
      </div>

      {dup ? (
        <div className="aviso ambar">{Icone.aviso}
          <span>Este CPF já é de <b>{dup.pessoa.nome}</b>.{' '}
            <button type="button" className="link" onClick={() => { zerar(rascunhoDe(dup.pessoa)); if (foto) mudar({ foto }); ir('/cadastro/dados'); }}>
              Abrir o cadastro
            </button>
          </span>
        </div>
      ) : null}
      {falha ? <div className="aviso vermelho">{Icone.aviso}<span>{falha}</span></div> : null}

      <button type="button" className="btn" disabled={indo} onClick={liberar}>
        {Icone.ok}{indo ? 'Liberando…' : 'Liberar entrada'}
      </button>
    </>
  );
}
