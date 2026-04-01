import asyncio
import os
import sys
from pathlib import Path

# Adiciona o diretório raiz ao sys.path para importar os módulos locais
root_path = Path(__file__).parent.parent
sys.path.append(str(root_path))

from database.db import AsyncSessionLocal
from database.models import Anime
from sqlalchemy import update

FIX_MAP = {
    681: "https://www.anitube.news/wp-content/uploads/assistir-eureka-seven-todos-os-episodios-todos-os-episodios-online-anitube.jpg",
    682: "https://www.anitube.news/wp-content/uploads/assistir-eureka-seven-ao-todos-os-episodios-todos-os-episodios-online-anitube.jpg",
}

async def force_apply_fix():
    print("📦 [DB] Conectando para aplicar correções de capa...")
    async with AsyncSessionLocal() as db:
        for anime_id, cover_url in FIX_MAP.items():
            print(f"🖼  Atualizando capa para ID {anime_id} -> {cover_url[:50]}...")
            
            # 1. Atualiza Anime.url_capa
            await db.execute(
                update(Anime)
                .where(Anime.id == anime_id)
                .values(url_capa=cover_url)
            )
            
        await db.commit()
        print("🚀 Mudanças persistidas no Supabase com sucesso.")

if __name__ == "__main__":
    asyncio.run(force_apply_fix())
