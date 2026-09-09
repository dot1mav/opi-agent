"""Tests for exec module."""

from opi_agent.config import config_set, config_unset
from opi_agent.exec import (
    FORBIDDEN_CHARS,
    get_allowed_commands,
    get_allowed_paths,
    validate_command,
)


class TestValidateCommand:
    """Tests for command validation."""

    def setup_method(self):
        """Reset config before each test."""
        for key in ["OPI_ALLOWED_COMMANDS", "OPI_ALLOWED_PATHS", "OPI_SHELL_ENABLED", "ALLOW_EXEC"]:
            config_unset(key)

    def test_empty_command(self):
        valid, error = validate_command([])
        assert not valid
        assert "No command provided" in error

    def test_allowed_commands_list(self):
        config_set("OPI_ALLOWED_COMMANDS", "echo,ls,cat")
        valid, error = validate_command(["echo", "hello"])
        assert valid

        valid, error = validate_command(["rm", "file"])
        assert not valid
        assert "not in allowed list" in error

    def test_forbidden_metacharacters(self):
        for char in FORBIDDEN_CHARS:
            valid, error = validate_command(["echo", f"hello{char}world"])
            assert not valid, f"Character {char} should be forbidden"
            assert "Forbidden character" in error

    def test_forbidden_patterns(self):
        # Map each regex pattern to a test string that should match it
        pattern_tests = {
            r"\|\|": "test||test",
            r"&&": "test&&test",
            r";;": "test;;test",
            r"\$\(": "test$(test",
            r">>": "test>>test",
            r"<<": "test<<test",
            r"2>": "test2>test",
            r"2>>": "test2>>test",
            r"&>": "test&>test",
            r"&>>": "test&>>test",
        }
        for pattern, test_str in pattern_tests.items():
            valid, error = validate_command(["echo", test_str])
            assert not valid, f"Pattern {pattern} should be forbidden (test: {test_str})"
            msg = f"Expected 'Forbidden pattern' in error for {pattern}: {error}"
            assert "Forbidden pattern" in error, msg

    def test_forbidden_commands(self):
        forbidden = ["sudo", "su", "doas", "pkexec", "systemctl", "service"]
        for cmd in forbidden:
            valid, error = validate_command([cmd, "arg"])
            assert not valid, f"Command {cmd} should be forbidden"
            assert "forbidden" in error.lower()

    def test_forbidden_shells(self):
        shells = ["sh", "bash", "zsh", "fish", "csh", "tcsh", "ksh", "dash"]
        for shell in shells:
            valid, error = validate_command([shell, "-c", "echo hi"])
            assert not valid, f"Shell {shell} should be forbidden"
            assert "forbidden" in error.lower()

    def test_allowed_paths(self):
        config_set("OPI_ALLOWED_PATHS", "/tmp:/home/user")
        valid, error = validate_command(["cat", "/tmp/file.txt"])
        assert valid

        valid, error = validate_command(["cat", "/etc/passwd"])
        assert not valid
        assert "not in allowed paths" in error

    def test_relative_paths_allowed(self):
        config_set("OPI_ALLOWED_PATHS", "/workspace")
        valid, error = validate_command(["cat", "./file.txt"])
        assert valid  # Relative paths not checked if they don't start with /

    def test_path_traversal_blocked(self):
        config_set("OPI_ALLOWED_PATHS", "/workspace")
        valid, error = validate_command(["cat", "../etc/passwd"])
        assert not valid
        assert "not in allowed paths" in error


class TestGetAllowedCommands:
    """Tests for allowed commands parsing."""

    def test_empty(self):
        config_unset("OPI_ALLOWED_COMMANDS")
        assert get_allowed_commands() == set()

    def test_parsing(self):
        config_set("OPI_ALLOWED_COMMANDS", "echo, ls , cat ")
        commands = get_allowed_commands()
        assert commands == {"echo", "ls", "cat"}


class TestGetAllowedPaths:
    """Tests for allowed paths parsing."""

    def test_empty(self):
        config_unset("OPI_ALLOWED_PATHS")
        assert get_allowed_paths() == []

    def test_parsing(self):
        config_set("OPI_ALLOWED_PATHS", "/tmp : /home/user : /opt")
        paths = get_allowed_paths()
        assert len(paths) == 3
        assert all(p.is_absolute() for p in paths)
