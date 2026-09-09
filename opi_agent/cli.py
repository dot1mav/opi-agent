"""CLI argument parsing and command dispatch for opi-agent."""

import argparse
import sys

from opi_agent.config import (
    ENV_PATH,
    config_get,
    config_set,
    config_show,
    config_unset,
    get_patch_path,
    list_patches,
    set_patch_path,
    set_patch_url,
)
from opi_agent.daemon import chat_mode, daemon_loop
from opi_agent.exceptions import ConfigError, ExecError, OpiAgentError, ServiceError, SubagentError, UpdateError
from opi_agent.exec import run_exec
from opi_agent.log import get_logger, setup_logging
from opi_agent.schemas import CONFIG_SCHEMAS, validate_value
from opi_agent.service import (
    service_action,
    service_health,
    service_install,
    service_logs,
    service_uninstall,
    service_unit,
)
from opi_agent.telegram import run_telegram_bot
from opi_agent.update import (
    print_version,
    update_apply,
    update_check,
    update_rollback,
    update_status,
)

logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(
        prog="opi-agent",
        description="OPI Agent CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    # version
    sub.add_parser("version", help="Print agent version")

    # update
    upd = sub.add_parser("update", help="Update management")
    upd_sub = upd.add_subparsers(dest="action", required=True, metavar="ACTION")
    upd_sub.add_parser("status", help="Show git status")
    upd_sub.add_parser("check", help="Check for updates")
    upd_apply = upd_sub.add_parser("apply", help="Apply updates (fast-forward only)")
    upd_apply.add_argument("--confirm", action="store_true", required=True, help="Confirm update")
    upd_rollback = upd_sub.add_parser("rollback", help="Rollback to previous commit")
    upd_rollback.add_argument(
        "--confirm", action="store_true", required=True, help="Confirm rollback"
    )

    # service
    svc = sub.add_parser("service", help="Service management")
    svc.add_argument("--service", choices=["opi-agent", "opi-agent-telegram"], default="opi-agent", help="Service to manage")
    svc_sub = svc.add_subparsers(dest="action", required=True, metavar="ACTION")
    svc_sub.add_parser("status", help="Show service status")
    svc_sub.add_parser("start", help="Start service")
    svc_sub.add_parser("stop", help="Stop service")
    svc_sub.add_parser("restart", help="Restart service")
    svc_sub.add_parser("health", help="Check service health")
    svc_logs = svc_sub.add_parser("logs", help="Show service logs")
    svc_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    svc_logs.add_argument("-n", "--lines", type=int, default=100, help="Number of lines to show")
    svc_unit = svc_sub.add_parser("unit", help="Show/generate systemd unit")
    svc_unit.add_argument("--dry-run", action="store_true", help="Show unit without installing")

    # config
    cfg = sub.add_parser("config", help="Configuration management")
    cfg_sub = cfg.add_subparsers(dest="action", required=True, metavar="ACTION")
    show = cfg_sub.add_parser("show", help="Show all configuration")
    show.add_argument("--raw", action="store_true", help="Show unmasked values")
    get = cfg_sub.add_parser("get", help="Get a configuration value")
    get.add_argument("key", help="Configuration key")
    setp = cfg_sub.add_parser("set", help="Set a configuration value")
    setp.add_argument("key", help="Configuration key")
    setp.add_argument("value", nargs=argparse.REMAINDER, help="Configuration value")
    unset = cfg_sub.add_parser("unset", help="Remove a configuration key")
    unset.add_argument("key", help="Configuration key")
    validate = cfg_sub.add_parser("validate", help="Validate configuration")
    validate.add_argument("key", nargs="?", help="Specific key to validate (default: all)")

    # paths
    paths = sub.add_parser("paths", help="Path validation")
    paths_sub = paths.add_subparsers(dest="action", required=True, metavar="ACTION")
    paths_sub.add_parser("check", help="Check configured paths")

    # exec
    ex = sub.add_parser("exec", help="Execute a command (requires OPI_SHELL_ENABLED=1)")
    ex.add_argument(
        "--confirm", action="store_true", help="Confirm execution (required by default)"
    )
    ex.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to execute")

    # daemon
    sub.add_parser("daemon", help="Run daemon loop (used by systemd)")

    # patch
    patch = sub.add_parser("patch", help="Patch management")
    patch_sub = patch.add_subparsers(dest="action", required=True, metavar="ACTION")
    patch_sub.add_parser("list", help="List available patches")
    patch_apply = patch_sub.add_parser("apply", help="Apply a patch")
    patch_apply.add_argument("patch_file", help="Patch file name or path")
    patch_apply.add_argument(
        "--dry-run", action="store_true", help="Check if patch applies cleanly"
    )
    patch_url = patch_sub.add_parser("set-url", help="Set patch base URL")
    patch_url.add_argument("url", help="Patch base URL")
    patch_path = patch_sub.add_parser("set-path", help="Set local patch path")
    patch_path.add_argument("path", help="Local patch directory path")

    # chat
    sub.add_parser("chat", help="Interactive chat mode (placeholder)")

    # telegram
    sub.add_parser("telegram", help="Run Telegram bot (long polling or webhook)")

    # install/uninstall (for CLI convenience)
    install = sub.add_parser("install", help="Install systemd service (requires root)")
    install.add_argument("--service", choices=["opi-agent", "opi-agent-telegram", "both"], default="opi-agent", help="Service to install")
    uninstall = sub.add_parser("uninstall", help="Uninstall systemd service (requires root)")
    uninstall.add_argument("--service", choices=["opi-agent", "opi-agent-telegram", "both"], default="opi-agent", help="Service to uninstall")

    # subagent
    sa = sub.add_parser("subagent", help="Subagent management")
    sa_sub = sa.add_subparsers(dest="action", required=True, metavar="ACTION")
    sa_sub.add_parser("list", help="List all subagents")
    sa_sub.add_parser("status", help="Show subagent summary")
    sa_kill = sa_sub.add_parser("kill", help="Kill a subagent")
    sa_kill.add_argument("agent_id", help="Subagent ID to kill")
    sa_sub.add_parser("kill-all", help="Kill all active subagents")
    sa_sub.add_parser("cleanup", help="Remove finished subagents from registry")

    return parser


def handle_config(args: argparse.Namespace) -> int:
    """Handle config subcommands."""
    try:
        if args.action == "show":
            data = config_show(raw=args.raw)
            for key, value in data.items():
                print(f"{key}={value}")
            return 0

        if args.action == "get":
            value = config_get(args.key)  # type: ignore[assignment]
            if value is None:
                return 1
            print(value)
            return 0

        if args.action == "set":
            value = " ".join(args.value).strip()
            if not value:
                raise ConfigError("Missing value")
            config_set(args.key, value)
            print(f"{args.key} updated.")
            return 0

        if args.action == "unset":
            if config_unset(args.key):
                print(f"{args.key} removed.")
            else:
                print(f"{args.key} not found.")
            return 0

        if args.action == "validate":
            data = config_show(raw=True)
            keys = [args.key] if args.key else list(CONFIG_SCHEMAS.keys())

            errors = 0
            for key in keys:
                if key in data:
                    schema = CONFIG_SCHEMAS.get(key)
                    if schema:
                        is_valid, error = validate_value(schema, data[key])
                        if is_valid:
                            print(f"{key}: OK")
                        else:
                            print(f"{key}: FAIL - {error}")
                            errors += 1
                    else:
                        print(f"{key}: UNKNOWN (no schema)")
                else:
                    print(f"{key}: NOT SET")
            return 1 if errors > 0 else 0

    except ConfigError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code

    return 1


def handle_service(args: argparse.Namespace) -> int:
    """Handle service subcommands."""
    from opi_agent.service import APP_NAME, TELEGRAM_APP_NAME

    service_name = TELEGRAM_APP_NAME if args.service == "opi-agent-telegram" else APP_NAME

    try:
        if args.action == "status":
            return service_action("status", service_name)
        if args.action == "start":
            return service_action("start", service_name)
        if args.action == "stop":
            return service_action("stop", service_name)
        if args.action == "restart":
            return service_action("restart", service_name)
        if args.action == "health":
            return service_health(service_name)
        if args.action == "logs":
            return service_logs(follow=args.follow, lines=args.lines, app_name=service_name)
        if args.action == "unit":
            unit = service_unit(dry_run=args.dry_run, app_name=service_name)
            if args.dry_run:
                print(unit)
            return 0
    except ServiceError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    return 1


def handle_update(args: argparse.Namespace) -> int:
    """Handle update subcommands."""
    try:
        if args.action == "status":
            return update_status()
        if args.action == "check":
            return update_check()
        if args.action == "apply":
            return update_apply(args.confirm)
        if args.action == "rollback":
            return update_rollback(args.confirm)
    except UpdateError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    return 1


def handle_exec(args: argparse.Namespace) -> int:
    """Handle exec command."""
    try:
        return run_exec(args.cmd, args.confirm)
    except ExecError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code


def handle_paths(args: argparse.Namespace) -> int:
    """Handle paths subcommands."""
    from opi_agent.config import BASE_DIR, LOGS_DIR, RUN_DIR, VENV_PYTHON, WORKSPACE_DIR

    if args.action == "check":
        checks = [
            ("base_dir", BASE_DIR, True),
            ("workspace", WORKSPACE_DIR, WORKSPACE_DIR.exists() and WORKSPACE_DIR.is_dir()),
            ("logs", LOGS_DIR, LOGS_DIR.exists() and LOGS_DIR.is_dir()),
            ("run", RUN_DIR, RUN_DIR.exists() and RUN_DIR.is_dir()),
            ("env_exists", ENV_PATH, ENV_PATH.exists()),
            ("venv_python", VENV_PYTHON, VENV_PYTHON.exists()),
        ]
        ok = True
        for name, path, state in checks:
            status = "OK" if state else "FAIL"
            print(f"{name}: {status} -> {path}")
            ok = ok and state
        return 0 if ok else 1
    return 1


def handle_patch(args: argparse.Namespace) -> int:
    """Handle patch subcommands."""
    try:
        if args.action == "list":
            patches = list_patches()
            if patches:
                for p in patches:
                    print(p.name)
            else:
                print("No patches found")
            return 0

        if args.action == "apply":
            patch_path = get_patch_path()
            if not patch_path:
                raise ConfigError("OPI_PATCH_PATH not configured")

            # Find patch file
            patch_file = patch_path / args.patch_file
            if not patch_file.exists():
                # Try without extension
                for ext in [".patch", ".diff"]:
                    test = patch_path / (args.patch_file + ext)
                    if test.exists():
                        patch_file = test
                        break

            if not patch_file.exists():
                raise ConfigError(f"Patch file not found: {args.patch_file}")

            from opi_agent.config import apply_patch

            apply_patch(patch_file, dry_run=args.dry_run)
            print("Patch applied successfully" if not args.dry_run else "Patch would apply cleanly")
            return 0

        if args.action == "set-url":
            set_patch_url(args.url)
            print(f"OPI_PATCH_URL set to: {args.url}")
            return 0

        if args.action == "set-path":
            set_patch_path(args.path)
            print(f"OPI_PATCH_PATH set to: {args.path}")
            return 0

    except ConfigError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code

    return 1


def handle_subagent(args: argparse.Namespace) -> int:
    """Handle subagent subcommands."""
    import asyncio
    from opi_agent.subagent import get_manager

    manager = get_manager()

    try:
        if args.action == "list":
            agents = manager.list_agents()
            if not agents:
                print("No subagents registered.")
                return 0

            for info in agents:
                elapsed = f"{info.elapsed:.1f}s"
                status_icon = {
                    "pending": "⏳",
                    "running": "🟢",
                    "completed": "✅",
                    "failed": "❌",
                    "killed": "⛔",
                }.get(info.state.value, "?")

                line = (
                    f"  {status_icon} {info.id}  {info.name}  "
                    f"state={info.state.value}  elapsed={elapsed}"
                )
                if info.error:
                    line += f"  error={info.error}"
                print(line)
            return 0

        if args.action == "status":
            summary = manager.summary()
            enabled_str = "yes" if summary["enabled"] else "no"
            print(f"Subagents enabled: {enabled_str}")
            print(f"Max concurrent:   {summary['max_count']}")
            print(f"Active:           {summary['active']}")
            print(f"Completed:        {summary['completed']}")
            print(f"Failed:           {summary['failed']}")
            print(f"Killed:           {summary['killed']}")
            print(f"Total registered: {summary['total']}")
            return 0

        if args.action == "kill":
            async def _kill():
                return await manager.kill(args.agent_id)
            info = asyncio.run(_kill())
            print(f"Killed subagent {info.id} ({info.name})")
            return 0

        if args.action == "kill-all":
            async def _kill_all():
                return await manager.kill_all()
            count = asyncio.run(_kill_all())
            print(f"Killed {count} subagent(s)")
            return 0

        if args.action == "cleanup":
            count = manager.cleanup_finished()
            print(f"Cleaned up {count} finished subagent(s)")
            return 0

    except SubagentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code
    except OpiAgentError as e:
        print(f"error: {e.message}", file=sys.stderr)
        return e.code

    return 1


def main() -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    # Setup basic logging for CLI
    setup_logging()

    # Route commands
    if args.command == "version":
        print_version()
        return 0

    if args.command == "update":
        return handle_update(args)

    if args.command == "service":
        return handle_service(args)

    if args.command == "config":
        return handle_config(args)

    if args.command == "paths":
        return handle_paths(args)

    if args.command == "exec":
        return handle_exec(args)

    if args.command == "daemon":
        return daemon_loop()

    if args.command == "patch":
        return handle_patch(args)

    if args.command == "subagent":
        return handle_subagent(args)

    if args.command == "chat":
        return chat_mode()

    if args.command == "telegram":
        return run_telegram_bot()

    if args.command == "install":
        from opi_agent.service import APP_NAME, TELEGRAM_APP_NAME

        services = []
        if args.service == "both":
            services = [APP_NAME, TELEGRAM_APP_NAME]
        else:
            services = [TELEGRAM_APP_NAME if args.service == "opi-agent-telegram" else APP_NAME]

        try:
            for svc in services:
                service_install(svc)
            return 0
        except ServiceError as e:
            print(f"error: {e.message}", file=sys.stderr)
            return e.code

    if args.command == "uninstall":
        from opi_agent.service import APP_NAME, TELEGRAM_APP_NAME

        services = []
        if args.service == "both":
            services = [APP_NAME, TELEGRAM_APP_NAME]
        else:
            services = [TELEGRAM_APP_NAME if args.service == "opi-agent-telegram" else APP_NAME]

        try:
            for svc in services:
                service_uninstall(svc)
            return 0
        except ServiceError as e:
            print(f"error: {e.message}", file=sys.stderr)
            return e.code

    return 1


if __name__ == "__main__":
    sys.exit(main())
