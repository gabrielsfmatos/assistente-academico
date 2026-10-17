"""Conexão com o banco de dados SQLite."""

from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

from app import models  # noqa: F401  (registra as tabelas no SQLModel)

# O banco fica na raiz do projeto. O .gitignore impede que ele vá para o GitHub.
DB_PATH = Path(__file__).resolve().parent.parent / "academico.db"


def get_engine(url: str | None = None):
    # check_same_thread=False: o bot do Telegram atende mensagens em outra thread.
    return create_engine(url or f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def init_db(engine) -> None:
    """Cria as tabelas que ainda não existem."""
    SQLModel.metadata.create_all(engine)


def get_session(engine) -> Session:
    return Session(engine)
