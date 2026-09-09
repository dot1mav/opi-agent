"""Tests for patch management."""

from pathlib import Path

import pytest

from opi_agent.config import (
    apply_patch,
    get_patch_path,
    get_patch_url,
    list_patches,
    set_patch_path,
    set_patch_url,
)
from opi_agent.exceptions import ConfigError


class TestPatchConfig:
    """Tests for patch configuration."""

    def test_get_set_patch_url(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_patch_url() is None
            set_patch_url("https://example.com/patches")
            assert get_patch_url() == "https://example.com/patches"
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_get_set_patch_path(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            assert get_patch_path() is None
            set_patch_path("/opt/patches")
            path = get_patch_path()
            assert path == Path("/opt/patches").resolve()
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestListPatches:
    """Tests for listing patches."""

    def test_no_patch_path(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            patches = list_patches()
            assert patches == []
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_list_patches(self, tmp_path: Path):
        patch_dir = tmp_path / "patches"
        patch_dir.mkdir()
        (patch_dir / "fix1.patch").write_text("diff --git a/file b/file")
        (patch_dir / "fix2.diff").write_text("diff --git a/file b/file")
        (patch_dir / "readme.txt").write_text("not a patch")

        env_file = tmp_path / ".env"
        env_file.write_text(f"OPI_PATCH_PATH={patch_dir}\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            patches = list_patches()
            assert len(patches) == 2
            names = {p.name for p in patches}
            assert names == {"fix1.patch", "fix2.diff"}
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]


class TestApplyPatch:
    """Tests for applying patches."""

    def test_patch_not_found(self, tmp_path: Path):
        env_file = tmp_path / ".env"
        env_file.write_text("OPI_PATCH_PATH=/nonexistent\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            with pytest.raises(ConfigError, match="Patch failed"):
                apply_patch(Path("missing.patch"))
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_patch_file_not_found(self, tmp_path: Path):
        patch_dir = tmp_path / "patches"
        patch_dir.mkdir()
        env_file = tmp_path / ".env"
        env_file.write_text(f"OPI_PATCH_PATH={patch_dir}\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            with pytest.raises(ConfigError, match="Patch failed"):
                apply_patch(Path("missing.patch"))
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]

    def test_apply_patch_dry_run(self, tmp_path: Path):
        # Create a simple test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("original content\n")

        # Create a patch using diff with labels (works on Windows)
        patch_dir = tmp_path / "patches"
        patch_dir.mkdir()
        patch_file = patch_dir / "test.patch"

        # Create new version of the file
        new_file = tmp_path / "test_new.txt"
        new_file.write_text("patched content\n")

        # Generate patch using diff with labels
        import subprocess

        diff_cmd = [
            "diff",
            "-u",
            "--label=a/test.txt",
            "--label=b/test.txt",
            str(test_file),
            str(new_file),
        ]
        result = subprocess.run(
            diff_cmd,
            capture_output=True,
            text=True,
        )
        patch_file.write_text(result.stdout)

        env_file = tmp_path / ".env"
        env_file.write_text(f"OPI_PATCH_PATH={patch_dir}\n")
        import os

        os.environ["OPI_TEST_ENV_FILE"] = str(env_file)

        try:
            # This should work in dry-run mode
            apply_patch(patch_file, target_dir=tmp_path, dry_run=True)
        finally:
            del os.environ["OPI_TEST_ENV_FILE"]
