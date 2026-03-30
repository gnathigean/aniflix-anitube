import asyncio
import re
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from database.db import init_db, AsyncSessionLocal
from database.models import Anime, Episodio
from sqlalchemy.future import select
from scrapers.anitube_provider import AniTubeProvider

async def run_worker():
    print("🚀 Iniciando Worker de Catalogação Automática...")
    await init_db()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await Stealth().apply_stealth_async(page)
        
        # Acessa a página principal do AniTube para raspar os lançamentos recentes
        url = "https://www.anitube.news/"
        print(f"Acessando catálogo em: {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            print("Página carregada! Lendo catálogo de vídeos no DOM...")
            
            # Pega as vitrines de vídeos recentes - Seletor heurístico comum em temas WP / PHP de Animes
            items = await page.evaluate('''() => {
                const results = [];
                const cards = document.querySelectorAll('.epiItem');
                
                cards.forEach(el => {
                    const a = el.querySelector('a');
                    const img = el.querySelector('img');
                    
                    if (a && img) {
                        results.push({
                            title: a.getAttribute('title') || img.getAttribute('alt') || a.innerText,
                            eps_url: a.href,
                            img_url: img.src || img.getAttribute('data-src') || img.getAttribute('data-lazy-src')
                        });
                    }
                });
                return results;
            }''')
            
        except Exception as e:
            print(f"Erro ao ler página de catálogo: {str(e)}")
            await browser.close()
            return

        await browser.close()

        if not items:
            print("Nenhum item recente encontrado no AniTube. O seletor pode precisar de ajuste manual.")
            return
            
        print(f"⭐ Encontrados {len(items)} episódios no catálogo inicial. Extraindo streams...")
        
        # Inicia a gravação no banco de dados e itera com a extração
        async with AsyncSessionLocal() as session:
            # Vamos limitar para 5 animes pra não demorar eternamente (o motor aguarda 2-5 segs por segurança + processamento)
            limit = 5
            for idx, item in enumerate(items[:limit]):
                title = item['title'].strip()
                
                # Heurística para limpar número do ep e ter o nome real do Anime ("One Piece Episódio 1070" -> "One Piece")
                clean_title = re.sub(r'(?i)\s*(?:epis[oó]dio|ep\.)?\s*\d+.*$', '', title).strip()
                if not clean_title: 
                    clean_title = title
                    
                print(f"\n[{idx+1}/{limit}] Processando: {clean_title}")
                
                # Verifica ou cria o Anime
                exist_q = await session.execute(select(Anime).where(Anime.titulo == clean_title))
                anime = exist_q.scalar_one_or_none()
                
                if not anime:
                    anime = Anime(
                        titulo=clean_title,
                        sinopse=f"Anime extraído automaticamente do AniTube!\nUma jornada incrível aguarda em {clean_title}.",
                        ano_lancamento=2024,
                        url_capa=item['img_url'],
                        status="Em Lançamento"
                    )
                    session.add(anime)
                    await session.flush()
                    
                # Extraindo o número do episódio ou iterando como Episódio 1 "Especial"
                match = re.search(r'(?i)(?:epis[oó]dio|ep\.)?\s*(\d+)', title)
                ep_num = int(match.group(1)) if match else 1
                
                exist_ep = await session.execute(
                    select(Episodio).where(Episodio.anime_id == anime.id, Episodio.numero == ep_num)
                )
                
                if exist_ep.scalar_one_or_none():
                    print(f"▶️ Episódio {ep_num} já existe no DB. Pulando...")
                    continue
                    
                # Utiliza o robô invisível do Passo 4 para puxar o M3U8 e Headers base64
                print(f"🎬 Inicializando extrator avançado (Proxy Catch)... Aguardando M3U8...")
                provider = AniTubeProvider()
                try:
                    stream_data = await provider.extract_episode(item['eps_url'])
                    
                    ep = Episodio(
                        anime_id=anime.id,
                        numero=ep_num,
                        titulo_episodio=title,
                        tipo="Lançamento Automático",
                        url_stream_original=stream_data["url_stream_original"],
                        headers_b64=stream_data["headers_b64"]
                    )
                    session.add(ep)
                    await session.commit()
                    print(f"✅ Salvo e pronto para Proxy: {clean_title} - EP {ep_num}")
                except Exception as e:
                    print(f"❌ Erro ao extrair link do servidor: {str(e)}")
                    await session.rollback()

    print("\n🏁 Worker finalizado! Atualize a sua página do Localhost!")

if __name__ == "__main__":
    asyncio.run(run_worker())
