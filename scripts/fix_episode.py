"""
Script para forçar a re-extração de um episódio específico e atualizar o banco.
Uso: python scripts/fix_episode.py <episodio_id>
"""
import asyncio
import sys
import os

sys.path.append(os.getcwd())

from database.db import AsyncSessionLocal, init_db
from database.models import Episodio
from scrapers.anitube_provider import AniTubeProvider
from sqlalchemy import select

async def fix_episode(ep_id: int):
    await init_db()
    
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Episodio).where(Episodio.id == ep_id))
        ep = res.scalar_one_or_none()
        if not ep:
            print(f"❌ Episódio ID {ep_id} não encontrado no banco.")
            return
        
        print(f"🎬 Episódio: {ep.titulo_episodio}")
        print(f"🔗 URL Origem: {ep.url_episodio_origem}")
        print(f"⚠️  URL Stream atual (possivelmente expirada): {(ep.url_stream_original or '')[:80]}...")
        
        if not ep.url_episodio_origem:
            print("❌ Sem URL de origem para re-extrair.")
            return
        
        print("\n🔄 Iniciando re-extração...")
        provider = AniTubeProvider()
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            provider.browser = browser
            
            result = await provider.extract_episode(ep.url_episodio_origem)
            
            if result and result.get("url_stream_original"):
                nova_url = result["url_stream_original"]
                print(f"\n✅ Nova URL extraída: {nova_url[:100]}...")
                
                # Atualiza o banco de dados
                ep.url_stream_original = nova_url
                ep.headers_b64 = result.get("headers_b64")
                await session.commit()
                print("💾 Banco de dados atualizado com sucesso!")
            else:
                print("❌ Re-extração falhou. Nenhuma URL encontrada.")
            
            await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/fix_episode.py <episodio_id>")
        print("Exemplo: python scripts/fix_episode.py 12245")
        sys.exit(1)
    
    ep_id = int(sys.argv[1])
    asyncio.run(fix_episode(ep_id))
