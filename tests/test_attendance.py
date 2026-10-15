from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import ClassSession, Course
from app.services.attendance import (
    compute_summary,
    max_allowed_absences,
    sessions_on,
    update_class_session,
)

START = date(2026, 8, 17)
TODAY = date(2026, 10, 14)


def make_sessions(n: int) -> list[ClassSession]:
    """n aulas semanais a partir de START, todas presença por padrão."""
    return [ClassSession(course_id=1, day=START + timedelta(weeks=i)) for i in range(n)]


@pytest.mark.parametrize(
    "planned, expected",
    [(35, 8), (32, 8), (29, 7), (4, 1), (3, 0), (0, 0)],
)
def test_max_absences_rounds_down(planned, expected):
    # 35 aulas: 9 faltas daria 74,3% (< 75%), então o limite é 8
    assert max_allowed_absences(planned) == expected


def test_all_present():
    s = compute_summary(make_sessions(10), TODAY)
    assert s.absences == 0
    assert s.remaining_absences == 2  # floor(10 * 0.25)
    assert s.status == "atencao"  # restam só 2


def test_cancelled_class_is_removed_from_calculation():
    sessions = make_sessions(8)
    sessions[0].cancelled = True
    sessions[1].attended = False
    s = compute_summary(sessions, TODAY)
    assert s.planned_sessions == 7
    assert s.absences == 1
    assert s.projected_frequency == pytest.approx(6 / 7)


def test_cancelled_class_with_absence_flag_is_not_an_absence():
    sessions = make_sessions(4)
    sessions[0].cancelled = True
    sessions[0].attended = False
    assert compute_summary(sessions, TODAY).absences == 0


def test_exam_day_counts_as_presence_but_absence_on_exam_day_counts():
    sessions = make_sessions(4)
    sessions[0].has_exam = True  # presente na prova
    sessions[1].has_exam = True
    sessions[1].attended = False  # faltou no dia da prova
    s = compute_summary(sessions, TODAY)
    assert s.absences == 1


def test_frequency_to_date_ignores_future_classes():
    sessions = make_sessions(20)  # vai até dezembro
    sessions[0].attended = False
    s = compute_summary(sessions, TODAY)
    held = sum(1 for x in sessions if x.day <= TODAY)
    assert s.held_sessions == held
    assert s.frequency_to_date == pytest.approx((held - 1) / held)


def test_failed_by_absence():
    sessions = make_sessions(8)  # limite = 2
    for x in sessions[:3]:
        x.attended = False
    assert compute_summary(sessions, TODAY).status == "reprovado_por_falta"


def test_course_without_attendance_requirement():
    sessions = make_sessions(8)
    for x in sessions[:5]:
        x.attended = False
    s = compute_summary(sessions, TODAY, requires_attendance=False)
    assert s.status == "nao_cobra"


def test_no_classes_held_yet():
    s = compute_summary([ClassSession(course_id=1, day=date(2027, 3, 1))], TODAY)
    assert s.frequency_to_date is None


# ---------- testes com banco em memória ----------


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Course(id=1, name="Aprendizagem Profunda", code="AP", term=6, credits=4))
        session.add(ClassSession(course_id=1, day=TODAY))
        session.commit()
        yield session


def test_update_class_session_marks_absence(db):
    cs = update_class_session(db, 1, TODAY, attended=False)
    assert cs.attended is False
    assert cs.cancelled is False  # campos não informados não mudam


def test_update_class_session_rejects_day_without_class(db):
    with pytest.raises(ValueError):
        update_class_session(db, 1, TODAY + timedelta(days=1), attended=False)


def test_sessions_on(db):
    assert len(sessions_on(db, TODAY)) == 1
    assert sessions_on(db, TODAY + timedelta(days=1)) == []
