"""Configuration schemas and validation for opi-agent."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigSchema:
    """Schema definition for a configuration key."""

    key: str
    description: str
    default: Any = None
    required: bool = False
    sensitive: bool = False
    validator: str | None = None  # Name of validator function
    choices: list[Any] | None = None


# Known configuration keys with schemas
CONFIG_SCHEMAS: dict[str, ConfigSchema] = {
    "OPI_BASE_DIR": ConfigSchema(
        key="OPI_BASE_DIR",
        description="Base directory for opi-agent",
        default="/opt/opi",
        required=False,
    ),
    "OPI_SERVICE_NAME": ConfigSchema(
        key="OPI_SERVICE_NAME",
        description="Systemd service name",
        default="opi-agent",
        required=False,
    ),
    "OPI_UPDATE_BRANCH": ConfigSchema(
        key="OPI_UPDATE_BRANCH",
        description="Branch allowed for self-update",
        default="main",
        required=False,
    ),
    "OPI_ORIGIN_URL": ConfigSchema(
        key="OPI_ORIGIN_URL",
        description="Expected origin URL for update validation",
        default=None,
        required=False,
    ),
    "OPI_SHELL_ENABLED": ConfigSchema(
        key="OPI_SHELL_ENABLED",
        description="Enable shell command execution (requires --confirm)",
        default="false",
        required=False,
        choices=["true", "false", "1", "0", "yes", "no", "on", "off", "y", "n"],
    ),
    "OPI_HEARTBEAT_SECONDS": ConfigSchema(
        key="OPI_HEARTBEAT_SECONDS",
        description="Daemon heartbeat interval in seconds",
        default="60",
        required=False,
        validator="positive_int",
    ),
    "OPI_API_KEY": ConfigSchema(
        key="OPI_API_KEY",
        description="API key for external services",
        default=None,
        required=False,
        sensitive=True,
    ),
    "OPI_ALLOWED_COMMANDS": ConfigSchema(
        key="OPI_ALLOWED_COMMANDS",
        description="Comma-separated list of allowed executable commands",
        default="",
        required=False,
    ),
    "OPI_ALLOWED_PATHS": ConfigSchema(
        key="OPI_ALLOWED_PATHS",
        description="Colon-separated list of allowed paths for exec arguments",
        default="",
        required=False,
    ),
    "OPI_EXEC_TIMEOUT": ConfigSchema(
        key="OPI_EXEC_TIMEOUT",
        description="Default timeout for exec commands in seconds",
        default="30",
        required=False,
        validator="positive_int",
    ),
    "OPI_EXTRA_GROUPS": ConfigSchema(
        key="OPI_EXTRA_GROUPS",
        description="Additional groups for service user (comma-separated)",
        default="",
        required=False,
    ),
    "OPI_GRANT_ACL": ConfigSchema(
        key="OPI_GRANT_ACL",
        description="Grant ACL access to allowed paths",
        default="false",
        required=False,
        choices=["true", "false", "1", "0", "yes", "no", "on", "off", "y", "n"],
    ),
    "OPI_PATCH_URL": ConfigSchema(
        key="OPI_PATCH_URL",
        description="Base URL for patch files",
        default=None,
        required=False,
    ),
    "OPI_PATCH_PATH": ConfigSchema(
        key="OPI_PATCH_PATH",
        description="Local path for patch files",
        default=None,
        required=False,
    ),
    "TELEGRAM_BOT_TOKEN": ConfigSchema(
        key="TELEGRAM_BOT_TOKEN",
        description="Telegram bot token from @BotFather",
        default=None,
        required=False,
        sensitive=True,
    ),
    "TELEGRAM_ALLOWED_USERS": ConfigSchema(
        key="TELEGRAM_ALLOWED_USERS",
        description="Comma-separated list of allowed Telegram user IDs",
        default="",
        required=False,
    ),
    "TELEGRAM_WEBHOOK_URL": ConfigSchema(
        key="TELEGRAM_WEBHOOK_URL",
        description="Public HTTPS URL for webhook mode (empty = long polling)",
        default="",
        required=False,
    ),
    "TELEGRAM_WEBHOOK_PORT": ConfigSchema(
        key="TELEGRAM_WEBHOOK_PORT",
        description="Local port for webhook server",
        default="8443",
        required=False,
        validator="positive_int",
    ),
    "TELEGRAM_WEBHOOK_CERT": ConfigSchema(
        key="TELEGRAM_WEBHOOK_CERT",
        description="Path to SSL certificate for webhook",
        default=None,
        required=False,
    ),
    "TELEGRAM_WEBHOOK_KEY": ConfigSchema(
        key="TELEGRAM_WEBHOOK_KEY",
        description="Path to SSL private key for webhook",
        default=None,
        required=False,
        sensitive=True,
    ),
    "TELEGRAM_PROXY": ConfigSchema(
        key="TELEGRAM_PROXY",
        description="SOCKS5h proxy URL (socks5h://[user:pass@]host:port)",
        default="",
        required=False,
    ),
    "TELEGRAM_PARSE_MODE": ConfigSchema(
        key="TELEGRAM_PARSE_MODE",
        description="Default message parse mode",
        default="HTML",
        required=False,
        choices=["HTML", "Markdown", "MarkdownV2", "None"],
    ),
    "TELEGRAM_MAX_FILE_SIZE_MB": ConfigSchema(
        key="TELEGRAM_MAX_FILE_SIZE_MB",
        description="Maximum file size for uploads in MB",
        default="50",
        required=False,
        validator="positive_int",
    ),
    "OPI_SUBAGENT_ENABLED": ConfigSchema(
        key="OPI_SUBAGENT_ENABLED",
        description="Enable subagent spawning",
        default="false",
        required=False,
        choices=["true", "false", "1", "0", "yes", "no", "on", "off", "y", "n"],
    ),
    "OPI_SUBAGENT_MAX_COUNT": ConfigSchema(
        key="OPI_SUBAGENT_MAX_COUNT",
        description="Maximum number of concurrent subagents",
        default="3",
        required=False,
        validator="positive_int",
    ),
    "OPI_SUBAGENT_TIMEOUT": ConfigSchema(
        key="OPI_SUBAGENT_TIMEOUT",
        description="Default timeout for subagent tasks in seconds",
        default="120",
        required=False,
        validator="positive_int",
    ),
}

# Validators
VALIDATORS = {
    "positive_int": lambda v: int(v) > 0,
    "bool": lambda v: (
        str(v).strip().lower() in {"1", "true", "yes", "on", "y", "0", "false", "no", "off", "n"}
    ),
}


def validate_value(schema: ConfigSchema, value: str) -> tuple[bool, str | None]:
    """Validate a configuration value against its schema.

    Args:
        schema: ConfigSchema for the key
        value: Value to validate

    Returns:
        Tuple of (is_valid, error_message)
    """

    if schema.choices is not None and value not in schema.choices:
        choices_str = ", ".join(str(c) for c in schema.choices)
        return False, f"Value must be one of: {choices_str}"

    if schema.validator and schema.validator in VALIDATORS:
        try:
            if not VALIDATORS[schema.validator](value):
                return False, f"Validation failed for {schema.validator}"
        except (ValueError, TypeError) as e:
            return False, f"Invalid value: {e}"

    return True, None


def get_schema(key: str) -> ConfigSchema | None:
    """Get schema for a configuration key.

    Args:
        key: Configuration key

    Returns:
        ConfigSchema if known, None otherwise
    """
    return CONFIG_SCHEMAS.get(key)


def list_schemas() -> list[ConfigSchema]:
    """List all known configuration schemas.

    Returns:
        List of ConfigSchema objects
    """
    return list(CONFIG_SCHEMAS.values())
