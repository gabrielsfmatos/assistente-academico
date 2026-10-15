"""Modelo de dados do sistema.

Cada classe abaixo vira uma tabela no banco SQLite.
O SQLModel junta duas coisas: a definição da tabela (SQLAlchemy)
e a validação dos campos (Pydantic).
"""

from datetime import date
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

# Curso de graduação "da casa". Só disciplinas desse curso entram no CR
# (norma da UNIRIO: disciplinas cursadas em outro curso não contam).
HOME_PROGRAM = "SI"  # Bacharelado em Sistemas de Informação


class Course(SQLModel, table=True):
    """Uma disciplina cursada (ou em curso)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    code: Optional[str] = Field(default=None, index=True)  # sigla, ex.: "ACD"
    term: int  # período em que foi cursada (1, 2, ..., 6)
    credits: float
    program: str = HOME_PROGRAM  # curso em que a disciplina foi cursada
    requires_attendance: bool = True  # algumas disciplinas não cobram frequência
    final_grade: Optional[float] = None  # média final, digitada no fim do período

    sessions: list["ClassSession"] = Relationship(back_populates="course")
    assessments: list["Assessment"] = Relationship(back_populates="course")
    schedule: list["ScheduleSlot"] = Relationship(back_populates="course")


class ClassSession(SQLModel, table=True):
    """Uma aula em um dia específico.

    Toda aula é presença (attended=True) ou falta (attended=False).
    As flags só destacam o que aconteceu no dia; apenas `cancelled`
    muda o cálculo: aula cancelada sai da conta de frequência.
    """

    __table_args__ = (UniqueConstraint("course_id", "day"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    day: date = Field(index=True)
    attended: bool = True
    cancelled: bool = False
    has_exam: bool = False  # dia de prova
    has_quiz: bool = False  # dia de teste
    note: Optional[str] = None

    course: Optional[Course] = Relationship(back_populates="sessions")


class Assessment(SQLModel, table=True):
    """Uma avaliação (P1, P2, trabalho...). Serve para registro e agenda;
    a média final continua sendo digitada em Course.final_grade."""

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    name: str  # ex.: "P1"
    day: Optional[date] = None
    grade: Optional[float] = None

    course: Optional[Course] = Relationship(back_populates="assessments")


class ScheduleSlot(SQLModel, table=True):
    """Um horário fixo da grade semanal (ex.: segunda, 16h-18h, ACD)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    course_id: int = Field(foreign_key="course.id", index=True)
    weekday: int  # 0 = segunda ... 4 = sexta (mesmo padrão do Python)
    start_time: str  # "16:00"
    end_time: str  # "18:00"

    course: Optional[Course] = Relationship(back_populates="schedule")
