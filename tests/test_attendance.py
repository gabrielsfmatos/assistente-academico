from datetime import date, timedelta

import pytest

from app.models import ClassSession
from app.services.attendance import (
    NoClassError,
    cancel_day,
    compute_summary,
    get_class_session,
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


def test_absence_counts_once_per_class():
    # Regra nova: cada aula vale 1 (a planilha contava AP em dobro)
    sessions = make_sessions(4)
    sessions[1].attended = False
    assert compute_summary(sessions, TODAY).absences == 1


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


# ---------- testes com banco (fixture `db` em conftest.py) ----------

from tests.conftest import MONDAY  # noqa: E402

TUESDAY = MONDAY + timedelta(days=1)


def test_update_class_session_marks_absence(db):
    assert update_class_session(db, 3, TUESDAY, attended=False) is True
    cs = get_class_session(db, 3, TUESDAY)
    assert cs.attended is False
    assert cs.cancelled is False  # campos não informados não mudam


def test_registering_same_absence_twice_changes_nothing(db):
    update_class_session(db, 3, TUESDAY, attended=False)
    assert update_class_session(db, 3, TUESDAY, attended=False) is False


def test_update_class_session_rejects_day_without_class(db):
    with pytest.raises(NoClassError, match="segunda"):
        update_class_session(db, 3, MONDAY, attended=False)  # AP não tem aula na segunda


def test_sessions_on(db):
    assert [s.course.code for s in sessions_on(db, MONDAY)] == ["ACD", "EI"]
    assert sessions_on(db, MONDAY + timedelta(days=5)) == []  # sábado


def test_cancel_day(db):
    names = cancel_day(db, MONDAY)
    assert len(names) == 2
    assert all(s.cancelled for s in sessions_on(db, MONDAY))


def test_cancel_day_without_classes(db):
    with pytest.raises(NoClassError, match="sábado"):
        cancel_day(db, MONDAY + timedelta(days=5))
