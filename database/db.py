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
    # Ajuste para driver Psycopg v3 (Gold Standard para PgBouncer/Supabase)
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    
    # Psycopg v3 lida melhor com Poolers. Vamos remover cache manual de statements.
    is_pooler = "6543" in DATABASE_URL

    if is_pooler:
        # Modo de Segurança para PgBouncer (Transaction Mode) no Psycopg v3
        engine_args.update({
            "poolclass": NullPool,
            "connect_args": {
                "prepare_threshold": None, # Desativa prepared statements no Psycopg v3
                "connect_timeout": 60
            }
        })
        engine = create_async_engine(DATABASE_URL, **engine_args)
        print(f"📦 [DB] PgBouncer detectado (6543). v4.1: Psycopg v3 (Unprepared Mode).")
    else:
        # Modo de Alta Performance para Conexão DIRETA (5432)
        engine_args.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_recycle": 3600,
            "pool_pre_ping": True,
        })
        engine = create_async_engine(DATABASE_URL, **engine_args)
        print(f"🚀 [DB] Conexão DIRETA detectada (5432). v4.1: Psycopg v3.")

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
    
    try:
        if db_type == "SQLITE LOCAL":
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        else:
            # No Supabase/PgBouncer, pulamos qualquer comando no startup (inclusive ping)
            # para evitar que a introspecção de tipos cause erro no PgBouncer.
            print("[DB] 🛡️ PgBouncer — Silêncio Total: Pulando comandos de controle no startup.")
    except Exception as e:
        print(f"⚠️ [DB] Aviso na inicialização (Não-Fatal): {e}")
