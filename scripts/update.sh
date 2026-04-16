#!/bin/bash
set -euo pipefail

echo "=== Yandex Auto Up - Update Script ==="
echo ""

# Проверка что запущено от root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)" 
   exit 1
fi

# Переход в директорию проекта
cd "$(dirname "$0")/.."
PROJECT_DIR=$(pwd)

echo "Project directory: $PROJECT_DIR"
echo ""

# Git pull
echo "Pulling latest changes from GitHub..."
git pull origin main
echo ""

# Копирование файлов
echo "Copying updated files to /opt/yandex-auto-up/app/..."
rm -rf /opt/yandex-auto-up/app/yauto
cp -r src/yauto /opt/yandex-auto-up/app/
echo "Files copied successfully"
echo ""

# Перезапуск сервиса
echo "Restarting yandex-auto-up service..."
systemctl restart yandex-auto-up
echo "Service restarted"
echo ""

# Проверка статуса
echo "Service status:"
systemctl status yandex-auto-up --no-pager -l | head -10
echo ""

echo "=== Update completed successfully! ==="
echo "Run 'yauto' to open the panel"
