"""Pytest configuration and fixtures."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_env(monkeypatch):
    """Isolate environment variables for each test."""
    # Save original env
    original_env = dict(os.environ)

    # Clear test-related env vars
    for key in list(os.environ.keys()):
        if key.startswith("OPI_"):
            monkeypatch.delenv(key, raising=False)

    yield

    # Restore
    for key in list(os.environ.keys()):
        if key.startswith("OPI_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in original_env.items():
        if key.startswith("OPI_"):
            monkeypatch.setenv(key, value)


@pytest.fixture
def temp_env_file(tmp_path):
    """Create a temporary .env file and set OPI_TEST_ENV_FILE."""
    env_file = tmp_path / ".env"
    env_file.write_text("")
    os.environ["OPI_TEST_ENV_FILE"] = str(env_file)
    yield env_file
    del os.environ["OPI_TEST_ENV_FILE"]


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    import subprocess

    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo_path, capture_output=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, capture_output=True)

    # Create initial commit
    (repo_path / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, capture_output=True)

    return repo_path
