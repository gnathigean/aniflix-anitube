import asyncio
import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, selectinload
from database.models import Base, Anime, Temporada, Episodio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

# URLs de Conexão
LOCAL_DB = "sqlite:///animes.db"
# Pega do ENV ou usa a padrão fornecida pelo usuário anteriormente
REMOTE_DB = os.getenv("DATABASE_URL", "postgresql://postgres.cbakvdprewsryjlckpyd:tEzrl269ku7ULIod@aws-1-sa-east-1.pooler.supabase.com:6543/postgres")
# Converte para asyncpg se necessário para o destino
if REMOTE_DB.startswith("postgresql://"):
    REMOTE_DB_ASYNC = REMOTE_DB.replace("postgresql://", "postgresql+asyncpg://")
else:
    REMOTE_DB_ASYNC = REMOTE_DB

async def sync():
    print("🚀 Iniciando Sincronização Local -> Supabase...")
    
    # Engine Local (Síncrona para facilitar leitura do SQLite)
    local_engine = create_engine(LOCAL_DB)
    LocalSession = sessionmaker(bind=local_engine)
    
    # Engine Remota (Assíncrona para escrita no Supabase)
    # Desabilita o cache de statements para compatibilidade com PgBouncer (Transaction Mode)
    remote_engine = create_async_engine(
        REMOTE_DB_ASYNC,
        connect_args={"statement_cache_size": 0}
    )
    RemoteSession = sessionmaker(remote_engine, class_=AsyncSession, expire_on_commit=False)
    
    async with remote_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    with LocalSession() as local_session:
        # Lê animes do local
        animes = local_session.query(Anime).options(
            selectinload(Anime.temporadas).selectinload(Temporada.episodios)
        ).all()
        
        print(f"📦 Encontrados {len(animes)} animes no banco local.")
        
        for anime in animes:
            print(f"🔄 Sincronizando: {anime.titulo}...")
            async with RemoteSession() as remote_session:
                # Verifica se anime existe no remoto pelo título
                res = await remote_session.execute(select(Anime).where(Anime.titulo == anime.titulo))
                rem_anime = res.scalar_one_or_none()
                
                if not rem_anime:
                    rem_anime = Anime(
                        titulo=anime.titulo,
                        url_capa=anime.url_capa,
                        sinopse=anime.sinopse,
                        ano=anime.ano,
                        genero=anime.genero,
                        qtd_dub=anime.qtd_dub,
                        qtd_leg=anime.qtd_leg
                    )
                    remote_session.add(rem_anime)
                    await remote_session.flush()
                
                # Sincroniza temporadas
                for temp in anime.temporadas:
                    res_t = await remote_session.execute(
                        select(Temporada).where(Temporada.anime_id == rem_anime.id, Temporada.numero == temp.numero)
                    )
                    rem_temp = res_t.scalar_one_or_none()
                    if not rem_temp:
                        rem_temp = Temporada(anime_id=rem_anime.id, numero=temp.numero)
                        remote_session.add(rem_temp)
                        await remote_session.flush()
                    
                    # Sincroniza episódios
                    for ep in temp.episodios:
                        res_e = await remote_session.execute(
                            select(Episodio).where(
                                Episodio.temporada_id == rem_temp.id, 
                                Episodio.numero == ep.numero,
                                Episodio.idioma == ep.idioma
                            )
                        )
                        rem_ep = res_e.scalar_one_or_none()
                        if not rem_ep:
                            rem_ep = Episodio(
                                temporada_id=rem_temp.id,
                                numero=ep.numero,
                                titulo_episodio=ep.titulo_episodio,
                                url_episodio_origem=ep.url_episodio_origem,
                                url_stream_original=ep.url_stream_original,
                                headers_b64=ep.headers_b64,
                                idioma=ep.idioma
                            )
                            remote_session.add(rem_ep)
                
                await remote_session.commit()
    
    print("✅ Sincronização concluída com sucesso!")

if __name__ == "__main__":
    asyncio.run(sync())
