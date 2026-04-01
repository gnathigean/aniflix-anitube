import httpx
import asyncio

async def run():
    # URL extraída do log anterior
    url = "https://www.anitube.news/nUE0pUZ6Yl9mLKEmqKEin3HhLzkiM3Ajo3DhL29gYmVjZwViZQDiMTSln2IlYKEbLJ4gLv5bqT1f/0/2/bg.mp4?p=1&q=RGFya2VyIHRoYW4gQmxhY2sg4oCTIEVwaXPDs2RpbyAwMw==&nocache1770921754"
    
    # Teste 1: Sem referer (Default Proxy)
    headers1 = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "referer": "https://www.anitube.news/"
    }
    
    # Teste 2: Com referer real do Episódio
    headers2 = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "referer": "https://www.anitube.news/video/925543/"
    }

    async with httpx.AsyncClient(verify=False) as client:
        print("Teste 1: Referer Genérico...")
        r1 = await client.get(url, headers=headers1)
        print(f"Status: {r1.status_code}, Content-Type: {r1.headers.get('content-type')}")
        
        print("\nTeste 2: Referer Episódio...")
        r2 = await client.get(url, headers=headers2)
        print(f"Status: {r2.status_code}, Content-Type: {r2.headers.get('content-type')}")

if __name__ == "__main__":
    asyncio.run(run())
