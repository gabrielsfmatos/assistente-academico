"""Dados de teste compartilhados: um semestre pequeno, parecido com o real.

Semana de 12/10/2026 (segunda) a 23/10/2026 (sexta):
- ACD: segunda e quarta, cobra frequência
- EI: segunda e quarta, NÃO cobra frequência
- AP: terça e quinta, cobra frequência
Histórico: uma disciplina de SI (nota 10, 4 créditos) e Cálculo II de
Engenharia de Produção (nota 5, fora do CR).
"""

from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import Assessment, ClassSession, Course, CourseStatus, ScheduleSlot

MONDAY = date(2026, 10, 12)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        acd = Course(id=1, name="Algoritmos para Ciência de Dados", code="ACD", term=6, credits=4)
        ei = Course(
            id=2, name="Empreendedorismo e Inovação", code="EI", term=6, credits=4,
            requires_attendance=False,
        )
        ap = Course(id=3, name="Aprendizagem Profunda", code="AP", term=6, credits=4)
        old = Course(
            id=4, name="Estatística", term=5, credits=4, final_grade=10, status=CourseStatus.PASSED
        )
        calc = Course(
            id=5, name="Cálculo II", term=3, credits=4, final_grade=5, program="EP",
            status=CourseStatus.FAILED,
        )
        session.add_all([acd, ei, ap, old, calc])
        for course_id, weekdays in ((1, (0, 2)), (2, (0, 2)), (3, (1, 3))):
            for wd in weekdays:
                session.add(
                    ScheduleSlot(course_id=course_id, weekday=wd, start_time="16:00", end_time="18:00")
                )
            for week in range(2):
                for wd in weekdays:
                    day = MONDAY + timedelta(weeks=week, days=wd)
                    session.add(ClassSession(course_id=course_id, day=day))
        session.add(Assessment(course_id=3, name="P1", day=date(2026, 10, 22)))
        session.commit()
        yield session
