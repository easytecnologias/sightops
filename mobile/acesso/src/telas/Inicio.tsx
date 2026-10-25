import { useNavigate } from 'react-router-dom';
import { useLocal } from '../lib/local';
import { pendentes, tipoDoLocal, useAoVivo, usePessoas, useTriagem } from '../lib/dados';
import { nomeTipo, vocab } from '../lib/vocab';
import { useCadastro } from '../lib/cadastro';
import { Avatar, Carregando, Icone, Vazio, hora } from '../ui/pecas';

/* AC1 · Acesso — inicio */
export function Inicio() {
  const local = useLocal();
  const vivo = useAoVivo();
  const pessoas = usePessoas();
  const triagem = useTriagem();
  const { zerar } = useCadastro();
  const ir = useNavigate();

  const tipo = tipoDoLocal(pessoas.data?.perfil, local);
  const v = vocab(tipo);
  const r = vivo.data?.resumo;
  const semFoto = (pessoas.data?.pessoas ?? []).filter((p) => p.ativo && !p.tem_foto).length;
  const fila = pendentes(triagem.data, local).length;
  const passagens = vivo.data?.passagens ?? [];
  const num = (n?: number) => (n === undefined ? '—' : n.toLocaleString('pt-BR'));

  return (
    <>
      <div className="blocos">
        <div className="bloco"><span className="rot">{v.dentro}</span><span className="num">{num(r?.inside_now)}</span></div>
        <div className="bloco"><span className="rot">Entradas hoje</span><span className="num">{num(r?.entries)}</span></div>
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

      {fila > 0 ? (
        <button type="button" className="cartao-link" onClick={() => ir('/triagem')}>
          <span className="ic">{Icone.conversa}</span>
          <span className="corpo">
            <span className="t">{fila} {fila === 1 ? 'foto esperando' : 'fotos esperando'} aprovação</span>
            <span className="s">Mandadas pelo WhatsApp</span>
          </span>
          <span className="seta">{Icone.seta}</span>
        </button>
      ) : null}

      <section className="cartao">
        <h2>Passando agora <span className="selo verde">ao vivo</span></h2>
        {vivo.isLoading ? <Carregando /> : vivo.error ? <Vazio>{(vivo.error as Error).message}</Vazio>
          : !passagens.length ? <Vazio>Ninguém passou pelos leitores hoje.</Vazio>
            : passagens.map((p) => {
              const saida = p.tipo.startsWith('saida');
              const quem = p.nome || 'Rosto não reconhecido';
              const sub = [p.turma || nomeTipo(p.tipo_pessoa, tipo), p.porta, `${saida ? 'saiu' : 'entrou'} ${hora(p.hora)}`]
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
