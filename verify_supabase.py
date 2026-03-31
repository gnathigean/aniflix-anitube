import asyncio
import os
from sqlalchemy import text
from database.db import engine

async def verify():
    print("Iniciando verificação do Supabase...")
    try:
        async with engine.connect() as conn:
            # 1. Verifica Tabelas
            res = await conn.execute(text("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public'"))
            tables = [row[0] for row in res.fetchall()]
            print(f"Tabelas: {tables}")
            
            # 2. Verifica Contagem
            if 'animes' in tables:
                r = await conn.execute(text("SELECT count(*) FROM animes"))
                print(f"Total de Animes no Supabase: {r.scalar()}")
                
                # 3. Verifica se Dragon Ball existe
                r = await conn.execute(text("SELECT count(*) FROM animes WHERE titulo ILIKE '%Dragon Ball%'"))
                print(f"Registros de 'Dragon Ball': {r.scalar()}")
            else:
                print("❌ Tabela 'animes' não encontrada no Supabase.")
                
    except Exception as e:
        print(f"❌ Erro de conexão: {e}")

if __name__ == "__main__":
    asyncio.run(verify())
