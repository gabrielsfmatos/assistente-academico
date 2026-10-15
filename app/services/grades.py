"""Regras de notas e CR.

Regras (definidas por Gabriel / normas da UNIRIO):
- A média final de cada disciplina é digitada manualmente (o critério
  de cálculo varia por disciplina, então o sistema não tenta calcular).
- Aprovação: média >= 7 e, se a disciplina cobra frequência, >= 75%.
- CR = média das notas ponderada pelos créditos, só com disciplinas
  cursadas no curso da casa (HOME_PROGRAM). Ex.: Cálculo II, cursada em
  Engenharia de Produção, não entra.
- Truncamento (igual à planilha): CR acumulado com 4 casas, CR do
  período com 2 casas, sempre arredondando para baixo.
"""

from collections import defaultdict
from decimal import ROUND_DOWN, Decimal
from typing import Iterable, Mapping, Optional

from sqlmodel import Session, select

from app.models import HOME_PROGRAM, Course

APPROVAL_GRADE = 7.0
CR_PLACES = 4
TERM_CR_PLACES = 2


def truncate(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def weighted_average(
    courses: Iterable[Course],
    places: int,
    overrides: Optional[Mapping[int, float]] = None,
) -> Optional[Decimal]:
    """Média ponderada por créditos, ignorando disciplinas sem nota e de outro curso.

    `overrides` permite simular notas: {course_id: nota_hipotetica}.
    """
    overrides = overrides or {}
    total_points = Decimal(0)
    total_credits = Decimal(0)
    for c in courses:
        if c.program != HOME_PROGRAM:
            continue
        grade = overrides.get(c.id, c.final_grade) if c.id is not None else c.final_grade
        if grade is None:
            continue
        # Decimal(str(...)) evita erros de float como 9.4 virar 9.39999...
        credits = Decimal(str(c.credits))
        total_points += Decimal(str(grade)) * credits
        total_credits += credits
    if total_credits == 0:
        return None
    return truncate(total_points / total_credits, places)


def compute_cr(courses: Iterable[Course], overrides: Optional[Mapping[int, float]] = None):
    return weighted_average(courses, CR_PLACES, overrides)


def cr_by_term(courses: Iterable[Course]) -> dict[int, Optional[Decimal]]:
    by_term: dict[int, list[Course]] = defaultdict(list)
    for c in courses:
        by_term[c.term].append(c)
    return {t: weighted_average(cs, TERM_CR_PLACES) for t, cs in sorted(by_term.items())}


def validate_grade(grade: float) -> None:
    if not 0 <= grade <= 10:
        raise ValueError(f"Nota inválida: {grade}. Use um valor entre 0 e 10.")


def is_approved(final_grade: Optional[float], attendance_ok: bool = True) -> Optional[bool]:
    """None enquanto a média final não foi lançada."""
    if final_grade is None:
        return None
    return final_grade >= APPROVAL_GRADE and attendance_ok


# ---------- Funções que acessam o banco ----------


def current_cr(db: Session) -> Optional[Decimal]:
    return compute_cr(db.exec(select(Course)).all())


def simulate_cr(db: Session, hypothetical: Mapping[int, float]) -> Optional[Decimal]:
    """CR se as disciplinas em `hypothetical` fechassem com essas notas."""
    for grade in hypothetical.values():
        validate_grade(grade)
    return compute_cr(db.exec(select(Course)).all(), overrides=hypothetical)


def set_final_grade(db: Session, course_id: int, grade: Optional[float]) -> Course:
    if grade is not None:
        validate_grade(grade)
    course = db.get(Course, course_id)
    if course is None:
        raise ValueError(f"Disciplina {course_id} não encontrada.")
    course.final_grade = grade
    db.add(course)
    db.commit()
    db.refresh(course)
    return course
