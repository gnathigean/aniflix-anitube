import httpx
import asyncio

async def test():
    url = "https://www.anitube.news/nUE0pUZ6Yl9mLKEmqKEin3HhLzkiM3Ajo3DhL29gYmVjZwViZQDiMTSln2IlYKEbLJ4gLv5bqT1f/0/2/bg.mp4?p=1&q=RGFya2VyIHRoYW4gQmxhY2sg4oCTIEVwaXPDs2RpbyAwMw==&nocache1770921754"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "referer": "https://www.anitube.news/video/925543/",
    }
    async with httpx.AsyncClient(verify=False) as client:
        r = await client.get(url, headers=headers)
        with open("player_page.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("HTML saved to player_page.html. Parsing for video urls...")

if __name__ == "__main__":
    asyncio.run(test())
