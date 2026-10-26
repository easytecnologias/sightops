import { useState } from 'react';
import { Capacitor } from '@capacitor/core';
import { BarcodeScanner, GoogleBarcodeScannerModuleInstallState as Inst } from '@capacitor-mlkit/barcode-scanning';
import { macDaEtiqueta } from '../lib/etiqueta';
import { Icone } from './pecas';

/**
 * Botao "Ler etiqueta": abre o leitor de codigo do Google (tela pronta, sem
 * pedir permissao de camera) e devolve o MAC lido. Na primeira vez o Android
 * baixa o modulo do leitor -- avisamos em vez de parecer travado.
 */
export function useLeitorEtiqueta(aoLer: (mac: string) => void, aoErro: (msg: string) => void) {
  const [estado, setEstado] = useState<'' | 'baixando' | 'lendo'>('');

  async function garantirModulo() {
    const { available } = await BarcodeScanner.isGoogleBarcodeScannerModuleAvailable();
    if (available) return;
    setEstado('baixando');
    await new Promise<void>((ok, falha) => {
      let feito = false;
      void BarcodeScanner.addListener('googleBarcodeScannerModuleInstallProgress', (e) => {
        if (feito) return;
        if (e.state === Inst.COMPLETED) { feito = true; ok(); }
        if (e.state === Inst.FAILED || e.state === Inst.CANCELED) { feito = true; falha(new Error('Não deu para baixar o leitor de etiqueta. Confira a internet e tente de novo.')); }
      });
      BarcodeScanner.installGoogleBarcodeScannerModule().catch((e) => { if (!feito) { feito = true; falha(e); } });
      setTimeout(() => { if (!feito) { feito = true; falha(new Error('O leitor ainda está baixando. Tente de novo em instantes.')); } }, 90000);
    }).finally(() => { void BarcodeScanner.removeAllListeners(); });
  }

  async function ler() {
    if (!Capacitor.isNativePlatform()) { aoErro('A leitura da etiqueta funciona no app do celular.'); return; }
    try {
      await garantirModulo();
      setEstado('lendo');
      const { barcodes } = await BarcodeScanner.scan();
      const textos = barcodes.map((b) => b.rawValue || b.displayValue || '').filter(Boolean);
      const mac = textos.map(macDaEtiqueta).find(Boolean);
      if (mac) aoLer(mac);
      else if (textos.length) aoErro(`Li “${textos[0].slice(0, 40)}”, que não é o MAC. Aponte para o código ao lado de “MAC”.`);
    } catch (e) {
      const msg = (e as Error).message || '';
      if (!/cancel/i.test(msg)) aoErro(msg || 'Não deu para ler a etiqueta.');
    } finally { setEstado(''); }
  }

  return { estado, ler };
}

export function LerEtiqueta({ aoLer, aoErro }: { aoLer: (mac: string) => void; aoErro: (msg: string) => void }) {
  const { estado, ler } = useLeitorEtiqueta(aoLer, aoErro);
  return (
    <button type="button" className="btn2" disabled={!!estado} onClick={() => void ler()}>
      {Icone.camera}{estado === 'baixando' ? 'Baixando o leitor (só na 1ª vez)…' : estado === 'lendo' ? 'Lendo…' : 'Ler etiqueta da câmera'}
    </button>
  );
}
