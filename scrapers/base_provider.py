import base64
import json
import asyncio
from abc import ABC, abstractmethod
from playwright.async_api import async_playwright, Page, Route
from playwright_stealth import Stealth


class BaseProvider(ABC):
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.extracted_url: str | None = None
        self.extracted_headers: str | None = None
        self._anivideo_iframe_url: str | None = None

    async def init_browser(self, headless: bool = True) -> Page:
        if not self.playwright:
            self.playwright = await async_playwright().start()
        
        # Verifica se o browser morreu/desconectou no servidor
        if self.browser and not self.browser.is_connected():
            self.browser = None
            self.context = None

        if not self.browser:
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--no-first-run',
                    '--no-zygote',
                    '--single-process',
                ]
            )
            self.context = None

        if not self.context:
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            
        try:
            page = await self.context.new_page()
        except Exception:
            # Fallback se o contexto corrompeu
            self.context = await self.browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
            )
            page = await self.context.new_page()

        await Stealth().apply_stealth_async(page)
        return page

    async def _intercept_request(self, route: Route):
        request = route.request
        url = request.url

        # Estratégia 1: m3u8 direto (HLS) ou mp4
        is_stream = (".m3u8" in url or ".mp4" in url or "/hls/" in url or "playlist.m3u8" in url)
        is_hls = (
            is_stream
            and "anivideo.net/videohls.php" not in url
            and "nocache" not in url
            and "segment" not in url.lower()
        )
        if is_hls and not self.extracted_url:
            # Aceita se tiver index.m3u8 ou se for um m3u8 sem ser segmento (.ts)
            if "index.m3u8" in url or ((".m3u8" in url or ".mp4" in url) and ".ts" not in url and "seg-" not in url):
                self.extracted_url = base64.urlsafe_b64encode(url.encode()).decode()
                headers_json = json.dumps(dict(request.headers))
                self.extracted_headers = base64.urlsafe_b64encode(headers_json.encode()).decode()
                print(f"[{self.__class__.__name__}] ✅ [Estratégia HLS] Stream Detectada: {url[:80]}...")

        # Estratégia 2: Captura a URL do iframe intermediário do anivideo.net
        if "anivideo.net/file/" in url and not self._anivideo_iframe_url:
            self._anivideo_iframe_url = url
            print(f"[{self.__class__.__name__}] 📡 [Estratégia Iframe] AniVideo detectado: {url[:80]}...")

        try:
            await route.continue_()
        except Exception:
            pass

    async def setup_interception(self, page: Page):
        await page.route("**/*", self._intercept_request)

    @abstractmethod
    async def extract_episode(self, episode_url: str) -> dict:
        pass

    async def close_browser(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
