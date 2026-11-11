"""Очередь событий для правил автоматизации.

API кладёт событие в список Redis, воркер забирает его командой BRPOP.
Если Redis не настроен (локальный запуск, тесты), правило выполняется сразу
в том же процессе, чтобы поведение платформы не менялось."""
import json
import logging

import redis

from .config import settings

log = logging.getLogger("bizflow.events")
QUEUE = "bizflow:events"

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3)
    return _client


def publish(kind: str, company_id: int, **data) -> None:
    event = {"kind": kind, "company_id": company_id, **data}
    r = get_redis()
    if r is not None:
        try:
            r.lpush(QUEUE, json.dumps(event, ensure_ascii=False))
            return
        except redis.RedisError as exc:
            log.warning("Redis недоступен, событие обрабатывается синхронно: %s", exc)
    from .automation import handle_event
    from .db import SessionLocal

    with SessionLocal() as db:
        handle_event(db, event, processed_by=f"{settings.hostname} (inline)")
