import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { imagem } from './api';

function base64(blob: Blob): Promise<string> {
  return new Promise((ok, falha) => {
    const r = new FileReader();
    r.onload = () => ok(String(r.result).split(',')[1] || '');
    r.onerror = () => falha(new Error('Não consegui ler o PDF.'));
    r.readAsDataURL(blob);
  });
}

/**
 * Baixa o PDF do servidor e entrega ao usuario.
 *
 * No celular, `<a download>` nao funciona dentro do WebView: o arquivo vai
 * para o cache do app e abre a folha de compartilhar do Android (WhatsApp,
 * e-mail, Drive, "Salvar em arquivos"). No navegador, baixa direto.
 */
export async function compartilharPdf(caminho: string, nome: string, titulo: string): Promise<void> {
  const blob = await imagem(caminho);
  if (blob.size < 100) throw new Error('O servidor devolveu um PDF vazio.');
  const arquivo = `${nome.replace(/[^A-Za-z0-9._-]+/g, '-').toLowerCase() || 'relatorio'}.pdf`;
  if (!Capacitor.isNativePlatform()) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = arquivo;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
    return;
  }
  const salvo = await Filesystem.writeFile({ path: arquivo, data: await base64(blob), directory: Directory.Cache });
  await Share.share({ title: titulo, url: salvo.uri, dialogTitle: 'Enviar relatório' });
}
