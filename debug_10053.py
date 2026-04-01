import asyncio
import logging
from scrapers.anitube_provider import AniTubeProvider
from database.db import init_db

logging.basicConfig(level=logging.INFO)

async def test():
    await init_db()
    provider = AniTubeProvider()
    print("Testing episode 10053 directly...")
    
    # Vamos pegar a URL original do episódio 10053 primeiro do banco de dados simulado
    # Na verdade, eu não tenho a URL exata do DB, então vou procurar no DB.
    from sqlalchemy import select
    from database.db import AsyncSessionLocal
    from database.models import Episodio
    
    async with AsyncSessionLocal() as session:
        ep = await session.execute(select(Episodio).where(Episodio.id == 10053))
        ep = ep.scalar_one_or_none()
        if not ep:
            print("Episodio 10053 not found.")
            return
        
        url_origem = ep.url_episodio_origem
        print(f"URL de Origem: {url_origem}")
        
        # Inserindo interceptação manual:
        page = await provider.init_browser()
        print("Browser init sucessful.")
        
        await page.goto(url_origem)
        print("Page accessed.")
        
        html = await page.content()
        with open("test_10053.html", "w", encoding="utf-8") as f:
            f.write(html)
            
        print("HTML saved to test_10053.html. Running standard extraction...")
        
        res = await provider.extract_episode(url_origem)
        print(f"Extraction result: {res}")
        
        await provider.close_browser()

if __name__ == "__main__":
    asyncio.run(test())
