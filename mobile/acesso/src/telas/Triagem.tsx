import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { enviar, ErroApi, imagem } from '../lib/api';
import { useLocal } from '../lib/local';
import { pendentes, tipoDoLocal, usePessoas, useTriagem, type ItemTriagem } from '../lib/dados';
import { mascaraFone } from '../lib/cpf';
import { nomeTipo } from '../lib/vocab';
import { useCadastro } from '../lib/cadastro';
import { Carregando, Icone, Vazio, hora, useToast } from '../ui/pecas';

const MOTIVO: Record<string, string> = {
  'nome nao identificado': 'nome não identificado',
  'site nao identificado': 'local não identificado',
  'sem foto': 'sem foto',
  'possivel duplicado': 'já existe alguém com esse nome',
};

function FotoItem({ item }: { item: ItemTriagem }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    setUrl(null);
    if (item.photo_base64) { setUrl(`data:image/jpeg;base64,${item.photo_base64}`); return; }
    if (!item.photo_url?.startsWith('/')) return;
    let vivo = true;
    let criada = '';
    imagem(item.photo_url).then((b) => { criada = URL.createObjectURL(b); if (vivo) setUrl(criada); }).catch(() => {});
    return () => { vivo = false; if (criada) URL.revokeObjectURL(criada); };
  }, [item.id, item.photo_base64, item.photo_url]);
  return (
    <div className="foto-triagem">
      {url ? <img src={url} alt={`Foto enviada para ${item.suggested.full_name || 'a pessoa'}`} /> : <span>Sem foto nesta mensagem</span>}
    </div>
  );
}

/** 403 aqui quer dizer perfil: no servidor, aprovar/recusar a triagem e de administrador. */
function mensagemErro(e: unknown): string {
  if (e instanceof ErroApi && e.status === 403) return 'Aprovar ou recusar a triagem é só para administrador do cliente. Peça a quem administra o SightOps.';
  return (e as Error).message || 'Não deu certo.';
}

/* AC7 · Triagem do WhatsApp */
export function Triagem() {
  const local = useLocal();
  const t = useTriagem();
  const pessoas = usePessoas();
  const qc = useQueryClient();
  const toast = useToast();
  const ir = useNavigate();
  const { zerar } = useCadastro();
  const [i, setI] = useState(0);
  const [indo, setIndo] = useState('');
  const [recusar, setRecusar] = useState(false);
  const [erro, setErro] = useState('');

  const lista = pendentes(t.data, local);
  // approve-ready do servidor aprova as prontas de TODOS os locais: a conta e a dele.
  const prontos = t.data?.summary?.ready ?? 0;
  const item = lista[Math.min(i, Math.max(0, lista.length - 1))];
  const tipoLocal = tipoDoLocal(pessoas.data?.perfil, local);

  useEffect(() => { setRecusar(false); setErro(''); }, [item?.id]);

  async function aprovar() {
    if (!item) return;
    setIndo('aprovar'); setErro('');
    try {
      const r = await enviar<{ person?: { id?: string } }>(`/api/access-control/whatsapp/triage/${encodeURIComponent(item.id)}/approve`);
      await Promise.all([qc.invalidateQueries({ queryKey: ['triagem'] }), qc.invalidateQueries({ queryKey: ['pessoas'] })]);
      if (r.person?.id) { zerar(); ir(`/cadastro/pronto/${encodeURIComponent(r.person.id)}`); }
      else toast('Aprovada. Enviando aos leitores.');
    } catch (e) { setErro(mensagemErro(e)); } finally { setIndo(''); }
  }

  async function confirmarRecusa() {
    if (!item) return;
    setIndo('recusar'); setErro('');
    try {
      await enviar(`/api/access-control/whatsapp/triage/${encodeURIComponent(item.id)}/reject`, { reason: 'recusada no app: pedir outra foto' });
      await qc.invalidateQueries({ queryKey: ['triagem'] });
      toast('Recusada. Peça outra foto ao responsável.');
    } catch (e) { setErro(mensagemErro(e)); } finally { setIndo(''); setRecusar(false); }
  }

  async function aprovarProntos() {
    setIndo('todos'); setErro('');
    try {
      await enviar('/api/access-control/whatsapp/triage/approve-ready');
      await Promise.all([qc.invalidateQueries({ queryKey: ['triagem'] }), qc.invalidateQueries({ queryKey: ['pessoas'] })]);
      toast(`${prontos} aprovadas. Enviando aos leitores.`);
    } catch (e) { setErro(mensagemErro(e)); } finally { setIndo(''); }
  }

  if (t.isLoading) return <Carregando />;
  if (t.error) return <Vazio>{(t.error as Error).message}</Vazio>;

  const s = item?.suggested ?? {};
  const linha2 = [s.class_name, s.enrollment_code ? `mat. ${s.enrollment_code}` : '', s.person_type ? nomeTipo(s.person_type, tipoLocal) : '']
    .filter(Boolean).join(' · ');

  return (
    <>
      <div className="linha-titulo">
        <div>
          <h1 className="titulo-tela">Triagem</h1>
          <p className="sub-tela">Fotos mandadas pelo WhatsApp</p>
        </div>
        {lista.length ? <span className="mono contador-pag">{Math.min(i, lista.length - 1) + 1} de {lista.length}</span> : null}
      </div>

      {!item ? (
        <section className="cartao"><Vazio>Nada esperando aprovação.<br />Quando um responsável mandar foto no WhatsApp, ela aparece aqui.</Vazio></section>
      ) : (
        <>
          <FotoItem item={item} />
          <div className="ficha-triagem">
            <b className="n">{s.full_name || 'Nome não identificado'}</b>
            {linha2 ? <span>{linha2}</span> : null}
            <span>
              Enviada por <b style={{ color: 'var(--text)' }}>{item.from_name || mascaraFone(item.from_number) || 'desconhecido'}</b>
              {hora(item.created_at.replace('T', ' ')) ? ` · ${hora(item.created_at.replace('T', ' '))}` : ''}
            </span>
            {item.raw_text ? <div className="texto">{item.raw_text}</div> : null}
          </div>

          {item.status !== 'ready' ? (
            <div className="aviso ambar">{Icone.aviso}
              <span>Precisa de revisão: {(item.reasons || []).map((r) => MOTIVO[r] || r).join(', ') || 'dados incompletos'}. Corrija pelo painel web antes de aprovar.</span>
            </div>
          ) : null}
          {erro ? <div className="aviso vermelho">{Icone.aviso}<span>{erro}</span></div> : null}

          {recusar ? (
            <div className="acoes-duplas">
              <button type="button" className="btn2" onClick={() => setRecusar(false)}>Voltar</button>
              <button type="button" className="btn" style={{ background: 'var(--danger)' }} disabled={!!indo} onClick={confirmarRecusa}>
                {indo === 'recusar' ? 'Recusando…' : 'Confirmar recusa'}
              </button>
            </div>
          ) : (
            <div className="acoes-duplas">
              <button type="button" className="btn2" disabled={!!indo} onClick={() => setRecusar(true)}>Pedir outra</button>
              <button type="button" className="btn" disabled={!!indo || item.status !== 'ready'} onClick={aprovar}>
                {indo === 'aprovar' ? 'Aprovando…' : 'Aprovar e enviar'}
              </button>
            </div>
          )}

          {lista.length > 1 ? (
            <div className="acoes-duplas" style={{ gridTemplateColumns: '1fr 1fr' }}>
              <button type="button" className="btn2" disabled={i === 0} onClick={() => setI(Math.max(0, i - 1))}>{Icone.volta}Anterior</button>
              <button type="button" className="btn2" disabled={i >= lista.length - 1} onClick={() => setI(i + 1)}>Próxima{Icone.seta}</button>
            </div>
          ) : null}

          {prontos > 1 ? (
            <button type="button" className="link" disabled={!!indo} onClick={aprovarProntos}>
              {indo === 'todos' ? 'Aprovando…' : `Aprovar as ${prontos} que passaram na checagem (todos os locais)`}
            </button>
          ) : null}
        </>
      )}
    </>
  );
}
