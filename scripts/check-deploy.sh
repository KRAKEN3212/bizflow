#!/usr/bin/env bash
# Проверка результата развёртывания стека.
#   TAG=1.2.0 bash scripts/check-deploy.sh
# Завершается с ошибкой, если за TIMEOUT секунд:
#   - не все сервисы стека запустили нужное число реплик;
#   - обновление api закончилось откатом или паузой;
#   - не все реплики api работают на образе с тегом $TAG;
#   - /api/health не отвечает кодом 200 или отвечает другой версией.
# В GitHub Actions причина ошибки дополнительно выводится аннотацией.
set -euo pipefail

TAG=${TAG:?нужно задать TAG}
STACK=${STACK:-bizflow}
TIMEOUT=${TIMEOUT:-300}
URL=${URL:-http://127.0.0.1}
deadline=$((SECONDS + TIMEOUT))

fail() {
  trap - ERR
  set +e +o pipefail
  echo "ОШИБКА: $*"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    errors=$(docker service ls --format '{{.Name}}' | while read -r s; do
               docker service ps "$s" --no-trunc --format "$s: {{.Error}}" | grep -v ': $' | head -n 2
             done | tr '\n' ';' | cut -c1-900)
    echo "::error title=check-deploy::$* | ошибки задач: ${errors:-нет}"
  fi
  docker stack services "$STACK" || true
  docker service ps "${STACK}_api" --no-trunc | head -n 20 || true
  exit 1
}
trap 'fail "команда в строке $LINENO завершилась с ошибкой: $BASH_COMMAND"' ERR

while true; do
  state=$(docker service inspect "${STACK}_api" --format '{{if .UpdateStatus}}{{.UpdateStatus.State}}{{end}}')
  case "$state" in
    rollback_*|paused)
      fail "обновление api завершилось состоянием '$state': $(docker service inspect "${STACK}_api" --format '{{.UpdateStatus.Message}}')" ;;
  esac
  pending=$(docker stack services "$STACK" --format '{{.Replicas}}' | awk -F'[/ ]' '$1 != $2' | wc -l)
  want=$(docker service inspect "${STACK}_api" --format '{{.Spec.Mode.Replicated.Replicas}}')
  on_tag=$(docker service ps "${STACK}_api" --filter desired-state=running \
             --format '{{.Image}} {{.CurrentState}}' | grep -c ":${TAG}.*Running" || true)
  if [ "$pending" -eq 0 ] && [ "$on_tag" -eq "$want" ] && { [ -z "$state" ] || [ "$state" = "completed" ]; }; then
    break
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    fail "за ${TIMEOUT} с стек не пришёл в нужное состояние: сервисов с неполным числом реплик $pending, реплик api на теге $TAG: $on_tag из $want, обновление: ${state:-нет}"
  fi
  sleep 5
done

# Реплики уже запущены, но Traefik подхватывает маршруты и проверяет здоровье
# реплик с интервалом в несколько секунд, поэтому запрос повторяется до общего
# таймаута. Ответ 503 (нет базы данных) считается неуспешным.
while true; do
  code=$(curl -s -o /tmp/health.json -w '%{http_code}' --max-time 5 "$URL/api/health" || true)
  health=$(cat /tmp/health.json 2>/dev/null || true)
  if [ "$code" = "200" ] && echo "$health" | grep -q "\"version\":\"${TAG}\""; then
    break
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    fail "/api/health не ответил версией $TAG с кодом 200 (последний ответ: код $code, $health)"
  fi
  sleep 3
done
echo "$health"
echo "Развёртывание версии $TAG подтверждено"
docker stack services "$STACK"
