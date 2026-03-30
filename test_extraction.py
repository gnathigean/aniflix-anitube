import asyncio
from scrapers.anitube_provider import AniTubeProvider

async def test():
    url_ep = "https://www.anitube.news/video/925946/"
    print(f"Investigando IFRAMES em: {url_ep}")
    
    provider = AniTubeProvider()
    try:
        page = await provider.init_browser()
        await page.goto(url_ep, wait_until="load", timeout=30000)
        await asyncio.sleep(2)
        
        iframes = await page.evaluate("""() => Array.from(document.querySelectorAll('iframe')).map(i => i.src || i.getAttribute('data-src') || i.innerHTML)""")
        print("IFRAMES ENCONTRADOS:", iframes)
        
        html = await page.content()
        import re
        frames_html = re.findall(r'<iframe[^>]+>', html)
        print("TAGS IFRAME HTML:", frames_html)
        
        await provider.close_browser()
    except Exception as e:
        print(f"FALHA GERAL: {e}")
        import traceback; traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test())
