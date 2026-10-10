"""Shared SQLAlchemy engine/session setup, used by both the backend API and the collector."""
import logging
import os
from contextlib import contextmanager

from sqlalchemy import Enum, create_engine, inspect, text
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


def add_missing_enum_values(bind: Engine) -> list[str]:
    """PostgreSQL speichert Auswahlfelder (z. B. den Geraetetyp) als eigenen Datentyp mit
    fester Werteliste. Neue Werte aus spaeteren Versionen werden hier ergaenzt - nur
    hinzufuegen, nie loeschen. SQLite braucht das nicht. Gibt die ergaenzten Werte zurueck."""
    if bind.dialect.name != "postgresql":
        return []
    enum_types = {}
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, Enum) and column.type.native_enum and column.type.name:
                enum_types[column.type.name] = column.type.enums
    added = []
    # ALTER TYPE ... ADD VALUE ausserhalb einer Transaktion, damit der Wert sofort nutzbar ist
    with bind.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for type_name, values in enum_types.items():
            existing = set(conn.execute(
                text("SELECT e.enumlabel FROM pg_enum e JOIN pg_type t ON e.enumtypid = t.oid "
                     "WHERE t.typname = :name"),
                {"name": type_name},
            ).scalars())
            if not existing:
                continue  # Typ gibt es (noch) nicht - legt create_all vollstaendig an
            for value in values:
                if value not in existing:
                    quoted = value.replace("'", "''")
                    conn.execute(text(f"ALTER TYPE {type_name} ADD VALUE IF NOT EXISTS '{quoted}'"))
                    added.append(f"{type_name}.{value}")
    for name in added:
        logger.warning("Datenbank aktualisiert: Auswahlwert %s ergänzt", name)
    return added


def init_db() -> None:
    """Create all tables, add new columns and enum values. Safe to call repeatedly."""
    from . import models  # noqa: F401  (ensures models are registered on Base)

    Base.metadata.create_all(bind=engine)
    add_missing_columns(engine)
    add_missing_enum_values(engine)
