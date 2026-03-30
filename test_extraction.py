import asyncio
import base64
import json
from scrapers.anitube_provider import AniTubeProvider

async def test():
    provider = AniTubeProvider()
    # Testar com o anime que o usuário citou (A-Rank Party) ou similar
    url_ep = "https://www.anitube.news/video/998307/" # Episódio de teste
    print(f"Buscando stream para: {url_ep}")
    
    data = await provider.extract_episode(url_ep)
    if data and data.get("url_stream_original"):
        url = data["url_stream_original"]
        headers = data["headers_b64"]
        
        # Gera link do proxy
        proxy_url = f"http://localhost:8000/stream?url_b64={base64.urlsafe_b64encode(url.encode()).decode()}&headers_b64={headers}"
        print("\n" + "="*50)
        print("✅ EXTRAÇÃO COM SUCESSO!")
        print(f"URL Original: {url[:80]}...")
        print(f"Proxy URL: {proxy_url}")
        print("="*50)
    else:
        print("❌ FALHA NA EXTRAÇÃO. Verifique o log do Playwright.")

if __name__ == "__main__":
    asyncio.run(test())
