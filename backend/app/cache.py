"""Кэш сводной статистики в Redis. Реплики API не хранят состояние у себя,
поэтому общий кэш одинаково виден любой из них."""
import json
import logging

import redis

from .config import settings
from .events import get_redis

log = logging.getLogger("bizflow.cache")


def _key(company_id: int) -> str:
    return f"bizflow:stats:{company_id}"


def get_stats(company_id: int) -> dict | None:
    r = get_redis()
    if r is None:
        return None
    try:
        raw = r.get(_key(company_id))
    except redis.RedisError as exc:
        log.warning("Кэш недоступен: %s", exc)
        return None
    return json.loads(raw) if raw else None


def set_stats(company_id: int, data: dict) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.setex(_key(company_id), settings.stats_cache_ttl, json.dumps(data))
    except redis.RedisError as exc:
        log.warning("Кэш недоступен: %s", exc)


def invalidate_stats(company_id: int) -> None:
    r = get_redis()
    if r is None:
        return
    try:
        r.delete(_key(company_id))
    except redis.RedisError:
        pass
