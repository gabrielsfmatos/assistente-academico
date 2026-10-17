#!/usr/bin/env bash
# Atualiza o servidor com a última versão do GitHub:
#     bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m pytest -q
sudo systemctl restart academico-bot.service academico-site.service
echo "Atualizado: $(git log -1 --format='%h %s')"
