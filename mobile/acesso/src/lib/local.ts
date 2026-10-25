import { useEffect, useState } from 'react';
import { pegar, salvar } from './storage';

/* O local (escola, condominio, empresa) escolhido vale para o app inteiro e
   sobrevive a fechar o aplicativo. Evento proprio porque varias telas precisam
   saber na hora que ele mudou. */
const CHAVE = 'acesso.local';
const EVENTO = 'acesso:local';
let _memoria: string | null = null;
let _carregado = false;

export async function carregarLocal(): Promise<string | null> {
  if (!_carregado) { _memoria = await pegar(CHAVE); _carregado = true; }
  return _memoria;
}

export function escolherLocal(s: string) {
  _memoria = s;
  _carregado = true;
  void salvar(CHAVE, s);
  window.dispatchEvent(new Event(EVENTO));
}

export function useLocal(): string {
  const [local, setLocal] = useState<string>(_memoria ?? '');
  useEffect(() => {
    let vivo = true;
    carregarLocal().then((v) => { if (vivo) setLocal(v ?? ''); });
    const ouvir = () => setLocal(_memoria ?? '');
    window.addEventListener(EVENTO, ouvir);
    return () => { vivo = false; window.removeEventListener(EVENTO, ouvir); };
  }, []);
  return local;
}
