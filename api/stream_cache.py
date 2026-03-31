"""
stream_cache.py — Extração On-Demand de URLs de Stream

Como funciona:
  1. Usuário clica em play
  2. Player chama GET /api/resolve-stream/{ep_id}
  3. Se a URL está no cache (< 2h), retorna imediatamente
  4. Se não, executa AniTubeProvider.extract_episode(url_origem) com Playwright
  5. Salva no cache por 2h
  6. Retorna a URL fresca para o player

Vantagem: nunca precisamos re-armazenar URLs no banco — elas são extraídas
na hora certa e expiram naturalmente do cache.
"""

import asyncio
import time
import logging
from typing import Optional

logger = logging.getLogger("stream_cache")

# Cache em memória: { episodio_id: {"url": ..., "headers": ..., "ts": float } }
_cache: dict[int, dict] = {}
_locks: dict[int, asyncio.Lock] = {}
_mapping: dict = {}

def _load_mapping():
    global _mapping
    if not _mapping:
        from pathlib import Path
        import json
        mapping_path = Path("mapeamento_animes.json")
        if mapping_path.exists():
            try:
                with open(mapping_path, "r", encoding="utf-8") as f:
                    _mapping = json.load(f)
            except Exception as e:
                logger.error(f"[Cache] ❌ Erro ao carregar mapeamento_animes.json: {e}")
    return _mapping

CACHE_TTL = 60 * 60 * 2  # 2 horas


def _get_lock(ep_id: int) -> asyncio.Lock:
    """Garante que cada episódio tenha seu próprio lock para evitar extrações duplicadas."""
    if ep_id not in _locks:
        _locks[ep_id] = asyncio.Lock()
    return _locks[ep_id]


def get_cached(ep_id: int) -> Optional[dict]:
    """Retorna do cache se a URL ainda for válida (< 2h)."""
    entry = _cache.get(ep_id)
    if entry and (time.time() - entry["ts"]) < CACHE_TTL:
        logger.info(f"[Cache] ✅ Hit para ep {ep_id} — {int((CACHE_TTL - (time.time() - entry['ts'])) / 60)}min restantes")
        return entry
    return None


async def resolve_stream(ep_id: int, url_origem: str) -> dict:
    """
    Resolve a URL de stream on-demand.
    Thread-safe: não faz extração duplicada para o mesmo ep_id.
    """
    # 1. Verifica cache
    cached = get_cached(ep_id)
    if cached:
        return cached

    # 2. Adquire lock para evitar extrações paralelas do mesmo ep
    lock = _get_lock(ep_id)
    async with lock:
        # Double-check após o lock (outro coroutine pode ter preenchido o cache)
        cached = get_cached(ep_id)
        if cached:
            return cached

        logger.info(f"[Cache] 🔄 Extraindo stream on-demand para ep {ep_id}: {url_origem[:60]}...")

        try:
            from scrapers.anitube_provider import AniTubeProvider
            provider = AniTubeProvider()
            result = await provider.extract_episode(url_origem)

            if not result or not result.get("url_stream_original"):
                raise ValueError("Extração retornou resultado vazio")

            entry = {
                "url": result["url_stream_original"],
                "headers": result.get("headers_b64", ""),
                "ts": time.time(),
            }
            _cache[ep_id] = entry
            logger.info(f"[Cache] ✅ Stream salvo no cache para ep {ep_id}")
            return entry

        except Exception as e:
            logger.error(f"[Cache] ❌ Falha na extração para ep {ep_id}: {e}")
            raise


async def resolve_origin_url(anime_titulo: str, ep_numero: int, idioma: str) -> Optional[dict]:
    """
    Busca a URL da página do episódio no Anitube usando o mapeamento ou Live Search.
    Retorna {"page_url": str, "series_url": str} ou None.
    """
    mapping = _load_mapping()
    logger.info(f"[Cache] 🔍 Buscando no mapeamento: '{anime_titulo}' ({len(mapping)} animes carregados)")
    
    anime_data = mapping.get(anime_titulo)
    found_title = anime_titulo

    # 1. Fallback Fuzzy no Mapping
    if not anime_data:
        logger.info(f"[Cache] ⚠️ Match exato falhou para '{anime_titulo}'. Tentando fuzzy...")
        for titulo, data in mapping.items():
            if anime_titulo.lower() in titulo.lower() or titulo.lower() in anime_titulo.lower():
                logger.info(f"[Cache] ✨ Encontrado fuzzy no mapping: '{titulo}'")
                anime_data = data
                found_title = titulo
                break
    
    # 2. Fallback LIVE SEARCH (Busca em tempo real no site)
    from scrapers.anitube_provider import AniTubeProvider
    provider = AniTubeProvider()

    if not anime_data:
        logger.info(f"[Cache] 🔥 Anime '{found_title}' não mapeado. Iniciando LOGIN LIVE SEARCH...")
        search_results = await provider.search_series(anime_titulo)
        if search_results["leg"] or search_results["dub"]:
            logger.info(f"[Cache] ✅ Live Search encontrou resultados para '{anime_titulo}'")
            anime_data = search_results
        else:
            logger.warning(f"[Cache] ❌ Anime '{anime_titulo}' não encontrado nem via Live Search.")
            return None
    
    key = "dub" if "dub" in idioma.lower() else "leg"
    series_urls = anime_data.get(key, [])
    if not series_urls:
        logger.warning(f"[Cache] ⚠️ Anime '{anime_titulo}' sem links para idioma {idioma}.")
        return None
    
    # Busca a URL específica do episódio dentro da página da série
    series_url = series_urls[0]
    logger.info(f"[Cache] 📍 Localizando EP {ep_numero} em {series_url}")
    ep_page_url = await provider.find_episode_url(series_url, ep_numero)
    
    if ep_page_url:
        return {
            "page_url": ep_page_url,
            "series_url": series_url
        }
    return None


def invalidate(ep_id: int):
    """Remove um episódio do cache (forçar nova extração)."""
    _cache.pop(ep_id, None)


def cache_stats() -> dict:
    """Retorna estatísticas do cache para debug."""
    now = time.time()
    valid = sum(1 for e in _cache.values() if (now - e["ts"]) < CACHE_TTL)
    return {
        "total": len(_cache),
        "valid": valid,
        "expired": len(_cache) - valid,
    }
