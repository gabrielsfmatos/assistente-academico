"""Site: edição direta dos dados acadêmicos.

Usa exatamente a mesma camada de serviços do agente. Toda alteração feita
aqui entra no mesmo log (origem "site") e pode ser desfeita.

Rodar (na raiz do projeto):
    python -m uvicorn app.web.main:app --reload
e abrir http://127.0.0.1:8000
"""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models import Assessment, ChangeLog, ClassSession, ScheduleSlot
from app.services import attendance as attendance_svc
from app.services.changes import ChangeBatch, undo_last_batch

WEB_DIR = Path(__file__).parent
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]
SHORT_DAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
LONG_DAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
# Uma cor por disciplina (na ordem das siglas), distintas entre si e legíveis.
COURSE_COLORS = ["#3B6FE0", "#8A4FE8", "#0E9F8E", "#E0712B", "#D9436F", "#4C8A2E", "#B7791F"]

templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.globals.update(MONTHS=MONTHS, SHORT_DAYS=SHORT_DAYS, LONG_DAYS=LONG_DAYS)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def create_app(engine=None, today_fn=date.today) -> FastAPI:
    engine = engine or get_engine()
    init_db(engine)
    app = FastAPI(title="Assistente Acadêmico")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    def get_db():
        with Session(engine) as db:
            yield db

    # ------------------------------------------------------------ apoio

    def colors(db: Session) -> dict[int, str]:
        courses = sorted(attendance_svc.current_courses(db), key=lambda c: c.code or c.name)
        return {c.id: COURSE_COLORS[i % len(COURSE_COLORS)] for i, c in enumerate(courses)}

    def last_change(db: Session) -> Optional[ChangeLog]:
        return db.exec(
            select(ChangeLog).where(ChangeLog.undone == False).order_by(ChangeLog.id.desc())  # noqa: E712
        ).first()

    def time_rows(db: Session) -> list[tuple[str, str]]:
        """Faixas de horário da grade (ex.: 16:00–18:00), a partir dos horários cadastrados."""
        ids = [c.id for c in attendance_svc.current_courses(db)]
        slots = db.exec(select(ScheduleSlot).where(ScheduleSlot.course_id.in_(ids))).all()
        return sorted({(s.start_time, s.end_time) for s in slots})

    def block_view(cs: ClassSession, palette: dict[int, str]) -> dict:
        slot = next((s for s in cs.course.schedule if s.weekday == cs.day.weekday()), None)
        exam = next((a for a in cs.course.assessments if a.day == cs.day), None)
        return {
            "course_id": cs.course_id,
            "code": cs.course.code or cs.course.name[:3].upper(),
            "name": cs.course.name,
            "start": slot.start_time if slot else "",
            "end": slot.end_time if slot else "",
            "day": cs.day,
            "attended": cs.attended,
            "cancelled": cs.cancelled,
            "quiz": cs.has_quiz,
            "exam": exam.name if exam else None,
            "past": cs.day <= today_fn(),
            "color": palette.get(cs.course_id, COURSE_COLORS[0]),
        }

    def sheet_context(db: Session, course_id: int, day: date) -> dict:
        cs = attendance_svc.get_class_session(db, course_id, day)
        db.refresh(cs)
        course = cs.course
        upcoming = db.exec(
            select(Assessment)
            .where(Assessment.course_id == course_id, Assessment.day >= today_fn())
            .order_by(Assessment.day)
        ).all()
        return {
            "b": block_view(cs, colors(db)),
            "course": course,
            "summary": attendance_svc.summarize_course(db, course, today_fn()),
            "upcoming": upcoming,
            "last_change": last_change(db),
        }

    # ------------------------------------------------------------ páginas

    @app.get("/", response_class=HTMLResponse)
    def week_page(request: Request, semana: Optional[date] = None, db: Session = Depends(get_db)):
        today = today_fn()
        start = monday_of(semana or today)
        days = [start + timedelta(days=i) for i in range(5)]
        palette = colors(db)
        grid: dict[tuple[date, str], list[dict]] = {}
        for cs in attendance_svc.sessions_between(db, days[0], days[-1]):
            b = block_view(cs, palette)
            grid.setdefault((cs.day, b["start"]), []).append(b)
        return templates.TemplateResponse(
            request,
            "semana.html",
            {
                "tab": "semana",
                "today": today,
                "days": days,
                "rows": time_rows(db),
                "grid": grid,
                "prev_week": start - timedelta(days=7),
                "next_week": start + timedelta(days=7),
                "is_current_week": start == monday_of(today),
                "last_change": last_change(db),
            },
        )

    @app.get("/faltas")
    def old_attendance_url():
        return RedirectResponse("/", status_code=307)

    @app.get("/aulas/{course_id}/{day}", response_class=HTMLResponse)
    def class_sheet(request: Request, course_id: int, day: date, db: Session = Depends(get_db)):
        try:
            ctx = sheet_context(db, course_id, day)
        except attendance_svc.NoClassError as exc:
            return HTMLResponse(str(exc), status_code=404)
        return templates.TemplateResponse(request, "_sheet.html", ctx)

    # ------------------------------------------------------------ ações (HTMX)

    @app.post("/aulas/{course_id}/{day}/{field}", response_class=HTMLResponse)
    def update_class(
        request: Request,
        course_id: int,
        day: date,
        field: str,
        valor: Optional[int] = None,
        db: Session = Depends(get_db),
    ) -> Response:
        try:
            cs = attendance_svc.get_class_session(db, course_id, day)
        except attendance_svc.NoClassError as exc:
            return HTMLResponse(str(exc), status_code=404)
        batch = ChangeBatch(source="site")
        if field == "presenca":
            attended = (not cs.attended) if valor is None else bool(valor)
            attendance_svc.update_class_session(db, course_id, day, attended=attended, batch=batch)
        elif field == "cancelada":
            attendance_svc.update_class_session(db, course_id, day, cancelled=not cs.cancelled, batch=batch)
        elif field == "teste":
            attendance_svc.update_class_session(db, course_id, day, has_quiz=not cs.has_quiz, batch=batch)
        else:
            return HTMLResponse("Campo desconhecido.", status_code=400)
        return templates.TemplateResponse(request, "_sheet_update.html", sheet_context(db, course_id, day))

    @app.post("/desfazer")
    def undo(request: Request, db: Session = Depends(get_db)):
        undo_last_batch(db)
        back = request.headers.get("referer") or "/"
        return RedirectResponse(back, status_code=303)

    return app


# Instância usada pelo uvicorn (banco real).
app = create_app()
