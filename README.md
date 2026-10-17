# Assistente Acadêmico

Sistema de gestão acadêmica (frequência, provas e CR) com um agente de IA no Telegram para consultas e atualizações em linguagem natural.

> Em construção. Etapa atual: agente no Telegram em uso real.

## Arquitetura

```
Site (edição direta)  ─┐
                       ├→ camada de serviços (regras + validação) → SQLite
Agente (Telegram)  ────┘
```

O site e o agente usam as mesmas funções em `app/services/`. O agente nunca acessa o banco diretamente.

## Regras de negócio

- Toda aula é **presença** ou **falta**. Prova e teste são flags do dia; **aula cancelada sai do cálculo**.
- Frequência mínima de **75%**: no máximo 25% de faltas sobre as aulas previstas (arredondado para baixo).
- Aprovação: média final **≥ 7** (e frequência ≥ 75% nas disciplinas que cobram).
- **CR**: média ponderada por créditos, só com disciplinas do curso de Sistemas de Informação, truncada em 4 casas.
- Disciplina **trancada** sai do CR, da frequência e da grade (reversível).
- Toda alteração fica num **log**; "desfazer" reverte a última mensagem/ação inteira.

## Estrutura

```
app/
  models.py              tabelas: Course, ClassSession, Assessment, ScheduleSlot, ChangeLog
  db.py                  conexão com o SQLite
  services/
    attendance.py        regras de frequência
    grades.py            regras de notas e CR (inclui simulação)
    assessments.py       provas: datas, notas e avisos de data
    courses.py           disciplinas: busca, trancar, regras, média final
    changes.py           log de alterações e desfazer
  agent/
    tools.py             ferramentas que o LLM pode chamar (todas passam pelos serviços)
    grade_text.py        trava: só grava a nota que o usuário realmente escreveu
    prompt.py            instruções de sistema (regras de comportamento)
    llm.py               adaptador do Gemini (trocar de provedor = trocar este arquivo)
    agent.py             laço mensagem -> modelo -> ferramentas -> resposta
scripts/
  import_xlsx.py         importa a planilha antiga e audita as fórmulas
  show_summary.py        mostra frequência e CR no terminal
  check_gemini.py        testa a chave da API e lista os modelos
  chat.py                conversa com o agente pelo terminal
  eval_agent.py          roda os 29 casos e mede a taxa de acerto
  telegram_bot.py        o agente no Telegram (responde só ao dono)
tests/                   testes automatizados (pytest)
  agent_cases.yaml       29 frases de teste do agente com o resultado esperado
```

## Como rodar (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m scripts.import_xlsx "data\Gestao_Faculdade.xlsx" --reset
python -m scripts.show_summary
python -m pytest

# agente (precisa do .env com GEMINI_API_KEY)
python -m scripts.chat
python -m scripts.eval_agent --tag v1
python -m scripts.telegram_bot   # precisa de TELEGRAM_BOT_TOKEN e TELEGRAM_USER_ID
```
