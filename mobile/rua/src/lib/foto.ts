import { useEffect, useState } from 'react';
import { API_BASE, tokenAtual } from './api';

/**
 * Carrega a foto da camera.
 *
 * O arquivo e protegido (401 sem sessao), e `<img src>` nao sabe mandar o
 * cabecalho Authorization -- no navegador o cookie resolve, mas dentro do
 * APK/IPA nao ha cookie: so o Bearer. Entao a imagem e buscada por fetch e
 * virada em objectURL, o que funciona nas duas plataformas pelo mesmo caminho.
 *
 * Sem rede nao ha foto: ela nao cabe no cache de texto que o resto do app usa.
 * A tela diz isso em vez de mostrar um quadrado quebrado.
 */
export type EstadoFoto = 'carregando' | 'pronta' | 'sem-foto' | 'sem-sinal' | 'erro';

export function useFoto(caminho?: string | null) {
  const [url, setUrl] = useState<string | null>(null);
  const [estado, setEstado] = useState<EstadoFoto>('carregando');

  useEffect(() => {
    if (!caminho) { setEstado('sem-foto'); setUrl(null); return; }
    if (!navigator.onLine) { setEstado('sem-sinal'); setUrl(null); return; }

    let vivo = true;
    let criada: string | null = null;
    setEstado('carregando');

    (async () => {
      try {
        const t = tokenAtual();
        const res = await fetch(API_BASE + caminho, {
          credentials: 'same-origin',
          headers: t ? { Authorization: `Bearer ${t}` } : undefined,
        });
        if (!res.ok) throw new Error(String(res.status));
        const blob = await res.blob();
        if (!vivo) return;
        criada = URL.createObjectURL(blob);
        setUrl(criada);
        setEstado('pronta');
      } catch {
        if (vivo) { setEstado('erro'); setUrl(null); }
      }
    })();

    // Sem revoke, cada visita a uma camera deixaria um blob preso na memoria
    // do webview -- num dia de campo isso vira dezenas de megabytes.
    return () => { vivo = false; if (criada) URL.revokeObjectURL(criada); };
  }, [caminho]);

  return { url, estado };
}
