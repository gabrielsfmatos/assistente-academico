"""Backup do banco de dados.

Faz uma cópia consistente do academico.db (mesmo com o bot e o site rodando),
guarda em backups/ e apaga as cópias mais antigas que KEEP dias.
Com --telegram, também manda a cópia para o seu chat no Telegram, em modo
silencioso. É a cópia "fora do servidor": se a máquina da Oracle sumir,
os dados continuam com você.

Uso (na raiz do projeto):
    python -m scripts.backup_db              # só a cópia local
    python -m scripts.backup_db --telegram   # cópia local + Telegram

No servidor, roda sozinho todo dia (deploy/academico-backup.timer).
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

from app.db import DB_PATH

BACKUP_DIR = DB_PATH.parent / "backups"
KEEP = 14  # dias de cópias locais


def backup(db_path: Path = DB_PATH, dest_dir: Path = BACKUP_DIR, keep: int = KEEP) -> Path:
    """Copia o banco usando a API de backup do SQLite (segura com o banco em uso)."""
    if not db_path.exists():
        raise FileNotFoundError(f"Banco não encontrado: {db_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"academico-{datetime.now():%Y-%m-%d_%H%M}.db"
    with sqlite3.connect(db_path) as src, sqlite3.connect(dest) as out:
        src.backup(out)
    out.close()
    old = sorted(dest_dir.glob("academico-*.db"))[:-keep] if keep > 0 else []
    for path in old:
        path.unlink()
    return dest


def send_telegram(path: Path, token: str, chat_id: str) -> None:
    with path.open("rb") as f:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendDocument",
            data={
                "chat_id": chat_id,
                "caption": f"Backup do banco ({datetime.now():%d/%m/%Y})",
                "disable_notification": "true",
            },
            files={"document": (path.name, f, "application/octet-stream")},
            timeout=60,
        )
    r.raise_for_status()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--telegram", action="store_true", help="manda a cópia para o Telegram")
    parser.add_argument("--keep", type=int, default=KEEP, help="quantas cópias locais manter")
    args = parser.parse_args()

    load_dotenv()
    dest = backup(keep=args.keep)
    print(f"Backup salvo em {dest} ({dest.stat().st_size // 1024} KB)")

    if args.telegram:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.getenv("TELEGRAM_USER_ID", "").strip()
        if not token or not chat_id:
            print("TELEGRAM_BOT_TOKEN ou TELEGRAM_USER_ID ausente no .env.", file=sys.stderr)
            return 1
        send_telegram(dest, token, chat_id)
        print("Cópia enviada para o Telegram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
