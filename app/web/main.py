"""Site: edição direta dos dados acadêmicos.

Usa exatamente a mesma camada de serviços do agente. Toda alteração feita
aqui entra no mesmo log (origem "site") e pode ser desfeita.

Abas: Semana (agenda), Provas e Histórico (períodos, notas e CR).

Rodar (na raiz do projeto):
    python -m uvicorn app.web.main:app --reload
e abrir http://127.0.0.1:8000
"""

import asyncio
import logging
import os
from datetime import date, timedelta
from decimal import Decimal
from itertools import groupby
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, urlsplit

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_engine, init_db
from app.models import Assessment, ClassSession, Course, CourseStatus, ScheduleSlot
from app.services import assessments as assessment_svc
from app.services import attendance as attendance_svc
from app.services import courses as course_svc
from app.services import grades as grades_svc
from app.services.changes import ChangeBatch, undo_last_batch
from app.web import auth

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent
MONTHS = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto",
          "setembro", "outubro", "novembro", "dezembro"]
SHORT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
SHORT_DAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
LONG_DAYS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
STATUS_LABELS = {
    CourseStatus.IN_PROGRESS: "cursando",
    CourseStatus.PASSED: "aprovada",
    CourseStatus.FAILED: "reprovada",
    CourseStatus.DROPPED: "trancada",
}
# Cor única das disciplinas (cabeçalho dos painéis e datas das provas). As aulas
# são coloridas pelo que aconteceu: presença, falta ou sem aula (ver style.css).
COURSE_COLOR = "#1D2A5B"


def br(value) -> str:
    """Números com vírgula: Decimal('9.4212') -> '9,4212'; 8.25 -> '8,25'; 10.0 -> '10'."""
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        text = str(value)
    else:
        text = f"{value:g}"
    return text.replace(".", ",")


def parse_grade(text: str) -> Optional[float]:
    """'9,5' ou '9.5' -> 9.5; vazio -> None (apagar). Erro se não for nota de 0 a 10."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        grade = float(text)
    except ValueError:
        raise ValueError(f"\"{text}\" não é uma nota. Use números, como 8,5.") from None
    grades_svc.validate_grade(grade)
    return grade


def relative_day(day: date, today: date) -> str:
    delta = (day - today).days
    if delta == 0:
        return "hoje"
    if delta == 1:
        return "amanhã"
    if delta == -1:
        return "ontem"
    return f"em {delta} dias" if delta > 0 else f"há {-delta} dias"


templates = Jinja2Templates(directory=WEB_DIR / "templates")
templates.env.globals.update(
    MONTHS=MONTHS, SHORT_MONTHS=SHORT_MONTHS, SHORT_DAYS=SHORT_DAYS, LONG_DAYS=LONG_DAYS,
    STATUS_LABELS=STATUS_LABELS,
)
templates.env.filters["br"] = br
# Versão dos arquivos de estilo/script no endereço (style.css?v=...): quando o arquivo muda,
# o endereço muda e o navegador baixa o novo, em vez de usar a cópia antiga guardada.
templates.env.globals["ASSET_V"] = str(
    max(int((WEB_DIR / "static" / f).stat().st_mtime) for f in ("style.css", "htmx.min.js"))
)


def week_monday(day: date) -> date:
    """Segunda-feira da semana de `day`, com a semana de domingo a sábado.

    Domingo já pertence à semana que começa nele, então no domingo o site mostra
    a semana seguinte (segunda a sexta); de segunda a sábado, a semana corrente.
    """
    sunday = day - timedelta(days=(day.weekday() + 1) % 7)
    return sunday + timedelta(days=1)


def back_to(
    path: str, aviso: Optional[str] = None, erro: Optional[str] = None, ok: Optional[str] = None
) -> RedirectResponse:
    """Volta para a página depois de um formulário, com uma mensagem opcional:
    ok = confirmação rápida ("Salvo"), aviso = salvo mas confira, erro = não salvou."""
    params = {k: v for k, v in {"ok": ok, "aviso": aviso, "erro": erro}.items() if v}
    return RedirectResponse(path + (f"?{urlencode(params)}" if params else ""), status_code=303)


def create_app(engine=None, today_fn=date.today, password: Optional[str] = None) -> FastAPI:
    """`password`: senha do site. None = site aberto (só para uso no próprio computador)."""
    engine = engine or get_engine()
    init_db(engine)
    app = FastAPI(title="Assistente Acadêmico")
    app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")

    if password is None:
        log.warning("SITE_PASSWORD não definida: o site está aberto, sem senha.")
    elif len(password) < auth.MIN_PASSWORD_LENGTH:
        log.warning("SITE_PASSWORD curta: use pelo menos %d caracteres.", auth.MIN_PASSWORD_LENGTH)
    limiter = auth.LoginLimiter()

    def get_db():
        with Session(engine) as db:
            yield db

    # ------------------------------------------------------------ senha

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")  # ninguém embute o site em outra página
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # Páginas sempre buscadas de novo no servidor: sem isso, o celular pode reabrir uma cópia
        # antiga (ex.: a semana de quando o atalho foi aberto pela última vez).
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.middleware("http")
    async def require_login(request: Request, call_next):
        if password is None or auth.is_public(request.url.path):
            return await call_next(request)
        if auth.is_logged_in(request.cookies.get(auth.COOKIE_NAME), password):
            return await call_next(request)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        login_url = "/login?" + urlencode({"prox": target})
        if request.headers.get("HX-Request"):  # pedido do HTMX: manda a página inteira para o login
            return Response(status_code=401, headers={"HX-Redirect": login_url})
        return RedirectResponse(login_url, status_code=303)

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, prox: str = "/"):
        if password is None:
            return RedirectResponse("/", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"prox": auth.safe_next(prox)})

    @app.post("/login")
    async def login(
        request: Request,
        senha: str = Form(""),
        prox: str = Form("/"),
        lembrar: Optional[str] = Form(None),
    ):
        if password is None:
            return RedirectResponse("/", status_code=303)
        key = auth.client_key(request.headers, request.client.host if request.client else None)
        wait = limiter.retry_after(key)
        if wait:
            minutes = max(1, round(wait / 60))
            return templates.TemplateResponse(
                request, "login.html",
                {"prox": auth.safe_next(prox), "bloqueado": minutes}, status_code=429,
            )
        if not auth.check_password(senha, password):
            limiter.fail(key)
            await asyncio.sleep(1)  # atrasa quem tenta adivinhar a senha
            return templates.TemplateResponse(
                request, "login.html", {"prox": auth.safe_next(prox), "erro": True}, status_code=401
            )
        limiter.reset(key)
        response = RedirectResponse(auth.safe_next(prox), status_code=303)
        response.set_cookie(
            auth.COOKIE_NAME,
            auth.session_token(password),
            # Sem "manter conectado", o cookie some ao fechar o navegador (computador de outra pessoa).
            max_age=auth.COOKIE_MAX_AGE if lembrar else None,
            httponly=True,
            samesite="lax",
            secure=auth.is_https(request.url.scheme, request.headers),
        )
        return response

    @app.get("/sair")
    def logout():
        response = RedirectResponse("/login" if password else "/", status_code=303)
        response.delete_cookie(auth.COOKIE_NAME)
        return response

    # ------------------------------------------------------------ apoio

    def code_of(course: Course) -> str:
        return course.code or course.name[:3].upper()

    def page(request: Request, name: str, tab: str, db: Session, **ctx) -> HTMLResponse:
        """Contexto comum das páginas: aba e mensagens."""
        ctx.update(
            tab=tab,
            ok=request.query_params.get("ok"),
            aviso=request.query_params.get("aviso"),
            erro=request.query_params.get("erro"),
            auth_enabled=password is not None,
        )
        return templates.TemplateResponse(request, name, ctx)

    def time_rows(db: Session) -> list[tuple[str, str]]:
        """Faixas de horário da grade (ex.: 16:00–18:00), a partir dos horários cadastrados."""
        ids = [c.id for c in attendance_svc.current_courses(db)]
        slots = db.exec(select(ScheduleSlot).where(ScheduleSlot.course_id.in_(ids))).all()
        return sorted({(s.start_time, s.end_time) for s in slots})

    def block_view(cs: ClassSession) -> dict:
        slot = next((s for s in cs.course.schedule if s.weekday == cs.day.weekday()), None)
        exam = next((a for a in cs.course.assessments if a.day == cs.day), None)
        return {
            "course_id": cs.course_id,
            "code": code_of(cs.course),
            "name": cs.course.name,
            "start": slot.start_time if slot else "",
            "end": slot.end_time if slot else "",
            "day": cs.day,
            "attended": cs.attended,
            "cancelled": cs.cancelled,
            "quiz": cs.has_quiz,
            "exam": exam.name if exam else None,
            "past": cs.day <= today_fn(),
            "color": COURSE_COLOR,
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
            "b": block_view(cs),
            "course": course,
            "summary": attendance_svc.summarize_course(db, course, today_fn()),
            "upcoming": upcoming,
        }

    def exam_view(a: Assessment, today: date) -> dict:
        return {
            "id": a.id,
            "name": a.name,
            "course_id": a.course_id,
            "course": a.course.name,
            "code": code_of(a.course),
            "color": COURSE_COLOR,
            "day": a.day,
            # Nota só depois da prova (prova sem data: liberada, ex.: trabalho entregue).
            "happened": a.day is None or a.day <= today,
            "when": relative_day(a.day, today) if a.day else None,
            "days_left": (a.day - today).days if a.day else None,
            "grade": a.grade,
        }

    # ------------------------------------------------------------ semana

    @app.get("/", response_class=HTMLResponse)
    def week_page(request: Request, semana: Optional[date] = None, db: Session = Depends(get_db)):
        today = today_fn()
        start = week_monday(semana or today)
        days = [start + timedelta(days=i) for i in range(5)]
        grid: dict[tuple[date, str], list[dict]] = {}
        for cs in attendance_svc.sessions_between(db, days[0], days[-1]):
            b = block_view(cs)
            grid.setdefault((cs.day, b["start"]), []).append(b)
        return page(
            request, "semana.html", "semana", db,
            today=today,
            days=days,
            rows=time_rows(db),
            grid=grid,
            prev_week=start - timedelta(days=7),
            next_week=start + timedelta(days=7),
            is_current_week=start == week_monday(today),
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

    # ------------------------------------------------------------ provas

    @app.get("/provas", response_class=HTMLResponse)
    def exams_page(request: Request, db: Session = Depends(get_db)):
        today = today_fn()
        ids = [c.id for c in attendance_svc.current_courses(db)]
        rows = db.exec(select(Assessment).where(Assessment.course_id.in_(ids))).all()
        views = [exam_view(a, today) for a in rows]
        upcoming = sorted((v for v in views if v["day"] and v["day"] >= today), key=lambda v: v["day"])
        done = sorted(
            (v for v in views if v["day"] and v["day"] < today), key=lambda v: v["day"], reverse=True
        )
        undated = sorted((v for v in views if not v["day"]), key=lambda v: (v["code"], v["name"]))
        return page(
            request, "provas.html", "provas", db,
            today=today, upcoming=upcoming, done=done, undated=undated,
        )

    @app.get("/provas/nova", response_class=HTMLResponse)
    def new_exam_sheet(request: Request, db: Session = Depends(get_db)):
        courses = [
            {"id": c.id, "code": code_of(c), "name": c.name, "color": COURSE_COLOR}
            for c in sorted(attendance_svc.current_courses(db), key=code_of)
        ]
        return templates.TemplateResponse(request, "_exam_new.html", {"courses": courses})

    @app.post("/provas")
    def create_exam(
        disciplina: int = Form(...),
        dia: date = Form(...),
        nome: str = Form(""),
        db: Session = Depends(get_db),
    ):
        course = db.get(Course, disciplina)
        if course is None or course.status == CourseStatus.DROPPED:
            return back_to("/provas", erro="Disciplina não encontrada.")
        name = nome.strip() or assessment_svc.next_free_name(db, course.id)
        result = assessment_svc.schedule_assessment(
            db, course.id, name, dia, batch=ChangeBatch(source="site")
        )
        if result.warnings:
            return back_to("/provas", aviso=" ".join(result.warnings))
        return back_to("/provas", ok=f"{result.assessment.name} de {code_of(course)} salva.")

    @app.get("/provas/{assessment_id}", response_class=HTMLResponse)
    def exam_sheet(request: Request, assessment_id: int, db: Session = Depends(get_db)):
        a = db.get(Assessment, assessment_id)
        if a is None:
            return HTMLResponse("Avaliação não encontrada.", status_code=404)
        return templates.TemplateResponse(
            request, "_exam_sheet.html", {"e": exam_view(a, today_fn())}
        )

    @app.post("/provas/{assessment_id}")
    def update_exam(
        assessment_id: int,
        dia: Optional[str] = Form(None),
        nota: Optional[str] = Form(None),  # ausente = prova futura, sem campo de nota
        db: Session = Depends(get_db),
    ):
        a = db.get(Assessment, assessment_id)
        if a is None:
            return back_to("/provas", erro="Avaliação não encontrada.")
        try:
            grade = parse_grade(nota)
        except ValueError as exc:
            return back_to("/provas", erro=str(exc))
        new_day = date.fromisoformat(dia) if dia else a.day
        if grade is not None and new_day is not None and new_day > today_fn():
            return back_to("/provas", erro="A nota só pode ser lançada a partir do dia da prova.")
        batch = ChangeBatch(source="site")  # data e nota no mesmo lote: um "desfazer" só
        warnings: list[str] = []
        if dia:
            if new_day != a.day:
                warnings = assessment_svc.schedule_assessment(
                    db, a.course_id, a.name, new_day, batch=batch
                ).warnings
        if nota is None:
            pass  # formulário sem campo de nota: não mexe na nota
        elif grade is None:
            if a.grade is not None:
                assessment_svc.clear_assessment_grade(db, a.id, batch=batch)
        else:
            assessment_svc.set_assessment_grade(db, a.course_id, a.name, grade, batch=batch)
        if warnings:
            return back_to("/provas", aviso=" ".join(warnings))
        return back_to("/provas", ok="Alterações salvas.")

    @app.post("/provas/{assessment_id}/excluir")
    def delete_exam(assessment_id: int, db: Session = Depends(get_db)):
        try:
            assessment_svc.delete_assessment(db, assessment_id, batch=ChangeBatch(source="site"))
        except ValueError as exc:
            return back_to("/provas", erro=str(exc))
        return back_to("/provas", ok="Prova excluída.")

    # ------------------------------------------------------------ histórico

    def term_views(db: Session) -> list[dict]:
        courses = db.exec(select(Course)).all()
        crs = grades_svc.cr_by_term(courses)
        terms = []
        for term, group in groupby(sorted(courses, key=lambda c: (-c.term, c.name)), key=lambda c: c.term):
            group = list(group)
            terms.append({
                "term": term,
                "cr": crs.get(term),
                "credits": sum(c.credits for c in group if grades_svc.counts_for_cr(c)),
                "courses": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "code": c.code,
                        "credits": c.credits,
                        "grade": c.final_grade,
                        "status": c.status,
                        "counts": grades_svc.counts_for_cr(c),
                        "program": c.program,
                    }
                    for c in group
                ],
            })
        return terms

    def simulation_inputs(db: Session) -> list[Course]:
        """Disciplinas do período atual que entram no CR e ainda não têm média final."""
        return [
            c for c in attendance_svc.current_courses(db)
            if grades_svc.counts_for_cr(c) and c.final_grade is None
        ]

    @app.get("/historico", response_class=HTMLResponse)
    def history_page(request: Request, db: Session = Depends(get_db)):
        all_courses = db.exec(select(Course)).all()
        return page(
            request, "historico.html", "historico", db,
            cr=grades_svc.current_cr(db),
            total_credits=sum(
                c.credits for c in all_courses
                if grades_svc.counts_for_cr(c) and c.final_grade is not None
            ),
            terms=term_views(db),
            current_term=attendance_svc.current_term(db),
            sim_courses=simulation_inputs(db),
        )

    @app.post("/historico/simular", response_class=HTMLResponse)
    async def simulate(request: Request, db: Session = Depends(get_db)):
        form = await request.form()
        hypothetical: dict[int, float] = {}
        error = None
        courses = simulation_inputs(db)
        for c in courses:
            try:
                grade = parse_grade(str(form.get(f"nota_{c.id}", "")))
            except ValueError as exc:
                error = f"{c.name}: {exc}"
                break
            if grade is not None:
                hypothetical[c.id] = grade
        # Só calcula com TODAS as médias preenchidas: um CR parcial engana mais do que ajuda.
        complete = len(hypothetical) == len(courses)
        ctx: dict = {"error": error, "filled": len(hypothetical), "complete": complete}
        if not error and complete and hypothetical:
            ctx["total"] = grades_svc.simulate_cr(db, hypothetical, scope="acumulado")
            ctx["term"] = grades_svc.simulate_cr(db, hypothetical, scope="periodo")
            ctx["current"] = grades_svc.current_cr(db)
        return templates.TemplateResponse(request, "_sim_result.html", ctx)

    @app.get("/disciplinas/{course_id}", response_class=HTMLResponse)
    def course_sheet(request: Request, course_id: int, db: Session = Depends(get_db)):
        course = db.get(Course, course_id)
        if course is None:
            return HTMLResponse("Disciplina não encontrada.", status_code=404)
        is_current = course.term == attendance_svc.current_term(db)
        summary = None
        if is_current and course.sessions and course.status != CourseStatus.DROPPED:
            summary = attendance_svc.summarize_course(db, course, today_fn())
        return templates.TemplateResponse(
            request,
            "_course_sheet.html",
            {
                "c": course,
                "color": COURSE_COLOR,
                "is_current": is_current,
                "counts": grades_svc.counts_for_cr(course),
                "summary": summary,
            },
        )

    def course_action(course_id: int, db: Session, action) -> RedirectResponse:
        if db.get(Course, course_id) is None:
            return back_to("/historico", erro="Disciplina não encontrada.")
        try:
            action(ChangeBatch(source="site"))
        except ValueError as exc:
            return back_to("/historico", erro=str(exc))
        return back_to("/historico", ok="Alteração salva.")

    @app.post("/disciplinas/{course_id}/media")
    def set_final(course_id: int, nota: str = Form(""), db: Session = Depends(get_db)):
        try:
            grade = parse_grade(nota)
        except ValueError as exc:
            return back_to("/historico", erro=str(exc))
        return course_action(
            course_id, db,
            lambda b: course_svc.set_final_grade(db, course_id, grade, today=today_fn(), batch=b),
        )

    @app.post("/disciplinas/{course_id}/trancar")
    def toggle_dropped(course_id: int, db: Session = Depends(get_db)):
        course = db.get(Course, course_id)
        if course is not None and course.status == CourseStatus.DROPPED:
            return course_action(course_id, db, lambda b: course_svc.undrop_course(db, course_id, b))
        return course_action(course_id, db, lambda b: course_svc.drop_course(db, course_id, b))

    @app.post("/disciplinas/{course_id}/frequencia")
    def toggle_attendance_rule(course_id: int, db: Session = Depends(get_db)):
        course = db.get(Course, course_id)
        value = not course.requires_attendance if course else True
        return course_action(
            course_id, db, lambda b: course_svc.set_requires_attendance(db, course_id, value, b)
        )

    @app.post("/disciplinas/{course_id}/curso")
    def set_program(course_id: int, curso: str = Form(...), db: Session = Depends(get_db)):
        if not curso.strip():
            return back_to("/historico", erro="Informe o curso (ex.: SI).")
        return course_action(course_id, db, lambda b: course_svc.set_program(db, course_id, curso, b))

    # ------------------------------------------------------------ desfazer

    @app.post("/desfazer")
    def undo(request: Request, db: Session = Depends(get_db)):
        undo_last_batch(db)
        # Volta para a mesma página, sem repetir mensagens antigas (?aviso=...).
        referer = urlsplit(request.headers.get("referer") or "/")
        semana = dict(p.split("=", 1) for p in referer.query.split("&") if p.startswith("semana="))
        target = auth.safe_next(referer.path or "/")
        return RedirectResponse(target + (f"?{urlencode(semana)}" if semana else ""), status_code=303)

    return app


# Instância usada pelo uvicorn (banco real, senha do .env).
load_dotenv()
app = create_app(password=os.getenv("SITE_PASSWORD", "").strip() or None)
