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

Сети: `public` (Traefik, frontend, api, мониторинг) и `backend` (internal: api, worker,
postgres, redis, prometheus). Секреты Swarm: `db_password`, `jwt_secret`, `grafana_password`.

## Структура репозитория

```
backend/                 серверная часть (FastAPI)
  app/main.py            создание приложения, метрики Prometheus
  app/routers/           auth.py (вход, пользователи), crm.py (CRUD), system.py (health, stats)
  app/models.py          модели SQLAlchemy
  app/security.py        bcrypt, JWT, проверка ролей
  app/events.py          публикация событий в Redis
  app/automation.py      правила автоматизации
  app/worker.py          фоновый воркер
  app/seed.py            тестовые данные
  tests/                 тесты pytest
  Dockerfile
frontend/                клиентская часть (HTML + JS) и конфигурация nginx
monitoring/              prometheus.yml, источник данных и дашборд Grafana
scripts/                 подготовка кластера, деплой, нагрузочный тест
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
python scripts/loadtest.py --threads 20 --seconds 60
```

Резервная копия базы:

```bash
docker exec $(docker ps -qf name=bizflow_postgres) pg_dump -U bizflow bizflow > backup.sql
```

## CI/CD

`.github/workflows/ci-cd.yml`: линтер и тесты, сборка образов и публикация в GHCR,
развёртывание на менеджер-узел по SSH. Для деплоя в репозитории нужны секреты
`SWARM_HOST`, `SWARM_USER`, `SWARM_SSH_KEY`, `GHCR_TOKEN`.

## Тесты

```bash
cd backend
pip install -r requirements-dev.txt
ruff check app tests && pytest -v
```
