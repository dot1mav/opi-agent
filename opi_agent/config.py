"""Configuration management for opi-agent."""

import os
import tempfile
from pathlib import Path
from typing import Any

from opi_agent.exceptions import ConfigError
from opi_agent.log import get_logger
from opi_agent.schemas import get_schema, validate_value

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
VENV_DIR = BASE_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "bin" / "python"
WORKSPACE_DIR = BASE_DIR / "workspace"
LOGS_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / "run"
SENSITIVE_KEYS = {"token", "secret", "password", "api"}


def is_sensitive_key(key: str) -> bool:
    """Check if a configuration key is sensitive.

    A key is sensitive if any underscore-separated part matches
    a known sensitive keyword exactly.

    Args:
        key: Configuration key to check

    Returns:
        True if sensitive, False otherwise
    """
    parts = key.lower().split("_")
    return any(part in SENSITIVE_KEYS for part in parts)


def get_env_path() -> Path:
    """Get the .env file path, respecting OPI_TEST_ENV_FILE for testing."""
    test_env = os.environ.get("OPI_TEST_ENV_FILE")
    if test_env:
        return Path(test_env)
    return BASE_DIR / ".env"


def get_env_file_path(path: Path | None = None) -> Path:
    """Get the .env file path, with optional override."""
    if path is not None:
        return path
    return get_env_path()


def is_true(value: Any) -> bool:
    """Check if a value represents true."""
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def read_env_file(path: Path | None = None) -> dict[str, str]:
    """Read .env file into a dictionary.

    Args:
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)

    Returns:
        Dictionary of key-value pairs
    """
    path = get_env_file_path(path)
    data: dict[str, str] = {}
    if not path.exists():
        return data

    try:
        content = path.read_text(encoding="utf-8")
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in raw:
                continue
            key, value = raw.split("=", 1)
            data[key.strip()] = value.strip()
    except OSError as e:
        raise ConfigError(f"Failed to read {path}: {e}") from e

    return data


def write_env_file(data: dict[str, str], path: Path | None = None) -> None:
    """Write dictionary to .env file atomically.

    Args:
        data: Configuration dictionary
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)
    """
    path = get_env_file_path(path)
    lines = [f"{k}={v}" for k, v in sorted(data.items())]
    content = "\n".join(lines) + "\n"

    try:
        # Atomic write using temp file + rename
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            delete=False,
            prefix=".env.tmp.",
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        # Preserve permissions if file exists
        if path.exists():
            tmp_path.chmod(path.stat().st_mode)
        else:
            tmp_path.chmod(0o600)

        tmp_path.replace(path)
    except OSError as e:
        raise ConfigError(f"Failed to write {path}: {e}") from e


def update_env_line(key: str, value: str | None, path: Path | None = None) -> None:
    """Update a single line in .env file, preserving comments and formatting.

    Args:
        key: Configuration key
        value: New value (None to remove)
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)
    """
    path = get_env_file_path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    found = False

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            out.append(raw)
            continue

        existing_key, _, _ = raw.partition("=")
        if existing_key.strip() == key:
            found = True
            if value is not None:
                out.append(f"{key}={value}")
        else:
            out.append(raw)

    if value is not None and not found:
        out.append(f"{key}={value}")

    write_env_file(
        dict(
            line.split("=", 1) for line in out if "=" in line and not line.strip().startswith("#")
        ),
        path,
    )


def mask_value(key: str, value: str) -> str:
    """Mask sensitive values for display.

    Args:
        key: Configuration key
        value: Configuration value

    Returns:
        Masked value if sensitive, original otherwise
    """
    return "***" if is_sensitive_key(key) else value


def config_show(raw: bool = False, path: Path | None = None) -> dict[str, str]:
    """Get all configuration values.

    Args:
        raw: Show unmasked values
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)

    Returns:
        Dictionary of configuration values
    """
    path = get_env_file_path(path)
    data = read_env_file(path)
    if not raw:
        return {k: mask_value(k, v) for k, v in data.items()}
    return data


def config_get(key: str, path: Path | None = None, default: str | None = None) -> str | None:
    """Get a single configuration value.

    Args:
        key: Configuration key
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)
        default: Default value if key not found

    Returns:
        Configuration value or default
    """
    path = get_env_file_path(path)
    data = read_env_file(path)
    return data.get(key, default)


def config_set(key: str, value: str, path: Path | None = None, validate: bool = True) -> None:
    """Set a configuration value.

    Args:
        key: Configuration key
        value: Configuration value
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)
        validate: Whether to validate against schema

    Raises:
        ConfigError: If validation fails
    """
    if validate:
        schema = get_schema(key)
        if schema:
            is_valid, error = validate_value(schema, value)
            if not is_valid:
                raise ConfigError(f"Invalid value for {key}: {error}")

    path = get_env_file_path(path)
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    data = read_env_file(path)
    data[key] = value
    write_env_file(data, path)

    # Ensure secure permissions
    path.chmod(0o600)
    logger.info("Configuration updated: %s", key)


def config_unset(key: str, path: Path | None = None) -> bool:
    """Remove a configuration key.

    Args:
        key: Configuration key
        path: Path to .env file (uses OPI_TEST_ENV_FILE or default if not provided)

    Returns:
        True if key was removed, False if not found
    """
    path = get_env_file_path(path)
    data = read_env_file(path)
    if key in data:
        del data[key]
        write_env_file(data, path)
        logger.info("Configuration removed: %s", key)
        return True
    return False


def get_env(key: str, default: str | None = None) -> str | None:
    """Get configuration value from environment or .env file.

    Priority: OS environment > .env file > default

    Args:
        key: Configuration key
        default: Default value if not found

    Returns:
        Configuration value or default
    """
    # Check OS environment first
    if key in os.environ:
        return os.environ[key]

    # Check .env file
    data = read_env_file()
    if key in data:
        return data[key]

    return default


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean configuration value.

    Args:
        key: Configuration key
        default: Default value

    Returns:
        Boolean value
    """
    value = get_env(key)
    if value is None:
        return default
    return is_true(value)


def get_env_int(key: str, default: int = 0) -> int:
    """Get integer configuration value.

    Args:
        key: Configuration key
        default: Default value

    Returns:
        Integer value
    """
    value = get_env(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


# Patch/Extra access functions
def get_patch_url() -> str | None:
    """Get patch base URL from configuration.

    Returns:
        Patch URL or None if not configured
    """
    return get_env("OPI_PATCH_URL")


def get_patch_path() -> Path | None:
    """Get patch local path from configuration.

    Returns:
        Patch path or None if not configured
    """
    path_str = get_env("OPI_PATCH_PATH")
    if path_str:
        return Path(path_str).expanduser().resolve()
    return None


def set_patch_url(url: str) -> None:
    """Set patch base URL.

    Args:
        url: Patch base URL
    """
    config_set("OPI_PATCH_URL", url)


def set_patch_path(path: str) -> None:
    """Set patch local path.

    Args:
        path: Local patch path
    """
    config_set("OPI_PATCH_PATH", path)


def list_patches(patch_path: Path | None = None) -> list[Path]:
    """List available patch files.

    Args:
        patch_path: Override patch path

    Returns:
        List of patch file paths
    """
    path = patch_path or get_patch_path()
    if not path or not path.exists():
        return []

    return sorted(path.glob("*.patch")) + sorted(path.glob("*.diff"))


def apply_patch(patch_file: Path, target_dir: Path | None = None, dry_run: bool = False) -> bool:
    """Apply a patch file.

    Args:
        patch_file: Path to patch file
        target_dir: Target directory (default: BASE_DIR)
        dry_run: If True, only check if patch applies cleanly

    Returns:
        True if successful

    Raises:
        ConfigError: If patch command fails
    """
    import subprocess

    target = target_dir or Path(__file__).resolve().parent.parent

    cmd = ["patch", "-p1"]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend(["-i", str(patch_file)])

    logger.info("Applying patch: %s (dry_run=%s)", patch_file.name, dry_run)

    try:
        result = subprocess.run(
            cmd,
            cwd=str(target),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ConfigError(f"Patch failed: {result.stderr}")
        logger.info("Patch applied successfully: %s", patch_file.name)
        return True
    except FileNotFoundError as e:
        raise ConfigError("patch command not found. Install patch utility.") from e
    except OSError as e:
        raise ConfigError(f"Failed to run patch: {e}") from e
