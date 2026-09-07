#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "opi-agent"
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
VENV_DIR = BASE_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
SERVICE_FILE = Path("/etc/systemd/system") / f"{APP_NAME}.service"
SERVICE_USER = "opi-agent"

WORKSPACE_DIR = BASE_DIR / "workspace"
LOGS_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / "run"

VERSION_FALLBACK = "0.1.0"
SENSITIVE_KEY_RE = re.compile(r"(key|token|secret|password|pass|api)", re.I)


def is_true(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def die(message: str, code: int = 1):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def ensure_dirs():
    for p in (WORKSPACE_DIR, LOGS_DIR, RUN_DIR):
        p.mkdir(parents=True, exist_ok=True)


def read_env_file(path: Path = ENV_PATH) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def write_env_file(data: dict[str, str], path: Path = ENV_PATH):
    lines = [f"{k}={v}" for k, v in sorted(data.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def update_env_line(key: str, value: str | None):
    lines = (
        ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    )
    out: list[str] = []
    found = False

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out.append(raw)
            continue

        existing_key, _, existing_value = raw.partition("=")
        if existing_key.strip() == key:
            found = True
            if value is None:
                continue
            out.append(f"{key}={value}")
        else:
            out.append(raw)

    if value is not None and not found:
        out.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def mask_value(key: str, value: str) -> str:
    return "***" if SENSITIVE_KEY_RE.search(key) else value


def run(
    args,
    cwd: Path | None = None,
    check: bool = False,
    capture: bool = False,
    env: dict[str, str] | None = None,
):
    return subprocess.run(
        args,
        cwd=str(cwd or BASE_DIR),
        check=check,
        text=True,
        capture_output=capture,
        env=env,
    )


def git(*args, capture: bool = True, check: bool = False):
    return run(["git", *args], capture=capture, check=check)


def in_git_repo() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_describe() -> str:
    if not in_git_repo():
        return VERSION_FALLBACK
    result = git("describe", "--tags", "--dirty", "--always")
    if result.returncode == 0:
        return result.stdout.strip()
    return VERSION_FALLBACK


def print_version():
    print(git_describe())


def update_status():
    if not in_git_repo():
        print("Not a git repository.")
        return 1

    git("fetch", "--all", "--prune", "--tags")
    branch = git("branch", "--show-current").stdout.strip() or "(detached)"
    status = git("status", "--short", "--branch").stdout.strip()
    print(status or f"On branch {branch}\nworking tree clean")

    upstream = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if upstream.returncode != 0:
        print("No upstream configured.")
        return 0

    counts = git(
        "rev-list", "--left-right", "--count", f"HEAD...{upstream.stdout.strip()}"
    )
    if counts.returncode == 0:
        behind, ahead = counts.stdout.strip().split()
        print(f"ahead={ahead} behind={behind}")
    return 0


def update_check():
    if not in_git_repo():
        print("Not a git repository.")
        return 1

    local_changes = git("status", "--porcelain").stdout.strip()
    if local_changes:
        print("Local changes detected:")
        print(local_changes)
        return 2

    git("fetch", "--all", "--prune", "--tags")
    print("Repository is clean and remote refs were refreshed.")
    return 0


def update_apply(confirm: bool):
    if not confirm:
        die("use --confirm to apply updates")

    if not in_git_repo():
        die("Not a git repository.")

    if git("status", "--porcelain").stdout.strip():
        die("working tree is dirty; commit/stash changes first")

    git("fetch", "--all", "--prune", "--tags")

    result = git("pull", "--ff-only")
    if result.returncode != 0:
        return result.returncode

    compile_result = run(
        [sys.executable, "-m", "py_compile", str(BASE_DIR / "opi_agent.py")]
    )
    if compile_result.returncode != 0:
        die("new code failed syntax check after pull")

    print("Update applied successfully.")
    return 0


def systemctl(*args, capture: bool = False):
    if shutil.which("systemctl") is None:
        die("systemctl is not available on this system")
    return run(["systemctl", *args, APP_NAME], capture=capture)


def service_action(action: str):
    if action == "status":
        return systemctl("status").returncode
    return systemctl(action).returncode


def service_install():
    if os.geteuid() != 0:
        die("service install requires root")

    if not VENV_PYTHON.exists():
        die("virtualenv not found. Run install_opi.sh first.")

    if (
        shutil.which("id")
        and subprocess.run(["id", "-u", SERVICE_USER], capture_output=True).returncode
        != 0
    ):
        run(
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

    unit = f"""[Unit]
Description=OPI Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={SERVICE_USER}
Group={SERVICE_USER}
WorkingDirectory={BASE_DIR}
EnvironmentFile={ENV_PATH}
ExecStart={VENV_PYTHON} {BASE_DIR / "opi_agent.py"} daemon
Restart=on-failure
RestartSec=3

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
ReadWritePaths={WORKSPACE_DIR} {LOGS_DIR} {RUN_DIR}

[Install]
WantedBy=multi-user.target
"""
    SERVICE_FILE.write_text(unit, encoding="utf-8")
    run(["systemctl", "daemon-reload"], check=True)
    run(["systemctl", "enable", "--now", APP_NAME], check=True)
    print(f"{APP_NAME} service installed and started.")


def service_uninstall():
    if os.geteuid() != 0:
        die("service uninstall requires root")
    run(["systemctl", "disable", "--now", APP_NAME], capture=True)
    if SERVICE_FILE.exists():
        SERVICE_FILE.unlink()
    run(["systemctl", "daemon-reload"], check=True)
    print(f"{APP_NAME} service removed.")


def config_show(raw: bool = False):
    data = read_env_file()
    if not ENV_PATH.exists():
        print(f"{ENV_PATH} does not exist.")
        return 1
    for key, value in data.items():
        print(f"{key}={value if raw else mask_value(key, value)}")
    return 0


def config_get(key: str):
    data = read_env_file()
    if key not in data:
        die(f"{key} not found", code=2)
    print(data[key])
    return 0


def config_set(key: str, value: str):
    ensure_dirs()
    data = read_env_file()
    data[key] = value
    write_env_file(data)
    print(f"{key} updated.")
    return 0


def config_unset(key: str):
    data = read_env_file()
    if key in data:
        del data[key]
        write_env_file(data)
        print(f"{key} removed.")
    return 0


def paths_check():
    ensure_dirs()
    checks = [
        ("base_dir", BASE_DIR, True),
        ("workspace", WORKSPACE_DIR, os.access(WORKSPACE_DIR, os.W_OK)),
        ("logs", LOGS_DIR, os.access(LOGS_DIR, os.W_OK)),
        ("run", RUN_DIR, os.access(RUN_DIR, os.W_OK)),
        ("env_exists", ENV_PATH, ENV_PATH.exists()),
        ("venv_python", VENV_PYTHON, VENV_PYTHON.exists()),
    ]
    ok = True
    for name, path, state in checks:
        print(f"{name}: {'OK' if state else 'FAIL'} -> {path}")
        ok = ok and bool(state)
    return 0 if ok else 1


def exec_allowed() -> bool:
    env = read_env_file()
    return is_true(env.get("ALLOW_EXEC", "0"))


def exec_confirm_required() -> bool:
    env = read_env_file()
    return is_true(env.get("EXEC_CONFIRM_REQUIRED", "1"))


def run_exec(cmd_parts: list[str], confirm: bool):
    if not exec_allowed():
        die("exec is disabled. Set ALLOW_EXEC=1 in .env")

    if exec_confirm_required() and not confirm:
        die("exec requires --confirm")

    if not cmd_parts:
        die("no command provided")

    if cmd_parts and cmd_parts[0] == "--":
        cmd_parts = cmd_parts[1:]

    ensure_dirs()
    result = run(cmd_parts, cwd=WORKSPACE_DIR)
    return result.returncode


def daemon_loop():
    ensure_dirs()
    print(f"{APP_NAME} daemon started in {BASE_DIR}")
    while True:
        time.sleep(5)


def telegram_mode():
    print("Telegram mode placeholder. Keep this entrypoint for compatibility.")
    return 0


def chat_mode():
    print("Chat mode placeholder. Type 'exit' to quit.")
    while True:
        try:
            text = input("> ").strip()
        except EOFError:
            break
        if text.lower() in {"exit", "quit"}:
            break
        print(text)
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog=APP_NAME, description="OPI Agent CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version")

    upd = sub.add_parser("update")
    upd_sub = upd.add_subparsers(dest="action", required=True)
    upd_sub.add_parser("status")
    upd_sub.add_parser("check")
    upd_apply = upd_sub.add_parser("apply")
    upd_apply.add_argument("--confirm", action="store_true")

    svc = sub.add_parser("service")
    svc_sub = svc.add_subparsers(dest="action", required=True)
    for name in ("status", "start", "stop", "restart"):
        svc_sub.add_parser(name)

    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="action", required=True)
    show = cfg_sub.add_parser("show")
    show.add_argument("--raw", action="store_true")
    get = cfg_sub.add_parser("get")
    get.add_argument("key")
    setp = cfg_sub.add_parser("set")
    setp.add_argument("key")
    setp.add_argument("value", nargs=argparse.REMAINDER)
    unset = cfg_sub.add_parser("unset")
    unset.add_argument("key")

    paths = sub.add_parser("paths")
    paths_sub = paths.add_subparsers(dest="action", required=True)
    paths_sub.add_parser("check")

    ex = sub.add_parser("exec")
    ex.add_argument("--confirm", action="store_true")
    ex.add_argument("cmd", nargs=argparse.REMAINDER)

    sub.add_parser("daemon")
    sub.add_parser("telegram")
    sub.add_parser("install")
    sub.add_parser("install-full")
    sub.add_parser("uninstall")
    sub.add_parser("chat")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "version":
        return print_version() or 0

    if args.command == "update":
        if args.action == "status":
            return update_status()
        if args.action == "check":
            return update_check()
        if args.action == "apply":
            return update_apply(args.confirm)

    if args.command == "service":
        return service_action(args.action)

    if args.command == "config":
        if args.action == "show":
            return config_show(raw=args.raw)
        if args.action == "get":
            return config_get(args.key)
        if args.action == "set":
            value = " ".join(args.value).strip()
            if not value:
                die("missing value")
            return config_set(args.key, value)
        if args.action == "unset":
            return config_unset(args.key)

    if args.command == "paths":
        return paths_check()

    if args.command == "exec":
        return run_exec(args.cmd, args.confirm)

    if args.command in {"install", "install-full"}:
        service_install()
        return 0

    if args.command == "uninstall":
        service_uninstall()
        return 0

    if args.command == "daemon":
        return daemon_loop()

    if args.command == "telegram":
        return telegram_mode()

    if args.command == "chat":
        return chat_mode()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
