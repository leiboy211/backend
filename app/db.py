from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import settings
import threading

connect_args = {}
database_url = str(settings.database_url or "")
is_postgres = database_url.startswith(("postgresql://", "postgresql+psycopg2://", "postgres://"))
if is_postgres and settings.database_sslmode:
    connect_args["sslmode"] = settings.database_sslmode
if is_postgres:
    connect_args["connect_timeout"] = 5
if is_postgres and settings.database_statement_timeout_ms:
    connect_args["options"] = f"-c statement_timeout={settings.database_statement_timeout_ms}"

engine_kwargs = {
    "pool_pre_ping": True,
    "connect_args": connect_args,
    "hide_parameters": True,
}
if is_postgres:
    engine_kwargs.update(
        {
            "pool_size": settings.database_pool_size,
            "max_overflow": settings.database_max_overflow,
            "pool_timeout": settings.database_pool_timeout,
            "pool_recycle": settings.database_pool_recycle,
        }
    )

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

_schema_init_lock = threading.Lock()
_schema_initialized = False


def ensure_schema_initialized(force: bool = False) -> None:
    global _schema_initialized
    if _schema_initialized and not force:
        return
    with _schema_init_lock:
        if _schema_initialized and not force:
            return
        # Import models lazily so SQLAlchemy sees every table before create_all runs.
        from app import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        _schema_initialized = True


def get_db():
    ensure_schema_initialized()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
