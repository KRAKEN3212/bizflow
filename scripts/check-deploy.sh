#!/usr/bin/env bash
# Проверка результата развёртывания стека.
#   TAG=1.2.0 bash scripts/check-deploy.sh
# Завершается с ошибкой, если за TIMEOUT секунд:
#   - не все сервисы стека запустили нужное число реплик;
#   - обновление api закончилось откатом или паузой;
#   - не все реплики api работают на образе с тегом $TAG;
#   - /api/health не отвечает кодом 200 или отвечает другой версией.
set -euo pipefail

TAG=${TAG:?нужно задать TAG}
STACK=${STACK:-bizflow}
TIMEOUT=${TIMEOUT:-300}
URL=${URL:-http://127.0.0.1}
deadline=$((SECONDS + TIMEOUT))

while true; do
  state=$(docker service inspect "${STACK}_api" --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}')
  case "$state" in
    rollback_*|paused)
      echo "ОШИБКА: обновление api завершилось состоянием '$state'"
      docker service inspect "${STACK}_api" --format '{{.UpdateStatus.Message}}'
      exit 1 ;;
  esac
  pending=$(docker stack services "$STACK" --format '{{.Replicas}}' | awk -F'[/ ]' '$1 != $2' | wc -l)
  want=$(docker service inspect "${STACK}_api" --format '{{.Spec.Mode.Replicated.Replicas}}')
  on_tag=$(docker service ps "${STACK}_api" --filter desired-state=running \
             --format '{{.Image}} {{.CurrentState}}' | grep -c ":${TAG}.*Running" || true)
  if [ "$pending" -eq 0 ] && [ "$on_tag" -eq "$want" ] && { [ -z "$state" ] || [ "$state" = "completed" ]; }; then
    break
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "ОШИБКА: за ${TIMEOUT} с стек не пришёл в нужное состояние"
    echo "  сервисов с неполным числом реплик: $pending; реплик api на теге $TAG: $on_tag из $want; обновление: ${state:-нет}"
    docker stack services "$STACK"
    docker service ps "${STACK}_api" --no-trunc | head -20
    exit 1
  fi
  sleep 5
done

# -f: ответ 503 (нет базы данных) считается ошибкой
health=$(curl -fsS --retry 5 --retry-delay 3 --retry-all-errors "$URL/api/health")
echo "$health"
if ! echo "$health" | grep -q "\"version\":\"${TAG}\""; then
  echo "ОШИБКА: /api/health отвечает не версией $TAG"
  exit 1
fi
echo "Развёртывание версии $TAG подтверждено"
docker stack services "$STACK"
