"""Дымовой тест развёрнутой платформы (только стандартная библиотека).

    python scripts/smoke.py --url http://127.0.0.1

Проверяет вход, CRUD клиента, срабатывание правил автоматизации через
очередь и воркер, отказ в доступе без токена. Код возврата 1 при ошибке."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def call(base, method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.headers.get("X-Served-By")
    except urllib.error.HTTPError as exc:
        return exc.code, None, exc.headers.get("X-Served-By")


def wait_task(base, token, predicate, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        _, tasks, _ = call(base, "GET", "/api/tasks", token=token)
        found = [t for t in tasks if predicate(t)]
        if found:
            return found[0]
        time.sleep(1)
    return None


def processed_event(base, token, predicate):
    """Запись журнала автоматизации (/api/events) для события; в поле processed_by
    имя реплики воркера или «<реплика api> (inline)» для резервной обработки без Redis."""
    _, events, _ = call(base, "GET", "/api/events", token=token)
    found = [e for e in events or [] if predicate(e)]
    return found[0] if found else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1")
    base = ap.parse_args().url
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"[{'OK' if ok else 'FAIL'}] {name}{' — ' + detail if detail else ''}")

    status, health, inst = call(base, "GET", "/api/health")
    check("health отвечает 200", status == 200, f"{health} от {inst}")

    status, _, _ = call(base, "GET", "/api/clients")
    check("без токена доступ запрещён", status == 401, f"код {status}")

    status, body, _ = call(base, "POST", "/api/auth/login", {"email": "admin@bizflow-demo.ru", "password": "demo12345"})
    check("вход демо-пользователя", status == 200)
    if status != 200:
        return 1
    token = body["access_token"]

    name = f"Дымовой тест {int(time.time())}"
    status, client, _ = call(base, "POST", "/api/clients", {"name": name}, token)
    check("создание клиента", status == 201)
    task = wait_task(base, token, lambda t: t["source"] == "automation" and name in t["title"])
    check("правило создало задачу по событию client.created", task is not None, task["title"] if task else "")
    ev = processed_event(base, token, lambda e: e["kind"] == "client.created" and name in e["payload"])
    check("событие client.created обработал воркер из очереди, а не резервный обработчик API",
          ev is not None and not ev["processed_by"].endswith("(inline)"), ev["processed_by"] if ev else "события нет в журнале")

    status, deal, _ = call(base, "POST", "/api/deals", {"title": name, "amount": 1000, "stage": "won", "client_id": client["id"]}, token)
    check("создание сделки сразу со статусом «Успешно»", status == 201)
    task = wait_task(base, token, lambda t: t["source"] == "automation" and t["deal_id"] == deal["id"])
    check("правило создало задачу по событию deal.won", task is not None, task["title"] if task else "")
    ev = processed_event(base, token, lambda e: e["kind"] == "deal.won" and f'"deal_id": {deal["id"]}' in e["payload"])
    check("событие deal.won обработал воркер из очереди, а не резервный обработчик API",
          ev is not None and not ev["processed_by"].endswith("(inline)"), ev["processed_by"] if ev else "события нет в журнале")

    status, _, _ = call(base, "DELETE", f"/api/deals/{deal['id']}", token=token)
    status2, _, _ = call(base, "DELETE", f"/api/clients/{client['id']}", token=token)
    check("удаление сделки и клиента", status == 204 and status2 == 204)

    instances = {call(base, "GET", "/api/health")[2] for _ in range(12)}
    check("запросы распределяются между репликами", len(instances) > 1, ", ".join(sorted(map(str, instances))))

    print(f"Итого: {sum(checks)} из {len(checks)} проверок пройдено")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
