import os
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Chemin DB relatif au dossier racine du projet
BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR}/instafarm.db")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Active WAL mode et optimisations SQLite a chaque connexion."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA cache_size=10000;")
    cursor.close()


# Appliquer les pragmas sur chaque nouvelle connexion raw
event.listen(engine.sync_engine, "connect", _set_sqlite_pragmas)


async def get_db():
    """Dependency FastAPI : fournit une session async."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """Cree toutes les tables au demarrage."""
    from backend.models import Base  # noqa: F811

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
