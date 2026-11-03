# SightOps Rua: ficha do Google Play

Textos e respostas para cadastrar o app no Play Console (conta Easy Tecnologia).
Imagens: `icone-512.png`, `destaque-1024x500.png` (`python scripts/gerar-loja.py`) e capturas
`tela-*.png` com dados fictícios (`npm run build && python scripts/telas-loja.py`; a do mapa fica de fora,
sem fundo de mapa no teste).
Pacote: `SightOps-Rua-2.0.19.aab` (versionCode 30), minSdk 24, target 36.

## Criar app

| Campo | Resposta |
|---|---|
| Nome do app | SightOps Rua |
| Nome do pacote | `br.com.easytecnologias.sightops.rua` |
| Idioma padrão | Português (Brasil) – pt-BR |
| App ou jogo | App |
| Gratuito ou pago | Gratuito |

**Logo depois de criar:** Protegido com o Google Play › Assinatura de apps › **Mudar chave** › "Exportar e fazer
upload de uma chave de um keystore Java" (chave `sightops-rua.jks`, SHA-256 55:A1:99:7C…C1:7A). Só então enviar o AAB.

## Ficha principal da loja

**Nome (até 30):** SightOps Rua

**Descrição curta (até 80):**
App de campo do técnico: câmeras, gravadores, fibra (OLT/ONU) e switches.

**Descrição completa:**

O SightOps Rua é o aplicativo de campo dos técnicos que instalam e mantêm os equipamentos monitorados pela plataforma SightOps: câmeras, gravadores (NVR/DVR), redes de fibra (OLT e ONU), switches e controle de acesso.

No celular, o técnico vê o que precisa de atenção no site e resolve na hora:

• Início com o que está fora do ar ou com sinal ruim no site escolhido
• Equipamentos por Rede, CFTV e Acesso, com o caminho do sinal: conector, OLT, PON, ONU, switch, câmera e canal do gravador
• Ficha da ONU com sinal recebido e enviado, distância e histórico das últimas horas
• Implantar: ativar ONU nova, ativar câmera de fábrica, ajustar IP e nome, cadastrar no gravador
• Ler a etiqueta do equipamento para preencher o MAC sem digitar
• Vídeo ao vivo para conferir a imagem logo depois da instalação
• Mapa do site com as câmeras e os cabos

O acesso é restrito: só entra quem tem usuário criado pela empresa na plataforma SightOps, e cada técnico vê apenas os sites e as funções que tem permissão para usar.

O SightOps Rua não tem anúncios e não vende dados. A comunicação com a plataforma é criptografada.

Desenvolvido pela Easy Tecnologia, Maceió/AL.

**Categoria:** Empresas · **E-mail:** easy@easytecnologias.com.br · **Site:** https://easytecnologias.com.br
**Política de privacidade:** https://easytecnologias.com.br/privacidade/rua/

## Conteúdo do app

| Seção | Resposta |
|---|---|
| Política de privacidade | https://easytecnologias.com.br/privacidade/rua/ |
| Anúncios | Não |
| ID de publicidade | Não usa (conferido no APK: só INTERNET, localização, câmera e estado da rede) |
| Detalhes do login | **Sim**: mesmo usuário de demonstração do Acesso (`revisor.play`, cliente demo-play), texto PT + EN abaixo |
| Classificação | "Todos os outros tipos"; Não para tudo |
| Público-alvo | Só 18+ |
| Apps governamentais / Recursos financeiros / Saúde | Não / Nenhum / Nenhum |
| Categoria | App · Empresas |

### Detalhes do login (outras informações)

> Ferramenta de campo de técnicos de empresas clientes. Entre com o usuário e a senha acima (o PIN é opcional). A conta de demonstração não tem equipamentos reais conectados, por isso as listas aparecem vazias; os comandos (ativar ONU, reiniciar câmera) só funcionam com equipamento do cliente.
> EN: Field tool for client technicians. Log in with the username and password above (PIN is optional). The demo account has no real devices connected, so lists are empty; device commands only work with the client's equipment.

## Segurança dos dados

Coleta ou compartilha dados? **Sim**. Criptografados em trânsito? **Sim**. Pedido de exclusão? **Sim** (pela empresa ou por easy@easytecnologias.com.br).

| Tipo de dado | Coletado | Compartilhado | Opcional? | Finalidade |
|---|---|---|---|---|
| Local · Local exato | Sim | Não | Opcional | Funcionalidade do app (coordenadas do equipamento instalado, só quando o técnico toca em "usar minha posição") |
| Atividade no app · Outras ações | Sim | Não | Obrigatório | Funcionalidade do app (registro de quem ativou/alterou cada equipamento) |
| Informações pessoais · ID do usuário | Sim | Não | Obrigatório | Gerenciamento da conta |

- Não coletados: contatos, fotos, áudio, arquivos, identificadores de publicidade, financeiros, saúde.
- A localização do mapa (ponto azul) fica no aparelho e não é enviada.
- Localização só em primeiro plano: não precisa da declaração de localização em segundo plano.
