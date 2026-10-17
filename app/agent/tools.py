"""Ferramentas que o modelo de linguagem pode chamar.

Princípios:
- O modelo NÃO acessa o banco nem faz contas: ele escolhe uma ferramenta e os argumentos.
- Toda ferramenta chama a camada de serviços (as mesmas funções que o site usa).
- Toda resposta é um dicionário simples (vira JSON para o modelo).
- Erros de validação voltam como {"ok": False, "erro": ...} para o modelo explicar ao usuário.
- Alterações estruturais (trancar, regra de frequência, curso) e provas com data estranha
  NÃO são executadas na hora: viram uma "ação pendente" que só roda com confirmação.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from sqlmodel import Session, select

from app.agent.grade_text import check_grade
from app.models import Assessment, Course
from app.services import assessments as assessment_svc
from app.services import attendance as attendance_svc
from app.services import courses as course_svc
from app.services import grades as grades_svc
from app.services.changes import ChangeBatch, undo_last_batch

# ---------------------------------------------------------------- formatação


def br_number(value, places: Optional[int] = None) -> Optional[str]:
    """9.4212 -> '9,4212' (vírgula decimal, como o usuário escreve)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        text = str(value)
    elif places is not None:
        text = f"{value:.{places}f}"
    else:
        text = f"{value:g}"
    return text.replace(".", ",")


def br_date(day: Optional[date]) -> Optional[str]:
    if day is None:
        return None
    return f"{day:%d/%m/%Y} ({attendance_svc.WEEKDAY_NAMES[day.weekday()]})"


# ---------------------------------------------------------------- estado


@dataclass
class PendingAction:
    description: str
    run: Callable[[Session, ChangeBatch], dict]


@dataclass
class AgentState:
    """Estado que sobrevive entre mensagens da mesma conversa."""

    pending: Optional[PendingAction] = None


# ---------------------------------------------------------------- declarações

COURSE_ARG = {
    "type": "string",
    "description": "Sigla (ex.: ACD) ou nome da disciplina.",
}
DAY_ARG = {"type": "string", "description": "Data no formato AAAA-MM-DD."}
GRADE_TEXT_ARG = {
    "type": "string",
    "description": "A nota EXATAMENTE como o usuário escreveu (ex.: '9,3', 'oito', 'nove e meio').",
}

DECLARATIONS: list[dict] = [
    {
        "name": "consultar_situacao",
        "description": (
            "Situação de todas as disciplinas do período: faltas, limite de faltas, faltas "
            "restantes, frequência, se cobra frequência, média final e próximas avaliações. "
            "Use para perguntas sobre faltas, risco de reprovar e próximas provas."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "aulas_do_dia",
        "description": (
            "Lista as aulas de um dia com o estado atual (presença/falta, cancelada, prova). "
            "Use antes de registrar 'faltei hoje' ou 'fui só em X'."
        ),
        "parameters": {"type": "object", "properties": {"dia": DAY_ARG}, "required": ["dia"]},
    },
    {
        "name": "listar_avaliacoes",
        "description": "Lista as avaliações (P1, P2...) com datas e notas. Opcionalmente de uma disciplina.",
        "parameters": {"type": "object", "properties": {"disciplina": COURSE_ARG}},
    },
    {
        "name": "consultar_cr",
        "description": "CR acumulado atual e CR de cada período.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "simular_cr",
        "description": (
            "Simula o CR com médias finais hipotéticas. escopo='acumulado' (CR geral) ou "
            "'periodo' (CR só do período atual). Não grava nada."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "notas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"disciplina": COURSE_ARG, "nota": {"type": "number"}},
                        "required": ["disciplina", "nota"],
                    },
                },
                "escopo": {"type": "string", "enum": ["acumulado", "periodo"]},
            },
            "required": ["notas", "escopo"],
        },
    },
    {
        "name": "registrar_presenca",
        "description": "Registra presença ou falta em uma ou mais aulas.",
        "parameters": {
            "type": "object",
            "properties": {
                "registros": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "disciplina": COURSE_ARG,
                            "dia": DAY_ARG,
                            "presente": {"type": "boolean"},
                        },
                        "required": ["disciplina", "dia", "presente"],
                    },
                }
            },
            "required": ["registros"],
        },
    },
    {
        "name": "cancelar_aulas",
        "description": (
            "Marca aula(s) como cancelada(s) (saem do cálculo de frequência). "
            "Sem disciplina = todas as aulas do dia."
        ),
        "parameters": {
            "type": "object",
            "properties": {"dia": DAY_ARG, "disciplina": COURSE_ARG},
            "required": ["dia"],
        },
    },
    {
        "name": "marcar_avaliacao",
        "description": (
            "Cria uma avaliação com data, ou muda a data de uma existente. Se o usuário não "
            "disser qual avaliação é uma prova NOVA, omita 'nome': o sistema usa o próximo "
            "nome livre (P1, P2...)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "disciplina": COURSE_ARG,
                "nome": {"type": "string", "description": "Ex.: P1, P2. Opcional para prova nova."},
                "dia": DAY_ARG,
            },
            "required": ["disciplina", "dia"],
        },
    },
    {
        "name": "lancar_nota_avaliacao",
        "description": "Lança a nota de uma avaliação (ex.: 9,3 na P1).",
        "parameters": {
            "type": "object",
            "properties": {
                "disciplina": COURSE_ARG,
                "nome": {"type": "string"},
                "nota": {"type": "number"},
                "nota_texto": GRADE_TEXT_ARG,
            },
            "required": ["disciplina", "nome", "nota", "nota_texto"],
        },
    },
    {
        "name": "lancar_media_final",
        "description": "Lança a média final da disciplina (define aprovada/reprovada).",
        "parameters": {
            "type": "object",
            "properties": {
                "disciplina": COURSE_ARG,
                "nota": {"type": "number"},
                "nota_texto": GRADE_TEXT_ARG,
            },
            "required": ["disciplina", "nota", "nota_texto"],
        },
    },
    {
        "name": "desfazer_ultima_alteracao",
        "description": "Desfaz todas as alterações feitas pela última mensagem que alterou algo.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "trancar_disciplina",
        "description": "Tranca a disciplina (sai do CR, da frequência e da grade). Exige confirmação.",
        "parameters": {
            "type": "object",
            "properties": {"disciplina": COURSE_ARG},
            "required": ["disciplina"],
        },
    },
    {
        "name": "alterar_regra_frequencia",
        "description": "Define se a disciplina cobra frequência mínima. Exige confirmação.",
        "parameters": {
            "type": "object",
            "properties": {"disciplina": COURSE_ARG, "cobra_frequencia": {"type": "boolean"}},
            "required": ["disciplina", "cobra_frequencia"],
        },
    },
    {
        "name": "alterar_curso_disciplina",
        "description": (
            "Define em qual curso a disciplina foi cursada (só SI entra no CR). "
            "Ex.: curso='EP' para Engenharia de Produção. Exige confirmação."
        ),
        "parameters": {
            "type": "object",
            "properties": {"disciplina": COURSE_ARG, "curso": {"type": "string"}},
            "required": ["disciplina", "curso"],
        },
    },
    {
        "name": "confirmar_acao_pendente",
        "description": "Executa a ação que estava aguardando confirmação do usuário.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancelar_acao_pendente",
        "description": "Descarta a ação que estava aguardando confirmação.",
        "parameters": {"type": "object", "properties": {}},
    },
]

WRITE_TOOLS = {
    "registrar_presenca",
    "cancelar_aulas",
    "marcar_avaliacao",
    "lancar_nota_avaliacao",
    "lancar_media_final",
    "desfazer_ultima_alteracao",
    "confirmar_acao_pendente",
}


# ---------------------------------------------------------------- implementação


class AgentTools:
    def __init__(self, db: Session, today: date, batch: ChangeBatch, state: AgentState):
        self.db = db
        self.today = today
        self.batch = batch
        self.state = state

    # ----- infraestrutura

    def call(self, name: str, args: dict) -> dict:
        method = getattr(self, f"tool_{name}", None)
        if method is None:
            return {"ok": False, "erro": f"Ferramenta desconhecida: {name}"}
        try:
            return method(**(args or {}))
        except (ValueError, TypeError) as exc:  # validações dos serviços
            self.db.rollback()
            return {"ok": False, "erro": str(exc)}

    def _course(self, ref: str, only_current: bool = True) -> Course:
        matches = course_svc.find_courses(self.db, ref, only_current=only_current)
        if len(matches) == 1:
            return matches[0]
        options = ", ".join(
            f"{c.code or '-'} ({c.name})" for c in attendance_svc.current_courses(self.db)
        )
        if not matches:
            raise ValueError(f"Disciplina '{ref}' não encontrada. Disciplinas do período: {options}.")
        names = ", ".join(c.name for c in matches)
        raise ValueError(f"'{ref}' pode ser mais de uma disciplina: {names}. Pergunte qual.")

    @staticmethod
    def _day(text: str) -> date:
        try:
            return date.fromisoformat(text)
        except (TypeError, ValueError):
            raise ValueError(f"Data inválida: {text!r}. Use AAAA-MM-DD.") from None

    def _pending(self, description: str, run: Callable[[Session, ChangeBatch], dict]) -> dict:
        self.state.pending = PendingAction(description, run)
        return {
            "ok": True,
            "aguardando_confirmacao": True,
            "pergunta_ao_usuario": f"Confirma: {description}?",
        }

    # ----- consultas

    def tool_consultar_situacao(self) -> dict:
        summaries = {
            s.course_id: s for s in attendance_svc.summarize_all(self.db, self.today)
        }
        disciplinas = []
        for c in attendance_svc.current_courses(self.db):
            s = summaries.get(c.id)
            item = {
                "sigla": c.code,
                "nome": c.name,
                "situacao": c.status.value,
                "cobra_frequencia": c.requires_attendance,
                "media_final": br_number(c.final_grade),
            }
            if s is None:
                item["frequencia"] = "sem aulas no calendário"
            else:
                item.update(
                    faltas=s.absences,
                    limite_faltas=s.max_absences,
                    faltas_restantes=(s.remaining_absences if c.requires_attendance else None),
                    frequencia_ate_hoje=br_number(
                        round(s.frequency_to_date * 100, 1) if s.frequency_to_date is not None else None
                    ),
                    status_frequencia={
                        "ok": "ok",
                        "atencao": "atenção: poucas faltas restantes",
                        "reprovado_por_falta": "reprovado por falta",
                        "nao_cobra": "não cobra frequência mínima",
                    }[s.status],
                )
            disciplinas.append(item)
        return {
            "ok": True,
            "hoje": br_date(self.today),
            "disciplinas": disciplinas,
            "proximas_avaliacoes": [
                self._assessment_dict(a) for a in assessment_svc.upcoming(self.db, self.today)
            ],
        }

    def tool_aulas_do_dia(self, dia: str) -> dict:
        day = self._day(dia)
        sessions = attendance_svc.sessions_on(self.db, day)
        if not sessions:
            return {"ok": True, "dia": br_date(day), "aulas": [], "aviso": f"Não há aulas em {br_date(day)}."}
        aulas = []
        for s in sessions:
            aulas.append(
                {
                    "sigla": s.course.code,
                    "nome": s.course.name,
                    "presenca": "presente" if s.attended else "falta",
                    "cancelada": s.cancelled,
                    "prova": day in assessment_svc.exam_days(self.db, s.course_id),
                    "teste": s.has_quiz,
                }
            )
        return {"ok": True, "dia": br_date(day), "aulas": aulas}

    def _assessment_dict(self, a: Assessment) -> dict:
        return {
            "sigla": a.course.code,
            "disciplina": a.course.name,
            "avaliacao": a.name,
            "data": br_date(a.day),
            "nota": br_number(a.grade),
        }

    def tool_listar_avaliacoes(self, disciplina: Optional[str] = None) -> dict:
        query = select(Assessment)
        if disciplina:
            query = query.where(Assessment.course_id == self._course(disciplina).id)
        rows = sorted(self.db.exec(query).all(), key=lambda a: (a.day or date.max, a.name))
        return {"ok": True, "avaliacoes": [self._assessment_dict(a) for a in rows]}

    def tool_consultar_cr(self) -> dict:
        courses = self.db.exec(select(Course)).all()
        return {
            "ok": True,
            "cr_acumulado": br_number(grades_svc.compute_cr(courses)),
            "cr_por_periodo": {
                f"{t}º": br_number(v) for t, v in grades_svc.cr_by_term(courses).items() if v is not None
            },
        }

    def tool_simular_cr(self, notas: list, escopo: str = "acumulado") -> dict:
        hypothetical = {}
        for item in notas:
            course = self._course(item["disciplina"])
            hypothetical[course.id] = float(item["nota"])
        sim = grades_svc.simulate_cr(self.db, hypothetical, scope=escopo)
        result = {
            "ok": True,
            "escopo": escopo,
            "cr_simulado": br_number(sim.cr),
            "disciplinas_sem_nota_fora_do_calculo": sim.missing,
        }
        return result

    # ----- alterações diretas

    def tool_registrar_presenca(self, registros: list) -> dict:
        resultados = []
        for r in registros:
            item = {"disciplina": r.get("disciplina"), "dia": r.get("dia")}
            try:
                course = self._course(r["disciplina"])
                day = self._day(r["dia"])
                changed = attendance_svc.update_class_session(
                    self.db, course.id, day, attended=bool(r["presente"]), batch=self.batch
                )
                tipo = "presença" if r["presente"] else "falta"
                item.update(
                    disciplina=course.code or course.name,
                    dia=br_date(day),
                    resultado=f"{tipo} registrada" if changed else f"{tipo} já estava registrada",
                )
            except (ValueError, KeyError) as exc:
                self.db.rollback()
                item["erro"] = str(exc)
            resultados.append(item)
        return {"ok": all("erro" not in i for i in resultados), "resultados": resultados}

    def tool_cancelar_aulas(self, dia: str, disciplina: Optional[str] = None) -> dict:
        day = self._day(dia)
        if disciplina:
            course = self._course(disciplina)
            changed = attendance_svc.update_class_session(
                self.db, course.id, day, cancelled=True, batch=self.batch
            )
            return {
                "ok": True,
                "canceladas": [course.name],
                "dia": br_date(day),
                "ja_estava_cancelada": not changed,
            }
        names = attendance_svc.cancel_day(self.db, day, batch=self.batch)
        return {"ok": True, "canceladas": names, "dia": br_date(day)}

    def _next_assessment_name(self, course: Course) -> str:
        existing = {a.name for a in course.assessments}
        n = 1
        while f"P{n}" in existing:
            n += 1
        return f"P{n}"

    def tool_marcar_avaliacao(self, disciplina: str, dia: str, nome: Optional[str] = None) -> dict:
        course = self._course(disciplina)
        day = self._day(dia)
        nome = nome or self._next_assessment_name(course)
        warnings = assessment_svc.date_warnings(self.db, course, day)
        if warnings:
            def run(db: Session, batch: ChangeBatch) -> dict:
                assessment_svc.schedule_assessment(db, course.id, nome, day, batch)
                return {"ok": True, "feito": f"{nome} de {course.name} marcada para {br_date(day)}"}

            pending = self._pending(f"marcar {nome} de {course.name} em {br_date(day)}", run)
            pending["avisos"] = warnings
            return pending
        result = assessment_svc.schedule_assessment(self.db, course.id, nome, day, self.batch)
        return {
            "ok": True,
            "avaliacao": self._assessment_dict(result.assessment),
            "alterado": result.changed,
        }

    def tool_lancar_nota_avaliacao(
        self, disciplina: str, nome: str, nota: float, nota_texto: str = ""
    ) -> dict:
        grade = check_grade(nota, nota_texto)  # trava: só grava a nota que o usuário escreveu
        course = self._course(disciplina)
        a = assessment_svc.set_assessment_grade(self.db, course.id, nome, grade, self.batch)
        return {"ok": True, "avaliacao": self._assessment_dict(a)}

    def tool_lancar_media_final(self, disciplina: str, nota: float, nota_texto: str = "") -> dict:
        grade = check_grade(nota, nota_texto)  # trava: só grava a nota que o usuário escreveu
        course = self._course(disciplina)
        course_svc.set_final_grade(self.db, course.id, grade, today=self.today, batch=self.batch)
        self.db.refresh(course)
        return {
            "ok": True,
            "disciplina": course.name,
            "media_final": br_number(course.final_grade),
            "situacao": course.status.value,
        }

    def tool_desfazer_ultima_alteracao(self) -> dict:
        self.state.pending = None
        undone = undo_last_batch(self.db)
        if not undone:
            return {"ok": True, "desfeito": [], "aviso": "Não há alterações para desfazer."}
        return {"ok": True, "desfeito": undone}

    # ----- alterações que exigem confirmação

    def tool_trancar_disciplina(self, disciplina: str) -> dict:
        course = self._course(disciplina)

        def run(db: Session, batch: ChangeBatch) -> dict:
            course_svc.drop_course(db, course.id, batch)
            return {"ok": True, "feito": f"{course.name} trancada"}

        return self._pending(
            f"trancar {course.name} (sai do CR, da frequência e da grade; dá para desfazer)", run
        )

    def tool_alterar_regra_frequencia(self, disciplina: str, cobra_frequencia: bool) -> dict:
        course = self._course(disciplina)
        atual = "cobra" if course.requires_attendance else "não cobra"
        novo = "passa a cobrar" if cobra_frequencia else "deixa de cobrar"

        def run(db: Session, batch: ChangeBatch) -> dict:
            course_svc.set_requires_attendance(db, course.id, bool(cobra_frequencia), batch)
            return {"ok": True, "feito": f"{course.name} {novo} frequência mínima"}

        return self._pending(
            f"{course.name} {novo} frequência mínima (hoje está cadastrada como: {atual})", run
        )

    def tool_alterar_curso_disciplina(self, disciplina: str, curso: str) -> dict:
        course = self._course(disciplina, only_current=False)

        def run(db: Session, batch: ChangeBatch) -> dict:
            course_svc.set_program(db, course.id, curso, batch)
            return {"ok": True, "feito": f"{course.name} marcada como cursada em {curso.upper()}"}

        return self._pending(
            f"marcar {course.name} ({course.term}º período) como cursada em {curso.upper()} "
            "(sai do CR)",
            run,
        )

    def tool_confirmar_acao_pendente(self) -> dict:
        pending = self.state.pending
        if pending is None:
            return {"ok": False, "erro": "Não há nenhuma ação aguardando confirmação."}
        self.state.pending = None
        return pending.run(self.db, self.batch)

    def tool_cancelar_acao_pendente(self) -> dict:
        pending = self.state.pending
        self.state.pending = None
        if pending is None:
            return {"ok": True, "aviso": "Não havia ação pendente."}
        return {"ok": True, "cancelado": pending.description}
