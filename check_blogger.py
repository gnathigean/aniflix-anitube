import httpx
import asyncio
import re

async def run():
    url = "https://www.blogger.com/video.g?token=AD6v5dy_yY3D81eD3AELl-T0PN82QJtL7GBAqbMsfl8qDzLAQeOtQdAy7sQzsuZeKGMHUKHEJB0Wof0MYCmC8nkoW2XJdwxh7Vdadt40aD0nOXBfEWUY2uGSUubBh8Z8GWZg8g_Yg_o"
    async with httpx.AsyncClient() as c:
        r = await c.get(url)
        with open("blogger.html", "w") as f:
            f.write(r.text)
        print("Salvo em blogger.html")

asyncio.run(run())
