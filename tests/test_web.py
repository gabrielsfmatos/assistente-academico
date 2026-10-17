"""Testes do site com o banco de teste (conftest.py)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.services.attendance import get_class_session
from app.web.main import create_app

TODAY = date(2026, 10, 13)  # terça


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine=engine, today_fn=lambda: TODAY))


def test_week_page_shows_calendar(client):
    html = client.get("/").text
    assert "Outubro" in html
    assert "block-1-2026-10-12" in html and "block-3-2026-10-13" in html
    assert 'class="dayhead is-today"' in html


def test_exam_is_shown_in_block(client):
    html = client.get("/?semana=2026-10-19").text
    assert 'class="b-exam">P1' in html  # P1 de AP em 22/10


def test_old_url_redirects(client):
    assert client.get("/faltas", follow_redirects=False).status_code == 307


def test_sheet_shows_course_details(client):
    html = client.get("/aulas/3/2026-10-13").text
    assert "Aprendizagem Profunda" in html
    assert "faltas permitidas" in html
    assert "P1" in html  # próxima prova


def test_sheet_for_course_without_attendance_rule(client):
    html = client.get("/aulas/2/2026-10-12").text
    assert "não cobra frequência" in html


def test_mark_absence_from_sheet(client, db):
    r = client.post("/aulas/3/2026-10-13/presenca?valor=0")
    assert r.status_code == 200
    assert 'hx-swap-oob="true"' in r.text  # bloco da grade e última alteração atualizam juntos
    assert get_class_session(db, 3, TODAY).attended is False


def test_site_changes_are_logged_and_undoable(client, db):
    client.post("/aulas/3/2026-10-13/presenca?valor=0")
    assert "pelo site" in client.get("/").text
    client.post("/desfazer", follow_redirects=False)
    db.expire_all()
    assert get_class_session(db, 3, TODAY).attended is True


def test_day_without_class_is_rejected(client):
    assert client.get("/aulas/3/2026-10-12").status_code == 404
    assert client.post("/aulas/3/2026-10-12/presenca").status_code == 404


def test_cancel_class(client, db):
    client.post("/aulas/1/2026-10-12/cancelada")
    db.expire_all()
    assert get_class_session(db, 1, date(2026, 10, 12)).cancelled is True
