"""
Worker de Importação v2.0 — AnimeProxy
Fase 1: Mapeamento Total (A-Z) -> mapeamento_animes.json
Fase 2: Importação Serial (Obra por Obra)
"""

import asyncio
import json
import re
import string
import os
import base64
from datetime import datetime
from pathlib import Path
import httpx
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from sqlalchemy.future import select

from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider

STATUS_FILE = Path("import_status.json")
MAP_FILE = Path("mapeamento_animes.json")
DB_WRITE_LOCK = asyncio.Lock()

def _fix_db_permissions():
    db_path = Path("animes.db")
    if db_path.exists():
        db_path.chmod(0o666)

def save_json(path, data):
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

def load_json(path, default):
    if not path.exists(): return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except: return default

def parse_titulo(raw: str):
    # Remove lixo comum e normaliza para unificação
    idioma = "Legendado"
    if re.search(r'\(Dublado\)|- Dublado|\bDub\b', raw, re.IGNORECASE): idioma = "Dublado"
    
    # Remove EP/Video/Filme e números
    name = re.sub(r'[-–]\s*(?:Epis[oó]dio|Ep|Video|Filme|Movie)\s*\d+.*$', '', raw, flags=re.IGNORECASE).strip()
    # Remove "Todos os Episódios"
    name = re.sub(r'\s*[-–]\s*Todos\s+os\s+Epis[oó]dios.*$', '', name, flags=re.IGNORECASE).strip()
    
    # Detecta Temporada e remove do nome base
    season_match = re.search(r'(?:Season|Temporada|Part|Livro|Fase)\s*(\d+)', name, re.IGNORECASE)
    num_temp = 1
    if season_match:
        num_temp = int(season_match.group(1))
        name = name[:season_match.start()].strip()
    
    # Limpeza radical de sufixos
    name = re.sub(r'\s*[-–]?\s*\((?:Dublado|Legendado|Dub|Leg|HD|SD|FHD|Fã-Sub|Completo|Bluray)\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s*[-–]?\s*(?:Dublado|Legendado|Dub\b|Leg\b|HD\b|SD\b)', '', name, flags=re.IGNORECASE).strip()
    
    # Remove espaços extras e pontuação final
    name = name.strip(' –-')
    
    return name, num_temp, f"Temporada {num_temp}", idioma

def is_already_running():
    pid_file = Path("importer.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            os.kill(pid, 0) # Checa se processo ainda existe
            return True
        except (ProcessLookupError, ValueError):
            pass
    pid_file.write_text(str(os.getpid()))
    return False

def extrair_ep_clemente(titulo: str, fallback_index: int) -> int:
    m = re.search(r'(?:Epis[oó]dio|Ep\.|Ep|Video)\s*(\d+)', titulo, re.IGNORECASE)
    if m: return int(m.group(1))
    t_limpo = re.sub(r'[\(\[][^\]\)]+[\)\]]', '', titulo).strip()
    m2 = re.search(r'\b(\d+)\b', t_limpo)
    return int(m2.group(1)) if m2 else fallback_index

async def fetch_mal_metadata(titulo: str):
    try:
        query = parse_titulo(titulo)[0]
        url = f"https://api.jikan.moe/v4/anime?q={query}&limit=1"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data'):
                    mal = data['data'][0]
                    return {
                        "sinopse": mal.get('synopsis', ''),
                        "url_capa": mal.get('images', {}).get('jpg', {}).get('large_image_url', ''),
                        "ano": str(mal.get('year') or (mal.get('aired', {}).get('from') or '')[:4])
                    }
    except: pass
    return None

async def get_total_pages(page, url):
    await page.goto(url, wait_until="domcontentloaded", timeout=25000)
    await asyncio.sleep(2)
    return await page.evaluate("""() => {
        let max = 1;
        document.querySelectorAll('.page-numbers').forEach(a => {
            const num = parseInt(a.innerText);
            if(!isNaN(num) && num > max) max = num;
        });
        return max;
    }""")

async def fase_scan(status):
    map_obras = load_json(MAP_FILE, {})
    status["fase"] = "Mapeamento (A-Z)"
    save_json(STATUS_FILE, status)
    
    categories = [
        ("Legendados", "https://www.anitube.news/lista-de-animes-legendados-online/"),
        ("Dublados", "https://www.anitube.news/lista-de-animes-dublados-online/")
    ]
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        
        alfabeto = list(string.ascii_lowercase) + ['0-9']
        for cat_nome, cat_url in categories:
            idioma_tipo = "leg" if "Legendados" in cat_nome else "dub"
            status["log_recente"].insert(0, f"🔍 Varrendo {cat_nome}...")
            save_json(STATUS_FILE, status)
            
            for letra in alfabeto:
                base_url = f"{cat_url}?letra={letra}"
                status[f"idx_{idioma_tipo}"] = f"Letra {letra.upper()}"
                save_json(STATUS_FILE, status)
                try:
                    max_p = await get_total_pages(page, base_url)
                    for p in range(1, max_p + 1):
                        p_url = base_url if p == 1 else f"{cat_url}page/{p}/?letra={letra}"
                        try:
                            await page.goto(p_url, wait_until="domcontentloaded", timeout=30000)
                            await asyncio.sleep(1) # Pequena pausa para garantir injeção de elementos
                        except:
                            await page.goto(p_url, wait_until="load", timeout=30000)
                        anchors = await page.query_selector_all('.aniItem a')
                        for a in anchors:
                            href = await a.get_attribute('href')
                            title = await a.get_attribute('title') or await a.inner_text()
                            if href and '/video/' in href:
                                nome, _, _, _ = parse_titulo(title)
                                if nome not in map_obras: map_obras[nome] = {"leg": [], "dub": [], "done": False}
                                if href not in map_obras[nome][idioma_tipo]:
                                    map_obras[nome][idioma_tipo].append(href)
                        status["obras_mapeadas"] = len(map_obras)
                        save_json(STATUS_FILE, status)
                        save_json(MAP_FILE, map_obras)
                except: pass
        await browser.close()
    status["fase"] = "Mapeamento Concluído"
    save_json(STATUS_FILE, status)

async def processar_episodio(item, base_index, status, db_anime_id, db_temp_id, idioma_fixo):
    provider = AniTubeProvider()
    try:
        n_ep = extrair_ep_clemente(item['title'], base_index)
        async with AsyncSessionLocal() as session:
            qe = await session.execute(select(Episodio).where(Episodio.temporada_id == db_temp_id, Episodio.numero == n_ep, Episodio.idioma == idioma_fixo))
            if qe.scalar_one_or_none():
                status["pulados"] += 1
                status["log_recente"].insert(0, f"◽ Pulado: Ep {n_ep} já existe.")
                save_json(STATUS_FILE, status)
                return

        data = await provider.extract_episode(item['eps_url'])
        if not data or not data.get("url_stream_original"): raise Exception("Stream não capturado")
        
        async with DB_WRITE_LOCK:
            _fix_db_permissions()
            async with AsyncSessionLocal() as session:
                ep = Episodio(
                    temporada_id=db_temp_id,
                    numero=n_ep,
                    titulo_episodio=item['title'],
                    url_stream_original=data["url_stream_original"],
                    headers_b64=data["headers_b64"],
                    idioma=idioma_fixo,
                    url_episodio_origem=item['eps_url']  # URL da página Anitube para re-extração on-demand
                )
                session.add(ep)
                anime = (await session.execute(select(Anime).where(Anime.id == db_anime_id))).scalar_one()
                if idioma_fixo == "Dublado": anime.qtd_dub = (anime.qtd_dub or 0) + 1
                else: anime.qtd_leg = (anime.qtd_leg or 0) + 1
                await session.commit()
        
        status["sucesso"] += 1
        status["log_recente"].insert(0, f"✅ {n_ep} ({idioma_fixo}) - {item['title'][:15]}")
        save_json(STATUS_FILE, status)
    except Exception as e:
        status["erros"] += 1
        status["log_recente"].insert(0, f"❌ ERRO {item['title'][:15]}: {e}")
        save_json(STATUS_FILE, status)

async def fase_importacao(status):
    map_obras = load_json(MAP_FILE, {})
    status["fase"] = "Importação Ativa"
    save_json(STATUS_FILE, status)
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        await Stealth().apply_stealth_async(page)
        
        for nome, data in map_obras.items():
            if data.get("done"):
                status["pulados"] += 1
                status["log_recente"].insert(0, f"◽ Pulado: {nome} (já concluído)")
                save_json(STATUS_FILE, status)
                continue
            status["log_recente"].insert(0, f"🎬 Obra: {nome}")
            save_json(STATUS_FILE, status)
            
            for idioma in ["Legendado", "Dublado"]:
                key = "leg" if idioma == "Legendado" else "dub"
                urls = data.get(key, [])
                if not urls: continue
                
                # Espera o carregamento real da rede e dá um tempo para o JS injetar links
                try:
                    await page.goto(urls[0], wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
                except:
                    await page.goto(urls[0], wait_until="load", timeout=30000)
                
                await page.mouse.wheel(0, 1000); await asyncio.sleep(2)  # Trigger Lazy Load
                
                # Busca episódios na página atual — FILTRANDO LIXO (#respond, #, etc)
                eps_raw = await page.evaluate("""() => 
                    Array.from(document.querySelectorAll('a'))
                        .filter(a => a.href.includes('/video/') && !a.href.includes('#') && !a.href.includes('respond') && !a.href.includes('edit'))
                        .map(a => ({ title: a.title || a.innerText, eps_url: a.href }))
                """)
                
                # Se não achou EP, tenta o link "Todos os Episódios" ou link de Lista (hamburguer)
                if not eps_raw:
                    link_todos = await page.evaluate("""() => { 
                        const a = Array.from(document.querySelectorAll('a')).find(x => x.innerText.toLowerCase().includes('todos') || (x.href && x.href.includes('episodios')));
                        return a ? a.href : null; 
                    }""")
                    if link_todos:
                        await page.goto(link_todos, wait_until="networkidle", timeout=25000)
                        await page.mouse.wheel(0, 1000); await asyncio.sleep(2)
                        eps_raw = await page.evaluate("""() => Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('/video/')).map(a => ({ title: a.title || a.innerText, eps_url: a.href }))""")

                if not eps_raw:
                    status["log_recente"].insert(0, f"⚠️ Nenhum EP em {idioma} para {nome}")
                    save_json(STATUS_FILE, status)
                    continue
                
                # Remove duplicados e inverte
                seen = set(); unique_eps = []
                for e in eps_raw:
                    if e['eps_url'] not in seen:
                        seen.add(e['eps_url']); unique_eps.append(e)
                unique_eps.reverse()

                # DB Init
                async with DB_WRITE_LOCK:
                    async with AsyncSessionLocal() as session:
                        anime = (await session.execute(select(Anime).where(Anime.titulo.ilike(nome)))).scalar_one_or_none()
                        if not anime:
                            mal = await fetch_mal_metadata(nome)
                            anime = Anime(titulo=nome, url_capa=mal['url_capa'] if mal else "", sinopse=mal['sinopse'] if mal else "", ano=mal['ano'] if mal else "")
                            session.add(anime); await session.flush()
                        temp = (await session.execute(select(Temporada).where(Temporada.anime_id == anime.id, Temporada.numero == 1))).scalar_one_or_none()
                        if not temp:
                            temp = Temporada(anime_id=anime.id, numero=1)
                            session.add(temp); await session.flush()
                        await session.commit()
                        aid, tid = anime.id, temp.id

                # Episódios Sequenciais para não sobrecarregar
                for i, ep_item in enumerate(eps_raw):
                    await processar_episodio(ep_item, i+1, status, aid, tid, idioma)
            
            data["done"] = True
            save_json(MAP_FILE, map_obras)
        await browser.close()
    status["fase"] = "Concluído Total"
    save_json(STATUS_FILE, status)

async def main():
    if is_already_running():
        print("❌ Já existe uma instância do importador em execução. Abortando.")
        return

    await init_db()
    status = {
        "iniciado_em": datetime.now().isoformat(), "obras_mapeadas": 0, "sucesso": 0, "erros": 0, "pulados": 0,
        "idx_leg": "-", "idx_dub": "-", "fase": "Iniciando", "log_recente": ["🚀 Sistema Iniciado"]
    }
    save_json(STATUS_FILE, status)
    
    try:
        # Pula scan se mapeamento já existir para ganhar tempo
        if not MAP_FILE.exists() or os.path.getsize(MAP_FILE) < 100:
            await fase_scan(status)
        else:
            status["obras_mapeadas"] = len(load_json(MAP_FILE, {}))
            status["log_recente"].insert(0, "⏩ Pulando mapeamento (arquivo já existe)")
            save_json(STATUS_FILE, status)
            
        await fase_importacao(status)
    finally:
        if Path("importer.pid").exists():
            Path("importer.pid").unlink()

if __name__ == "__main__":
    asyncio.run(main())
