import asyncio
import os
import sys
from pathlib import Path

# Adiciona o diretório atual ao path
sys.path.append(os.getcwd())

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, selectinload
from sqlalchemy.future import select
from database.models import Episodio, Temporada, Anime
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

async def test():
    engine = create_async_engine("sqlite+aiosqlite:///animes.db")
    async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    
    templates = Jinja2Templates(directory="frontend")
    import base64
    def b64encode_filter(s):
        if not s: return ""
        return base64.urlsafe_b64encode(s.encode()).decode()
    templates.env.filters["b64encode"] = b64encode_filter

    async with async_session() as session:
        # Busca o episódio 244 (o que o usuário reportou)
        result = await session.execute(
            select(Episodio)
            .options(
                selectinload(Episodio.temporada).selectinload(Temporada.anime).selectinload(Anime.temporadas).selectinload(Temporada.episodios),
                selectinload(Episodio.temporada).selectinload(Temporada.episodios)
            )
            .where(Episodio.id == 244)
        )
        episodio = result.scalar_one_or_none()
        if not episodio:
            print("Episódio 244 não encontrado.")
            return

        print(f"Testando renderização para: {episodio.temporada.anime.titulo}")
        
        # Mock request para o Jinja2
        scope = {"type": "http"}
        request = Request(scope)
        
        try:
            content = templates.get_template("player.html").render(
                request=request, 
                episodio=episodio, 
                progresso=10
            )
            print("Renderização bem sucedida!")
        except Exception as e:
            print(f"ERRO DE RENDERIZAÇÃO: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
