import random
from scrapers.base_provider import BaseProvider

class AnimesDigitalProvider(BaseProvider):
    async def extract_episode(self, episode_url: str) -> dict:
        page = await self.init_browser()
        await self.setup_interception(page)
        
        # Delay aleatório inicial (Furtividade)
        await page.wait_for_timeout(random.randint(2000, 5000))
        
        try:
            print(f"[AnimesDigital] Acessando a página: {episode_url}")
            await page.goto(episode_url, wait_until="domcontentloaded")
            
            # Animes Digital pode rodar o player num iframe com o servidor de stream
            for _ in range(15):
                if self.extracted_url:
                    break
                
                try:
                    await page.evaluate('''() => {
                        const buttons = document.querySelectorAll('button, .play-button, .jw-icon-display, video');
                        buttons.forEach(b => b.click());
                        
                        // Caso esteja em um iframe do Blogger ou do Fembed/Google Drive
                        document.querySelectorAll('iframe').forEach(ifr => {
                            try {
                                ifr.contentWindow.document.querySelectorAll('.play-button').forEach(v => v.click());
                            } catch(e) {}
                        });
                    }''')
                except Exception:
                    pass
                
                await page.wait_for_timeout(1000)
                
            if not self.extracted_url:
                raise Exception("Falha ao capturar link de streaming no AnimesDigital.")
                
            return {
                "url_stream_original": self.extracted_url,
                "headers_b64": self.extracted_headers
            }
        
        finally:
            await self.close_browser()
