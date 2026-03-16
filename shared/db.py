from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.config import DATABASE_URL, DATABASE_URL_SYNC
from shared.models import Base


# --- Async (для dashboard) --- загружается лениво ---

def _make_async():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


class _AsyncDB:
    """Ленивый контейнер для async-компонентов (не импортирует asyncpg до первого обращения)."""
    _engine = None
    _session_factory = None

    @classmethod
    def _ensure(cls):
        if cls._engine is None:
            cls._engine, cls._session_factory = _make_async()

    @classmethod
    def engine(cls):
        cls._ensure()
        return cls._engine

    @classmethod
    def session_factory(cls):
        cls._ensure()
        return cls._session_factory


async def get_db():
    async with _AsyncDB.session_factory()() as session:
        yield session


async def init_db():
    async with _AsyncDB.engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def get_async_session():
    """Получить async session factory для прямого использования."""
    return _AsyncDB.session_factory()


# --- Sync (для скраперов) ---

sync_engine = create_engine(DATABASE_URL_SYNC, echo=False)
SyncSessionLocal = sessionmaker(bind=sync_engine)


def init_db_sync():
    Base.metadata.create_all(sync_engine)


def get_db_sync():
    session = SyncSessionLocal()
    try:
        yield session
    finally:
        session.close()
