import logging
import time

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

log = logging.getLogger("bizflow.db")

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # У каждой реплики свой пул соединений, поэтому он намеренно небольшой:
    # 5 реплик x (5 + 5) соединений укладываются в max_connections PostgreSQL.
    engine = create_engine(settings.database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_schema() -> None:
    """Создание таблиц. Несколько реплик API стартуют одновременно, поэтому
    в PostgreSQL создание схемы выполняется под advisory-блокировкой."""
    from . import models  # noqa: F401  регистрирует модели в метаданных

    if engine.dialect.name != "postgresql":
        Base.metadata.create_all(bind=engine)
        return

    # В Swarm нет depends_on: реплика может стартовать раньше базы данных,
    # поэтому подключение повторяется, пока PostgreSQL не станет доступен.
    for attempt in range(1, 31):
        try:
            with engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(424242)"))
                Base.metadata.create_all(bind=conn)
                # миграция для баз, созданных версией 1.0/1.1: идентификатор события
                # с уникальным индексом защищает от повторной обработки
                conn.execute(text("ALTER TABLE event_log ADD COLUMN IF NOT EXISTS event_id VARCHAR(32)"))
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_event_log_event_id ON event_log (event_id)"))
            return
        except OperationalError as exc:
            log.warning("База данных недоступна (попытка %s/30): %s", attempt, exc.orig)
            time.sleep(2)
    raise RuntimeError("Не удалось подключиться к базе данных")
