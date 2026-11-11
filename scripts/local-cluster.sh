#!/usr/bin/env bash
# Учебный стенд: три узла Swarm в контейнерах docker:dind на одном компьютере.
# Каждый контейнер играет роль отдельного сервера со своим Docker Engine.
# Порты публикуются только на 127.0.0.1, Docker API узлов наружу не открывается.
#
#   bash scripts/local-cluster.sh          # создать кластер и скопировать проект
#   docker exec -it swarm-manager sh       # дальше работа идёт на менеджер-узле
set -euo pipefail
export MSYS_NO_PATHCONV=1   # для Git Bash в Windows

# Адреса узлов закреплены: без этого после перезапуска Docker контейнеры
# получают IP в другом порядке и рабочие узлы теряют менеджера.
docker network inspect swarm-lab >/dev/null 2>&1 || docker network create --subnet 172.20.0.0/24 swarm-lab >/dev/null
MANAGER_IP=172.20.0.2

docker run -d --privileged --name swarm-manager --hostname manager --network swarm-lab --ip "$MANAGER_IP" \
  -e DOCKER_TLS_CERTDIR= --restart unless-stopped \
  -p 127.0.0.1:80:80 -p 127.0.0.1:3000:3000 -p 127.0.0.1:9090:9090 -p 127.0.0.1:8081:8081 \
  docker:29-dind >/dev/null
for n in 1 2; do
  docker run -d --privileged --name "swarm-worker-$n" --hostname "worker-$n" --network swarm-lab --ip "172.20.0.$((n + 2))" \
    -e DOCKER_TLS_CERTDIR= --restart unless-stopped docker:29-dind >/dev/null
done

for c in swarm-manager swarm-worker-1 swarm-worker-2; do
  until docker exec "$c" docker info >/dev/null 2>&1; do sleep 2; done
done

docker exec swarm-manager docker swarm init --advertise-addr "$MANAGER_IP" >/dev/null
TOKEN=$(docker exec swarm-manager docker swarm join-token -q worker)
for n in 1 2; do
  docker exec "swarm-worker-$n" docker swarm join --token "$TOKEN" "$MANAGER_IP:2377"
done

# инструменты для скриптов и копия проекта на менеджер-узле
docker exec swarm-manager sh -c 'apk add -q bash openssl curl && mkdir -p /opt/bizflow'
tar --exclude=.git --exclude=__pycache__ -cf - -C "$(dirname "$0")/.." . | docker exec -i swarm-manager tar -xf - -C /opt/bizflow

docker exec swarm-manager sh -c 'cd /opt/bizflow && bash scripts/swarm-init.sh >/dev/null &&
  docker node update --label-add tier=app worker-1 >/dev/null &&
  docker node update --label-add tier=app worker-2 >/dev/null && docker node ls'
