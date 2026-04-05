"""Agent007 sub-agent framework.

Provides a lightweight, Protocol-based agent system for spawning
autonomous financial sub-agents on the Pi 5. Designed for low memory
footprint with bounded queues and semaphore-limited concurrency.

Components:
    - base.py           — SubAgentProtocol, SubAgentResult, AgentMessage
    - bus.py            — AgentMessageBus, SharedContext
    - registry.py       — SubAgentRegistry (lifecycle management)
    - ollama_brain.py   — Ollama-driven spawn decision engine
    - specs/            — JSON sub-agent definitions
    - implementations/  — Concrete agent classes
"""

from agents.base import SubAgentProtocol, SubAgentResult, AgentMessage
from agents.bus import AgentMessageBus, SharedContext
from agents.registry import SubAgentRegistry
from agents.ollama_brain import OllamaBrain

__all__ = [
    "SubAgentProtocol",
    "SubAgentResult",
    "AgentMessage",
    "AgentMessageBus",
    "SharedContext",
    "SubAgentRegistry",
    "OllamaBrain",
]
