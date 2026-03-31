import asyncio
from scrapers.anitube_provider import AniTubeProvider

async def test():
    provider = AniTubeProvider()
    page = await provider.init_browser()
    
    # Listener para ver todas as requisições (ignorando blacklist)
    async def log_req(req):
        url = req.url
        if ".m3u8" in url or ".mp4" in url or "googlevideo" in url or "mcdn" in url or "cloudflare" in url:
            print(f"REQUISIÇÃO INTERCEPTADA: {url[:100]}")
            
    page.on("request", log_req)
    
    print("Acessando...")
    await page.goto("https://www.anitube.news/video/925946/", wait_until="load", timeout=30000)
    
    print("Frames na página:")
    for f in page.frames:
        print(" - FRAME:", f.url[:80])
        
    await asyncio.sleep(2)
    print("Rolando e clicando...")
    await page.mouse.wheel(0, 300); await asyncio.sleep(1)
    await page.mouse.click(640, 360); await asyncio.sleep(3)
    
    for f in page.frames:
        if "bg.mp4" in f.url:
            print("Clicando no btn do frame bg.mp4...")
            try:
                await f.evaluate("""() => {
                    const btn = document.querySelector('video, button, .vjs-big-play-button, .jw-icon-display, .play-button');
                    if(btn) btn.click();
                    else console.log("Botão de play não encontrado no frame.");
                }""")
            except Exception as e:
                print("Erro ao clicar no frame:", e)
                
    await asyncio.sleep(5)
    await provider.close_browser()

if __name__ == "__main__":
    asyncio.run(test())
