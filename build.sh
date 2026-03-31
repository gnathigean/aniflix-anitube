#!/usr/bin/env bash
# exit on error
set -o errexit

# Instala dependências do Python
pip install -r requirements.txt

# Instala os navegadores do Playwright e suas dependências de sistema (necessário no Render)
playwright install --with-deps chromium
