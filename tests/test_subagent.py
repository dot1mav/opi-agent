"""Tests for subagent module."""

import asyncio
import os
import time

import pytest

from opi_agent.exceptions import SubagentError
from opi_agent.subagent import (
    SubagentInfo,
    SubagentManager,
    SubagentState,
    get_manager,
    reset_manager,
)


@pytest.fixture(autouse=True)
def _reset_manager():
    """Reset the global manager singleton before each test."""
    reset_manager()
    yield
    reset_manager()


@pytest.fixture
def _enable_subagent():
    """Enable subagent for tests."""
    os.environ["OPI_SUBAGENT_ENABLED"] = "true"
    os.environ["OPI_SUBAGENT_MAX_COUNT"] = "3"
    os.environ["OPI_SUBAGENT_TIMEOUT"] = "10"
    yield
    for key in ["OPI_SUBAGENT_ENABLED", "OPI_SUBAGENT_MAX_COUNT", "OPI_SUBAGENT_TIMEOUT"]:
        os.environ.pop(key, None)


class TestSubagentState:
    """Tests for SubagentState enum."""

    def test_states_exist(self):
        assert SubagentState.PENDING.value == "pending"
        assert SubagentState.RUNNING.value == "running"
        assert SubagentState.COMPLETED.value == "completed"
        assert SubagentState.FAILED.value == "failed"
        assert SubagentState.KILLED.value == "killed"


class TestSubagentInfo:
    """Tests for SubagentInfo dataclass."""

    def test_elapsed_while_running(self):
        info = SubagentInfo(
            id="test1",
            name="test",
            state=SubagentState.RUNNING,
            started_at=time.time() - 5,
        )
        assert info.elapsed >= 4.9
        assert info.is_active is True

    def test_elapsed_when_finished(self):
        start = time.time() - 10
        info = SubagentInfo(
            id="test1",
            name="test",
            state=SubagentState.COMPLETED,
            started_at=start,
            finished_at=start + 5,
        )
        assert abs(info.elapsed - 5.0) < 0.1
        assert info.is_active is False

    def test_is_active_pending(self):
        info = SubagentInfo(
            id="test1",
            name="test",
            state=SubagentState.PENDING,
            started_at=time.time(),
        )
        assert info.is_active is True

    def test_is_active_failed(self):
        info = SubagentInfo(
            id="test1",
            name="test",
            state=SubagentState.FAILED,
            started_at=time.time(),
            finished_at=time.time(),
        )
        assert info.is_active is False


class TestSubagentManager:
    """Tests for SubagentManager."""

    def test_not_enabled_raises(self):
        manager = SubagentManager()
        with pytest.raises(SubagentError, match="disabled"):
            asyncio.run(
                manager.spawn("test", lambda: asyncio.sleep(0))
            )

    @pytest.mark.usefixtures("_enable_subagent")
    def test_spawn_and_complete(self):
        manager = SubagentManager()

        async def _task():
            return "done"

        agent_id = asyncio.run(manager.spawn("test-task", _task))
        assert agent_id is not None
        assert len(agent_id) == 12

        # Wait for completion
        time.sleep(0.5)

        info = manager.status(agent_id)
        assert info.state == SubagentState.COMPLETED
        assert info.result == "done"
        assert info.name == "test-task"

    @pytest.mark.usefixtures("_enable_subagent")
    def test_spawn_and_timeout(self):
        manager = SubagentManager()

        async def _slow_task():
            await asyncio.sleep(100)
            return "never"

        async def _run():
            agent_id = await manager.spawn("slow", _slow_task, timeout=1)
            # Wait for timeout to fire (need > 1s)
            await asyncio.sleep(1.5)
            return agent_id

        agent_id = asyncio.run(_run())

        info = manager.status(agent_id)
        assert info.state == SubagentState.FAILED
        assert "Timed out" in info.error

    @pytest.mark.usefixtures("_enable_subagent")
    def test_spawn_and_failure(self):
        manager = SubagentManager()

        async def _failing_task():
            raise ValueError("boom")

        agent_id = asyncio.run(
            manager.spawn("fail", _failing_task)
        )

        time.sleep(0.5)

        info = manager.status(agent_id)
        assert info.state == SubagentState.FAILED
        assert "boom" in info.error

    @pytest.mark.usefixtures("_enable_subagent")
    def test_max_count_enforced(self):
        os.environ["OPI_SUBAGENT_MAX_COUNT"] = "1"
        manager = SubagentManager()

        async def _slow():
            await asyncio.sleep(10)

        # First spawn succeeds
        asyncio.run(manager.spawn("first", _slow))

        # Second spawn fails
        with pytest.raises(SubagentError, match="Maximum"):
            asyncio.run(manager.spawn("second", _slow))

    @pytest.mark.usefixtures("_enable_subagent")
    def test_list_agents(self):
        manager = SubagentManager()

        async def _task():
            return "ok"

        asyncio.run(manager.spawn("task-a", _task))
        asyncio.run(manager.spawn("task-b", _task))

        time.sleep(0.5)

        all_agents = manager.list_agents()
        assert len(all_agents) == 2

        active = manager.list_agents(active_only=True)
        # Both should be completed by now
        assert len(active) == 0

    @pytest.mark.usefixtures("_enable_subagent")
    def test_kill_agent(self):
        manager = SubagentManager()

        async def _slow():
            await asyncio.sleep(100)

        agent_id = asyncio.run(manager.spawn("killme", _slow))
        time.sleep(0.2)

        async def _kill():
            return await manager.kill(agent_id)

        info = asyncio.run(_kill())
        assert info.state == SubagentState.KILLED
        assert "Killed by user" in info.error

    @pytest.mark.usefixtures("_enable_subagent")
    def test_kill_nonexistent(self):
        manager = SubagentManager()
        with pytest.raises(SubagentError, match="not found"):
            asyncio.run(manager.kill("nonexistent"))

    @pytest.mark.usefixtures("_enable_subagent")
    def test_kill_all(self):
        manager = SubagentManager()

        async def _slow():
            await asyncio.sleep(100)

        asyncio.run(manager.spawn("a", _slow))
        asyncio.run(manager.spawn("b", _slow))
        time.sleep(0.2)

        async def _kill_all():
            return await manager.kill_all()

        count = asyncio.run(_kill_all())
        assert count == 2

    @pytest.mark.usefixtures("_enable_subagent")
    def test_cleanup_finished(self):
        manager = SubagentManager()

        async def _task():
            return "ok"

        asyncio.run(manager.spawn("task1", _task))
        time.sleep(0.5)

        count = manager.cleanup_finished()
        assert count == 1
        assert len(manager.list_agents()) == 0

    @pytest.mark.usefixtures("_enable_subagent")
    def test_summary(self):
        manager = SubagentManager()
        summary = manager.summary()
        assert summary["enabled"] is True
        assert summary["max_count"] == 3
        assert summary["total"] == 0
        assert summary["active"] == 0


class TestSingleton:
    """Tests for module-level singleton."""

    def test_get_manager_returns_same_instance(self):
        m1 = get_manager()
        m2 = get_manager()
        assert m1 is m2

    def test_reset_manager(self):
        m1 = get_manager()
        reset_manager()
        m2 = get_manager()
        assert m1 is not m2

