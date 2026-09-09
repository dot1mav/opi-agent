"""Tests for update module."""

import subprocess
from pathlib import Path
from unittest.mock import patch

from opi_agent.update import (
    get_update_branch,
    git_describe,
    in_git_repo,
    update_status,
    validate_origin,
)


class TestGitRepo:
    """Tests for git repository detection."""

    def test_in_git_repo_true(self, tmp_path: Path):
        # Create a git repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        with patch("opi_agent.update.BASE_DIR", tmp_path):
            assert in_git_repo() is True

    def test_in_git_repo_false(self, tmp_path: Path):
        with patch("opi_agent.update.BASE_DIR", tmp_path):
            assert in_git_repo() is False


class TestGitDescribe:
    """Tests for version string generation."""

    def test_git_describe_in_repo(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "test.txt").write_text("test")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "tag", "v1.0.0"], cwd=tmp_path, capture_output=True)

        with patch("opi_agent.update.BASE_DIR", tmp_path):
            version = git_describe()
            assert version == "v1.0.0"

    def test_git_describe_fallback(self, tmp_path: Path):
        with patch("opi_agent.update.BASE_DIR", tmp_path):
            version = git_describe()
            assert version == "0.1.0"


class TestUpdateStatus:
    """Tests for update status."""

    def test_not_a_repo(self, tmp_path: Path, capsys):
        with patch("opi_agent.update.BASE_DIR", tmp_path):
            result = update_status()
            assert result == 1
            captured = capsys.readouterr()
            assert "Not a git repository" in captured.out


class TestGetUpdateBranch:
    """Tests for update branch configuration."""

    def test_default_branch(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_update_branch() == "main"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_custom_branch(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("OPI_UPDATE_BRANCH=develop\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_update_branch() == "develop"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestValidateOrigin:
    """Tests for origin URL validation."""

    def test_no_origin_configured(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert validate_origin() is True
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_matching_origin(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/repo.git"],
            cwd=tmp_path,
            capture_output=True,
        )

        env_file = tmp_path / ".env"
        env_file.write_text("OPI_ORIGIN_URL=https://github.com/user/repo.git\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            with patch("opi_agent.update.BASE_DIR", tmp_path):
                assert validate_origin() is True
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_mismatched_origin(self, tmp_path: Path):
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True
        )
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/user/repo.git"],
            cwd=tmp_path,
            capture_output=True,
        )

        env_file = tmp_path / ".env"
        env_file.write_text("OPI_ORIGIN_URL=https://github.com/other/repo.git\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            with patch("opi_agent.update.BASE_DIR", tmp_path):
                assert validate_origin() is False
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]
