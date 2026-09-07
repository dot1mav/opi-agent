#!/usr/bin/env python3
"""
opi_agent.py - Local AI Agent for Orange Pi (ARMv7l)

A fully functional local AI agent that:
  * Executes shell commands inside a sandboxed workspace
  * Talks to an OpenAI-compatible LLM API (router on localhost:20128/v1)
  * Provides a curses TUI, a plain CLI, a FIFO daemon, and a Telegram bot
  * Installs/uninstalls itself as a systemd service
  * Supports SOCKS5h proxy for Telegram (DNS resolved via proxy)

Usage:
    opi_agent.py run          # curses TUI (default)
    opi_agent.py cli          # plain CLI
    opi_agent.py daemon       # FIFO-based daemon in /opt/opi/run
    opi_agent.py telegram     # Telegram bot
    opi_agent.py install      # install systemd daemon service
    opi_agent.py install-full # install daemon + telegram services
    opi_agent.py uninstall    # remove systemd service(s)
    opi_agent.py models       # list models available on the router
    opi_agent.py exec <cmd>   # one-shot shell exec inside sandbox

Author: opi-agent contributors
License: MIT
"""

import os
import sys
import json
import time
import queue
import signal
import logging
import argparse
import subprocess
import threading
import shlex
from pathlib import Path
from datetime import datetime

try:
    import curses
except ImportError:  # pragma: no cover - minimal systems may lack curses
    curses = None

try:
    from openai import OpenAI as _OpenAIClient
except ImportError:
    _OpenAIClient = None

try:
    import requests
except ImportError:
    requests = None

# PySocks detection (used for socks5h proxy support via `requests`)
try:
    import socks  # noqa: F401
    _HAS_SOCKS = True
except ImportError:
    _HAS_SOCKS = False


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Allow override via env var; default to /opt/opi as requested by user
BASE_DIR = Path(os.environ.get("OPI_BASE_DIR", "/opt/opi")).expanduser()
WORKSPACE_DIR = BASE_DIR / "workspace"
LOG_FILE = BASE_DIR / "opi_agent.log"
ENV_FILE = BASE_DIR / ".env"

ALLOWED_DIRS = [str(WORKSPACE_DIR), str(BASE_DIR / "run"), str(BASE_DIR)]


def load_dotenv(path=None):
    """Load KEY=VALUE pairs from a .env file into os.environ (existing env wins)."""
    candidates = []
    if path:
        candidates.append(Path(path).expanduser())
    env_file = os.environ.get("OPI_ENV_FILE")
    if env_file:
        candidates.append(Path(env_file).expanduser())
    candidates.append(ENV_FILE)
    candidates.append(Path.home() / ".opi_agent" / ".env")
    candidates.append(Path.cwd() / ".env")
    for cand in candidates:
        try:
            if not cand.is_file():
                continue
            for raw in cand.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
            break
        except OSError:
            continue


load_dotenv()

# Ensure base dirs exist (best effort; may need root for /opt/opi)
for d in (BASE_DIR, WORKSPACE_DIR, BASE_DIR / "run"):
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


BLOCKED_COMMANDS = [
    "rm -rf /",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "init 0",
    "init 6",
    ":(){:|:&};:",
    "chmod -r 777 /",
    "> /dev/sda",
]

FORBIDDEN_PATHS = [
    "/etc/shadow",
    "/etc/passwd",
    "/boot",
    "/dev",
    "/proc",
    "/sys",
]

SERVICE_NAME = "opi-agent"
TELEGRAM_SERVICE_NAME = "opi-agent-telegram"

API_MAX_RETRIES = int(os.environ.get("OPI_API_RETRIES", "10"))
API_INITIAL_DELAY = 2
API_MAX_DELAY = 60


# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USERS = set(
    uid.strip()
    for uid in os.environ.get("TELEGRAM_ALLOWED_USERS", "").split(",")
    if uid.strip()
)
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_LONG_POLL_TIMEOUT = 60
TELEGRAM_PROGRESS_INTERVAL = 4
# SOCKS5h proxy: socks5h://[user:pass@]host:port  (h = DNS resolved by proxy)
TELEGRAM_PROXY = os.environ.get("TELEGRAM_PROXY", "")


# ---------------------------------------------------------------------------
# Logging setup (file + stream handlers)
# ---------------------------------------------------------------------------

try:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    # /opt/opi not writable - fall back to ~/.opi_agent for logs/.env
    # (workspace dirs will still try the configured path)
    pass

logger = logging.getLogger("opi_agent")
logger.setLevel(logging.DEBUG)
_log_fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

try:
    _fh = logging.FileHandler(LOG_FILE)
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_log_fmt)
    logger.addHandler(_fh)
except OSError:
    # Fallback: log to home dir
    _fh = logging.FileHandler(Path.home() / ".opi_agent.log")
    _fh.setLevel(logging.DEBUG)
    _fh.setFormatter(_log_fmt)
    logger.addHandler(_fh)

_sh = logging.StreamHandler()
_sh.setLevel(logging.INFO)
_sh.setFormatter(_log_fmt)
logger.addHandler(_sh)

logger.info("opi_agent starting; workspace=%s", WORKSPACE_DIR)


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """Validates shell commands and paths before execution."""

    def is_blocked_command(self, command: str) -> bool:
        cmd = command.strip().lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd:
                logger.warning("Blocked command pattern matched: %r", blocked)
                return True
        return False

    def extract_paths_from_command(self, command: str) -> list:
        paths = []
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        for i, tok in enumerate(tokens):
            if i > 0 and tokens[i - 1] in (">", ">>", "<", "-o", "--output"):
                paths.append(tok)
            elif tok.startswith("/") and not tok.startswith("/usr/bin"):
                paths.append(tok)
        return paths

    def is_path_allowed(self, path: str) -> bool:
        try:
            real = os.path.realpath(path)
        except Exception:
            return False
        for forbidden in FORBIDDEN_PATHS:
            if real == forbidden or real.startswith(forbidden + "/"):
                logger.warning("Forbidden path requested: %s", real)
                return False
        if not path.startswith("/"):
            return True
        for allowed in ALLOWED_DIRS:
            if real == allowed or real.startswith(allowed + "/"):
                return True
        logger.warning("Path outside allowed dirs: %s", real)
        return False

    def validate(self, command: str):
        if not command or not command.strip():
            return False, "empty command"
        if self.is_blocked_command(command):
            return False, "command matches blocklist"
        for p in self.extract_paths_from_command(command):
            if not self.is_path_allowed(p):
                return False, "path not allowed: %s" % p
        return True, ""


# ---------------------------------------------------------------------------
# ShellExecutor
# ---------------------------------------------------------------------------

class ShellExecutor:
    """Runs shell commands inside the sandboxed workspace."""

    TIMEOUT = 120
    MAX_OUTPUT = 5000

    def __init__(self, sandbox: Sandbox = None):
        self.sandbox = sandbox or Sandbox()

    def run(self, command: str) -> str:
        ok, reason = self.sandbox.validate(command)
        if not ok:
            result = "BLOCKED: %s" % reason
            logger.info(result)
            return result

        logger.debug("Executing: %s", command)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT,
                cwd=str(WORKSPACE_DIR),
            )
        except subprocess.TimeoutExpired:
            result = "ERROR: command timed out after %ds" % self.TIMEOUT
            logger.warning(result)
            return result
        except Exception as exc:
            result = "ERROR: %s" % exc
            logger.warning(result)
            return result

        out = proc.stdout or ""
        if proc.stderr:
            out += "\n[stderr]\n" + proc.stderr
        if len(out) > self.MAX_OUTPUT:
            out = out[: self.MAX_OUTPUT] + "\n... [output truncated]"

        result = "exit=%d\n%s" % (proc.returncode, out)
        logger.debug("Command result (first 200 chars): %s", result[:200])
        return result


# ---------------------------------------------------------------------------
# System prompt and tool definition
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a local AI agent running on an Orange Pi (ARMv7l).
You may execute shell commands via the execute_shell tool.
All commands run inside the sandboxed workspace: {ws}

Rules:
 - Only issue commands accepted by the sandbox (no destructive system commands).
 - Work step by step; use the tool whenever it helps you answer accurately.
 - When you have enough information, give a concise final answer without
   calling any more tools.
""".format(ws=WORKSPACE_DIR)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a shell command inside the sandboxed workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run",
                    }
                },
                "required": ["command"],
            },
        },
    }
]


def execute_shell(command: str) -> str:
    return _default_executor.run(command)


_default_executor = ShellExecutor()


# ---------------------------------------------------------------------------
# HTTP helper for router (models listing, etc.) - with optional proxy
# ---------------------------------------------------------------------------

def _proxies_for_url(url: str):
    """Return proxies dict for requests if TELEGRAM_PROXY is set."""
    if not TELEGRAM_PROXY:
        return None
    if "api.telegram.org" in url:
        return {"http": TELEGRAM_PROXY, "https": TELEGRAM_PROXY}
    return None


def list_router_models(base_url: str, api_key: str) -> list:
    """Query the OpenAI-compatible /v1/models endpoint."""
    if requests is None:
        return []
    try:
        r = requests.get(
            base_url.rstrip("/") + "/models",
            headers={"Authorization": "Bearer %s" % api_key},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]
    except Exception as exc:
        logger.warning("list_router_models failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ModelNotAvailableError(Exception):
    """Raised when the router returns model_not_found / no credentials."""

    def __init__(self, model, base_url, api_key, cause):
        self.model = model
        self.base_url = base_url
        self.cause = cause
        msg = "model %r not available at %s" % (model, base_url)
        models = list_router_models(base_url, api_key)
        if models:
            msg += "\nAvailable models on router:\n  - " + "\n  - ".join(models[:30])
            if len(models) > 30:
                msg += "\n  ... and %d more" % (len(models) - 30)
        else:
            msg += "\n(Could not list models from /v1/models endpoint.)"
        super().__init__(msg)


class Agent:
    """LLM agent with a tool-use loop and API retry with exponential backoff."""

    def __init__(
        self,
        executor: ShellExecutor = None,
        model: str = None,
        base_url: str = None,
        api_key: str = None,
        max_iterations: int = 30,
        api_retries: int = API_MAX_RETRIES,
    ):
        self.executor = executor or ShellExecutor()
        self.model = model or os.environ.get("OPI_MODEL", "kr/")
        self.base_url = base_url or os.environ.get("OPI_BASE_URL", "http://localhost:20128/v1")
        self.api_key = (
            api_key
            or os.environ.get("OPI_API_KEY")
            or os.environ.get("9ROUTER_KEY", "local")
        )
        self.max_iterations = max_iterations
        self.api_retries = api_retries
        self.client = None
        self.last_api_error = None
        if _OpenAIClient is not None:
            self.client = _OpenAIClient(base_url=self.base_url, api_key=self.api_key)

    def _call_api(self, messages: list):
        if self.client is None:
            raise RuntimeError(
                "openai package not available; pip install openai to use the API"
            )
        delay = API_INITIAL_DELAY
        last_exc = None
        for attempt in range(1, self.api_retries + 1):
            try:
                logger.debug("API attempt %d/%d (model=%s)", attempt, self.api_retries, self.model)
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    max_tokens=1024,
                )
            except Exception as exc:
                last_exc = exc
                self.last_api_error = str(exc)
                msg_str = str(exc)
                # Detect model_not_found / no credentials - don't retry, raise immediately
                if "model_not_found" in msg_str or "No active credentials" in msg_str:
                    logger.error("Model/provider not available: %s", msg_str)
                    raise ModelNotAvailableError(self.model, self.base_url, self.api_key, exc)
                logger.warning("API attempt %d failed: %s", attempt, exc)
                if attempt < self.api_retries:
                    time.sleep(min(delay, API_MAX_DELAY))
                    delay = min(delay * 2, API_MAX_DELAY)
        raise RuntimeError(
            "API failed after %d retries: %s" % (self.api_retries, last_exc)
        )

    def run_task(self, task_prompt: str, output_cb=None, cancel_cb=None) -> str:
        """Run a task to completion; output_cb(text) receives progress lines.
        cancel_cb() -> True if the caller wants to abort early."""

        def emit(text):
            if output_cb:
                try:
                    output_cb(str(text))
                except Exception:
                    pass
            else:
                print(text)

        emit("[*] Task: %s" % task_prompt)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task_prompt},
        ]

        for iteration in range(1, self.max_iterations + 1):
            if cancel_cb and cancel_cb():
                emit("[!] Task cancelled by user")
                return "cancelled"
            emit("[*] Iteration %d/%d" % (iteration, self.max_iterations))
            try:
                resp = self._call_api(messages)
            except ModelNotAvailableError as exc:
                emit("[!] Model not available: %s" % exc)
                emit("[*] Tip: run `opi models` to list models on the router,")
                emit("[*]      then set OPI_MODEL=<name> in %s" % ENV_FILE)
                return "failed: model not available"
            except Exception as exc:
                emit("[!] API error: %s" % exc)
                return "failed: %s" % exc

            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None)

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    }
                )
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    command = args.get("command", "")
                    emit("[exec] $ %s" % command)
                    result = self.executor.run(command)
                    emit(result)
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result}
                    )
                continue

            answer = msg.content or "(empty response)"
            emit("[done] %s" % answer)
            return answer

        return "failed: max iterations reached"


# ---------------------------------------------------------------------------
# Task queue, result store, worker thread
# ---------------------------------------------------------------------------

task_queue = queue.Queue()
result_store = {}
_result_lock = threading.Lock()


def worker(agent: Agent):
    while True:
        task_id, prompt = task_queue.get()
        if prompt is None:
            task_queue.task_done()
            break
        try:
            with _result_lock:
                result_store[task_id] = {
                    "prompt": prompt,
                    "status": "running",
                    "started": datetime.now().isoformat(),
                }
            result = agent.run_task(prompt)
            status = "done" if not result.startswith("failed") else "error"
        except Exception as exc:
            logger.exception("Task %s failed", task_id)
            result = "failed: %s" % exc
            status = "error"
        with _result_lock:
            result_store[task_id].update({
                "result": result,
                "status": status,
                "finished": datetime.now().isoformat(),
            })
        task_queue.task_done()


def submit_task(prompt: str) -> int:
    task_id = int(time.time() * 1000) % 10 ** 9
    task_queue.put((task_id, prompt))
    return task_id


def get_result(task_id: int):
    with _result_lock:
        return result_store.get(task_id)


# ════════════════════════════════════════════════════════════════
# Telegram Bot Interface (with SOCKS5h proxy support)
# ════════════════════════════════════════════════════════════════

class TelegramBot:
    """Telegram bot for remote management and chat with the Agent."""

    def __init__(self, agent, token="", allowed_users=None, proxy=""):
        self.agent = agent
        self.token = token or TELEGRAM_BOT_TOKEN
        self.allowed_users = allowed_users if allowed_users is not None else TELEGRAM_ALLOWED_USERS
        self.proxy = proxy or TELEGRAM_PROXY
        self._last_update_id = 0
        self._active_chats = {}

        if not self.token:
            raise ValueError("Telegram bot token not set. Set TELEGRAM_BOT_TOKEN env var.")
        if requests is None:
            raise RuntimeError("requests package not available (pip install requests[socks]).")
        if self.proxy:
            if not (self.proxy.startswith("socks5h://")
                    or self.proxy.startswith("socks5://")
                    or self.proxy.startswith("http://")
                    or self.proxy.startswith("https://")):
                raise ValueError(
                    "TELEGRAM_PROXY must start with socks5h://, socks5://, http://, or https://"
                )
            if self.proxy.startswith("socks5") and not _HAS_SOCKS:
                raise RuntimeError(
                    "socks5h/socks5 proxy requires PySocks: "
                    "pip install 'requests[socks]'  (or: pip install PySocks)"
                )
            logger.info("Telegram using proxy: %s", self._redact_proxy(self.proxy))

    @staticmethod
    def _redact_proxy(proxy):
        """Hide credentials in proxy URL when logging."""
        if "@" in proxy:
            scheme, rest = proxy.split("://", 1)
            creds, host = rest.rsplit("@", 1)
            return "%s://***@%s" % (scheme, host)
        return proxy

    def _tg_request(self, method, payload=None, params=None):
        url = TELEGRAM_API_BASE.format(token=self.token, method=method)
        proxies = _proxies_for_url(url)
        headers = {"Content-Type": "application/json"}
        try:
            if payload is not None:
                r = requests.post(url, json=payload, headers=headers,
                                  timeout=TELEGRAM_LONG_POLL_TIMEOUT + 10,
                                  proxies=proxies)
            else:
                r = requests.get(url, params=params or {},
                                 headers=headers,
                                 timeout=TELEGRAM_LONG_POLL_TIMEOUT + 10,
                                 proxies=proxies)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.RequestException as e:
            logger.error("Telegram API error: %s", e)
            return {"ok": False, "description": str(e)}

    def send_message(self, chat_id, text, parse_mode="Markdown"):
        max_len = 4096
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, max_len)
            if split_at < 1000:
                split_at = max_len
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip()
        ok = True
        for chunk in chunks:
            result = self._tg_request("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": parse_mode,
            })
            if not result.get("ok"):
                if parse_mode:
                    result = self._tg_request("sendMessage", {
                        "chat_id": chat_id,
                        "text": chunk,
                    })
                if not result.get("ok"):
                    ok = False
            time.sleep(0.05)
        return ok

    def send_typing(self, chat_id):
        self._tg_request("sendChatAction", {
            "chat_id": chat_id,
            "action": "typing",
        })

    def poll_once(self):
        params = {"timeout": TELEGRAM_LONG_POLL_TIMEOUT}
        if self._last_update_id:
            params["offset"] = self._last_update_id + 1
        result = self._tg_request("getUpdates", params=params)
        if not result.get("ok"):
            logger.warning("getUpdates failed: %s", result.get("description", "unknown"))
            time.sleep(5)
            return
        for update in result.get("result", []):
            self._last_update_id = update.get("update_id", self._last_update_id)
            try:
                self._handle_update(update)
            except Exception as e:
                logger.exception("Error handling update: %s", e)

    def run(self):
        me = self._tg_request("getMe")
        if not me.get("ok"):
            logger.error("Bot token verification failed: %s", me.get("description", ""))
            print("Bot token verification failed: " + str(me.get("description", "unknown error")))
            print("Set TELEGRAM_BOT_TOKEN env var with a valid token from @BotFather.")
            return
        bot_name = me["result"].get("username", "opi-agent")
        logger.info("Telegram bot @%s started.", bot_name)
        print("=" * 60)
        print(" Telegram bot @" + bot_name + " is running.")
        print(" Allowed users: " + str(len(self.allowed_users)) + " configured")
        if self.proxy:
            print(" Proxy: " + self._redact_proxy(self.proxy))
        print(" Press Ctrl+C to stop.")
        print("=" * 60)
        while True:
            try:
                self.poll_once()
            except KeyboardInterrupt:
                logger.info("Telegram bot stopped by user.")
                print("\nBot stopped.")
                break
            except Exception as e:
                logger.exception("Polling error: %s", e)
                time.sleep(10)

    def _is_allowed(self, user_id):
        if not self.allowed_users:
            return True
        return str(user_id) in self.allowed_users

    def _handle_update(self, update):
        msg = update.get("message") or update.get("edited_message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        user = msg.get("from", {})
        user_id = user.get("id", 0)
        username = user.get("username") or user.get("first_name", "uid:" + str(user_id))

        if not self._is_allowed(user_id):
            logger.warning("Unauthorized access from %s (uid=%s)", username, user_id)
            self.send_message(chat_id, "You are not authorized to use this bot.")
            return

        logger.info("TG [%s/%s]: %s", username, user_id, text[:100])

        if not text:
            return

        if text.startswith("/"):
            self._handle_command(chat_id, text, username, user_id)
        else:
            self._handle_chat(chat_id, text, username, user_id)

    def _handle_command(self, chat_id, text, username, user_id):
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower().split("@")[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("/start", "/help"):
            self.send_message(chat_id, (
                "*OPI Agent Bot*\n\n"
                "Connected to Orange Pi AI Agent.\n\n"
                "*Commands:*\n"
                "/run <command> - Execute shell command (sandboxed)\n"
                "/ask <question> - Ask the AI model\n"
                "/status - System status\n"
                "/tasks - Recent tasks\n"
                "/cancel - Cancel running task\n"
                "/help - Show this help\n\n"
                "Or send a message directly to chat with the AI."
            ))
        elif cmd == "/run":
            if not arg:
                self.send_message(chat_id, "Usage: /run <command>")
                return
            self._execute_shell(chat_id, arg)
        elif cmd == "/ask":
            if not arg:
                self.send_message(chat_id, "Usage: /ask <question>")
                return
            self._run_agent_task(chat_id, arg)
        elif cmd == "/status":
            self._send_status(chat_id)
        elif cmd == "/tasks":
            self._send_task_list(chat_id)
        elif cmd == "/cancel":
            self._cancel_task(chat_id)
        else:
            self.send_message(chat_id, "Unknown command: " + cmd + ". Type /help")

    def _handle_chat(self, chat_id, text, username, user_id):
        self._run_agent_task(chat_id, text)

    def _run_agent_task(self, chat_id, prompt):
        self.send_typing(chat_id)

        def progress_cb(text_chunk):
            now = time.time()
            state = self._active_chats.get(chat_id, {})
            last = state.get("last_progress_time", 0)
            if now - last >= TELEGRAM_PROGRESS_INTERVAL:
                self.send_typing(chat_id)
                state["last_progress_time"] = now
                self._active_chats[chat_id] = state

        def _worker():
            self.send_message(chat_id, "Processing...")
            try:
                result = self.agent.run_task(prompt, output_cb=progress_cb)
                if len(result) > 3500:
                    result = result[:3500] + "\n\n... (truncated)"
                prefix = "Result:\n\n" if not result.startswith("Error") else ""
                self.send_message(chat_id, prefix + result)
            except Exception as e:
                logger.exception("Agent task error: %s", e)
                self.send_message(chat_id, "Error: " + str(e)[:200])
            finally:
                self._active_chats.pop(chat_id, None)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        self._active_chats[chat_id] = {"thread": t, "last_progress_time": 0}

    def _execute_shell(self, chat_id, command):
        self.send_typing(chat_id)

        def _worker():
            try:
                executor = getattr(self.agent, "executor", None)
                if executor is None:
                    self.send_message(chat_id, "Executor not available.")
                    return
                output = executor.run(command)
                exit_code = 0
                if output.startswith("exit="):
                    try:
                        exit_code = int(output.split("\n", 1)[0][5:])
                    except ValueError:
                        exit_code = -1
                output = output.strip() or "(no output)"
                status = "OK" if exit_code == 0 else "(exit " + str(exit_code) + ")"
                self.send_message(chat_id, status + "\n```\n" + output + "\n```")
            except PermissionError as e:
                self.send_message(chat_id, "Blocked: " + str(e)[:300])
            except Exception as e:
                logger.exception("Shell exec error: %s", e)
                self.send_message(chat_id, "Error: " + str(e)[:200])

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _send_status(self, chat_id):
        try:
            import platform
            uptime = "unknown"
            try:
                with open("/proc/uptime") as f:
                    secs = float(f.read().split()[0])
                    h, m = int(secs // 3600), int((secs % 3600) // 60)
                    uptime = str(h) + "h " + str(m) + "m"
            except Exception:
                pass
            mem = "unknown"
            try:
                with open("/proc/meminfo") as f:
                    lines = {}
                    for l in f.readlines():
                        if ":" in l:
                            k, v = l.split(":", 1)
                            lines[k] = v
                    total = int(lines["MemTotal"].split()[0])
                    avail = int(lines["MemAvailable"].split()[0])
                    used = total - avail
                    mem = str(used // 1024) + "M / " + str(total // 1024) + "M"
            except Exception:
                pass
            task_count = len(result_store)
            self.send_message(chat_id, (
                "*System Status*\n\n"
                "Host: `" + platform.node() + "`\n"
                "Arch: `" + platform.machine() + "`\n"
                "Python: `" + platform.python_version() + "`\n"
                "Uptime: `" + uptime + "`\n"
                "Memory: `" + mem + "`\n"
                "Workspace: `" + str(WORKSPACE_DIR) + "`\n"
                "Tasks stored: `" + str(task_count) + "`\n"
                "Agent model: `" + str(getattr(self.agent, "model", "n/a")) + "`"
            ))
        except Exception as e:
            self.send_message(chat_id, "Status error: " + str(e))

    def _send_task_list(self, chat_id):
        with _result_lock:
            if not result_store:
                self.send_message(chat_id, "No tasks recorded.")
                return
            lines = ["*Recent Tasks:*\n"]
            for tid, info in list(result_store.items())[-10:]:
                status = info.get("status", "?")
                marker = "[done]" if status == "done" else "[run]" if status == "running" else "[err]"
                lines.append(marker + " `" + str(tid) + "` - " + status)
            self.send_message(chat_id, "\n".join(lines))

    def _cancel_task(self, chat_id):
        state = self._active_chats.get(chat_id)
        if state and state.get("thread"):
            state["cancelled"] = True
            self.send_message(chat_id, "Cancel request registered.")
        else:
            self.send_message(chat_id, "No active task to cancel.")


def telegram_main(agent):
    if not TELEGRAM_BOT_TOKEN:
        print("Telegram bot token not configured!")
        print("Get a token from @BotFather, then edit %s" % ENV_FILE)
        print("  TELEGRAM_BOT_TOKEN=123456:ABC-DEF...")
        print("Optionally set allowed user IDs:")
        print("  TELEGRAM_ALLOWED_USERS=123456789,987654321")
        print("And if you are behind a censorship wall:")
        print("  TELEGRAM_PROXY=socks5h://127.0.0.1:1080")
        return 1
    try:
        bot = TelegramBot(agent)
        bot.run()
        return 0
    except Exception as e:
        print("Failed to start Telegram bot: " + str(e))
        logger.exception("Telegram bot error: %s", e)
        return 1


# ---------------------------------------------------------------------------
# Improved TUI (curses) with colors, status bar, history, scrollback, async
# ---------------------------------------------------------------------------

# Curses color pairs
_COLOR_TITLE = 1
_COLOR_PROMPT = 2
_COLOR_OUTPUT = 3
_COLOR_USER = 4
_COLOR_ERROR = 5
_COLOR_STATUS = 6
_COLOR_INFO = 7
_COLOR_SUCCESS = 8
_COLOR_DIM = 9


def _init_colors():
    if curses is None or not curses.has_colors():
        return False
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_TITLE, curses.COLOR_WHITE, curses.COLOR_BLUE)
    curses.init_pair(_COLOR_PROMPT, curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_OUTPUT, curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_USER, curses.COLOR_YELLOW, -1)
    curses.init_pair(_COLOR_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(_COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(_COLOR_INFO, curses.COLOR_MAGENTA, -1)
    curses.init_pair(_COLOR_SUCCESS, curses.COLOR_GREEN, -1)
    curses.init_pair(_COLOR_DIM, 8, -1)
    return True


class TuiState:
    """Holds all mutable UI state for the curses TUI."""

    def __init__(self):
        self.output_lines = []  # list of (text, color_pair) tuples
        self.input_buf = ""
        self.history = []
        self.history_pos = -1
        self.scroll_offset = 0
        self.running_task = False
        self.cancel_requested = False
        self.spinner_idx = 0
        self.last_status = "ready"
        self.task_thread = None

    def add_output(self, text, color=_COLOR_OUTPUT):
        for line in str(text).split("\n"):
            self.output_lines.append((line, color))
        if self.scroll_offset != 0:
            self.scroll_offset = 0

    def push_history(self, cmd):
        if cmd and (not self.history or self.history[-1] != cmd):
            self.history.append(cmd)
            if len(self.history) > 200:
                self.history = self.history[-200:]
        self.history_pos = -1

    def history_prev(self):
        if not self.history:
            return None
        if self.history_pos == -1:
            self.history_pos = len(self.history) - 1
        elif self.history_pos > 0:
            self.history_pos -= 1
        if 0 <= self.history_pos < len(self.history):
            return self.history[self.history_pos]
        return None

    def history_next(self):
        if not self.history or self.history_pos == -1:
            return None
        self.history_pos += 1
        if self.history_pos >= len(self.history):
            self.history_pos = -1
            return ""
        return self.history[self.history_pos]

    @property
    def spinner(self):
        frames = ["|", "/", "-", "\\"]
        return frames[self.spinner_idx % len(frames)]


def tui_main(agent: Agent):
    if curses is None:
        logger.warning("curses unavailable; falling back to CLI")
        cli_main(agent)
        return

    def run_screen(stdscr):
        curses.curs_set(1)
        colors_ok = _init_colors()

        def attr(pair):
            return curses.color_pair(pair) if colors_ok else curses.A_NORMAL

        state = TuiState()
        state.add_output("OPI Agent TUI - workspace: %s" % WORKSPACE_DIR, _COLOR_INFO)
        state.add_output("Model: %s | Base URL: %s" % (agent.model, agent.base_url), _COLOR_DIM)
        state.add_output("Type a task and press Enter. Hotkeys: F1=help F2=clear "
                         "PgUp/PgDn=scroll Up/Dn=history Ctrl+C=cancel F10=quit", _COLOR_DIM)

        def draw():
            stdscr.erase()
            h, w = stdscr.getmaxyx()
            if h < 5 or w < 20:
                stdscr.addstr(0, 0, "Terminal too small"[:w-1])
                stdscr.refresh()
                return

            # Title bar (top)
            title = " OPI Agent  |  model=%s  |  ws=%s " % (agent.model, WORKSPACE_DIR)
            if len(title) > w:
                title = title[:w]
            try:
                stdscr.addstr(0, 0, title.ljust(w)[:w], attr(_COLOR_TITLE) | curses.A_BOLD)
            except curses.error:
                pass

            # Output area (lines 1 .. h-3)
            output_h = h - 4
            total_lines = len(state.output_lines)
            if state.scroll_offset == 0:
                start = max(0, total_lines - output_h)
            else:
                start = max(0, total_lines - output_h - state.scroll_offset)
            visible = state.output_lines[start:start + output_h]
            for i, (line, color) in enumerate(visible):
                row = 1 + i
                if row >= h - 3:
                    break
                text = line[:w-1]
                try:
                    stdscr.addstr(row, 0, text.ljust(w-1)[:w-1], attr(color))
                except curses.error:
                    pass

            # Scroll indicator (right side of output area)
            if state.scroll_offset > 0:
                indicator = " [up:%d] " % state.scroll_offset
                try:
                    stdscr.addstr(1, max(0, w - len(indicator) - 1), indicator, attr(_COLOR_INFO))
                except curses.error:
                    pass

            # Input line (line h-2)
            prompt_char = ">" if not state.running_task else state.spinner
            prompt_color = _COLOR_PROMPT if not state.running_task else _COLOR_INFO
            try:
                stdscr.addstr(h - 2, 0, prompt_char + " ", attr(prompt_color) | curses.A_BOLD)
                input_text = state.input_buf
                avail_w = max(1, w - len(prompt_char) - 2)
                if len(input_text) <= avail_w:
                    stdscr.addstr(h - 2, len(prompt_char) + 1,
                                 input_text[:avail_w], attr(_COLOR_USER))
                else:
                    visible_input = input_text[-avail_w:]
                    stdscr.addstr(h - 2, len(prompt_char) + 1,
                                 visible_input, attr(_COLOR_USER))
            except curses.error:
                pass

            # Status bar (bottom line)
            status_parts = []
            if state.running_task:
                status_parts.append("RUNNING %s" % state.spinner)
            else:
                status_parts.append(state.last_status)
            status_parts.append("hist:%d" % len(state.history))
            status_parts.append("lines:%d" % len(state.output_lines))
            if state.cancel_requested:
                status_parts.append("CANCELLING")
            status_text = " " + " | ".join(status_parts) + " "
            status_text = status_text.ljust(w)[:w]
            try:
                stdscr.addstr(h - 1, 0, status_text, attr(_COLOR_STATUS))
            except curses.error:
                pass

            # Position cursor at end of input
            try:
                stdscr.move(h - 2, min(len(prompt_char) + 1 + len(state.input_buf), w - 2))
            except curses.error:
                pass

            stdscr.refresh()

        def output_cb(text):
            color = _COLOR_OUTPUT
            t = str(text)
            if t.startswith("[!]") or t.startswith("ERROR") or t.startswith("BLOCKED"):
                color = _COLOR_ERROR
            elif t.startswith("[*]"):
                color = _COLOR_INFO
            elif t.startswith("[exec]"):
                color = _COLOR_PROMPT
            elif t.startswith("[done]"):
                color = _COLOR_SUCCESS
            state.add_output(t, color)

        def cancel_cb():
            return state.cancel_requested

        def run_task_async(prompt):
            state.running_task = True
            state.cancel_requested = False
            state.last_status = "running"

            def _worker():
                try:
                    result = agent.run_task(prompt, output_cb=output_cb, cancel_cb=cancel_cb)
                    if result.startswith("failed") or result.startswith("cancelled"):
                        state.add_output("=> " + result, _COLOR_ERROR)
                        state.last_status = "error"
                    else:
                        state.add_output("=> " + result, _COLOR_SUCCESS)
                        state.last_status = "done"
                except Exception as e:
                    state.add_output("[!] Exception: %s" % e, _COLOR_ERROR)
                    state.last_status = "error"
                finally:
                    state.running_task = False
                    state.cancel_requested = False
                    state.task_thread = None

            state.task_thread = threading.Thread(target=_worker, daemon=True)
            state.task_thread.start()

        # Main event loop
        stdscr.timeout(200)  # refresh every 200ms while waiting for input
        while True:
            draw()
            key = stdscr.getch()

            if key == -1:
                if state.running_task:
                    state.spinner_idx += 1
                continue

            if key in (curses.KEY_BACKSPACE, 127, 8):
                state.input_buf = state.input_buf[:-1]
            elif key in (10, 13):  # Enter
                cmd = state.input_buf.strip()
                state.input_buf = ""
                if cmd:
                    if state.running_task:
                        state.add_output("[!] A task is already running. Press Ctrl+C to cancel.", _COLOR_ERROR)
                        continue
                    if cmd.lower() in ("quit", "exit", "q"):
                        if state.running_task:
                            state.add_output("[!] Cannot quit while task is running.", _COLOR_ERROR)
                            continue
                        break
                    state.push_history(cmd)
                    state.add_output("> " + cmd, _COLOR_PROMPT)
                    run_task_async(cmd)
            elif key == curses.KEY_UP:
                prev = state.history_prev()
                if prev is not None:
                    state.input_buf = prev
            elif key == curses.KEY_DOWN:
                nxt = state.history_next()
                if nxt is not None:
                    state.input_buf = nxt
            elif key == curses.KEY_PPAGE:  # Page Up
                state.scroll_offset += 10
            elif key == curses.KEY_NPAGE:  # Page Down
                state.scroll_offset = max(0, state.scroll_offset - 10)
            elif key == curses.KEY_HOME:
                state.scroll_offset = max(0, len(state.output_lines) - 5)
            elif key == curses.KEY_END:
                state.scroll_offset = 0
            elif key == curses.KEY_RESIZE:
                pass
            elif key == 3:  # Ctrl+C
                if state.running_task:
                    state.cancel_requested = True
                    state.last_status = "cancelling"
                    state.add_output("[*] Cancel requested...", _COLOR_INFO)
                else:
                    state.add_output("[*] Press F10 or type 'quit' to exit", _COLOR_DIM)
            elif key == 12:  # Ctrl+L - refresh
                stdscr.redrawwin()
            elif key == curses.KEY_F0 + 1 or key == 262:  # F1 = help
                state.add_output("", _COLOR_DIM)
                state.add_output("=== Help ===", _COLOR_INFO)
                state.add_output("Type a task description and press Enter to run it.", _COLOR_DIM)
                state.add_output("Hotkeys:", _COLOR_DIM)
                state.add_output("  Enter       - Run typed task", _COLOR_DIM)
                state.add_output("  Up/Down     - Browse command history", _COLOR_DIM)
                state.add_output("  PgUp/PgDn   - Scroll output (10 lines)", _COLOR_DIM)
                state.add_output("  Home/End    - Jump to top/bottom", _COLOR_DIM)
                state.add_output("  Ctrl+C      - Cancel running task", _COLOR_DIM)
                state.add_output("  Ctrl+L      - Refresh screen", _COLOR_DIM)
                state.add_output("  F1          - This help", _COLOR_DIM)
                state.add_output("  F2          - Clear output", _COLOR_DIM)
                state.add_output("  F10         - Quit", _COLOR_DIM)
                state.add_output("  quit/exit/q - Quit (alternative)", _COLOR_DIM)
                state.add_output("============", _COLOR_INFO)
            elif key == curses.KEY_F0 + 2:  # F2 = clear
                state.output_lines = []
                state.scroll_offset = 0
            elif key == curses.KEY_F0 + 10:  # F10 = quit
                if state.running_task:
                    state.cancel_requested = True
                    state.add_output("[*] Cancelling... press F10 again to force quit", _COLOR_INFO)
                    time.sleep(0.3)
                    if state.running_task:
                        break
                else:
                    break
            elif 32 <= key < 127:
                state.input_buf += chr(key)

        if state.task_thread and state.task_thread.is_alive():
            state.cancel_requested = True
            state.task_thread.join(timeout=2)

    curses.wrapper(run_screen)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def cli_main(agent: Agent):
    print("OPI Agent CLI")
    print("  workspace : %s" % WORKSPACE_DIR)
    print("  model     : %s" % agent.model)
    print("  base URL  : %s" % agent.base_url)
    print("Type a task and press Enter ('quit' to exit).")
    while True:
        try:
            line = input("agent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break
        result = agent.run_task(line)
        print("=> %s" % result)


# ---------------------------------------------------------------------------
# Daemon mode (FIFO + pidfile in /opt/opi/run)
# ---------------------------------------------------------------------------

DAEMON_DIR = BASE_DIR / "run"
FIFO_PATH = DAEMON_DIR / "agent.fifo"
PIDFILE = DAEMON_DIR / "agent.pid"
DAEMON_OUT = DAEMON_DIR / "last_result.json"


def daemon_main(agent: Agent):
    try:
        DAEMON_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.error("Cannot create daemon dir %s (need write permission)", DAEMON_DIR)
        sys.exit(1)

    if PIDFILE.exists():
        logger.error("Daemon appears to be running (pidfile %s)", PIDFILE)
        sys.exit(1)
    PIDFILE.write_text(str(os.getpid()))

    if not FIFO_PATH.exists():
        os.mkfifo(str(FIFO_PATH))

    def _stop(signum, frame):
        logger.info("Daemon stopping (signal %s)", signum)
        PIDFILE.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    logger.info("Daemon listening on %s", FIFO_PATH)
    print("Daemon listening on %s (pid %d)" % (FIFO_PATH, os.getpid()))
    try:
        while True:
            with open(str(FIFO_PATH), "r") as fifo:
                prompt = fifo.read().strip()
            if not prompt:
                continue
            logger.info("Daemon received task: %s", prompt)
            result = agent.run_task(prompt, output_cb=lambda t: logger.info(t))
            DAEMON_OUT.write_text(
                json.dumps(
                    {"task": prompt, "result": result},
                    ensure_ascii=False,
                    indent=2,
                )
            )
    finally:
        PIDFILE.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# One-shot exec (sandbox)
# ---------------------------------------------------------------------------

def exec_main(agent: Agent, command: str):
    """Run a single shell command in the sandbox and print the result."""
    print(agent.executor.run(command))


# ---------------------------------------------------------------------------
# Models listing
# ---------------------------------------------------------------------------

def models_main(agent: Agent):
    print("Querying %s/models ..." % agent.base_url)
    models = list_router_models(agent.base_url, agent.api_key)
    if not models:
        print("No models returned (or endpoint unreachable / unauthorized).")
        print("Check OPI_BASE_URL and OPI_API_KEY in %s" % ENV_FILE)
        return 1
    print("Available models (%d):" % len(models))
    for m in models:
        marker = " (current)" if m == agent.model else ""
        print("  - " + m + marker)
    if agent.model not in models:
        print("\nWARNING: current model %r is NOT in the list above." % agent.model)
        print("Set OPI_MODEL=<one-of-above> in %s" % ENV_FILE)
    return 0


# ---------------------------------------------------------------------------
# systemd install / uninstall
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=Orange Pi Local AI Agent (daemon)
After=network.target

[Service]
Type=simple
ExecStart={python} {script} daemon
WorkingDirectory={workspace}
Restart=on-failure
RestartSec=5
User={user}
EnvironmentFile={envfile}
# Fallback env (overridden by EnvironmentFile if present)
Environment=OPI_BASE_DIR={base_dir}
Environment=OPI_MODEL={model}
Environment=OPI_BASE_URL={base_url}

[Install]
WantedBy=multi-user.target
"""

SYSTEMD_TELEGRAM_UNIT_TEMPLATE = """[Unit]
Description=Orange Pi AI Agent - Telegram Bot
After=network.target opi-agent.service
Wants=opi-agent.service

[Service]
Type=simple
ExecStart={python} {script} telegram
WorkingDirectory={workspace}
Restart=on-failure
RestartSec=5
User={user}
EnvironmentFile={envfile}
Environment=OPI_BASE_DIR={base_dir}

[Install]
WantedBy=multi-user.target
"""


def _ensure_env_file(envfile: Path):
    """Create a .env with placeholder values if it doesn't exist."""
    if envfile.exists():
        return
    template = """# opi-agent environment file
# Edit and restart with: systemctl restart opi-agent opi-agent-telegram

# --- LLM router ---
OPI_BASE_URL=http://localhost:20128/v1
OPI_API_KEY=local
# Set this to a valid model id from `opi models`:
OPI_MODEL=kr/

# --- Telegram bot (optional, only needed for `telegram` service) ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=
# SOCKS5h proxy (DNS resolved by proxy) - required if Telegram is blocked
# Format: socks5h://[user:pass@]host:port
TELEGRAM_PROXY=
"""
    try:
        envfile.write_text(template)
        try:
            os.chmod(envfile, 0o600)
        except OSError:
            pass
        logger.info("Created env file template at %s", envfile)
    except OSError:
        logger.warning("Cannot write %s (need root). Run install as root.", envfile)


def install_service(install_telegram: bool = False):
    """Write the systemd units and enable/start the service(s)."""
    envfile = ENV_FILE
    _ensure_env_file(envfile)

    unit_path = Path("/etc/systemd/system/%s.service" % SERVICE_NAME)
    unit = SYSTEMD_UNIT_TEMPLATE.format(
        python=sys.executable,
        script=str(Path(__file__).resolve()),
        workspace=str(WORKSPACE_DIR),
        user=os.environ.get("USER") or "root",
        envfile=str(envfile),
        base_dir=str(BASE_DIR),
        model=os.environ.get("OPI_MODEL", "kr/"),
        base_url=os.environ.get("OPI_BASE_URL", "http://localhost:20128/v1"),
    )
    try:
        unit_path.write_text(unit)
    except OSError:
        logger.error("Root privileges required to install service")
        return 1

    if install_telegram:
        tg_unit_path = Path("/etc/systemd/system/%s.service" % TELEGRAM_SERVICE_NAME)
        tg_unit = SYSTEMD_TELEGRAM_UNIT_TEMPLATE.format(
            python=sys.executable,
            script=str(Path(__file__).resolve()),
            workspace=str(WORKSPACE_DIR),
            user=os.environ.get("USER") or "root",
            envfile=str(envfile),
            base_dir=str(BASE_DIR),
        )
        tg_unit_path.write_text(tg_unit)

    subprocess.run("systemctl daemon-reload", shell=True, check=True)
    subprocess.run("systemctl enable %s" % SERVICE_NAME, shell=True, check=True)
    subprocess.run("systemctl restart %s" % SERVICE_NAME, shell=True, check=True)
    logger.info("Service %s installed and started", SERVICE_NAME)
    print("Installed: %s.service" % SERVICE_NAME)
    if install_telegram:
        subprocess.run("systemctl enable %s" % TELEGRAM_SERVICE_NAME, shell=True, check=True)
        subprocess.run("systemctl restart %s" % TELEGRAM_SERVICE_NAME, shell=True, check=True)
        logger.info("Service %s installed and started", TELEGRAM_SERVICE_NAME)
        print("Installed: %s.service" % TELEGRAM_SERVICE_NAME)
    print("\nEdit %s to set tokens / model, then:" % envfile)
    print("  systemctl restart %s" % SERVICE_NAME)
    if install_telegram:
        print("  systemctl restart %s" % TELEGRAM_SERVICE_NAME)
    return 0


def uninstall_service():
    try:
        subprocess.run("systemctl stop %s" % TELEGRAM_SERVICE_NAME, shell=True, check=False)
        subprocess.run("systemctl disable %s" % TELEGRAM_SERVICE_NAME, shell=True, check=False)
        subprocess.run("systemctl stop %s" % SERVICE_NAME, shell=True, check=False)
        subprocess.run("systemctl disable %s" % SERVICE_NAME, shell=True, check=False)
        for name in (SERVICE_NAME, TELEGRAM_SERVICE_NAME):
            p = Path("/etc/systemd/system/%s.service" % name)
            if p.exists():
                p.unlink()
        subprocess.run("systemctl daemon-reload", shell=True, check=False)
        logger.info("Services uninstalled")
        print("Removed: %s.service, %s.service" % (SERVICE_NAME, TELEGRAM_SERVICE_NAME))
        return 0
    except OSError:
        logger.error("Root privileges required to uninstall service")
        return 1


# ---------------------------------------------------------------------------
# argparse main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="opi_agent",
        description="Local AI Agent for Orange Pi (ARMv7l)",
    )
    parser.add_argument("--model", default=None,
                        help="model name (env: OPI_MODEL, default: kr/)")
    parser.add_argument("--base-url", default=None,
                        help="router base URL (env: OPI_BASE_URL, default: http://localhost:20128/v1)")
    parser.add_argument("--api-key", default=None,
                        help="API key (env: OPI_API_KEY or 9ROUTER_KEY, default: local)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="start curses TUI (default)")
    sub.add_parser("cli", help="start plain CLI")
    sub.add_parser("daemon", help="run as FIFO-based daemon")
    sub.add_parser("telegram", help="start Telegram bot")
    sub.add_parser("models", help="list models available on the router")
    sub.add_parser("install", help="install systemd daemon service")
    sub.add_parser("install-full", help="install daemon + telegram services")
    sub.add_parser("uninstall", help="uninstall systemd service(s)")
    exec_p = sub.add_parser("exec", help="run a single shell command in the sandbox")
    exec_p.add_argument("cmd", nargs=argparse.REMAINDER, help="command to run")

    args = parser.parse_args()
    command = args.command or "run"

    if command == "install":
        sys.exit(install_service(install_telegram=False))
    if command == "install-full":
        sys.exit(install_service(install_telegram=True))
    if command == "uninstall":
        sys.exit(uninstall_service())

    agent = Agent(model=args.model, base_url=args.base_url, api_key=args.api_key)

    if command == "exec":
        cmd_str = " ".join(args.cmd) if args.cmd else ""
        if not cmd_str:
            print("Usage: opi_agent.py exec <command...>")
            sys.exit(2)
        exec_main(agent, cmd_str)
        return
    if command == "models":
        sys.exit(models_main(agent))
    if command == "daemon":
        daemon_main(agent)
    elif command == "telegram":
        sys.exit(telegram_main(agent))
    elif command == "cli":
        cli_main(agent)
    else:
        tui_main(agent)


if __name__ == "__main__":
    main()
