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
