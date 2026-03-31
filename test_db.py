import os, asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from dotenv import load_dotenv

load_dotenv()

async def test():
    user_url = os.getenv("DATABASE_URL")
    if not user_url:
        print("DATABASE_URL not found!")
        return
    
    # Garantir asyncpg
    if "postgresql" in user_url and "asyncpg" not in user_url:
        user_url = user_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(user_url)
    try:
        async with engine.connect() as conn:
            res = await conn.execute(text("SELECT count(*) FROM episodios"))
            count = res.scalar()
            print(f"EPISODIOS_COUNT:{count}")
            
            res = await conn.execute(text("SELECT titulo FROM animes WHERE titulo ILIKE '%Dragon Ball%' LIMIT 1"))
            anime = res.scalar()
            print(f"DRAGONBALL_FOUND:{anime}")
    except Exception as e:
        print(f"DB_ERROR:{e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test())
