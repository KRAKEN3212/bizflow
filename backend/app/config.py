"""Настройки сервиса. Значения берутся из переменных окружения и Docker secrets."""
import os
import socket


def _read_secret(name: str, default: str = "") -> str:
    """Секрет читается из файла /run/secrets/<name>, если Swarm его подключил,
    иначе из переменной окружения с тем же именем в верхнем регистре."""
    path = os.getenv(f"{name.upper()}_FILE", f"/run/secrets/{name}")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    return os.getenv(name.upper(), default)


def _database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("DB_HOST")
    if not host:
        return "sqlite:///./bizflow.db"
    user = os.getenv("DB_USER", "bizflow")
    name = os.getenv("DB_NAME", "bizflow")
    password = _read_secret("db_password", "bizflow")
    return f"postgresql+psycopg://{user}:{password}@{host}:5432/{name}"


class Settings:
    app_name = "BizFlow"
    version = os.getenv("APP_VERSION", "1.0.0")
    database_url = _database_url()
    redis_url = os.getenv("REDIS_URL", "")
    jwt_secret = _read_secret("jwt_secret", "dev-secret-change-me")
    jwt_ttl_minutes = int(os.getenv("JWT_TTL_MINUTES", "240"))
    stats_cache_ttl = int(os.getenv("STATS_CACHE_TTL", "30"))
    hostname = socket.gethostname()


settings = Settings()
