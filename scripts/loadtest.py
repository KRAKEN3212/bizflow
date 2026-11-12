"""Простой нагрузочный тест BizFlow без сторонних библиотек.

    python scripts/loadtest.py --url http://127.0.0.1 --threads 20 --seconds 60
    python scripts/loadtest.py --ci --max-error-rate 0.01   # режим проверки для CI

Скрипт входит под демо-пользователем, затем несколько потоков параллельно
запрашивают сводку, списки клиентов и сделок. В конце выводится число
запросов, ошибок, перцентили времени ответа и распределение запросов
по репликам API (по заголовку X-Served-By).

Без флага --ci скрипт только измеряет и всегда завершается с кодом 0: так он
используется в экспериментах с отключением узла, где ошибки ожидаемы.
С флагом --ci скрипт завершается с кодом 1, если не было ни одного успешного
запроса или доля ошибок превысила --max-error-rate."""
import argparse
import sys
import collections
import json
import statistics
import threading
import time
import urllib.error
import urllib.request

PATHS = ["/api/stats", "/api/clients", "/api/deals", "/api/tasks", "/api/health"]


def login(base: str) -> str:
    body = json.dumps({"email": "admin@bizflow-demo.ru", "password": "demo12345"}).encode()
    req = urllib.request.Request(base + "/api/auth/login", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)["access_token"]


def check(ok: int, failed: int, max_error_rate: float) -> list[str]:
    """Условия режима --ci; возвращает список нарушений (пустой, если всё в порядке)."""
    problems = []
    if ok == 0:
        problems.append("нет ни одного успешного запроса")
    total = ok + failed
    rate = failed / total if total else 1.0
    if rate > max_error_rate:
        problems.append(f"доля ошибок {rate * 100:.2f} % больше допустимой {max_error_rate * 100:.2f} %")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1")
    ap.add_argument("--threads", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--ci", action="store_true",
                    help="завершиться с кодом 1 при превышении доли ошибок или без успешных запросов")
    ap.add_argument("--max-error-rate", type=float, default=0.01,
                    help="допустимая доля ошибок в режиме --ci (по умолчанию 0.01, то есть 1 %%)")
    args = ap.parse_args()

    token = login(args.url)
    stop_at = time.time() + args.seconds
    lock = threading.Lock()
    latencies: list[float] = []
    by_instance: collections.Counter = collections.Counter()
    errors = collections.Counter()

    def run(n: int) -> None:
        i = n
        while time.time() < stop_at:
            path = PATHS[i % len(PATHS)]
            i += 1
            req = urllib.request.Request(args.url + path, headers={"Authorization": f"Bearer {token}"})
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    resp.read()
                    inst = resp.headers.get("X-Served-By", "?")
                dt = time.perf_counter() - t0
                with lock:
                    latencies.append(dt)
                    by_instance[inst] += 1
            except urllib.error.HTTPError as exc:
                with lock:
                    errors[str(exc.code)] += 1
            except Exception as exc:  # обрыв соединения, таймаут
                with lock:
                    errors[type(exc).__name__] += 1

    threads = [threading.Thread(target=run, args=(k,)) for k in range(args.threads)]
    started = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - started

    total = len(latencies)
    print(f"Длительность: {elapsed:.0f} с, потоков: {args.threads}")
    print(f"Успешных запросов: {total}, ошибок: {sum(errors.values())} {dict(errors) if errors else ''}")
    if total:
        q = statistics.quantiles(latencies, n=100)
        print(f"Пропускная способность: {total / elapsed:.1f} запр/с")
        print(f"Время ответа, мс: медиана {q[49] * 1000:.1f}, p95 {q[94] * 1000:.1f}, p99 {q[98] * 1000:.1f}")
    print("Распределение по репликам API:")
    for inst, n in sorted(by_instance.items()):
        print(f"  {inst:<22} {n:>7}  ({n / max(total, 1) * 100:.1f} %)")

    if not args.ci:
        return 0
    problems = check(total, sum(errors.values()), args.max_error_rate)
    if problems:
        print("ПРОВЕРКА НЕ ПРОЙДЕНА: " + "; ".join(problems))
        return 1
    print(f"Проверка пройдена: доля ошибок не больше {args.max_error_rate * 100:.2f} %")
    return 0


if __name__ == "__main__":
    sys.exit(main())
