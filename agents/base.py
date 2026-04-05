"""Sub-agent contracts for Agent007.

Defines the Protocol-based interface that all sub-agents must satisfy,
plus shared data types for results and inter-agent messages.

Uses typing.Protocol instead of ABC — zero runtime overhead, structural
typing means any object with the right methods works. No inheritance needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.bus import AgentMessageBus, SharedContext


@dataclass
class SubAgentResult:
    """Standard result returned by every sub-agent run."""

    agent_name: str
    agent_type: str
    success: bool
    data: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    duration_ms: float = 0.0


@dataclass
class AgentMessage:
    """Message passed between agents via the message bus."""

    source: str
    event: str
    payload: dict[str, Any]
    target: str | None = None  # None = broadcast to all
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SubAgentProtocol(Protocol):
    """Contract every sub-agent must satisfy.

    Structural typing — implement these attrs/methods on any class
    and it qualifies. No need to inherit from anything.
    """

    name: str
    agent_type: str
    status: str

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        """Execute the agent's primary task.

        Args:
            context: Shared financial state (locked dict).
            bus: Message bus for inter-agent communication.

        Returns:
            SubAgentResult with success/failure and data.
        """
        ...

    async def health_check(self) -> bool:
        """Return True if the agent's dependencies are reachable."""
        ...

    async def shutdown(self) -> None:
        """Graceful cleanup — close sessions, persist state."""
        ...
