#!/usr/bin/env bash
# install_opi.sh - Installer for opi-agent on Orange Pi
#
# What it does:
#   1. Creates /opt/opi/{workspace,run}
#   2. Copies opi_agent.py to /opt/opi/opi_agent.py
#   3. Creates /opt/opi/.env template (with safe permissions)
#   4. Installs Python dependencies (openai, requests[socks])
#   5. Creates a global `opi` shortcut at /usr/local/bin/opi
#   6. Optional: installs systemd services (opi-agent, opi-agent-telegram)
#
# Usage:
#   sudo bash install_opi.sh           # install script + shortcut
#   sudo bash install_opi.sh --full    # also install systemd services
#   sudo bash install_opi.sh --uninstall
#
# After install:
#   opi                    # launch TUI
#   opi cli                # launch plain CLI
#   opi models             # list available models on router
#   opi telegram           # run Telegram bot (foreground)
#   opi daemon             # run as FIFO daemon
#   opi exec ls -la        # one-shot sandboxed shell command
#   opi install            # install/refresh systemd services
#   opi install-full       # install daemon + telegram services
#   opi uninstall          # remove systemd services
#
set -e

# --- paths ---
OPI_DIR="/opt/opi"
BIN_SRC="$(cd "$(dirname "$0")" && pwd)/opi_agent.py"
BIN_DST="$OPI_DIR/opi_agent.py"
SHORTCUT="/usr/local/bin/opi"
ENV_FILE="$OPI_DIR/.env"

INSTALL_SERVICES=0
UNINSTALL=0
for arg in "$@"; do
    case "$arg" in
        --full) INSTALL_SERVICES=1 ;;
        --uninstall) UNINSTALL=1 ;;
        -h|--help)
            grep '^#' "$0" | head -n 30
            exit 0
            ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# --- root check ---
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This installer must be run as root (use sudo)." >&2
    exit 1
fi

if [ "$UNINSTALL" = "1" ]; then
    echo "==> Uninstalling opi-agent"
    systemctl stop opi-agent-telegram 2>/dev/null || true
    systemctl disable opi-agent-telegram 2>/dev/null || true
    systemctl stop opi-agent 2>/dev/null || true
    systemctl disable opi-agent 2>/dev/null || true
    rm -f /etc/systemd/system/opi-agent.service
    rm -f /etc/systemd/system/opi-agent-telegram.service
    systemctl daemon-reload || true
    rm -f "$SHORTCUT"
    echo "Removed: $SHORTCUT"
    echo "Removed: systemd units"
    echo "Left in place (in case you want to keep data):"
    echo "  $OPI_DIR  (workspace, logs, .env)"
    echo "To fully remove data:  sudo rm -rf $OPI_DIR"
    exit 0
fi

# --- 1. directories ---
echo "==> Creating directories"
install -d -m 0755 "$OPI_DIR"
install -d -m 0755 "$OPI_DIR/workspace"
install -d -m 0755 "$OPI_DIR/run"

# --- 2. copy script ---
echo "==> Installing script to $BIN_DST"
if [ -f "$BIN_SRC" ]; then
    install -m 0755 "$BIN_SRC" "$BIN_DST"
else
    echo "ERROR: opi_agent.py not found next to this installer." >&2
    echo "       Place install_opi.sh and opi_agent.py in the same dir." >&2
    exit 1
fi

# --- 3. .env template ---
echo "==> Ensuring $ENV_FILE"
if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" <<'EOF'
# opi-agent environment file
# Edit and restart with: systemctl restart opi-agent opi-agent-telegram

# --- LLM router ---
OPI_BASE_URL=http://localhost:20128/v1
OPI_API_KEY=local
# Set this to a valid model id from `opi models`:
OPI_MODEL=kr/

# --- Telegram bot (optional, only needed for `telegram` service) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
# SOCKS5h proxy (DNS resolved by proxy) - required if Telegram is blocked
# Format: socks5h://[user:pass@]host:port
TELEGRAM_PROXY=
EOF
    chmod 600 "$ENV_FILE"
    echo "    created template"
else
    echo "    already exists (left untouched)"
fi

# --- 4. python deps ---
echo "==> Installing Python dependencies"
PYTHON_BIN="$(command -v python3 || command -v python)"
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: python3/python not found" >&2
    exit 1
fi
"$PYTHON_BIN" -m pip install --quiet --upgrade pip || true
# openai: LLM client
# requests[socks]: brings in PySocks for socks5h:// proxy
"$PYTHON_BIN" -m pip install --quiet openai 'requests[socks]' || {
    echo "WARNING: pip install failed. You may need to install these manually:"
    echo "  $PYTHON_BIN -m pip install openai 'requests[socks]'"
}

# --- 5. global shortcut ---
echo "==> Creating shortcut $SHORTCUT"
cat > "$SHORTCUT" <<EOF
#!/usr/bin/env bash
# opi - shortcut for opi-agent on Orange Pi
# Passes all args to opi_agent.py run/cli/daemon/telegram/models/exec/install/...
exec $PYTHON_BIN $BIN_DST "\$@"
EOF
chmod 0755 "$SHORTCUT"
echo "    $SHORTCUT -> $BIN_DST"

# --- 6. optional systemd ---
if [ "$INSTALL_SERVICES" = "1" ]; then
    echo "==> Installing systemd services"
    "$PYTHON_BIN" "$BIN_DST" install-full || {
        echo "WARNING: install-full failed. You can retry with:"
        echo "  $PYTHON_BIN $BIN_DST install-full"
    }
else
    echo "==> Skipping systemd services (use 'opi install' or 'opi install-full' to install)"
fi

# --- summary ---
echo ""
echo "============================================================"
echo " opi-agent installed successfully."
echo ""
echo " Quick start:"
echo "   opi               # launch TUI (default)"
echo "   opi models        # list available models on the router"
echo "   opi cli           # plain CLI mode"
echo ""
echo " Edit config:"
echo "   sudo nano $ENV_FILE"
echo ""
echo " Optional systemd:"
echo "   sudo opi install         # daemon service only"
echo "   sudo opi install-full    # daemon + telegram services"
echo "   sudo opi uninstall       # remove systemd services"
echo ""
echo " Logs:"
echo "   sudo tail -f $OPI_DIR/opi_agent.log"
echo "============================================================"
