"""Фоновый обработчик событий автоматизации.

Запускается тем же образом, что и API, но с другой командой:
    python -m app.worker
Несколько реплик воркера читают одну очередь. Порядок работы с очередью и
гарантии доставки описаны в events.py."""
import json
import logging
import signal
import time
from pathlib import Path

import redis
from sqlalchemy.exc import OperationalError

from .automation import handle_event
from .config import settings
from .db import SessionLocal, init_schema
from .events import QUEUE, ack, get_redis, reap, retry, take

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s worker: %(message)s")
log = logging.getLogger("bizflow.worker")

HEARTBEAT = Path("/tmp/worker-heartbeat")
REAP_EVERY = 30
_running = True


def _stop(*_):
    global _running
    _running = False
    log.info("Получен сигнал остановки, текущее событие будет доработано")


def process_one(r: redis.Redis, timeout: float = 2) -> bool:
    """Обработать одно событие. Возвращает False, если очередь пуста."""
    raw = take(r, timeout)
    if raw is None:
        return False
    event = json.loads(raw)
    try:
        with SessionLocal() as db:
            done = handle_event(db, event, processed_by=settings.hostname)
        ack(r, raw)
        if done:
            log.info("Обработано событие %s (%s) компании %s", event["kind"], event["id"][:8], event["company_id"])
    except OperationalError as exc:
        # база недоступна: событие не виновато, возвращаем без счёта попыток
        retry(r, raw, count_attempt=False)
        log.warning("База данных недоступна (%s), событие возвращено в очередь", exc.orig)
        time.sleep(3)
    except Exception:
        target = retry(r, raw)
        log.exception("Ошибка обработки события %s, оно перемещено в %s", event["id"][:8], target)
        time.sleep(1)
    return True


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    init_schema()
    r = get_redis()
    if r is None:
        raise SystemExit("REDIS_URL не задан, воркеру нечего читать")
    log.info("Воркер %s слушает очередь %s", settings.hostname, QUEUE)
    last_reap = 0.0
    while _running:
        # отметка жизни для HEALTHCHECK контейнера
        HEARTBEAT.touch()
        try:
            if time.time() - last_reap > REAP_EVERY:
                last_reap = time.time()
                n = reap(r)
                if n:
                    log.warning("Возвращено в очередь зависших событий: %s", n)
            process_one(r)
        except redis.RedisError as exc:
            log.warning("Нет связи с Redis (%s), повтор через 3 с", exc)
            time.sleep(3)


if __name__ == "__main__":
    main()
