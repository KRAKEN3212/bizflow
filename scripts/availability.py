"""Непрерывное измерение доступности API (например, во время обновления).

    python scripts/availability.py --seconds 120 --interval 0.05 --log avail.log

Один поток каждые INTERVAL секунд запрашивает /api/clients с токеном
демо-пользователя. Любой ответ, кроме 200, и любая сетевая ошибка или таймаут
считаются отказом. В конце выводится число запросов, отказов, самый длинный
непрерывный интервал недоступности и версии, ответившие за время измерения.
Подробный журнал каждого отказа пишется в файл --log."""
import argparse
import collections
import json
import time
import urllib.error
import urllib.request


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--interval", type=float, default=0.05)
    ap.add_argument("--log", default="availability.log")
    args = ap.parse_args()

    body = json.dumps({"email": "admin@bizflow-demo.ru", "password": "demo12345"}).encode()
    req = urllib.request.Request(args.url + "/api/auth/login", data=body, headers={"Content-Type": "application/json"})
    token = json.load(urllib.request.urlopen(req, timeout=10))["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    total = failed = 0
    outage_start = None
    longest = 0.0
    versions = collections.Counter()
    started = time.time()
    with open(args.log, "w", encoding="utf-8") as log:
        log.write(f"# старт {time.strftime('%Y-%m-%d %H:%M:%S')}, интервал {args.interval} с\n")
        while time.time() - started < args.seconds:
            t0 = time.time()
            ok, detail = False, ""
            try:
                with urllib.request.urlopen(urllib.request.Request(args.url + "/api/clients", headers=auth), timeout=3) as r:
                    r.read()
                    ok = r.status == 200
                    detail = str(r.status)
                with urllib.request.urlopen(args.url + "/api/health", timeout=3) as r:
                    versions[json.load(r)["version"]] += 1
            except urllib.error.HTTPError as exc:
                detail = f"HTTP {exc.code}"
            except Exception as exc:
                detail = type(exc).__name__
            total += 1
            now = time.time()
            if ok:
                if outage_start is not None:
                    longest = max(longest, now - outage_start)
                    outage_start = None
            else:
                failed += 1
                outage_start = outage_start or t0
                log.write(f"{time.strftime('%H:%M:%S', time.localtime(t0))}.{int(t0 % 1 * 1000):03d} отказ: {detail}\n")
            time.sleep(max(0.0, args.interval - (time.time() - t0)))
        if outage_start is not None:
            longest = max(longest, time.time() - outage_start)
        summary = (f"Запросов: {total}, отказов: {failed} ({failed / max(total, 1) * 100:.2f} %), "
                   f"самый длинный интервал недоступности: {longest:.2f} с\n"
                   f"Ответившие версии: {dict(versions)}")
        log.write("# " + summary.replace("\n", "\n# ") + "\n")
    print(f"Длительность измерения: {time.time() - started:.0f} с, интервал опроса {args.interval} с")
    print(summary)


if __name__ == "__main__":
    main()
