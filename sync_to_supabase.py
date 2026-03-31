import asyncio
import os
import logging
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from database.db import Base, init_db
from database.models import Anime, Temporada, Episodio
from sqlalchemy.orm import selectinload

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("sync_optimized")

SQLITE_URL = "sqlite+aiosqlite:///./animes.db"
from database.db import DATABASE_URL as SUPABASE_URL, engine_args as REMOTE_ENGINE_ARGS

async def sync():
    local_engine = create_async_engine(SQLITE_URL)
    local_session = async_sessionmaker(local_engine, expire_on_commit=False)
    
    remote_engine = create_async_engine(SUPABASE_URL, **REMOTE_ENGINE_ARGS)
    remote_session = async_sessionmaker(remote_engine, expire_on_commit=False)
    
    logger.info("🚀 Iniciando Sincronização OTIMIZADA Local -> Supabase...")

    async with local_session() as l_sess, remote_session() as r_sess:
        # Pega todos os animes locais
        result = await l_sess.execute(select(Anime))
        local_animes = result.scalars().all()
        
        for l_anime in local_animes:
            # Match por título
            r_anime_res = await r_sess.execute(select(Anime).where(Anime.titulo == l_anime.titulo))
            r_anime = r_anime_res.scalar_one_or_none()
            
            if not r_anime:
                logger.info(f"➕ [Anime] Criando '{l_anime.titulo}'...")
                r_anime = Anime(
                    titulo=l_anime.titulo, url_capa=l_anime.url_capa, sinopse=l_anime.sinopse,
                    formato=l_anime.formato, genero=l_anime.genero, autor=l_anime.autor,
                    estudio=l_anime.estudio, ano=l_anime.ano, status=l_anime.status,
                    qtd_dub=0, qtd_leg=0
                )
                r_sess.add(r_anime)
                await r_sess.flush()

            # Pega temporadas locais
            l_temps_res = await l_sess.execute(select(Temporada).where(Temporada.anime_id == l_anime.id))
            l_temps = l_temps_res.scalars().all()
            
            for l_temp in l_temps:
                r_temp_res = await r_sess.execute(
                    select(Temporada).where(Temporada.anime_id == r_anime.id, Temporada.numero == l_temp.numero)
                )
                r_temp = r_temp_res.scalar_one_or_none()
                if not r_temp:
                    r_temp = Temporada(anime_id=r_anime.id, numero=l_temp.numero, titulo_temporada=l_temp.titulo_temporada)
                    r_sess.add(r_temp)
                    await r_sess.flush()

                # BATCH CHECK para Episódios
                # Pega todos os números de episódios existentes remotamente para esta temporada
                r_existing_eps_res = await r_sess.execute(
                    select(Episodio.numero, Episodio.idioma).where(Episodio.temporada_id == r_temp.id)
                )
                r_existing_set = set(r_existing_eps_res.all()) # {(num, lang), ...}

                l_eps_res = await l_sess.execute(select(Episodio).where(Episodio.temporada_id == l_temp.id))
                l_eps = l_eps_res.scalars().all()
                
                to_add = []
                for l_ep in l_eps:
                    if (l_ep.numero, l_ep.idioma) not in r_existing_set:
                        to_add.append(Episodio(
                            temporada_id=r_temp.id, numero=l_ep.numero, 
                            titulo_episodio=l_ep.titulo_episodio, tipo=l_ep.tipo,
                            url_episodio_origem=l_ep.url_episodio_origem,
                            url_stream_original=l_ep.url_stream_original,
                            headers_b64=l_ep.headers_b64, idioma=l_ep.idioma
                        ))
                
                if to_add:
                    logger.info(f"    🚀 Subindo {len(to_add)} episódios para '{l_anime.titulo}'...")
                    r_sess.add_all(to_add)
                    
                    # Atualiza contadores
                    n_dub = sum(1 for e in to_add if e.idioma == "Dublado")
                    n_leg = len(to_add) - n_dub
                    r_anime.qtd_dub = (r_anime.qtd_dub or 0) + n_dub
                    r_anime.qtd_leg = (r_anime.qtd_leg or 0) + n_leg

            await r_sess.commit()
            
    await local_engine.dispose()
    await remote_engine.dispose()
    logger.info("✅ Sincronização Otimizada Concluída!")

if __name__ == "__main__":
    asyncio.run(sync())
