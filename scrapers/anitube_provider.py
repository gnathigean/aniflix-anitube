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
        # Recusa homepages ou links genéricos do site que não são vídeo
        blacklist = ["anitube.news/#", "anitube.news/video/", "anitube.news/contato", "anitube.news/genero"]
        if any(b in url_lower for b in blacklist): return False
        
        # Se for do próprio anitube.news, só aceita se for explicitamente .m3u8 (HLS)
        if "anitube.news" in url_lower and not ".m3u8" in url_lower:
            return False

        # Aceita se for m3u8, mp4 (exceto do próprio site) ou de hosts conhecidos de vídeo
        valid_hosts = ["anivideo.net", "prd.jwpltx.com", "m3u8", ".mp4", "blogger.com", "googleusercontent.com", "googlevideo.com", "ip-", ".net/"]
        return any(h in url_lower for h in valid_hosts)


    async def extract_episode(self, episode_url: str) -> dict:
        page = await self.init_browser()
        # Listener de interceptação Passiva (XHR/Fetch)
        async def on_request(request):
            url = request.url.lower()
            
            # FILTRO CRÍTICO: Ignorar domínios de rastreamento/analytics que quebram o player
            blacklist = ["jwpltx.com", "pixel", "analytics", "ping", "collect", "telemetry", "doubleclick", "adnxs"]
            if any(b in url for b in blacklist):
                return

            if (".m3u8" in url or ".mp4" in url or "googlevideo.com/videoplayback" in url) and self.is_valid_stream(request.url):
                # Validação adicional: URLs de stream reais costumam ser longas e ter caminhos específicos
                if len(url) > 20 and not "favicon" in url:
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
            # domcontentloaded é mais rápido e evita timeouts em sites com excesso de scripts/ads
            try:
                await page.goto(episode_url, wait_until="domcontentloaded", timeout=30000)
            except:
                await page.goto(episode_url, wait_until="load", timeout=30000)

            # Simula atividade para enganar protetores e disparar o player
            await page.mouse.wheel(0, 300)
            await asyncio.sleep(1)
            await page.mouse.wheel(0, -300)
            await asyncio.sleep(1)
            
            # Clica em vários pontos onde o player costuma estar
            await page.mouse.click(640, 360) 
            await asyncio.sleep(1)
            await page.mouse.click(640, 400)
            await asyncio.sleep(3)

            # Espera até 25s por stream capturado via rede
            for i in range(25):
                if self.extracted_url:
                    break
                await asyncio.sleep(1)

            if self.extracted_url:
                print(f"[AniTube] ✅ Estratégia 1 (Rede) sucedida.")
                return {"url_stream_original": self.extracted_url, "headers_b64": self.extracted_headers}

            # --- ESTRATÉGIA 1.5: Inspeção Recursiva de Conteúdo de Frames ---
            print("[AniTube] 🔍 Estratégia 1.5: Inspeção de Conteúdo em Frames...")
            for frame in page.frames:
                try:
                    f_content = await frame.content()
                    # Busca m3u8 ou mp4 no HTML do frame (evitando rastreadores)
                    m = re.search(r'(https?://[^\s"\'<>]+\.(?:m3u8|mp4)[^\s"\'<>]*|(?:file|url|src)["\']\s*:\s*["\'](https?://[^\s"\'<>]+)["\'])', f_content)
                    if m:
                        url_found = (m.group(2) if m.group(2) else m.group(1)).replace('\\/', '/')
                        blacklist = ["jwpltx.com", "pixel", "analytics", "ping", "collect"]
                        if not any(b in url_found for b in blacklist) and self.is_valid_stream(url_found):
                            print(f"[AniTube] ✅ Estratégia 1.5 (Frame Content) encontrou: {url_found[:60]}...")
                            # Retorna a URL plana e os headers codificados (como padrão)
                            headers = {"Referer": frame.url if frame.url else episode_url}
                            headers_b64 = base64.urlsafe_b64encode(json.dumps(headers).encode()).decode()
                            return {"url_stream_original": url_found, "headers_b64": headers_b64}
                except: continue

            # ─── ESTRATÉGIA 2: Captura src do iframe do AniVideo ────────────────
            print(f"[AniTube] ⚠️ Estratégia 1 falhou. Tentando Estratégia 2 (Iframe)...")
            
            # Busca iframes na página
            iframe_src = await page.evaluate("""() => {
                const iframes = document.querySelectorAll('iframe');
                for (const ifr of iframes) {
                    const src = ifr.src || ifr.getAttribute('src') || ifr.getAttribute('data-src') || '';
                    if (src && (src.includes('anivideo') || src.includes('blogger') || src.includes('player'))) {
                        return src;
                    }
                }
                return null;
            }""")

            if iframe_src and self.is_valid_stream(iframe_src):
                print(f"[AniTube] ✅ Estratégia 2 (Iframe) encontrou: {iframe_src[:80]}...")
                empty_headers = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
                return {"url_stream_original": iframe_src, "headers_b64": empty_headers}

            # ─── ESTRATÉGIA 3: Captura o URL do AniVideo via requisição interceptada ─
            if self._anivideo_iframe_url and self.is_valid_stream(self._anivideo_iframe_url):
                print(f"[AniTube] ✅ Estratégia 3 (AniVideo Interceptado) encontrou URL.")
                empty_headers = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
                return {"url_stream_original": self._anivideo_iframe_url, "headers_b64": empty_headers}

            # ─── ESTRATÉGIA 4: Varredura ampla no DOM ───────────────────────────
            print(f"[AniTube] ⚠️ Estratégia 3 falhou. Tentando Estratégia 4 (DOM amplo)...")
            
            # Espera mais um pouco e tenta clicar num player
            await asyncio.sleep(3)
            
            try:
                # Tenta navegar dentro de iframes
                for frame in page.frames:
                    if frame == page.main_frame:
                        continue
                    try:
                        frame_url = frame.url
                        if frame_url and frame_url != "about:blank" and ("anivideo" in frame_url or "blogger" in frame_url or "player" in frame_url):
                            print(f"[AniTube] ✅ Estratégia 4 (Frame URL): {frame_url[:80]}...")
                            empty_headers = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
                            return {"url_stream_original": frame_url, "headers_b64": empty_headers}
                        
                        # Tenta buscar video dentro do frame
                        video_src = await frame.evaluate("""() => {
                            const v = document.querySelector('video');
                            return v ? (v.src || v.currentSrc || '') : '';
                        }""")
                        if video_src and ("http" in video_src):
                            print(f"[AniTube] ✅ Estratégia 4 (Video em Frame): {video_src[:80]}...")
                            empty_headers = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
                            return {"url_stream_original": video_src, "headers_b64": empty_headers}
                    except Exception:
                        continue
            except Exception:
                pass

            # ─── ESTRATÉGIA 5: Extração via HTML bruto ──────────────────────────
            print(f"[AniTube] ⚠️ Estratégia 4 falhou. Tentando Estratégia 5 (regex no HTML)...")
            
            try:
                content = await page.content()
                
                # Procura por URLs de stream no HTML
                patterns = [
                    r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
                    r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
                    r'"file"\s*:\s*"(https?://[^\s"\'<>]+)"',
                    r'src=["\']([^"\']+anivideo[^"\']+)["\']',
                    r'src=["\']([^"\']+blogger\.com/video[^"\']+)["\']',
                ]
                
                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if match and "http" in match and self.is_valid_stream(match):
                            print(f"[AniTube] ✅ Estratégia 5 (Regex HTML): {match[:80]}...")
                            empty_headers = base64.urlsafe_b64encode(json.dumps({}).encode()).decode()
                            return {"url_stream_original": match, "headers_b64": empty_headers}
            except Exception:
                pass
            # ─── FALHA TOTAL ─────────────────────────────────────────────────────
            raise Exception("Todas as estratégias de extração falharam para este episódio.")
        finally:
            await self.close_browser()

    async def find_episode_url(self, series_url: str, episode_number: int) -> Optional[str]:
        """
        Busca a URL de um episódio específico na página da série ou na lista de todos os episódios.
        """
        page = await self.init_browser()
        try:
            print(f"[AniTube] 🔍 Buscando EP {episode_number} em: {series_url}")
            await page.goto(series_url, wait_until="domcontentloaded", timeout=30000)
            await page.mouse.wheel(0, 1000)
            await asyncio.sleep(2)

            # Busca links de vídeo
            eps_raw = await page.evaluate("""() => 
                Array.from(document.querySelectorAll('a'))
                    .filter(a => a.href.includes('/video/') && !a.href.includes('#') && !a.href.includes('respond') && !a.href.includes('edit'))
                    .map(a => ({ title: a.title || a.innerText, url: a.href }))
            """)

            # Tenta encontrar o "Ver todos" se não achou muitos episódios ou se o número é alto
            if not eps_raw or episode_number > 20:
                link_todos = await page.evaluate("""() => { 
                    const a = Array.from(document.querySelectorAll('a')).find(x => x.innerText.toLowerCase().includes('todos') || (x.href && x.href.includes('episodios')));
                    return a ? a.href : null; 
                }""")
                if link_todos:
                    print(f"[AniTube] 📂 Indo para 'Todos os Episódios': {link_todos}")
                    await page.goto(link_todos, wait_until="domcontentloaded", timeout=30000)
                    await page.mouse.wheel(0, 1000)
                    await asyncio.sleep(2)
                    eps_raw = await page.evaluate("""() => 
                        Array.from(document.querySelectorAll('a'))
                            .filter(a => a.href.includes('/video/'))
                            .map(a => ({ title: a.title || a.innerText, url: a.href }))
                    """)

            if not eps_raw:
                return None

            # Regex para extrair número do título/URL
            def extract_num(text):
                m = re.search(r'(?:Epis[oó]dio|Ep|Video|Filme|Movie)\s*(\d+)', text, re.IGNORECASE)
                if m: return int(m.group(1))
                # Tenta número isolado no final do título
                m = re.search(r'\b(\d+)\b$', text)
                if m: return int(m.group(1))
                return None

            # Procura o match exato
            for item in eps_raw:
                num = extract_num(item['title'])
                if num == episode_number:
                    print(f"[AniTube] ✅ Encontrado EP {episode_number}: {item['url']}")
                    return item['url']
                # Tenta via URL se o título falhar
                num_url = extract_num(item['url'].split('/')[-1])
                if num_url == episode_number:
                    print(f"[AniTube] ✅ Encontrado EP {episode_number} (pela URL): {item['url']}")
                    return item['url']

            return None
        finally:
            await self.close_browser()
