import asyncio
import os
from sqlalchemy.future import select
from sqlalchemy import func
from database.db import AsyncSessionLocal, init_db
from database.models import Anime, Episodio

async def check():
    await init_db()
    async with AsyncSessionLocal() as session:
        # Check Local/Supabase counts (depending on DATABASE_URL)
        anime_count = (await session.execute(select(func.count(Anime.id)))).scalar()
        epi_count = (await session.execute(select(func.count(Episodio.id)))).scalar()
        
        url = os.getenv("DATABASE_URL", "sqlite")
        print(f"--- DB STATUS ({'SUPABASE' if 'supabase' in url else 'LOCAL'}) ---")
        print(f"Animes: {anime_count}")
        print(f"Episodios: {epi_count}")

if __name__ == "__main__":
    asyncio.run(check())
