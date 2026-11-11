"""Проверки очереди событий и правил автоматизации на Redis в памяти (fakeredis)."""
import json

import fakeredis
import pytest
from sqlalchemy import func, select

from app import events, worker
from app.automation import handle_event
from app.db import SessionLocal, init_schema
from app.models import Company, EventLog, Task


@pytest.fixture()
def r():
    init_schema()
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture()
def company():
    init_schema()
    with SessionLocal() as db:
        c = Company(name="Очередь")
        db.add(c)
        db.commit()
        return c.id


def _tasks(company_id):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(Task).where(Task.company_id == company_id))


def _push(r, company_id, event_id="e1"):
    event = {"id": event_id, "kind": "client.created", "company_id": company_id, "attempt": 0, "name": "Тест"}
    r.lpush(events.QUEUE, json.dumps(event, ensure_ascii=False))
    return event


def test_duplicate_event_creates_one_task(company):
    event = {"id": "dup1", "kind": "client.created", "company_id": company, "name": "Дубль"}
    with SessionLocal() as db:
        assert handle_event(db, event, "test") is True
    with SessionLocal() as db:
        assert handle_event(db, event, "test") is False
    assert _tasks(company) == 1
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(EventLog).where(EventLog.event_id == "dup1")) == 1


def test_worker_acknowledges_processed_event(r, company):
    _push(r, company, "ack1")
    assert worker.process_one(r, timeout=0.1) is True
    assert r.llen(events.QUEUE) == 0 and r.llen(events.PROCESSING) == 0
    assert _tasks(company) == 1


def test_stuck_event_is_returned_and_not_duplicated(r, company):
    _push(r, company, "crash1")
    # воркер взял событие и выполнил правило, но упал до подтверждения
    raw = events.take(r, timeout=0.1)
    with SessionLocal() as db:
        handle_event(db, json.loads(raw), "упавший воркер")
    assert r.llen(events.PROCESSING) == 1
    # пока не истёк таймаут видимости, событие остаётся у «своего» воркера
    assert events.reap(r, visibility=60) == 0
    # после таймаута сборщик возвращает его в очередь, второй воркер обрабатывает
    assert events.reap(r, now=10**10, visibility=60) == 1
    assert worker.process_one(r, timeout=0.1) is True
    assert r.llen(events.PROCESSING) == 0
    assert _tasks(company) == 1


def test_failed_event_goes_to_dead_list(r, company, monkeypatch):
    _push(r, company, "bad1")

    def boom(*args, **kwargs):
        raise ValueError("ошибка правила")

    monkeypatch.setattr(worker, "handle_event", boom)
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    for _ in range(events.MAX_ATTEMPTS):
        worker.process_one(r, timeout=0.1)
    assert r.llen(events.DEAD) == 1
    assert json.loads(r.lindex(events.DEAD, 0))["attempt"] == events.MAX_ATTEMPTS
    assert r.llen(events.QUEUE) == 0 and r.llen(events.PROCESSING) == 0
