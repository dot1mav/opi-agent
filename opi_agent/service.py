"""Systemd service management for opi-agent."""

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pwd
else:
    try:
        import pwd
    except ImportError:
        pwd = None  # type: ignore

from opi_agent.config import ENV_PATH, get_env
from opi_agent.exceptions import ServiceError
from opi_agent.log import get_logger

logger = get_logger(__name__)

APP_NAME = "opi-agent"
TELEGRAM_APP_NAME = "opi-agent-telegram"
BASE_DIR = Path(__file__).resolve().parent.parent
VENV_DIR = BASE_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
SERVICE_FILE = Path("/etc/systemd/system") / f"{APP_NAME}.service"
TELEGRAM_SERVICE_FILE = Path("/etc/systemd/system") / f"{TELEGRAM_APP_NAME}.service"
SERVICE_USER = "opi-agent"

WORKSPACE_DIR = BASE_DIR / "workspace"
LOGS_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / "run"


def is_root() -> bool:
    """Check if running as root (cross-platform)."""
    if hasattr(os, "geteuid"):
        return bool(os.geteuid() == 0)
    # On Windows, check if we have admin privileges
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
    except Exception:
        return False


def ensure_dirs() -> None:
    """Ensure runtime directories exist."""
    for p in (WORKSPACE_DIR, LOGS_DIR, RUN_DIR):
        p.mkdir(parents=True, exist_ok=True)


def systemctl(*args: str, capture: bool = False, app_name: str = None) -> subprocess.CompletedProcess:
    """Run systemctl command.

    Args:
        *args: systemctl arguments
        capture: Whether to capture output
        app_name: Service name (defaults to APP_NAME)

    Returns:
        CompletedProcess result

    Raises:
        ServiceError: If systemctl not available
    """
    if shutil.which("systemctl") is None:
        raise ServiceError("systemctl is not available on this system")

    name = app_name or APP_NAME
    return subprocess.run(
        ["systemctl", *args, name],
        capture_output=capture,
        text=True,
    )


def service_action(action: str, app_name: str = None) -> int:
    """Perform a service action.

    Args:
        action: Action to perform (status, start, stop, restart)
        app_name: Service name (defaults to APP_NAME)

    Returns:
        Exit code
    """
    if action == "status":
        result = systemctl("status", capture=True, app_name=app_name)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    result = systemctl(action, app_name=app_name)
    return result.returncode


def service_health(app_name: str = None) -> int:
    """Check service health.

    Args:
        app_name: Service name (defaults to APP_NAME)

    Returns:
        0 if healthy, non-zero otherwise
    """
    result = systemctl("is-active", capture=True, app_name=app_name)
    if result.returncode == 0:
        print("Service is active and healthy")
        return 0
    else:
        print(f"Service is not active: {result.stdout.strip()}")
        return result.returncode


def service_logs(follow: bool = False, lines: int = 100, app_name: str = None) -> int:
    """Show service logs.

    Args:
        follow: Follow log output
        lines: Number of lines to show
        app_name: Service name (defaults to APP_NAME)

    Returns:
        Exit code
    """
    name = app_name or APP_NAME
    cmd = ["journalctl", "-u", name, "-n", str(lines)]
    if follow:
        cmd.append("-f")

    try:
        subprocess.run(cmd, check=False)
        return 0
    except FileNotFoundError:
        # Fallback to log file
        log_file = LOGS_DIR / f"{name}.log"
        if log_file.exists():
            cmd = ["tail", "-n", str(lines)]
            if follow:
                cmd.append("-f")
            cmd.append(str(log_file))
            subprocess.run(cmd, check=False)
            return 0
        else:
            msg = "journalctl not available and no log file found"
            raise ServiceError(msg) from None


def service_unit(dry_run: bool = False, app_name: str = None) -> str:
    """Generate systemd unit file content.

    Args:
        dry_run: If True, return content without installing
        app_name: Service name (APP_NAME or TELEGRAM_APP_NAME)

    Returns:
        Unit file content
    """
    venv_python = get_env("OPI_VENV_PYTHON") or str(VENV_PYTHON)
    base_dir = get_env("OPI_BASE_DIR") or str(BASE_DIR)
    service_user = get_env("OPI_SERVICE_USER") or SERVICE_USER

    if app_name == TELEGRAM_APP_NAME:
        service_file = TELEGRAM_SERVICE_FILE
        exec_cmd = f"{venv_python} {base_dir}/opi_agent.py telegram"
        description = "opi-agent Telegram Bot"
        log_paths = f"{LOGS_DIR} {RUN_DIR}"
    else:
        service_file = SERVICE_FILE
        exec_cmd = f"{venv_python} {base_dir}/opi_agent.py daemon"
        description = "OPI Agent"
        log_paths = f"{WORKSPACE_DIR} {LOGS_DIR} {RUN_DIR}"

    unit = f"""[Unit]
Description={description}
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User={service_user}
Group={service_user}
WorkingDirectory={base_dir}
EnvironmentFile={base_dir}/.env
ExecStart={exec_cmd}
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
ReadWritePaths={log_paths}

[Install]
WantedBy=multi-user.target
"""

    if dry_run:
        return unit

    # Write to systemd
    if not is_root():
        raise ServiceError("Service installation requires root privileges")

    service_file.write_text(unit, encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", app_name or APP_NAME], check=True)

    return unit


def service_install(app_name: str = None) -> None:
    """Install and start the systemd service.

    Args:
        app_name: Service name (APP_NAME or TELEGRAM_APP_NAME)
    """
    name = app_name or APP_NAME
    if not is_root():
        raise ServiceError("Service installation requires root privileges")

    if not VENV_PYTHON.exists():
        raise ServiceError("Virtualenv not found. Run install_opi.sh first.")

    # Create service user if needed
    if (
        shutil.which("id")
        and subprocess.run(["id", "-u", SERVICE_USER], capture_output=True).returncode != 0
    ):
        subprocess.run(
            [
                "useradd",
                "--system",
                "--user-group",
                "--home-dir",
                str(BASE_DIR),
                "--shell",
                "/usr/sbin/nologin",
                SERVICE_USER,
            ],
            check=True,
        )

    ensure_dirs()

    # Set ownership
    if name == TELEGRAM_APP_NAME:
        log_paths = [LOGS_DIR, RUN_DIR]
    else:
        log_paths = [WORKSPACE_DIR, LOGS_DIR, RUN_DIR]

    subprocess.run(
        [
            "chown",
            "-R",
            f"{SERVICE_USER}:{SERVICE_USER}",
            *[str(p) for p in log_paths],
        ],
        check=False,
    )
    if ENV_PATH.exists():
        subprocess.run(["chown", f"{SERVICE_USER}:{SERVICE_USER}", str(ENV_PATH)], check=False)
        subprocess.run(["chmod", "600", str(ENV_PATH)], check=False)

    service_unit(dry_run=False, app_name=name)
    logger.info("%s service installed and started", name)


def service_uninstall(app_name: str = None) -> None:
    """Uninstall the systemd service.

    Args:
        app_name: Service name (APP_NAME or TELEGRAM_APP_NAME)
    """
    name = app_name or APP_NAME
    service_file = TELEGRAM_SERVICE_FILE if name == TELEGRAM_APP_NAME else SERVICE_FILE

    if not is_root():
        raise ServiceError("Service uninstallation requires root privileges")

    subprocess.run(["systemctl", "disable", "--now", name], capture_output=True)
    if service_file.exists():
        service_file.unlink()
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    logger.info("%s service removed", name)
