#!/usr/bin/env bash
# Instalação no servidor (Ubuntu). Rode UMA vez, dentro da pasta do projeto:
#     bash deploy/setup.sh
# Pode rodar de novo sem problema (por exemplo, depois de mudar os arquivos .service).
set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(whoami)"
cd "$DIR"

echo "==> Fuso horário de Brasília (o sistema usa a data de hoje para faltas e provas)"
sudo timedatectl set-timezone America/Sao_Paulo

echo "==> Memória de reserva (swap de 2 GB), para a máquina de 1 GB não travar na instalação"
if [ ! -f /swapfile ]; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile > /dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab > /dev/null
fi

echo "==> Pacotes do sistema"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv python3-pip sqlite3 > /dev/null

echo "==> Ambiente virtual e bibliotecas"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

echo "==> Conferindo arquivos que não vêm do GitHub"
missing=0
for f in .env academico.db; do
  if [ ! -f "$f" ]; then echo "   FALTA: $f (copie do seu computador, ver GUIA_SERVIDOR.md)"; missing=1; fi
done
grep -q '^SITE_PASSWORD=..*' .env 2>/dev/null || { echo "   FALTA: SITE_PASSWORD no .env"; missing=1; }
[ "$missing" = 0 ] || { echo "Corrija os itens acima e rode o setup de novo."; exit 1; }
chmod 600 .env academico.db
mkdir -p data backups

echo "==> Testes"
.venv/bin/python -m pytest -q

echo "==> Serviços (bot, site e backup diário)"
for unit in academico-bot.service academico-site.service academico-backup.service academico-backup.timer; do
  sed -e "s#__USER__#$USER_NAME#g" -e "s#__DIR__#$DIR#g" "deploy/$unit" | sudo tee "/etc/systemd/system/$unit" > /dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now academico-bot.service academico-site.service academico-backup.timer
sudo systemctl restart academico-bot.service academico-site.service

sleep 3
systemctl --no-pager --lines=0 status academico-bot.service academico-site.service || true
echo
echo "Pronto. Próximo passo: Tailscale (GUIA_SERVIDOR.md, etapa 5)."
