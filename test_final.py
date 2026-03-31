import asyncio
import traceback
from scrapers.anitube_provider import AniTubeProvider

async def test():
    print("Testando Diamond no Ace EP 7...")
    try:
        data = await AniTubeProvider().extract_episode("https://www.anitube.news/video/925946/")
        print("\n✅ SUCESSO LÍQUIDO E CERTO!")
        print("URL M3U8/MP4:", data["url_stream_original"])
    except Exception as e:
        print(f"FALHA EXPLOSIVA: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
