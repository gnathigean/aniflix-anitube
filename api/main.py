from fastapi import FastAPI, Depends, Request, Response
from typing import Optional
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import desc, func
import uuid, json, asyncio, subprocess, os, stat, base64, time, logging
from pathlib import Path

logger = logging.getLogger("uvicorn")

from database.db import init_db, get_db
from database.models import Anime, Temporada, Episodio, Favorito, Progresso
from api.proxy import router as proxy_router
from api import stream_cache

app = FastAPI(title="AnimeProxy Hub")
app.include_router(proxy_router)
app.mount("/static", StaticFiles(directory="frontend"), name="static")
app.mount("/icons", StaticFiles(directory="frontend/icons"), name="icons")
templates = Jinja2Templates(directory="frontend")

def b64encode_filter(s):
    if not s: return ""
    return base64.urlsafe_b64encode(s.encode()).decode()

templates.env.filters["b64encode"] = b64encode_filter

STATUS_FILE = Path("import_status.json")
_import_proc = None

def get_session_id(request: Request) -> str:
    return request.cookies.get("session_id") or str(uuid.uuid4())

def set_session_cookie(response: Response, sid: str):
    response.set_cookie("session_id", sid, max_age=60*60*24*365, httponly=True, samesite="lax")

# ─── Startup ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    await init_db()
    # Garante permissão de escrita no banco SQLite
    db_path = Path("animes.db")
    if db_path.exists():
        db_path.chmod(0o666)

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    ico_path = Path("frontend/favicon.ico")
    if ico_path.exists():
        return FileResponse(ico_path)
    # Retorna um favicon SVG inline se não houver arquivo físico
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#6d28d9"/><text y="24" x="4" font-size="24">🎌</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")

@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    return FileResponse("frontend/manifest.json", media_type="application/manifest+json")

@app.get("/sw.js", include_in_schema=False)
async def get_sw():
    return FileResponse("frontend/sw.js", media_type="application/javascript")

@app.get("/.well-known/appspecific/com.chrome.devtools.json", include_in_schema=False)
async def devtools_json():
    return JSONResponse({"workspace": {}})

# ─── Páginas HTML ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    sid = get_session_id(request)
    
    # Carregamento Inicial Otimizado (Limitado a 60)
    result = await db.execute(
        select(Anime).order_by(desc(Anime.id)).limit(60)
    )
    animes = result.scalars().all()

    # Seção Bombando (Fallback se views_dia for 0)
    top_dia_r = await db.execute(
        select(Episodio).options(selectinload(Episodio.temporada).selectinload(Temporada.anime))
        .where(Episodio.views_dia > 0)
        .order_by(desc(Episodio.views_dia)).limit(15)
    )
    top_dia = top_dia_r.scalars().all()
    
    if not top_dia:
        # Fallback 1: Animes com mais views totais (coalesce para tratar nulos como 0)
        top_dia_r = await db.execute(
            select(Anime).order_by(desc(func.coalesce(Anime.visualizacoes_total, 0))).limit(15)
        )
        top_dia_animes = top_dia_r.scalars().all()
        # Fallback 2: Se mesmo assim vazio, pega ordenado por ID (mais novos)
        if not top_dia_animes:
            top_dia_r = await db.execute(select(Anime).order_by(desc(Anime.id)).limit(15))
            top_dia_animes = top_dia_r.scalars().all()
    else:
        # Remove duplicatas de animes nos eps que bombam
        seen = set()
        top_dia_animes = []
        for ep in top_dia:
            if ep.temporada.anime_id not in seen:
                top_dia_animes.append(ep.temporada.anime)
                seen.add(ep.temporada.anime_id)

    continuar_r = await db.execute(
        select(Progresso)
        .options(selectinload(Progresso.episodio).selectinload(Episodio.temporada).selectinload(Temporada.anime))
        .where(Progresso.session_id == sid, Progresso.progresso_segundos > 5)
        .order_by(desc(Progresso.atualizado_em)).limit(12)
    )
    continuar = continuar_r.scalars().all()

    fav_r = await db.execute(select(Favorito.anime_id).where(Favorito.session_id == sid))
    fav_ids = set(r[0] for r in fav_r.all())

    resp = templates.TemplateResponse(request=request, name="index.html", context={
        "animes": animes, "top_dia_animes": top_dia_animes, 
        "continuar": continuar, "fav_ids": fav_ids
    })
    set_session_cookie(resp, sid)
    return resp

# --- API Elite Catalog ---
@app.get("/api/animes")
async def get_animes_paginated(
    request: Request,
    q: Optional[str] = None, 
    categoria: Optional[str] = None,
    offset: int = 0, 
    limit: int = 40, 
    db: AsyncSession = Depends(get_db)
):
    sid = get_session_id(request)
    query = select(Anime)

    if q:
        query = query.where(Anime.titulo.ilike(f"%{q}%"))

    if categoria == "filmes":
        # Animes com apenas 1 episódio no total
        subquery = (
            select(Anime.id)
            .join(Anime.temporadas)
            .join(Temporada.episodios)
            .group_by(Anime.id)
            .having(func.count(Episodio.id) == 1)
        )
        query = query.where(Anime.id.in_(subquery))
    elif categoria == "bombando":
        query = query.order_by(desc(Anime.visualizacoes_total))
    elif categoria == "favoritos":
        query = query.join(Anime.favoritos).where(Favorito.session_id == sid)
    else:
        query = query.order_by(desc(Anime.id))

    result = await db.execute(query.offset(offset).limit(limit))
    animes = result.scalars().all()
    return [{"id": a.id, "titulo": a.titulo, "url_capa": a.url_capa, "ano": a.ano, "qtd_leg": a.qtd_leg, "qtd_dub": a.qtd_dub, "visualizacoes_total": a.visualizacoes_total} for a in animes]

@app.post("/api/favoritos/{anime_id}")
async def toggle_favorito(anime_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    sid = get_session_id(request)
    res = await db.execute(select(Favorito).where(Favorito.anime_id == anime_id, Favorito.session_id == sid))
    fav = res.scalar_one_or_none()
    
    if fav:
        await db.delete(fav)
        status = "removed"
    else:
        new_fav = Favorito(anime_id=anime_id, session_id=sid)
        db.add(new_fav)
        status = "added"
    
    await db.commit()
    return {"status": status}

@app.get("/anime/{anime_id}", response_class=HTMLResponse)
async def anime_detail(request: Request, anime_id: int, db: AsyncSession = Depends(get_db)):
    sid = get_session_id(request)
    result = await db.execute(
        select(Anime)
        .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
        .where(Anime.id == anime_id)
    )
    anime = result.scalar_one_or_none()
    if not anime:
        return HTMLResponse("Anime não encontrado", status_code=404)
        
    fav_r = await db.execute(select(Favorito).where(Favorito.session_id == sid, Favorito.anime_id == anime_id))
    is_fav = fav_r.scalar_one_or_none() is not None
    
    # Busca último progresso neste anime
    prog_r = await db.execute(
        select(Progresso)
        .join(Episodio, Progresso.episodio_id == Episodio.id)
        .join(Temporada, Episodio.temporada_id == Temporada.id)
        .where(Temporada.anime_id == anime_id, Progresso.session_id == sid)
        .order_by(desc(Progresso.atualizado_em))
        .limit(1)
    )
    ultimo_progresso = prog_r.scalar_one_or_none()
    
    resp = templates.TemplateResponse(request=request, name="anime.html", context={
        "anime": anime, 
        "is_fav": is_fav,
        "ultimo_progresso": ultimo_progresso
    })
    set_session_cookie(resp, sid)
    return resp

@app.get("/player/{episodio_id}", response_class=HTMLResponse)
async def player(request: Request, episodio_id: int, db: AsyncSession = Depends(get_db)):
    sid = get_session_id(request)
    result = await db.execute(
        select(Episodio)
        .options(selectinload(Episodio.temporada).selectinload(Temporada.anime))
        .where(Episodio.id == episodio_id)
    )
    episodio = result.scalar_one_or_none()
    if not episodio:
        return HTMLResponse("Episódio não encontrado.", status_code=404)
    
    # Carrega o contexto completo do anime para o seletor de temporadas do Aniflix
    anime_result = await db.execute(
        select(Anime)
        .options(selectinload(Anime.temporadas).selectinload(Temporada.episodios))
        .where(Anime.id == episodio.temporada.anime_id)
    )
    full_anime = anime_result.scalar_one_or_none()
    if full_anime:
        episodio.temporada.anime = full_anime

    prog_r = await db.execute(select(Progresso).where(Progresso.episodio_id == episodio_id, Progresso.session_id == sid))
    prog = prog_r.scalar_one_or_none()
    progresso = prog.progresso_segundos if prog else 0
    
    # Busca IDs do próximo e anterior (mesmo idioma e cross-season)
    prev_id = None
    next_id = None
    if full_anime:
        # Coleta todos os episódios de todas as temporadas, ordenados por Temporada -> Episódio
        all_eps = []
        # Ordenamos as temporadas pelo número
        sorted_seasons = sorted(full_anime.temporadas, key=lambda x: x.numero or 0)
        for t in sorted_seasons:
            # Ordenamos os episódios pelo número
            sorted_eps = sorted(t.episodios, key=lambda x: x.numero or 0)
            for e in sorted_eps:
                if e.idioma == episodio.idioma:
                    all_eps.append(e.id)
        
        try:
            curr_idx = all_eps.index(episodio_id)
            if curr_idx > 0: 
                prev_id = all_eps[curr_idx - 1]
            if curr_idx < len(all_eps) - 1: 
                next_id = all_eps[curr_idx + 1]
        except (ValueError, IndexError):
            pass

    resp = templates.TemplateResponse(request=request, name="player.html", context={
        "episodio": episodio, 
        "anime": full_anime, 
        "progresso": progresso,
        "prev_ep_id": prev_id,
        "next_ep_id": next_id
    })
    resp.set_cookie("session_id", sid, max_age=31536000)
    # Evita que o navegador do usuário faça cache do player.html com código de player defasado
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/api/resolve-stream/{episodio_id}")
async def resolve_stream(episodio_id: int, db: AsyncSession = Depends(get_db)):
    """
    Resolve a URL de stream.
    - Cache hit (2h): retorna imediatamente
    - Sem cache: retorna a URL do banco (pode estar expirada)
    - Se url_episodio_origem existe e URL falhar: player deve chamar /api/reextract-stream/{id}
    """
    result = await db.execute(
        select(Episodio)
        .options(selectinload(Episodio.temporada).selectinload(Temporada.anime))
        .where(Episodio.id == episodio_id)
    )
    ep = result.scalar_one_or_none()
    if not ep:
        return JSONResponse({"error": "Episódio não encontrado"}, status_code=404)

    def to_b64(url: str) -> str:
        if not url: return ""
        try:
            decoded = base64.urlsafe_b64decode(url + "==").decode("utf-8")
            if decoded.startswith("http"): return url
        except: pass
        return base64.urlsafe_b64encode(url.encode()).decode()

    # 1. Cache hit → retorna imediatamente
    cached = stream_cache.get_cached(episodio_id)
    if cached:
        return JSONResponse({
            "url_b64": to_b64(cached["url"]),
            "headers_b64": cached["headers"],
            "from_cache": True,
            "can_reextract": True # Sempre marcamos como true agora porque temos o resolver dinâmico
        })

    # 2. Se tem URL no banco, usa ela (pode estar expirada, mas o player tenta)
    if ep.url_stream_original:
        url_b64 = to_b64(ep.url_stream_original)
        return JSONResponse({
            "url_b64": url_b64,
            "headers_b64": ep.headers_b64 or "",
            "from_cache": False,
            "can_reextract": True
        })

    return JSONResponse({"error": "Episódio sem URL de stream. Use /api/reextract-stream para tentar resolver."}, status_code=422)


@app.post("/api/reextract-stream/{episodio_id}")
async def reextract_stream(episodio_id: int, db: AsyncSession = Depends(get_db)):
    """
    Força re-extração da URL via Playwright.
    Se url_episodio_origem faltar, tenta descobrir via mapeamento JSON.
    """
    result = await db.execute(
        select(Episodio)
        .options(selectinload(Episodio.temporada).selectinload(Temporada.anime))
        .where(Episodio.id == episodio_id)
    )
    ep = result.scalar_one_or_none()
    if not ep:
        return JSONResponse({"error": "Episódio não encontrado"}, status_code=404)

    # Invalida cache
    stream_cache.invalidate(episodio_id)

    # 1. Se não tem URL de origem, tenta descobrir via mapeamento ou Live Search
    if not ep.url_episodio_origem:
        try:
            anime_titulo = ep.temporada.anime.titulo
            origin_info = await stream_cache.resolve_origin_url(anime_titulo, ep.numero, ep.idioma or "Legendado")
            if origin_info and origin_info.get("page_url"):
                logger.info(f"[API] ✨ Origem descoberta e salva para ep {episodio_id}: {origin_info['page_url']}")
                ep.url_episodio_origem = origin_info["page_url"]
                await db.commit()
        except Exception as e:
            logger.error(f"[API] Falha crítica ao descobrir origem para ep {episodio_id}: {e}")

    if not ep.url_episodio_origem:
        return JSONResponse({
            "error": "Episódio sem URL de origem e não encontrado no mapeamento. Re-extração impossível."
        }, status_code=422)

    # 2. Com a origem em mãos, extrai o stream
    try:
        entry = await stream_cache.resolve_stream(episodio_id, ep.url_episodio_origem)

        def to_b64(url: str) -> str:
            try:
                decoded = base64.urlsafe_b64decode(url + "==").decode("utf-8")
                if decoded.startswith("http"): return url
            except: pass
            return base64.urlsafe_b64encode(url.encode()).decode()

        url_b64 = to_b64(entry["url"])
        ep.url_stream_original = entry["url"]
        ep.headers_b64 = entry["headers"]
        await db.commit()
        return JSONResponse({
            "url_b64": url_b64, 
            "headers_b64": entry["headers"], 
            "from_cache": False,
            "can_reextract": True
        })
    except asyncio.TimeoutError:
        return JSONResponse({"error": "Re-extração excedeu o tempo limite (Playwright)."}, status_code=504)
    except Exception as e:
        logger.error(f"[API] Erro Fatal em reextract_stream: {e}")
        return JSONResponse({"error": f"Erro interno: {str(e)}"}, status_code=503)


@app.get("/api/cache/stats")
async def cache_stats():
    """Debug: estatísticas do cache de streams."""
    return stream_cache.cache_stats()


@app.post("/api/cache/invalidate/{episodio_id}")
async def cache_invalidate(episodio_id: int):
    """Invalida o cache de um episódio específico (força nova extração)."""
    stream_cache.invalidate(episodio_id)
    return {"ok": True}

@app.get("/importer", response_class=HTMLResponse)
async def importer_page(request: Request):
    return templates.TemplateResponse(request=request, name="importer.html", context={})

# ─── API ──────────────────────────────────────────────────────────────────────

@app.post("/api/view/{episodio_id}")
async def registrar_view(episodio_id: int, db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(
            select(Episodio).options(selectinload(Episodio.temporada).selectinload(Temporada.anime))
            .where(Episodio.id == episodio_id)
        )
        ep = result.scalar_one_or_none()
        if ep:
            ep.views_total = (ep.views_total or 0) + 1
            ep.views_dia = (ep.views_dia or 0) + 1
            ep.views_semana = (ep.views_semana or 0) + 1
            ep.views_mes = (ep.views_mes or 0) + 1
            
            if ep.temporada and ep.temporada.anime:
                anime = ep.temporada.anime
                anime.visualizacoes_total = (anime.visualizacoes_total or 0) + 1
                
            await db.commit()
        return {"ok": True}
    except Exception as e:
        logger.error(f"[API] Erro ao registrar view {episodio_id}: {e}")
        # Retorna 200 para não quebrar o player se apenas a view falhar
        return {"ok": False, "error": "Database busy"}

@app.post("/api/progresso/{episodio_id}")
async def salvar_progresso(episodio_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    sid = get_session_id(request)
    body = await request.json()
    seg = float(body.get("segundos", 0))
    dur = float(body.get("duracao", 0))
    result = await db.execute(select(Progresso).where(Progresso.episodio_id == episodio_id, Progresso.session_id == sid))
    prog = result.scalar_one_or_none()
    if prog:
        prog.progresso_segundos = seg
        prog.duracao_segundos = dur
    else:
        db.add(Progresso(episodio_id=episodio_id, session_id=sid, progresso_segundos=seg, duracao_segundos=dur))
    await db.commit()
    return {"ok": True}

@app.get("/api/search")
async def search(q: str = "", db: AsyncSession = Depends(get_db)):
    if len(q) < 2:
        return []
    result = await db.execute(select(Anime).where(Anime.titulo.ilike(f"%{q}%")).limit(10))
    animes = result.scalars().all()
    return [{"id": a.id, "titulo": a.titulo, "url_capa": a.url_capa} for a in animes]

@app.post("/api/import/start")
async def import_start():
    global _import_proc
    if _import_proc and _import_proc.poll() is None:
        return {"ok": False, "msg": "Já em execução"}
        
    # GARANTIA: Derruba qualquer importador órfão para não ter DB local escrevendo logs
    try:
        subprocess.run(["pkill", "-f", "venv/bin/python importer.py"], check=False)
    except: pass
        
    # Herda o ambiente atual incluindo variaveis do uvicorn como DATABASE_URL
    _import_proc = subprocess.Popen(
        ["venv/bin/python", "importer.py"],
        cwd=str(Path(__file__).parent.parent),
        env=os.environ.copy()
    )
    return {"ok": True, "pid": _import_proc.pid}

# Cache das métricas do banco para evitar derrubar o Supabase com o Polling agressivo do Cliente (2s)
_metrics_cache = {}
_metrics_ts = 0

@app.get("/api/import/status")
async def import_status(db: AsyncSession = Depends(get_db)):
    global _metrics_cache, _metrics_ts
    
    # 1. Carrega Status base do Arquivo (Disco do Worker)
    try:
        if dict_status := json.loads(STATUS_FILE.read_text()) if STATUS_FILE.exists() else None:
            status = dict_status
        else:
            status = {"fase": "aguardando", "total_eps": 0, "processados": 0, "sucesso": 0, "erros": 0}
    except Exception:
        status = {"fase": "aguardando", "erros": 0}

    # 2. Carrega Métricas Globais do Banco (Apenas a cada 10segundos para economizar CPU)
    now = time.time()
    if now - _metrics_ts > 10:
        try:
            from sqlalchemy.sql import func
            res_total = await db.execute(select(func.count(Anime.id)))
            res_dub = await db.execute(select(func.sum(Anime.qtd_dub)))
            res_leg = await db.execute(select(func.sum(Anime.qtd_leg)))
            
            _metrics_cache = {
                "db_obras": res_total.scalar() or 0,
                "db_eps_dub": res_dub.scalar() or 0,
                "db_eps_leg": res_leg.scalar() or 0,
            }
            _metrics_ts = now
        except Exception as e:
            logger.error(f"[API] Falha nas métricas: {e}")
            pass

    # 3. Mesclar as métricas (Worker + Supabase DB)
    status.update(_metrics_cache)
    
    # 4. Calcular Faltantes e Progresso Baseado em Mapeamento vs Banco
    mapped = status.get("obras_mapeadas", 0)
    db_count = status.get("db_obras", 0)
    
    rem = max(0, mapped - db_count)
    if mapped > 0 and db_count > 0:
        status["db_progresso_perc"] = int((db_count / mapped) * 100)
    else:
        status["db_progresso_perc"] = 0
        
    status["db_faltantes"] = rem
    return status
