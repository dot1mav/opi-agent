#!/usr/bin/env bash
set -euo pipefail

APP_NAME="opi-agent"
TELEGRAM_APP_NAME="opi-agent-telegram"
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$BASE_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
SERVICE_USER="opi-agent"
SKIP_SERVICE=0
START_SERVICE=1
INSTALL_TELEGRAM=0

usage() {
  cat <<EOF
Usage: $0 [--skip-service] [--no-start] [--with-telegram]

Options:
  --skip-service     only create venv and runtime dirs, do not install systemd unit
  --no-start         install service but do not start it
  --with-telegram    also install opi-agent-telegram service
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-service) SKIP_SERVICE=1 ;;
    --no-start) START_SERVICE=0 ;;
    --with-telegram) INSTALL_TELEGRAM=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
  shift
done

need_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    echo "Root required for service installation. Use --skip-service if you only want local setup." >&2
    exit 1
  fi
}

ensure_runtime_dirs() {
  mkdir -p "$BASE_DIR/workspace" "$BASE_DIR/logs" "$BASE_DIR/run"
}

ensure_env_file() {
  if [[ ! -f "$BASE_DIR/.env" && -f "$BASE_DIR/.env.example" ]]; then
    cp "$BASE_DIR/.env.example" "$BASE_DIR/.env"
  fi
  if [[ -f "$BASE_DIR/.env" ]]; then
    chmod 600 "$BASE_DIR/.env"
  fi
  if [[ -f "$BASE_DIR/.env.example" ]]; then
    chmod 600 "$BASE_DIR/.env.example"
  fi
}

ensure_venv() {
  if [[ ! -d "$VENV_DIR" ]]; then
    python3 -m venv "$VENV_DIR"
  fi

  "$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel

  if [[ -f "$BASE_DIR/requirements.txt" ]]; then
    "$VENV_PYTHON" -m pip install -r "$BASE_DIR/requirements.txt"
  fi

  # Install package in development mode
  "$VENV_PYTHON" -m pip install -e "$BASE_DIR"
}

install_service_unit() {
  local name="$1"
  local template="$2"

  need_root

  if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
    useradd \
      --system \
      --user-group \
      --home-dir "$BASE_DIR" \
      --shell /usr/sbin/nologin \
      "$SERVICE_USER"
  fi

  local log_dirs="$BASE_DIR/logs $BASE_DIR/run"
  if [[ "$name" == "$APP_NAME" ]]; then
    log_dirs="$BASE_DIR/workspace $log_dirs"
  fi

  chown -R "$SERVICE_USER:$SERVICE_USER" $log_dirs || true
  if [[ -f "$BASE_DIR/.env" ]]; then
    chown "$SERVICE_USER:$SERVICE_USER" "$BASE_DIR/.env" || true
    chmod 600 "$BASE_DIR/.env" || true
  fi

  local unit_file="/etc/systemd/system/${name}.service"

  if [[ -f "$template" ]]; then
    sed \
      -e "s|__BASE_DIR__|$BASE_DIR|g" \
      -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
      -e "s|__SERVICE_USER__|$SERVICE_USER|g" \
      "$template" > "$unit_file"
  else
    local exec_cmd
    if [[ "$name" == "$APP_NAME" ]]; then
      exec_cmd="$VENV_PYTHON $BASE_DIR/opi_agent.py daemon"
    else
      exec_cmd="$VENV_PYTHON $BASE_DIR/opi_agent.py telegram"
    fi

    cat > "$unit_file" <<EOF
[Unit]
Description=$([[ "$name" == "$APP_NAME" ]] && echo "OPI Agent" || echo "opi-agent Telegram Bot")
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$BASE_DIR
EnvironmentFile=$BASE_DIR/.env
ExecStart=$exec_cmd
Restart=on-failure
RestartSec=3
WatchdogSec=30

NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
LockPersonality=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true
RestrictNamespaces=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths=$log_dirs

[Install]
WantedBy=multi-user.target
EOF
  fi

  systemctl daemon-reload
  systemctl enable "${name}.service"
  if [[ "$START_SERVICE" -eq 1 ]]; then
    systemctl restart "${name}.service"
  fi
}

main() {
  cd "$BASE_DIR"
  ensure_runtime_dirs
  ensure_env_file
  ensure_venv

  if [[ "$SKIP_SERVICE" -eq 0 ]]; then
    install_service_unit "$APP_NAME" "$BASE_DIR/opi-agent.service.template"
    if [[ "$INSTALL_TELEGRAM" -eq 1 ]]; then
      install_service_unit "$TELEGRAM_APP_NAME" "$BASE_DIR/opi-agent-telegram.service.template"
    fi
  fi

  echo "Install completed."
  echo "Venv: $VENV_DIR"
  echo "Run:  $VENV_PYTHON $BASE_DIR/opi_agent.py --help"
}

main "$@"