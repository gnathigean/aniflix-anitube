import httpx
import asyncio

async def test():
    url = "https://www.anitube.news/nUE0pUZ6Yl9mLKEmqKEin3HhLzkiM3Ajo3DhL29gYmVjZwViZQDiMTSln2IlYKEbLJ4gLv5bqT1f/0/2/bg.mp4?p=1&q=RGFya2VyIHRoYW4gQmxhY2sg4oCTIEVwaXPDs2RpbyAwMw==&nocache1770921754"
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "referer": "https://www.anitube.news/video/925543/",
        "range": "bytes=0-" # Força o CDN a pensar que é um player de vídeo
    }
    async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
        r = await client.get(url, headers=headers)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type')}")
        print(f"Body snippet: {r.text[:500]}")

if __name__ == "__main__":
    asyncio.run(test())
