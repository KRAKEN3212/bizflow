from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

DealStage = Literal["new", "negotiation", "won", "lost"]
TaskStatus = Literal["open", "done"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=6, max_length=100)
    role: Literal["admin", "manager"] = "manager"


class UserOut(ORM):
    id: int
    email: str
    full_name: str
    role: str
    company_id: int


class MeOut(UserOut):
    company_name: str
    plan: str


class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    note: str | None = None


class ClientOut(ORM):
    id: int
    name: str
    email: str | None
    phone: str | None
    note: str | None
    created_at: datetime


class DealIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    amount: float = Field(ge=0, default=0)
    stage: DealStage = "new"
    client_id: int | None = None


class DealOut(ORM):
    id: int
    title: str
    amount: float
    stage: str
    client_id: int | None
    client_name: str | None = None
    created_at: datetime


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    status: TaskStatus = "open"
    due_date: date | None = None
    deal_id: int | None = None


class TaskOut(ORM):
    id: int
    title: str
    status: str
    due_date: date | None
    deal_id: int | None
    source: str
    created_at: datetime


class EventOut(ORM):
    id: int
    kind: str
    payload: str
    processed_by: str
    created_at: datetime
