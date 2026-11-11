import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, email, company="ООО Тест"):
    r = client.post("/api/auth/register", json={
        "company_name": company, "full_name": "Тестовый Пользователь",
        "email": email, "password": "secret123",
    })
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["database"] is True
    assert "X-Served-By" in r.headers


def test_auth_required(client):
    assert client.get("/api/clients").status_code == 401


def test_login(client):
    _register(client, "login@test.ru")
    ok = client.post("/api/auth/login", json={"email": "login@test.ru", "password": "secret123"})
    bad = client.post("/api/auth/login", json={"email": "login@test.ru", "password": "wrong"})
    assert ok.status_code == 200 and bad.status_code == 401


def test_client_crud_and_automation(client):
    h = _register(client, "crud@test.ru")
    r = client.post("/api/clients", json={"name": "ООО Ромашка", "email": "r@r.ru"}, headers=h)
    assert r.status_code == 201
    cid = r.json()["id"]

    r = client.put(f"/api/clients/{cid}", json={"name": "ООО Ромашка+", "phone": "123"}, headers=h)
    assert r.json()["name"] == "ООО Ромашка+"

    # без Redis правило срабатывает синхронно: появилась задача «связаться»
    tasks = client.get("/api/tasks", headers=h).json()
    assert any(t["source"] == "automation" for t in tasks)

    assert client.delete(f"/api/clients/{cid}", headers=h).status_code == 204
    assert client.get("/api/clients", headers=h).json() == []


def test_deal_won_creates_task(client):
    h = _register(client, "deal@test.ru")
    d = client.post("/api/deals", json={"title": "Внедрение", "amount": 1000}, headers=h).json()
    client.put(f"/api/deals/{d['id']}", json={"title": "Внедрение", "amount": 1000, "stage": "won"}, headers=h)
    tasks = client.get("/api/tasks", headers=h).json()
    assert any(t["deal_id"] == d["id"] and t["source"] == "automation" for t in tasks)
    stats = client.get("/api/stats", headers=h).json()
    assert stats["won_amount"] == 1000


def test_deal_created_as_won_creates_task(client):
    h = _register(client, "wonnow@test.ru")
    d = client.post("/api/deals", json={"title": "Сразу успешно", "amount": 500, "stage": "won"}, headers=h).json()
    tasks = client.get("/api/tasks", headers=h).json()
    assert any(t["deal_id"] == d["id"] and t["source"] == "automation" for t in tasks)


def test_health_returns_503_without_database(client):
    from app.db import get_db
    from app.main import app as fastapi_app

    class BrokenSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("нет соединения с БД")

    fastapi_app.dependency_overrides[get_db] = lambda: BrokenSession()
    try:
        r = client.get("/api/health")
    finally:
        fastapi_app.dependency_overrides.clear()
    assert r.status_code == 503
    assert r.json()["status"] == "unavailable"


def test_tenant_isolation(client):
    a = _register(client, "a@tenant.ru", "Компания А")
    b = _register(client, "b@tenant.ru", "Компания Б")
    cid = client.post("/api/clients", json={"name": "Клиент А"}, headers=a).json()["id"]
    assert client.get("/api/clients", headers=b).json() == []
    assert client.delete(f"/api/clients/{cid}", headers=b).status_code == 404
