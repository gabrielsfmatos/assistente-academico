# Assistente Acadêmico

Sistema de gestão acadêmica (frequência, provas e CR) com um agente de IA no WhatsApp para consultas e atualizações em linguagem natural.

> Em construção. Etapa atual: modelo de dados, regras de negócio e importação da planilha antiga.

## Arquitetura

```
Site (edição direta)  ─┐
                       ├→ camada de serviços (regras + validação) → SQLite
Agente (WhatsApp)  ────┘
```

O site e o agente usam as mesmas funções em `app/services/`. O agente nunca acessa o banco diretamente.

## Regras de negócio

- Toda aula é **presença** ou **falta**. Prova e teste são flags do dia; **aula cancelada sai do cálculo**.
- Frequência mínima de **75%**: no máximo 25% de faltas sobre as aulas previstas (arredondado para baixo).
- Aprovação: média final **≥ 7** (e frequência ≥ 75% nas disciplinas que cobram).
- **CR**: média ponderada por créditos, só com disciplinas do curso de Sistemas de Informação, truncada em 4 casas.

## Estrutura

```
app/
  models.py              tabelas: Course, ClassSession, Assessment, ScheduleSlot
  db.py                  conexão com o SQLite
  services/
    attendance.py        regras de frequência
    grades.py            regras de notas e CR
scripts/
  import_xlsx.py         importa a planilha antiga e audita as fórmulas
  show_summary.py        mostra frequência e CR no terminal
tests/                   testes automatizados (pytest)
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
