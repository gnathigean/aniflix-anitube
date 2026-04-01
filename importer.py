"""
Worker de Importação v3.0 — Aniflix (Anti-Furo & Resiliência Total)
Sistema projetado para rodar como Daemon, garantindo integridade 100%.
"""

import asyncio
import json
import re
import string
import os
import logging
import traceback
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import httpx
import argparse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

load_dotenv()

# Configuração de Logs Profissional
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler("importer.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("aniflix_importer")

from database.db import init_db, AsyncSessionLocal, engine
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider

STATUS_FILE = Path("import_status.json")
MAP_FILE = Path("mapeamento_animes.json")
DB_WRITE_LOCK = asyncio.Lock()

# --- UTILITÁRIOS ---

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
    idioma = "Legendado"
    if re.search(r'\(Dublado\)|- Dublado|\bDub\b', raw, re.IGNORECASE): idioma = "Dublado"
    name = re.sub(r'[-–]\s*(?:Epis[oó]dio|Ep|Video|Filme|Movie)\s*\d+.*$', '', raw, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s*[-–]\s*Todos\s+os\s+Epis[oó]dios.*$', '', name, flags=re.IGNORECASE).strip()
    season_match = re.search(r'(?:Season|Temporada|Part|Livro|Fase)\s*(\d+)', name, re.IGNORECASE)
    num_temp = 1
    if season_match:
        num_temp = int(season_match.group(1))
        name = name[:season_match.start()].strip()
    name = re.sub(r'\s*[-–]?\s*\((?:Dublado|Legendado|Dub|Leg|HD|SD|FHD|Fã-Sub|Completo|Bluray)\)', '', name, flags=re.IGNORECASE).strip()
    name = re.sub(r'\s*[-–]?\s*(?:Dublado|Legendado|Dub\b|Leg\b|HD\b|SD\b)', '', name, flags=re.IGNORECASE).strip()
    name = name.strip(' –-')
    return name, num_temp, f"Temporada {num_temp}", idioma

# --- DECORATORS ---

def retry_async(retries=3, delay=5, exceptions=(Exception,)):
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_ex = None
            for i in range(retries):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_ex = e
                    logger.warning(f"⚠️ Falha em {func.__name__} ({i+1}/{retries}): {e}")
                    await asyncio.sleep(delay * (i + 1))
            raise last_ex
        return wrapper
    return decorator

# --- LOGICA DE BANCO ---

@retry_async(retries=5, delay=2)
async def ensure_anime_and_season(nome, metadata=None):
    async with AsyncSessionLocal() as session:
        q = await session.execute(select(Anime).where(Anime.titulo.ilike(nome)))
        anime = q.scalar_one_or_none()
        if not anime:
            anime = Anime(
                titulo=nome,
                url_capa=metadata.get('url_capa', '') if metadata else "",
                sinopse=metadata.get('sinopse', '') if metadata else "",
                ano=metadata.get('ano', '') if metadata else ""
            )
            session.add(anime)
            await session.flush()
        
        q_temp = await session.execute(select(Temporada).where(Temporada.anime_id == anime.id, Temporada.numero == 1))
        temp = q_temp.scalar_one_or_none()
        if not temp:
            temp = Temporada(anime_id=anime.id, numero=1)
            session.add(temp)
            await session.flush()
            
        await session.commit()
        return anime.id, temp.id

@retry_async(retries=5, delay=2)
async def save_episode_to_db(data, anime_id, temp_id, numero, idioma, url_origem):
    async with DB_WRITE_LOCK:
        async with AsyncSessionLocal() as session:
            q = await session.execute(select(Episodio).where(
                Episodio.temporada_id == temp_id, Episodio.numero == numero, Episodio.idioma == idioma
            ))
            existing = q.scalar_one_or_none()
            if existing:
                if existing.url_stream_original: return True # Já tem stream
                existing.url_stream_original = data["url_stream_original"]
                existing.headers_b64 = data.get("headers_b64")
                existing.url_episodio_origem = url_origem
            else:
                ep = Episodio(
                    temporada_id=temp_id,
                    numero=numero,
                    titulo_episodio=f"Episódio {numero}",
                    url_stream_original=data["url_stream_original"],
                    headers_b64=data.get("headers_b64"),
                    idioma=idioma,
                    url_episodio_origem=url_origem
                )
                session.add(ep)
                anime = await session.get(Anime, anime_id)
                if anime:
                    if idioma == "Dublado": anime.qtd_dub = (anime.qtd_dub or 0) + 1
                    else: anime.qtd_leg = (anime.qtd_leg or 0) + 1
            await session.commit()
            return True

# --- FASES DO IMPORTADOR ---

async def fase_scan(status):
    """Fase 1: Mapear todas as URLs de animes do site."""
    map_obras = load_json(MAP_FILE, {})
    status["fase"] = "Mapeamento (Scan)"
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
            logger.info(f"🔍 Iniciando Scan: {cat_nome}")
            
            for letra in alfabeto:
                base_url = f"{cat_url}?letra={letra}"
                logger.info(f"Letra {letra.upper()}...")
                try:
                    await page.goto(base_url, wait_until="domcontentloaded", timeout=30000)
                    # Detecta paginação
                    max_p = await page.evaluate("""() => {
                        let max = 1;
                        document.querySelectorAll('.page-numbers').forEach(a => {
                            const num = parseInt(a.innerText);
                            if(!isNaN(num) && num > max) max = num;
                        });
                        return max;
                    }""")
                    
                    for p in range(1, max_p + 1):
                        p_url = base_url if p == 1 else f"{cat_url}page/{p}/?letra={letra}"
                        await page.goto(p_url, wait_until="domcontentloaded", timeout=30000)
                        anchors = await page.query_selector_all('.aniItem a')
                        for a in anchors:
                            href = await a.get_attribute('href')
                            title = await a.get_attribute('title') or await a.inner_text()
                            if href and '/video/' in href:
                                nome, _, _, _ = parse_titulo(title)
                                if nome not in map_obras: 
                                    map_obras[nome] = {"leg": [], "dub": [], "done": False, "done_episodes": []}
                                if href not in map_obras[nome][idioma_tipo]:
                                    map_obras[nome][idioma_tipo].append(href)
                        
                        status["obras_mapeadas"] = len(map_obras)
                        save_json(STATUS_FILE, status)
                        save_json(MAP_FILE, map_obras)
                except Exception as e:
                    logger.warning(f"Erro na letra {letra}: {e}")
        await browser.close()

async def fase_importacao(status):
    """Fase 2: Importar episódios das obras mapeadas."""
    map_obras = load_json(MAP_FILE, {})
    status["fase"] = "Importação (Massiva)"
    save_json(STATUS_FILE, status)
    
    provider = AniTubeProvider()
    
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        # Processamos em lotes para não estourar memória
        for nome, data in map_obras.items():
            if data.get("done"): continue
            
            logger.info(f"🎬 Iniciando Obra: {nome}")
            aid, tid = await ensure_anime_and_season(nome)
            
            for idioma in ["Legendado", "Dublado"]:
                key = "leg" if idioma == "Legendado" else "dub"
                urls = data.get(key, [])
                if not urls: continue
                
                # Para cada URL de série (podem ser várias partes no site)
                for s_url in urls:
                    try:
                        # Extrai lista de episódios da página da série
                        eps_raw = await provider.list_episodes_from_page(s_url)
                        if not eps_raw: continue
                        
                        # Inverte para importar em ordem (1, 2, 3...)
                        eps_raw.reverse()
                        
                        for i, ep_item in enumerate(eps_raw):
                            ep_url = ep_item['url']
                            if ep_url in data.get("done_episodes", []): continue
                            
                            # Extrai e salva
                            ep_data = await provider.extract_episode(ep_url)
                            if ep_data and ep_data.get("url_stream_original"):
                                success = await save_episode_to_db(ep_data, aid, tid, i+1, idioma, ep_url)
                                if success:
                                    data.setdefault("done_episodes", []).append(ep_url)
                                    status["sucesso"] += 1
                                else: status["erros"] += 1
                            else:
                                status["erros"] += 1
                            
                            save_json(MAP_FILE, map_obras)
                            save_json(STATUS_FILE, status)
                            await asyncio.sleep(0.5) # Anti-block suave
                            
                    except Exception as e:
                        logger.error(f"Erro na obra {nome} ({idioma}): {e}")
            
            data["done"] = True
            save_json(MAP_FILE, map_obras)
        await browser.close()

async def auditoria_integridade(status):
    """Fase 3: Auditoria Profunda (Anti-Furo)."""
    status["fase"] = "Auditoria (Deep Check)"
    status["log_recente"].insert(0, f"🛡️ Iniciando Auditoria Anti-Furo...")
    save_json(STATUS_FILE, status)
    
    mapping = load_json(MAP_FILE, {})
    provider = AniTubeProvider()
    
    async with AsyncSessionLocal() as session:
        # Carrega animes e suas contagens
        result = await session.execute(
            select(Anime).options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
        )
        animes_db = result.scalars().all()
    
    for anime in animes_db:
        anime_map = mapping.get(anime.titulo)
        if not anime_map: continue
        
        for idioma in ["Legendado", "Dublado"]:
            key = "leg" if idioma == "Legendado" else "dub"
            if not anime_map.get(key): continue
            
            temp1 = next((t for t in anime.temporadas if t.numero == 1), None)
            if not temp1: continue
            
            # Pega números existentes no banco
            eps_banco = sorted([e.numero for e in temp1.episodios if e.idioma == idioma])
            if not eps_banco: continue
            
            max_ep = eps_banco[-1]
            furos = [n for n in range(1, max_ep + 1) if n not in eps_banco]
            
            if furos:
                logger.info(f"🧩 FURO DETECTADO em {anime.titulo} ({idioma}): {furos}")
                status["log_recente"].insert(0, f"🔧 Corrigindo {len(furos)} furos em {anime.titulo}")
                save_json(STATUS_FILE, status)
                
                # Tenta re-importar os furos
                for s_url in anime_map[key]:
                    eps_site = await provider.list_episodes_from_page(s_url)
                    eps_site.reverse()
                    for f_num in furos:
                        if f_num <= len(eps_site):
                            ep_meta = eps_site[f_num - 1]
                            logger.info(f"Recuperando: {anime.titulo} Ep {f_num}")
                            ep_data = await provider.extract_episode(ep_meta['url'])
                            if ep_data:
                                await save_episode_to_db(ep_data, anime.id, temp1.id, f_num, idioma, ep_meta['url'])
                                status["sucesso"] += 1
                                save_json(STATUS_FILE, status)

async def run_daemon():
    """Loop Infinito do Daemon v3.0."""
    logger.info("🔥 DAEMON ANIFLIX V3.0 INICIADO")
    await init_db()
    
    while True:
        status = {
            "iniciado_em": datetime.now().isoformat(),
            "obras_mapeadas": 0,
            "sucesso": 0,
            "erros": 0,
            "fase": "Iniciando Ciclo",
            "log_recente": []
        }
        
        try:
            # 1. Scan (Busca novidades e obras que faltam)
            await fase_scan(status)
            
            # 2. Importação (Processa o que está no mapa e não no banco)
            await fase_importacao(status)
            
            # 3. Auditoria (Garante que não ficou nenhum furo pra trás)
            await auditoria_integridade(status)
            
            logger.info("✅ Ciclo de integridade concluído.")
            status["fase"] = "Dormindo (60 min)"
            save_json(STATUS_FILE, status)
            await asyncio.sleep(3600) # Dorme 1 hora entre ciclos
            
        except Exception as e:
            logger.error(f"💥 Falha crítica no Daemon: {e}")
            traceback.print_exc()
            await asyncio.sleep(300) # Espera 5 min antes de tentar de novo após crash

if __name__ == "__main__":
    asyncio.run(run_daemon())
