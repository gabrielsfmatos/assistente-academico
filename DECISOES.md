# Diário de decisões

Registro do que foi decidido, por quê, o que deu errado e como foi corrigido.
Serve de base para os slides do AI Show Case e para as perguntas da entrevista.

Formato de cada entrada: **data · decisão** — motivo. Alternativas consideradas. Resultado.

## 14/10/2026

- **Problema escolhido: gestão acadêmica (frequência, provas e CR).** Eu já mantinha uma planilha no Google Sheets; a dor é abrir a planilha para registrar exceções e fazer contas (faltas restantes, CR).
- **Site próprio em vez de continuar no Google Sheets.** Controle do modelo de dados e das regras; o site permite edição direta e o agente é só um facilitador.
- **Agente de IA como facilitador, não como única interface.** Consultas e alterações sob demanda pelo WhatsApp; tudo também pode ser editado no site.
- **Entrada só por texto (sem áudio).** Mais prático no dia a dia e uma integração a menos.
- **Toda aula é presença ou falta; prova, teste e aula cancelada viram flags.** Aula cancelada sai do cálculo. A planilha tratava PROVA de forma diferente em cada disciplina.
- **Média final digitada manualmente.** O critério de avaliação muda por disciplina; reproduzir isso não vale o esforço.
- **CR só com disciplinas do curso de SI.** Norma da UNIRIO; na planilha a regra estava escondida na fórmula (Cálculo II). No sistema virou um atributo da disciplina.
- **Regras em código Python com testes automatizados.** O LLM nunca faz contas: só interpreta a mensagem e escolhe a função.

## O que encontrei ao importar a planilha (o "antes")

Ver `data/relatorio_importacao.md` (não vai para o GitHub). Resumo:
- faltas de Aprendizagem Profunda contadas em dobro;
- regra de PROVA diferente entre disciplinas;
- dia de TESTE fora de todas as contas;
- fórmulas ignorando a última semana do semestre;
- exclusão do Cálculo II escondida na fórmula do CR.

## 15/10/2026

- **Mantive o projeto atual em vez de um modelo de fraude/crédito.** Problema real, dados reais e
  "antes" mensurável; o padrão de agente (LLM interpreta, regras testadas executam, confirmação e
  log) é o mesmo de um agente de atendimento bancário. Fraude/crédito com dados fictícios seria
  comum entre candidatos e teria impacto só hipotético.
- **Trancamento como situação da disciplina, não exclusão.** Disciplina trancada sai do CR, da
  frequência e do cronograma, mas pode ser desfeita (o agente pode entender errado).
- **Prova cadastrada como fonte única da data.** A aula não guarda mais "dia de prova"; isso é
  consultado na tabela de avaliações, para as duas informações nunca ficarem diferentes.
- **Simulação de CR com lista incompleta:** calcula com as notas citadas e avisa quais disciplinas
  ficaram de fora.
- **Validação de datas:** falta ou cancelamento em dia sem aula é bloqueado; prova fora do dia da
  disciplina gera aviso e pede confirmação.
- **Na dúvida, o agente pergunta, nunca grava** (ex.: nota ilegível, disciplina não informada).
- **"Desfazer" reverte a última mensagem inteira**, com todas as ações dela (log de alterações em
  lotes).
- **Escopo fechado:** o agente recusa tudo que não for funcionalidade do sistema. Menos custo,
  menos risco de inventar respostas e mais fácil de testar.
- **Telegram em vez de WhatsApp:** gratuito, sem expiração de sandbox, sem endereço público
  (long polling). O bot responde apenas ao meu ID de usuário.
- **Site mobile-first** com 4 abas: Início (grade, provas, notas), Faltas (semana atual com
  navegação), Provas e Histórico (mesma estrutura da planilha). Fica depois do agente.
- **Conjunto de teste:** 29 frases escritas por mim (`tests/agent_cases.yaml`), avaliadas pelo
  estado final do banco, e não pelo nome das funções chamadas.

## 16/10/2026

- **Webinar do Nubank:** projeto em andamento é aceito, mas precisa ter resultados. Por isso o
  agente (que gera a taxa de acerto e o antes x depois) vem antes do site.
- **Quando o agente confirma antes de gravar:** registros claros (falta, nota, prova) são gravados
  direto, porque existe "desfazer"; pedem confirmação as alterações estruturais (trancar, regra de
  frequência, curso) e as correções em que o agente precisou deduzir algo.
- **Agente v1 (arquitetura):**
  - Eu executo as ferramentas (chamada automática do SDK desligada), para validar e registrar
    tudo no log.
  - Confirmação garantida por código, não só pelo prompt: trancar, mudar regra de frequência,
    mudar curso e prova com data estranha viram uma "ação pendente", que só roda com
    `confirmar_acao_pendente`. O modelo não consegue pular essa etapa.
  - Ferramentas devolvem números já formatados com vírgula, para o modelo só copiar.
  - O modelo do Gemini é configurável no `.env`; o adaptador fica isolado em `app/agent/llm.py`.
  - Limite de 6 idas e voltas por mensagem, para o agente não entrar em laço.
- **Avaliação:** `scripts/eval_agent.py` roda cada caso numa cópia limpa do banco e compara o
  estado final com o esperado. O critério em texto livre pode ser avaliado por um "juiz" LLM
  (`--judge`), opcional.

## 17/10/2026

- **Plano gratuito do Gemini insuficiente:** 20 chamadas/dia por modelo; a avaliação usa ~90.
  Ativei o faturamento com **pré-pagamento de R$ 30 e recarga automática desligada** (o saldo é
  um teto real de gastos). O crédito de US$ 300 do Google Cloud não cobre a API Gemini.
- **Modelos:** `gemini-2.5-flash-lite` (sugerido antes) já estava descontinuado para contas novas;
  troquei por `gemini-3.5-flash-lite` mudando só o `.env`.
- **Resultados v1 (prompt v1, 29 casos):**

  | Modelo | Acertos | Erros |
  |---|---|---|
  | gemini-3.8-flash | 27/29 (93%) | 2 conservadores: perguntou quando podia agir (casos 20 e 6) |
  | gemini-3.5-flash-lite | 28/29 (97%) | 1 **grave**: gravou nota 8 a partir de "oitcx" (caso 24) |

  Aprendizado: a taxa de acerto sozinha engana; um erro que grava dado errado é pior que uma
  pergunta a mais. O relatório passou a separar **erros graves**.
- **Mudanças da v2:**
  1. Prompt: prova nova sem nome é criada direto com o próximo nome livre (P1, P2...), escolhido
     pelo código; confirmação só para ALTERAR algo existente.
  2. Prompt: toda data citada é conferida com `aulas_do_dia` (dia da semana, se há aula).
  3. **Trava no código para notas:** as ferramentas de nota exigem a nota como o usuário
     escreveu (`nota_texto`). O código converte o texto sozinho ("9,3", "oito", "nove e meio") e
     recusa se não entender ou se o número for diferente. Nenhum modelo consegue gravar uma
     nota adivinhada, independentemente do prompt.
- **Resultados v2 (prompt v2, 29 casos):**

  | Modelo | Acertos | Erros graves | Observação |
  |---|---|---|---|
  | gemini-3.5-flash-lite | 29/29 (100%) | 0 | trava de notas recusou "oitcx" e o agente perguntou |
  | gemini-3.8-flash | 28/29 (97%) | 0 | caso 25: perguntou a disciplina, mas não conferiu a data (amanhã é sexta, sem aula) |

- **Modelo escolhido para o dia a dia: `gemini-3.5-flash-lite`.** Melhor resultado, zero erros
  graves e o mais barato. O 3.8-flash fica como alternativa no `.env`.
- **Segunda rodada da v2 no lite: 28/29**, 0 erros graves. Caso 18: o agente perguntou "P1 ou
  P2?" (em vez de propor a P2) e vazou um trecho das instruções na resposta. Variação natural
  entre rodadas: passo a reportar a **média de várias rodadas** (v2 lite: 29 e 28 → 98%).
- **v2.1:** em ambiguidade, propor a opção mais provável pelas datas e perguntar com sim/não;
  nunca citar as regras internas na resposta. Depois disso, paro de ajustar o prompt pelo
  conjunto de teste e passo a aprender com o uso real (Telegram).
- **Resultados v2.1 no lite: 29/29 e 29/29 (100% nas duas rodadas), 0 erros graves.**
  Evolução para o Show Case: v1 93–97% (com 1 erro grave) → v2 98% em média → v2.1 100%.
- **Telegram:** bot com long polling (`scripts/telegram_bot.py`), responde só ao meu
  `TELEGRAM_USER_ID`; mensagens processadas uma por vez (lock), na ordem em que chegam.
- **Site, etapa 1:** a primeira versão (visual de caderno, lista de aulas e resumo de faltas no
  topo) ficou sem cor e com informação demais no topo. **Refeita como agenda semanal no estilo do
  Teams:** colunas = dias, linhas = horários, uma cor por disciplina; falta = bloco cheio com
  etiqueta, aula cancelada = cinza listrado, prova = etiqueta amarela. Os detalhes (faltas,
  limite, frequência, próximas provas) aparecem ao tocar na aula, num painel que também permite
  marcar presença/falta, aula cancelada e teste. Toda alteração do site entra no mesmo log
  (origem "site") e pode ser desfeita, inclusive as feitas pelo agente.
- **HTMX incluído no projeto** (`app/web/static/htmx.min.js`), em vez de carregado de um CDN:
  o site não depende de serviço externo para funcionar na demonstração.

- **Hospedagem:** Oracle Cloud "Always Free" (máquina ARM em São Paulo, sem custo). Bot e site no
  mesmo servidor, com o SQLite em disco permanente. Plataformas gratuitas como Render não servem:
  desligam por inatividade ou apagam o banco a cada reinício. O site fica acessível só pelo
  Tailscale (rede privada) e com senha. A máquina será criada perto do uso real, porque a Oracle
  pode recuperar máquinas gratuitas ociosas.
- **Site, etapa 2:**
  - **Provas:** próximas, sem data e já feitas; criar, mudar data, lançar nota e excluir. Prova
    em dia sem aula é salva com aviso (no site a edição é direta e existe "desfazer"; no agente
    continua pedindo confirmação, porque ele pode ter entendido a data errado).
  - **Histórico:** períodos com CR, média final, trancar, curso da disciplina e regra de
    frequência. **Simulação de CR** ao vivo, sem salvar nada, usando a mesma função do agente.
  - **Excluir também entra no log:** o "desfazer" recria o registro apagado.
  - **Senha:** uma senha no `.env` (`SITE_PASSWORD`); o cookie guarda só uma assinatura (HMAC)
    da senha, nunca a senha. Senha errada espera 1 s, para dificultar tentativas em sequência.

## Antes x depois (medido em 17/10/2026)

Mesmo protocolo nos dois casos: quatro tarefas em sequência, cronômetro iniciado antes de
"chegar à ferramenta" (planilha: ligar o computador e abrir o Sheets; bot: desbloquear o celular
e abrir o Telegram). O bot já estava rodando, como estaria em uso real.

| Tarefa | Planilha (computador) | Bot (celular) | Redução |
|---|---|---|---|
| Registrar uma falta | 39 s | 17 s | −56% |
| Consultar as faltas de uma disciplina | 11 s | 11 s | 0% |
| Simular o CR do período | 1 min 46 s | 32 s | −70% |
| Simular o CR geral | 32 s | 20 s | −38% |
| **Total** | **3 min 08 s** | **1 min 20 s** | **−57%** |

Leitura honesta: consultas simples já eram rápidas na planilha (empate). O ganho está nas
tarefas que exigem chegar à ferramenta ou fazer contas (registro e simulações). Além do tempo,
o sistema corrigiu as 7 inconsistências de regra encontradas na planilha.
