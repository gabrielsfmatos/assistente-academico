"""Testes do agente SEM chamar a API do Gemini.

- As ferramentas são testadas diretamente (são código comum).
- O laço do agente usa um "modelo falso" com respostas roteirizadas.
"""

from datetime import timedelta

import pytest
from sqlmodel import Session

from app.agent.agent import Agent
from app.agent.llm import LLMReply, ToolCall
from app.agent.prompt import build_system_prompt
from app.agent.tools import AgentState, AgentTools
from app.models import Course, CourseStatus
from app.services.attendance import get_class_session
from app.services.changes import ChangeBatch
from tests.conftest import MONDAY

TUESDAY = MONDAY + timedelta(days=1)


@pytest.fixture
def tools(db):
    return AgentTools(db, TUESDAY, ChangeBatch(source="agente"), AgentState())


# ---------- ferramentas ----------


def test_aulas_do_dia(tools):
    result = tools.call("aulas_do_dia", {"dia": "2026-10-13"})
    assert [a["sigla"] for a in result["aulas"]] == ["AP"]


def test_aulas_do_dia_weekend(tools):
    result = tools.call("aulas_do_dia", {"dia": "2026-10-17"})
    assert result["aulas"] == [] and "sábado" in result["aviso"]


def test_registrar_presenca_and_duplicate(tools):
    args = {"registros": [{"disciplina": "AP", "dia": "2026-10-13", "presente": False}]}
    first = tools.call("registrar_presenca", args)
    second = tools.call("registrar_presenca", args)
    assert first["resultados"][0]["resultado"] == "falta registrada"
    assert second["resultados"][0]["resultado"] == "falta já estava registrada"


def test_registrar_presenca_day_without_class(tools):
    args = {"registros": [{"disciplina": "AP", "dia": "2026-10-12", "presente": False}]}
    result = tools.call("registrar_presenca", args)
    assert result["ok"] is False
    assert "segunda" in result["resultados"][0]["erro"]


def test_unknown_course_lists_options(tools):
    result = tools.call(
        "lancar_nota_avaliacao", {"disciplina": "TPS", "nome": "P1", "nota": 8, "nota_texto": "8"}
    )
    assert result["ok"] is False
    assert "ACD" in result["erro"]


def test_grade_guess_is_not_saved(tools):
    result = tools.call(
        "lancar_nota_avaliacao", {"disciplina": "ACD", "nome": "P1", "nota": 8, "nota_texto": "oitcx"}
    )
    assert result["ok"] is False and "Não entendi" in result["erro"]
    assert tools.call("listar_avaliacoes", {"disciplina": "ACD"})["avaliacoes"] == []


def test_grade_in_words_is_saved(tools):
    result = tools.call(
        "lancar_nota_avaliacao", {"disciplina": "EI", "nome": "p1", "nota": 9.5, "nota_texto": "nove e meio"}
    )
    assert result["avaliacao"]["nota"] == "9,5"


def test_final_grade_requires_matching_text(tools):
    result = tools.call("lancar_media_final", {"disciplina": "AP", "nota": 9.2, "nota_texto": "8,2"})
    assert result["ok"] is False


def test_new_assessment_gets_next_free_name(tools):
    first = tools.call("marcar_avaliacao", {"disciplina": "ACD", "dia": "2026-10-21"})
    second = tools.call("marcar_avaliacao", {"disciplina": "ACD", "dia": "2026-10-26"})
    assert first["avaliacao"]["avaliacao"] == "P1"
    assert second["avaliacao"]["avaliacao"] == "P2"


def test_invalid_date(tools):
    result = tools.call("aulas_do_dia", {"dia": "ontem"})
    assert result["ok"] is False and "AAAA-MM-DD" in result["erro"]


def test_marcar_avaliacao_with_bad_date_needs_confirmation(tools, db):
    result = tools.call("marcar_avaliacao", {"disciplina": "ACD", "nome": "P1", "dia": "2026-11-15"})
    assert result["aguardando_confirmacao"] is True
    assert "domingo" in result["avisos"][0]
    assert tools.call("listar_avaliacoes", {"disciplina": "ACD"})["avaliacoes"] == []
    tools.call("confirmar_acao_pendente", {})
    assert len(tools.call("listar_avaliacoes", {"disciplina": "ACD"})["avaliacoes"]) == 1


def test_trancar_only_after_confirmation(tools, db):
    result = tools.call("trancar_disciplina", {"disciplina": "AP"})
    assert result["aguardando_confirmacao"] is True
    assert db.get(Course, 3).status == CourseStatus.IN_PROGRESS
    tools.call("confirmar_acao_pendente", {})
    assert db.get(Course, 3).status == CourseStatus.DROPPED


def test_cancel_pending(tools, db):
    tools.call("trancar_disciplina", {"disciplina": "AP"})
    tools.call("cancelar_acao_pendente", {})
    assert tools.call("confirmar_acao_pendente", {})["ok"] is False
    assert db.get(Course, 3).status == CourseStatus.IN_PROGRESS


def test_simular_cr_uses_comma(tools):
    result = tools.call(
        "simular_cr", {"notas": [{"disciplina": "ACD", "nota": 10}], "escopo": "periodo"}
    )
    assert result["cr_simulado"] == "10,00"
    assert len(result["disciplinas_sem_nota_fora_do_calculo"]) == 2


def test_consultar_situacao(tools):
    result = tools.call("consultar_situacao", {})
    ei = next(d for d in result["disciplinas"] if d["sigla"] == "EI")
    assert ei["status_frequencia"] == "não cobra frequência mínima"
    assert ei["faltas_restantes"] is None
    assert result["proximas_avaliacoes"][0]["avaliacao"] == "P1"


def test_prompt_lists_courses(db):
    prompt = build_system_prompt(db, TUESDAY)
    assert "ACD = Algoritmos para Ciência de Dados" in prompt
    assert "terça, 13/10/2026" in prompt


# ---------- laço do agente com modelo falso ----------


class FakeChat:
    """Devolve respostas roteirizadas e guarda o que recebeu."""

    def __init__(self, script):
        self.script = list(script)
        self.received = []

    def send_user(self, text):
        self.received.append(("user", text))
        return self.script.pop(0)

    def send_tool_results(self, results):
        self.received.append(("tools", results))
        return self.script.pop(0)


def make_agent(engine, script):
    chat = FakeChat(script)
    agent = Agent(engine, today_fn=lambda: TUESDAY, chat_factory=lambda prompt, decls: chat)
    return agent, chat


def test_agent_executes_tool_and_replies(engine):
    agent, chat = make_agent(
        engine,
        [
            LLMReply(
                "",
                [
                    ToolCall(
                        "registrar_presenca",
                        {"registros": [{"disciplina": "AP", "dia": "2026-10-13", "presente": False}]},
                    )
                ],
            ),
            LLMReply("Falta registrada em AP hoje."),
        ],
    )
    reply = agent.reply("faltei hoje")
    assert reply.text == "Falta registrada em AP hoje."
    assert reply.wrote
    with Session(engine) as db:
        assert get_class_session(db, 3, TUESDAY).attended is False


def test_agent_undo_reverts_previous_message(engine):
    falta = ToolCall(
        "registrar_presenca",
        {"registros": [{"disciplina": "AP", "dia": "2026-10-13", "presente": False}]},
    )
    agent, chat = make_agent(
        engine,
        [
            LLMReply("", [falta]),
            LLMReply("Feito."),
            LLMReply("", [ToolCall("desfazer_ultima_alteracao", {})]),
            LLMReply("Desfeito."),
        ],
    )
    agent.reply("faltei hoje")
    agent.reply("desfaça a última alteração")
    with Session(engine) as db:
        assert get_class_session(db, 3, TUESDAY).attended is True


def test_agent_refusal_uses_no_tools(engine):
    agent, _ = make_agent(engine, [LLMReply("Só ajudo com sua vida acadêmica.")])
    reply = agent.reply("quantos anos tem o presidente?")
    assert reply.trace == [] and not reply.wrote


def test_agent_stops_after_max_steps(engine):
    loop = [LLMReply("", [ToolCall("consultar_cr", {})]) for _ in range(10)]
    agent, _ = make_agent(engine, loop)
    reply = agent.reply("cr?")
    assert "Não consegui concluir" in reply.text
