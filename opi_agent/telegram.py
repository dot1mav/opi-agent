"""Telegram bot for opi-agent with long polling, webhook, proxy, and scheduling support."""

import asyncio
import json
import logging
import os
import ssl
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

import aiohttp
from aiohttp import web

from opi_agent.config import BASE_DIR, get_env, get_env_bool, get_env_int
from opi_agent.log import get_logger, setup_logging

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


@dataclass
class TelegramUser:
    id: int
    first_name: str
    last_name: str = ""
    username: str = ""
    language_code: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def mention(self) -> str:
        return f"@{self.username}" if self.username else str(self.id)


@dataclass
class TelegramChat:
    id: int
    type: str
    title: str = ""
    username: str = ""
    first_name: str = ""
    last_name: str = ""


@dataclass
class TelegramMessage:
    message_id: int
    from_user: Optional[TelegramUser]
    chat: TelegramChat
    date: int
    text: str = ""
    entities: List[Dict] = field(default_factory=list)
    reply_to_message: Optional["TelegramMessage"] = None
    document: Optional[Dict] = None
    photo: List[Dict] = field(default_factory=list)

    @property
    def user_id(self) -> Optional[int]:
        return self.from_user.id if self.from_user else None

    @property
    def is_command(self) -> bool:
        return self.text.startswith("/") if self.text else False

    @property
    def command(self) -> Optional[str]:
        if not self.is_command:
            return None
        parts = self.text.split(maxsplit=1)
        return parts[0][1:].split("@")[0]

    @property
    def command_args(self) -> str:
        if not self.is_command:
            return ""
        parts = self.text.split(maxsplit=1)
        return parts[1] if len(parts) > 1 else ""


@dataclass
class ScheduledTask:
    name: str
    func: Callable
    interval: timedelta
    next_run: datetime
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    running: bool = False
    last_result: Any = None
    last_error: Optional[str] = None


class TelegramBot:
    """Full-featured Telegram bot for opi-agent."""

    def __init__(self):
        self.token = get_env("TELEGRAM_BOT_TOKEN")
        if not self.token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")

        self.allowed_users = self._parse_allowed_users(get_env("TELEGRAM_ALLOWED_USERS", ""))
        self.webhook_url = get_env("TELEGRAM_WEBHOOK_URL", "")
        self.webhook_port = get_env_int("TELEGRAM_WEBHOOK_PORT", 8443)
        self.webhook_cert = get_env("TELEGRAM_WEBHOOK_CERT")
        self.webhook_key = get_env("TELEGRAM_WEBHOOK_KEY")
        self.proxy = get_env("TELEGRAM_PROXY", "")
        self.parse_mode = get_env("TELEGRAM_PARSE_MODE", "HTML")
        self.max_file_size = get_env_int("TELEGRAM_MAX_FILE_SIZE_MB", 50) * 1024 * 1024

        self.session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.commands: Dict[str, Callable] = {}
        self.scheduled_tasks: Dict[str, ScheduledTask] = {}
        self.scheduler_task: Optional[asyncio.Task] = None
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None

        self._register_default_commands()

    def _parse_allowed_users(self, users_str: str) -> Set[int]:
        if not users_str:
            return set()
        result = set()
        for part in users_str.split(","):
            part = part.strip()
            if part:
                try:
                    result.add(int(part))
                except ValueError:
                    if part.startswith("@"):
                        logger.warning("Cannot resolve username %s to ID, use numeric ID", part)
        return result

    def is_allowed(self, user_id: int) -> bool:
        return not self.allowed_users or user_id in self.allowed_users

    def _register_default_commands(self):
        self.register_command("start", self.cmd_start, "Start the bot")
        self.register_command("help", self.cmd_help, "Show help")
        self.register_command("status", self.cmd_status, "Show agent status")
        self.register_command("exec", self.cmd_exec, "Execute a command")
        self.register_command("logs", self.cmd_logs, "Show recent logs")
        self.register_command("config", self.cmd_config, "Show configuration")
        self.register_command("tasks", self.cmd_tasks, "List scheduled tasks")
        self.register_command("schedule", self.cmd_schedule, "Schedule a task")
        self.register_command("unschedule", self.cmd_unschedule, "Remove a scheduled task")
        self.register_command("chat", self.cmd_chat, "Chat with the agent")
        self.register_command("subagents", self.cmd_subagents, "List subagents")
        self.register_command("spawn", self.cmd_spawn, "Spawn a subagent task")
        self.register_command("kill", self.cmd_kill_subagent, "Kill a subagent")

    def register_command(self, name: str, func: Callable, description: str = ""):
        self.commands[name] = func
        func.__doc__ = description

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            connector = aiohttp.TCPConnector(limit=10)
            if self.proxy:
                from aiohttp_socks import ProxyConnector
                connector = ProxyConnector.from_url(self.proxy)
            self.session = aiohttp.ClientSession(connector=connector)
        return self.session

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()
        if self.runner:
            await self.runner.cleanup()

    async def _api_call(self, method: str, data: Dict = None, files: Dict = None) -> Dict:
        session = await self._get_session()
        url = TELEGRAM_API.format(token=self.token, method=method)

        if files:
            form = aiohttp.FormData()
            for k, v in (data or {}).items():
                form.add_field(k, str(v))
            for k, v in files.items():
                form.add_field(k, v)
            async with session.post(url, data=form) as resp:
                return await resp.json()
        else:
            async with session.post(url, json=data) as resp:
                return await resp.json()

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = None,
        reply_markup: Dict = None,
        disable_web_page_preview: bool = True,
    ) -> Dict:
        data = {
            "chat_id": chat_id,
            "text": text[:4096],
            "parse_mode": parse_mode or self.parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        return await self._api_call("sendMessage", data)

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: str = None,
    ) -> Dict:
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:4096],
            "parse_mode": parse_mode or self.parse_mode,
        }
        return await self._api_call("editMessageText", data)

    async def send_document(
        self,
        chat_id: int,
        file_path: Path,
        caption: str = "",
    ) -> Dict:
        if file_path.stat().st_size > self.max_file_size:
            raise ValueError(f"File too large: {file_path.stat().st_size} bytes")

        with file_path.open("rb") as f:
            files = {"document": f}
            data = {"chat_id": chat_id, "caption": caption[:1024]}
            return await self._api_call("sendDocument", data, files)

    async def get_file(self, file_id: str) -> Dict:
        return await self._api_call("getFile", {"file_id": file_id})

    async def download_file(self, file_path: str, dest: Path) -> Path:
        session = await self._get_session()
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        async with session.get(url) as resp:
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(8192):
                    f.write(chunk)
        return dest

    def _parse_message(self, data: Dict) -> TelegramMessage:
        from_user = None
        if "from" in data:
            u = data["from"]
            from_user = TelegramUser(
                id=u["id"],
                first_name=u.get("first_name", ""),
                last_name=u.get("last_name", ""),
                username=u.get("username", ""),
                language_code=u.get("language_code", ""),
            )

        chat = TelegramChat(
            id=data["chat"]["id"],
            type=data["chat"]["type"],
            title=data["chat"].get("title", ""),
            username=data["chat"].get("username", ""),
            first_name=data["chat"].get("first_name", ""),
            last_name=data["chat"].get("last_name", ""),
        )

        return TelegramMessage(
            message_id=data["message_id"],
            from_user=from_user,
            chat=chat,
            date=data["date"],
            text=data.get("text", ""),
            entities=data.get("entities", []),
            document=data.get("document"),
            photo=data.get("photo", []),
        )

    async def handle_message(self, message: TelegramMessage):
        if not self.is_allowed(message.user_id or 0):
            await self.send_message(
                message.chat.id,
                "❌ You are not authorized to use this bot.",
            )
            return

        if message.is_command:
            await self.handle_command(message)
        else:
            await self.handle_chat(message)

    async def handle_command(self, message: TelegramMessage):
        cmd = message.command
        args = message.command_args

        if cmd not in self.commands:
            await self.send_message(
                message.chat.id,
                f"❓ Unknown command: /{cmd}\nUse /help for available commands.",
            )
            return

        try:
            func = self.commands[cmd]
            if asyncio.iscoroutinefunction(func):
                await func(message, args)
            else:
                func(message, args)
        except Exception as e:
            logger.exception("Error executing command %s", cmd)
            await self.send_message(
                message.chat.id,
                f"❌ Error executing /{cmd}: {e}",
            )

    async def handle_chat(self, message: TelegramMessage):
        await self.send_message(
            message.chat.id,
            f"💬 Received: {message.text[:100]}",
        )

    async def cmd_start(self, message: TelegramMessage, args: str):
        text = (
            "🤖 <b>opi-agent Telegram Bot</b>\n\n"
            "Welcome! I'm your Orange Pi agent.\n\n"
            "Use /help to see available commands."
        )
        await self.send_message(message.chat.id, text)

    async def cmd_help(self, message: TelegramMessage, args: str):
        lines = ["📋 <b>Available Commands:</b>\n"]
        for name, func in sorted(self.commands.items()):
            desc = func.__doc__ or "No description"
            lines.append(f"  /{name} - {desc}")
        lines.append("\n💬 You can also chat with me directly!")
        await self.send_message(message.chat.id, "\n".join(lines))

    async def cmd_status(self, message: TelegramMessage, args: str):
        from opi_agent.update import git_describe, in_git_repo
        from opi_agent.config import get_patch_url, get_patch_path

        version = git_describe()
        repo_status = "✅ Git repo" if in_git_repo() else "❌ Not a git repo"
        patch_url = get_patch_url() or "Not configured"
        patch_path = str(get_patch_path()) if get_patch_path() else "Not configured"

        text = (
            f"📊 <b>Agent Status</b>\n\n"
            f"Version: <code>{version}</code>\n"
            f"Repository: {repo_status}\n"
            f"Base dir: <code>{BASE_DIR}</code>\n"
            f"Patch URL: <code>{patch_url}</code>\n"
            f"Patch path: <code>{patch_path}</code>\n"
            f"Allowed users: {len(self.allowed_users) if self.allowed_users else 'All'}\n"
            f"Webhook: {'Enabled' if self.webhook_url else 'Long polling'}"
        )
        await self.send_message(message.chat.id, text)

    async def cmd_exec(self, message: TelegramMessage, args: str):
        if not args:
            await self.send_message(message.chat.id, "Usage: /exec <command>")
            return

        if not get_env_bool("OPI_SHELL_ENABLED", False):
            await self.send_message(message.chat.id, "❌ Shell execution is disabled (OPI_SHELL_ENABLED=false)")
            return

        from opi_agent.exec import validate_command, run_exec
        import shlex

        try:
            cmd_parts = shlex.split(args)
        except ValueError as e:
            await self.send_message(message.chat.id, f"❌ Invalid command syntax: {e}")
            return

        is_valid, error = validate_command(cmd_parts)
        if not is_valid:
            await self.send_message(message.chat.id, f"❌ {error}")
            return

        msg = await self.send_message(message.chat.id, f"⏳ Executing: <code>{args}</code>")

        try:
            exit_code = run_exec(cmd_parts, confirm=True)
            text = (
                f"✅ <b>Command completed</b>\n"
                f"Exit code: {exit_code}"
            )
            await self.edit_message(message.chat.id, msg["result"]["message_id"], text)
        except Exception as e:
            await self.edit_message(message.chat.id, msg["result"]["message_id"], f"❌ Error: {e}")

    async def cmd_logs(self, message: TelegramMessage, args: str):
        lines = 50
        if args:
            try:
                lines = int(args)
            except ValueError:
                pass

        log_file = BASE_DIR / "logs" / "agent.log"
        if not log_file.exists():
            await self.send_message(message.chat.id, "📭 No log file found")
            return

        content = log_file.read_text(encoding="utf-8", errors="replace")
        tail = "\n".join(content.splitlines()[-lines:])

        await self.send_message(
            message.chat.id,
            f"📄 <b>Last {lines} lines of agent.log:</b>\n<code>{tail[-4000:]}</code>",
        )

    async def cmd_config(self, message: TelegramMessage, args: str):
        from opi_agent.config import config_show

        data = config_show(raw=False)
        lines = ["⚙️ <b>Configuration:</b>\n"]
        for k, v in sorted(data.items()):
            lines.append(f"  <code>{k}</code>=<code>{v}</code>")
        await self.send_message(message.chat.id, "\n".join(lines))

    async def cmd_tasks(self, message: TelegramMessage, args: str):
        if not self.scheduled_tasks:
            await self.send_message(message.chat.id, "📭 No scheduled tasks")
            return

        lines = ["📅 <b>Scheduled Tasks:</b>\n"]
        for name, task in self.scheduled_tasks.items():
            status = "🟢 Running" if task.running else "⏸️ Waiting"
            next_run = task.next_run.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(f"  <b>{name}</b> - {status}")
            lines.append(f"    Interval: {task.interval}")
            lines.append(f"    Next run: {next_run}")
            if task.last_error:
                lines.append(f"    Last error: {task.last_error}")
            elif task.last_result is not None:
                lines.append(f"    Last result: {str(task.last_result)[:100]}")
        await self.send_message(message.chat.id, "\n".join(lines))

    async def cmd_schedule(self, message: TelegramMessage, args: str):
        parts = args.split(maxsplit=3)
        if len(parts) < 3:
            await self.send_message(
                message.chat.id,
                "Usage: /schedule <name> <interval_seconds> <command> [args...]",
            )
            return

        name, interval_str, cmd_name, *cmd_args = parts

        try:
            interval = int(interval_str)
        except ValueError:
            await self.send_message(message.chat.id, "❌ Invalid interval (must be seconds)")
            return

        if cmd_name not in self.commands:
            await self.send_message(message.chat.id, f"❌ Unknown command: {cmd_name}")
            return

        if name in self.scheduled_tasks:
            await self.send_message(message.chat.id, f"❌ Task '{name}' already exists")
            return

        func = self.commands[cmd_name]
        task = ScheduledTask(
            name=name,
            func=func,
            interval=timedelta(seconds=interval),
            next_run=datetime.now() + timedelta(seconds=interval),
            args=(message, " ".join(cmd_args)),
        )
        self.scheduled_tasks[name] = task
        await self.send_message(message.chat.id, f"✅ Scheduled task '{name}' every {interval}s")

    async def cmd_unschedule(self, message: TelegramMessage, args: str):
        name = args.strip()
        if not name:
            await self.send_message(message.chat.id, "Usage: /unschedule <name>")
            return

        if name in self.scheduled_tasks:
            del self.scheduled_tasks[name]
            await self.send_message(message.chat.id, f"✅ Removed task '{name}'")
        else:
            await self.send_message(message.chat.id, f"❌ Task '{name}' not found")

    async def cmd_chat(self, message: TelegramMessage, args: str):
        await self.send_message(
            message.chat.id,
            "💬 Chat mode: Send me messages and I'll respond.\n"
            "Type /help for commands, or just chat naturally.",
        )

    async def cmd_subagents(self, message: TelegramMessage, args: str):
        """List all registered subagents."""
        from opi_agent.subagent import get_manager

        manager = get_manager()
        summary = manager.summary()

        if summary["total"] == 0:
            await self.send_message(message.chat.id, "📭 No subagents registered.")
            return

        agents = manager.list_agents()
        lines = [f"🤖 <b>Subagents</b> ({summary['active']} active / {summary['total']} total)\n"]

        for info in agents:
            icon = {
                "pending": "⏳",
                "running": "🟢",
                "completed": "✅",
                "failed": "❌",
                "killed": "⛔",
            }.get(info.state.value, "?")
            lines.append(
                f"  {icon} <code>{info.id}</code> — {info.name} "
                f"({info.state.value}, {info.elapsed:.1f}s)"
            )
            if info.error:
                lines.append(f"    ⚠️ {info.error}")

        await self.send_message(message.chat.id, "\n".join(lines))

    async def cmd_spawn(self, message: TelegramMessage, args: str):
        """Spawn a subagent to run a background task."""
        from opi_agent.subagent import get_manager

        if not args:
            await self.send_message(
                message.chat.id,
                "Usage: /spawn <name> [timeout_seconds]\n"
                "Spawns a demo subagent task.",
            )
            return

        parts = args.split(maxsplit=1)
        name = parts[0]
        timeout = int(parts[1]) if len(parts) > 1 else 120

        manager = get_manager()

        async def _demo_task(task_name: str) -> str:
            """Demo subagent task that simulates work."""
            await asyncio.sleep(2)
            return f"Task '{task_name}' completed successfully"

        try:
            agent_id = await manager.spawn(
                name,
                _demo_task,
                args=(name,),
                timeout=timeout,
                metadata={"spawned_from": "telegram", "user_id": message.user_id},
            )
            await self.send_message(
                message.chat.id,
                f"✅ Subagent spawned!\n"
                f"ID: <code>{agent_id}</code>\n"
                f"Name: {name}\n"
                f"Timeout: {timeout}s\n"
                f"Use /subagents to check status.",
            )
        except Exception as e:
            await self.send_message(message.chat.id, f"❌ Failed to spawn: {e}")

    async def cmd_kill_subagent(self, message: TelegramMessage, args: str):
        """Kill a running subagent."""
        from opi_agent.subagent import get_manager

        if not args:
            await self.send_message(
                message.chat.id,
                "Usage: /kill <agent_id>\nKill a running subagent.",
            )
            return

        agent_id = args.strip()
        manager = get_manager()

        try:
            info = await manager.kill(agent_id)
            await self.send_message(
                message.chat.id,
                f"⛔ Killed subagent <code>{info.id}</code> ({info.name})",
            )
        except Exception as e:
            await self.send_message(message.chat.id, f"❌ {e}")

    async def _scheduler_loop(self):
        while self.running:
            now = datetime.now()
            for task in list(self.scheduled_tasks.values()):
                if not task.running and now >= task.next_run:
                    task.running = True
                    task.next_run = now + task.interval
                    asyncio.create_task(self._run_task(task))

            await asyncio.sleep(1)

    async def _run_task(self, task: ScheduledTask):
        try:
            if asyncio.iscoroutinefunction(task.func):
                result = await task.func(*task.args, **task.kwargs)
            else:
                result = task.func(*task.args, **task.kwargs)
            task.last_result = result
            task.last_error = None
        except Exception as e:
            task.last_error = str(e)
            logger.exception("Scheduled task %s failed", task.name)
        finally:
            task.running = False

    async def start_polling(self):
        logger.info("Starting Telegram bot in long polling mode")
        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())

        offset = 0
        while self.running:
            try:
                session = await self._get_session()
                url = TELEGRAM_API.format(token=self.token, method="getUpdates")
                params = {"offset": offset, "timeout": 30, "allowed_updates": ["message"]}
                async with session.get(url, params=params) as resp:
                    data = await resp.json()

                if data.get("ok"):
                    for update in data["result"]:
                        offset = update["update_id"] + 1
                        if "message" in update:
                            message = self._parse_message(update["message"])
                            asyncio.create_task(self.handle_message(message))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Polling error: %s", e)
                await asyncio.sleep(5)

    async def start_webhook(self):
        if not self.webhook_url:
            raise ValueError("TELEGRAM_WEBHOOK_URL not configured for webhook mode")

        logger.info("Starting Telegram bot in webhook mode on port %d", self.webhook_port)

        self.app = web.Application()
        self.app.router.add_post(f"/{self.token}", self._webhook_handler)
        self.app.router.add_get("/health", self._health_handler)

        self.runner = web.AppRunner(self.app)
        await self.runner.setup()

        ssl_context = None
        if self.webhook_cert and self.webhook_key:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.webhook_cert, self.webhook_key)

        site = web.TCPSite(self.runner, "0.0.0.0", self.webhook_port, ssl_context=ssl_context)
        await site.start()

        await self._set_webhook()
        self.running = True
        self.scheduler_task = asyncio.create_task(self._scheduler_loop())

        while self.running:
            await asyncio.sleep(3600)

    async def _webhook_handler(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            if "message" in data:
                message = self._parse_message(data["message"])
                asyncio.create_task(self.handle_message(message))
            return web.Response(text="OK")
        except Exception as e:
            logger.exception("Webhook error: %s", e)
            return web.Response(status=500, text="Error")

    async def _health_handler(self, request: web.Request) -> web.Response:
        return web.Response(text="OK")

    async def _set_webhook(self):
        url = f"{self.webhook_url.rstrip('/')}/{self.token}"
        data = {"url": url}
        if self.webhook_cert:
            with open(self.webhook_cert, "rb") as f:
                files = {"certificate": f}
                await self._api_call("setWebhook", data, files)
        else:
            await self._api_call("setWebhook", data)
        logger.info("Webhook set to %s", url)


def run_telegram_bot() -> int:
    """Entry point for telegram command."""
    import sys

    setup_logging(log_file=BASE_DIR / "logs" / "telegram.log")

    if not get_env("TELEGRAM_BOT_TOKEN"):
        print("❌ TELEGRAM_BOT_TOKEN not configured", file=sys.stderr)
        return 1

    bot = TelegramBot()

    try:
        if bot.webhook_url:
            asyncio.run(bot.start_webhook())
        else:
            asyncio.run(bot.start_polling())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.exception("Bot error: %s", e)
        return 1
    finally:
        asyncio.run(bot.close())

    return 0