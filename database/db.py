import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
from pathlib import Path
from dotenv import load_dotenv

# Força o recarregamento do .env, ignorando o que estiver no sistema se vazio
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip('"').strip("'")
if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    print("⚠️ AVISO: DATABASE_URL ausente ou configurada para SQLite! Verifique o .env.")
    DATABASE_URL = "sqlite+aiosqlite:///./animes.db"
else:
    # Ajuste para drivers assíncronos e PgBouncer (Supabase)
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # Se for Supabase/Postgres, desativa prepared statements na URL para o PgBouncer
    if "postgresql" in DATABASE_URL and "prepared_statements" not in DATABASE_URL:
        separator = "&" if "?" in DATABASE_URL else "?"
        DATABASE_URL += f"{separator}prepared_statements=false"

print(f"📦 [DB] Inicializando conexão com: {DATABASE_URL[:25]}...")

engine_args = {
    "echo": False,
    "pool_pre_ping": True,  # Verifica se a conexão está ativa antes de usar
}
from sqlalchemy.pool import NullPool

# ... (código anterior)

if "sqlite" in DATABASE_URL:
    engine_args["connect_args"] = {"timeout": 30}
else:
    # Essencial para Supabase/PgBouncer (Transaction Pooler na porta 6543)
    # Usamos NullPool porque o PgBouncer já faz o pooling. Evita conflito de prepared statements.
    engine_args["poolclass"] = NullPool
    engine_args["connect_args"] = {
        "statement_cache_size": 0,
        "command_timeout": 30
    }

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
    db_type = "SUPABASE/POSTGRES" if ("supabase" in DATABASE_URL or "postgres" in DATABASE_URL or "6543" in DATABASE_URL) else "SQLITE LOCAL"
    print(f"[DB] 🗄️ Inicializando banco de dados: {db_type}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
