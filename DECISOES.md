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
