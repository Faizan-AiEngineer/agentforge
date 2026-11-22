from alembic import context

from backend.app.db import Base, connect
from backend.app.runtime import Settings

settings = Settings.from_env()
connection = context.config.attributes.get("connection")


def migrate(conn):
    context.configure(connection=conn, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    url = settings.database_url or f"sqlite:///{(settings.root / 'agentforge.sqlite').as_posix()}"
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif connection is not None:
    migrate(connection)
else:
    settings.root.mkdir(parents=True, exist_ok=True)
    engine, _ = connect(settings.root, settings.database_url)
    with engine.connect() as conn:
        migrate(conn)
    engine.dispose()
