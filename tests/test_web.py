"""Testes do site com o banco de teste (conftest.py)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from sqlmodel import select

from app.models import Assessment, Course, CourseStatus
from app.services.attendance import get_class_session
from app.web.main import create_app

TODAY = date(2026, 10, 13)  # terça


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine=engine, today_fn=lambda: TODAY))


def test_week_page_shows_calendar(client):
    html = client.get("/").text
    assert "Última alteração" not in html
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
    assert 'hx-swap-oob="true"' in r.text  # o bloco da grade atualiza junto com o painel
    assert 'class="block absent' in r.text
    assert get_class_session(db, 3, TODAY).attended is False


def test_site_changes_are_logged_and_undoable(client, db):
    client.post("/aulas/3/2026-10-13/presenca?valor=0")
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


# ---------------------------------------------------------------- provas

def test_exams_page_lists_upcoming(client):
    html = client.get("/provas").text
    assert "Próximas" in html and "P1" in html and "Aprendizagem Profunda" in html
    assert "em 9 dias" in html  # 22/10, vista em 13/10


def test_create_exam_with_next_free_name(client, db):
    r = client.post("/provas", data={"disciplina": 3, "dia": "2026-10-29"}, follow_redirects=False)
    assert r.status_code == 303 and "aviso" not in r.headers["location"]
    a = db.exec(select(Assessment).where(Assessment.course_id == 3, Assessment.name == "P2")).one()
    assert a.day == date(2026, 10, 29)


def test_exam_on_day_without_class_saves_with_warning(client):
    r = client.post("/provas", data={"disciplina": 3, "dia": "2026-10-26"})  # segunda; AP é ter/qui
    assert "Salvo, mas confira" in r.text and "segunda" in r.text


def test_edit_exam_date_and_grade_in_one_undo(client, db):
    p1 = db.exec(select(Assessment).where(Assessment.name == "P1")).one()
    client.post(f"/provas/{p1.id}", data={"dia": "2026-10-13", "nota": "8,5"})  # hoje
    db.expire_all()
    assert (p1.day, p1.grade) == (date(2026, 10, 13), 8.5)
    client.post("/desfazer")
    db.expire_all()
    assert (p1.day, p1.grade) == (date(2026, 10, 22), None)  # um "desfazer" reverte as duas


def test_future_exam_has_no_grade_field(client, db):
    p1 = db.exec(select(Assessment).where(Assessment.name == "P1")).one()  # 22/10, futura
    html = client.get(f"/provas/{p1.id}").text
    assert 'name="nota"' not in html and "a partir do dia da prova" in html
    r = client.post(f"/provas/{p1.id}", data={"dia": "2026-10-22", "nota": "9"})
    assert "a partir do dia da prova" in r.text
    db.expire_all()
    assert p1.grade is None


def test_invalid_grade_is_rejected(client, db):
    p1 = db.exec(select(Assessment).where(Assessment.name == "P1")).one()
    r = client.post(f"/provas/{p1.id}", data={"dia": "2026-10-12", "nota": "oito"})
    assert "não é uma nota" in r.text
    r = client.post(f"/provas/{p1.id}", data={"dia": "2026-10-12", "nota": "11"})
    assert "Nota inválida" in r.text
    db.expire_all()
    assert p1.grade is None


def test_delete_exam_can_be_undone(client, db):
    p1_id = db.exec(select(Assessment).where(Assessment.name == "P1")).one().id
    client.post(f"/provas/{p1_id}/excluir")
    assert db.get(Assessment, p1_id) is None
    client.post("/desfazer")
    db.expire_all()
    assert db.get(Assessment, p1_id).day == date(2026, 10, 22)


# ---------------------------------------------------------------- histórico

def test_history_shows_cr_and_terms(client):
    html = client.get("/historico").text
    assert "10,0000" in html  # só Estatística (SI) entra; Cálculo II (EP) fica fora
    assert "fora do CR (EP)" in html
    assert "6º período" in html and "atual" in html


def test_simulation_does_not_save(client, db):
    html = client.post("/historico/simular", data={"nota_1": "7", "nota_3": "8,5"}).text
    assert "CR acumulado" in html
    assert "8,5000" in html  # (10*4 + 7*4 + 8,5*4) / 12
    assert "Empreendedorismo" in html  # avisa a disciplina que ficou fora da conta
    assert db.get(Course, 1).final_grade is None


def test_set_final_grade_and_drop_from_site(client, db):
    client.post("/disciplinas/1/media", data={"nota": "9,0"})
    db.expire_all()
    assert db.get(Course, 1).final_grade == 9.0
    client.post("/disciplinas/2/trancar")
    db.expire_all()
    assert db.get(Course, 2).status == CourseStatus.DROPPED
    client.post("/desfazer")
    db.expire_all()
    assert db.get(Course, 2).status == CourseStatus.IN_PROGRESS


# ---------------------------------------------------------------- senha

@pytest.fixture
def locked(engine):
    return TestClient(create_app(engine=engine, today_fn=lambda: TODAY, password="segredo"))


def test_password_required(locked):
    r = locked.get("/historico", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert locked.post("/disciplinas/1/media", data={"nota": "1"}, follow_redirects=False).status_code == 303
    assert locked.get("/static/style.css").status_code == 200


def test_wrong_password(locked):
    r = locked.post("/login", data={"senha": "errada", "prox": "/"}, follow_redirects=False)
    assert r.status_code == 401 and "sessao" not in r.cookies


def test_login_then_access(locked):
    r = locked.post("/login", data={"senha": "segredo", "prox": "/provas"}, follow_redirects=False)
    assert r.headers["location"] == "/provas"
    assert locked.get("/provas").status_code == 200
    locked.get("/sair")
    assert locked.get("/provas", follow_redirects=False).status_code == 303


def test_login_does_not_redirect_outside(locked):
    r = locked.post("/login", data={"senha": "segredo", "prox": "//evil.com"}, follow_redirects=False)
    assert r.headers["location"] == "/"


def test_blocks_colored_by_what_happened(client):
    client.post("/aulas/1/2026-10-12/cancelada")
    html = client.get("/").text
    assert 'class="block present' in html  # 13/10 (hoje), AP: presença
    assert 'class="block cancelled' in html and "Sem aula" in html
    assert 'class="block upcoming' in html  # 14/10 em diante


@pytest.mark.parametrize("url", ["/", "/provas", "/historico"])
def test_app_header_on_every_page(client, url):
    assert "Gerenciador Acadêmico" in client.get(url).text


def test_login_page_has_app_header(locked):
    assert "Gerenciador Acadêmico" in locked.get("/login").text


def test_save_shows_confirmation(client):
    r = client.post("/provas", data={"disciplina": 3, "dia": "2026-10-29"})
    assert 'class="toast"' in r.text and "P2 de AP salva" in r.text


def test_login_without_remember_is_session_cookie(locked):
    r = locked.post("/login", data={"senha": "segredo", "prox": "/"}, follow_redirects=False)
    assert "Max-Age" not in r.headers["set-cookie"]
    r = locked.post("/login", data={"senha": "segredo", "prox": "/", "lembrar": "1"}, follow_redirects=False)
    assert "Max-Age=7776000" in r.headers["set-cookie"]


def test_cookie_is_secure_behind_tailscale(locked):
    r = locked.post(
        "/login", data={"senha": "segredo", "prox": "/"},
        headers={"host": "academico.tail123.ts.net"}, follow_redirects=False,
    )
    assert "secure" in r.headers["set-cookie"].lower()


def test_too_many_wrong_passwords_block_login(engine, monkeypatch):
    import app.web.main as web

    async def no_wait(seconds):
        return None

    monkeypatch.setattr(web.asyncio, "sleep", no_wait)  # o teste não espera 1 s por tentativa
    c = TestClient(create_app(engine=engine, today_fn=lambda: TODAY, password="segredo"))
    for _ in range(5):
        assert c.post("/login", data={"senha": "errada"}).status_code == 401
    r = c.post("/login", data={"senha": "segredo"}, follow_redirects=False)
    assert r.status_code == 429 and "Muitas tentativas" in r.text  # bloqueado mesmo com a senha certa


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["x-frame-options"] == "DENY"
