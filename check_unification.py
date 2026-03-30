import asyncio
import sys
import os
sys.path.append(os.getcwd())
from database.db import AsyncSessionLocal
from database.models import Anime
from sqlalchemy.future import select

async def check(): 
    async with AsyncSessionLocal() as session:
        # Busca animes que tenham pelo menos 1 ep dublado e 1 leg
        q = await session.execute(select(Anime).where(Anime.qtd_dub > 0, Anime.qtd_leg > 0).limit(10))
        animes = q.scalars().all()
        if not animes:
            print("Nenhum anime unificado (Dub+Leg) encontrado ainda nesta rodada.")
        for a in animes:
            print(f"✅ UNIFICADO: {a.titulo} | Leg: {a.qtd_leg} | Dub: {a.qtd_dub}")

if __name__ == "__main__":
    asyncio.run(check())
