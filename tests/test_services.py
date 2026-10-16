"""Testes das funções novas: desfazer, provas, disciplinas e simulação de CR.
Usam a fixture `db` de conftest.py."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlmodel import select

from app.models import ChangeLog, Course, CourseStatus
from app.services.assessments import (
    exam_days,
    get_assessment,
    schedule_assessment,
    set_assessment_grade,
    upcoming,
)
from app.services.attendance import (
    current_courses,
    get_class_session,
    sessions_on,
    summarize_all,
    update_class_session,
)
from app.services.changes import ChangeBatch, undo_last_batch
from app.services.courses import (
    drop_course,
    find_courses,
    set_final_grade,
    set_program,
    set_requires_attendance,
    undrop_course,
)
from app.services.grades import current_cr, simulate_cr
from tests.conftest import MONDAY

TUESDAY = MONDAY + timedelta(days=1)


# ---------- log e desfazer ----------


def test_changes_are_logged(db):
    update_class_session(db, 3, TUESDAY, attended=False)
    log = db.exec(select(ChangeLog)).all()
    assert len(log) == 1
    assert "falta" in log[0].description


def test_undo_reverts_whole_batch(db):
    batch = ChangeBatch(source="agente")  # uma mensagem com duas ações
    update_class_session(db, 1, MONDAY, attended=False, batch=batch)
    update_class_session(db, 2, MONDAY, attended=False, batch=batch)

    undone = undo_last_batch(db)

    assert len(undone) == 2
    assert all(s.attended for s in sessions_on(db, MONDAY))


def test_undo_only_last_batch(db):
    update_class_session(db, 1, MONDAY, attended=False)  # lote 1
    update_class_session(db, 3, TUESDAY, attended=False)  # lote 2
    undo_last_batch(db)
    assert get_class_session(db, 1, MONDAY).attended is False  # lote 1 continua
    assert get_class_session(db, 3, TUESDAY).attended is True


def test_undo_twice_goes_further_back(db):
    update_class_session(db, 1, MONDAY, attended=False)
    update_class_session(db, 3, TUESDAY, attended=False)
    undo_last_batch(db)
    undo_last_batch(db)
    assert get_class_session(db, 1, MONDAY).attended is True


def test_undo_with_nothing_to_undo(db):
    assert undo_last_batch(db) == []


def test_undo_creation_deletes_record(db):
    schedule_assessment(db, 1, "P1", date(2026, 10, 21))
    undo_last_batch(db)
    assert get_assessment(db, 1, "P1") is None


def test_undo_restores_dates(db):
    schedule_assessment(db, 3, "P1", date(2026, 10, 20))  # move de 22/10 para 20/10
    undo_last_batch(db)
    assert get_assessment(db, 3, "p1").day == date(2026, 10, 22)


# ---------- provas ----------


def test_schedule_new_assessment_on_class_day(db):
    result = schedule_assessment(db, 1, "p2", date(2026, 10, 21))  # quarta, dia de ACD
    assert result.changed
    assert result.assessment.name == "P2"
    assert result.warnings == []


def test_schedule_assessment_warns_on_weekend(db):
    result = schedule_assessment(db, 1, "P1", date(2026, 11, 15))  # domingo
    assert "domingo" in result.warnings[0]
    assert result.assessment.day == date(2026, 11, 15)  # aviso não bloqueia


def test_schedule_assessment_warns_outside_course_days(db):
    result = schedule_assessment(db, 3, "P2", date(2026, 10, 21))  # quarta; AP é terça/quinta
    assert "terça, quinta" in result.warnings[0]


def test_exam_days_come_from_assessments(db):
    assert exam_days(db, 3) == {date(2026, 10, 22)}
    schedule_assessment(db, 3, "P1", date(2026, 10, 20))
    assert exam_days(db, 3) == {date(2026, 10, 20)}  # mudou num lugar só


def test_set_assessment_grade_creates_if_missing(db):
    a = set_assessment_grade(db, 2, "P1", 9.3)
    assert a.grade == 9.3 and a.day is None


def test_set_assessment_grade_rejects_invalid(db):
    with pytest.raises(ValueError):
        set_assessment_grade(db, 2, "P1", 11)


def test_upcoming_ignores_past_and_dropped(db):
    assert [a.name for a in upcoming(db, date(2026, 10, 15))] == ["P1"]
    assert upcoming(db, date(2026, 10, 23)) == []
    drop_course(db, 3)
    assert upcoming(db, date(2026, 10, 15)) == []


# ---------- disciplinas ----------


@pytest.mark.parametrize(
    "query, expected",
    [
        ("ACD", ["ACD"]),
        ("acd", ["ACD"]),
        ("aprendizagem profunda", ["AP"]),
        ("ciencia de dados", ["ACD"]),  # sem acento, parte do nome
        ("aprendizagem", ["AP"]),
        ("TPS", []),
    ],
)
def test_find_courses(db, query, expected):
    assert [c.code for c in find_courses(db, query)] == expected


def test_drop_course_removes_from_everything(db):
    drop_course(db, 3)
    assert "AP" not in [c.code for c in current_courses(db)]
    assert "AP" not in [s.course_name for s in summarize_all(db, TUESDAY)]
    assert sessions_on(db, TUESDAY) == []
    with pytest.raises(ValueError):
        update_class_session(db, 3, TUESDAY, attended=False)


def test_dropped_course_leaves_cr(db):
    set_final_grade(db, 1, 5.0)
    assert current_cr(db) == Decimal("7.5000")  # (10*4 + 5*4) / 8
    drop_course(db, 1)
    assert current_cr(db) == Decimal("10.0000")


def test_undrop_course(db):
    drop_course(db, 3)
    undrop_course(db, 3)
    assert db.get(Course, 3).status == CourseStatus.IN_PROGRESS


def test_set_requires_attendance(db):
    set_requires_attendance(db, 3, False)
    assert db.get(Course, 3).requires_attendance is False


def test_set_program_removes_from_cr(db):
    set_final_grade(db, 1, 5.0)
    set_program(db, 1, "ep")
    assert db.get(Course, 1).program == "EP"
    assert current_cr(db) == Decimal("10.0000")


def test_final_grade_sets_status(db):
    set_final_grade(db, 1, 9.2)
    assert db.get(Course, 1).status == CourseStatus.PASSED
    set_final_grade(db, 1, 6.9)
    assert db.get(Course, 1).status == CourseStatus.FAILED
    set_final_grade(db, 1, None)
    assert db.get(Course, 1).status == CourseStatus.IN_PROGRESS


def test_final_grade_fails_by_absence(db):
    # AP tem 4 aulas no fixture => limite de 1 falta; 2 faltas reprova
    update_class_session(db, 3, TUESDAY, attended=False)
    update_class_session(db, 3, TUESDAY + timedelta(days=2), attended=False)
    set_final_grade(db, 3, 9.0, today=date(2026, 10, 31))
    assert db.get(Course, 3).status == CourseStatus.FAILED


def test_final_grade_on_dropped_course_is_rejected(db):
    drop_course(db, 3)
    with pytest.raises(ValueError, match="trancada"):
        set_final_grade(db, 3, 9.0)


# ---------- simulação de CR ----------


def test_simulate_cr_total_with_all_grades(db):
    sim = simulate_cr(db, {1: 10, 2: 8, 3: 9})
    # (10*4 histórico + 10*4 + 8*4 + 9*4) / 16 = 9.25; Cálculo II (EP) fora
    assert sim.cr == Decimal("9.2500")
    assert sim.missing == []


def test_simulate_cr_term_scope(db):
    sim = simulate_cr(db, {1: 10, 2: 8, 3: 9}, scope="periodo")
    assert sim.cr == Decimal("9.00")


def test_simulate_cr_reports_missing_courses(db):
    sim = simulate_cr(db, {1: 10}, scope="periodo")
    assert sim.cr == Decimal("10.00")
    assert sim.missing == ["Aprendizagem Profunda", "Empreendedorismo e Inovação"]


def test_simulate_cr_does_not_save(db):
    simulate_cr(db, {1: 0})
    assert db.get(Course, 1).final_grade is None
