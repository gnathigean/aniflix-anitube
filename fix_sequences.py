import asyncio
from sqlalchemy import text
from database.db import AsyncSessionLocal, engine

async def fix_sequences():
    print("⏳ Corrigindo dessincronia de sequences no PostgreSQL/Supabase...")
    async with engine.begin() as conn:
        tables = ["animes", "temporadas", "episodios", "progressos", "favoritos"]
        for t in tables:
            try:
                # Sincroniza a sequence (tabela_id_seq) com o maior ID existente na tabela
                # Se a tabela estiver vazia, começa do 1
                q = text(f"SELECT setval('{t}_id_seq', COALESCE((SELECT MAX(id) FROM {t}), 1) + 1, false)")
                await conn.execute(q)
                print(f"✅ Sequence '{t}_id_seq' sincronizada!")
            except Exception as e:
                print(f"⚠️ Erro ao corrigir {t} (pode não existir): {e}")

asyncio.run(fix_sequences())
