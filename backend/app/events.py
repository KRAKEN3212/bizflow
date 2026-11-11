"""Очередь событий для правил автоматизации.

Схема «надёжной очереди» Redis:
  bizflow:events      — новые события (API добавляет командой LPUSH);
  bizflow:processing  — события, взятые воркером в работу (BLMOVE);
  bizflow:inflight    — хеш «идентификатор события -> время взятия в работу»;
  bizflow:dead        — события, которые не удалось обработать за MAX_ATTEMPTS попыток.

Воркер удаляет событие из bizflow:processing только после того, как задача
записана в базу (подтверждение). Если воркер упал, событие остаётся в
bizflow:processing, и через VISIBILITY_TIMEOUT секунд любой воркер вернёт его
в очередь. Доставка выполняется «хотя бы один раз», а повтор не создаёт
дубликатов благодаря уникальному идентификатору события (см. automation.py).

Ограничения: событие публикуется после фиксации транзакции в PostgreSQL, и
при падении реплики API ровно между этими двумя действиями оно будет потеряно
(шаблон transactional outbox не реализован). Redis пишет журнал AOF раз в
секунду, поэтому при аварии самого Redis могут пропасть события последней секунды.

Если Redis не настроен (локальный запуск, тесты) или недоступен, правило
выполняется сразу в процессе API."""
import json
import logging
import time
import uuid

import redis

from .config import settings

log = logging.getLogger("bizflow.events")
QUEUE = "bizflow:events"
PROCESSING = "bizflow:processing"
INFLIGHT = "bizflow:inflight"
DEAD = "bizflow:dead"
MAX_ATTEMPTS = 5
VISIBILITY_TIMEOUT = 60

# Атомарно убрать событие из processing и положить в целевой список.
# Возвращает 1, если событие действительно было в processing (защита от
# двойного возврата, когда сборщик запущен сразу на нескольких воркерах).
_MOVE_BACK = """
if redis.call('LREM', KEYS[1], 1, ARGV[1]) == 1 then
  redis.call('HDEL', KEYS[2], ARGV[2])
  redis.call('LPUSH', KEYS[3], ARGV[3])
  return 1
end
return 0
"""

_client: redis.Redis | None = None


def get_redis() -> redis.Redis | None:
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        _client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)
    return _client


def publish(kind: str, company_id: int, **data) -> None:
    event = {"id": uuid.uuid4().hex, "kind": kind, "company_id": company_id, "attempt": 0, **data}
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


# ---------- операции воркера ----------

def take(r: redis.Redis, timeout: float = 2) -> str | None:
    """Забрать самое старое событие и переложить его в список обрабатываемых."""
    raw = r.blmove(QUEUE, PROCESSING, timeout, "RIGHT", "LEFT")
    if raw is not None:
        r.hset(INFLIGHT, json.loads(raw)["id"], time.time())
    return raw


def ack(r: redis.Redis, raw: str) -> None:
    """Подтвердить обработку: событие больше не нужно хранить."""
    pipe = r.pipeline()
    pipe.lrem(PROCESSING, 1, raw)
    pipe.hdel(INFLIGHT, json.loads(raw)["id"])
    pipe.execute()


def retry(r: redis.Redis, raw: str, count_attempt: bool = True) -> str:
    """Вернуть событие в очередь после ошибки или отправить в dead-список."""
    event = json.loads(raw)
    if count_attempt:
        event["attempt"] = event.get("attempt", 0) + 1
    target = DEAD if event["attempt"] >= MAX_ATTEMPTS else QUEUE
    r.eval(_MOVE_BACK, 3, PROCESSING, INFLIGHT, target, raw, event["id"],
           json.dumps(event, ensure_ascii=False))
    return target


def reap(r: redis.Redis, now: float | None = None, visibility: float = VISIBILITY_TIMEOUT) -> int:
    """Вернуть в очередь события, которые слишком долго висят в обработке
    (воркер, взявший их, остановлен или упал). Возвращает число возвращённых."""
    now = time.time() if now is None else now
    returned = 0
    for raw in r.lrange(PROCESSING, 0, -1):
        event_id = json.loads(raw)["id"]
        started = r.hget(INFLIGHT, event_id)
        if started is None:
            # событие только что взято, отметка ещё не успела записаться
            r.hsetnx(INFLIGHT, event_id, now)
            continue
        if now - float(started) > visibility:
            returned += r.eval(_MOVE_BACK, 3, PROCESSING, INFLIGHT, QUEUE, raw, event_id, raw)
    return returned
