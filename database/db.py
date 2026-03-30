import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import event

# Padrão: SQLite local se não houver variável de ambiente
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./animes.db")

# Garante o uso do driver asyncpg para PostgreSQL
if DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://"):
    # Substitui protocolos para garantir async
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine_args = {"echo": False}
if "sqlite" in DATABASE_URL:
    engine_args["connect_args"] = {"timeout": 30}

engine = create_async_engine(DATABASE_URL, **engine_args)

if "sqlite" in DATABASE_URL:
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
