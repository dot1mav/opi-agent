"""Tests for config module."""

import os
from pathlib import Path

import pytest

from opi_agent.config import (
    config_get,
    config_set,
    config_show,
    config_unset,
    get_env,
    get_env_bool,
    get_env_int,
    read_env_file,
    write_env_file,
)


class TestEnvFile:
    """Tests for .env file reading/writing."""

    def test_read_empty_file(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("")
        data = read_env_file(env_file)
        assert data == {}

    def test_read_with_comments(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("# Comment\nKEY=value\n# Another comment\n")
        data = read_env_file(env_file)
        assert data == {"KEY": "value"}

    def test_read_multiline(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY1=value1\nKEY2=value2\n")
        data = read_env_file(env_file)
        assert data == {"KEY1": "value1", "KEY2": "value2"}

    def test_write_and_read(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        data = {"KEY1": "value1", "KEY2": "value2"}
        write_env_file(data, env_file)
        read_data = read_env_file(env_file)
        assert read_data == data

    def test_atomic_write(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        data = {"KEY": "value"}
        write_env_file(data, env_file)
        assert env_file.exists()
        assert env_file.read_text() == "KEY=value\n"


class TestConfigManagement:
    """Tests for config management functions."""

    def test_config_set_get(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            config_set("TEST_KEY", "test_value")
            assert config_get("TEST_KEY") == "test_value"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_config_unset(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            config_set("TEST_KEY", "test_value")
            assert config_unset("TEST_KEY") is True
            assert config_get("TEST_KEY") is None
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_config_show_masks_secrets(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            config_set("API_KEY", "secret123")
            config_set("NORMAL_KEY", "value")
            data = config_show(raw=False)
            assert data["API_KEY"] == "***"
            assert data["NORMAL_KEY"] == "value"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_config_show_raw(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            config_set("API_KEY", "secret123")
            data = config_show(raw=True)
            assert data["API_KEY"] == "secret123"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestGetEnv:
    """Tests for get_env priority resolution."""

    def test_os_env_priority(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=from_file\n")
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)
        os.environ["TEST_KEY"] = "from_os"

        try:
            assert get_env("TEST_KEY") == "from_os"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]
            del os.environ["TEST_KEY"]

    def test_file_fallback(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=from_file\n")
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_env("TEST_KEY") == "from_file"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_default(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_env("NONEXISTENT", "default") == "default"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestGetEnvBool:
    """Tests for boolean parsing."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("1", True),
            ("true", True),
            ("yes", True),
            ("on", True),
            ("y", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("off", False),
            ("n", False),
        ],
    )
    def test_bool_values(self, value: str, expected: bool, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text(f"TEST_KEY={value}\n")
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_env_bool("TEST_KEY") == expected
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestGetEnvInt:
    """Tests for integer parsing."""

    def test_valid_int(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=42\n")
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_env_int("TEST_KEY") == 42
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_invalid_int_returns_default(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("TEST_KEY=not_a_number\n")
        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_env_int("TEST_KEY", 100) == 100
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]
