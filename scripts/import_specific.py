"""
Script OTIMIZADO para importar animes específicos.
- Identifica gaps no banco antes de abrir o browser
- Busca todos os episódios da série de uma vez só
- Não reabre browser para cada episódio

Uso: python scripts/import_specific.py "Nome do Anime"
"""
import asyncio
import sys
import os
import re
from pathlib import Path

sys.path.append(os.getcwd())

from database.db import init_db, AsyncSessionLocal, DB_WRITE_LOCK
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from importer import processar_episodio, load_json, save_json, fetch_mal_metadata, STATUS_FILE, MAP_FILE

async def import_anime_by_title(target_title: str):
    print(f"🚀 Iniciando reparo prioritário para: '{target_title}'")
    await init_db()
    
    mapping = load_json(MAP_FILE, {})
    status = load_json(STATUS_FILE, {"sucesso": 0, "erros": 0, "pulados": 0, "log_recente": []})
    
    async with AsyncSessionLocal() as session:
        # Busca o anime no banco (fuzzy search)
        result = await session.execute(
            select(Anime)
            .where(Anime.titulo.ilike(f"%{target_title}%"))
            .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
        )
        animes = result.scalars().all()
        
        if not animes:
            print(f"⚠️ Anime '{target_title}' não encontrado no banco. Criando...")
            # Tenta criar via mapeamento
            anime_map = None
            for title, data in mapping.items():
                if target_title.lower() in title.lower():
                    anime_map = (title, data)
                    break
            if not anime_map:
                print(f"❌ Anime não encontrado no mapeamento também. Abortando.")
                return
            nome, data = anime_map
            mal = await fetch_mal_metadata(nome)
            new_anime = Anime(
                titulo=nome,
                url_capa=mal['url_capa'] if mal else "",
                sinopse=mal['sinopse'] if mal else "",
                ano=mal['ano'] if mal else ""
            )
            session.add(new_anime)
            await session.flush()
            temp = Temporada(anime_id=new_anime.id, numero=1)
            session.add(temp)
            await session.commit()
            animes = [new_anime]
            # Recarrega com relações
            result2 = await session.execute(
                select(Anime).where(Anime.id == new_anime.id)
                .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
            )
            animes = result2.scalars().all()

    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        provider = AniTubeProvider()
        provider.browser = browser
        
        try:
            for anime in animes:
                print(f"\n🎬 Processando: {anime.titulo}")
                
                # Encontra o mapeamento
                anime_map = mapping.get(anime.titulo)
                if not anime_map:
                    for title, data in mapping.items():
                        if target_title.lower() in title.lower():
                            anime_map = data
                            break
                
                if not anime_map:
                    print(f"⚠️ Sem mapeamento para '{anime.titulo}'.")
                    continue
                
                for temp in anime.temporadas:
                    for idioma in ["Legendado", "Dublado"]:
                        key = "leg" if idioma == "Legendado" else "dub"
                        urls = anime_map.get(key, [])
                        if not urls:
                            print(f"  ⏭️ Nenhuma URL para {idioma}. Pulando.")
                            continue
                        
                        series_url = urls[0]
                        
                        # Identifica gaps antes de abrir o browser
                        eps_no_banco = sorted([e.numero for e in temp.episodios if e.idioma == idioma])
                        max_ep_banco = max(eps_no_banco) if eps_no_banco else 0
                        
                        print(f"\n  📊 {idioma}: {len(eps_no_banco)} episódios no banco (máx: {max_ep_banco})")
                        
                        # Busca LISTA COMPLETA de episódios da série em UMA página só
                        print(f"  🌐 Buscando lista de episódios em: {series_url[:60]}...")
                        page = await browser.new_page()
                        try:
                            await page.goto(series_url, wait_until="domcontentloaded", timeout=30000)
                            await page.mouse.wheel(0, 1000)
                            await asyncio.sleep(2)
                            eps_raw = await page.evaluate("""() => 
                                Array.from(document.querySelectorAll('a'))
                                    .filter(a => a.href.includes('/video/') && !a.href.includes('#') && !a.href.includes('respond'))
                                    .map(a => ({ title: a.title || a.innerText.trim(), eps_url: a.href }))
                            """)
                        except Exception as e:
                            print(f"  ❌ Erro ao carregar página de série: {e}")
                            await page.close()
                            continue
                        finally:
                            await page.close()
                        
                        if not eps_raw:
                            print(f"  ⚠️ Nenhum episódio encontrado na página da série.")
                            continue
                        
                        # Normaliza e deduplica
                        seen = set()
                        unique_eps = []
                        for e in eps_raw:
                            if e['eps_url'] not in seen:
                                seen.add(e['eps_url'])
                                unique_eps.append(e)
                        unique_eps.reverse()  # Coloca do ep 1 em diante
                        
                        print(f"  📋 {len(unique_eps)} episódios encontrados no site")
                        
                        # Extrai numeração de cada episódio
                        def extract_num(title_or_url, fallback_idx):
                            m = re.search(r'(?:Epis[oó]dio|Ep\.?|Video)\s*(\d+)', title_or_url, re.IGNORECASE)
                            if m: return int(m.group(1))
                            m2 = re.search(r'\b(\d+)\b\s*$', title_or_url.strip())
                            return int(m2.group(1)) if m2 else fallback_idx
                        
                        # Identifica quais episódios estão faltando
                        gaps = []
                        for i, ep_item in enumerate(unique_eps):
                            ep_num = extract_num(ep_item['title'], i + 1)
                            if ep_num not in eps_no_banco:
                                gaps.append((ep_num, ep_item))
                        
                        if not gaps:
                            print(f"  ✅ {idioma}: Nenhum gap encontrado!")
                            continue
                        
                        print(f"  🔧 {len(gaps)} gaps encontrados: {[g[0] for g in gaps[:10]]}{'...' if len(gaps) > 10 else ''}")
                        
                        # Processa apenas os gaps
                        for ep_num, ep_item in gaps:
                            success = await processar_episodio(ep_item, ep_num, status, anime.id, temp.id, idioma)
                            if success:
                                print(f"  ✅ Ep {ep_num} ({idioma}) importado!")
                            else:
                                print(f"  ❌ Falha no Ep {ep_num} ({idioma})")
                            await asyncio.sleep(0.3)  # Anti rate-limit
        finally:
            await browser.close()
    
    print(f"\n✅ Concluído! Sucesso: {status['sucesso']} | Erros: {status['erros']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/import_specific.py \"Nome do Anime\"")
        sys.exit(1)
    
    asyncio.run(import_anime_by_title(sys.argv[1]))
