"""Sub-agent lifecycle manager for Agent007.

Loads agent specs from JSON, dynamically imports implementation classes,
and manages spawning/tracking/killing of sub-agents. Semaphore-bounded
to max 3 concurrent agents (Pi 5 RAM constraint).
"""

import asyncio
import importlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from agents.base import SubAgentResult, SubAgentProtocol
from agents.bus import AgentMessageBus, SharedContext

logger = logging.getLogger("agent007.registry")

SPECS_DIR = Path(__file__).parent / "specs"

# Pi 5 constraint — max concurrent sub-agents
MAX_CONCURRENT_AGENTS = 3


class SubAgentRegistry:
    """Manages the full lifecycle of sub-agents.

    Loads specs from JSON, imports implementations dynamically,
    spawns agents within a semaphore bound, and tracks active tasks.
    """

    def __init__(self) -> None:
        self._specs: dict[str, dict[str, Any]] = {}
        self._active: dict[str, asyncio.Task[SubAgentResult]] = {}
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
        self._results: dict[str, SubAgentResult] = {}

    async def load_specs(self) -> None:
        """Load all agent spec JSON files from the specs/ directory."""
        if not SPECS_DIR.exists():
            logger.warning("Specs directory not found: %s", SPECS_DIR)
            return

        for spec_file in SPECS_DIR.glob("*.json"):
            try:
                with open(spec_file) as f:
                    spec = json.load(f)
                agent_type = spec.get("type", "")
                if agent_type:
                    self._specs[agent_type] = spec
                    logger.info("Loaded spec: %s", agent_type)
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load spec %s: %s", spec_file, exc)

        logger.info("Registry loaded %d agent specs", len(self._specs))

    def get_spec(self, agent_type: str) -> dict[str, Any] | None:
        """Return the spec for a given agent type, or None."""
        return self._specs.get(agent_type)

    def list_specs(self) -> list[str]:
        """Return all loaded agent type names."""
        return list(self._specs.keys())

    def list_active(self) -> list[str]:
        """Return names of currently running agents."""
        # Clean up finished tasks while we're at it
        finished = [
            name for name, task in self._active.items()
            if task.done()
        ]
        for name in finished:
            task = self._active.pop(name)
            try:
                self._results[name] = task.result()
            except Exception as exc:
                logger.error("Agent %s failed: %s", name, exc)

        return list(self._active.keys())

    def is_active(self, agent_type: str) -> bool:
        """Check if an agent of this type is currently running."""
        self.list_active()  # Trigger cleanup
        return any(
            name.startswith(agent_type)
            for name in self._active
        )

    async def spawn(
        self,
        agent_type: str,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> str | None:
        """Spawn a sub-agent by type.

        Dynamically imports the implementation class from the spec,
        instantiates it, and runs it as an asyncio task behind a
        semaphore (max 3 concurrent).

        Returns the agent instance name, or None if spawn was blocked.
        """
        spec = self._specs.get(agent_type)
        if not spec:
            logger.error("No spec found for agent type: %s", agent_type)
            return None

        # Don't spawn duplicates
        if self.is_active(agent_type):
            logger.info("Agent %s already active, skipping", agent_type)
            return None

        # Dynamic import
        module_path = spec.get("implementation", "")
        class_name = spec.get("class", "")
        if not module_path or not class_name:
            logger.error("Spec for %s missing implementation/class", agent_type)
            return None

        try:
            module = importlib.import_module(module_path)
            agent_class = getattr(module, class_name)
        except (ImportError, AttributeError) as exc:
            logger.error("Failed to import %s.%s: %s", module_path, class_name, exc)
            return None

        # Instantiate
        agent: SubAgentProtocol = agent_class()
        instance_name = f"{agent_type}-{int(time.time())}"

        # Subscribe to bus
        event_filter = set(spec.get("events", [])) or None
        bus.subscribe(instance_name, event_filter)

        # Spawn behind semaphore
        async def _run_agent() -> SubAgentResult:
            async with self._semaphore:
                start = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        agent.run(context, bus),
                        timeout=spec.get("max_runtime_seconds", 120),
                    )
                    result.duration_ms = (time.monotonic() - start) * 1000
                    return result
                except asyncio.TimeoutError:
                    logger.warning("Agent %s timed out", instance_name)
                    return SubAgentResult(
                        agent_name=instance_name,
                        agent_type=agent_type,
                        success=False,
                        data={},
                        errors=["Timed out"],
                        duration_ms=(time.monotonic() - start) * 1000,
                    )
                except Exception as exc:
                    logger.error("Agent %s crashed: %s", instance_name, exc)
                    return SubAgentResult(
                        agent_name=instance_name,
                        agent_type=agent_type,
                        success=False,
                        data={},
                        errors=[str(exc)],
                        duration_ms=(time.monotonic() - start) * 1000,
                    )
                finally:
                    bus.unsubscribe(instance_name)
                    await agent.shutdown()

        task = asyncio.create_task(_run_agent())
        self._active[instance_name] = task
        logger.info("Spawned agent: %s", instance_name)
        return instance_name

    async def kill(self, agent_name: str) -> bool:
        """Cancel a running agent task."""
        task = self._active.get(agent_name)
        if not task or task.done():
            return False
        task.cancel()
        self._active.pop(agent_name, None)
        logger.info("Killed agent: %s", agent_name)
        return True

    def get_result(self, agent_name: str) -> SubAgentResult | None:
        """Retrieve the result of a completed agent."""
        return self._results.get(agent_name)
