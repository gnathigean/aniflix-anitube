import asyncio
import sys
import os

sys.path.append(os.getcwd())

from database.db import AsyncSessionLocal
from database.models import Episodio
from scrapers.anitube_provider import AniTubeProvider
from sqlalchemy import select

async def test_ep(ep_id: int):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Episodio).where(Episodio.id == ep_id))
        ep = res.scalar_one_or_none()
        if not ep:
            print("❌ Episódio não encontrado")
            return
            
        print(f"🎬 Testando extração para: {ep.titulo_episodio}")
        print(f"🌐 URL Origem: {ep.url_episodio_origem}")
        
        provider = AniTubeProvider()
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            provider.browser = browser
            
            result = await provider.extract_episode(ep.url_episodio_origem)
            
            if result and result.get("url_stream_original"):
                print("✅ SUCESSO!")
                print(f"🔗 URL Stream: {result['url_stream_original'][:100]}...")
            else:
                print("❌ FALHA NA EXTRAÇÃO")
                
            await browser.close()

if __name__ == "__main__":
    ep_id = 12245
    if len(sys.argv) > 1:
        ep_id = int(sys.argv[1])
    asyncio.run(test_ep(ep_id))
