from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "migrations" / "001_schema.sql"
DEFAULT_DB_PATH = Path(os.environ.get("SOCIAL_SECURITY_CRAWLER_DB", "social_security_crawler.sqlite3"))


class SQLiteStore:
    def __init__(self, path: str | os.PathLike[str] = DEFAULT_DB_PATH) -> None:
        self.path = Path(path)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self.conn.commit()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        cursor = self.conn.execute(sql, tuple(params))
        self.conn.commit()
        return cursor

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        self.conn.executemany(sql, rows)
        self.conn.commit()

    def fetchone(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, tuple(params)).fetchone()

    def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, tuple(params)).fetchall())


def utcnow() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def default_db() -> SQLiteStore:
    db = SQLiteStore()
    db.init_schema()
    return db
