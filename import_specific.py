import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from sqlalchemy.future import select

from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider
from importer import parse_titulo, fetch_mal_metadata, extrair_ep_clemente

async def processar_url(nome, url_lista, idioma):
    print(f"🎬 Importando {nome} ({idioma})...")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        
        try:
            await page.goto(url_lista, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(2)
        except:
            await page.goto(url_lista, wait_until="load", timeout=30000)
            
        await page.mouse.wheel(0, 1000); await asyncio.sleep(1)
        
        eps_raw = await page.evaluate("""() => 
            Array.from(document.querySelectorAll('a'))
                .filter(a => a.href.includes('/video/') && !a.href.includes('#') && !a.href.includes('respond'))
                .map(a => ({ title: a.title || a.innerText, eps_url: a.href }))
        """)
        
        if not eps_raw:
            print(f"⚠️ Nenhum episódio encontrado em {url_lista}")
            await browser.close()
            return

        # Unique and reverse to get sequential numbers
        seen = set(); unique_eps = []
        for e in eps_raw:
            if e['eps_url'] not in seen:
                seen.add(e['eps_url']); unique_eps.append(e)
        unique_eps.reverse()

        await init_db()
        async with AsyncSessionLocal() as session:
            anime = (await session.execute(select(Anime).where(Anime.titulo.ilike(nome)))).scalar_one_or_none()
            if not anime:
                mal = await fetch_mal_metadata(nome)
                anime = Anime(titulo=nome, url_capa=mal['url_capa'] if mal else "", sinopse=mal['sinopse'] if mal else "", ano=mal['ano'] if mal else "")
                session.add(anime); await session.flush()
            temp = (await session.execute(select(Temporada).where(Temporada.anime_id == anime.id, Temporada.numero == 1))).scalar_one_or_none()
            if not temp:
                temp = Temporada(anime_id=anime.id, numero=1)
                session.add(temp); await session.flush()
            await session.commit()
            aid, tid = anime.id, temp.id

        provider = AniTubeProvider()
        for i, item in enumerate(unique_eps):
            n_ep = extrair_ep_clemente(item['title'], i+1)
            async with AsyncSessionLocal() as session:
                qe = await session.execute(select(Episodio).where(Episodio.temporada_id == tid, Episodio.numero == n_ep, Episodio.idioma == idioma))
                if qe.scalar_one_or_none():
                    print(f"◽ Pulado: Ep {n_ep} ({idioma}) já existe.")
                    continue

            print(f"📡 Extraindo Ep {n_ep}...")
            data = await provider.extract_episode(item['eps_url'])
            if data and data.get("url_stream_original"):
                async with AsyncSessionLocal() as session:
                    ep = Episodio(
                        temporada_id=tid,
                        numero=n_ep,
                        titulo_episodio=item['title'],
                        url_stream_original=data["url_stream_original"],
                        headers_b64=data["headers_b64"],
                        idioma=idioma,
                        url_episodio_origem=item['eps_url']
                    )
                    session.add(ep)
                    # Update counts
                    a = (await session.execute(select(Anime).where(Anime.id == aid))).scalar_one()
                    if idioma == "Dublado": a.qtd_dub = (a.qtd_dub or 0) + 1
                    else: a.qtd_leg = (a.qtd_leg or 0) + 1
                    await session.commit()
                print(f"✅ Ep {n_ep} OK")
            else:
                print(f"❌ Falha no Ep {n_ep}")

        await browser.close()

async def run():
    # Solo Leveling
    await processar_url("Solo Leveling", "https://www.anitube.news/video/970749/", "Legendado")
    await processar_url("Solo Leveling", "https://www.anitube.news/video/972816/", "Dublado")
    # Solo Leveling 2
    # await processar_url("Solo Leveling 2", "https://www.anitube.news/video/997981/", "Legendado")
    # await processar_url("Solo Leveling 2", "https://www.anitube.news/video/998839/", "Dublado")

if __name__ == "__main__":
    asyncio.run(run())
