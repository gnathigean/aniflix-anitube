import asyncio
from scrapers.anitube_provider import AniTubeProvider
from database.db import AsyncSessionLocal
from database.models import Episodio
from sqlalchemy.future import select

async def test():
    async with AsyncSessionLocal() as session:
        ep = (await session.execute(select(Episodio).where(Episodio.id == 10808))).scalar_one_or_none()
        url = ep.url_episodio_origem if ep else "NADA"
    print(f"URL Korra: {url}")
    if url != "NADA":
        data = await AniTubeProvider().extract_episode(url)
        print("EXTRAIDO:", data)

asyncio.run(test())
