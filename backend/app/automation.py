"""Правила автоматизации бизнес-процессов.

Каждое событие несёт уникальный идентификатор. Задача и строка журнала
event_log записываются в одной транзакции, а на event_log.event_id стоит
уникальный индекс. Поэтому повторная доставка того же события (после сбоя
воркера или возврата из очереди) не создаёт вторую задачу."""
import json
import logging
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import Deal, EventLog, Task

log = logging.getLogger("bizflow.automation")


def handle_event(db: Session, event: dict, processed_by: str) -> bool:
    """Выполняет правило. Возвращает False, если событие уже было обработано."""
    event_id = event.get("id")
    if event_id and db.scalar(select(EventLog.id).where(EventLog.event_id == event_id)):
        log.info("Событие %s уже обработано, повтор пропущен", event_id)
        return False

    kind = event["kind"]
    company_id = event["company_id"]

    if kind == "client.created":
        db.add(Task(
            company_id=company_id,
            title=f"Связаться с новым клиентом «{event['name']}»",
            due_date=date.today() + timedelta(days=1),
            source="automation",
        ))
    elif kind == "deal.won":
        deal = db.get(Deal, event["deal_id"])
        if deal is not None:
            db.add(Task(
                company_id=company_id,
                deal_id=deal.id,
                title=f"Подготовить договор и счёт по сделке «{deal.title}»",
                due_date=date.today() + timedelta(days=2),
                source="automation",
            ))
    elif kind == "deal.lost":
        # сделку могли удалить до обработки события: тогда задача не нужна
        if db.get(Deal, event["deal_id"]) is not None:
            db.add(Task(
                company_id=company_id,
                deal_id=event["deal_id"],
                title="Запросить у клиента причину отказа",
                due_date=date.today() + timedelta(days=3),
                source="automation",
            ))

    db.add(EventLog(
        event_id=event_id,
        company_id=company_id,
        kind=kind,
        payload=json.dumps(event, ensure_ascii=False),
        processed_by=processed_by,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Дубликатом считается только случай, когда запись с этим event_id уже
        # есть (то же событие одновременно обработал другой воркер). Любое другое
        # нарушение целостности передаётся дальше: воркер повторит попытку,
        # а после исчерпания попыток отправит событие в dead-список.
        if event_id and db.scalar(select(EventLog.id).where(EventLog.event_id == event_id)):
            log.info("Событие %s уже записано другим воркером", event_id)
            return False
        raise
    return True
