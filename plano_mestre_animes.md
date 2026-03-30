# 🎌 Plano Mestre: Hub de Streaming de Animes Autônomo (Project AnimeProxy)

## 🎯 Objetivo do Projeto
Construir um ecossistema autônomo focado em animes. O sistema deve raspar metadados e links de streaming de plataformas específicas, armazenar em um banco SQLite otimizado e servir o conteúdo via uma interface web própria, utilizando um proxy de vídeo de alta performance para contornar bloqueios (CORS/Hotlinking).

## 🛠️ Stack Técnica
- **Orquestração:** Google Antigravity (Modo Agente Autônomo)
- **Scraping Engine:** Python 3.12+ com `Playwright` + `playwright-stealth`
- **Backend & Proxy:** `FastAPI` + `httpx` (Assíncrono)
- **Banco de Dados:** `SQLite` com `SQLAlchemy` (ORM) e `Alembic` (Migrations)
- **Frontend:** HTML/JS puro com `Video.js` (ou Next.js/Streamlit para a galeria)

## 🌐 Alvos de Extração (Providers)
1. `https://www.anitube.news/`
2. `https://animesdigital.org/home/`

---

## 🚀 Passo a Passo de Inicialização (Instruções para o Agente)

### Passo 1: Configuração do Ambiente
1. Crie um ambiente virtual: `python -m venv venv`
2. Ative o ambiente e instale as dependências base:
   `pip install fastapi uvicorn httpx sqlalchemy playwright playwright-stealth aiosqlite jinja2`
3. Instale os navegadores do Playwright: `playwright install chromium`
4. Crie a estrutura de pastas:
   - `/api` (Backend e Proxy)
   - `/database` (Modelos e Conexão)
   - `/scrapers` (Lógica de Extração e Providers)
   - `/frontend` (Arquivos estáticos e templates)

### Passo 2: Construção do Banco de Dados (`database/models.py`)
Implemente o ORM com SQLAlchemy focando na taxonomia de animes:
- **Tabela `Anime`:** `id`, `titulo`, `sinopse`, `ano_lancamento`, `estudio`, `url_capa`, `status` (Ex: Em Lançamento, Finalizado).
- **Tabela `Episodio`:** `id`, `anime_id` (Foreign Key), `numero`, `titulo_episodio`, `tipo` (Canônico/Filler), `url_stream_original`, `headers_b64` (Essencial para o Proxy).

### Passo 3: O Motor de Proxy (`api/proxy.py`)
Implemente o endpoint `/stream` em FastAPI.
- **Regras Críticas:** 1. O endpoint deve receber `url_b64` e `headers_b64`.
  2. Deve decodificar os parâmetros e fazer a requisição para o servidor original do anime usando `httpx.AsyncClient`.
  3. **Obrigatório:** Suporte a `Range Requests` (HTTP 206 Partial Content) lendo o cabeçalho `Range` do request original para permitir pular aberturas (seek) sem travar o player.
  4. Retornar os dados via `StreamingResponse`.

### Passo 4: O Motor de Scraping (`scrapers/`)
1. **Crie `base_provider.py`:** Uma classe abstrata que inicializa o Playwright em modo Stealth (`playwright-stealth`). Deve conter um método para interceptar a rede (`page.route("**/*")`) e capturar requisições terminadas em `.m3u8` ou `.mp4`, salvando a URL e os Headers em Base64.
2. **Crie `anitube_provider.py`:** Herde de `BaseProvider`. Implemente a navegação até a página do episódio do AniTube, lide com iframes e clique no player para forçar o disparo do evento de rede.
3. **Crie `animesdigital_provider.py`:** Herde de `BaseProvider`. Implemente a mesma lógica adaptada para o DOM do Animes Digital.

### Passo 5: API Principal e Frontend (`api/main.py`)
- Crie rotas CRUD simples para listar animes e episódios a partir do SQLite.
- Sirva uma página HTML simples (usando Jinja2 ou arquivos estáticos) que exiba a lista de episódios.
- Ao clicar em um episódio, abra o `Video.js` apontando a fonte (source) para o nosso endpoint `/stream` local, passando os parâmetros em Base64.

---

## ⚠️ Regras de Execução e Qualidade (Senior Guidelines)
- **Silêncio e Furtividade:** Nunca faça scraping agressivo. Coloque delays (`page.wait_for_timeout`) aleatórios entre 2 e 5 segundos entre as páginas para evitar banimentos de IP.
- **Tratamento de Erros:** O proxy não deve quebrar se o link original expirar; a API deve retornar um status claro (ex: 404 ou 410 Gone) para que o frontend saiba que o scraper precisa rodar novamente para aquele episódio.
- **Modularidade:** Mantenha os provedores (scrapers) estritamente separados. Se o layout do AniTube mudar, apenas `anitube_provider.py` deve ser editado.