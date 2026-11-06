package br.com.easytecnologias.termico.mega;

import android.os.Bundle;
import android.view.ViewGroup;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Com a tela de ponta a ponta, o Android nao encolhe o app quando o teclado
        // abre e o Capacitor so desconta as barras do sistema: sem isto o teclado
        // cobre os campos. Este ouvinte substitui o dele e soma o teclado.
        ViewCompat.setOnApplyWindowInsetsListener(bridge.getWebView(), (v, janela) -> {
            Insets barras = janela.getInsets(WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout());
            Insets teclado = janela.getInsets(WindowInsetsCompat.Type.ime());
            ViewGroup.MarginLayoutParams m = (ViewGroup.MarginLayoutParams) v.getLayoutParams();
            m.leftMargin = barras.left;
            m.topMargin = barras.top;
            m.rightMargin = barras.right;
            m.bottomMargin = Math.max(barras.bottom, teclado.bottom);
            v.setLayoutParams(m);
            return WindowInsetsCompat.CONSUMED;
        });
    }
}
