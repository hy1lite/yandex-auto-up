#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${YAUTO_INSTALL_ROOT:-/opt/yandex-auto-up}"
CONFIG_DIR="/etc/yandex-auto-up"
STATE_DIR="/var/lib/yandex-auto-up"
RUNTIME_DIR="/run/yandex-auto-up"
SERVICE_NAME="yandex-auto-up"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
BIN_LINK="/usr/local/bin/yauto"
STAGING_DIR="/root/yandex-auto-up"

log() {
    printf '%s\n' "$1"
}

require_root() {
    if [[ ${EUID} -ne 0 ]]; then
        log "Run uninstall as root."
        exit 1
    fi
}

main() {
    require_root

    systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true

    rm -f "$BIN_LINK"
    rm -f "$SERVICE_FILE"
    systemctl daemon-reload || true

    rm -rf "$INSTALL_ROOT" "$CONFIG_DIR" "$STATE_DIR" "$RUNTIME_DIR"
    rm -rf "$STAGING_DIR"

    log "yandex auto up has been removed from this server."
}

main "$@"
