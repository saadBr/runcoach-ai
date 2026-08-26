"""Alembic migration environment."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from runcoach.config import get_settings
from runcoach.db import models

config = context.config
settings = get_settings()

config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace("%", "%%"),
)

target_metadata = models.Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without creating a database connection."""

    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations using a live database connection."""

    configuration = config.get_section(config.config_ini_section)
    if configuration is None:
        raise RuntimeError("Alembic configuration section is missing.")

    connectable = engine_from_config(
        configuration,
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
