#!/usr/bin/env python3
"""
Fix Black Clover - Dublado
1) Usa search_series para encontrar a URL real do catálogo dub
2) Extrai lista de episódios da página de catálogo (sem âncoras)
3) Importa os faltantes com numeração sequencial correta
"""
import asyncio
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider
from sqlalchemy.future import select

BLACK_CLOVER_ANIME_ID = 289

# Regex para URL de episódio limpa: /video/NUMERO/ sem âncora #
EP_URL_RE = re.compile(r'https?://www\.anitube\.news/video/\d+/?\s*$')


async def get_eps_existentes(session, temporada_id: int) -> set[int]:
    r = await session.execute(
        select(Episodio.numero)
        .where(Episodio.temporada_id == temporada_id)
        .where(Episodio.idioma == "Dublado")
    )
    return set(r.scalars().all())


async def descobre_catalog_url(provider: AniTubeProvider) -> str | None:
    """Usa search_series para achar a URL do catálogo do Black Clover Dublado."""
    print("\n🔎 Buscando URL do catálogo 'Black Clover Dublado' no AniTube...")
    resultado = await provider.search_series("Black Clover Dublado")
    dubs = resultado.get("dub", [])
    legs = resultado.get("leg", [])
    print(f"  URLs Dub encontradas: {dubs}")
    print(f"  URLs Leg encontradas: {legs}")
    if dubs:
        return dubs[0]
    # Fallback: tenta busca sem "Dublado"
    resultado2 = await provider.search_series("Black Clover")
    dubs2 = resultado2.get("dub", [])
    if dubs2:
        return dubs2[0]
    return None


async def coleta_eps_do_catalogo(provider: AniTubeProvider, catalog_url: str) -> list[tuple[int, str]]:
    """Navega no catálogo e coleta links de episódio limpos (sem âncoras)."""
    print(f"\n📋 Coletando episódios do catálogo: {catalog_url}")
    page = await provider.init_browser()
    lista = []
    try:
        await page.goto(catalog_url, wait_until="domcontentloaded", timeout=30000)
        # Scroll para carregar lazy content
        for _ in range(5):
            await page.mouse.wheel(0, 800)
            await asyncio.sleep(0.5)
        await asyncio.sleep(2)

        items = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('a'))
                .filter(a => /\\/video\\/\\d+\\/?$/.test(a.href))
                .map(a => ({
                    title: (a.title || a.innerText || a.getAttribute('aria-label') || '').trim(),
                    url: a.href.split('#')[0].replace(/\\/$/, '') + '/'
                }))
        """)

        # Remove duplicatas por URL
        vistos = {}
        for item in items:
            url = item['url']
            if url in vistos:
                continue
            vistos[url] = item['title']

        # Extrai número dos títulos
        ep_sem_num = []
        for url, title in vistos.items():
            m = re.search(r'(?:Epis[oó]dio|Ep|ep)[\s.\-]*(\d+)', title, re.IGNORECASE)
            if m:
                lista.append((int(m.group(1)), url))
            else:
                m2 = re.search(r'\b(\d+)\b\s*$', title.strip())
                if m2:
                    lista.append((int(m2.group(1)), url))
                else:
                    ep_sem_num.append(url)

        # Episódios sem número extraível: usa ordem de aparecimento
        prox = max((n for n, _ in lista), default=0) + 1
        for url in ep_sem_num:
            lista.append((prox, url))
            prox += 1

        lista.sort(key=lambda x: x[0])
        print(f"  ✅ {len(lista)} episódios encontrados (sem âncoras)")
        for num, url in lista:
            print(f"    Ep {num}: {url}")

    except Exception as e:
        print(f"  ❌ Erro ao coletar catálogo: {e}")
    finally:
        await provider.close_browser()

    return lista


async def importar_faltantes(session, temporada_id: int, lista: list[tuple[int, str]]):
    eps_existentes = await get_eps_existentes(session, temporada_id)
    print(f"\n  Eps já no banco (Dublado): {sorted(eps_existentes)}")

    novos = 0
    erros = 0

    for ep_num, ep_url in lista:
        if ep_num in eps_existentes:
            print(f"  ⏭️  Ep {ep_num} já existe.")
            continue

        print(f"\n  🔄 Importando Ep {ep_num}: {ep_url}")
        provider = AniTubeProvider()
        try:
            resultado = await provider.extract_episode(ep_url)
            if not resultado or not resultado.get("url_stream_original"):
                print(f"  ❌ Ep {ep_num}: sem stream retornada")
                erros += 1
                continue

            ep = Episodio(
                temporada_id=temporada_id,
                numero=ep_num,
                idioma="Dublado",
                tipo="Episódio",
                titulo_episodio=f"Episódio {ep_num}",
                url_episodio_origem=ep_url,
                url_stream_original=resultado["url_stream_original"],
                headers_b64=resultado.get("headers_b64"),
            )
            session.add(ep)
            await session.commit()
            eps_existentes.add(ep_num)
            novos += 1
            print(f"  ✅ Ep {ep_num} salvo!")

        except Exception as e:
            print(f"  ❌ Ep {ep_num}: {e}")
            await session.rollback()
            erros += 1

    print(f"\n🏁 Concluído! ✅ {novos} novos | ❌ {erros} erros")
    print(f"   Total Dublado no banco: {await get_eps_existentes(session, temporada_id)}")


async def main():
    await init_db()

    async with AsyncSessionLocal() as session:
        r = await session.execute(
            select(Temporada).where(Temporada.anime_id == BLACK_CLOVER_ANIME_ID)
        )
        temp = r.scalars().first()
        if not temp:
            print("❌ Temporada não encontrada!")
            return
        print(f"✅ Temporada: ID={temp.id}")

        # Passo 1: Encontrar URL do catálogo via search
        provider = AniTubeProvider()
        catalog_url = await descobre_catalog_url(provider)

        if not catalog_url:
            print("❌ Não foi possível encontrar a URL do catálogo. Informe manualmente.")
            return

        print(f"\n📌 Catálogo localizado: {catalog_url}")

        # Passo 2: Coletar lista de episódios
        lista = await coleta_eps_do_catalogo(AniTubeProvider(), catalog_url)

        if not lista:
            print("❌ Nenhum episódio encontrado no catálogo!")
            return

        # Passo 3: Importar os faltantes
        await importar_faltantes(session, temp.id, lista)


if __name__ == "__main__":
    asyncio.run(main())
