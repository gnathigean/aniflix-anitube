import asyncio
import os
import json
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from database.db import AsyncSessionLocal, init_db
from database.models import Anime, Temporada, Episodio

async def verify():
    print("🔍 Iniciando Verificação de Integridade...")
    await init_db()
    
    async with AsyncSessionLocal() as session:
        # Pega todos os animes com temporadas e episódios
        result = await session.execute(
            select(Anime).options(
                selectinload(Anime.temporadas).selectinload(Temporada.episodios)
            )
        )
        animes = result.scalars().all()
        
        report = {
            "total_animes": len(animes),
            "animes_com_gaps": [],
            "animes_sem_episodios": [],
            "animes_com_erro_stream": []
        }
        
        for anime in animes:
            total_eps_anime = 0
            anime_gaps = []
            
            if not anime.temporadas:
                report["animes_sem_episodios"].append(anime.titulo)
                continue
                
            for temp in anime.temporadas:
                # Group by language to check gaps in each
                for idioma in ["Legendado", "Dublado"]:
                    eps = [e for e in temp.episodios if e.idioma == idioma]
                    if not eps: continue
                    
                    nums = sorted([e.numero for e in eps])
                    if not nums: continue
                    
                    # Check for gaps
                    max_num = nums[-1]
                    expected = set(range(1, max_num + 1))
                    actual = set(nums)
                    missing = sorted(list(expected - actual))
                    
                    if missing:
                        anime_gaps.append({
                            "temporada": temp.numero,
                            "idioma": idioma,
                            "missing": missing
                        })
                    
                    # Check for empty streams
                    empty_streams = [e.numero for e in eps if not e.url_stream_original]
                    if empty_streams:
                        report["animes_com_erro_stream"].append({
                            "titulo": anime.titulo,
                            "idioma": idioma,
                            "episodios": empty_streams
                        })

            if anime_gaps:
                report["animes_com_gaps"].append({
                    "titulo": anime.titulo,
                    "gaps": anime_gaps
                })
                
    # Salva o relatório
    with open("integrity_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
        
    print(f"✅ Verificação concluída!")
    print(f"📊 Total de Animes: {report['total_animes']}")
    print(f"⚠️ Animes com Gaps: {len(report['animes_com_gaps'])}")
    print(f"❌ Animes sem Episódios: {len(report['animes_sem_episodios'])}")
    print(f"📁 Relatório salvo em 'integrity_report.json'")

if __name__ == "__main__":
    asyncio.run(verify())
