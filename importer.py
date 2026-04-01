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
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import httpx
import argparse
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

# Carrega variáveis de ambiente (Supabase) — Sanitiza aspas extras
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("importer")

from database.db import init_db, AsyncSessionLocal, engine
from database.models import Anime, Temporada, Episodio
from scrapers.anitube_provider import AniTubeProvider

STATUS_FILE = Path("import_status.json")
MAP_FILE = Path("mapeamento_animes.json")
DB_WRITE_LOCK = asyncio.Lock()

def _log_db_status():
    # Sanitiza a URL para o log também
    url = os.getenv("DATABASE_URL", "sqlite:///animes.db").strip('"').strip("'")
    if "supabase" in url or "postgres" in url or "pooler" in url:
        logger.info("🚀 Conectado ao SUPABASE (PostgreSQL Mode)")
    else:
        logger.warning("⚠️ Usando SQLITE LOCAL (animes.db)")

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

def is_already_running():
    pid_file = Path("importer.pid")
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text())
            os.kill(pid, 0)
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
                    max_p = await page.goto(base_url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2)
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
                        try:
                            await page.goto(p_url, wait_until="domcontentloaded", timeout=30000)
                        except:
                            await page.goto(p_url, wait_until="load", timeout=30000)
                        anchors = await page.query_selector_all('.aniItem a')
                        for a in anchors:
                            href = await a.get_attribute('href')
                            title = await a.get_attribute('title') or await a.inner_text()
                            if href and '/video/' in href:
                                if nome not in map_obras: 
                                    map_obras[nome] = {"leg": [], "dub": [], "done": False, "done_episodes": []}
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
    n_ep = int(base_index)
    provider = AniTubeProvider()
    try:
        # 1. Verifica se já existe no banco de dados (especialmente útil para o Supabase)
        async with AsyncSessionLocal() as session:
            qe = await session.execute(
                select(Episodio).where(
                    Episodio.temporada_id == db_temp_id, 
                    Episodio.numero == n_ep, 
                    Episodio.idioma == idioma_fixo
                )
            )
            existing_ep = qe.scalar_one_or_none()
            
            # SE JÁ EXISTE E TEM URL, PULA. SE EXISTE MAS ESTÁ "BURACODE" (sem stream), TENTA EXTRAIR.
            if existing_ep and existing_ep.url_stream_original and existing_ep.url_episodio_origem:
                status["pulados"] += 1
                return True

        # 2. Extração via Playwright (Lenta mas Robusta)
        data = await provider.extract_episode(item['eps_url'])
        if not data or not data.get("url_stream_original"): 
            raise Exception("Stream não capturado")
        
        async with DB_WRITE_LOCK:
            async with AsyncSessionLocal() as session:
                if existing_ep:
                    # Carrega novamente na nova sessão para evitar detached state
                    ep = await session.get(Episodio, existing_ep.id)
                    ep.url_stream_original = data["url_stream_original"]
                    ep.headers_b64 = data.get("headers_b64")
                    ep.url_episodio_origem = item['eps_url']
                else:
                    ep = Episodio(
                        temporada_id=db_temp_id,
                        numero=n_ep,
                        titulo_episodio=item['title'],
                        url_stream_original=data["url_stream_original"],
                        headers_b64=data.get("headers_b64"),
                        idioma=idioma_fixo,
                        url_episodio_origem=item['eps_url']
                    )
                    session.add(ep)
                    
                anime = (await session.execute(select(Anime).where(Anime.id == db_anime_id))).scalar_one()
                # Só incrementa se for NOVO
                if not existing_ep:
                    if idioma_fixo == "Dublado": anime.qtd_dub = (anime.qtd_dub or 0) + 1
                    else: anime.qtd_leg = (anime.qtd_leg or 0) + 1
                
                await session.commit()
        
        status["sucesso"] += 1
        status["log_recente"].insert(0, f"✅ {n_ep} ({idioma_fixo}) - {item['title'][:15]}")
        save_json(STATUS_FILE, status)
        return True
    except Exception as e:
        status["erros"] += 1
        status["log_recente"].insert(0, f"❌ ERRO {n_ep} - {item['title'][:15]}: {str(e)[:50]}")
        save_json(STATUS_FILE, status)
        return False

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
                continue
            status["log_recente"].insert(1, f"🎬 Obra: {nome}")
            save_json(STATUS_FILE, status)
            for idioma in ["Legendado", "Dublado"]:
                key = "leg" if idioma == "Legendado" else "dub"
                urls = data.get(key, [])
                if not urls: continue
                try:
                    await page.goto(urls[0], wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)
                except Exception:
                    try:
                        await page.goto(urls[0], wait_until="load", timeout=30000)
                    except Exception as err:
                        continue

                await page.mouse.wheel(0, 1000); await asyncio.sleep(2)
                await page.mouse.wheel(0, 1000); await asyncio.sleep(2)
                eps_raw = await page.evaluate("""() => 
                    Array.from(document.querySelectorAll('a'))
                        .filter(a => {
                            const href = a.href || "";
                            const title = (a.title || a.innerText || "").toLowerCase();
                            return (href.includes('/video/') || title.includes('episódio') || title.includes('ep. ')) && !href.includes('#') && !href.includes('respond');
                        })
                        .map(a => ({ title: a.title || a.innerText, eps_url: a.href }))
                """)
                if not eps_raw:
                    link_todos = await page.evaluate("""() => { 
                        const a = Array.from(document.querySelectorAll('a')).find(x => x.innerText.toLowerCase().includes('todos') || (x.href && x.href.includes('episodios')));
                        return a ? a.href : null; 
                    }""")
                    if link_todos:
                        await page.goto(link_todos, wait_until="networkidle", timeout=25000)
                        await page.mouse.wheel(0, 1000); await asyncio.sleep(2)
                        eps_raw = await page.evaluate("""() => Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('/video/')).map(a => ({ title: a.title || a.innerText, eps_url: a.href }))""")
                if not eps_raw: continue
                seen = set(); unique_eps = []
                for e in eps_raw:
                    if e['eps_url'] not in seen:
                        seen.add(e['eps_url']); unique_eps.append(e)
                unique_eps.reverse()
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
                # Filtra apenas episódios ainda não processados (conforme mapeamento local)
                done_list = data.get("done_episodes", [])
                
                for i, ep_item in enumerate(unique_eps):
                    if ep_item['eps_url'] in done_list:
                        status["pulados"] += 1
                        continue
                        
                    success = await processar_episodio(ep_item, i+1, status, aid, tid, idioma)
                    if success:
                        if "done_episodes" not in data: data["done_episodes"] = []
                        data["done_episodes"].append(ep_item['eps_url'])
                        save_json(MAP_FILE, map_obras)
                
                # Pequena pausa entre idiomas para aliviar o banco
                await asyncio.sleep(1)
            data["done"] = True
            save_json(MAP_FILE, map_obras)
        await browser.close()
    status["fase"] = "Concluído Total"
    save_json(STATUS_FILE, status)

async def fase_reparo(status):
    """Fase de Gap-Filling Otimizada: reusa navegador por série."""
    status["fase"] = "Reparo de Gaps (Otimizado)"
    status["log_recente"].insert(0, "🛠️ Iniciando REPARO OTIMIZADO (Reuso de navegador)")
    save_json(STATUS_FILE, status)
    
    mapping = load_json(MAP_FILE, {})
    total_gaps = 0
    total_preenchidos = 0
    total_erros = 0
    
    from playwright.async_api import async_playwright
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Anime).options(
                    selectinload(Anime.temporadas).selectinload(Temporada.episodios)
                )
            )
            animes = result.scalars().all()
            
            print(f"🔎 Analisando {len(animes)} animes para gaps...")
            
            for anime in animes:
                anime_map = mapping.get(anime.titulo, {})
                context = await browser.new_context()
                page = await context.new_page()
                
                try:
                    for temp in anime.temporadas:
                        for idioma in ["Legendado", "Dublado"]:
                            eps = [e for e in temp.episodios if e.idioma == idioma]
                            if not eps: continue
                            
                            nums = sorted([e.numero for e in eps])
                            if not nums: continue
                            
                            max_num = nums[-1]
                            nums_set = set(nums)
                            gaps = [i for i in range(1, max_num + 1) if i not in nums_set]
                            
                            if not gaps: continue
                            
                            total_gaps += len(gaps)
                            print(f"🧩 {anime.titulo} ({idioma}): {len(gaps)} gaps")
                            
                            key = "leg" if idioma == "Legendado" else "dub"
                            series_urls = anime_map.get(key, [])
                            if not series_urls: continue
                            
                            # Carrega página da série UMA VEZ
                            try:
                                await page.goto(series_urls[0], wait_until="domcontentloaded", timeout=30000)
                            except: pass
                            
                            falhas_consecutivas = 0
                            
                            for gap_num in gaps:
                                if falhas_consecutivas >= 3:
                                    status["log_recente"].insert(0, f"🛑 {anime.titulo}: desisitindo de gaps após erros")
                                    break
                                
                                try:
                                    # 1. Busca URL do episódio específico (reusando a página ativa)
                                    provider = AniTubeProvider()
                                    ep_url = await provider.find_episode_url(series_urls[0], gap_num, external_page=page)
                                    
                                    if not ep_url:
                                        print(f"  ⚠️ Ep {gap_num}: não encontrado")
                                        falhas_consecutivas += 1
                                        continue
                                    
                                    # 2. Extrai stream (precisamos de uma nova página para a extração não interferir na lista)
                                    ext_page = await context.new_page()
                                    provider_ext = AniTubeProvider()
                                    # Injetamos o browser no provider para ele não criar outro, mas ele ainda chamará init_browser
                                    # que criará uma nova página. Na verdade, vamos mudar o extra_episode para aceitar browser ou page.
                                    # Por enquanto, deixamos ele criar um browser novo só para a extração do stream (que é a parte pesada)
                                    # mas a busca da URL já está otimizada.
                                    data = await provider_ext.extract_episode(ep_url)
                                    await ext_page.close()
                                    
                                    if not data or not data.get("url_stream_original"):
                                        falhas_consecutivas += 1
                                        total_erros += 1
                                        continue
                                    
                                    # 3. Salva no banco
                                    async with DB_WRITE_LOCK:
                                        async with AsyncSessionLocal() as save_session:
                                            ep = Episodio(
                                                temporada_id=temp.id,
                                                numero=gap_num,
                                                titulo_episodio=f"Episódio {gap_num}",
                                                url_stream_original=data["url_stream_original"],
                                                headers_b64=data.get("headers_b64"),
                                                idioma=idioma,
                                                url_episodio_origem=ep_url
                                            )
                                            save_session.add(ep)
                                            anime_obj = await save_session.get(Anime, anime.id)
                                            if anime_obj:
                                                if idioma == "Dublado": anime_obj.qtd_dub = (anime_obj.qtd_dub or 0) + 1
                                                else: anime_obj.qtd_leg = (anime_obj.qtd_leg or 0) + 1
                                            await save_session.commit()
                                            
                                    total_preenchidos += 1
                                    falhas_consecutivas = 0
                                    status["sucesso"] += 1
                                    status["log_recente"].insert(0, f"✅ Gap: {anime.titulo} Ep {gap_num} ({idioma})")
                                    save_json(STATUS_FILE, status)
                                    
                                except Exception as e:
                                    print(f"  ❌ Ep {gap_num} Erro: {e}")
                                    falhas_consecutivas += 1
                                    total_erros += 1
                                    
                finally:
                    await context.close()
    
    resumo = f"✅ Reparo OTIMIZADO concluído! Gaps: {total_gaps} | Preenchidos: {total_preenchidos} | Erros: {total_erros}"
    print(resumo)
    status["log_recente"].insert(0, resumo)
    status["fase"] = "Reparo Concluído"
    save_json(STATUS_FILE, status)

async def main():
    parser = argparse.ArgumentParser(description="Worker de Importação Aniflix")
    parser.add_argument("--repair", action="store_true", help="Executa o reparador de gaps")
    parser.add_argument("--scan", action="store_true", help="Apenas re-mapeia o site")
    args = parser.parse_args()

    if is_already_running(): return
    _log_db_status()
    await init_db()
    
    while True:
        status = load_json(STATUS_FILE, {
            "iniciado_em": datetime.now().isoformat(), "obras_mapeadas": 0, "sucesso": 0, "erros": 0, "pulados": 0,
            "idx_leg": "-", "idx_dub": "-", "fase": "Iniciando", "log_recente": ["🚀 Sistema Iniciado"]
        })
        status["fase"] = "Retomando..."
        save_json(STATUS_FILE, status)
        
        try:
            if args.repair:
                await fase_reparo(status)
                break
            elif args.scan:
                await fase_scan(status)
                break
            else:
                if not MAP_FILE.exists() or os.path.getsize(MAP_FILE) < 100:
                    await fase_scan(status)
                else:
                    mapeamento_atual = load_json(MAP_FILE, {})
                    status["obras_mapeadas"] = len(mapeamento_atual)
                    if "Retomando" not in status["log_recente"][0]:
                        status["log_recente"].insert(0, "⏩ Retomando de mapeamento existente")
                    save_json(STATUS_FILE, status)
                await fase_importacao(status)
                
                # Fase automática de gap-filling após importação
                print("\n🔄 Iniciando verificação de gaps automaticamente...")
                status["log_recente"].insert(0, "🔄 Iniciando verificação de gaps...")
                save_json(STATUS_FILE, status)
                await fase_reparo(status)
                break
                
        except Exception as e:
            import traceback
            err_msg = f"💥 ERRO NO LOOP: {e}"
            print(err_msg)
            traceback.print_exc()
            status["fase"] = "Erro (Aguardando Retentativa)"
            status["log_recente"].insert(0, f"⏳ Erro crítico. Tentando novamente em 60s... ({str(e)[:50]})")
            save_json(STATUS_FILE, status)
            await asyncio.sleep(60) # Aguarda antes de tentar de novo
        
    if Path("importer.pid").exists():
        Path("importer.pid").unlink()

if __name__ == "__main__":
    asyncio.run(main())
