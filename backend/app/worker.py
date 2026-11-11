"""Фоновый обработчик событий автоматизации.

Запускается тем же образом, что и API, но с другой командой:
    python -m app.worker
Несколько реплик воркера читают одну очередь; BRPOP отдаёт каждое событие
ровно одному из них, поэтому воркеры масштабируются так же, как API."""
import json
import logging
import signal
import time

import redis

from .automation import handle_event
from .config import settings
from .db import SessionLocal, init_schema
from .events import QUEUE, get_redis

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker: %(message)s")
log = logging.getLogger("bizflow.worker")

_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("Получен сигнал остановки, текущее событие будет доработано")


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    init_schema()
    r = get_redis()
    if r is None:
        raise SystemExit("REDIS_URL не задан, воркеру нечего читать")
    log.info("Воркер %s слушает очередь %s", settings.hostname, QUEUE)
    while _running:
        try:
            item = r.brpop(QUEUE, timeout=2)
        except redis.RedisError as exc:
            log.warning("Нет связи с Redis (%s), повтор через 3 с", exc)
            time.sleep(3)
            continue
        if item is None:
            continue
        event = json.loads(item[1])
        try:
            with SessionLocal() as db:
                handle_event(db, event, processed_by=settings.hostname)
            log.info("Обработано событие %s компании %s", event["kind"], event["company_id"])
        except Exception:
            log.exception("Ошибка обработки, событие возвращено в очередь")
            r.rpush(QUEUE, item[1])
            time.sleep(1)


if __name__ == "__main__":
    main()
