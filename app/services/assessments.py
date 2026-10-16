"""Provas e outras avaliações.

A tabela Assessment é a fonte única da data da prova. A tela de faltas
descobre se um dia tem prova consultando esta tabela.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlmodel import Session, select

from app.models import Assessment, Course, CourseStatus, ScheduleSlot
from app.services.attendance import WEEKDAY_NAMES
from app.services.changes import ChangeBatch, create, update_fields
from app.services.grades import validate_grade


@dataclass
class ScheduleResult:
    assessment: Assessment
    changed: bool
    warnings: list[str] = field(default_factory=list)


def normalize_name(name: str) -> str:
    """'p1' -> 'P1'; 'prova final' -> 'Prova final'"""
    name = name.strip()
    if len(name) <= 3:
        return name.upper()
    return name[0].upper() + name[1:]


def get_assessment(db: Session, course_id: int, name: str) -> Optional[Assessment]:
    return db.exec(
        select(Assessment).where(
            Assessment.course_id == course_id, Assessment.name == normalize_name(name)
        )
    ).first()


def exam_days(db: Session, course_id: int) -> set[date]:
    rows = db.exec(select(Assessment.day).where(Assessment.course_id == course_id)).all()
    return {d for d in rows if d is not None}


def upcoming(db: Session, today: date) -> list[Assessment]:
    """Avaliações a partir de hoje, das disciplinas não trancadas, por data."""
    rows = db.exec(
        select(Assessment)
        .join(Course)
        .where(Assessment.day >= today, Course.status != CourseStatus.DROPPED)
    ).all()
    return sorted(rows, key=lambda a: a.day)


def date_warnings(db: Session, course: Course, day: date) -> list[str]:
    """Avisos (não bloqueiam): prova em fim de semana ou fora do dia da disciplina."""
    weekday = day.weekday()
    if weekday >= 5:
        return [f"{day:%d/%m/%Y} é {WEEKDAY_NAMES[weekday]}."]
    class_days = set(
        db.exec(select(ScheduleSlot.weekday).where(ScheduleSlot.course_id == course.id)).all()
    )
    if class_days and weekday not in class_days:
        dias = ", ".join(WEEKDAY_NAMES[d] for d in sorted(class_days))
        return [
            f"{day:%d/%m/%Y} é {WEEKDAY_NAMES[weekday]}, mas {course.name} tem aula às {dias}."
        ]
    return []


def schedule_assessment(
    db: Session, course_id: int, name: str, day: date, batch: Optional[ChangeBatch] = None
) -> ScheduleResult:
    """Cria a avaliação ou muda a data dela. Devolve avisos sobre a data."""
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError(f"Disciplina {course_id} não encontrada.")
    name = normalize_name(name)
    warnings = date_warnings(db, course, day)
    existing = get_assessment(db, course_id, name)
    if existing is None:
        a = create(
            db,
            Assessment(course_id=course_id, name=name, day=day),
            batch,
            f"{name} de {course.name} marcada para {day:%d/%m}",
        )
        return ScheduleResult(a, True, warnings)
    changed = update_fields(
        db, existing, {"day": day}, batch, f"{name} de {course.name} movida para {day:%d/%m}"
    )
    return ScheduleResult(existing, changed, warnings)


def set_assessment_grade(
    db: Session, course_id: int, name: str, grade: float, batch: Optional[ChangeBatch] = None
) -> Assessment:
    """Lança a nota de uma avaliação (cria a avaliação, sem data, se não existir)."""
    validate_grade(grade)
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError(f"Disciplina {course_id} não encontrada.")
    name = normalize_name(name)
    description = f"Nota {grade:g} na {name} de {course.name}"
    existing = get_assessment(db, course_id, name)
    if existing is None:
        return create(db, Assessment(course_id=course_id, name=name, grade=grade), batch, description)
    update_fields(db, existing, {"grade": grade}, batch, description)
    return existing
