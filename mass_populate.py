import asyncio
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from sqlalchemy.future import select
from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider


TITULO_PATTERN = re.compile(
    r'^(?P<nome>.+?)'                          # Nome base do anime
    r'(?:\s+(?P<temporada>'
    r'(?:Season|Temporada|Part)\s*\d+'         # ex: Season 3
    r'|\d{1,2}(?:\.\d+)?'                      # ex: "Dragon Ball Z 2" (número isolado)
    r'))?'
    r'(?:\s+[-–]\s+.*)?$',                     # ex: – Todos os Episódios
    re.IGNORECASE
)

def parse_titulo(raw: str):
    """
    Dado "Dragon Ball Z (Dublado) - Season 2 – Episódio 45"
    retorna (nome_anime, num_temporada, nome_temporada, num_ep)
    """
    # Remove o sufixo de episódio para limpar
    sem_ep = re.sub(r'\s*[-–]\s*Epis[oó]dio\s*\d+.*$', '', raw, flags=re.IGNORECASE).strip()
    sem_ep = re.sub(r'\s*[-–]\s*Todos\s+os\s+Epis[oó]dios.*$', '', sem_ep, flags=re.IGNORECASE).strip()

    # Detecta tipo: Dublado / Legendado (gera temporada separada se presente)
    tipo_audio = None
    for t in ['Dublado', 'Legendado', 'Dub']:
        if re.search(rf'\({t}\)', sem_ep, re.IGNORECASE):
            tipo_audio = t.capitalize()
            sem_ep = re.sub(rf'\s*\({t}\)', '', sem_ep, flags=re.IGNORECASE).strip()
            break

    # Detecta Season / Temporada
    season_match = re.search(r'(?:Season|Temporada|Part)\s*(\d+)', sem_ep, re.IGNORECASE)
    num_temporada = int(season_match.group(1)) if season_match else 1
    if season_match:
        sem_ep = sem_ep[:season_match.start()].strip()
    # Limpa número solto no final (ex: "Dragon Ball Super 2")
    numfim = re.search(r'\b(\d+)\s*$', sem_ep)
    if numfim and not season_match:
        num_temporada = int(numfim.group(1))
        sem_ep = sem_ep[:numfim.start()].strip()

    nome_anime = sem_ep.strip(' –-')

    # Rótulo da temporada
    partes = []
    if num_temporada > 1:
        partes.append(f"Temporada {num_temporada}")
    if tipo_audio:
        partes.append(tipo_audio)
    nome_temporada = " — ".join(partes) if partes else "Temporada 1"
    if tipo_audio and num_temporada == 1:
        nome_temporada = tipo_audio

    return nome_anime, num_temporada, nome_temporada


def extrair_ep(titulo: str) -> int:
    m = re.search(r'Epis[oó]dio\s*(\d+)', titulo, re.IGNORECASE)
    if m:
        return int(m.group(1))
    m2 = re.search(r'[-–]\s*(\d+)\s*$', titulo.strip())
    if m2:
        return int(m2.group(1))
    return 0


async def mass_populate(start_page: int = 1, end_page: int = 10):
    print(f"🚀 Importação em Massa [{start_page}–{end_page}]...")
    await init_db()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await ctx.new_page()
        await Stealth().apply_stealth_async(page)

        all_items = []
        for p_num in range(start_page, end_page + 1):
            url = f"https://www.anitube.news/page/{p_num}/" if p_num > 1 else "https://www.anitube.news/"
            print(f"\n➔ Página {p_num}")
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                items = await page.evaluate("""() => {
                    const r = [];
                    document.querySelectorAll('.epiItem').forEach(el => {
                        const a = el.querySelector('a');
                        const img = el.querySelector('img');
                        if (a && img) r.push({
                            title: a.getAttribute('title') || img.getAttribute('alt') || '',
                            eps_url: a.href,
                            img_url: img.src || img.dataset.src || ''
                        });
                    });
                    return r;
                }""")
                all_items.extend(items)
                print(f"   ✔ {len(items)} eps (total: {len(all_items)})")
            except Exception as e:
                print(f"   ⚠ Erro: {e}")

        await browser.close()

    print(f"\n⭐ {len(all_items)} episódios para processar...")

    async with AsyncSessionLocal() as session:
        for idx, item in enumerate(all_items):
            titulo_raw = item['title'].strip()
            if not titulo_raw:
                continue

            nome_anime, num_temp, nome_temp = parse_titulo(titulo_raw)
            ep_num = extrair_ep(titulo_raw)

            print(f"\n[{idx+1}/{len(all_items)}] {nome_anime} | {nome_temp} | EP {ep_num}")

            # --- Anime ---
            q = await session.execute(select(Anime).where(Anime.titulo == nome_anime))
            anime = q.scalar_one_or_none()
            if not anime:
                anime = Anime(titulo=nome_anime, url_capa=item['img_url'], status="Disponível", ano_lancamento=2024)
                session.add(anime)
                await session.flush()
                print(f"   ✨ Novo anime: {nome_anime}")

            # --- Temporada ---
            qt = await session.execute(
                select(Temporada).where(Temporada.anime_id == anime.id, Temporada.numero == num_temp)
            )
            temporada = qt.scalar_one_or_none()
            if not temporada:
                temporada = Temporada(anime_id=anime.id, numero=num_temp, titulo_temporada=nome_temp)
                session.add(temporada)
                await session.flush()

            # --- Verifica Episódio ---
            qe = await session.execute(
                select(Episodio).where(Episodio.temporada_id == temporada.id, Episodio.numero == ep_num)
            )
            if qe.scalar_one_or_none():
                print(f"   ▶ Episódio {ep_num} já existe.")
                continue

            # --- Extrai Stream ---
            provider = AniTubeProvider()
            try:
                data = await provider.extract_episode(item['eps_url'])
                ep = Episodio(
                    temporada_id=temporada.id,
                    numero=ep_num,
                    titulo_episodio=titulo_raw,
                    tipo="Lançamento",
                    url_stream_original=data["url_stream_original"],
                    headers_b64=data["headers_b64"]
                )
                session.add(ep)
                await session.commit()
                print(f"   ✅ Salvo!")
            except Exception as e:
                print(f"   ❌ Erro: {e}")
                await session.rollback()

    print("\n🏁 Importação finalizada!")


if __name__ == "__main__":
    asyncio.run(mass_populate(1, 10))
