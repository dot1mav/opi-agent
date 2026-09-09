"""Update management for opi-agent."""

import subprocess
import sys

from opi_agent.config import BASE_DIR, get_env
from opi_agent.exceptions import UpdateError
from opi_agent.log import get_logger

logger = get_logger(__name__)

VERSION_FALLBACK = "0.1.0"


def in_git_repo() -> bool:
    """Check if we're in a git repository."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_describe() -> str:
    """Get git describe output for version."""
    if not in_git_repo():
        return VERSION_FALLBACK

    result = subprocess.run(
        ["git", "describe", "--tags", "--dirty", "--always"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return VERSION_FALLBACK


def print_version() -> None:
    """Print version string."""
    print(git_describe())


def git(*args: str, capture: bool = True, check: bool = False) -> subprocess.CompletedProcess:
    """Run git command."""
    return subprocess.run(
        ["git", *args],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=capture,
        check=check,
    )


def update_status() -> int:
    """Show git repository status."""
    if not in_git_repo():
        print("Not a git repository.")
        return 1

    git("fetch", "--all", "--prune", "--tags")
    branch = git("branch", "--show-current", capture=True).stdout.strip() or "(detached)"
    status = git("status", "--short", "--branch", capture=True).stdout.strip()
    print(status or f"On branch {branch}\nworking tree clean")

    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if upstream_result.returncode != 0:
        print("No upstream configured.")
        return 0

    counts = git(
        "rev-list",
        "--left-right",
        "--count",
        f"HEAD...{upstream_result.stdout.strip()}",
        capture=True,
    )
    if counts.returncode == 0:
        behind, ahead = counts.stdout.strip().split()
        print(f"ahead={ahead} behind={behind}")
    return 0


def update_check() -> int:
    """Check for available updates."""
    if not in_git_repo():
        print("Not a git repository.")
        return 1

    local_changes = git("status", "--porcelain", capture=True).stdout.strip()
    if local_changes:
        print("Local changes detected:")
        print(local_changes)
        return 2

    git("fetch", "--all", "--prune", "--tags")
    print("Repository is clean and remote refs were refreshed.")

    # Check if behind
    upstream_result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if upstream_result.returncode == 0:
        counts = git(
            "rev-list",
            "--left-right",
            "--count",
            f"HEAD...{upstream_result.stdout.strip()}",
            capture=True,
        )
        if counts.returncode == 0:
            behind, ahead = counts.stdout.strip().split()
            if int(behind) > 0:
                print(f"Updates available: {behind} commits behind")
                return 0
            else:
                print("Already up to date")
    return 0


def update_apply(confirm: bool) -> int:
    """Apply updates from remote.

    Args:
        confirm: Must be True to apply

    Returns:
        Exit code
    """
    if not confirm:
        raise UpdateError("Use --confirm to apply updates")

    if not in_git_repo():
        raise UpdateError("Not a git repository.")

    if git("status", "--porcelain", capture=True).stdout.strip():
        raise UpdateError("Working tree is dirty; commit/stash changes first")

    git("fetch", "--all", "--prune", "--tags")

    result = git("pull", "--ff-only", capture=False)
    if result.returncode != 0:
        return result.returncode

    # Verify syntax after pull
    compile_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(BASE_DIR / "opi_agent.py")],
        capture_output=True,
    )
    if compile_result.returncode != 0:
        raise UpdateError("New code failed syntax check after pull")

    # Reinstall dependencies if requirements.txt changed
    req_file = BASE_DIR / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            check=False,
        )

    print("Update applied successfully.")
    return 0


def update_rollback(confirm: bool) -> int:
    """Rollback to previous commit.

    Args:
        confirm: Must be True to rollback

    Returns:
        Exit code
    """
    if not confirm:
        raise UpdateError("Use --confirm to rollback")

    if not in_git_repo():
        raise UpdateError("Not a git repository.")

    # Show reflog for user to choose
    reflog = subprocess.run(
        ["git", "reflog", "--oneline", "-10"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    print("Recent commits:")
    print(reflog.stdout)

    # Get previous commit (HEAD@{1})
    result = subprocess.run(
        ["git", "rev-parse", "HEAD@{1}"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise UpdateError("No previous commit found in reflog")

    prev_sha = result.stdout.strip()
    print(f"Rolling back to: {prev_sha}")

    # Hard reset
    reset_result = subprocess.run(
        ["git", "reset", "--hard", prev_sha],
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
    )
    if reset_result.returncode != 0:
        raise UpdateError(f"Reset failed: {reset_result.stderr}")

    # Reinstall dependencies
    req_file = BASE_DIR / "requirements.txt"
    if req_file.exists():
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(req_file)],
            check=False,
        )

    print("Rollback completed. Restart service to apply changes.")
    return 0


def get_update_branch() -> str:
    """Get configured update branch."""
    branch = get_env("OPI_UPDATE_BRANCH")
    return branch if branch is not None else "main"


def validate_origin() -> bool:
    """Validate origin URL matches configured value."""
    expected = get_env("OPI_ORIGIN_URL")
    if not expected:
        return True

    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=str(BASE_DIR),
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        return False

    actual = result.stdout.strip()
    return actual == expected
