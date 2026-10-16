"""Regras de notas e CR.

Regras (definidas por Gabriel / normas da UNIRIO):
- A média final de cada disciplina é digitada manualmente (o critério
  de cálculo varia por disciplina, então o sistema não tenta calcular).
- Aprovação: média >= 7 e, se a disciplina cobra frequência, >= 75%.
- CR = média das notas ponderada pelos créditos, só com disciplinas
  cursadas no curso da casa (HOME_PROGRAM). Ex.: Cálculo II, cursada em
  Engenharia de Produção, não entra. Disciplinas trancadas também não.
- Truncamento (igual à planilha): CR acumulado com 4 casas, CR do
  período com 2 casas, sempre arredondando para baixo.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from typing import Iterable, Mapping, Optional

from sqlmodel import Session, select

from app.models import HOME_PROGRAM, Course, CourseStatus

APPROVAL_GRADE = 7.0
CR_PLACES = 4
TERM_CR_PLACES = 2


def truncate(value: Decimal, places: int) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_DOWN)


def counts_for_cr(course: Course) -> bool:
    return course.program == HOME_PROGRAM and course.status != CourseStatus.DROPPED


def weighted_average(
    courses: Iterable[Course],
    places: int,
    overrides: Optional[Mapping[int, float]] = None,
) -> Optional[Decimal]:
    """Média ponderada por créditos, ignorando disciplinas sem nota, de outro
    curso ou trancadas. `overrides` permite simular notas: {course_id: nota}."""
    overrides = overrides or {}
    total_points = Decimal(0)
    total_credits = Decimal(0)
    for c in courses:
        if not counts_for_cr(c):
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


@dataclass
class CRSimulation:
    scope: str  # "acumulado" | "periodo"
    cr: Optional[Decimal]
    missing: list[str] = field(default_factory=list)  # disciplinas do período sem nota


def current_cr(db: Session) -> Optional[Decimal]:
    return compute_cr(db.exec(select(Course)).all())


def simulate_cr(
    db: Session, hypothetical: Mapping[int, float], scope: str = "acumulado"
) -> CRSimulation:
    """CR se as disciplinas em `hypothetical` fechassem com essas notas.

    Se alguma disciplina do período atual ficou sem nota (nem lançada nem
    simulada), o cálculo segue sem ela e a lista `missing` avisa quais foram.
    """
    if scope not in {"acumulado", "periodo"}:
        raise ValueError("scope deve ser 'acumulado' ou 'periodo'.")
    for grade in hypothetical.values():
        validate_grade(grade)

    courses = db.exec(select(Course)).all()
    term = max((c.term for c in courses), default=None)
    current = [c for c in courses if c.term == term and counts_for_cr(c)]
    missing = [c.name for c in current if c.final_grade is None and c.id not in hypothetical]

    if scope == "periodo":
        cr = weighted_average(current, TERM_CR_PLACES, hypothetical)
    else:
        cr = compute_cr(courses, overrides=hypothetical)
    return CRSimulation(scope=scope, cr=cr, missing=sorted(missing))
