"""Ollama-driven decision engine for Agent007.

Evaluates current financial state and decides which sub-agents to spawn.
Uses llama3.2:1b locally on the Pi 5 for intelligent decisions, with
deterministic rule-based fallback when the LLM returns garbage.

The brain enhances spawn decisions but never gates them — rules always work.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from agents.bus import SharedContext
from tools import _get_session

load_dotenv()

logger = logging.getLogger("agent007.brain")

OLLAMA_URL = os.getenv("OLLAMA_URL", "")
OLLAMA_MODEL = "llama3.2:1b"

AVAILABLE_AGENT_TYPES = [
    "bill-tracker",
    "balance-monitor",
    "fund-watcher",
    "cash-flow-forecaster",
    "anomaly-detector",
]


class OllamaBrain:
    """Decision engine that determines which sub-agents to spawn.

    Two-tier strategy:
    1. Ask Ollama for intelligent, context-aware decisions
    2. Fall back to deterministic rules if Ollama fails or returns garbage
    """

    async def evaluate(self, context: SharedContext) -> list[str]:
        """Evaluate financial state and return agent types to spawn.

        Args:
            context: Current shared financial state.

        Returns:
            List of agent type strings to spawn.
        """
        snapshot = await context.snapshot()

        # Try Ollama first
        try:
            llm_agents = await self._ask_ollama(snapshot)
            if llm_agents:
                logger.info("Ollama recommends: %s", llm_agents)
                return llm_agents
        except (aiohttp.ClientError, ValueError) as exc:
            logger.warning("Ollama decision failed, using rules: %s", exc)

        # Fall back to deterministic rules
        return self._rule_based_evaluation(snapshot)

    async def _ask_ollama(self, snapshot: dict[str, Any]) -> list[str]:
        """Ask Ollama which agents should run given the financial state."""
        # Build a concise summary — 1B model needs short prompts
        summary = self._summarize_state(snapshot)

        prompt = (
            "You are a financial monitoring system.\n"
            f"Current state:\n{summary}\n\n"
            f"Available agents: {', '.join(AVAILABLE_AGENT_TYPES)}\n\n"
            "Which agents should run right now? Respond with a JSON array "
            "of agent type strings only. Example: [\"bill-tracker\", \"balance-monitor\"]\n"
            "If none needed, respond: []\n\n"
            "JSON response:"
        )

        session = await _get_session()
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()

        raw = body.get("response", "").strip()

        # Parse JSON array from response
        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            return []

        agents = json.loads(match.group())
        # Validate — only return known types
        return [a for a in agents if a in AVAILABLE_AGENT_TYPES]

    def _rule_based_evaluation(self, snapshot: dict[str, Any]) -> list[str]:
        """Deterministic fallback when Ollama is unavailable or unreliable."""
        agents: list[str] = []
        now = datetime.now(timezone.utc)

        # Balance monitor — always run
        agents.append("balance-monitor")

        # Bill tracker — if any bills data shows upcoming dues
        bills = snapshot.get("latest_bills")
        if bills:
            for bill in (bills if isinstance(bills, list) else []):
                due_str = bill.get("due_date", "")
                if not due_str or bill.get("paid"):
                    continue
                try:
                    due = datetime.fromisoformat(due_str)
                    if due.tzinfo is None:
                        due = due.replace(tzinfo=timezone.utc)
                    days_until = (due - now).days
                    if 0 <= days_until <= 3:
                        agents.append("bill-tracker")
                        break
                except (ValueError, TypeError):
                    continue
        else:
            # No bill data yet — run tracker to populate
            agents.append("bill-tracker")

        # Fund watcher — after 4PM ET (21:00 UTC roughly)
        if now.hour >= 21:
            agents.append("fund-watcher")

        # Anomaly detector — if balance changed significantly
        balances = snapshot.get("latest_balances")
        if balances and isinstance(balances, dict):
            checking = balances.get("checking", {})
            if isinstance(checking, dict):
                balance = checking.get("balance", 0)
                if isinstance(balance, (int, float)) and balance < 500:
                    agents.append("anomaly-detector")

        return list(set(agents))  # Deduplicate

    def _summarize_state(self, snapshot: dict[str, Any]) -> str:
        """Build a concise text summary of financial state for the LLM."""
        lines = []

        balances = snapshot.get("latest_balances")
        if balances and isinstance(balances, dict):
            lines.append(f"Balances: available")
        else:
            lines.append("Balances: unknown")

        bills = snapshot.get("latest_bills")
        if bills and isinstance(bills, list):
            unpaid = sum(1 for b in bills if not b.get("paid"))
            lines.append(f"Bills: {len(bills)} total, {unpaid} unpaid")
        else:
            lines.append("Bills: no data")

        navs = snapshot.get("latest_navs")
        if navs:
            lines.append("401K NAVs: available")
        else:
            lines.append("401K NAVs: not yet pulled")

        forecast = snapshot.get("latest_forecast")
        if forecast:
            flags = forecast.get("risk_flags", []) if isinstance(forecast, dict) else []
            lines.append(f"Forecast: available, {len(flags)} risk flags")
        else:
            lines.append("Forecast: not generated")

        now = datetime.now(timezone.utc)
        lines.append(f"Time: {now.strftime('%H:%M UTC')} ({now.strftime('%A')})")

        return "\n".join(lines)
