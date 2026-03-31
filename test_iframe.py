import asyncio
from scrapers.anitube_provider import AniTubeProvider

async def test():
    provider = AniTubeProvider()
    page = await provider.init_browser()
    target = "https://www.anitube.news/nUE0pUZ6Yl9lMJWipz5jn20hLzkiM3Ajo3DhL29gYmVjZwViZQtiMTyuoJ9hMP1hol1uLl5bqT1f/0/6/bg.mp4?p=1&q=RGlhbW9uZCBubyBBY2Ug4oCTIEVwaXPDs2RpbyAwNw==&nocache1770889691"
    
    await page.goto(target, wait_until="networkidle", timeout=30000)
    await page.screenshot(path="iframe_player.png")
    
    html = await page.content()
    with open("iframe_html.txt", "w") as f:
        f.write(html)
        
    print("Screenshot salva como iframe_player.png e HTML como iframe_html.txt")
    await provider.close_browser()

if __name__ == "__main__":
    asyncio.run(test())
