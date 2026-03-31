import asyncio
from database.db import get_db
from database.models import Anime, Episodio
from sqlalchemy import select
from sqlalchemy.orm import selectinload

async def check():
    async with get_db() as db:
        # Check animes
        res = await db.execute(select(Anime).limit(5))
        animes = res.scalars().all()
        print(f"DEBUG: Found {len(animes)} animes")
        for a in animes:
            print(f" - {a.titulo} (Views: {a.visualizacoes_total})")
            
        # Check episodes views_dia
        res_ep = await db.execute(select(Episodio).where(Episodio.views_dia > 0).limit(5))
        eps = res_ep.scalars().all()
        print(f"DEBUG: Found {len(eps)} episodes with views_dia > 0")
        
        # Check a specific anime mentioned by user
        res_spec = await db.execute(select(Anime).where(Anime.titulo.ilike("%Diamond%")))
        spec = res_spec.scalar_one_or_none()
        if spec:
            print(f"DEBUG: {spec.titulo} EXISTS")
        else:
            print("DEBUG: Diamond NO Ace NOT FOUND")

if __name__ == "__main__":
    asyncio.run(check())
