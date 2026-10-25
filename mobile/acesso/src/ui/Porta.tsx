import { useEffect, useRef, useState } from 'react';
import { enviar } from '../lib/api';
import type { Leitor } from '../lib/dados';
import { Icone, useToast } from './pecas';

/**
 * Abrir / fechar porta pelo leitor (canal 1, como o painel web).
 *
 * Dois toques, como na web: o primeiro so arma ("Toque de novo"), o segundo
 * manda a ordem. Porta de cliente e coisa seria: ninguem abre sem querer.
 * A ordem vai na hora para o equipamento; o servidor registra quem mandou.
 */
type Acao = 'abrir' | 'fechar';

function rota(id: string, acao: Acao) {
  const i = encodeURIComponent(id);
  return acao === 'abrir'
    ? `/api/access-control/devices/${i}/open-door?channel=1`
    : `/api/access-control/painel/controladora/${i}/fechar?canal=1`;
}

export function BotoesPorta({ leitor }: { leitor: Leitor }) {
  const toast = useToast();
  const [armado, setArmado] = useState<Acao | ''>('');
  const [indo, setIndo] = useState<Acao | ''>('');
  const timer = useRef<number>();
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function tocar(acao: Acao) {
    if (indo) return;
    if (armado !== acao) {
      setArmado(acao);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setArmado(''), 4000);
      return;
    }
    window.clearTimeout(timer.current);
    setArmado('');
    setIndo(acao);
    try {
      await enviar(rota(leitor.id, acao));
      toast(`${leitor.nome}: porta ${acao === 'abrir' ? 'aberta' : 'fechada'}.`);
    } catch (e) {
      toast(`${leitor.nome}: não consegui ${acao} (${(e as Error).message}).`, true);
    } finally {
      setIndo('');
    }
  }

  const rotulo = (a: Acao) => (indo === a ? 'Enviando…' : armado === a ? 'Toque de novo' : a === 'abrir' ? 'Abrir' : 'Fechar');
  return (
    <span className="botoes-porta">
      <button type="button" className={`bp abrir${armado === 'abrir' ? ' armado' : ''}`} disabled={!!indo}
              aria-label={`Abrir a porta ${leitor.nome}`} onClick={() => tocar('abrir')}>
        {armado === 'abrir' ? Icone.aviso : Icone.porta}{rotulo('abrir')}
      </button>
      <button type="button" className={`bp fechar${armado === 'fechar' ? ' armado' : ''}`} disabled={!!indo}
              aria-label={`Fechar a porta ${leitor.nome}`} onClick={() => tocar('fechar')}>
        {armado === 'fechar' ? Icone.aviso : Icone.cadeado}{rotulo('fechar')}
      </button>
    </span>
  );
}
