---
name: sightops-analise-produto
description: Analisa o SightOps como PRODUTO com 11 agentes especialistas em paralelo (experiencia de uso, primeiro acesso, celular, desempenho percebido, confiabilidade, seguranca/LGPD, preco e licenca, concorrencia, vendas por segmento, integracoes, operacao/suporte) e junta tudo num relatorio de sugestoes priorizadas. Use quando o usuario pedir para "analisar o sistema e dar sugestoes", "o que melhorar para vender", "olhar tudo", "analise com agentes", ou quiser ideias de produto. Diferente de sightops-audit (que caca bug tecnico): aqui a pergunta e o que faz o cliente comprar, usar e continuar pagando.
disable-model-invocation: true
---

# Analise de produto com 11 agentes

So le e sugere. Nenhum agente edita arquivo, publica, ou fala com equipamento
de cliente. Responda ao usuario em portugues, em linguagem de dono de negocio.

## 1. Escopo

Se o usuario citou um modulo (ex.: "so o controle de acesso"), passe esse foco
a todos os agentes. Sem foco, o alvo e o sistema inteiro. Leia antes, rapido:
`README.md`, `app/core/permissions.py` (lista `MODULOS`) e
`app/services/licensing_service.py` (planos e precos). Resuma em 10 linhas o
que o produto e; esse resumo vai no inicio do prompt de cada agente.

## 2. Disparar os 11 agentes NUMA UNICA mensagem (em paralelo)

Use a ferramenta Agent, tipo `Explore` (so leitura) para os agentes 1 a 6 e 10
a 11, e `general-purpose` para 7, 8 e 9 (podem pesquisar na web). Cada prompt
leva: o resumo do passo 1, o foco, o papel abaixo e o formato de saida da
secao 3. Peca que cada um cite arquivo e linha (ou fonte web) como prova.

| # | Agente | O que procura |
|---|---|---|
| 1 | Experiencia de uso | Telas confusas, cliques demais, termos tecnicos para o cliente final, botoes sem retorno, tabelas que nao cabem (`frontend/js`, `frontend/index.html`) |
| 2 | Primeiro acesso | O caminho do cliente novo: cadastro, primeiro equipamento, primeiro resultado. Quanto tempo ate o "uau"? Ha tela vazia sem instrucao? |
| 3 | Celular | Apps em `mobile/` (acesso, alerta, dono, rua) e o painel em tela pequena: o que falta para o dono ou tecnico usar so pelo celular |
| 4 | Desempenho percebido | O que o usuario sente como lento: telas que carregam tudo de uma vez, falta de paginacao, chamadas em serie, varreduras sem progresso |
| 5 | Confiabilidade | Onde o sistema pode mostrar estado errado ou falhar calado (`except` mudo, status que nao expira, aviso que nao chega). Isso derruba a confianca do cliente |
| 6 | Seguranca e LGPD | Dado pessoal (CPF, foto, localizacao), consentimento, retencao, quem ve o que, isolamento entre clientes; o que um comprador ou prefeitura vai exigir |
| 7 | Preco e licenca | Coerencia de `licensing_service.py` com o valor de cada modulo; o que hoje sai de graca; sugestao de cobranca por unidade de valor (porta, aluno, veiculo, caixa, ONU) |
| 8 | Concorrencia | Pesquisa na web os concorrentes de cada modulo no Brasil (VMS, portaria/condominio, gestao de OLT, botao de panico, transporte escolar, auditoria de PDV): preco publico, o que eles tem que o SightOps nao tem, e o contrario |
| 9 | Vendas por segmento | Para integradora, provedor, condominio, escola/prefeitura, empresa e varejo: argumento de venda em uma frase, objecoes provaveis, o que falta no produto para fechar |
| 10 | Integracoes | O que conecta e o que falta: Zabbix, WhatsApp, Telegram, fabricantes, API publica, exportacao, ERP/CRM. Onde uma integracao faria o cliente ficar |
| 11 | Operacao e suporte | O que vai gerar chamado de suporte: mensagens de erro, falta de autoatendimento, falta de log visivel ao cliente, backup, atualizacao. Quanto custa atender cada cliente novo |

## 3. Formato que cada agente devolve

No maximo 8 achados, cada um com:

- **Achado** (uma frase, linguagem de negocio)
- **Prova** (arquivo:linha, tela, ou link)
- **Sugestao** (o que fazer)
- **Impacto** no cliente ou na venda: alto / medio / baixo
- **Esforco**: pequeno (dias) / medio (semanas) / grande (meses)

Sem achado inventado: se nao achou prova, nao entra.

## 4. Consolidar

1. Junte achados repetidos entre agentes (contam como mais fortes).
2. Monte a matriz impacto x esforco e separe:
   - **Fazer ja**: impacto alto, esforco pequeno.
   - **Planejar**: impacto alto, esforco medio/grande.
   - **Talvez**: impacto medio.
   - **Ignorar por agora**: impacto baixo.
3. De uma nota de 0 a 10 por area (as 11) e uma nota geral do produto.

## 5. Entregar

Comece pelo resultado: nota geral e as 5 acoes de "Fazer ja". Depois a tabela
de notas por area, depois o resto por grupo. Frases curtas; o usuario le no
celular. Se o relatorio for longo, ofereca publicar como pagina (Artifact)
para compartilhar com socio ou cliente.

Nao comece a implementar nada. Ao final, pergunte qual item o usuario quer
atacar primeiro.
