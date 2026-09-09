# OPI Agent

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-green.svg)](https://www.python.org/downloads/)
[![CI/CD](https://github.com/dot1mav/opi-agent/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/dot1mav/opi-agent/actions/workflows/ci-cd.yml)

> **Agent runtime for Orange Pi single-board computers** -- manage services, execute commands,
> and monitor devices through a CLI, Telegram bot, or interactive chat mode with a hardened
> subagent system.

> :warning: **Security Warning:** This agent is designed to run on single-board computers with
> elevated privileges. It includes command execution capabilities. Always review and restrict
> the allowed commands, paths, and Telegram user lists before deploying to production. Never
> expose the Telegram bot token or `.env` file.

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Layout](#project-layout)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Telegram Bot](#telegram-bot)
- [Chat Mode](#chat-mode)
- [Subagent System](#subagent-system)
- [Configuration](#configuration)
- [Exec Security](#exec-security)
- [Service Management](#service-management)
- [Updating and Rollback](#updating-and-rollback)
- [Development](#development)
- [CI/CD](#cicd)
- [Troubleshooting](#troubleshooting)
- [Release Procedure](#release-procedure)
- [Command Reference Summary](#command-reference-summary)
- [License](#license)

---

## Overview

**opi-agent** is a Python-based agent runtime designed for Orange Pi single-board computers. It provides a secure, auditable interface for remote system administration via:

- **CLI** for local and SSH-based management
- **Telegram bot** for mobile administration with webhook and polling modes
- **Chat mode** for interactive terminal sessions
- **Subagent system** for parallel task execution with lifecycle management
- **Automatic updates** via Git with automatic rollback on failure
- **Patch system** for applying remote patches from configurable sources
- **Systemd integration** with comprehensive security hardening
- **Daemon mode** with health-check heartbeats

---

## Features

| Feature | Description |
|---------|-------------|
| Modular Architecture | Clean separation of concerns across 12 purpose-built modules |
| Telegram Integration | Full-featured bot with webhook and polling support |
| Remote Execution | Secure command execution with path and allowlist validation |
| Subagent System | Parallel task execution with configurable limits and timeouts |
| Self-Updating | Git-based updates with automatic rollback on failure |
| Patch System | Apply remote patches from configurable URLs and paths |
| Systemd Service | Hardened service with watchdog, resource limits, and sandboxing |
| Configuration Management | `.env`-based config with JSON Schema validation |
| Security Hardening | Defense-in-depth: no shell, privilege restrictions, path allowlists |
| Health Monitoring | Daemon mode with configurable heartbeat intervals |
| Comprehensive Logging | Structured logging with console, file, and syslog outputs |
| Audit Trail | Full command and action logging for compliance |

---

## Project Layout

```
opi-agent/
+-- .github/
|   +-- workflows/
|       +-- ci-cd.yml              # GitHub Actions CI/CD pipeline
+-- opi_agent/                     # Main Python package
|   +-- __init__.py                # Package metadata and version
|   +-- cli.py                     # CLI argument parsing & command dispatch
|   +-- config.py                  # .env read/write, get/set, patch helpers
|   +-- daemon.py                  # Daemon loop & interactive chat mode
|   +-- exceptions.py              # Typed exception hierarchy
|   +-- exec.py                    # Secure command execution engine
|   +-- log.py                     # Logging configuration
|   +-- schemas.py                 # Config key schemas & validation
|   +-- service.py                 # Systemd service install/uninstall/ctl
|   +-- subagent.py                # Subagent lifecycle manager
|   +-- telegram.py                # Telegram bot (polling, webhook, scheduler)
|   +-- update.py                  # Git-based self-update & rollback
+-- tests/                         # Test suite
|   +-- conftest.py                # Shared pytest fixtures
|   +-- test_config.py             # Config read/write/validation tests
|   +-- test_patch.py              # Patch listing & application tests
|   +-- test_subagent.py           # Subagent spawn/kill/cleanup tests
|   +-- test_update.py             # Update/rollback tests
+-- install_opi.sh                 # Bash installer (venv + systemd)
+-- pyproject.toml                 # Build config, tool settings
+-- requirements.txt               # Runtime dependencies
+-- requirements-dev.txt           # Dev dependencies
+-- .env.example                   # Example configuration
+-- .env                           # Active configuration (git-ignored)
+-- README.md                      # This file
+-- LICENSE                        # MIT License
```

---

## Installation

### Prerequisites

| Requirement | Minimum Version | Purpose |
|------------|----------------|---------|
| Python | 3.11+ | Runtime |
| Git | 2.0+ | Updates and patches |
| systemd | 245+ | Service management |
| sudo | any | Installation only |

### Quick Install (Recommended)

```bash
git clone https://github.com/dot1mav/opi-agent.git
cd opi-agent
chmod +x install_opi.sh
sudo ./install_opi.sh
```

### Installer Flags

| Flag | Description |
|------|-------------|
| `--skip-service` | Skip systemd service installation entirely |
| `--no-start` | Install but do not start the service |
| `--with-telegram` | Enable Telegram bot integration during install |

### Manual Installation

```bash
# Create virtual environment
python3 -m venv /opt/opi-agent/venv
source /opt/opi-agent/venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example /opt/opi-agent/.env
nano /opt/opi-agent/.env

# Verify configuration
opi-agent config show

# Install and start service
sudo cp opi-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now opi-agent
```

---

## Quick Start

```bash
# Show version and build info
opi-agent version

# Display current configuration
opi-agent config show

# Execute a command securely
opi-agent exec -- echo "Hello from opi-agent"

# Start the daemon (background heartbeat)
opi-agent daemon

# Start the Telegram bot
opi-agent telegram

# Enter interactive chat mode
opi-agent chat

# Check service health
opi-agent service health
```

---

## CLI Reference

The CLI is available as `opi-agent <command>`, or via `python opi_agent.py <command>` and `python -m opi_agent <command>`.

### General Commands

| Command | Description |
|---------|-------------|
| `version` | Show version, build, and Python info |
| `paths check` | Validate all configured paths exist and are accessible |

### Update Commands

| Command | Description |
|---------|-------------|
| `update status` | Show git status and ahead/behind counts |
| `update check` | Check for available updates from remote |
| `update apply --confirm` | Apply updates (fast-forward only) |
| `update rollback --confirm` | Rollback to the previous version |

### Service Commands

| Command | Description |
|---------|-------------|
| `service status` | Show systemd service status |
| `service start` | Start the agent service |
| `service stop` | Stop the agent service |
| `service restart` | Restart the agent service |
| `service health` | Run a health check |
| `service logs` | View service journal logs (supports `--follow`) |
| `service unit` | Show the generated systemd unit file |

### Config Commands

| Command | Description |
|---------|-------------|
| `config show` | Display all configuration values |
| `config get <key>` | Get a specific configuration value |
| `config set <key> <value>` | Set a configuration value |
| `config unset <key>` | Remove a configuration value |
| `config schemas` | Show all configuration schema definitions |

### Exec Commands

| Command | Description |
|---------|-------------|
| `exec -- <command>` | Execute a command with security checks |
| `exec --timeout <sec>` | Override execution timeout |

### Daemon Commands

| Command | Description |
|---------|-------------|
| `daemon` | Start daemon mode with heartbeat |
| `daemon --heartbeat <sec>` | Override heartbeat interval |

### Patch Commands

| Command | Description |
|---------|-------------|
| `patch list` | List available patches |
| `patch set-url <url>` | Set the patch source URL |
| `patch set-path <path>` | Set the local patch path |
| `patch apply` | Apply the configured patch |

### Subagent Commands

| Command | Description |
|---------|-------------|
| `subagent list` | List all active subagents |
| `subagent status <id>` | Show status of a specific subagent |
| `subagent kill <id>` | Kill a specific subagent |
| `subagent kill-all` | Kill all running subagents |
| `subagent cleanup` | Clean up completed/failed subagents |

### Telegram Command

| Command | Description |
|---------|-------------|
| `telegram` | Start the Telegram bot (webhook or polling) |

### Install / Uninstall

| Command | Description |
|---------|-------------|
| `install --service <name>` | Install systemd service (opi-agent, opi-agent-telegram, or both) |
| `uninstall --service <name>` | Uninstall systemd service |

---

## Telegram Bot

### Setup

1. Create a bot via [@BotFather](https://t.me/BotFather) and obtain the token.
2. Configure the `.env` file with your token and allowed users.
3. Start the bot: `opi-agent telegram`

### Supported Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and bot introduction |
| `/help` | Show all available commands |
| `/status` | Show agent and system status |
| `/config` | Show current configuration |
| `/exec <command>` | Execute a command (restricted to allowed users) |
| `/logs [lines]` | Show recent log entries |
| `/subagents` | List active subagents |
| `/spawn <task>` | Spawn a new subagent |
| `/kill <id>` | Kill a specific subagent |
| `/ping` | Health check ping |
| `/version` | Show version information |

### Telegram Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | *(required)* |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated list of allowed user IDs | *(empty = block all)* |
| `TELEGRAM_WEBHOOK_URL` | Public URL for webhook mode | *(empty = polling)* |
| `TELEGRAM_WEBHOOK_PORT` | Port for webhook server | `8443` |
| `TELEGRAM_WEBHOOK_CERT` | Path to SSL certificate for webhook | *(optional)* |
| `TELEGRAM_WEBHOOK_KEY` | Path to SSL private key for webhook | *(optional)* |
| `TELEGRAM_PROXY` | SOCKS5/HTTP proxy URL | *(empty = direct)* |
| `TELEGRAM_PARSE_MODE` | Message parse mode (`HTML`, `Markdown`) | `HTML` |
| `TELEGRAM_MAX_FILE_SIZE_MB` | Max upload file size in MB | `50` |

---

## Chat Mode

Interactive terminal mode for local administration.

```bash
opi-agent chat
```

### Chat Commands

| Command | Description |
|---------|-------------|
| `help` | Show available chat commands |
| `status` | Display agent and system status |
| `config` | Show current configuration |
| `exec <command>` | Execute a command |
| `exit` / `quit` | Exit chat mode |

---

## Subagent System

The subagent system enables parallel task execution with full lifecycle management.

### Architecture

```
+--------------------------------------------------+
|                   opi-agent                       |
|                                                   |
|  +----------+    +----------+    +----------+    |
|  | CLI      |    | Telegram |    | Chat     |    |
|  +----+-----+    +----+-----+    +----+-----+    |
|       |               |               |           |
|       +---------------+---------------+           |
|                       |                           |
|                       v                           |
|              +----------------+                   |
|              |  Subagent Mgr  |                   |
|              |  (subagent.py) |                   |
|              +-------+--------+                   |
|                      |                            |
|        +-------------+-------------+              |
|        v             v             v              |
|  +----------+  +----------+  +----------+        |
|  |Subagent 1|  |Subagent 2|  |Subagent N|        |
|  | PENDING  |  | RUNNING  |  | COMPLETED|        |
|  +----------+  +----------+  +----------+        |
+--------------------------------------------------+
```

### Subagent States

| State | Description |
|-------|-------------|
| `PENDING` | Created, waiting to be scheduled |
| `RUNNING` | Currently executing a task |
| `COMPLETED` | Task finished successfully |
| `FAILED` | Task ended with an error |
| `KILLED` | Terminated by user or system |

### Subagent Configuration

| Key | Description | Default |
|-----|-------------|---------|
| `OPI_SUBAGENT_ENABLED` | Enable the subagent system | `false` |
| `OPI_SUBAGENT_MAX_COUNT` | Maximum concurrent subagents | `3` |
| `OPI_SUBAGENT_TIMEOUT` | Subagent execution timeout (seconds) | `120` |

### CLI Usage

```bash
# List active subagents
python opi_agent.py subagent list

# Check status of a specific subagent
python opi_agent.py subagent status <subagent-id>

# Kill a specific subagent
python opi_agent.py subagent kill <subagent-id>

# Kill all running subagents
python opi_agent.py subagent kill-all

# Clean up completed/failed subagents
python opi_agent.py subagent cleanup
```

### Telegram Usage

```
/subagents                    # List active subagents
/spawn analyze disk usage     # Spawn a new subagent
/kill <subagent-id>           # Kill a specific subagent
```

### Programmatic Usage

```python
from opi_agent.subagent import SubagentManager

manager = SubagentManager(config)

# Spawn a subagent
subagent_id = await manager.spawn(
    task="analyze disk usage",
    timeout=120
)

# Check status
status = await manager.status(subagent_id)
print(f"State: {status.state}")

# Kill if needed
await manager.kill(subagent_id)

# Cleanup finished subagents
cleaned = await manager.cleanup()
print(f"Cleaned up {cleaned} subagents")
```

---

## Configuration

All configuration is managed via `.env` file with JSON Schema validation.

### Core Settings

| Key | Description | Default |
|-----|-------------|---------|
| `OPI_BASE_DIR` | Base directory for agent data | `/opt/opi` |
| `OPI_SERVICE_NAME` | Systemd service name | `opi-agent` |
| `OPI_HEARTBEAT_SECONDS` | Daemon heartbeat interval | `60` |

### Execution Security

| Key | Description | Default |
|-----|-------------|---------|
| `OPI_SHELL_ENABLED` | Allow shell execution (strongly discouraged) | `false` |
| `OPI_ALLOWED_COMMANDS` | Comma-separated command allowlist | *(empty = block all)* |
| `OPI_ALLOWED_PATHS` | Colon-separated path allowlist for file arguments | *(empty = block all)* |
| `OPI_EXEC_TIMEOUT` | Default execution timeout (seconds) | `30` |
| `OPI_EXTRA_GROUPS` | Additional user groups for execution | *(empty)* |
| `OPI_GRANT_ACL` | ACL grants for specific paths | *(empty)* |

### Update and Patch

| Key | Description | Default |
|-----|-------------|---------|
| `OPI_PATCH_URL` | Remote patch source URL | *(empty)* |
| `OPI_PATCH_PATH` | Local patch directory path | *(empty)* |
| `OPI_UPDATE_BRANCH` | Git branch for updates | `main` |
| `OPI_ORIGIN_URL` | Git remote origin URL | *(auto-detected)* |

### Subagent Settings

| Key | Description | Default |
|-----|-------------|---------|
| `OPI_SUBAGENT_ENABLED` | Enable subagent system | `false` |
| `OPI_SUBAGENT_MAX_COUNT` | Maximum concurrent subagents | `3` |
| `OPI_SUBAGENT_TIMEOUT` | Subagent timeout (seconds) | `120` |

### Telegram Settings

| Key | Description | Default |
|-----|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | *(required)* |
| `TELEGRAM_ALLOWED_USERS` | Allowed user IDs (comma-separated) | *(empty)* |
| `TELEGRAM_WEBHOOK_URL` | Webhook URL (empty for polling) | *(empty)* |
| `TELEGRAM_WEBHOOK_PORT` | Webhook server port | `8443` |
| `TELEGRAM_WEBHOOK_CERT` | SSL certificate path | *(optional)* |
| `TELEGRAM_WEBHOOK_KEY` | SSL private key path | *(optional)* |
| `TELEGRAM_PROXY` | SOCKS5/HTTP proxy URL | *(empty)* |
| `TELEGRAM_PARSE_MODE` | Message parse mode | `HTML` |
| `TELEGRAM_MAX_FILE_SIZE_MB` | Max upload size in MB | `50` |

### Example `.env`

```ini
# Core
OPI_BASE_DIR=/opt/opi
OPI_SERVICE_NAME=opi-agent
OPI_HEARTBEAT_SECONDS=60

# Execution Security
OPI_SHELL_ENABLED=false
OPI_ALLOWED_COMMANDS=ls,cat,df,uptime,free,top,uname
OPI_ALLOWED_PATHS=/opt/opi/workspace:/tmp
OPI_EXEC_TIMEOUT=30
OPI_GRANT_ACL=false

# Updates
OPI_UPDATE_BRANCH=main
OPI_ORIGIN_URL=https://github.com/dot1mav/opi-agent.git

# Subagents
OPI_SUBAGENT_ENABLED=false
OPI_SUBAGENT_MAX_COUNT=3
OPI_SUBAGENT_TIMEOUT=120

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_WEBHOOK_PORT=8443
TELEGRAM_PROXY=
TELEGRAM_PARSE_MODE=HTML
TELEGRAM_MAX_FILE_SIZE_MB=50
```

## Exec Security

The execution engine implements defense-in-depth security measures.

### Security Defenses

| Layer | Defense | Description |
|-------|---------|-------------|
| Shell | `shell=False` | Commands executed without shell interpretation |
| Privileges | No `sudo`/`su`/`doas`/`pkexec` | Privilege escalation commands blocked |
| Metacharacters | No shell metacharacters | `|`, `&`, `;`, `$`, backticks, etc. blocked |
| Allowlist | Command allowlist | Only whitelisted commands can execute |
| Paths | Path validation | File operations restricted to allowed paths |
| Timeout | Execution timeout | Commands terminated after configurable timeout |
| Groups | Group restrictions | Execute with minimal system groups |
| ACL | ACL grants | Fine-grained file access control |
| Logging | Full audit log | All execution attempts are logged |

### Configuration

```ini
# Disable shell (recommended)
OPI_SHELL_ENABLED=false

# Allow only specific commands
OPI_ALLOWED_COMMANDS=uptime,df,free,top,ps

# Restrict file access paths
OPI_ALLOWED_PATHS=/opt/opi-agent,/var/log

# Set execution timeout
OPI_EXEC_TIMEOUT=30

# Grant specific ACLs
OPI_GRANT_ACL=/var/log:read,/tmp:write
```

---

## Service Management

### Systemd Hardening Features

The generated systemd unit file includes comprehensive security hardening:

| Directive                          | Purpose                                    |
|------------------------------------|--------------------------------------------|
| `Type=notify`                      | Service notifies systemd when ready        |
| `WatchdogSec=30`                   | systemd monitors heartbeat                 |
| `Restart=on-failure`               | Automatic restart on crash                 |
| `RestartSec=3`                     | 3-second delay before restart              |
| `NoNewPrivileges=true`             | Cannot gain new privileges via setuid      |
| `ProtectSystem=strict`             | Filesystem read-only except ReadWritePaths |
| `ProtectHome=read-only`            | Home directories are read-only             |
| `PrivateTmp=true`                  | Isolated `/tmp` namespace                  |
| `PrivateDevices=true`              | No access to physical devices              |
| `ProtectKernelTunables=true`       | Cannot modify `/proc`, `/sys`              |
| `ProtectKernelModules=true`        | Cannot load/unload kernel modules          |
| `ProtectControlGroups=true`        | Cannot modify cgroups                      |
| `LockPersonality=true`             | Locks execution domain                     |
| `MemoryDenyWriteExecute=true`      | No W^X memory pages                        |
| `RestrictSUIDSGID=true`            | Cannot create setuid/setgid files          |
| `RestrictNamespaces=true`          | Cannot create new namespaces               |
| `SystemCallArchitectures=native`   | Only native syscall ABI                    |
| `SystemCallFilter=@system-service` | Whitelist of system service syscalls       |
| `CapabilityBoundingSet=`           | Drop all Linux capabilities                |
| `AmbientCapabilities=`             | No ambient capabilities                    |

### Service Commands

```bash
# Main daemon service
opi-agent service status
opi-agent service start
opi-agent service stop
opi-agent service restart
opi-agent service health
opi-agent service logs -f -n 100
opi-agent service unit --dry-run

# Telegram bot service
opi-agent service --service opi-agent-telegram status
opi-agent service --service opi-agent-telegram start

# Install/uninstall
opi-agent install --service both
opi-agent uninstall --service both
```

## Updating and Rollback

### Update Process

1. **Check** - Compare local version with remote
2. **Stash** - Preserve any local changes
3. **Pull** - Fetch and merge updates from the configured branch
4. **Install** - Install any new dependencies
5. **Verify** - Run post-update verification
6. **Restart** - Restart the service if running

### Commands

```bash
# Check for updates
opi-agent update check

# Apply updates
opi-agent update apply --confirm

# Rollback to previous version
opi-agent update rollback --confirm

# View update status
opi-agent update status
```

### Rollback

If an update fails or causes issues, rollback restores the previous version:

```bash
opi-agent update rollback --confirm
```

The rollback uses the git reflog to restore `HEAD@{1}` and reinstalls dependencies.

---

## Development

### Development Dependencies

```bash
pip install -r requirements-dev.txt
```

| Tool | Purpose |
|------|---------|
| `pytest` | Test runner |
| `pytest-cov` | Code coverage reporting |
| `ruff` | Fast Python linter and formatter |
| `mypy` | Static type checker |
| `bandit` | Security-focused linter |
| `pip-audit` | Dependency vulnerability scanner |

### Setup

```bash
# Clone the repository
git clone https://github.com/dot1mav/opi-agent.git
cd opi-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install all dependencies
pip install -r requirements.txt -r requirements-dev.txt

# Run tests
pytest

# Run with coverage
pytest --cov=opi_agent --cov-report=term-missing
```

### Linting and Formatting

```bash
# Lint
ruff check .

# Format
ruff format .

# Type check
mypy opi_agent/

# Security audit
bandit -r opi_agent/

# Dependency audit
pip-audit
```

### Running Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_config.py

# Run with coverage
pytest --cov=opi_agent --cov-report=html
```

---

## CI/CD

The project uses GitHub Actions for continuous integration and deployment.

### Pipeline Steps

| Step | Description |
|------|-------------|
| Checkout | Clone the repository |
| Python Setup | Set up Python 3.11+ |
| Install Dependencies | Install production and dev requirements |
| Lint (ruff) | Check code style and formatting |
| Type Check (mypy) | Static type verification |
| Security (bandit) | Security-focused code analysis |
| Test (pytest) | Run test suite with coverage |
| Audit (pip-audit) | Check for dependency vulnerabilities |
| Build | Build distribution packages |
| Release | Create GitHub releases (on tag push) |

### Triggering

| Event | Action |
|-------|--------|
| Push to `main` | Run full CI pipeline |
| Pull Request | Run full CI pipeline |
| Tag `v*` | Run CI + create release |

---

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| `Permission denied` | Insufficient privileges | Use `sudo` for system operations |
| `Command not in allowlist` | Command not in `OPI_ALLOWED_COMMANDS` | Add command to the allowlist in `.env` |
| `Path not allowed` | Path not in `OPI_ALLOWED_PATHS` | Add path to the allowlist in `.env` |
| `Execution timeout` | Command took too long | Increase `OPI_EXEC_TIMEOUT` |
| `Service failed to start` | Configuration error | Check `service logs` for details |
| `Telegram connection failed` | Network or token issue | Verify `TELEGRAM_BOT_TOKEN` and network |
| `Update failed` | Git or dependency error | Check logs, use `update rollback` |
| `Subagent limit reached` | Too many concurrent subagents | Kill idle subagents or increase limit |
| `Config validation failed` | Invalid config value | Check config with `config schemas` |

### Debug Commands

```bash
# Check service status and logs
python opi_agent.py service status
python opi_agent.py service logs --follow

# Validate configuration
python opi_agent.py config show
python opi_agent.py config schemas

# Check system paths
python opi_agent.py paths check

# Test execution
python opi_agent.py exec -- "echo hello"

# Health check
python opi_agent.py service health

# Version info
python opi_agent.py version
```

---

## Release Procedure

1. Update version in `opi_agent/__init__.py`
2. Update `CHANGELOG.md` with release notes
3. Commit all changes: `git commit -am "Release vX.Y.Z"`
4. Create tag: `git tag vX.Y.Z`
5. Push: `git push origin main --tags`
6. GitHub Actions will automatically create the release

### Versioning

This project follows [Semantic Versioning](https://semver.org/):

- **Major** (X.0.0) - Breaking changes
- **Minor** (0.X.0) - New features, backward compatible
- **Patch** (0.0.X) - Bug fixes, backward compatible

---

## Command Reference Summary

| Command | Description |
|---------|-------------|
| `version` | Show version information |
| `paths check` | Validate configured paths |
| `config show` | Display all configuration |
| `config get <key>` | Get a config value |
| `config set <key> <value>` | Set a config value |
| `config unset <key>` | Remove a config value |
| `config schemas` | Show config schemas |
| `exec -- <cmd>` | Execute a command |
| `daemon` | Start daemon mode |
| `chat` | Enter chat mode |
| `telegram` | Start Telegram bot |
| `update status` | Show update status |
| `update check` | Check for updates |
| `update apply --confirm` | Apply updates (fast-forward) |
| `update rollback --confirm` | Rollback to previous version |
| `service status` | Show service status |
| `service start` | Start service |
| `service stop` | Stop service |
| `service restart` | Restart service |
| `service health` | Run health check |
| `service logs` | View service logs |
| `service unit` | Show systemd unit file |
| `patch list` | List available patches |
| `patch set-url <url>` | Set patch source URL |
| `patch set-path <path>` | Set local patch path |
| `patch apply` | Apply patches |
| `subagent list` | List active subagents |
| `subagent status <id>` | Show subagent status |
| `subagent kill <id>` | Kill a subagent |
| `subagent kill-all` | Kill all subagents |
| `subagent cleanup` | Clean up finished subagents |
| `install --service <name>` | Install systemd service |
| `uninstall --service <name>` | Uninstall systemd service |

---

## License

This project is licensed under the **MIT License**. See the [LICENSE](LICENSE) file for details.

```
MIT License

Copyright (c) 2024 dot1mav

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

*Built with care by [dot1mav](https://github.com/dot1mav)*
