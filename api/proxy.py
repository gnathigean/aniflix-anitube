import base64
import json
import httpx
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
import urllib.parse

router = APIRouter()

# Cliente compartilhado com SSL desabilitado e timeout generoso
client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
    verify=False,
    follow_redirects=True,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)
)

def pad_b64(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)

@router.get("/stream")
async def proxy_stream(request: Request, url_b64: str, headers_b64: str = ""):
    # Decodifica a URL origial a partir de base64 urlsafe
    try:
        url = base64.urlsafe_b64decode(pad_b64(url_b64).encode()).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Erro ao decodificar url_b64")

    # Decodifica os headers (JSON) a partir de base64 urlsafe
    headers = {}
    if headers_b64:
        try:
            headers_str = base64.urlsafe_b64decode(pad_b64(headers_b64).encode()).decode("utf-8")
            headers = json.loads(headers_str)
        except Exception:
            raise HTTPException(status_code=400, detail="Erro ao decodificar headers_b64")

    # SANEAMENTO DE HEADERS: Remove campos que o httpx/servidor original podem rejeitar
    forbidden_headers = ["host", "content-length", "connection", "accept-encoding", "content-type", "cookie"]
    headers = {k: v for k, v in headers.items() if k.lower() not in forbidden_headers}

    # Referer Fallback (Anti-Bloqueio)
    if not headers.get("Referer") and not headers.get("referer"):
        headers["Referer"] = "https://www.anitube.news/"

    # Repassa o cabeçalho Range para suportar Pular Abertura (Seek de vídeo)
    range_header = request.headers.get("Range")
    if range_header:
        headers["Range"] = range_header

    try:
        print(f"[Proxy] 🔄 Streaming: {url[:60]}...")
        req = client.build_request("GET", url, headers=headers)
        response = await client.send(req, stream=True)

        # Trata erros do servidor de origem com fallback
        if response.status_code >= 400:
            print(f"[Proxy] ❌ Erro {response.status_code} no host original: {url[:100]}")
            await response.aclose()
            
            # Fallback: tenta com outro User-Agent se for 403 ou 404
            if response.status_code in (403, 404, 503):
                fallback_headers = dict(headers)
                fallback_headers["User-Agent"] = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36"
                try:
                    req2 = client.build_request("GET", url, headers=fallback_headers)
                    response = await client.send(req2, stream=True)
                    if response.status_code >= 400:
                        await response.aclose()
                        raise HTTPException(status_code=502, detail=f"Conteúdo indisponível no servidor de origem (HTTP {response.status_code}). URL pode ter expirado.")
                except httpx.RequestError:
                    raise HTTPException(status_code=502, detail="Falha no fallback de conexão.")
            else:
                raise HTTPException(status_code=502, detail=f"Conteúdo indisponível no servidor de origem (HTTP {response.status_code})")

        # Repassa cabeçalhos essenciais para vídeo
        resp_headers = {}
        for key in ["content-type", "content-length", "content-range", "accept-ranges", "cache-control"]:
            if key in response.headers:
                resp_headers[key] = response.headers[key]

        # SEGURANÇA: Se o servidor de origem retornar HTML quando esperamos vídeo, levantamos erro
        ctype = response.headers.get("content-type", "").lower()
        if "text/html" in ctype and ".m3u8" not in url.lower():
            print(f"[Proxy] ⚠️ Servidor de origem retornou HTML em vez de vídeo: {url[:80]}...")
            await response.aclose()
            raise HTTPException(status_code=502, detail="Servidor de origem retornou conteúdo inválido (HTML). Acesso pode estar bloqueado.")

        # Verifica se é uma playlist HLS (m3u8) para reescreveremos os links internos (.ts)
        is_m3u8 = "mpegurl" in ctype or ".m3u8" in url.lower()
        
        if is_m3u8:
            content = await response.aread()
            text = content.decode("utf-8")
            
            new_lines = []
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    new_lines.append(line)
                else:
                    # Resolve URL relativa para absoluta
                    abs_url = urllib.parse.urljoin(url, line)
                    # Codifica o link interno do segmento .ts / sub-m3u8 para o nosso proxy
                    new_b64 = base64.urlsafe_b64encode(abs_url.encode("utf-8")).decode("utf-8")
                    proxy_url = f"/stream?url_b64={new_b64}&headers_b64={headers_b64}"
                    new_lines.append(proxy_url)
            
            modified_content = "\n".join(new_lines).encode("utf-8")
            if "content-length" in resp_headers:
                resp_headers["content-length"] = str(len(modified_content))
                
            return Response(
                content=modified_content,
                status_code=response.status_code,
                headers=resp_headers
            )
            
        else:
            # Arquivo binário (Segmento de Vídeo .ts ou .mp4), retorna via Stream
            async def stream_generator():
                async for chunk in response.aiter_bytes():
                    yield chunk

            return StreamingResponse(
                stream_generator(),
                status_code=response.status_code,
                headers=resp_headers,
                background=response.aclose
            )

    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Falha de comunicação com o servidor original: {str(e)}")
