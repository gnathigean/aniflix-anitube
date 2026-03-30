import asyncio
import base64
from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Episodio

async def populate():
    print("Iniciando banco de dados...")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # Cria anime de teste
        anime = Anime(
            titulo="Big Buck Bunny (Anime de Teste)",
            sinopse="Um anime clássico de teste para validar o player de vídeo, o proxy HLS e o frontend.",
            ano_lancamento=2008,
            estudio="Blender Foundation",
            url_capa="https://upload.wikimedia.org/wikipedia/commons/c/c5/Big_buck_bunny_poster_big.jpg",
            status="Finalizado"
        )
        session.add(anime)
        await session.flush()
        
        # Stream de teste HLS open source
        test_url = "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8"
        b64_url = base64.urlsafe_b64encode(test_url.encode("utf-8")).decode("utf-8")
        
        ep = Episodio(
            anime_id=anime.id,
            numero=1,
            titulo_episodio="O Despertar do Coelho (Piloto)",
            tipo="Canônico",
            url_stream_original=b64_url,
            headers_b64=""
        )
        session.add(ep)
        await session.commit()
        print("✅ Dados de teste inseridos com sucesso!")

if __name__ == "__main__":
    asyncio.run(populate())
