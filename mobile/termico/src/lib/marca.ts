/**
 * Marca do cliente (white-label). Vem de clientes/<cliente>/cliente.json no
 * build. Nenhuma tela usa cor de marca fixa: tudo sai das variaveis daqui.
 * Verde/ambar de situacao sao iguais para todos os clientes.
 */
type Marca = {
  nome: string; empresa: string; sigla: string; cor: string; destaque: string;
  alerta: string; fonte: string; slogan: string; versao: string;
};
declare const __CLIENTE__: Marca;
export const MARCA: Marca = __CLIENTE__;

function tom(hex: string, t: number, alvo: 0 | 255): string {
  const n = parseInt(hex.slice(1), 16);
  const c = [n >> 16, (n >> 8) & 255, n & 255].map((v) => Math.round(v + (alvo - v) * t));
  return `rgb(${c.join(',')})`;
}

export function aplicarMarca(): void {
  const r = document.documentElement.style;
  r.setProperty('--cor', MARCA.cor);
  r.setProperty('--cor-suave', tom(MARCA.cor, 0.9, 255));
  r.setProperty('--cor-escura', tom(MARCA.cor, 0.35, 0));
  r.setProperty('--destaque', MARCA.destaque);
  r.setProperty('--destaque-suave', tom(MARCA.destaque, 0.86, 255));
  r.setProperty('--alerta', MARCA.alerta);
  r.setProperty('--alerta-suave', tom(MARCA.alerta, 0.9, 255));
  r.setProperty('--fonte', `'${MARCA.fonte}', system-ui, sans-serif`);
  document.title = MARCA.nome;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', MARCA.cor);
}
