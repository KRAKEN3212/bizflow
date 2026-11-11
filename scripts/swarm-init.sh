#!/usr/bin/env bash
# Первичная подготовка менеджер-узла Swarm:
# инициализация кластера, метки узла, секреты и локальный реестр образов.
set -euo pipefail

if [ "$(docker info --format '{{.Swarm.LocalNodeState}}')" != "active" ]; then
  docker swarm init ${ADVERTISE_ADDR:+--advertise-addr "$ADVERTISE_ADDR"}
fi

NODE_ID=$(docker info --format '{{.Swarm.NodeID}}')
docker node update --label-add tier=main "$NODE_ID" >/dev/null

# Секреты создаются один раз. Значения генерируются случайно и нигде,
# кроме зашифрованного хранилища Raft, не сохраняются.
create_secret() {
  if ! docker secret inspect "$1" >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '\n' | docker secret create "$1" - >/dev/null
    echo "создан секрет $1"
  fi
}
create_secret db_password
create_secret jwt_secret
if ! docker secret inspect grafana_password >/dev/null 2>&1; then
  printf '%s' "${GRAFANA_PASSWORD:-bizflow-admin}" | docker secret create grafana_password - >/dev/null
  echo "создан секрет grafana_password"
fi

# Реестр образов для узлов кластера. Публикуется через ingress, поэтому
# адрес 127.0.0.1:5000 работает на любом узле Swarm.
if ! docker service inspect registry >/dev/null 2>&1; then
  docker service create --detach --name registry --publish 5000:5000 \
    --constraint node.role==manager \
    --mount type=volume,source=registry-data,target=/var/lib/registry \
    registry:2
fi

echo "Токен для подключения рабочих узлов:"
docker swarm join-token worker
