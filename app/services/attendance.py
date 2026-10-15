"""Regras de frequência.

Regras (definidas por Gabriel):
- Toda aula é presença ou falta. Prova e teste são só flags do dia.
- Aula cancelada sai do cálculo de frequência.
- Frequência mínima de 75% => no máximo 25% de faltas sobre as aulas
  previstas no semestre (arredondando para baixo).
- Disciplinas com requires_attendance=False não reprovam por falta.
"""

from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from math import floor
from typing import Iterable, Optional

from sqlmodel import Session, select

from app.models import ClassSession, Course

MAX_ABSENCE_RATIO = Fraction(1, 4)  # 25% (Fraction evita erro de ponto flutuante)
WARNING_THRESHOLD = 2  # alerta quando restarem 2 faltas ou menos


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


# ---------- Funções que acessam o banco (usadas pelo site e pelo agente) ----------


def summarize_course(db: Session, course: Course, today: date) -> AttendanceSummary:
    sessions = db.exec(select(ClassSession).where(ClassSession.course_id == course.id)).all()
    return compute_summary(
        sessions,
        today,
        course_name=course.name,
        requires_attendance=course.requires_attendance,
        course_id=course.id,
    )


def current_courses(db: Session) -> list[Course]:
    """Disciplinas do período atual (o maior período cadastrado)."""
    courses = db.exec(select(Course)).all()
    if not courses:
        return []
    current_term = max(c.term for c in courses)
    return sorted((c for c in courses if c.term == current_term), key=lambda c: c.name)


def summarize_all(db: Session, today: date) -> list[AttendanceSummary]:
    return [
        summarize_course(db, c, today)
        for c in current_courses(db)
        if c.sessions  # ignora disciplinas sem aulas no calendário (ex.: extensão)
    ]


def sessions_on(db: Session, day: date) -> list[ClassSession]:
    """Aulas de um dia (usado para entender "faltei hoje")."""
    return list(db.exec(select(ClassSession).where(ClassSession.day == day)).all())


def update_class_session(
    db: Session,
    course_id: int,
    day: date,
    *,
    attended: Optional[bool] = None,
    cancelled: Optional[bool] = None,
    has_exam: Optional[bool] = None,
    has_quiz: Optional[bool] = None,
    note: Optional[str] = None,
) -> ClassSession:
    """Altera uma aula existente. Só muda os campos informados.

    Gera erro se a disciplina não tem aula nesse dia: assim nem o site
    nem o agente conseguem registrar falta num dia sem aula.
    """
    cs = db.exec(
        select(ClassSession).where(ClassSession.course_id == course_id, ClassSession.day == day)
    ).first()
    if cs is None:
        raise ValueError(f"Não existe aula da disciplina {course_id} em {day:%d/%m/%Y}.")

    for field, value in {
        "attended": attended,
        "cancelled": cancelled,
        "has_exam": has_exam,
        "has_quiz": has_quiz,
        "note": note,
    }.items():
        if value is not None:
            setattr(cs, field, value)

    db.add(cs)
    db.commit()
    db.refresh(cs)
    return cs
