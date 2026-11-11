"""Общие настройки тестов: временная база SQLite и работа без Redis."""
import os
import tempfile

_db_file = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_file}"
os.environ.pop("REDIS_URL", None)
