"""Backup: a cópia é um banco válido e as cópias antigas são apagadas."""

import sqlite3

from scripts.backup_db import backup


def make_db(path):
    with sqlite3.connect(path) as db:
        db.execute("create table t (x int)")
        db.execute("insert into t values (42)")


def test_backup_copies_data(tmp_path):
    src = tmp_path / "academico.db"
    make_db(src)
    dest = backup(src, tmp_path / "backups")
    with sqlite3.connect(dest) as db:
        assert db.execute("select x from t").fetchone() == (42,)


def test_backup_keeps_only_recent_copies(tmp_path):
    src = tmp_path / "academico.db"
    make_db(src)
    folder = tmp_path / "backups"
    folder.mkdir()
    for day in range(1, 6):  # cópias antigas de 01 a 05/10
        (folder / f"academico-2026-10-0{day}_0300.db").write_bytes(b"")
    backup(src, folder, keep=3)
    names = sorted(p.name for p in folder.glob("academico-*.db"))
    assert len(names) == 3
    assert names[0] == "academico-2026-10-04_0300.db"  # 01, 02 e 03 foram apagadas
