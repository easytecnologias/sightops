import { useEffect, useState } from 'react';
import { pegar, salvar } from './storage';

const CHAVE = 'rua.site';

/* O site escolhido vale para o app inteiro e sobrevive a fechar o aplicativo:
   o tecnico passa o dia no mesmo lugar. Fica num evento proprio porque mais
   de uma tela precisa saber que ele mudou -- sem isso a lista continuaria
   mostrando o site anterior ate alguem navegar de novo. */
const EVENTO = 'rua:site';

let _memoria: string | null = null;

export function useSite() {
  const [site, setSite] = useState<string | null>(_memoria);
  const [pronto, setPronto] = useState(_memoria !== null);

  useEffect(() => {
    let vivo = true;
    if (_memoria === null) {
      pegar(CHAVE).then((v) => {
        if (!vivo) return;
        _memoria = v;
        setSite(v);
        setPronto(true);
      });
    }
    const ouvir = () => setSite(_memoria);
    window.addEventListener(EVENTO, ouvir);
    return () => { vivo = false; window.removeEventListener(EVENTO, ouvir); };
  }, []);

  const escolher = (s: string) => {
    _memoria = s;
    setSite(s);
    void salvar(CHAVE, s);
    window.dispatchEvent(new Event(EVENTO));
  };

  return { site, escolher, pronto };
}
