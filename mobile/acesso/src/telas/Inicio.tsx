import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLocal } from '../lib/local';
import { pegar, salvar } from '../lib/storage';
import { tipoDoLocal, useAoVivo, usePessoas, useVisaoGeral } from '../lib/dados';
import { nomeTipo, vocab } from '../lib/vocab';
import { useCadastro } from '../lib/cadastro';
import { Avatar, Carregando, Icone, Vazio, hora } from '../ui/pecas';

/** Leitor escolhido no "ao vivo", guardado por local (a portaria de cada um). */
function usePortaEscolhida(site: string): [string, (id: string) => void] {
  const [porta, setPorta] = useState('');
  const chave = `acesso.porta.${site.toUpperCase()}`;
  useEffect(() => { let vivo = true; pegar(chave).then((v) => { if (vivo) setPorta(v || ''); }); return () => { vivo = false; }; }, [chave]);
  return [porta, (id: string) => { setPorta(id); void salvar(chave, id); }];
}

/* AC1 · Acesso — inicio */
export function Inicio() {
  const local = useLocal();
  const visao = useVisaoGeral(local);
  const leitores = (visao.data?.leitores?.lista ?? []).filter((l) => !local || l.site.toUpperCase() === local.toUpperCase());
  const [portaSalva, escolher] = usePortaEscolhida(local);
  const porta = leitores.some((l) => l.id === portaSalva) ? portaSalva : '';
  const vivo = useAoVivo(porta);
  const pessoas = usePessoas();
  const { zerar } = useCadastro();
  const ir = useNavigate();

  const tipo = tipoDoLocal(pessoas.data?.perfil, local);
  const v = vocab(tipo);
  const r = vivo.data?.resumo;
  const semFoto = (pessoas.data?.pessoas ?? []).filter((p) => p.ativo && !p.tem_foto).length;
  const passagens = vivo.data?.passagens ?? [];
  const num = (n?: number) => (n === undefined ? '—' : n.toLocaleString('pt-BR'));

  return (
    <>
      <div className="blocos">
        <div className="bloco"><span className="rot">{v.dentro}</span><span className="num">{num(r?.inside_now)}</span></div>
        <div className="bloco"><span className="rot">{porta ? 'Entradas aqui' : 'Entradas hoje'}</span><span className="num">{num(r?.entries)}</span></div>
        <button type="button" className="bloco" onClick={() => ir('/pessoas?f=semfoto')}>
          <span className="rot">Sem foto</span>
          <span className={`num${semFoto ? ' ambar' : ''}`}>{pessoas.data ? num(semFoto) : '—'}</span>
        </button>
      </div>

      <button type="button" className="cta" onClick={() => { zerar(); ir('/cadastro/foto'); }}>
        <span className="ic">{Icone.mais}</span>
        <span style={{ flex: 1 }}>
          <b>Cadastrar pessoa</b>
          <span>Foto, dados e portas, direto do celular</span>
        </span>
      </button>

      <button type="button" className="cartao-link" onClick={() => ir('/visitante')}>
        <span className="ic" style={{ background: 'var(--blue-soft)', color: '#174f86' }}>{Icone.cracha}</span>
        <span className="corpo">
          <span className="t">{v.nomes.visitor || 'Visitante'} rápido</span>
          <span className="s">Cadastro de quem vem uma vez</span>
        </span>
        <span className="seta">{Icone.seta}</span>
      </button>

      {leitores.length > 1 ? (
        <div className="chips" role="group" aria-label="Leitor do ao vivo">
          <button type="button" className="chip" aria-pressed={!porta} onClick={() => escolher('')}>Todos</button>
          {leitores.map((l) => (
            <button key={l.id} type="button" className="chip" aria-pressed={porta === l.id} onClick={() => escolher(l.id)}>
              <span className={`pt-chip${l.status.toLowerCase() === 'online' ? '' : ' off'}`} />{l.nome}
            </button>
          ))}
        </div>
      ) : null}

      <section className="cartao">
        <h2>{porta ? `Passando · ${leitores.find((l) => l.id === porta)?.nome}` : 'Passando agora'} <span className="selo verde">ao vivo</span></h2>
        {vivo.isLoading ? <Carregando /> : vivo.error ? <Vazio>{(vivo.error as Error).message}</Vazio>
          : !passagens.length ? <Vazio>{porta ? 'Ninguém passou por este leitor hoje.' : 'Ninguém passou pelos leitores hoje.'}</Vazio>
            : passagens.map((p) => {
              const saida = p.tipo.startsWith('saida');
              const quem = p.nome || 'Rosto não reconhecido';
              const sub = [p.turma || nomeTipo(p.tipo_pessoa, tipo), porta ? '' : p.porta, `${saida ? 'saiu' : 'entrou'} ${hora(p.hora)}`]
                .filter(Boolean).join(' · ');
              return (
                <div key={p.id} className="item">
                  <Avatar nome={p.nome} pessoaId={p.pessoa_id} temFoto={p.tem_foto} pequeno />
                  <span className="corpo"><span className="t">{quem}</span><span className="s">{sub}</span></span>
                  {!p.pessoa_id ? <span className="selo ambar">sem cadastro</span>
                    : <span className={`selo ${saida ? 'cinza' : 'verde'}`}>{saida ? 'saída' : 'entrada'}</span>}
                </div>
              );
            })}
      </section>
    </>
  );
}
