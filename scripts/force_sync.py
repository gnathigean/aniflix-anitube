import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import func
from database.models import Base, Anime, Temporada, Episodio
from dotenv import load_dotenv

# Configurações
SQLITE_URL = "sqlite+aiosqlite:///./animes.db"
load_dotenv(override=True)
SUPABASE_URL = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")

async def force_sync():
    print(f"🚀 Iniciando Sincronização Forçada...")
    print(f"📂 Origem: {SQLITE_URL}")
    print(f"☁️ Destino: {SUPABASE_URL[:30]}...")

    engine_lite = create_async_engine(SQLITE_URL)
    engine_sb = create_async_engine(
        SUPABASE_URL, 
        pool_pre_ping=True,
        connect_args={"statement_cache_size": 0}
    )
    
    SessionLite = async_sessionmaker(engine_lite, expire_on_commit=False)
    SessionSB = async_sessionmaker(engine_sb, expire_on_commit=False)

    # 1. Sincronizar Animes
    print("\n--- [1/3] Sincronizando ANIMES ---")
    anime_map = {} # sqlite_id -> supabase_id
    async with SessionLite() as s_lite:
        res = await s_lite.execute(select(Anime))
        local_animes = res.scalars().all()
        print(f"📦 Encontrados {len(local_animes)} animes locais.")

        async with SessionSB() as s_sb:
            for i, la in enumerate(local_animes):
                # Upsert Anime
                # Como não temos UniqueConstraint explícita no model, vamos buscar por título
                q = await s_sb.execute(select(Anime).where(Anime.titulo == la.titulo))
                sa = q.scalar_one_or_none()
                
                if not sa:
                    sa = Anime(
                        titulo=la.titulo, url_capa=la.url_capa, sinopse=la.sinopse,
                        formato=la.formato, genero=la.genero, autor=la.autor,
                        estudio=la.estudio, ano=la.ano, status=la.status,
                        qtd_dub=la.qtd_dub, qtd_leg=la.qtd_leg, visualizacoes_total=la.visualizacoes_total
                    )
                    s_sb.add(sa)
                    await s_sb.flush()
                else:
                    # Update (opcional, mas bom para garantir paridade)
                    sa.url_capa = la.url_capa
                    sa.sinopse = la.sinopse
                    sa.qtd_dub = la.qtd_dub
                    sa.qtd_leg = la.qtd_leg
                
                anime_map[la.id] = sa.id
                if i % 100 == 0:
                    print(f"  > Processados {i}/{len(local_animes)} animes...")
                    await s_sb.commit()
            await s_sb.commit()

    # 2. Sincronizar Temporadas
    print("\n--- [2/3] Sincronizando TEMPORADAS ---")
    season_map = {} # sqlite_id -> supabase_id
    async with SessionLite() as s_lite:
        res = await s_lite.execute(select(Temporada))
        local_seasons = res.scalars().all()
        
        async with SessionSB() as s_sb:
            for i, ls in enumerate(local_seasons):
                sb_anime_id = anime_map.get(ls.anime_id)
                if not sb_anime_id: continue
                
                q = await s_sb.execute(select(Temporada).where(
                    Temporada.anime_id == sb_anime_id, 
                    Temporada.numero == ls.numero
                ))
                ss = q.scalar_one_or_none()
                
                if not ss:
                    ss = Temporada(anime_id=sb_anime_id, numero=ls.numero, titulo_temporada=ls.titulo_temporada)
                    s_sb.add(ss)
                    await s_sb.flush()
                
                season_map[ls.id] = ss.id
                if i % 100 == 0:
                    print(f"  > Processadas {i}/{len(local_seasons)} temporadas...")
                    await s_sb.commit()
            await s_sb.commit()

    # 3. Sincronizar Episódios (O mais pesado)
    print("\n--- [3/3] Sincronizando EPISÓDIOS ---")
    async with SessionLite() as s_lite:
        # Vamos processar por temporada para não estourar memória
        for sqlite_s_id, sb_s_id in season_map.items():
            res = await s_lite.execute(select(Episodio).where(Episodio.temporada_id == sqlite_s_id))
            local_eps = res.scalars().all()
            if not local_eps: continue
            
            async with SessionSB() as s_sb:
                print(f"  > Sincronizando {len(local_eps)} episódios da temporada {sb_s_id}...")
                for le in local_eps:
                    q = await s_sb.execute(select(Episodio).where(
                        Episodio.temporada_id == sb_s_id,
                        Episodio.numero == le.numero,
                        Episodio.idioma == le.idioma
                    ))
                    se = q.scalar_one_or_none()
                    
                    if not se:
                        se = Episodio(
                            temporada_id=sb_s_id,
                            numero=le.numero,
                            titulo_episodio=le.titulo_episodio,
                            tipo=le.tipo,
                            url_episodio_origem=le.url_episodio_origem,
                            url_stream_original=le.url_stream_original,
                            headers_b64=le.headers_b64,
                            idioma=le.idioma,
                            views_total=le.views_total
                        )
                        s_sb.add(se)
                    else:
                        # Update links se estiverem vazios no Supabase
                        if le.url_stream_original and not se.url_stream_original:
                            se.url_stream_original = le.url_stream_original
                            se.headers_b64 = le.headers_b64
                
                await s_sb.commit()

    print("\n✅ Sincronização Concluída com Sucesso!")
    await engine_lite.dispose()
    await engine_sb.dispose()

if __name__ == "__main__":
    asyncio.run(force_sync())
