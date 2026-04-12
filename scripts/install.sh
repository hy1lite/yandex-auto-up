#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="yandex-auto-up"
INSTALL_ROOT="/opt/yandex-auto-up"
APP_DIR="$INSTALL_ROOT/app"
VENV_DIR="$INSTALL_ROOT/venv"
CONFIG_DIR="/etc/yandex-auto-up"
STATE_DIR="/var/lib/yandex-auto-up"
BIN_LINK="/usr/local/bin/yauto"
SERVICE_FILE="/etc/systemd/system/yandex-auto-up.service"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd -- "$SCRIPT_DIR/.." && pwd)

log() {
    printf '%s\n' "$1"
}

require_root() {
    if [[ ${EUID} -ne 0 ]]; then
        log "Run this installer as root."
        exit 1
    fi
}

install_packages() {
    if ! command -v apt-get >/dev/null 2>&1; then
        log "Only apt-based distributions are supported by this installer right now."
        exit 1
    fi
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        ca-certificates \
        iputils-ping \
        python3 \
        python3-pip \
        python3-venv
}

install_project() {
    mkdir -p "$INSTALL_ROOT"
    rm -rf "$APP_DIR"
    mkdir -p "$APP_DIR"
    cp -a "$PROJECT_DIR/." "$APP_DIR/"

    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --upgrade pip setuptools wheel
    "$VENV_DIR/bin/pip" install "$APP_DIR"

    mkdir -p "$CONFIG_DIR/profiles" "$CONFIG_DIR/keys" "$STATE_DIR" /run/yandex-auto-up
    if [[ ! -f "$CONFIG_DIR/keys/ПРОЧИТАЙ МЕНЯ.txt" ]]; then
        cat > "$CONFIG_DIR/keys/ПРОЧИТАЙ МЕНЯ.txt" <<'EOF'
Переносите сюда ключи Service Account Yandex Cloud.

Подхватываются ВСЕ файлы из этой папки автоматически:
  - любые имена файлов (не только *.json)
  - любое количество ключей
  - файлы проверяются по содержимому, а не по расширению

Просто скопируйте сюда файл(ы) ключей и перезапустите панель.
EOF
    fi
    install -m 644 "$APP_DIR/systemd/yandex-auto-up.service" "$SERVICE_FILE"
    ln -sf "$VENV_DIR/bin/yauto" "$BIN_LINK"
}

reload_systemd() {
    systemctl daemon-reload
    systemctl enable yandex-auto-up
    systemctl restart yandex-auto-up || true
}

print_next_steps() {
    log ""
    log "Installation finished."
    log ""
    log "Next steps:"
    log "  1. Copy key files to: /etc/yandex-auto-up/keys/"
    log "  2. Run: sudo yauto setup"
    log "  3. Check: sudo yauto status"
    log "  4. Logs:  sudo yauto logs --journal"
}

main() {
    require_root
    install_packages
    install_project
    reload_systemd
    print_next_steps
}

main "$@"
