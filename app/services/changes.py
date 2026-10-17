"""Registro de alterações e "desfazer".

Toda alteração feita pela camada de serviços passa por aqui:
1. guardamos uma foto do registro antes e depois (em JSON);
2. alterações da mesma mensagem/ação compartilham um "lote" (batch);
3. desfazer = reverter o último lote inteiro, na ordem inversa.

É isso que permite ao agente errar sem causar estrago permanente.
"""

import json
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

from sqlmodel import Session, SQLModel, select

from app.models import Assessment, ChangeLog, ClassSession, Course

ENTITIES: dict[str, type[SQLModel]] = {
    "course": Course,
    "classsession": ClassSession,
    "assessment": Assessment,
}


@dataclass
class ChangeBatch:
    """Agrupa as alterações de uma mesma mensagem (agente) ou ação (site)."""

    source: str = "sistema"  # "site" | "agente" | "sistema"
    id: str = field(default_factory=lambda: uuid4().hex)


def snapshot(obj: SQLModel) -> dict:
    """Campos do registro em formato JSON (datas viram texto ISO)."""
    return obj.model_dump(mode="json")


def _entity_name(obj: SQLModel) -> str:
    return type(obj).__tablename__


def _record(db: Session, batch: ChangeBatch, obj, action: str, before, after, description: str):
    db.add(
        ChangeLog(
            batch_id=batch.id,
            source=batch.source,
            entity=_entity_name(obj),
            entity_id=obj.id,
            action=action,
            before=json.dumps(before, ensure_ascii=False) if before is not None else None,
            after=json.dumps(after, ensure_ascii=False) if after is not None else None,
            description=description,
        )
    )


def update_fields(
    db: Session, obj: SQLModel, fields: dict, batch: Optional[ChangeBatch], description: str
) -> bool:
    """Altera campos de um registro e registra no log.

    Retorna False (e não grava nada) se nenhum valor mudou de fato,
    por exemplo, ao registrar uma falta que já estava registrada.
    """
    batch = batch or ChangeBatch()
    before = snapshot(obj)
    changed = False
    for name, value in fields.items():
        if getattr(obj, name) != value:
            setattr(obj, name, value)
            changed = True
    if not changed:
        return False
    db.add(obj)
    db.flush()
    _record(db, batch, obj, "update", before, snapshot(obj), description)
    db.commit()
    db.refresh(obj)
    return True


def create(db: Session, obj: SQLModel, batch: Optional[ChangeBatch], description: str) -> SQLModel:
    batch = batch or ChangeBatch()
    db.add(obj)
    db.flush()  # gera o id
    _record(db, batch, obj, "create", None, snapshot(obj), description)
    db.commit()
    db.refresh(obj)
    return obj


def delete(db: Session, obj: SQLModel, batch: Optional[ChangeBatch], description: str) -> None:
    """Apaga o registro, guardando uma cópia no log para o "desfazer" recriar."""
    batch = batch or ChangeBatch()
    _record(db, batch, obj, "delete", snapshot(obj), None, description)
    db.delete(obj)
    db.commit()


def _restore(model: type[SQLModel], data: dict) -> SQLModel:
    """Converte o JSON salvo de volta para os tipos corretos (ex.: texto -> date)."""
    return model.model_validate(data)


def undo_last_batch(db: Session) -> list[str]:
    """Reverte o último lote de alterações. Retorna as descrições revertidas
    (lista vazia se não há nada para desfazer)."""
    last = db.exec(
        select(ChangeLog).where(ChangeLog.undone == False).order_by(ChangeLog.id.desc())  # noqa: E712
    ).first()
    if last is None:
        return []

    entries = db.exec(
        select(ChangeLog).where(ChangeLog.batch_id == last.batch_id).order_by(ChangeLog.id.desc())
    ).all()

    for entry in entries:
        model = ENTITIES[entry.entity]
        current = db.get(model, entry.entity_id)
        if entry.action == "update" and current is not None:
            restored = _restore(model, json.loads(entry.before))
            for name in json.loads(entry.before):
                setattr(current, name, getattr(restored, name))
            db.add(current)
        elif entry.action == "create" and current is not None:
            db.delete(current)
        elif entry.action == "delete" and current is None:
            db.add(_restore(model, json.loads(entry.before)))
        entry.undone = True
        db.add(entry)

    db.commit()
    return [e.description for e in reversed(entries)]
