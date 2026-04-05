"""Bill Tracker sub-agent for Agent007.

Sweeps all 31 bills, cross-references payment status, and escalates
overdue bills via SMS and N8N. Publishes updated bill data to the
message bus and shared context.
"""

import logging
import time
from datetime import datetime, timezone

from agents.base import AgentMessage, SubAgentResult
from agents.bus import AgentMessageBus, SharedContext
from tools import _get_session
from tools.bills import get_all_bills

logger = logging.getLogger("agent007.agent.bill_tracker")


class BillTrackerAgent:
    """Monitors all 31 bills — flags overdue, escalates via SMS."""

    name = "Bill Tracker"
    agent_type = "bill-tracker"
    status = "idle"

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        self.status = "running"
        start = time.monotonic()

        try:
            # get_all_bills() handles red-line alerts internally
            bills = await get_all_bills()

            # Update shared context
            await context.set("latest_bills", bills)

            # Publish to bus
            unpaid = [b for b in bills if not b.get("paid")]
            await bus.publish(AgentMessage(
                source=self.name,
                event="bills_updated",
                payload={
                    "total": len(bills),
                    "unpaid": len(unpaid),
                    "unpaid_names": [b.get("name") for b in unpaid],
                },
            ))

            self.status = "completed"
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=True,
                data={
                    "bills_checked": len(bills),
                    "unpaid_count": len(unpaid),
                },
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            self.status = "error"
            logger.error("Bill tracker failed: %s", exc)
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
