"""
AniTubeProvider v3.0 - Extração Multi-Estratégia & Reuso de Recursos.
Otimizado para o Daemon Aniflix, priorizando velocidade e baixo consumo de RAM.
"""

import asyncio
import random
import re
import base64
import json
import logging
from typing import Optional, List, Dict
from scrapers.base_provider import BaseProvider
from playwright.async_api import Page, Browser

logger = logging.getLogger("anitube_provider")

class AniTubeProvider(BaseProvider):
    def is_valid_stream(self, url: str) -> bool:
        if not url or not isinstance(url, str): return False
        url_lower = url.lower()
        
        # FILTRO AGRESSIVO: Rejeita telemetria e trackers
        blacklist = [
            "anitube.news/#", "anitube.news/video/", "cdn-cgi", "rum", "pixel", 
            "analytics", "ping", "telemetry", "beacon", "cloudflare", "facebook.com"
        ]
        if any(b in url_lower for b in blacklist):
            if "googlevideo" not in url_lower: return False
        
        # BLOQUEIO DE PLAYER INTERNO: links bg.mp4 no anitube.news são páginas PHP, não o vídeo real.
        if "anitube.news" in url_lower and "bg.mp4" in url_lower: return False
        
        # BLOQUEIO DE PLAYER INTERNO: links bg.mp4 no anitube.news são páginas PHP, não o vídeo real.
        if "anitube.news" in url_lower and "bg.mp4" in url_lower: return False
        
        # O novo formato deles embute um 'bg.mp4' no próprio anitube.news (agora ignorado acima)
        if "anitube.news" in url_lower and not (".m3u8" in url_lower or ".mp4" in url_lower): return False

        valid_exts = [".m3u8", ".mp4", ".ts", "googlevideo.com/videoplayback"]
        is_video = any(ext in url_lower for ext in valid_exts)
        
        if "anivideo.net" in url_lower: return is_video

        # O frontend cuidará de converter iframes do Blogger/Anitube para a tag <iframe>.
        valid_hosts = ["prd.jwpltx.com", "blogger.com", "googleusercontent.com", "ip-", ".net/", "video.google", "anitube.news"]
        return any(h in url_lower for h in valid_hosts) or is_video

    async def list_episodes_from_page(self, url: str, external_page: Optional[Page] = None) -> List[Dict]:
        """Extrai todos os episódios de uma página de série de uma só vez."""
        page = external_page or await self.init_browser()
        try:
            if not external_page:
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Garante que carregou o conteúdo (alguns sites usam lazy load)
            await page.mouse.wheel(0, 1000); await asyncio.sleep(1)
            await page.mouse.wheel(0, 1000); await asyncio.sleep(1)

            eps = await page.evaluate("""() => 
                Array.from(document.querySelectorAll('a'))
                    .filter(a => {
                        const h = a.href || "";
                        const t = (a.title || a.innerText || "").toLowerCase();
                        return (h.includes('/video/') || t.includes('episódio') || t.includes('ep. ')) 
                               && !h.includes('#') && !h.includes('respond');
                    })
                    .map(a => ({ title: a.title || a.innerText, url: a.href }))
            """)
            
            # Remove duplicatas por URL
            seen = set(); unique = []
            for e in eps:
                if e['url'] not in seen:
                    seen.add(e['url']); unique.append(e)
            return unique
        except Exception as e:
            logger.error(f"Erro ao listar episódios de {url}: {e}")
            return []
        finally:
            if not external_page: await self.close_browser()

    async def extract_episode(self, episode_url: str) -> Optional[dict]:
        """Extração de stream com múltiplas estratégias (Rede -> Regex -> Iframe)."""
        page = await self.init_browser()
        self.extracted_url = None
        self.extracted_headers = None
        
        async def on_request(request):
            url = request.url.lower()
            if self.is_valid_stream(request.url):
                if (".m3u8" in url or ".mp4" in url or "googlevideo.com" in url):
                    if len(url) > 80:
                        self.extracted_url = request.url
                        self.extracted_headers = base64.urlsafe_b64encode(json.dumps(request.headers).encode()).decode()

        page.on("request", on_request)

        try:
            logger.info(f"🔍 Extraindo: {episode_url}")
            await page.goto(episode_url, wait_until="domcontentloaded", timeout=30000)
            
            # Estratégia 0: Extração segura via Regex LEVE / HTML Find
            content = await page.content()
            matches = re.findall(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', content)

            import html
            import json
            
            # Captura estado atual (Fidelity Headers)
            current_cookies = await page.context.cookies()
            cookie_str = "; ".join([f"{c['name']}={c['value']}" for c in current_cookies])
            ua = await page.evaluate("navigator.userAgent")
            fidelity_headers = {"referer": episode_url, "user-agent": ua, "cookie": cookie_str}
            fidelity_b64 = base64.urlsafe_b64encode(json.dumps(fidelity_headers).encode()).decode()

            for stream_url in matches:
                stream_url = html.unescape(stream_url.replace('\\/', '/'))
            # Estratégia Principal: Forçar Play em todas as camadas (Frames / Iframes)
            logger.info("🎬 Tentando ativar o Player em Profundidade...")
            
            # Script insano que entra em todo frame (mesmo cross-origin às vezes o playwright permite via main frame)
            # ou pede para o Playwright ir em cada frame conhecido e disparar clique/play.
            
            try:
                # 1. Clique duplo central para tentar matar popups transparentes do Anivideo
                await page.mouse.click(640, 360); await asyncio.sleep(0.5)
                await page.mouse.click(640, 360); await asyncio.sleep(1)
                
                # 2. Varredura e injeção de Play() em frames
                for f in page.frames:
                    try:
                        # Se encontrarmos o iframe do Blogger/GoogleVideo, focamos nele e clicamos!
                        if "blogger.com" in f.url or "anivideo" in f.url:
                            logger.info(f"🎯 Focando no frame de vídeo: {f.url[:40]}...")
                            # Tenta dar play via javascript no elemento video (se não houver bloqueio CORS severo)
                            await f.evaluate("document.querySelectorAll('video').forEach(v => v.play())", timeout=2000)
                    except:
                        pass
            except:
                pass

            # 3. Espera interceptação de rede (CDN Final do Google ou Mpd)
            for _ in range(20): 
                if self.extracted_url:
                    logger.info("✅ Encontrado via Rede (CDN Final)")
                    return {"url_stream_original": self.extracted_url, "headers_b64": self.extracted_headers}
                await asyncio.sleep(1)
                
                # Resgate instantâneo pela árvore de Frames montada
                for f in page.frames:
                    if f.url and "about:blank" not in f.url:
                        if self.is_valid_stream(f.url) and "anitube.news" not in f.url:
                            logger.info(f"✅ Encontrado Video Iframe nativo ({f.url[:50]}...)")
                            return {"url_stream_original": f.url, "headers_b64": fidelity_b64}

            raise Exception("Falha em todas as estratégias de extração profunda.")
        except Exception as e:
            logger.warning(f"Erro na extração: {e}")
            return None
        finally:
            if page:
                try: await page.close()
                except: pass

    async def find_episode_url(self, series_url: str, episode_number: int, external_page: Optional[Page] = None) -> Optional[str]:
        """Busca a URL de um episódio específico na página da série."""
        eps = await self.list_episodes_from_page(series_url, external_page=external_page)
        
        # Ordem costuma ser decrescente no site (Mais novos no topo)
        # Vamos inverter para bater o index
        eps.reverse() 
        
        def clean_num(t, u=""):
            m = re.search(r'(?:Epis[oó]dio|Ep\.|Ep|Video)\s*(\d+)', t, re.IGNORECASE)
            if m: return int(m.group(1))
            m_nums = re.findall(r'\b(\d{1,4})\b', t)
            if m_nums: return int(m_nums[-1])
            # Pelo final da URL
            m_url = re.search(r'(\d+)(?:[ab]|sl\d+)?/?$', u.rstrip('/'))
            if m_url: return int(m_url.group(1))
            return None

        for idx, item in enumerate(eps):
            f_num = clean_num(item['title'], item['url']) or (idx + 1)
            if f_num == episode_number:
                return item['url']
        return None
