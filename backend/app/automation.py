"""Правила автоматизации бизнес-процессов."""
import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .models import Deal, EventLog, Task


def handle_event(db: Session, event: dict, processed_by: str) -> None:
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
        db.add(Task(
            company_id=company_id,
            deal_id=event["deal_id"],
            title="Запросить у клиента причину отказа",
            due_date=date.today() + timedelta(days=3),
            source="automation",
        ))

    db.add(EventLog(
        company_id=company_id,
        kind=kind,
        payload=json.dumps(event, ensure_ascii=False),
        processed_by=processed_by,
    ))
    db.commit()
