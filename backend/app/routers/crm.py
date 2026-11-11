"""CRUD-операции над клиентами, сделками и задачами.

Каждый запрос фильтруется по company_id текущего пользователя, так что
данные разных арендаторов в общей базе не пересекаются."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import cache
from ..db import get_db
from ..events import publish
from ..models import Client, Deal, EventLog, Task, User
from ..schemas import ClientIn, ClientOut, DealIn, DealOut, EventOut, TaskIn, TaskOut
from ..security import current_user

router = APIRouter(prefix="/api", tags=["crm"])


def _own(db: Session, model, obj_id: int, user: User):
    obj = db.get(model, obj_id)
    if obj is None or obj.company_id != user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    return obj


def _check_client(db: Session, client_id: int | None, user: User) -> None:
    if client_id is not None:
        _own(db, Client, client_id, user)


def _deal_out(deal: Deal) -> DealOut:
    out = DealOut.model_validate(deal)
    out.client_name = deal.client.name if deal.client else None
    return out


# ---------- клиенты ----------

@router.get("/clients", response_model=list[ClientOut])
def list_clients(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Client).where(Client.company_id == user.company_id)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Client.name.ilike(like), Client.email.ilike(like), Client.phone.ilike(like)))
    return db.scalars(stmt.order_by(Client.id.desc())).all()


@router.post("/clients", response_model=ClientOut, status_code=201)
def create_client(data: ClientIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    client = Client(company_id=user.company_id, **data.model_dump())
    db.add(client)
    db.commit()
    cache.invalidate_stats(user.company_id)
    publish("client.created", user.company_id, client_id=client.id, name=client.name)
    return client


@router.put("/clients/{client_id}", response_model=ClientOut)
def update_client(client_id: int, data: ClientIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    client = _own(db, Client, client_id, user)
    for key, value in data.model_dump().items():
        setattr(client, key, value)
    db.commit()
    return client


@router.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, Client, client_id, user))
    db.commit()
    cache.invalidate_stats(user.company_id)
    return Response(status_code=204)


# ---------- сделки ----------

@router.get("/deals", response_model=list[DealOut])
def list_deals(stage: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Deal).where(Deal.company_id == user.company_id)
    if stage:
        stmt = stmt.where(Deal.stage == stage)
    return [_deal_out(d) for d in db.scalars(stmt.order_by(Deal.id.desc())).all()]


@router.post("/deals", response_model=DealOut, status_code=201)
def create_deal(data: DealIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _check_client(db, data.client_id, user)
    deal = Deal(company_id=user.company_id, **data.model_dump())
    db.add(deal)
    db.commit()
    cache.invalidate_stats(user.company_id)
    # сделка может быть заведена сразу закрытой — правило срабатывает и в этом случае
    if deal.stage in ("won", "lost"):
        publish(f"deal.{deal.stage}", user.company_id, deal_id=deal.id)
    return _deal_out(deal)


@router.put("/deals/{deal_id}", response_model=DealOut)
def update_deal(deal_id: int, data: DealIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    deal = _own(db, Deal, deal_id, user)
    _check_client(db, data.client_id, user)
    old_stage = deal.stage
    for key, value in data.model_dump().items():
        setattr(deal, key, value)
    db.commit()
    cache.invalidate_stats(user.company_id)
    if old_stage != deal.stage and deal.stage in ("won", "lost"):
        publish(f"deal.{deal.stage}", user.company_id, deal_id=deal.id)
    return _deal_out(deal)


@router.delete("/deals/{deal_id}", status_code=204)
def delete_deal(deal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, Deal, deal_id, user))
    db.commit()
    cache.invalidate_stats(user.company_id)
    return Response(status_code=204)


# ---------- задачи ----------

@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(status_: str | None = Query(None, alias="status"), user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Task).where(Task.company_id == user.company_id)
    if status_:
        stmt = stmt.where(Task.status == status_)
    return db.scalars(stmt.order_by(Task.status, Task.due_date, Task.id.desc())).all()


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(data: TaskIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if data.deal_id is not None:
        _own(db, Deal, data.deal_id, user)
    task = Task(company_id=user.company_id, **data.model_dump())
    db.add(task)
    db.commit()
    cache.invalidate_stats(user.company_id)
    return task


@router.put("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, data: TaskIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    task = _own(db, Task, task_id, user)
    if data.deal_id is not None:
        _own(db, Deal, data.deal_id, user)
    for key, value in data.model_dump().items():
        setattr(task, key, value)
    db.commit()
    cache.invalidate_stats(user.company_id)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, Task, task_id, user))
    db.commit()
    cache.invalidate_stats(user.company_id)
    return Response(status_code=204)


# ---------- журнал автоматизации ----------

@router.get("/events", response_model=list[EventOut])
def list_events(user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = (select(EventLog).where(EventLog.company_id == user.company_id)
            .order_by(EventLog.id.desc()).limit(50))
    return db.scalars(stmt).all()
