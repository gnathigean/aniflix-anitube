import asyncio
import os
from database.db import AsyncSessionLocal, engine
from database.models import Episodio, Anime
from sqlalchemy import func
from sqlalchemy.future import select

async def main():
    print("--- DIAGNÓSTICO ANIFLIX ---")
    try:
        async with AsyncSessionLocal() as session:
            # Contagem de episódios
            q = await session.execute(select(func.count(Episodio.id)))
            count = q.scalar()
            print(f"Total de Episódios no Banco: {count}")
            
            # Verificando Dragon Ball
            q = await session.execute(select(Anime).where(Anime.titulo.ilike("%Dragon Ball%")))
            anime = q.scalar_one_or_none()
            if anime:
                print(f"Anime encontrado: {anime.titulo} (ID: {anime.id})")
                q = await session.execute(select(func.count(Episodio.id)).where(Episodio.anime_id == anime.id))
                eps = q.scalar()
                print(f"Episódios de Dragon Ball: {eps}")
            else:
                print("Anime 'Dragon Ball' não encontrado no banco.")
                
            # Verificando se há erros no log do proxy (uvicorn.out)
            if os.path.exists("uvicorn.out"):
                print("\nÚltimas linhas do log do servidor:")
                with open("uvicorn.out", "r") as f:
                    lines = f.readlines()
                    for l in lines[-10:]:
                        print(f"  {l.strip()}")
            
    except Exception as e:
        print(f"Erro no diagnóstico: {e}")

if __name__ == "__main__":
    asyncio.run(main())
