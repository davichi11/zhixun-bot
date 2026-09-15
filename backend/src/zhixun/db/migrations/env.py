"""Alembic 迁移环境。

生产环境用 `alembic revision --autogenerate` + `alembic upgrade head` 管理表结构变更，
**禁止**直接改生产库。
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from zhixun.config.settings import settings
from zhixun.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 同步 URL（Alembic 不支持 async driver，这里做一次转换）
config.set_main_option("sqlalchemy.url", settings.database_url.replace("+aiosqlite", "").replace(
    "+asyncpg", "+psycopg"
))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
