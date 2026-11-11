from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import cache
from ..config import settings
from ..db import get_db
from ..events import DEAD, PROCESSING, QUEUE, get_redis
from ..models import Client, Deal, Task, User
from ..security import current_user

router = APIRouter(tags=["system"])


@router.get("/api/health")
def health(response: Response, db: Session = Depends(get_db)):
    """Проверка готовности. Используется HEALTHCHECK контейнера, балансировщиком
    и конвейером CI/CD. Поле instance показывает, какая реплика ответила.

    Без PostgreSQL реплика работать не может: ответ 503, и Traefik с Docker
    исключают её из обслуживания. Без Redis реплика остаётся рабочей: кэш
    статистики не используется, а правила автоматизации выполняются сразу в
    процессе API. Поэтому недоступный Redis даёт статус degraded с кодом 200."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    redis_ok = None
    r = get_redis()
    if r is not None:
        try:
            redis_ok = bool(r.ping())
        except Exception:
            redis_ok = False
    if not db_ok:
        response.status_code = 503
        status = "unavailable"
    else:
        status = "degraded" if redis_ok is False else "ok"
    return {
        "status": status,
        "instance": settings.hostname,
        "version": settings.version,
        "database": db_ok,
        "redis": redis_ok,
    }


@router.get("/api/stats")
def stats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cached = cache.get_stats(user.company_id)
    if cached is not None:
        return {**cached, "cache": "hit", "instance": settings.hostname}

    cid = user.company_id
    by_stage = dict(db.execute(
        select(Deal.stage, func.count()).where(Deal.company_id == cid).group_by(Deal.stage)
    ).all())
    won_sum = db.scalar(
        select(func.coalesce(func.sum(Deal.amount), 0)).where(Deal.company_id == cid, Deal.stage == "won")
    )
    pipeline_sum = db.scalar(
        select(func.coalesce(func.sum(Deal.amount), 0))
        .where(Deal.company_id == cid, Deal.stage.in_(["new", "negotiation"]))
    )
    data = {
        "clients": db.scalar(select(func.count()).select_from(Client).where(Client.company_id == cid)),
        "deals": sum(by_stage.values()),
        "deals_by_stage": by_stage,
        "won_amount": float(won_sum or 0),
        "pipeline_amount": float(pipeline_sum or 0),
        "open_tasks": db.scalar(
            select(func.count()).select_from(Task).where(Task.company_id == cid, Task.status == "open")
        ),
    }
    r = get_redis()
    if r is not None:
        try:
            data["queue_length"] = r.llen(QUEUE)
            data["queue_processing"] = r.llen(PROCESSING)
            data["queue_dead"] = r.llen(DEAD)
        except Exception:
            data["queue_length"] = None
    cache.set_stats(cid, data)
    return {**data, "cache": "miss", "instance": settings.hostname}


@router.get("/metrics", include_in_schema=False)
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
