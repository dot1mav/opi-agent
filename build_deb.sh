#!/usr/bin/env bash
set -euo pipefail

# Configuration
PACKAGE_NAME="opi-agent"
VERSION=$(python -m opi_agent.__init__ 2>/dev/null || echo "2.0.0") # Try to get version from code
if [[ "$VERSION" == "2.0.0" ]]; then
    # Fallback to git tag if available
    VERSION=$(git describe --tags --abbrev=0 2>/dev/null || echo "2.0.0")
fi
VERSION=${VERSION#v} # Remove 'v' prefix if present
ARCHITECTURE="arm64" # Primary target for Orange Pi
MAINTAINER="dot1mav <dot1mav@example.com>"
INSTALL_DIR="/opt/opi-agent"

echo "Building $PACKAGE_NAME version $VERSION for $ARCHITECTURE..."

# 1. Create build directory structure
BUILD_DIR="dist/debian"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/$INSTALL_DIR"
mkdir -p "$BUILD_DIR/DEBIAN"

# 2. Copy project files into the package structure
# Exclude artifacts, git, and tests
rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude 'workspace' \
    --exclude 'logs' \
    --exclude 'run' \
    --exclude 'dist' \
    --exclude 'tests' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    "$GITHUB_WORKSPACE" "$BUILD_DIR/$INSTALL_DIR/" 2>/dev/null || \
    cp -r . "$BUILD_DIR/$INSTALL_DIR/"

# Fix the copy for local builds where GITHUB_WORKSPACE isn't set
if [[ -z "${GITHUB_WORKSPACE:-}" ]]; then
    # Clean up the copy of the current dir
    rm -rf "$BUILD_DIR/$INSTALL_DIR/.git"
    rm -rf "$BUILD_DIR/$INSTALL_DIR/dist"
fi

# 3. Create the control file
cat > "$BUILD_DIR/DEBIAN/control" <<EOF
Package: $PACKAGE_NAME
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCHITECTURE
Maintainer: $MAINTAINER
Description: OPI Agent runtime for Orange Pi
A secure, auditable interface for remote system administration
via CLI, Telegram bot, and subagent system.
EOF

# 4. Create the post-installation script
# This is the magic: it runs your existing installation logic
cat > "$BUILD_DIR/DEBIAN/postinst" <<EOF
#!/bin/bash
set -e

# Set paths
BASE_DIR="$INSTALL_DIR"
S_SCRIPT="\$BASE_DIR/install_opi.sh"

echo "Running opi-agent post-installation configuration..."

if [[ -f "\$S_SCRIPT" ]]; then
    chmod +x "\$S_SCRIPT"
    # Run the existing install script to handle venv, users, and systemd
    # We use --skip-service if we want to handle it differently, 
    # but normally we let install_opi.sh do its job.
    bash "\$S_SCRIPT"
else
    echo "Error: install_opi.sh not found in \$BASE_DIR"
    exit 1
fi

echo "opi-agent installed successfully."
EOF

chmod 755 "$BUILD_DIR/DEBIAN/postinst"

# 5. Create the pre-removal script
cat > "$BUILD_DIR/DEBIAN/prerm" <<EOF
#!/bin/bash
set -e

echo "Stopping opi-agent services..."
systemctl stop opi-agent.service 2>/dev/null || true
systemctl disable opi-agent.service 2>/dev/null || true
systemctl stop opi-agent-telegram.service 2>/dev/null || true
systemctl disable opi-agent-telegram.service 2>/dev/null || true
EOF

chmod 755 "$BUILD_DIR/DEBIAN/prerm"

# 6. Build the package
mkdir -p dist
dpkg-deb --build "$BUILD_DIR" "dist/${PACKAGE_NAME}_${VERSION}_${ARCHITECTURE}.deb"

echo "Package created: dist/${PACKAGE_NAME}_${VERSION}_${ARCHITECTURE}.deb"
