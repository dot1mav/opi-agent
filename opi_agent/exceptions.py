"""Custom exceptions for opi-agent."""


class OpiAgentError(Exception):
    """Base exception for opi-agent errors."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.message = message
        self.code = code


class ConfigError(OpiAgentError):
    """Configuration-related errors."""

    def __init__(self, message: str, code: int = 2):
        super().__init__(message, code)


class ExecError(OpiAgentError):
    """Command execution errors."""

    def __init__(self, message: str, code: int = 3):
        super().__init__(message, code)


class UpdateError(OpiAgentError):
    """Update-related errors."""

    def __init__(self, message: str, code: int = 4):
        super().__init__(message, code)


class ServiceError(OpiAgentError):
    """Service management errors."""

    def __init__(self, message: str, code: int = 5):
        super().__init__(message, code)


class ValidationError(OpiAgentError):
    """Validation errors."""

    def __init__(self, message: str, code: int = 6):
        super().__init__(message, code)


class GitError(OpiAgentError):
    """Git operation errors."""

    def __init__(self, message: str, code: int = 7):
        super().__init__(message, code)


class SubagentError(OpiAgentError):
    """Subagent management errors."""

    def __init__(self, message: str, code: int = 8):
        super().__init__(message, code)
