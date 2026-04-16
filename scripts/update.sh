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

# Останови сервис
echo "Stopping service..."
systemctl stop yandex-auto-up
echo ""

# Удали весь Python кеш
echo "Removing Python cache..."
find "$PROJECT_DIR/src" -type f -name "*.pyc" -delete 2>/dev/null || true
find "$PROJECT_DIR/src" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find /opt/yandex-auto-up -type f -name "*.pyc" -delete 2>/dev/null || true
find /opt/yandex-auto-up -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
echo "Cache cleared"
echo ""

# Переустанови пакет
echo "Reinstalling package..."
/opt/yandex-auto-up/venv/bin/pip uninstall -y yandex-auto-up 2>/dev/null || true
/opt/yandex-auto-up/venv/bin/pip install -e "$PROJECT_DIR"
echo ""

# Запусти сервис
echo "Starting service..."
systemctl start yandex-auto-up
echo ""

# Проверка статуса
echo "Service status:"
systemctl status yandex-auto-up --no-pager -l | head -10
echo ""

echo "=== Update completed successfully! ==="
echo "Run 'yauto' to open the panel"

