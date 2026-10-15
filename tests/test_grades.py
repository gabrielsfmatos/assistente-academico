from decimal import Decimal

import pytest

from app.models import Course
from app.services.grades import compute_cr, cr_by_term, is_approved, truncate, validate_grade


def course(id, grade, credits, term=1, program="SI"):
    return Course(id=id, name=f"D{id}", term=term, credits=credits, final_grade=grade, program=program)


def test_truncate_rounds_down():
    assert truncate(Decimal("9.42129"), 4) == Decimal("9.4212")
    assert truncate(Decimal("9.999"), 2) == Decimal("9.99")


def test_cr_is_weighted_by_credits():
    cr = compute_cr([course(1, 10, 4), course(2, 7, 2)])
    assert cr == Decimal("9.0000")  # (40 + 14) / 6


def test_cr_ignores_courses_from_other_program():
    # Ex.: Cálculo II cursada em Engenharia de Produção
    cr = compute_cr([course(1, 9, 4), course(2, 0, 4, program="EP")])
    assert cr == Decimal("9.0000")


def test_cr_ignores_courses_without_final_grade():
    assert compute_cr([course(1, 8, 4), course(2, None, 4)]) == Decimal("8.0000")


def test_cr_avoids_float_errors():
    # 9.4 em float é 9.39999...; com Decimal o resultado fica exato
    assert compute_cr([course(1, 9.4, 4)]) == Decimal("9.4000")


def test_cr_simulation_with_overrides():
    courses = [course(1, 10, 4), course(2, None, 4, term=2)]
    assert compute_cr(courses, overrides={2: 8}) == Decimal("9.0000")


def test_cr_without_grades_is_none():
    assert compute_cr([course(1, None, 4)]) is None


def test_cr_by_term_uses_two_places():
    terms = cr_by_term([course(1, 10, 3, term=1), course(2, 9.4, 4, term=1), course(3, 8, 4, term=2)])
    assert terms == {1: Decimal("9.65"), 2: Decimal("8.00")}


@pytest.mark.parametrize("grade", [-1, 10.5])
def test_invalid_grade(grade):
    with pytest.raises(ValueError):
        validate_grade(grade)


def test_approval():
    assert is_approved(7.0) is True
    assert is_approved(6.9) is False
    assert is_approved(9.0, attendance_ok=False) is False
    assert is_approved(None) is None
