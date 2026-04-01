import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
from sqlalchemy.pool import NullPool
from pathlib import Path
from dotenv import load_dotenv

# Força o recarregamento do .env, ignorando o que estiver no sistema se vazio
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path, override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip('"').strip("'")

engine_args = {
    "echo": False,
}

if not DATABASE_URL or DATABASE_URL.startswith("sqlite"):
    print("⚠️ AVISO: DATABASE_URL ausente ou configurada para SQLite! Verifique o .env.")
    DATABASE_URL = "sqlite+aiosqlite:///./animes.db"
    from sqlalchemy.pool import StaticPool
    engine_args.update({
        "poolclass": StaticPool,
        "connect_args": {"timeout": 30}
    })
    engine = create_async_engine(DATABASE_URL, **engine_args)
else:
    # Ajuste para drivers assíncronos e PgBouncer TRANSACTION MODE (Supabase)
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
    
    # IMPORTANTE: Desativar prepared statement cache DIRETAMENTE na URL para o PgBouncer
    sep = "&" if "?" in DATABASE_URL else "?"
    if "prepared_statement_cache_size" not in DATABASE_URL:
        DATABASE_URL += f"{sep}prepared_statement_cache_size=0"
    if "statement_cache_size" not in DATABASE_URL:
        DATABASE_URL += "&statement_cache_size=0"

    print(f"📦 [DB] Inicializando conexão com: {DATABASE_URL[:40]}...")

    # A desativação do cache de statements é OBRIGATÓRIA para PgBouncer Transaction Mode
    engine_args.update({
        "poolclass": NullPool,
        "connect_args": {
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
            "command_timeout": 60
        }
    })
    engine = create_async_engine(DATABASE_URL, prepared_statement_cache_size=0, **engine_args)

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
    
    if db_type == "SQLITE LOCAL":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        # No Supabase/PgBouncer, pulamos o create_all no startup para evitar introspecção
        # que causa o erro 'DuplicatePreparedStatementError'.
        print("[DB] 🛡️ PgBouncer detectado: Pulando create_all (schema já deve existir).")
