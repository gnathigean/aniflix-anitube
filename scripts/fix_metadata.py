import asyncio
import os
import sys
import re
from pathlib import Path

# Adiciona o diretório raiz ao sys.path para importar os módulos locais
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))

from database.db import AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from scrapers.anitube_provider import AniTubeProvider

async def extract_anime_cover_and_metadata(page, series_url):
    """Extrai capa e metadados básicos da página da série."""
    try:
        await page.goto(series_url, wait_until="domcontentloaded", timeout=30000)
        # Extrai URL da capa
        cover_url = await page.evaluate("""() => {
            const img = document.querySelector('.ani_loop_item_img img, .ani_single_top_img img, .poster img');
            return img ? img.src : null;
        }""")
        # Extrai Thumbnails dos episódios (opcional)
        return {"url_capa": cover_url}
    except Exception as e:
        print(f"  ⚠️ Erro ao navegar na página da série: {e}")
        return None

async def fix_anime_metadata(anime_id: int):
    provider = AniTubeProvider()
    
    async with AsyncSessionLocal() as db:
        # 1. Busca o anime no banco
        result = await db.execute(
            select(Anime)
            .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
            .where(Anime.id == anime_id)
        )
        anime = result.scalar_one_or_none()
        if not anime:
            print(f"❌ Anime ID {anime_id} não encontrado.")
            return

        print(f"🔍 Corrigindo metadados para: {anime.titulo}...")
        
        # 2. Busca o anime no AniTube pelo título
        # results = {"leg": [...], "dub": [...]}
        results = await provider.search_series(anime.titulo)
        
        urls = results.get("leg", [])
        if not urls: urls = results.get("dub", [])
        
        if not urls:
            print(f"⚠️ Nenhum resultado no AniTube para '{anime.titulo}'.")
            return
            
        series_url = urls[0]
        print(f"✅ Encontrado no AniTube: {series_url}")
        
        # 3. Visita a página da série para extrair a capa
        page = await provider.init_browser()
        try:
            metadata = await extract_anime_cover_and_metadata(page, series_url)
            if metadata and metadata.get("url_capa"):
                anime.url_capa = metadata["url_capa"]
                print(f"🖼️ Capa atualizada: {anime.url_capa[:60]}...")
            else:
                print("⚠️ Não foi possível encontrar a imagem da capa na página.")
        finally:
            await provider.close_browser()

        await db.commit()
        print(f"✨ Sucesso: {anime.titulo} atualizado no banco.")

async def main():
    if len(sys.argv) < 2:
        print("Uso: python scripts/fix_metadata.py <anime_id1> <anime_id2> ...")
        return
        
    ids = [int(x) for x in sys.argv[1:]]
    for aid in ids:
        await fix_anime_metadata(aid)

if __name__ == "__main__":
    asyncio.run(main())
