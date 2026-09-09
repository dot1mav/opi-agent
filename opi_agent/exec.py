"""Secure command execution for opi-agent."""

import os
import shlex
import subprocess
from pathlib import Path

from opi_agent.config import get_env, get_env_bool, get_env_int
from opi_agent.exceptions import ExecError
from opi_agent.log import get_logger

logger = get_logger(__name__)

WORKSPACE_DIR = Path(__file__).resolve().parent.parent / "workspace"

# Shell metacharacters that are forbidden
FORBIDDEN_CHARS = {"|", ">", "<", "&", ";", "$", "`", "(", ")", "{", "}", "*", "?", "[", "]", "~"}
FORBIDDEN_PATTERNS = [
    r"\|\|",
    r"&&",
    r";;",
    r"\$\(",
    r">>",
    r"<<",
    r"2>",
    r"2>>",
    r"&>",
    r"&>>",
]


def exec_allowed() -> bool:
    """Check if command execution is enabled."""
    return get_env_bool("OPI_SHELL_ENABLED", False) or get_env_bool("ALLOW_EXEC", False)


def exec_confirm_required() -> bool:
    """Check if --confirm flag is required."""
    return get_env_bool("EXEC_CONFIRM_REQUIRED", True)


def get_allowed_commands() -> set[str]:
    """Get set of allowed commands from configuration."""
    commands_str = get_env("OPI_ALLOWED_COMMANDS", "")
    if not commands_str:
        return set()
    return {cmd.strip() for cmd in commands_str.split(",") if cmd.strip()}


def get_allowed_paths() -> list[Path]:
    """Get list of allowed paths from configuration."""
    paths_str = get_env("OPI_ALLOWED_PATHS", "")
    if not paths_str:
        return []
    return [Path(p.strip()).expanduser().resolve() for p in paths_str.split(":") if p.strip()]


def get_exec_timeout() -> int:
    """Get exec timeout in seconds."""
    return get_env_int("OPI_EXEC_TIMEOUT", 30)


def validate_command(cmd_parts: list[str]) -> tuple[bool, str | None]:
    """Validate command against security policies.

    Args:
        cmd_parts: Command parts (already split)

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not cmd_parts:
        return False, "No command provided"

    # Check if command is in allowed list
    allowed_commands = get_allowed_commands()
    if allowed_commands:
        cmd_name = Path(cmd_parts[0]).name
        if cmd_name not in allowed_commands:
            return (
                False,
                f"Command '{cmd_name}' not in allowed list: {', '.join(sorted(allowed_commands))}",
            )

    # Check for forbidden patterns first (more specific)
    for part in cmd_parts:
        for pattern in FORBIDDEN_PATTERNS:
            import re

            if re.search(pattern, part):
                return False, f"Forbidden pattern '{pattern}' in argument: {part}"

    # Check for forbidden metacharacters in all args
    for part in cmd_parts:
        for char in FORBIDDEN_CHARS:
            if char in part:
                return False, f"Forbidden character '{char}' in argument: {part}"

    # Check for forbidden commands
    forbidden_commands = {
        "sudo",
        "su",
        "doas",
        "pkexec",
        "runuser",
        "machinectl",
        "systemctl",
        "service",
    }
    cmd_name = Path(cmd_parts[0]).name.lower()
    if cmd_name in forbidden_commands:
        return False, f"Command '{cmd_name}' is forbidden"

    # Check for shell commands
    shell_commands = {"sh", "bash", "zsh", "fish", "csh", "tcsh", "ksh", "dash"}
    if cmd_name in shell_commands:
        return False, f"Shell '{cmd_name}' is forbidden"

    # Validate paths in arguments
    allowed_paths = get_allowed_paths()
    if allowed_paths:
        for part in cmd_parts[1:]:
            # Check if argument looks like an absolute path or contains traversal
            if part.startswith(("/", "~")) or ".." in part:
                try:
                    arg_path = Path(part).expanduser().resolve()
                    # Check if path is within allowed paths
                    path_allowed = False
                    for allowed in allowed_paths:
                        try:
                            arg_path.relative_to(allowed)
                            path_allowed = True
                            break
                        except ValueError:
                            continue
                    if not path_allowed:
                        return False, f"Path not in allowed paths: {part}"
                except (OSError, ValueError):
                    # Not a valid path, skip validation
                    pass

    return True, None


def run_exec(cmd_parts: list[str], confirm: bool = False) -> int:
    """Execute a command with security checks.

    Args:
        cmd_parts: Command parts (argv style)
        confirm: Whether --confirm flag was provided

    Returns:
        Exit code of the command

    Raises:
        ExecError: If execution is not allowed or validation fails
    """
    if not exec_allowed():
        raise ExecError(
            "Command execution is disabled. Set OPI_SHELL_ENABLED=1 or ALLOW_EXEC=1 in .env"
        )

    if exec_confirm_required() and not confirm:
        raise ExecError("Command execution requires --confirm flag")

    # Handle -- separator
    if cmd_parts and cmd_parts[0] == "--":
        cmd_parts = cmd_parts[1:]

    if not cmd_parts:
        raise ExecError("No command provided after -- separator")

    # Validate command
    is_valid, error = validate_command(cmd_parts)
    if not is_valid:
        raise ExecError(f"Command validation failed: {error}")

    # Ensure workspace exists
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Prepare environment
    env = os.environ.copy()
    env["OPI_WORKSPACE"] = str(WORKSPACE_DIR)

    logger.info("Executing command: %s", " ".join(shlex.quote(p) for p in cmd_parts))

    try:
        result = subprocess.run(
            cmd_parts,
            cwd=str(WORKSPACE_DIR),
            env=env,
            timeout=get_exec_timeout(),
            check=False,
        )
        logger.info("Command exited with code: %d", result.returncode)
        return result.returncode
    except subprocess.TimeoutExpired as e:
        raise ExecError(f"Command timed out after {get_exec_timeout()} seconds") from e
    except FileNotFoundError as e:
        raise ExecError(f"Command not found: {cmd_parts[0]}") from e
    except OSError as e:
        raise ExecError(f"Failed to execute command: {e}") from e
