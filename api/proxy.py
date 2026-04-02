import base64
import json
import httpx
import random
import asyncio
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException, Response, Depends
from fastapi.responses import StreamingResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import urllib.parse

from database.db import get_db
from database.models import Episodio
from api import stream_cache

router = APIRouter()

def pad_b64(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)

@router.get("/stream")
async def proxy_stream(
    request: Request, 
    url_b64: str, 
    headers_b64: str = "", 
    episodio_id: Optional[int] = None,
    retry: int = 0,
    db: AsyncSession = Depends(get_db)
):
    # Decodifica a URL origial a partir de base64 urlsafe
    try:
        url = base64.urlsafe_b64decode(pad_b64(url_b64).encode()).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=422, detail="Erro ao decodificar url_b64")

    headers = {}
    if headers_b64:
        try:
            # Normaliza para lowercase para facilitar a checagem
            headers_str = base64.urlsafe_b64decode(pad_b64(headers_b64).encode()).decode("utf-8")
            raw_headers = json.loads(headers_str)
            headers = {k.lower(): v for k, v in raw_headers.items()}
        except Exception:
            pass
            
    # Fallback user agents para mascaramento
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
    ]
    
    # SANEAMENTO DE HEADERS: Filtramos apenas o essencial que causa conflito e retira Client Hints do HeadlessChrome
    forbidden_headers = [
        "host", "connection", "accept-encoding", 
        "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"
    ]
    headers = {k: v for k, v in headers.items() if k not in forbidden_headers}

    # Fallback caso os headers extraídos pelo bot não tenham User-Agent/Referer
    if "user-agent" not in headers:
        headers["user-agent"] = random.choice(user_agents)
    
    if "referer" not in headers:
        # Tenta inferir referer do domínio se nada foi passado
        from urllib.parse import urlparse
        parsed = urlparse(url)
        headers["referer"] = f"{parsed.scheme}://{parsed.netloc}/"
    
    # Accept necessário para alguns CDNs
    if "accept" not in headers:
        headers["accept"] = "*/*"

    # Repassa o cabeçalho Range para suportar Pular Abertura (Seek de vídeo)
    range_header = request.headers.get("Range")
    if range_header:
        # Normalize para lowercase e evite chaves duplicadas (Ex: 'range' e 'Range' fariam o Google dar error 400)
        if "Range" in headers: del headers["Range"]
        if "range" in headers: del headers["range"]
        headers["range"] = range_header

    # Headers de bypass extras para servidores OVH/ip-51
    if "ip-51-79-82" in url or ".net" in url:
        headers["sec-fetch-dest"] = "video"
        headers["sec-fetch-mode"] = "cors"
        headers["sec-fetch-site"] = "cross-site"
        headers["origin"] = "https://www.anitube.news"

    # Cliente LOCAL para não multiplexar conexões no GoogleVideo
    local_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=25.0, read=90.0, write=30.0, pool=15.0),
        verify=False,
        http2=False,  # BUG H2 FASTAPI: Causa deadlock no stream de vídeo!
        follow_redirects=True
    )

    try:
        print(f"[Proxy] 🔄 Streaming (Timeout 25s): {url[:60]}...")
        req = local_client.build_request("GET", url, headers=headers)
        response = await local_client.send(req, stream=True)

        if response.status_code in [403, 404, 410]:
            print(f"[Proxy] ⚠️ Link expirou ou foi bloqueado (HTTP {response.status_code}). Notificando frontend via 410.")
            await response.aclose()
            await local_client.aclose()
            raise HTTPException(status_code=410, detail="O link original expirou. Por favor, recarregue a página para re-extrair.")

        if response.status_code >= 400:
            error_body = await response.aread()
            print(f"[Proxy] ❌ Erro {response.status_code} no host original: {url[:100]}")
            await response.aclose()
            await local_client.aclose()
            # Retorna 410 (Gone) para sinalizar que o link expirou e precisa ser re-extraído
            raise HTTPException(status_code=410, detail=f"O link expirou ou é inválido (Origem: {response.status_code})")

        with open("/tmp/proxy_trace.txt", "w") as f:
            f.write(f"SUCCESS!\nSTATUS: {response.status_code}\nCONTENT-TYPE: {response.headers.get('content-type')}\nHEADERS SENT: {headers}\nRESPONSE HEADERS: {response.headers}\n")

        # Repassa cabeçalhos essenciais para vídeo
        resp_headers = {}
        for key in ["content-type", "content-length", "content-range", "accept-ranges", "cache-control"]:
            if key in response.headers:
                resp_headers[key] = response.headers[key]
                
        # Correção extra para Range requests
        if response.status_code == 200 and range_header:
            response.status_code = 206
            if "content-range" not in resp_headers:
                length = resp_headers.get("content-length", "*")
                start = range_header.replace("bytes=", "").split("-")[0]
                resp_headers["content-range"] = f"bytes {start}-{length}/{length}"

        ctype = response.headers.get("content-type", "").lower()
        if "text/html" in ctype and ".m3u8" not in url.lower():
            print(f"[Proxy] ⚠️ Servidor de origem retornou HTML em vez de vídeo: {url[:80]}...")
            await response.aclose()
            await local_client.aclose()
            raise HTTPException(status_code=502, detail="Servidor de origem retornou conteúdo inválido")

        is_m3u8 = "mpegurl" in ctype or ".m3u8" in url.lower()
        
        if is_m3u8:
            try:
                raw_content = await response.aread()
                text = raw_content.decode("utf-8", errors="ignore")
                
                # IMPORTANTE: SEMPRE fechar antes de processar pesado para evitar leaking
                if not response.is_closed: await response.aclose()
                if not local_client.is_closed: await local_client.aclose()
                
                if not text.strip().startswith("#EXTM3U"):
                    return Response(content=raw_content, media_type=ctype)

                new_lines = []
                for line in text.splitlines():
                    if line.startswith("#") or not line.strip():
                        new_lines.append(line)
                    else:
                        if not line.startswith("http"):
                             # Resolve URLs relativas
                            base = url.rsplit("/", 1)[0]
                            line = f"{base}/{line}"
                        
                        part_b64 = base64.urlsafe_b64encode(line.encode()).decode().replace("=", "")
                        part_proxy = f"/stream?url_b64={part_b64}&headers_b64={headers_b64}"
                        new_lines.append(part_proxy)
                        
                return Response(content="\n".join(new_lines), media_type="application/vnd.apple.mpegurl")
            except Exception as e:
                print(f"[Proxy] ⚠️ Falha ao processar M3U8: {e}")
                # Se ainda tivermos o binário, retornamos ele
                if 'raw_content' in locals() and raw_content:
                    return Response(content=raw_content, media_type=ctype)
                raise

        else:
            # Arquivo binário (Segmento de Vídeo .ts ou .mp4), retorna via Stream
            async def stream_generator():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    if not response.is_closed:
                        await response.aclose()
                    if not local_client.is_closed:
                        await local_client.aclose()

            return StreamingResponse(
                stream_generator(),
                status_code=response.status_code,
                headers=resp_headers
            )

    except HTTPException as e:
        # Se for erro de link expirado (410) ou proibido e tivermos EP_ID, tentamos auto-reparo
        if e.status_code in [403, 404, 410] and episodio_id and retry < 2:
            logger_uv = logging.getLogger("uvicorn")
            logger_uv.warning(f"[Proxy] 🔄 Auto-reparo disparado para EP {episodio_id} após erro {e.status_code} (Tentativa {retry+1})")
            try:
                # 1. Busca episódio no DB para ter a URL de origem
                result = await db.execute(
                    select(Episodio).where(Episodio.id == episodio_id)
                )
                ep = result.scalar_one_or_none()
                if ep and ep.url_episodio_origem:
                    # 2. Invalida cache e re-extrai
                    stream_cache.invalidate(episodio_id)
                    entry = await stream_cache.resolve_stream(episodio_id, ep.url_episodio_origem)
                    
                    # 3. Redireciona para o novo link (incrementando o retry)
                    new_url_b64 = base64.urlsafe_b64encode(entry["url"].encode()).decode().replace("=", "")
                    new_headers_b64 = entry["headers"] # Já vem em b64 do resolve_stream
                    
                    # Logamos o sucesso
                    logger_uv.info(f"[Proxy] ✨ Auto-reparo bem sucedido para EP {episodio_id}. Redirecionando...")
                    return RedirectResponse(url=f"/stream?url_b64={new_url_b64}&headers_b64={new_headers_b64}&episodio_id={episodio_id}&retry={retry + 1}")
            except Exception as re_err:
                logger_uv.error(f"[Proxy] ❌ Falha no auto-reparo para EP {episodio_id}: {re_err}")
        raise
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        # Erro de conexão/timeout — verifica se vale a pena tentar auto-reparo
        logger_uv = logging.getLogger("uvicorn")
        from urllib.parse import urlparse
        dead_host = urlparse(url).hostname or ""
        logger_uv.warning(f"[Proxy] ⚠️ Erro de rede/timeout para host '{dead_host}': {type(e).__name__}")
        
        if episodio_id and retry < 1:  # Só 1 retry para timeout (host morto = extração retorna mesmo host)
            logger_uv.warning(f"[Proxy] 🔄 Auto-reparo disparado por erro de rede/timeout no EP {episodio_id} (Tentativa {retry+1})")
            try:
                result = await db.execute(select(Episodio).where(Episodio.id == episodio_id))
                ep = result.scalar_one_or_none()
                if ep and ep.url_episodio_origem:
                    stream_cache.invalidate(episodio_id)
                    entry = await stream_cache.resolve_stream(episodio_id, ep.url_episodio_origem)
                    new_url_b64 = base64.urlsafe_b64encode(entry["url"].encode()).decode().replace("=", "")
                    new_headers_b64 = entry["headers"]
                    return RedirectResponse(url=f"/stream?url_b64={new_url_b64}&headers_b64={new_headers_b64}&episodio_id={episodio_id}&retry={retry + 1}")
            except Exception as re_err:
                logger_uv.error(f"[Proxy] ❌ Falha no auto-reparo (rede) para EP {episodio_id}: {re_err}")

        raise HTTPException(
            status_code=502, 
            detail=f"O servidor de vídeo original ({dead_host}) está fora do ar. Este anime pode estar temporariamente indisponível na fonte."
        )
        
    except Exception as e:
        import traceback
        logger_uv = logging.getLogger("uvicorn")
        err_msg = f"ERROR: {str(e)}\nURL: {url}\n{traceback.format_exc()}"
        logger_uv.error(f"[Proxy] ❌ ERRO CRÍTICO no proxy: {err_msg}")
        
        try:
            with open("/tmp/proxy_error.log", "a") as f:
                f.write(f"\n--- {datetime.now()} ---\n{err_msg}\n")
        except:
            pass
            
        if not local_client.is_closed:
             await local_client.aclose()
        raise HTTPException(status_code=500, detail=f"Erro interno no proxy: {str(e)}")
