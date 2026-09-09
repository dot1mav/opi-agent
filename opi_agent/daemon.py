"""Daemon loop for opi-agent."""

import os
import signal
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import systemd.daemon
else:
    try:
        import systemd.daemon
    except ImportError:
        systemd = None  # type: ignore

from opi_agent.config import BASE_DIR, get_env_int
from opi_agent.log import get_logger, setup_logging

logger = get_logger(__name__)

RUN_DIR = BASE_DIR / "run"
PID_FILE = RUN_DIR / "daemon.pid"


class Daemon:
    """Main daemon class."""

    def __init__(self) -> None:
        self.running = False
        self.heartbeat_interval = get_env_int("OPI_HEARTBEAT_SECONDS", 60)

    def setup_signals(self) -> None:
        """Set up signal handlers."""
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._handle_reload)

    def _handle_signal(self, signum: int, frame: Any) -> None:
        """Handle termination signals."""
        logger.info("Received signal %d, shutting down", signum)
        self.running = False

    def _handle_reload(self, signum: int, frame: Any) -> None:
        """Handle reload signal."""
        logger.info("Received SIGHUP, reloading configuration")
        # Reload configuration here if needed

    def write_pid(self) -> None:
        """Write PID file."""
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))

    def remove_pid(self) -> None:
        """Remove PID file."""
        if PID_FILE.exists():
            PID_FILE.unlink()

    def check_stale_pid(self) -> bool:
        """Check for stale PID file.

        Returns:
            True if stale PID found and removed
        """
        if not PID_FILE.exists():
            return False

        try:
            pid = int(PID_FILE.read_text().strip())
            # Check if process exists
            import os

            os.kill(pid, 0)
            # Process exists, not stale
            return False
        except (ValueError, OSError, ProcessLookupError):
            # Stale PID file
            logger.warning("Removing stale PID file: %s", PID_FILE)
            PID_FILE.unlink()
            return True

    def run(self) -> int:
        """Run the daemon loop.

        Returns:
            Exit code
        """
        # Check for stale PID
        self.check_stale_pid()

        # Write PID
        self.write_pid()

        # Setup signals
        self.setup_signals()

        # Notify systemd we're ready
        if systemd is not None:
            try:
                systemd.daemon.notify("READY=1")
            except Exception as e:
                logger.debug("Systemd notify failed: %s", e)

        logger.info("%s daemon started in %s", "opi-agent", BASE_DIR)
        self.running = True

        last_heartbeat = time.time()

        while self.running:
            now = time.time()

            # Heartbeat
            if now - last_heartbeat >= self.heartbeat_interval:
                logger.debug("Heartbeat")
                last_heartbeat = now

                # Notify systemd watchdog
                if systemd is not None:
                    try:
                        systemd.daemon.notify("WATCHDOG=1")
                    except Exception as e:
                        logger.debug("Systemd watchdog notify failed: %s", e)

            time.sleep(1)

        # Cleanup
        self.remove_pid()
        logger.info("Daemon stopped")
        return 0


def daemon_loop() -> int:
    """Main daemon entrypoint.

    Returns:
        Exit code
    """
    # Setup logging
    log_file = BASE_DIR / "logs" / "agent.log"
    setup_logging(log_file=log_file)

    daemon = Daemon()
    return daemon.run()


def chat_mode() -> int:
    """Interactive chat mode."""
    from opi_agent.config import get_env

    print("opi-agent interactive chat mode.")
    print("Type 'help' for commands, 'exit' to quit.\n")

    while True:
        try:
            text = input("opi> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            break
        if text.lower() == "help":
            print("Commands: help, status, exec <cmd>, config, exit")
            continue
        if text.lower() == "status":
            from opi_agent.update import git_describe, in_git_repo

            version = git_describe()
            repo_ok = "yes" if in_git_repo() else "no"
            print(f"Version: {version}, Git repo: {repo_ok}")
            continue
        if text.lower() == "config":
            from opi_agent.config import config_show

            data = config_show(raw=False)
            for k, v in sorted(data.items()):
                print(f"  {k}={v}")
            continue
        if text.lower().startswith("exec "):
            from opi_agent.exec import run_exec

            cmd_str = text[5:].strip()
            import shlex

            try:
                parts = shlex.split(cmd_str)
            except ValueError as e:
                print(f"Parse error: {e}")
                continue
            try:
                code = run_exec(parts, confirm=True)
                print(f"Exit code: {code}")
            except Exception as e:
                print(f"Error: {e}")
            continue

        print(f"Unknown command: {text}. Type 'help' for commands.")

    return 0


def telegram_mode() -> int:
    """Telegram mode — delegates to the full implementation in telegram.py."""
    from opi_agent.telegram import run_telegram_bot

    return run_telegram_bot()
