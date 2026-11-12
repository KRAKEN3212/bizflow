# BizFlow

Учебная SaaS-платформа для автоматизации бизнеса: клиенты, сделки, задачи и фоновые
правила автоматизации. Проект показывает, как настроить сервисы для горизонтального
масштабирования в кластере Docker Swarm.

## Состав

| Сервис      | Образ                        | Назначение                                        | Реплики |
|-------------|------------------------------|---------------------------------------------------|---------|
| traefik     | traefik:v3.6                 | точка входа :80, балансировка, панель :8081       | 1       |
| frontend    | bizflow-frontend             | nginx со статикой клиентского приложения          | 2       |
| api         | bizflow-api                  | REST API на FastAPI, JWT, метрики `/metrics`      | 3       |
| worker      | bizflow-api (`app.worker`)   | обработка очереди событий, правила автоматизации  | 2       |
| postgres    | postgres:16-alpine           | основная база данных                              | 1       |
| redis       | redis:7-alpine               | кэш статистики и очередь событий                  | 1       |
| prometheus  | prom/prometheus:v2.53.0      | сбор метрик :9090                                 | 1       |
| grafana     | grafana/grafana:11.1.0       | дашборд :3000                                     | 1       |

Сети: `public` (Traefik, frontend, api, Prometheus, Grafana) и `backend` с флагом `internal`
(api, worker, postgres, redis, Prometheus). К обеим сетям подключены только api и Prometheus.
Опубликованные порты: 80 и 8081 (Traefik), 3000 (Grafana), 9090 (Prometheus), 5000 (реестр).
Секреты Swarm: `db_password`, `jwt_secret`, `grafana_password`.

## Проверка готовности и очередь событий

`GET /api/health` отвечает 200, если реплика может работать, и 503, если недоступен
PostgreSQL. Код 503 исключает реплику из балансировки Traefik и делает контейнер
unhealthy. Недоступный Redis даёт статус `degraded` с кодом 200: кэш статистики не
используется, правила автоматизации выполняются сразу в процессе API.

Очередь построена по схеме «надёжной очереди» Redis: воркер забирает событие командой
BLMOVE в список `bizflow:processing` и удаляет его оттуда только после записи в базу.
Зависшие события (воркер упал) через 60 секунд возвращаются в очередь, после пяти
неудачных попыток событие попадает в `bizflow:dead`. Доставка выполняется «хотя бы
один раз»; повтор не создаёт дубликатов, потому что у каждого события есть
идентификатор с уникальным индексом в таблице `event_log`. Другие ошибки целостности
базы данных дубликатом не считаются: событие возвращается в очередь для повторной попытки.

Ограничения: событие отправляется в Redis после фиксации транзакции, и при падении
реплики API между этими действиями оно теряется (transactional outbox не реализован);
Redis сохраняет журнал AOF раз в секунду, поэтому при аварии самого Redis могут
пропасть события последней секунды. Redis использует политику `volatile-lru`:
вытесняются только ключи кэша со сроком жизни, списки очереди не вытесняются.

## Структура репозитория

```
backend/                 серверная часть (FastAPI)
  app/main.py            создание приложения, метрики Prometheus
  app/routers/           auth.py (вход, пользователи), crm.py (CRUD), system.py (health, stats)
  app/models.py          модели SQLAlchemy
  app/security.py        bcrypt, JWT, проверка ролей
  app/events.py          очередь событий в Redis (публикация, взятие, подтверждение, возврат)
  app/automation.py      правила автоматизации
  app/worker.py          фоновый воркер
  app/seed.py            тестовые данные
  tests/                 тесты pytest
  Dockerfile
frontend/                клиентская часть (HTML + JS) и конфигурация nginx
monitoring/              prometheus.yml, источник данных и дашборд Grafana
scripts/                 подготовка кластера, деплой и его проверка, дымовой и нагрузочный тесты,
                         измерение доступности
docker-compose.yml       локальная разработка на одной машине
docker-stack.yml         описание стека для Docker Swarm
.github/workflows/       конвейер CI/CD
```

## Локальный запуск без кластера

```bash
docker compose up --build
docker compose exec api python -m app.seed
```

Приложение: http://localhost:8000, вход `admin@bizflow-demo.ru` / `demo12345`.

## Развёртывание в Docker Swarm

На менеджер-узле:

```bash
bash scripts/swarm-init.sh          # swarm init, метки, секреты, реестр образов
TAG=1.0.0 bash scripts/deploy.sh    # сборка, push в реестр, docker stack deploy
docker exec $(docker ps -qf name=bizflow_api | head -1) python -m app.seed
```

Для учебного стенда на одном компьютере `scripts/local-cluster.sh` создаёт три узла
в контейнерах `docker:dind` и выполняет подготовку кластера.

Адреса: приложение http://127.0.0.1, панель Traefik http://127.0.0.1:8081,
Prometheus http://127.0.0.1:9090, Grafana http://127.0.0.1:3000 (admin / пароль из
секрета `grafana_password`).

## Администрирование

```bash
docker service scale bizflow_api=6                 # масштабирование
TAG=1.1.0 bash scripts/deploy.sh                   # обновление по одной реплике
docker service rollback bizflow_api                # ручной откат
docker node update --availability drain worker-1   # вывод узла на обслуживание
docker service logs -f bizflow_worker              # журналы
python scripts/loadtest.py --threads 20 --seconds 60   # нагрузка, только измерение
python scripts/loadtest.py --ci --max-error-rate 0.01  # код 1 при ошибках > 1 % или без успешных
python scripts/availability.py --seconds 120      # зонд доступности (фиксирует неуспешные проверки)
TAG=1.2.0 bash scripts/check-deploy.sh             # проверка результата деплоя
python scripts/smoke.py                            # дымовой тест
bash scripts/rotate-db-password.sh                 # смена пароля БД: секрет + ALTER USER
```

Резервная копия базы:

```bash
docker exec $(docker ps -qf name=bizflow_postgres) pg_dump -U bizflow bizflow > backup.sql
```

## CI/CD

`.github/workflows/ci-cd.yml`:

1. `test` — ruff, тесты pytest, проверка синтаксиса `docker-stack.yml`;
2. `build` — сборка образов и публикация в GHCR с тегом `1.0.<номер запуска>-<sha>`;
3. `cloud-test` — временный кластер Swarm на облачной виртуальной машине GitHub Actions:
   развёртывание стека из опубликованных образов, `check-deploy.sh`, тестовые данные,
   дымовой тест, масштабирование до пяти реплик и короткая нагрузка;
4. `deploy` — обновление стека на постоянном сервере по SSH и `check-deploy.sh`.
   Выполняется, только если в репозитории заданы секреты `SWARM_HOST`, `SWARM_USER`,
   `SWARM_SSH_KEY`, `GHCR_TOKEN`; постоянного сервера у проекта пока нет, поэтому
   этот этап пропускается.

## Тесты

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests && pytest -v
```
