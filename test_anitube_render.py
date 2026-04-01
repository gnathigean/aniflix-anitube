from playwright.async_api import async_playwright
import asyncio

async def test():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
        url = "https://www.anitube.news/video/925543/"
        print(f"Acessando {url}...")
        
        await page.goto(url, wait_until="networkidle")
        
        # Tirar screenshot
        await page.screenshot(path="artifacts/anitube_page.png", full_page=True)
        print("Screenshot salva na raiz: anitube_page.png")
        
        # Extrair iframes
        frames = page.frames
        print(f"Número de iframes encontrados no DOM: {len(frames)}")
        for i, f in enumerate(frames):
            print(f"[{i}] URL: {f.url}")
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(test())
