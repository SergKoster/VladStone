"""Изоляция тестов от дев-БД.

Тесты не должны бить в живую `vladstone_dev.sqlite3`: она копит матчи разных
версий движка между прогонами, и старьё ломает загрузку. Здесь БД
переключается на свежий временный файл ДО импорта приложения (env читается
один раз при импорте app.db.session).
"""

import importlib
import os
import tempfile
from pathlib import Path

from sqlalchemy import event

_postgres_test_url = os.environ.get("TEST_DATABASE_URL")
if _postgres_test_url:
    # CI передаёт отдельную ephemeral PostgreSQL database для проверок
    # настоящих транзакций. ENVIRONMENT не меняем: dev-login и providers
    # завязаны на "local".
    os.environ["DATABASE_URL"] = _postgres_test_url
else:
    _TMP_DB = Path(tempfile.gettempdir()) / f"vladstone_test_{os.getpid()}.sqlite3"
    # Свежий файл на каждый прогон: не тащим накопленный мусор.
    if _TMP_DB.exists():
        _TMP_DB.unlink()
    # Forward slashes в URL (Windows-путь с бэкслешами SQLAlchemy не разберёт).
    # ENVIRONMENT НЕ трогаем: dev-login и провайдеры завязаны на "local".
    os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

# SQLite leaves foreign-key constraints disabled by default.  Keeping them on
# in tests makes its integrity checks match PostgreSQL, including PvP seats.
# The module is intentionally loaded only after DATABASE_URL is set above.
engine = importlib.import_module("app.db.session").engine


if engine.dialect.name == "sqlite":

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
