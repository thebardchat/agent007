"""Inter-agent communication for Agent007.

AgentMessageBus — bounded async pub/sub for agent-to-agent messages.
SharedContext — locked dict for cross-agent shared financial state.

All queues are bounded to prevent RAM blowout on the Pi 5.
"""

import asyncio
import logging
from typing import Any

from agents.base import AgentMessage

logger = logging.getLogger("agent007.bus")

# Pi 5 RAM constraints — keep queues small
BUS_MAX_SIZE = 50
AGENT_QUEUE_MAX_SIZE = 10


class AgentMessageBus:
    """Lightweight async message bus for inter-agent communication.

    Bounded queues prevent memory blowout. Messages are delivered
    to targeted agents or broadcast to all subscribers.
    """

    def __init__(self) -> None:
        self._global_queue: asyncio.Queue[AgentMessage] = asyncio.Queue(
            maxsize=BUS_MAX_SIZE,
        )
        self._agent_queues: dict[str, asyncio.Queue[AgentMessage]] = {}
        self._subscriptions: dict[str, set[str] | None] = {}

    def subscribe(
        self,
        agent_name: str,
        event_filter: set[str] | None = None,
    ) -> None:
        """Register an agent to receive messages.

        Args:
            agent_name: Unique agent identifier.
            event_filter: Set of event types to receive. None = all events.
        """
        self._agent_queues[agent_name] = asyncio.Queue(
            maxsize=AGENT_QUEUE_MAX_SIZE,
        )
        self._subscriptions[agent_name] = event_filter
        logger.info("Bus: %s subscribed (filter=%s)", agent_name, event_filter)

    def unsubscribe(self, agent_name: str) -> None:
        """Remove an agent from the bus."""
        self._agent_queues.pop(agent_name, None)
        self._subscriptions.pop(agent_name, None)

    async def publish(self, message: AgentMessage) -> None:
        """Publish a message to the bus.

        Targeted messages go to a specific agent. Broadcasts go to all
        subscribers whose event filter matches (or who accept all events).
        """
        # Always put on global queue for the bus processor
        try:
            self._global_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning("Bus global queue full, dropping oldest message")
            try:
                self._global_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._global_queue.put_nowait(message)

        # Route to targeted agent or broadcast
        if message.target:
            queue = self._agent_queues.get(message.target)
            if queue:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning("Queue full for %s, dropping", message.target)
        else:
            # Broadcast to all matching subscribers
            for name, event_filter in self._subscriptions.items():
                if name == message.source:
                    continue  # Don't echo back to sender
                if event_filter is not None and message.event not in event_filter:
                    continue
                queue = self._agent_queues.get(name)
                if queue:
                    try:
                        queue.put_nowait(message)
                    except asyncio.QueueFull:
                        logger.warning("Queue full for %s, dropping", name)

    async def receive(self, agent_name: str, timeout: float = 5.0) -> AgentMessage | None:
        """Receive the next message for a specific agent.

        Returns None if no message arrives within timeout.
        """
        queue = self._agent_queues.get(agent_name)
        if not queue:
            return None
        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    async def drain(self) -> list[AgentMessage]:
        """Pull all pending messages from the global queue.

        Used by the bus processor in main.py to handle routing,
        dashboard updates, and cascading triggers.
        """
        messages = []
        while not self._global_queue.empty():
            try:
                messages.append(self._global_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return messages


class SharedContext:
    """Thread-safe shared state between parent and all sub-agents.

    Wraps a dict with asyncio.Lock for safe concurrent access.
    Data stays in RAM; large payloads should go to Weaviate instead.
    """

    def __init__(self) -> None:
        self._data: dict[str, Any] = {
            "latest_balances": None,
            "latest_bills": None,
            "latest_navs": None,
            "latest_forecast": None,
            "active_alerts": [],
        }
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any:
        """Read a value from shared context."""
        async with self._lock:
            return self._data.get(key)

    async def set(self, key: str, value: Any) -> None:
        """Write a value to shared context."""
        async with self._lock:
            self._data[key] = value

    async def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the entire context.

        Used by OllamaBrain to evaluate financial state.
        """
        async with self._lock:
            return dict(self._data)
