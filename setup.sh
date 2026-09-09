#!/usr/bin/env bash
set -euo pipefail

# Configuration
REPO_URL="https://github.com/dot1mav/opi-agent"
INSTALL_DIR="/opt/opi-agent"
SCRIPT_NAME="install_opi.sh"

usage() {
    echo "Usage: curl -sSL https://raw.githubusercontent.com/dot1mav/opi-agent/main/setup.sh | sudo bash [-p PATH] [install|update|remove]"
    echo ""
    echo "Commands:"
    echo "  install   Install opi-agent to the specified path"
    echo "  update     Clean update: preserves .env, refreshes all other files and dependencies"
    echo "  remove     Stop and remove opi-agent and its services"
    echo ""
    echo "Options:"
    echo "  -p PATH    Custom installation path (default: $INSTALL_DIR)"
    exit 1
}

# Default path
TARGET_DIR=$INSTALL_DIR

# Parse arguments
ACTION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -p) TARGET_DIR="$2"; shift 2 ;;
        install|update|remove) ACTION="$1"; shift ;;
        *) usage ;;
    esac
done

if [[ -z "$ACTION" ]]; then usage; fi

case "$ACTION" in
    install)
        echo "Installing opi-agent to $TARGET_DIR..."
        mkdir -p "$TARGET_DIR"
        if [[ -d "$TARGET_DIR/.git" ]]; then
            echo "Already installed. Use 'update' instead."
            exit 1
        fi
        git clone "$REPO_URL" "$TARGET_DIR"
        bash "$TARGET_DIR/$SCRIPT_NAME"
        ;;
    update)
        if [[ ! -d "$TARGET_DIR/.git" ]]; then
            echo "Error: Installation not found at $TARGET_DIR"
            exit 1
        fi
        echo "Performing clean update at $TARGET_DIR..."
        
        cd "$TARGET_DIR"
        
        # 1. Backup .env
        if [[ -f ".env" ]]; then
            echo "Backing up .env..."
            cp .env .env.bak
        fi
        
        # 2. Force update everything from remote
        echo "Refreshing codebase..."
        git fetch origin main
        git reset --hard origin/main
        
        # 3. Restore .env
        if [[ -f ".env.bak" ]]; then
            echo "Restoring .env..."
            mv .env.bak .env
        fi
        
        # 4. Clean up old venv and dependencies to ensure a fresh state
        echo "Cleaning old environment..."
        rm -rf .venv
        
        # 5. Run the install script to recreate venv and update services
        bash "$SCRIPT_NAME"
        
        echo "Restarting services..."
        systemctl restart opi-agent.service 2>/dev/null || true
        systemctl restart opi-agent-telegram.service 2>/dev/null || true
        
        echo "Update completed successfully."
        ;;
    remove)
        echo "Removing opi-agent..."
        systemctl stop opi-agent.service 2>/dev/null || true
        systemctl disable opi-agent.service 2>/dev/null || true
        systemctl stop opi-agent-telegram.service 2>/dev/null || true
        systemctl disable opi-agent-telegram.service 2>/dev/null || true
        rm -rf "$TARGET_DIR"
        userdel opi-agent 2>/dev/null || true
        echo "Removal complete."
        ;;
esac
