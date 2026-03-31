import asyncio
import os
from dotenv import load_dotenv

# Força carregamento
load_dotenv(".env")
url = os.environ.get("DATABASE_URL", "").strip('"').strip("'")
print(f"URL Detectada no .env: {url[:30]}...")

from database.db import AsyncSessionLocal, init_db
from database.models import Episodio
from sqlalchemy.future import select

async def clean_dirty_urls():
    await init_db()
    async with AsyncSessionLocal() as session:
        # Busca episódios que possuem urls "sujas"
        stmt = select(Episodio).filter(
            (Episodio.url_stream_original.ilike('%cdn-cgi%')) |
            (Episodio.url_stream_original.ilike('%jwplayer.js%')) |
            (Episodio.url_stream_original.ilike('%rum?%'))
        )
        result = await session.execute(stmt)
        episodios = result.scalars().all()
        
        print(f"Encontrados {len(episodios)} episódios com URLs sujas no banco.")
        
        for ep in episodios:
            # Apagando a url para forçar re-extração on the fly (ou poderiamos extrair agora)
            ep.url_stream_original = ""
        
        await session.commit()
        print("Banco de dados limpo com sucesso. Os episódios serão extraídos novamente de forma limpa ao serem acessados.")

if __name__ == "__main__":
    asyncio.run(clean_dirty_urls())
