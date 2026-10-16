# Assistente Acadêmico

Sistema de gestão acadêmica (frequência, provas e CR) com um agente de IA no Telegram para consultas e atualizações em linguagem natural.

> Em construção. Etapa atual: regras de negócio e conjunto de teste do agente.

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
scripts/
  import_xlsx.py         importa a planilha antiga e audita as fórmulas
  show_summary.py        mostra frequência e CR no terminal
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
```
