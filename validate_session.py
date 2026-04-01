import asyncio
import base64
import json
import httpx
from scrapers.anitube_provider import AniTubeProvider
from database.db import init_db

async def validate():
    await init_db()
    provider = AniTubeProvider()
    url_origem = "https://www.anitube.news/video/925543/"
    
    print(f"🚀 Iniciando extração COM SESSÃO para: {url_origem}")
    result = await provider.extract_episode(url_origem)
    
    if not result:
        print("❌ Extração falhou.")
        return

    stream_url = result["url_stream_original"]
    headers_b64 = result["headers_b64"]
    
    print(f"✅ Stream extraído: {stream_url[:60]}...")
    
    # Decodificar headers para o teste
    headers = {}
    if headers_b64:
        headers_str = base64.urlsafe_b64decode(headers_b64 + "==").decode("utf-8")
        headers = json.loads(headers_str)
        print(f"📦 Cookies capturados: {headers.get('cookie', 'Nenhum')[:50]}...")
    
    # Simular o Proxy com os headers de fidelidade
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        print("\n🧪 Testando requisição com Headers de Fidelidade...")
        resp = await client.get(stream_url, headers=headers)
        print(f"Status Final: {resp.status_code}")
        print(f"Content-Type: {resp.headers.get('content-type')}")
        
        if resp.status_code == 200 and "video" in resp.headers.get('content-type', ''):
            print("✨ SUCESSO! O proxy agora consegue ler o vídeo.")
        else:
            print("❌ FALHA! O site ainda redirecionou ou bloqueou.")

    await provider.close_browser()

if __name__ == "__main__":
    asyncio.run(validate())
