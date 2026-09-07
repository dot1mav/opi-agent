# opi-agent

`dot1mav/opi-agent` — an agent runtime for Orange Pi single-board computers, intended for
production deployment. This document describes the secure rewrite architecture.

> **Security warning:** this software can execute shell commands on the host when
> explicitly enabled. Read the [Exec security](#exec-security) section before enabling
> anything. Run the service as an unprivileged user and keep `ALLOW_EXEC=0` unless you
> have reviewed the implications.

## Overview

The project is a single Python entrypoint (`opi_agent.py`) managed by a systemd service.
The installer (`install_opi.sh`) sets up an isolated virtualenv, runtime directories,
permissions, and a hardened systemd unit. All state lives inside the project directory.

## Layout

| Path | Purpose |
|---|---|
| `opi_agent.py` | Main CLI / agent entrypoint |
| `install_opi.sh` | Installer (venv, dirs, permissions, systemd unit) |
| `opi-agent.service.template` | Template of the hardened systemd unit |
| `.env` | Local configuration (mode `600`) |
| `workspace/` | Working directory for agent operations and `exec` commands |
| `logs/` | Runtime logs |
| `run/` | Runtime state (pid files, etc.) |
| `requirements.txt` | Python dependencies installed into the venv |
| `.github/workflows/ci-cd.yml` | CI/CD pipeline |
| `.venv/` | Virtualenv created by the installer (never created manually) |

## Installation

All dependencies are installed into `BASE_DIR/.venv`. **Never** install project
dependencies with global `pip` or `pipx`; always use the installer so the venv and
permissions stay consistent.

```bash
git clone https://github.com/dot1mav/opi-agent.git && cd opi-agent
chmod +x install_opi.sh
sudo ./install_opi.sh            # full install incl. systemd service
./install_opi.sh --skip-service  # local or CI setup, no systemd unit
./install_opi.sh --skip-service --no-start  # install without starting anything
```

Installer behavior:

- **Idempotent** — safe to re-run; existing `.env` and configuration are preserved.
- Creates runtime directories: `workspace/`, `logs/`, `run/`.
- Creates the venv at `BASE_DIR/.venv` if missing and installs `requirements.txt` into it.
- Installs and enables a systemd service (`opi-agent`) unless `--skip-service` is given.
  With `--no-start`, the unit is installed but not started.
- Without root or systemd it falls back to a local setup and prints instructions.

## CLI

Run everything through the venv interpreter:

```bash
.venv/bin/python opi_agent.py --help
```

| Command | Description |
|---|---|
| `.venv/bin/python opi_agent.py --help` | Show help |
| `... version` | Print agent version |
| `... update status` | Show current git state (branch, dirty/clean) |
| `... update check` | Check remote for available updates |
| `... update apply --confirm` | Update: requires a **clean working tree** and a **fast-forward pull** |
| `... service status` / `start` / `stop` / `restart` | Manage the systemd unit (requires systemd; start/stop/restart require root or polkit) |
| `... config show [--raw]` | Show `.env` values; secrets masked unless `--raw` |
| `... config get KEY` | Print one config value |
| `... config set KEY VALUE` | Write a value to `.env` (preserves mode 600) |
| `... config unset KEY` | Remove a key from `.env` |
| `... paths check` | Verify configured paths exist and are readable |
| `... exec --confirm -- COMMAND` | Run `COMMAND` in the workspace (see security section) |
| `... daemon` | Foreground loop used by the systemd unit |
| `... chat` | Interactive chat entrypoint |
| `... telegram` | Telegram entrypoint; may be a compatibility/placeholder mode depending on build |

Notes:

- `update apply` refuses to run on dirty local changes first.
- `service` subcommands other than `status` require root (or equivalent polkit rights).
- The `chat` and `telegram` entrypoints may be compatibility/placeholder modes; check the
  source for what is actually implemented in your revision.

## Configuration

Configuration lives in `.env` at the project root, created by the installer with mode
`600`. Keep it that way:

```bash
chmod 600 .env
```

Relevant example variables:

```dotenv
ALLOW_EXEC=0
EXEC_CONFIRM_REQUIRED=1
```

- `ALLOW_EXEC=0` (default): command execution is disabled.
- `EXEC_CONFIRM_REQUIRED=1` (default): every `exec` requires `--confirm`.

Other application-specific variables belong in `.env` as well. This document does not
prescribe a fixed list of API/token variables — consult the source code and
`requirements.txt` for the variables your revision actually reads.

`config show` masks values whose key names look sensitive (e.g. keys containing
`KEY`, `TOKEN`, `SECRET`, `PASSWORD`). Use `--raw` only when you need the literal values,
and never paste raw output into tickets, chats, or logs.

## Exec security

- Command execution is **disabled by default** (`ALLOW_EXEC=0`). It only runs when
  `ALLOW_EXEC=1`.
- When `EXEC_CONFIRM_REQUIRED=1`, each invocation must include `--confirm`:
  `exec --confirm -- COMMAND`.
- The command runs with `workspace/` as its working directory.

**This is a gate, not a sandbox.** There is no command whitelist and no complete shell
sandbox. A command that passes the gate has the full permissions of the service user
(plus whatever the systemd sandbox restricts). Enabling `ALLOW_EXEC` carries real risk —
review the exact commands your workflow needs and the service user's privileges first.

## systemd hardening

The installed unit (from `opi-agent.service.template`) uses:

```ini
NoNewPrivileges=true
PrivateTmp=true
PrivateDevices=true
ProtectSystem=strict
ProtectHome=read-only
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
MemoryDenyWriteExecute=true
RestrictSUIDSGID=true
RestrictNamespaces=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
CapabilityBoundingSet=
AmbientCapabilities=
ReadWritePaths=/opt/opi-agent/workspace /opt/opi-agent/logs /opt/opi-agent/run
```

- Only the paths listed in `ReadWritePaths` (workspace, logs, run) are writable by the service.
- The service user must have real filesystem write permission on those directories; the
  installer grants ownership when run as root. If you change `BASE_DIR`, re-run the
  installer so `ReadWritePaths` and ownership stay consistent.
- `MemoryDenyWriteExecute=true` blocks JIT/mmap+w+x patterns; ordinary Python code is
  unaffected, but some native extensions may fail.
- `SystemCallFilter=@system-service` blocks unusual syscalls; legitimate exotic tools run
  under the service may log `seccomp` denials in `journalctl`.
- Empty capabilities and `NoNewPrivileges=true` mean the service cannot escalate; any
  task requiring root must be done outside the service.

## Filesystem, permissions, backups, network

- Run the service as a dedicated unprivileged user (the installer creates one).
- Keep `.env` at mode `600` and owned by the service user or an admin account.
- **Back up `.env` before** running `config set`/`unset` or applying updates; it contains
  your secrets and is not stored in git.
- Restrict network exposure with a firewall; the agent runs locally and does not require inbound ports. Only outbound application traffic is needed.
- Apply least privilege everywhere: service user, group memberships, `OPI_ALLOWED_PATHS`
  / allowed-path configuration, and filesystem ACLs.
- Review `.env` and the systemd unit before enabling `ALLOW_EXEC=1`.

## Updating and rollback

```bash
.venv/bin/python opi_agent.py update status   # verify clean tree
.venv/bin/python opi_agent.py update check    # see what is available
.venv/bin/python opi_agent.py update apply --confirm
sudo systemctl restart opi-agent
```

Rollback:

```bash
git reflog                       # find the previous known-good commit
git reset --hard <previous-sha>
.venv/bin/pip install -r requirements.txt
sudo systemctl restart opi-agent
```

Keep a copy of the previous `.env` so configuration can be restored alongside code.

## CI/CD

`.github/workflows/ci-cd.yml` runs:

- `py_compile` validation of `opi_agent.py`
- `bash -n` syntax check of `install_opi.sh`
- CLI smoke tests via the venv interpreter
- Placeholder/diff checks (fail on leftover placeholders)
- A sandboxed install step using `./install_opi.sh --skip-service`

On `v*` tags, a release `tar.gz` artifact is generated and attached to the release.
**CI never installs or starts systemd units.**

## Troubleshooting

```bash
journalctl -u opi-agent -f          # follow service logs
sudo systemctl status opi-agent
sudo systemctl restart opi-agent
.venv/bin/python opi_agent.py paths check
ls -la .venv/bin/python             # venv sanity
git status                          # dirty tree blocks updates
```

Common causes:

| Symptom | Likely cause |
|---|---|
| Service fails to start, `ModuleNotFoundError` | Missing/broken venv — re-run `sudo ./install_opi.sh` |
| Permission denied writing logs/workspace/run | Service user lacks ownership; re-run installer as root |
| `update apply` refuses | Dirty working tree or non-fast-forward remote state |
| Unit fails with sandbox/namespace errors | Kernel or container lacking a hardening feature (e.g. seccomp, namespaces); adjust the unit deliberately, not silently |
| `config get` returns empty | Variable unset; use `config set KEY VALUE` |
| `exec` rejected | `ALLOW_EXEC` disabled or missing `--confirm` |

## Release procedure

```bash
git status                      # must be clean
git tag vX.Y.Z
git push origin main --tags
```

CI builds the release artifact (`tar.gz`) under `dist/` for tag builds and attaches it to
the GitHub release.

## Command reference (summary)

| Command / option | Notes |
|---|---|
| `sudo ./install_opi.sh` | Full install incl. systemd unit |
| `./install_opi.sh --skip-service` | Local/CI install, no unit |
| `--no-start` | Do not start the service after install |
| `.venv/bin/python opi_agent.py --help` | Help |
| `version` | Version string |
| `update status` / `check` / `apply --confirm` | Clean tree + fast-forward required for apply |
| `service status\|start\|stop\|restart` | systemd required; mutations need root |
| `config show [--raw]` / `get KEY` / `set KEY VALUE` / `unset KEY` | Secrets masked without `--raw` |
| `paths check` | Path availability/readability |
| `exec --confirm -- COMMAND` | Gated by `ALLOW_EXEC`, cwd = workspace |
| `daemon` / `chat` / `telegram` | Service loop / interactive entrypoints (telegram may be a placeholder) |
