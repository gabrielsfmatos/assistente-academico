"""Regras de frequência.

Regras (definidas por Gabriel):
- Toda aula é presença ou falta. Prova e teste são só destaques do dia.
- Aula cancelada sai do cálculo de frequência.
- Frequência mínima de 75% => no máximo 25% de faltas sobre as aulas
  previstas no semestre (arredondando para baixo).
- Disciplinas com requires_attendance=False não reprovam por falta.
- Disciplinas trancadas saem da frequência e da grade.
- Não é possível registrar falta/cancelamento em dia sem aula.
"""

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from math import floor
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models import ClassSession, Course, CourseStatus
from app.services.changes import ChangeBatch, update_fields

MAX_ABSENCE_RATIO = Fraction(1, 4)  # 25% (Fraction evita erro de ponto flutuante)
WARNING_THRESHOLD = 2  # alerta quando restarem 2 faltas ou menos
WEEKDAY_NAMES = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


class NoClassError(ValueError):
    """Tentativa de alterar uma aula que não existe naquele dia."""


@dataclass(frozen=True)
class AttendanceSummary:
    course_id: Optional[int]
    course_name: str
    requires_attendance: bool
    planned_sessions: int  # aulas previstas no semestre (sem as canceladas)
    held_sessions: int  # aulas que já aconteceram até `today`
    absences: int
    max_absences: int
    remaining_absences: int
    frequency_to_date: Optional[float]  # None se nenhuma aula aconteceu ainda
    projected_frequency: Optional[float]  # considerando o semestre inteiro
    status: str  # "ok" | "atencao" | "reprovado_por_falta" | "nao_cobra"


def max_allowed_absences(planned_sessions: int) -> int:
    return floor(planned_sessions * MAX_ABSENCE_RATIO)


def compute_summary(
    sessions: Iterable[ClassSession],
    today: date,
    course_name: str = "",
    requires_attendance: bool = True,
    course_id: Optional[int] = None,
) -> AttendanceSummary:
    """Função pura: recebe as aulas e calcula tudo. Fácil de testar."""
    counted = [s for s in sessions if not s.cancelled]
    held = [s for s in counted if s.day <= today]

    planned = len(counted)
    absences = sum(1 for s in counted if not s.attended)
    absences_to_date = sum(1 for s in held if not s.attended)
    max_abs = max_allowed_absences(planned)
    remaining = max_abs - absences

    freq_to_date = (len(held) - absences_to_date) / len(held) if held else None
    projected = (planned - absences) / planned if planned else None

    if not requires_attendance:
        status = "nao_cobra"
    elif remaining < 0:
        status = "reprovado_por_falta"
    elif remaining <= WARNING_THRESHOLD:
        status = "atencao"
    else:
        status = "ok"

    return AttendanceSummary(
        course_id=course_id,
        course_name=course_name,
        requires_attendance=requires_attendance,
        planned_sessions=planned,
        held_sessions=len(held),
        absences=absences,
        max_absences=max_abs,
        remaining_absences=remaining,
        frequency_to_date=freq_to_date,
        projected_frequency=projected,
        status=status,
    )


# ---------- Consultas (usadas pelo site e pelo agente) ----------


def current_term(db: Session) -> Optional[int]:
    terms = db.exec(select(Course.term)).all()
    return max(terms) if terms else None


def current_courses(db: Session) -> list[Course]:
    """Disciplinas do período atual que não foram trancadas."""
    term = current_term(db)
    if term is None:
        return []
    courses = db.exec(
        select(Course).where(Course.term == term, Course.status != CourseStatus.DROPPED)
    ).all()
    return sorted(courses, key=lambda c: c.name)


def summarize_course(db: Session, course: Course, today: date) -> AttendanceSummary:
    sessions = db.exec(select(ClassSession).where(ClassSession.course_id == course.id)).all()
    return compute_summary(
        sessions,
        today,
        course_name=course.name,
        requires_attendance=course.requires_attendance,
        course_id=course.id,
    )


def summarize_all(db: Session, today: date) -> list[AttendanceSummary]:
    return [
        summarize_course(db, c, today)
        for c in current_courses(db)
        if c.sessions  # ignora disciplinas sem aulas no calendário (ex.: extensão)
    ]


def sessions_on(db: Session, day: date) -> list[ClassSession]:
    """Aulas de um dia, sem disciplinas trancadas (usado para "faltei hoje")."""
    rows = db.exec(
        select(ClassSession)
        .join(Course)
        .where(ClassSession.day == day, Course.status != CourseStatus.DROPPED)
    ).all()
    return sorted(rows, key=lambda s: s.course.name)


def sessions_between(db: Session, start: date, end: date) -> list[ClassSession]:
    """Aulas de um intervalo (usado pela tela da semana)."""
    rows = db.exec(
        select(ClassSession)
        .join(Course)
        .where(
            ClassSession.day >= start,
            ClassSession.day <= end,
            Course.status != CourseStatus.DROPPED,
        )
    ).all()
    return sorted(rows, key=lambda s: (s.day, s.course.name))


def get_class_session(db: Session, course_id: int, day: date) -> ClassSession:
    cs = db.exec(
        select(ClassSession).where(ClassSession.course_id == course_id, ClassSession.day == day)
    ).first()
    if cs is None or cs.course.status == CourseStatus.DROPPED:
        course = db.get(Course, course_id)
        name = course.name if course else f"disciplina {course_id}"
        raise NoClassError(
            f"{name} não tem aula em {day:%d/%m/%Y} ({WEEKDAY_NAMES[day.weekday()]})."
        )
    return cs


# ---------- Alterações ----------


def update_class_session(
    db: Session,
    course_id: int,
    day: date,
    *,
    attended: Optional[bool] = None,
    cancelled: Optional[bool] = None,
    has_quiz: Optional[bool] = None,
    note: Optional[str] = None,
    batch: Optional[ChangeBatch] = None,
) -> bool:
    """Altera uma aula existente. Só muda os campos informados.

    Gera NoClassError se a disciplina não tem aula nesse dia: assim nem o
    site nem o agente conseguem registrar falta num dia sem aula.
    Retorna False se nada mudou (ex.: a falta já estava registrada).
    """
    cs = get_class_session(db, course_id, day)
    fields = {
        k: v
        for k, v in {
            "attended": attended,
            "cancelled": cancelled,
            "has_quiz": has_quiz,
            "note": note,
        }.items()
        if v is not None  # só os campos informados
    }
    labels = []
    if attended is not None:
        labels.append("presença" if attended else "falta")
    if cancelled is not None:
        labels.append("aula cancelada" if cancelled else "aula confirmada")
    if has_quiz is not None:
        labels.append("teste" if has_quiz else "sem teste")
    description = f"{cs.course.name} em {day:%d/%m}: {', '.join(labels) or 'observação'}"
    return update_fields(db, cs, fields, batch, description)


def cancel_day(db: Session, day: date, batch: Optional[ChangeBatch] = None) -> list[str]:
    """Cancela todas as aulas de um dia. Retorna os nomes das disciplinas afetadas."""
    sessions = sessions_on(db, day)
    if not sessions:
        raise NoClassError(f"Você não tem aulas em {day:%d/%m/%Y} ({WEEKDAY_NAMES[day.weekday()]}).")
    batch = batch or ChangeBatch()
    for cs in sessions:
        update_class_session(db, cs.course_id, day, cancelled=True, batch=batch)
    return [cs.course.name for cs in sessions]
