"""Subagent management for opi-agent.

Subagents are isolated worker processes spawned by the main agent to perform
independent tasks. Each subagent has its own timeout and lifecycle management.

Usage:
    manager = SubagentManager()
    agent_id = await manager.spawn("my-task", task_handler, args=("arg1",))
    status = manager.status(agent_id)
    await manager.kill(agent_id)
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from opi_agent.config import get_env_bool, get_env_int
from opi_agent.exceptions import SubagentError
from opi_agent.log import get_logger

logger = get_logger(__name__)


class SubagentState(str, Enum):
    """Lifecycle states of a subagent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    KILLED = "killed"


@dataclass
class SubagentInfo:
    """Information about a running or completed subagent."""

    id: str
    name: str
    state: SubagentState
    started_at: float
    finished_at: Optional[float] = None
    timeout: int = 120
    result: Any = None
    error: Optional[str] = None
    task_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        if self.finished_at:
            return self.finished_at - self.started_at
        return time.time() - self.started_at

    @property
    def is_active(self) -> bool:
        return self.state in (SubagentState.PENDING, SubagentState.RUNNING)


class SubagentManager:
    """Manages the lifecycle of subagents."""

    def __init__(self) -> None:
        self._agents: dict[str, SubagentInfo] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    @property
    def enabled(self) -> bool:
        return get_env_bool("OPI_SUBAGENT_ENABLED", False)

    @property
    def max_count(self) -> int:
        return get_env_int("OPI_SUBAGENT_MAX_COUNT", 3)

    @property
    def default_timeout(self) -> int:
        return get_env_int("OPI_SUBAGENT_TIMEOUT", 120)

    def active_count(self) -> int:
        return sum(1 for info in self._agents.values() if info.is_active)

    def _check_limits(self) -> None:
        if not self.enabled:
            raise SubagentError(
                "Subagent spawning is disabled. Set OPI_SUBAGENT_ENABLED=true"
            )
        if self.active_count() >= self.max_count:
            raise SubagentError(
                f"Maximum subagent limit reached ({self.max_count}). "
                "Kill existing subagents or increase OPI_SUBAGENT_MAX_COUNT."
            )

    async def spawn(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """Spawn a new subagent to run an async function."""
        self._check_limits()

        agent_id = uuid.uuid4().hex[:12]
        timeout = timeout or self.default_timeout
        kwargs = kwargs or {}

        info = SubagentInfo(
            id=agent_id,
            name=name,
            state=SubagentState.PENDING,
            started_at=time.time(),
            timeout=timeout,
            task_name=func.__name__ if hasattr(func, "__name__") else str(func),
            metadata=metadata or {},
        )
        self._agents[agent_id] = info

        logger.info("Spawning subagent %s (%s)", agent_id, name)

        async def _wrapped() -> None:
            info.state = SubagentState.RUNNING
            try:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                info.result = result
                info.state = SubagentState.COMPLETED
                logger.info("Subagent %s completed successfully", agent_id)
            except asyncio.TimeoutError:
                info.error = f"Timed out after {timeout}s"
                info.state = SubagentState.FAILED
                logger.warning("Subagent %s timed out after %ds", agent_id, timeout)
            except Exception as e:
                info.error = str(e)
                info.state = SubagentState.FAILED
                logger.exception("Subagent %s failed: %s", agent_id, e)
            finally:
                info.finished_at = time.time()
                self._tasks.pop(agent_id, None)

        task = asyncio.create_task(_wrapped())
        self._tasks[agent_id] = task
        info.state = SubagentState.RUNNING

        return agent_id

    @property
    def is_active(self) -> bool:
        return self.state in (SubagentState.PENDING, SubagentState.RUNNING)



    def status(self, agent_id: str) -> SubagentInfo:
        if agent_id not in self._agents:
            raise SubagentError(f"Subagent not found: {agent_id}")
        return self._agents[agent_id]

    def list_agents(self, active_only: bool = False) -> list[SubagentInfo]:
        agents = list(self._agents.values())
        if active_only:
            agents = [a for a in agents if a.is_active]
        return sorted(agents, key=lambda a: a.started_at, reverse=True)

    async def kill(self, agent_id: str) -> SubagentInfo:
        if agent_id not in self._agents:
            raise SubagentError(f"Subagent not found: {agent_id}")

        info = self._agents[agent_id]
        if not info.is_active:
            raise SubagentError(
                f"Subagent {agent_id} is already {info.state.value}"
            )

        task = self._tasks.get(agent_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        info.state = SubagentState.KILLED
        info.finished_at = time.time()
        info.error = "Killed by user"
        self._tasks.pop(agent_id, None)

        logger.info("Killed subagent %s (%s)", agent_id, info.name)
        return info

    async def kill_all(self) -> int:
        active = [a for a in self._agents.values() if a.is_active]
        count = 0
        for info in active:
            try:
                await self.kill(info.id)
                count += 1
            except SubagentError:
                pass
        return count

    def cleanup_finished(self) -> int:
        finished = [
            aid for aid, info in self._agents.items() if not info.is_active
        ]
        for aid in finished:
            del self._agents[aid]
        return len(finished)

    def summary(self) -> dict[str, Any]:
        all_agents = list(self._agents.values())
        return {
            "total": len(all_agents),
            "active": sum(1 for a in all_agents if a.is_active),
            "completed": sum(
                1 for a in all_agents if a.state == SubagentState.COMPLETED
            ),
            "failed": sum(
                1 for a in all_agents if a.state == SubagentState.FAILED
            ),
            "killed": sum(
                1 for a in all_agents if a.state == SubagentState.KILLED
            ),
            "max_count": self.max_count,
            "enabled": self.enabled,
        }


# Module-level singleton
_manager: Optional[SubagentManager] = None


def get_manager() -> SubagentManager:
    global _manager
    if _manager is None:
        _manager = SubagentManager()
    return _manager


def reset_manager() -> None:
    global _manager
    _manager = None
