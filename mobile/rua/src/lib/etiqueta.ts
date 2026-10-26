/**
 * Tira o MAC do que o leitor leu na etiqueta.
 *
 * A etiqueta da camera tem varios codigos (serial, MAC, P2P/QR). O do MAC
 * vem como "443B3282AA9D", "44:3B:32:82:AA:9D" ou dentro de um texto maior
 * ("MAC:44-3B-..."). Doze hexadecimais soltos so contam com borda dos dois
 * lados, senao um pedaco do serial viraria MAC.
 */
export function macDaEtiqueta(texto: string): string {
  const t = (texto || '').toUpperCase();
  const formata = (hexa: string) => hexa.match(/.{2}/g)!.join(':');
  const comSeparador = /(?<![0-9A-Z])([0-9A-F]{2})([:\-. ])([0-9A-F]{2})\2([0-9A-F]{2})\2([0-9A-F]{2})\2([0-9A-F]{2})\2([0-9A-F]{2})(?![0-9A-Z])/;
  const depoisDeMac = t.match(/MAC[^0-9A-F]{0,4}([0-9A-F:\-. ]{12,17})/);
  if (depoisDeMac) {
    const hexa = depoisDeMac[1].replace(/[^0-9A-F]/g, '');
    if (hexa.length >= 12) return formata(hexa.slice(0, 12));
  }
  const m = t.match(comSeparador);
  if (m) return formata([m[1], m[3], m[4], m[5], m[6], m[7]].join(''));
  const solto = t.match(/(?<![0-9A-Z])[0-9A-F]{12}(?![0-9A-Z])/);
  return solto ? formata(solto[0]) : '';
}

/** "44:3B:..." ou "443b32..." -> e um MAC inteiro? */
export const ehMac = (texto: string) => (texto || '').replace(/[^0-9A-Fa-f]/g, '').length === 12
  && /^[0-9A-Fa-f:\-. ]+$/.test((texto || '').trim());
