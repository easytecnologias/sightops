import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { obter } from '../lib/api';
import { useLocal } from '../lib/local';
import { tipoDoLocal, usePessoas, type Grupo, type ListaPessoas } from '../lib/dados';
import { mascaraCpf, mascaraFone } from '../lib/cpf';
import { nomeTipo, tipoNoLocal, vocab } from '../lib/vocab';
import {
  conferir, ErroDuplicado, procurarDuplicado, rascunhoDe, salvar, useCadastro,
} from '../lib/cadastro';
import { Camera } from '../ui/Camera';
import { Avatar, Carregando, Icone, useToast } from '../ui/pecas';

/** Local e tipo de local de quem esta sendo cadastrado (o da pessoa, se ja existe). */
function useContexto() {
  const local = useLocal();
  const { r } = useCadastro();
  const pessoas = usePessoas();
  const site = r.existente?.site || local;
  const tipoLocal = tipoDoLocal(pessoas.data?.perfil, site);
  return { site, tipoLocal, pessoas };
}

function Topo({ titulo, sub, passo, voltar }: { titulo: string; sub: string; passo: number; voltar: () => void }) {
  return (
    <div className="topo-escuro">
      <div className="l1">
        <button type="button" className="redondo" aria-label="Voltar" onClick={voltar}>{Icone.volta}</button>
        <span><b>{titulo}</b><small>{sub}</small></span>
      </div>
      <div className="passos" aria-label={`Passo ${passo} de 3`}>
        {[1, 2, 3].map((n) => <span key={n} className={n <= passo ? 'on' : ''} />)}
      </div>
    </div>
  );
}

function AvisoDuplicado({ erro, aoAbrir }: { erro: ErroDuplicado; aoAbrir: () => void }) {
  return (
    <div className="aviso ambar">
      {Icone.aviso}
      <span>
        {erro.campo === 'CPF' ? 'Este CPF' : 'Esta matrícula'} já é de <b>{erro.pessoa.nome}</b>
        {erro.pessoa.site ? ` (${erro.pessoa.site})` : ''}. Para não gravar por cima, abra o cadastro que já existe.{' '}
        <button type="button" className="link" onClick={aoAbrir}>Abrir o cadastro</button>
      </span>
    </div>
  );
}

/* AC3 · Cadastro 1/3 — foto */
export function CadastroFoto() {
  const { r, mudar } = useCadastro();
  const ir = useNavigate();
  const editando = !!r.existente;
  return (
    <Camera
      titulo={editando ? `Foto de ${r.existente!.nome.split(' ')[0]}` : 'Foto do rosto'}
      sub={editando ? 'A foto nova substitui a do leitor' : 'Passo 1 de 3 · é ela que abre a catraca'}
      passo={editando ? undefined : 1}
      aoFechar={() => (editando || r.foto ? ir('/cadastro/dados') : ir('/'))}
      aoTirar={(foto) => { if (r.foto) URL.revokeObjectURL(r.foto.url); mudar({ foto }); ir('/cadastro/dados', { replace: true }); }}
    />
  );
}

/* AC4 · Cadastro 2/3 — dados */
export function CadastroDados() {
  const { r, mudar, zerar } = useCadastro();
  const { site, tipoLocal } = useContexto();
  const ir = useNavigate();
  const v = vocab(tipoLocal);
  const tipo = r.tipo ? tipoNoLocal(r.tipo, tipoLocal) : v.tipos[0][0];
  const [erros, setErros] = useState<Record<string, string>>({});
  const [dup, setDup] = useState<ErroDuplicado | null>(null);
  const [indo, setIndo] = useState(false);
  const [falha, setFalha] = useState('');
  const condo = tipoLocal === 'condominio';
  const aluno = tipo === 'student';
  const temFoto = !!r.foto || !!r.existente?.tem_foto;
  const mudouTipo = r.existente && r.existente.tipo !== tipo;

  async function continuar() {
    const atual = { ...r, tipo };
    mudar({ tipo });
    const e = conferir(atual, condo);
    setErros(e);
    setDup(null);
    setFalha('');
    if (Object.keys(e).length) return;
    setIndo(true);
    try {
      await procurarDuplicado(atual);
      ir('/cadastro/portas');
    } catch (err) {
      if (err instanceof ErroDuplicado) setDup(err);
      else setFalha((err as Error).message);
    } finally {
      setIndo(false);
    }
  }

  const campo = (k: string) => `campo${erros[k] ? ' ruim' : ''}`;

  return (
    <section className="tela-cheia" style={{ padding: 0, background: 'var(--bg)' }}>
      <Topo titulo={r.existente ? 'Editar cadastro' : 'Quem é'} sub={`${r.existente ? '' : 'Passo 2 de 3 · '}${site || 'sem local'}`}
            passo={2} voltar={() => (r.existente ? ir('/pessoas') : ir('/cadastro/foto'))} />
      <div className="form-passo">
        <div className="foto-linha">
          <span className="foto-mini">
            {r.foto ? <img src={r.foto.url} alt="Foto tirada agora" />
              : r.existente?.tem_foto ? <Avatar nome={r.existente.nome} pessoaId={r.existente.id} temFoto versao={r.existente.foto_em} />
                : Icone.pessoa}
            <span className={`marca-ok${temFoto ? '' : ' falta'}`}>{temFoto ? Icone.ok : Icone.aviso}</span>
          </span>
          <span style={{ flex: 1, fontSize: 13, color: 'var(--muted2)' }}>
            {r.foto ? 'Foto nova, vai para os leitores' : temFoto ? 'Foto já está no cadastro' : 'Sem foto: o leitor facial não reconhece'}
          </span>
          <button type="button" className="link" onClick={() => ir('/cadastro/foto')}>{temFoto ? 'Refazer' : 'Tirar foto'}</button>
        </div>

        <div className="seg" role="group" aria-label="Tipo de pessoa">
          {v.tipos.map(([t, n]) => (
            <button key={t} type="button" aria-pressed={tipo === t} onClick={() => mudar({ tipo: t })}>{n}</button>
          ))}
        </div>
        {mudouTipo ? (
          <div className="aviso neutro">{Icone.aviso}<span>Estava cadastrada como {nomeTipo(r.existente!.tipo, tipoLocal)}. Vai ser salva como {nomeTipo(tipo, tipoLocal)}.</span></div>
        ) : null}

        <div className={campo('nome')}>
          <label htmlFor="nome">Nome completo</label>
          <div className="caixa"><input id="nome" value={r.nome} autoCapitalize="words" onChange={(e) => mudar({ nome: e.target.value })} /></div>
          {erros.nome ? <span className="ajuda">{erros.nome}</span> : null}
        </div>

        <div className={campo('cpf')}>
          <label htmlFor="cpf">{condo ? 'CPF (opcional)' : 'CPF'}</label>
          <div className="caixa">
            <input id="cpf" className="mono" inputMode="numeric" value={mascaraCpf(r.cpf)}
                   onChange={(e) => mudar({ cpf: e.target.value })} placeholder="000.000.000-00" />
          </div>
          {erros.cpf ? <span className="ajuda">{erros.cpf}</span>
            : condo ? <span className="ajuda">Sem CPF, o SightOps cria o número da pessoa no leitor.</span> : null}
        </div>

        <div className={aluno ? 'duas' : ''}>
          {aluno ? (
            <div className={campo('matricula')}>
              <label htmlFor="mat">Matrícula</label>
              <div className="caixa"><input id="mat" className="mono" value={r.matricula} onChange={(e) => mudar({ matricula: e.target.value })} /></div>
              {erros.matricula ? <span className="ajuda">{erros.matricula}</span> : null}
            </div>
          ) : null}
          <div className="campo">
            <label htmlFor="tur">{v.grupo}</label>
            <div className="caixa"><input id="tur" value={r.turma} placeholder={v.exemploGrupo} onChange={(e) => mudar({ turma: e.target.value })} /></div>
          </div>
        </div>

        <div className="campo">
          <label htmlFor="resp">{v.contato}</label>
          <div className="caixa">
            <input id="resp" value={r.responsavel} autoCapitalize="words"
                   placeholder={tipoLocal === 'escola' ? 'Ex.: Fernanda Costa (mãe)' : ''}
                   onChange={(e) => mudar({ responsavel: e.target.value })} />
          </div>
        </div>
        <div className="campo">
          <label htmlFor="zap">WhatsApp {tipoLocal === 'escola' ? 'do responsável' : 'para avisos'}</label>
          <div className="caixa">
            <input id="zap" className="mono" type="tel" inputMode="tel" value={mascaraFone(r.telefone)}
                   placeholder="(00) 00000-0000" onChange={(e) => mudar({ telefone: e.target.value })} />
          </div>
        </div>
        <label className="chave-linha">
          <span>Avisar entrada e saída no WhatsApp</span>
          <input type="checkbox" className="chave" checked={r.whatsapp} onChange={(e) => mudar({ whatsapp: e.target.checked })} />
        </label>

        <div className={campo('email')}>
          <label htmlFor="email">E-mail {tipoLocal === 'escola' ? 'do responsável' : 'para avisos'}</label>
          <div className="caixa">
            <input id="email" type="email" inputMode="email" autoCapitalize="none" spellCheck={false} value={r.email}
                   placeholder="nome@exemplo.com" onChange={(e) => mudar({ email: e.target.value })} />
          </div>
          {erros.email ? <span className="ajuda">{erros.email}</span> : null}
        </div>
        <label className="chave-linha">
          <span>Avisar por e-mail, com a foto da passagem</span>
          <input type="checkbox" className="chave" checked={r.avisaEmail && !!r.email.trim()} disabled={!r.email.trim()}
                 onChange={(e) => mudar({ avisaEmail: e.target.checked })} />
        </label>

        {dup ? <AvisoDuplicado erro={dup} aoAbrir={() => { zerar(rascunhoDe(dup.pessoa)); setDup(null); }} /> : null}
        {falha ? <div className="aviso vermelho">{Icone.aviso}<span>{falha}</span></div> : null}

        <div style={{ marginTop: 'auto', paddingTop: 6 }}>
          <button type="button" className="btn" disabled={indo} onClick={continuar}>
            {indo ? 'Conferindo CPF e matrícula…' : 'Continuar'}
          </button>
        </div>
      </div>
    </section>
  );
}

function leitoresDe(grupos: Grupo[], ids: string[]): { id: string; nome: string }[] {
  const m = new Map<string, string>();
  for (const g of grupos) if (ids.includes(g.id)) for (const l of g.leitores) m.set(l.id, l.nome);
  return [...m].map(([id, nome]) => ({ id, nome }));
}

/* AC5 · Cadastro 3/3 — acesso */
export function CadastroPortas() {
  const { r, mudar, zerar } = useCadastro();
  const { site, tipoLocal, pessoas } = useContexto();
  const ir = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const v = vocab(tipoLocal);
  const [indo, setIndo] = useState(false);
  const [falha, setFalha] = useState('');
  const [dup, setDup] = useState<ErroDuplicado | null>(null);

  const grupos = useMemo(() => (pessoas.data?.grupos ?? [])
    .filter((g) => g.ativo && (!g.site || g.site.toUpperCase() === site.toUpperCase())), [pessoas.data, site]);
  const daTurma = r.turma.trim()
    ? grupos.find((g) => g.nome.trim().toUpperCase() === r.turma.trim().toUpperCase()) : undefined;
  const soATurma = !!daTurma && r.grupos.length === 1 && r.grupos[0] === daTurma.id;
  const vai = leitoresDe(grupos, r.grupos);

  function alternar(id: string) {
    mudar({ grupos: r.grupos.includes(id) ? r.grupos.filter((g) => g !== id) : [...r.grupos, id] });
  }

  async function gravar() {
    setFalha('');
    setDup(null);
    setIndo(true);
    try {
      const res = await salvar(r, site);
      await qc.invalidateQueries({ queryKey: ['pessoas'] });
      if (res.avisos.length) toast(res.avisos.join(' · '), true);
      ir(`/cadastro/pronto/${encodeURIComponent(res.id)}`, { replace: true });
    } catch (err) {
      if (err instanceof ErroDuplicado) setDup(err);
      else setFalha((err as Error).message || 'Não foi possível salvar.');
    } finally {
      setIndo(false);
    }
  }

  return (
    <section className="tela-cheia" style={{ padding: 0, background: 'var(--bg)' }}>
      <Topo titulo="Por onde entra" sub={`${r.existente ? '' : 'Passo 3 de 3 · '}${r.nome.trim() || 'pessoa'}`} passo={3}
            voltar={() => ir('/cadastro/dados')} />
      <div className="form-passo">
        {pessoas.isLoading ? <Carregando /> : null}

        {daTurma ? (
          <button type="button" className="cartao-link" aria-pressed={soATurma}
                  style={soATurma ? { border: '2px solid var(--primary)', background: '#f2fbf7' } : undefined}
                  onClick={() => mudar({ grupos: [daTurma.id] })}>
            <span style={{
              width: 22, height: 22, borderRadius: '50%', flex: 'none',
              border: soATurma ? '6px solid var(--primary)' : '2px solid #9aa7af',
            }} />
            <span className="corpo">
              <span className="t">Igual à {v.grupo.toLowerCase()} {daTurma.nome}</span>
              <span className="s" style={{ whiteSpace: 'normal' }}>Mesmas portas dos outros {daTurma.membros} do grupo</span>
            </span>
          </button>
        ) : null}

        <span className="rot-secao">Grupos de acesso</span>
        {!pessoas.isLoading && !grupos.length ? (
          <div className="aviso ambar">{Icone.aviso}<span>Este local ainda não tem grupo de acesso. A pessoa fica cadastrada, mas só vai aos leitores depois de entrar num grupo (painel web, aba Acesso).</span></div>
        ) : (
          <section className="cartao">
            {grupos.map((g) => (
              <button key={g.id} type="button" className="opcao" aria-pressed={r.grupos.includes(g.id)} onClick={() => alternar(g.id)}>
                <span className="cx" aria-hidden="true">{r.grupos.includes(g.id) ? Icone.ok : null}</span>
                <span className="corpo">
                  <span className="t">{g.nome}</span>
                  <span className="s">{g.leitores.length ? g.leitores.map((l) => l.nome).join(', ') : 'nenhum leitor neste grupo'}</span>
                </span>
              </button>
            ))}
          </section>
        )}

        <div style={{ fontSize: 13, color: 'var(--muted2)', padding: '0 2px' }}>
          {vai.length
            ? <>Vai para <b style={{ color: 'var(--text)' }}>{vai.length} {vai.length === 1 ? 'leitor' : 'leitores'}</b>. Os horários são os do grupo. Quem tem a foto no leitor entra pelo rosto, sem cartão.</>
            : 'Sem grupo marcado, a pessoa não vai a nenhum leitor.'}
        </div>

        {dup ? <AvisoDuplicado erro={dup} aoAbrir={() => { zerar(rascunhoDe(dup.pessoa)); ir('/cadastro/dados'); }} /> : null}
        {falha ? <div className="aviso vermelho">{Icone.aviso}<span>{falha}</span></div> : null}

        <div style={{ marginTop: 'auto', paddingTop: 6 }}>
          <button type="button" className="btn" disabled={indo} onClick={gravar}>
            {Icone.ok}{indo ? 'Salvando…' : vai.length ? 'Salvar e enviar aos leitores' : 'Salvar cadastro'}
          </button>
        </div>
      </div>
    </section>
  );
}

/* AC6 · Enviado aos leitores */
export function CadastroPronto() {
  const { id = '' } = useParams();
  const { r, zerar } = useCadastro();
  const { site, tipoLocal } = useContexto();
  const ir = useNavigate();
  const v = vocab(tipoLocal);
  const [inicio] = useState(Date.now());

  // Pergunta o andamento a cada 3 s por 3 minutos: o servidor envia em
  // segundo plano e continua mesmo se a tela fechar.
  const q = useQuery({
    queryKey: ['pronto', id, site],
    queryFn: () => obter<ListaPessoas>(`/api/access-control/painel/pessoas${site ? `?site=${encodeURIComponent(site)}` : ''}`),
    refetchInterval: (query) => {
      const p = query.state.data?.pessoas.find((x) => x.id === id);
      const andando = !p || p.leitores.some((l) => l.status !== 'ok' && l.status !== 'failed');
      return andando && Date.now() - inicio < 180_000 ? 3000 : false;
    },
  });
  const p = q.data?.pessoas.find((x) => x.id === id);
  const nome = p?.nome || r.nome;
  const sub = [p?.turma || r.turma, p?.matricula ? `mat. ${p.matricula}` : '', nomeTipo(p?.tipo || r.tipo, tipoLocal)]
    .filter(Boolean).join(' · ');

  function proximo() {
    zerar({ tipo: r.tipo, turma: r.turma, grupos: r.grupos });
    ir('/cadastro/foto', { replace: true });
  }

  return (
    <section className="tela-cheia pronto">
      <div className="cabeca">
        <span className="foto-g">
          {r.foto ? <img src={r.foto.url} alt="" />
            : p?.tem_foto ? <Avatar nome={nome} pessoaId={id} temFoto versao={p.foto_em} /> : Icone.pessoa}
          <span className="marca-ok">{Icone.ok}</span>
        </span>
        <h1>{nome.split(' ').slice(0, 2).join(' ')} {r.existente ? 'atualizado' : 'cadastrado'}</h1>
        <p>{sub}</p>
      </div>

      <section className="cartao">
        <h2>Nos leitores</h2>
        {!p ? <Carregando texto="Conferindo no servidor…" />
          : !p.leitores.length ? (
            <div className="item"><span className="corpo"><span className="t">Nenhum leitor ainda</span>
              <span className="s" style={{ whiteSpace: 'normal' }}>{p.grupos.length ? 'O servidor está preparando o envio.' : 'Sem grupo de acesso: não vai a nenhum leitor.'}</span></span></div>
          ) : p.leitores.map((l) => (
            <div key={l.leitor_id} className="item">
              {l.status === 'ok' ? <span className="estado ok">{Icone.ok}</span>
                : l.status === 'failed' ? <span className="estado falhou">{Icone.x}</span>
                  : <span className="estado vai" aria-hidden="true" />}
              <span className="corpo">
                <span className="t">{l.leitor}</span>
                <span className="s" style={{ whiteSpace: 'normal' }}>
                  {l.status === 'ok' ? 'gravado no leitor'
                    : l.status === 'failed' ? `recusou: ${l.erro || 'sem detalhe'}`
                      : 'enviando… o servidor continua mesmo se você sair'}
                </span>
              </span>
            </div>
          ))}
      </section>

      {p && ((p.whatsapp && p.telefone) || (p.avisa_email && p.email)) ? (
        <div className="aviso neutro">{Icone.conversa}
          <span>{p.responsavel || 'O contato'} vai receber as entradas e saídas
            {p.whatsapp && p.telefone ? ' no WhatsApp' : ''}{p.whatsapp && p.telefone && p.avisa_email && p.email ? ' e' : ''}
            {p.avisa_email && p.email ? ` por e-mail (${p.email})` : ''}.</span>
        </div>
      ) : null}

      <div className="pe-fixo">
        <button type="button" className="btn duas-linhas" onClick={proximo}>
          Cadastrar o próximo<small>mantém {v.grupo.toLowerCase()} e portas</small>
        </button>
        <button type="button" className="btn2" onClick={() => { zerar(); ir('/', { replace: true }); }}>Voltar ao início</button>
      </div>
    </section>
  );
}
