"""Disciplinas: busca, situação (trancar), regras de frequência, curso e média final."""

import unicodedata
from typing import Optional

from sqlmodel import Session, select

from app.models import Course, CourseStatus
from app.services.attendance import current_courses, current_term, summarize_course
from app.services.changes import ChangeBatch, update_fields
from app.services.grades import APPROVAL_GRADE, validate_grade


def _plain(text: str) -> str:
    """'Ciência de Dados' -> 'ciencia de dados' (sem acento e minúsculo)."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold().strip()


def find_courses(db: Session, query: str, only_current: bool = True) -> list[Course]:
    """Procura disciplinas pela sigla ou pelo nome (ignora acentos e maiúsculas).

    Ordem: sigla exata > nome exato > nome que contém o texto.
    Mais de um resultado = ambiguidade; quem chama deve perguntar ao usuário.
    """
    q = _plain(query)
    if not q:
        return []
    if only_current:
        pool = current_courses(db)
    else:
        pool = list(db.exec(select(Course)).all())

    by_code = [c for c in pool if c.code and _plain(c.code) == q]
    if by_code:
        return by_code
    by_name = [c for c in pool if _plain(c.name) == q]
    if by_name:
        return by_name
    return [c for c in pool if q in _plain(c.name)]


def _get(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError(f"Disciplina {course_id} não encontrada.")
    return course


def drop_course(db: Session, course_id: int, batch: Optional[ChangeBatch] = None) -> bool:
    """Tranca a disciplina: sai do CR, da frequência e da grade (reversível)."""
    course = _get(db, course_id)
    return update_fields(
        db, course, {"status": CourseStatus.DROPPED}, batch, f"{course.name} trancada"
    )


def undrop_course(db: Session, course_id: int, batch: Optional[ChangeBatch] = None) -> bool:
    course = _get(db, course_id)
    if course.status != CourseStatus.DROPPED:
        return False
    return update_fields(
        db,
        course,
        {"status": CourseStatus.IN_PROGRESS},
        batch,
        f"{course.name} destrancada",
    )


def set_requires_attendance(
    db: Session, course_id: int, value: bool, batch: Optional[ChangeBatch] = None
) -> bool:
    course = _get(db, course_id)
    text = "passa a cobrar" if value else "deixa de cobrar"
    return update_fields(
        db,
        course,
        {"requires_attendance": value},
        batch,
        f"{course.name} {text} frequência mínima",
    )


def set_program(
    db: Session, course_id: int, program: str, batch: Optional[ChangeBatch] = None
) -> bool:
    """Define em qual curso a disciplina foi cursada (só o curso da casa entra no CR)."""
    course = _get(db, course_id)
    program = program.strip().upper()
    return update_fields(
        db, course, {"program": program}, batch, f"{course.name} marcada como cursada em {program}"
    )


def set_final_grade(
    db: Session,
    course_id: int,
    grade: Optional[float],
    today=None,
    batch: Optional[ChangeBatch] = None,
) -> bool:
    """Lança (ou apaga, com None) a média final e atualiza a situação da disciplina.

    Aprovada: média >= 7 e, se a disciplina cobra frequência, faltas dentro do limite.
    """
    course = _get(db, course_id)
    if course.status == CourseStatus.DROPPED:
        raise ValueError(f"{course.name} está trancada. Destranque antes de lançar a média.")
    if grade is None:
        status = CourseStatus.IN_PROGRESS
        description = f"Média final de {course.name} apagada"
    else:
        validate_grade(grade)
        attendance_ok = True
        if course.requires_attendance and course.sessions and today is not None:
            attendance_ok = summarize_course(db, course, today).remaining_absences >= 0
        approved = grade >= APPROVAL_GRADE and attendance_ok
        status = CourseStatus.PASSED if approved else CourseStatus.FAILED
        description = f"Média final {grade:g} em {course.name}"
    return update_fields(
        db, course, {"final_grade": grade, "status": status}, batch, description
    )


__all__ = [
    "current_courses",
    "current_term",
    "drop_course",
    "find_courses",
    "set_final_grade",
    "set_program",
    "set_requires_attendance",
    "undrop_course",
]
