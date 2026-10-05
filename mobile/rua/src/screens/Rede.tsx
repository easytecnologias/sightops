import { useOnline } from '../lib/rede';
import { useConectores, siteDoConector } from '../lib/dados';
import { Carregando, Cartao, Icone, Item, Procedencia, Titulo, Vazio } from '../ui/pecas';

/** Conectores do cliente: e por eles que todo comando chega ao equipamento,
 *  entao saber qual esta de pe explica metade das falhas do dia. */
export function Rede() {
  const online = useOnline();
  const q = useConectores();

  if (q.isPending && !q.data) return <Carregando />;
  const lista = (q.data ?? []).slice().sort((a, b) =>
    siteDoConector(a).localeCompare(siteDoConector(b)));
  const dePe = lista.filter((c) => c.online).length;

  return (
    <>
      <div className="linha-topo">
        <Titulo titulo="Rede" sub={`${dePe} de ${lista.length} conectores de pe`} />
        <span style={{ marginLeft: 'auto' }}>
          <Procedencia buscando={q.isFetching} atualizadoEm={q.dataUpdatedAt} online={online} />
        </span>
      </div>
      <Cartao>
        <h2>Conectores</h2>
        <p className="sub-h2">O caminho ate o equipamento de cada site</p>
        {lista.length === 0 ? (
          <Vazio>Nenhum conector cadastrado.</Vazio>
        ) : lista.map((c, i) => (
          <Item key={c.id ?? i} ponto={c.online ? 'verde' : 'vermelho'} icone={Icone.rede}
                titulo={siteDoConector(c) || c.name || '—'}
                sub={c.name && siteDoConector(c) !== c.name ? c.name : undefined}
                direita={
                  <span className={`selo ${c.online ? 'verde' : 'ambar'}`}>
                    {c.online ? 'online' : 'sem sinal'}
                  </span>
                } />
        ))}
      </Cartao>
    </>
  );
}
