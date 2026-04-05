"""Balance Monitor sub-agent for Agent007.

Checks Chase checking/savings balances, fires red-line SMS alerts
if below $500, and pushes updates to the dashboard and shared context.
"""

import logging
import time

from agents.base import AgentMessage, SubAgentResult
from agents.bus import AgentMessageBus, SharedContext
from tools import _get_session
from tools.chase import get_account_balances
from tools.alerts import push_to_dashboard

logger = logging.getLogger("agent007.agent.balance_monitor")


class BalanceMonitorAgent:
    """Monitors Chase balances — alerts on < $500, pushes to dashboard."""

    name = "Balance Monitor"
    agent_type = "balance-monitor"
    status = "idle"

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        self.status = "running"
        start = time.monotonic()

        try:
            # get_account_balances() handles red-line SMS alerts internally
            balances = await get_account_balances()

            # Update shared context
            await context.set("latest_balances", balances)

            # Push to dashboard
            await push_to_dashboard("balances", balances)

            # Publish to bus
            await bus.publish(AgentMessage(
                source=self.name,
                event="balances_updated",
                payload={"status": "updated"},
            ))

            self.status = "completed"
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=True,
                data={"accounts_checked": 2},
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            self.status = "error"
            logger.error("Balance monitor failed: %s", exc)
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=False,
                data={},
                errors=[str(exc)],
                duration_ms=(time.monotonic() - start) * 1000,
            )

    async def health_check(self) -> bool:
        try:
            session = await _get_session()
            return not session.closed
        except Exception:
            return False

    async def shutdown(self) -> None:
        self.status = "shutdown"
