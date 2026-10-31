# SightOps Acesso: ficha do Google Play

Textos e respostas para cadastrar o app no Play Console (conta Easy Tecnologia).
Imagens: `icone-512.png` e `destaque-1024x500.png` (gerar de novo com `python scripts/gerar-loja.py`).
Pacote: `SightOps-Acesso-1.2.0.aab` (versionCode 3), gerado com `npm run aab`.

## Criar app

| Campo | Resposta |
|---|---|
| Nome do app | SightOps Acesso |
| Idioma padrão | Português (Brasil) – pt-BR |
| App ou jogo | App |
| Gratuito ou pago | Gratuito |

## Ficha principal da loja

**Nome (até 30):** SightOps Acesso

**Descrição curta (até 80):**
Cadastro de pessoas, visitantes e portas do controle de acesso SightOps.

**Descrição completa:**

O SightOps Acesso é o aplicativo da equipe de escolas, condomínios e empresas que usam a plataforma SightOps para controlar quem entra e quem sai.

Com ele, a portaria, a secretaria ou a administração faz pelo celular o que antes exigia um computador:

• Cadastrar pessoas com foto do rosto, já enviada aos leitores de reconhecimento facial
• Registrar visitantes na hora, com nome, documento e com quem vão falar
• Abrir e fechar portas autorizadas com dois toques
• Ver a frequência de entradas e saídas e gerar o relatório em PDF
• Trabalhar em mais de um local (escola, condomínio ou empresa), cada um com o vocabulário certo: aluno e turma, morador e apartamento, colaborador e setor

O acesso é restrito: só entra quem tem usuário criado pela instituição na plataforma SightOps, e cada pessoa vê apenas os locais e as funções que tem permissão para usar.

O SightOps Acesso não tem anúncios e não vende dados. A comunicação com a plataforma é criptografada.

Desenvolvido pela Easy Tecnologia, Maceió/AL.

**Categoria:** Empresas  ·  **Tags:** controle de acesso, segurança, gestão
**E-mail de contato:** easy@easytecnologias.com.br  ·  **Site:** https://easytecnologias.com.br
**Política de privacidade:** https://easytecnologias.com.br/privacidade/acesso/

## Conteúdo do app (Política do app)

| Seção | Resposta |
|---|---|
| Política de privacidade | https://easytecnologias.com.br/privacidade/acesso/ |
| Anúncios | Não, o app não contém anúncios |
| Acesso ao app | Todas ou algumas funcionalidades são restritas: informar o login de teste (ver abaixo) |
| Classificação do conteúdo | Categoria "Utilitário, produtividade, comunicação ou outro"; responder **Não** a violência, sexo, linguagem, drogas, jogos de azar. Interação entre usuários: Não. Compartilha localização: Não. Compras digitais: Não. |
| Público-alvo | **18 anos ou mais** (só). O app é para funcionários das instituições. |
| Apps de notícias | Não |
| Apps governamentais | Não |
| Recursos financeiros | Nenhum |
| Saúde | Não |
| ID de publicidade | Não usa |

### Acesso ao app (instruções para o revisor)

Criar no SightOps um **usuário de demonstração** num cliente de teste (nunca de cliente real), com 1 local, algumas pessoas fictícias e permissão só de cadastro e relatório. Texto para colar:

> O app é de uso interno de escolas, condomínios e empresas clientes. Use o usuário e a senha abaixo na tela de entrada. Depois de entrar, escolha o local "Demonstração". As pessoas cadastradas são fictícias.
> Usuário: ____  Senha: ____

## Segurança dos dados

Coleta ou compartilha dados? **Sim**. Criptografados em trânsito? **Sim**. O usuário pode pedir exclusão? **Sim** (pela instituição ou por easy@easytecnologias.com.br).

| Tipo de dado | Coletado | Compartilhado | Opcional? | Finalidade |
|---|---|---|---|---|
| Informações pessoais · Nome | Sim | Não | Obrigatório | Funcionalidade do app, gerenciamento da conta |
| Informações pessoais · E-mail | Sim | Não | Opcional | Funcionalidade do app (avisos) |
| Informações pessoais · Telefone | Sim | Não | Opcional | Funcionalidade do app (avisos por WhatsApp) |
| Informações pessoais · Outras informações (CPF, matrícula, turma) | Sim | Não | Obrigatório | Funcionalidade do app |
| Fotos e vídeos · Fotos | Sim | Não | Obrigatório | Funcionalidade do app (reconhecimento facial na portaria) |

- **Compartilhado = Não** porque os dados vão só para a plataforma da Easy (operadora) e para os equipamentos da própria instituição; a Play não conta isso como compartilhamento com terceiros.
- Dados **não** coletados: localização, contatos, áudio, arquivos, histórico de navegação, identificadores de publicidade, dados financeiros, saúde.
- Processamento temporário (efêmero)? **Não** para fotos e cadastro (ficam guardados no SightOps).

## Assinatura (Play App Signing)

Usar a **chave atual** (`sightops-acesso.jks`, alias `sightops-acesso`, SHA-256 C0:D2:05:1A…D1:06:53) para que quem já tem o APK receba a atualização pela loja. No Console: Configuração › Integridade do app › Assinatura do app › "Usar uma chave diferente" › "Exportar e enviar uma chave de um keystore Java". Baixar o `pepk.jar` e a chave de criptografia que o Console oferece e rodar o comando que ele mostra (a senha fica no `.senha.txt`, nunca no chat).
