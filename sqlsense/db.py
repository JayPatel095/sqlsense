"""Connection handling for PostgreSQL and SQLite."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass


class DatabaseError(Exception):
    """A database failure with a message fit for showing to the user."""


@dataclass
class Connection:
    dialect: str  # "postgres" | "sqlite"
    raw: object  # DB-API connection

    def close(self) -> None:
        self.raw.close()


def connect(db_url: str) -> Connection:
    """Open a connection from a URL or SQLite file path.

    Accepts postgresql:// / postgres:// URLs, sqlite:// URLs, or a bare
    filesystem path to an existing SQLite database.
    """
    if db_url.startswith(("postgresql://", "postgres://")):
        return _connect_postgres(db_url)
    if db_url.startswith("sqlite://"):
        # sqlite:///relative.db and sqlite:////abs/path.db both work
        path = db_url[len("sqlite://") :]
        if path.startswith("/") and not os.path.isabs(path[1:]):
            path = path[1:]
        return _connect_sqlite(path)
    if "://" in db_url:
        scheme = db_url.split("://", 1)[0]
        raise DatabaseError(
            f"unsupported database scheme {scheme!r} (supported: postgresql, sqlite)"
        )
    return _connect_sqlite(db_url)


def _connect_postgres(dsn: str) -> Connection:
    import psycopg2

    try:
        raw = psycopg2.connect(dsn, connect_timeout=10)
    except psycopg2.Error as exc:
        detail = str(exc).strip().splitlines()
        raise DatabaseError(
            "could not connect to PostgreSQL: " + (detail[0] if detail else "unknown error")
        ) from exc
    return Connection(dialect="postgres", raw=raw)


def _connect_sqlite(path: str) -> Connection:
    # sqlite3.connect silently creates missing files; require an existing db
    # so a typo'd path fails loudly instead.
    if path != ":memory:" and not os.path.exists(path):
        raise DatabaseError(f"no such SQLite database file: {path}")
    try:
        raw = sqlite3.connect(path)
    except sqlite3.Error as exc:
        raise DatabaseError(f"could not open SQLite database {path}: {exc}") from exc
    return Connection(dialect="sqlite", raw=raw)
