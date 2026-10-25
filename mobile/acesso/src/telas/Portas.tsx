import { useLocal } from '../lib/local';
import { useVisaoGeral } from '../lib/dados';
import { desde } from '../lib/tempo';
import { Carregando, Icone, Vazio } from '../ui/pecas';
import { BotoesPorta } from '../ui/Porta';

/* Portas: abrir e fechar de longe, leitor por leitor do local escolhido no topo. */
export function Portas() {
  const local = useLocal();
  const visao = useVisaoGeral(local);
  const leitores = (visao.data?.leitores?.lista ?? [])
    .filter((l) => !local || l.site.toUpperCase() === local.toUpperCase())
    .sort((a, b) => a.nome.localeCompare(b.nome, 'pt-BR', { numeric: true }));

  return (
    <>
      <div>
        <h1 className="titulo-tela">Portas</h1>
        <p className="sub-tela">Abra ou feche de onde estiver. Dois toques para confirmar.</p>
      </div>

      {visao.isLoading ? <Carregando /> : visao.error ? <Vazio>{(visao.error as Error).message}</Vazio>
        : !leitores.length ? <section className="cartao"><Vazio>Nenhum leitor neste local.</Vazio></section> : (
          <section className="cartao">
            {leitores.map((l) => {
              const on = l.status.toLowerCase() === 'online';
              return (
                <div key={l.id} className="item item-porta">
                  <span className="ic-local">{Icone.porta}</span>
                  <span className="corpo">
                    <span className="t">{l.nome}</span>
                    <span className="s">{on ? 'no ar' : `fora do ar${l.visto ? ` · visto ${desde(l.visto)}` : ''}`}</span>
                  </span>
                  <span className={`selo ${on ? 'verde' : 'ambar'}`}>{on ? 'online' : 'offline'}</span>
                  <BotoesPorta leitor={l} />
                </div>
              );
            })}
          </section>
        )}

      <div className="aviso neutro">{Icone.aviso}
        <span>A ordem vai na hora para o leitor e fica registrada com o seu usuário. Leitor fora do ar não recebe.</span>
      </div>
    </>
  );
}
