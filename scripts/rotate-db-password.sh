#!/usr/bin/env bash
# Смена пароля базы данных (секрет db_password) в работающем стеке.
#   bash scripts/rotate-db-password.sh        # на менеджер-узле, где запущен postgres
#
# Заменить один секрет недостаточно: образ postgres читает POSTGRES_PASSWORD_FILE
# только при инициализации пустого каталога данных, и у пользователя уже созданной
# базы пароль от этого не изменится. Поэтому скрипт:
#   1) создаёт новый секрет со случайным паролем;
#   2) меняет пароль пользователя bizflow в работающей базе (ALTER USER);
#   3) подключает новый секрет к сервисам api, worker и postgres под прежним
#      именем файла /run/secrets/db_password (postgres при этом перезапускается);
#   4) удаляет старый секрет.
# Между шагами 2 и 3 новые подключения реплик со старым паролем отклоняются,
# поэтому смену пароля лучше выполнять в период низкой нагрузки.
# Имя нового секрета scripts/deploy.sh берёт из работающего сервиса api
# (переменная DB_PASSWORD_SECRET в docker-stack.yml).
set -euo pipefail
STACK=${STACK:-bizflow}

secret_of() {
  docker service inspect "${STACK}_$1" --format \
    '{{range .Spec.TaskTemplate.ContainerSpec.Secrets}}{{if eq .File.Name "db_password"}}{{.SecretName}}{{end}}{{end}}'
}

old=$(secret_of api)
[ -n "$old" ] || { echo "у сервиса ${STACK}_api не найден секрет db_password" >&2; exit 1; }
pg=$(docker ps -qf "name=${STACK}_postgres" | head -1)
[ -n "$pg" ] || { echo "контейнер ${STACK}_postgres на этом узле не найден" >&2; exit 1; }

new="db_password_$(date +%Y%m%d%H%M%S)"
password=$(openssl rand -hex 24)
printf '%s' "$password" | docker secret create "$new" - >/dev/null
echo "создан секрет $new (заменяет $old)"

# пароль передаётся через stdin, чтобы он не попал в список процессов
printf "ALTER USER bizflow PASSWORD '%s';\n" "$password" |
  docker exec -i "$pg" psql -v ON_ERROR_STOP=1 -q -U bizflow -d bizflow
echo "пароль пользователя bizflow в базе изменён"

for svc in api worker postgres; do
  docker service update --detach=false --quiet \
    --secret-rm "$(secret_of "$svc")" --secret-add "source=$new,target=db_password" "${STACK}_$svc"
  echo "сервис ${STACK}_$svc использует $new"
done

docker secret rm "$old" >/dev/null && echo "старый секрет $old удалён"
echo "Для ручного docker stack deploy задайте DB_PASSWORD_SECRET=$new"
