import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from database.db import Base, init_db
from database.models import Anime, Temporada, Episodio

# Configuração Local (SQLite)
SQLITE_URL = "sqlite+aiosqlite:///./animes.db"
local_engine = create_async_engine(SQLITE_URL)
LocalSession = async_sessionmaker(local_engine, expire_on_commit=False)

# Configuração Remota (Postgres)
REMOTE_URL = os.getenv("DATABASE_URL")
if not REMOTE_URL or "sqlite" in REMOTE_URL:
    print("❌ Erro: DATABASE_URL do Supabase não configurada!")
    exit(1)

# Garante asyncpg
if REMOTE_URL.startswith("postgres://"):
    REMOTE_URL = REMOTE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif REMOTE_URL.startswith("postgresql://"):
    REMOTE_URL = REMOTE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

remote_engine = create_async_engine(REMOTE_URL)
RemoteSession = async_sessionmaker(remote_engine, expire_on_commit=False)

async def migrate():
    print("🚀 Iniciando migração para Supabase...")
    
    # 1. Cria as tabelas no destino
    print("📁 Criando tabelas no Postgres...")
    async with remote_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Busca dados do SQLite
    async with LocalSession() as local_session:
        print("🔍 Lendo dados do SQLite...")
        result = await local_session.execute(
            select(Anime).options(
                selectinload(Anime.temporadas).selectinload(Temporada.episodios)
            )
        )
        animes = result.scalars().all()
        print(f"✅ Encontrados {len(animes)} animes.")

    # 3. Insere no Postgres
    async with RemoteSession() as remote_session:
        print("📤 Enviando para o Supabase (pode demorar alguns minutos)...")
        for anime in animes:
            print(f"👉 Migrando: {anime.titulo}")
            
            # Criar nova instância para evitar conflito de estado da sessão
            new_anime = Anime(
                id=anime.id,
                titulo=anime.titulo,
                url_capa=anime.url_capa,
                sinopse=anime.sinopse,
                formato=anime.formato,
                genero=anime.genero,
                autor=anime.autor,
                estudio=anime.estudio,
                ano=anime.ano,
                status=anime.status,
                qtd_dub=anime.qtd_dub,
                qtd_leg=anime.qtd_leg,
                visualizacoes_total=anime.visualizacoes_total
            )
            
            for temp in anime.temporadas:
                new_temp = Temporada(
                    id=temp.id,
                    numero=temp.numero,
                    titulo_temporada=temp.titulo_temporada,
                    anime=new_anime
                )
                for ep in temp.episodios:
                    new_ep = Episodio(
                        id=ep.id,
                        numero=ep.numero,
                        titulo_episodio=ep.titulo_episodio,
                        tipo=ep.tipo,
                        url_episodio_origem=ep.url_episodio_origem,
                        url_stream_original=ep.url_stream_original,
                        headers_b64=ep.headers_b64,
                        idioma=ep.idioma,
                        views_total=ep.views_total,
                        views_dia=ep.views_dia,
                        views_semana=ep.views_semana,
                        views_mes=ep.views_mes,
                        temporada=new_temp
                    )
            
            remote_session.add(new_anime)
            
        await remote_session.commit()
        print("✨ Migração concluída com sucesso!")

if __name__ == "__main__":
    asyncio.run(migrate())
