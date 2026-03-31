import base64
import json
import httpx
import random
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import StreamingResponse
import urllib.parse

router = APIRouter()

def pad_b64(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)

@router.get("/stream")
async def proxy_stream(request: Request, url_b64: str, headers_b64: str = ""):
    # Decodifica a URL origial a partir de base64 urlsafe
    try:
        url = base64.urlsafe_b64decode(pad_b64(url_b64).encode()).decode("utf-8")
    except Exception:
        raise HTTPException(status_code=400, detail="Erro ao decodificar url_b64")

    headers = {}
    if headers_b64:
        try:
            headers_str = base64.urlsafe_b64decode(pad_b64(headers_b64).encode()).decode("utf-8")
            headers = json.loads(headers_str)
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
    headers = {k: v for k, v in headers.items() if k.lower() not in forbidden_headers}

    # Fallback caso os headers extraídos pelo bot não tenham User-Agent/Referer
    if "user-agent" not in headers:
        headers["user-agent"] = random.choice(user_agents)
    if "referer" not in headers:
        headers["referer"] = "https://youtube.googleapis.com/"

    # Repassa o cabeçalho Range para suportar Pular Abertura (Seek de vídeo)
    range_header = request.headers.get("Range")
    if range_header:
        # Normalize para lowercase e evite chaves duplicadas (Ex: 'range' e 'Range' fariam o Google dar error 400)
        if "Range" in headers: del headers["Range"]
        if "range" in headers: del headers["range"]
        headers["range"] = range_header

    # Cliente LOCAL para não multiplexar conexões no GoogleVideo
    local_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=15.0, read=45.0, write=15.0, pool=10.0),
        verify=False,
        http2=False,  # BUG H2 FASTAPI: Causa deadlock no stream de vídeo! HTTP/1.1 suporta 100% após strip do user-agent.
        follow_redirects=True
    )

    try:
        print(f"[Proxy] 🔄 Streaming: {url[:60]}...")
        req = local_client.build_request("GET", url, headers=headers)
        response = await local_client.send(req, stream=True)

        if response.status_code >= 400:
            error_body = await response.aread()
            with open("/tmp/proxy_trace.txt", "w") as f:
                f.write(f"FAILED!\nSTATUS: {response.status_code}\nURL: {url}\nHEADERS SENT: {headers}\nBODY: {error_body.decode('utf-8', 'ignore')}\n")
            print(f"[Proxy] ❌ Erro {response.status_code} no host original: {url[:100]}")
            await local_client.aclose()
            raise HTTPException(status_code=502, detail=f"Conteúdo indisponível (HTTP {response.status_code})")

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
                # playlists m3u8 geralmente são pequenas, aread() é mais seguro que aiter_text() para evitar crash de encoding
                raw_content = await response.aread()
                text = raw_content.decode("utf-8", errors="ignore")
                await response.aclose()
                await local_client.aclose()
                
                # Se o "m3u8" na verdade for um arquivo binário (erro comum de redirecionamento do host)
                if not text.strip().startswith("#EXTM3U"):
                    print(f"[Proxy] ⚠️ M3U8 inválido ou binário detectado em {url[:80]}")
                    # Reinicia requisição como binário se falhar
                    return Response(content=raw_content, media_type=ctype)

                # Formata playlist com rotas de proxy pro HLS local
                new_lines = []
                for line in text.splitlines():
                    if line.startswith("#") or not line.strip():
                        new_lines.append(line)
                    else:
                        if not line.startswith("http"):
                            base = url.rsplit("/", 1)[0]
                            line = f"{base}/{line}"
                        part_b64 = base64.urlsafe_b64encode(line.encode()).decode()
                        part_proxy = f"/stream?url_b64={part_b64}&headers_b64={headers_b64}"
                        new_lines.append(part_proxy)
                        
                return Response(content="\n".join(new_lines), media_type="application/vnd.apple.mpegurl")
            except Exception as e:
                print(f"[Proxy] ⚠️ Falha ao processar M3U8: {e}. Retornando como binário.")
                # Fallback: retorna o conteúdo bruto se falhar o Parse
                if not 'raw_content' in locals(): raw_content = await response.aread()
                return Response(content=raw_content, media_type=ctype)

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

    except HTTPException:
        raise
    except Exception as e:
        print(f"[Proxy] ❌ ERRO CRÍTICO no proxy: {str(e)}")
        import traceback
        traceback.print_exc()
        if not local_client.is_closed:
             await local_client.aclose()
        raise HTTPException(status_code=500, detail=f"Erro interno no proxy: {str(e)}")
