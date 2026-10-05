"""Shared SQLAlchemy engine/session setup, used by both the backend API and the collector."""
import logging
import os
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.schema import CreateColumn

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://monitoring:monitoring@localhost:5432/monitoring",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


@contextmanager
def session_scope():
    """Provide a transactional scope for scripts/background jobs (non-FastAPI usage)."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def add_missing_columns(bind: Engine) -> list[str]:
    """create_all legt nur fehlende Tabellen an, keine neuen Spalten in bestehenden.
    Spalten, die in neueren Versionen dazugekommen sind, werden hier nachgezogen -
    nur hinzufuegen, nie aendern oder loeschen. Gibt die ergaenzten Spalten zurueck."""
    inspector = inspect(bind)
    added = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable and column.server_default is None:
                    raise RuntimeError(
                        f"Spalte {table.name}.{column.name} kann nicht automatisch ergänzt werden "
                        "(NOT NULL ohne server_default)"
                    )
                ddl = CreateColumn(column).compile(dialect=bind.dialect)
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
                added.append(f"{table.name}.{column.name}")
    for name in added:
        logger.warning("Datenbank aktualisiert: Spalte %s ergänzt", name)
    return added


def init_db() -> None:
    """Create all tables and add new columns. Safe to call repeatedly."""
    from . import models  # noqa: F401  (ensures models are registered on Base)

    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)
