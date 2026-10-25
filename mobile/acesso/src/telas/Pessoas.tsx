import { useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useLocal } from '../lib/local';
import { resumoLeitores, tipoDoLocal, usePessoas } from '../lib/dados';
import { digitos } from '../lib/cpf';
import { nomeTipo, tipoNoLocal, vocab } from '../lib/vocab';
import { rascunhoDe, useCadastro } from '../lib/cadastro';
import { Avatar, Carregando, Icone, Vazio } from '../ui/pecas';

const LIMITE = 80;

/* AC2 · Pessoas */
export function Pessoas() {
  const local = useLocal();
  const dados = usePessoas();
  const [param] = useSearchParams();
  const [busca, setBusca] = useState('');
  const [filtro, setFiltro] = useState(param.get('f') || 'todos');
  const { zerar } = useCadastro();
  const ir = useNavigate();

  const tipoLocal = tipoDoLocal(dados.data?.perfil, local);
  const v = vocab(tipoLocal);
  const todas = dados.data?.pessoas ?? [];

  const contagem = useMemo(() => {
    const c: Record<string, number> = { todos: todas.length, semfoto: 0 };
    for (const p of todas) {
      const t = tipoNoLocal(p.tipo, tipoLocal);
      c[t] = (c[t] || 0) + 1;
      if (p.ativo && !p.tem_foto) c.semfoto += 1;
    }
    return c;
  }, [todas, tipoLocal]);

  const lista = useMemo(() => {
    const termo = busca.trim().toLowerCase();
    const num = digitos(termo);
    return todas.filter((p) => {
      if (filtro === 'semfoto' && !(p.ativo && !p.tem_foto)) return false;
      if (filtro !== 'todos' && filtro !== 'semfoto' && tipoNoLocal(p.tipo, tipoLocal) !== filtro) return false;
      if (!termo) return true;
      return p.nome.toLowerCase().includes(termo) || p.turma.toLowerCase().includes(termo)
        || (num.length >= 3 && (digitos(p.cpf).includes(num) || p.matricula.includes(num)));
    });
  }, [todas, filtro, busca, tipoLocal]);

  const plural = (n: string) => (/r$/.test(n) ? `${n}es` : `${n}s`);
  const chips: [string, string][] = [['todos', 'Todos'], ...v.tipos.map(([t, n]) => [t, plural(n)] as [string, string]), ['semfoto', 'Sem foto']];

  return (
    <>
      <h1 className="titulo-tela">Pessoas</h1>
      <label className="busca">
        {Icone.busca}
        <input type="search" placeholder={`Nome, CPF, ${tipoLocal === 'escola' ? 'matrícula ou turma' : v.grupo.toLowerCase()}`}
               aria-label="Buscar pessoa" value={busca} onChange={(e) => setBusca(e.target.value)} />
      </label>
      <div className="chips" role="group" aria-label="Filtro">
        {chips.filter(([k]) => k === 'todos' || contagem[k]).map(([k, n]) => (
          <button key={k} type="button" className="chip" aria-pressed={filtro === k} onClick={() => setFiltro(k)}>
            {n} {contagem[k] ?? 0}
          </button>
        ))}
      </div>

      {dados.isLoading ? <Carregando /> : dados.error ? <Vazio>{(dados.error as Error).message}</Vazio> : (
        <section className="cartao">
          {!lista.length ? <Vazio>Ninguém encontrado.</Vazio> : lista.slice(0, LIMITE).map((p) => {
            const r = resumoLeitores(p);
            const sub = [p.turma || nomeTipo(p.tipo, tipoLocal), p.matricula ? `mat. ${p.matricula}` : '', p.ativo ? '' : 'inativo']
              .filter(Boolean).join(' · ');
            return (
              <button key={p.id} type="button" className="item"
                      onClick={() => {
                        zerar(rascunhoDe(p));
                        ir(p.tem_foto ? '/cadastro/dados' : '/cadastro/foto');
                      }}>
                <Avatar nome={p.nome} pessoaId={p.id} temFoto={p.tem_foto} versao={p.foto_em} semFoto={!p.tem_foto} />
                <span className="corpo"><span className="t">{p.nome}</span><span className="s">{sub}</span></span>
                <span className={`selo ${r.cor}`}>{r.texto}</span>
              </button>
            );
          })}
          {lista.length > LIMITE ? (
            <Vazio>Mostrando {LIMITE} de {lista.length}. Use a busca para achar quem falta.</Vazio>
          ) : null}
        </section>
      )}
    </>
  );
}
