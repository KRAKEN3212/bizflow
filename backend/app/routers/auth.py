from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Company, User
from ..schemas import LoginIn, MeOut, RegisterIn, TokenOut, UserIn, UserOut
from ..security import admin_only, create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


@router.post("/auth/register", response_model=TokenOut, status_code=201)
def register(data: RegisterIn, db: Session = Depends(get_db)):
    """Регистрация новой компании-арендатора и её администратора."""
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким e-mail уже есть")
    company = Company(name=data.company_name)
    db.add(company)
    db.flush()
    user = User(
        company_id=company.id,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role="admin",
    )
    db.add(user)
    db.commit()
    return TokenOut(access_token=create_token(user))


@router.post("/auth/login", response_model=TokenOut)
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == data.email))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный e-mail или пароль")
    return TokenOut(access_token=create_token(user))


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return MeOut(
        id=user.id, email=user.email, full_name=user.full_name, role=user.role,
        company_id=user.company_id, company_name=user.company.name, plan=user.company.plan,
    )


@router.get("/users", response_model=list[UserOut])
def list_users(user: User = Depends(admin_only), db: Session = Depends(get_db)):
    return db.scalars(select(User).where(User.company_id == user.company_id).order_by(User.id)).all()


@router.post("/users", response_model=UserOut, status_code=201)
def add_user(data: UserIn, user: User = Depends(admin_only), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == data.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким e-mail уже есть")
    new_user = User(
        company_id=user.company_id,
        email=data.email,
        full_name=data.full_name,
        password_hash=hash_password(data.password),
        role=data.role,
    )
    db.add(new_user)
    db.commit()
    return new_user
