import asyncio
import os
import sys
from pathlib import Path

# Adiciona o diretório raiz ao sys.path para importar os módulos locais
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))

from database.db import AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from scrapers.anitube_provider import AniTubeProvider

KNOWN_URLS = {
    681: "https://www.anitube.news/video/57402/", # Eureka Seven
    682: "https://www.anitube.news/video/56669/", # Eureka Seven AO
}

async def force_fix_metadata(anime_id, series_url):
    provider = AniTubeProvider()
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Anime)
            .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
            .where(Anime.id == anime_id)
        )
        anime = result.scalar_one_or_none()
        if not anime:
            print(f"❌ Anime ID {anime_id} não encontrado.")
            return

        print(f"🔍 Forçando correção de metadados via URL direta: {series_url}")
        page = await provider.init_browser()
        try:
            await page.goto(series_url, wait_until="domcontentloaded", timeout=40000)
            # Extrai capa
            cover_url = await page.evaluate("""() => {
                const img = document.querySelector('.ani_loop_item_img img, .ani_single_top_img img, .poster img, img[src*="poster"], img[src*="capa"]');
                return img ? img.src : null;
            }""")
            
            if cover_url:
                anime.url_capa = cover_url
                print(f"🖼️  Capa atualizada para ID {anime_id}: {cover_url[:60]}...")
            else:
                print(f"⚠️  Capa não encontrada na página para ID {anime_id}.")

            await db.commit()
            print(f"✅ Sucesso: {anime.titulo} atualizado.")
        finally:
            await provider.close_browser()

async def main():
    for aid, url in KNOWN_URLS.items():
        await force_fix_metadata(aid, url)

if __name__ == "__main__":
    asyncio.run(main())
