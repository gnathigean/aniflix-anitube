#!/usr/bin/env bash
# exit on error
set -o errexit

# Instala dependências do Python
pip install --upgrade pip
pip install -r requirements.txt

# Instala os navegadores do Playwright e suas dependências de sistema (necessário no Render)
echo "🌐 Instalando Playwright Chromium..."
python -m playwright install chromium

# Tenta instalar as dependências de sistema (pode falhar se não houver sudo, mas o Render geralmente permite)
python -m playwright install --with-deps chromium || echo "⚠️ Aviso: Falha ao instalar dependências de sistema do Playwright. Continuando..."
