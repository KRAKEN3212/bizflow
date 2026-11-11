"""Заполнение базы тестовыми данными.

    docker exec -it <контейнер api> python -m app.seed

Повторный запуск ничего не дублирует: если демо-компания уже есть, скрипт выходит."""
import random
from datetime import date, timedelta

from sqlalchemy import select

from .db import SessionLocal, init_schema
from .models import Client, Company, Deal, Task, User
from .security import hash_password

DEMO_EMAIL = "admin@bizflow-demo.ru"

CLIENTS = [
    ("ООО «Северный ветер»", "info@sev-veter.ru", "+7 495 120-44-10"),
    ("ИП Карпов А. В.", "karpov@mail.ru", "+7 916 300-12-87"),
    ("АО «ТехноСнаб»", "zakupki@tehnosnab.ru", "+7 812 640-22-05"),
    ("ООО «Зелёная линия»", "office@green-line.ru", "+7 343 211-09-90"),
    ("ООО «Альфа Логистик»", "sales@alfalog.ru", "+7 495 777-31-31"),
    ("Кафе «Пирожковая №1»", "pirozhki1@yandex.ru", "+7 903 555-08-17"),
    ("ООО «МедТрейд»", "medtrade@medtrade.ru", "+7 861 290-45-60"),
    ("ИП Соколова Е. Н.", "sokolova.en@gmail.com", "+7 926 418-73-02"),
    ("ООО «СтройМастер»", "info@stroymaster.ru", "+7 383 335-17-44"),
    ("АНО «Центр развития»", "cr@centr-razvitiya.ru", "+7 495 980-62-11"),
]

DEALS = [
    ("Внедрение CRM на 15 рабочих мест", 450000, "won"),
    ("Годовая подписка, тариф «Бизнес»", 180000, "negotiation"),
    ("Настройка интеграции с 1С", 95000, "new"),
    ("Автоматизация склада", 320000, "negotiation"),
    ("Обучение сотрудников", 40000, "won"),
    ("Подписка на 6 месяцев", 60000, "lost"),
    ("Доработка отчётов", 75000, "new"),
    ("Перенос данных из Excel", 25000, "won"),
    ("Модуль онлайн-записи", 110000, "new"),
    ("Расширение тарифа до 50 пользователей", 260000, "negotiation"),
    ("Интеграция с телефонией", 55000, "lost"),
    ("Пилотный проект на 1 месяц", 15000, "won"),
]

TASKS = [
    "Подготовить коммерческое предложение",
    "Провести демонстрацию платформы",
    "Согласовать график внедрения",
    "Выставить счёт",
    "Созвониться с бухгалтерией клиента",
    "Отправить инструкцию по подключению",
]


def run() -> None:
    init_schema()
    rnd = random.Random(2026)
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == DEMO_EMAIL)):
            print("Тестовые данные уже загружены")
            return
        company = Company(name="ООО «Ромашка Софт»", plan="business")
        db.add(company)
        db.flush()
        db.add_all([
            User(company_id=company.id, email=DEMO_EMAIL, full_name="Администратор демо",
                 password_hash=hash_password("demo12345"), role="admin"),
            User(company_id=company.id, email="manager@bizflow-demo.ru", full_name="Иванова Мария",
                 password_hash=hash_password("demo12345"), role="manager"),
        ])
        clients = [Client(company_id=company.id, name=n, email=e, phone=p) for n, e, p in CLIENTS]
        db.add_all(clients)
        db.flush()
        deals = []
        for title, amount, stage in DEALS:
            deal = Deal(company_id=company.id, client_id=rnd.choice(clients).id,
                        title=title, amount=amount, stage=stage)
            deals.append(deal)
        db.add_all(deals)
        db.flush()
        for i, title in enumerate(TASKS):
            db.add(Task(company_id=company.id, deal_id=deals[i].id, title=title,
                        status="done" if i % 3 == 0 else "open",
                        due_date=date.today() + timedelta(days=i - 1)))
        # Второй арендатор нужен, чтобы проверить изоляцию данных компаний.
        other = Company(name="ООО «Вектор»", plan="start")
        db.add(other)
        db.flush()
        db.add(User(company_id=other.id, email="admin@vector-demo.ru", full_name="Петров Олег",
                    password_hash=hash_password("demo12345"), role="admin"))
        db.add(Client(company_id=other.id, name="ООО «Чужой клиент»"))
        db.commit()
    print(f"Загружено: 2 компании, {len(CLIENTS) + 1} клиентов, {len(DEALS)} сделок, {len(TASKS)} задач")
    print(f"Вход: {DEMO_EMAIL} / demo12345")


if __name__ == "__main__":
    run()
