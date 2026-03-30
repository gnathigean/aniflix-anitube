"""
AniTubeProvider - Extração Multi-Estratégia

Estratégias em ordem de tentativa:
  1. HLS/m3u8 via interceptação de rede (mais rápido e confiável)
  2. Extração do src do iframe anivideo.net (fallback para cuando HLS não aparece)
  3. Busca por src de <video> tags e fontes no DOM (fallback DOM)
  4. Extração via URL da API do anivideo.net diretamente (fallback API)
  5. Salvar a URL do iframe anivideo.net como proxy (último recurso funcional)
"""

import asyncio
import random
import re
import base64
import json
from typing import Optional
from scrapers.base_provider import BaseProvider


class AniTubeProvider(BaseProvider):
    def is_valid_stream(self, url: str) -> bool:
        if not url or not isinstance(url, str): return False
        url_lower = url.lower()
        
        # FILTRO AGRESSIVO: Rejeita telemetria, trackers, scripts e cdn-cgi
        blacklist = [
            "anitube.news/#", "anitube.news/video/", "anitube.news/contato", "anitube.news/genero",
            "cdn-cgi", "rum", "pixel", "analytics", "ping", "telemetry", "beacon", "cloudflare"
        ]
        if any(b in url_lower for b in blacklist):
            # Previne falsos positivos: googlevideo possui palavras amplas na querystring
            if "googlevideo" not in url_lower:
                return False
        
        # Se for do próprio anitube.news, só aceita se for explicitamente .m3u8 (HLS)
        if "anitube.news" in url_lower and ".m3u8" not in url_lower:
            return False

        # Verifica se é uma extensão de vídeo válida ou host de confiança
        valid_exts = [".m3u8", ".mp4", ".ts", "googlevideo.com/videoplayback"]
        is_video = any(ext in url_lower for ext in valid_exts)
        
        if "anivideo.net" in url_lower:
            return is_video

        valid_hosts = ["prd.jwpltx.com", "blogger.com", "googleusercontent.com", "ip-", ".net/"]
        return any(h in url_lower for h in valid_hosts) or is_video


    async def extract_episode(self, episode_url: str) -> dict:
        page = await self.init_browser()
        # Listener de interceptação Passiva (XHR/Fetch)
        async def on_request(request):
            url = request.url.lower()
            
            # FILTRO CRÍTICO: Recusa URLs indesejadas antes de qualquer processamento
            if not self.is_valid_stream(request.url):
                return

            # Captura streams (m3u8, mp4, googlevideo)
            if (".m3u8" in url or ".mp4" in url or "googlevideo.com/videoplayback" in url):
                # Validação adicional: URLs de stream reais costumam ser longas (>100 chars)
                if len(url) > 100 and not "favicon" in url:
                    # Prioridade: m3u8 > mp4 / googlevideo
                    if not self.extracted_url or (".m3u8" in url and (".mp4" in self.extracted_url.lower() or "googlevideo" in self.extracted_url.lower())):
                        print(f"[AniTube] 📡 Capturado via rede: {url[:60]}...")
                        self.extracted_url = request.url
                        self.extracted_headers = base64.urlsafe_b64encode(json.dumps(request.headers).encode()).decode()
            
            if "anivideo" in url or "blogger.com/video" in url:
                self._anivideo_iframe_url = request.url

        page.on("request", on_request)

        try:
            print(f"[AniTube] 🔍 Acessando: {episode_url}")
            try:
                await page.goto(episode_url, wait_until="domcontentloaded", timeout=30000)
            except:
                await page.goto(episode_url, wait_until="load", timeout=30000)

            # Simula atividade para disparar o player
            await page.mouse.wheel(0, 300); await asyncio.sleep(1)
            await page.mouse.wheel(0, -300); await asyncio.sleep(1)
            await page.mouse.click(640, 360); await asyncio.sleep(1)
            await page.mouse.click(640, 400); await asyncio.sleep(3)

            # Espera até 25s por stream capturado via rede
            for i in range(25):
                if self.extracted_url: break
                await asyncio.sleep(1)

            if self.extracted_url:
                print(f"[AniTube] ✅ Estratégia 1 (Rede) sucedida.")
                return {"url_stream_original": self.extracted_url, "headers_b64": self.extracted_headers}

            # --- ESTRATÉGIA 1.5: Inspeção de Frames ---
            for frame in page.frames:
                try:
                    f_content = await frame.content()
                    m = re.search(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*|(?:file|url|src)["\']\s*:\s*["\'](https?://[^\s"\'<>]+)["\'])', f_content)
                    if m:
                        url_found = (m.group(2) if m.group(2) else m.group(1)).replace('\\/', '/')
                        if self.is_valid_stream(url_found):
                            print(f"[AniTube] ✅ Estratégia 1.5 (Frame Content) encontrou stream.")
                            headers = {"Referer": frame.url if frame.url else episode_url}
                            headers_b64 = base64.urlsafe_b64encode(json.dumps(headers).encode()).decode()
                            return {"url_stream_original": url_found, "headers_b64": headers_b64}
                except: continue

            # ─── ESTRATÉGIA 2: Iframe Drilling ────────────────
            iframe_src = await page.evaluate("""() => {
                const iframes = document.querySelectorAll('iframe');
                for (const ifr of iframes) {
                    const src = ifr.src || ifr.getAttribute('src') || ifr.getAttribute('data-src') || '';
                    if (src && (src.includes('anivideo') || src.includes('blogger') || src.includes('player') || src.includes('bg.mp4'))) return src;
                }
                return null;
            }""")

            target_iframe = iframe_src or self._anivideo_iframe_url
            if target_iframe:
                print(f"[AniTube] ⚠️ M3U8 não encontrado. Transpassando para iframe interno...")
                try:
                    await page.mouse.wheel(0, 300); await asyncio.sleep(1)
                    await page.mouse.click(640, 360); await asyncio.sleep(1)
                    
                    # Interage com todos os frames filhos que pareçam ser players
                    for frame in page.frames:
                        if "anivideo" in frame.url or "bg.mp4" in frame.url or "player" in frame.url:
                            try:
                                await frame.evaluate("""() => {
                                    const btn = document.querySelector('.vjs-big-play-button, .jw-icon-display, .play-button, video');
                                    if(btn) btn.click();
                                }""")
                            except: pass

                    for i in range(15):
                        if self.extracted_url:
                            print(f"[AniTube] ✅ Estratégia 2 (Iframe Intercept) encontrou URL via rede.")
                            return {"url_stream_original": self.extracted_url, "headers_b64": self.extracted_headers}
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"[AniTube] Falha na Interação do Iframe: {e}")

            raise Exception("Todas as estratégias de extração falharam para este episódio.")
        finally:
            await self.close_browser()

    async def find_episode_url(self, series_url: str, episode_number: int) -> Optional[str]:
        page = await self.init_browser()
        try:
            await page.goto(series_url, wait_until="domcontentloaded", timeout=30000)
            await page.mouse.wheel(0, 1000); await asyncio.sleep(2)
            eps_raw = await page.evaluate("""() => Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('/video/')).map(a => ({ title: a.title || a.innerText, url: a.href }))""")
            def extract_num(t):
                m = re.search(r'(?:Epis[oó]dio|Ep|Video|Filme|Movie)\s*(\d+)', t, re.IGNORECASE)
                if m: return int(m.group(1))
                m = re.search(r'\b(\d+)\b$', t); return int(m.group(1)) if m else None
            for item in eps_raw:
                if extract_num(item['title']) == episode_number: return item['url']
                if extract_num(item['url'].split('/')[-1]) == episode_number: return item['url']
            return None
        finally:
            await self.close_browser()
