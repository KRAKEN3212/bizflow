#!/usr/bin/env bash
# Сборка образов, публикация в реестр и обновление стека.
#   TAG=1.1.0 ./scripts/deploy.sh
# В конвейере CI/CD этот же порядок шагов выполняется на сервере по SSH.
set -euo pipefail
cd "$(dirname "$0")/.."

export REGISTRY=${REGISTRY:-127.0.0.1:5000}
export TAG=${TAG:-1.0.0}

if [ "${SKIP_BUILD:-0}" != "1" ]; then
  docker build --build-arg APP_VERSION="$TAG" -t "$REGISTRY/bizflow-api:$TAG" backend
  docker build -t "$REGISTRY/bizflow-frontend:$TAG" frontend
  docker push "$REGISTRY/bizflow-api:$TAG"
  docker push "$REGISTRY/bizflow-frontend:$TAG"
fi

docker stack deploy --with-registry-auth --prune -c docker-stack.yml bizflow
docker stack services bizflow
