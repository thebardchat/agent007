"""Cash Flow Forecaster sub-agent for Agent007.

Generates 30/60/90 day cash flow projections via Ollama. Checks for
negative balance within 14 days and fires dashboard alerts. Pushes
forecast data to shared context.
"""

import logging
import time

from agents.base import AgentMessage, SubAgentResult
from agents.bus import AgentMessageBus, SharedContext
from tools import _get_session
from tools.forecast import get_cash_flow_forecast
from tools.alerts import push_to_dashboard

logger = logging.getLogger("agent007.agent.cash_flow_forecaster")


class CashFlowForecasterAgent:
    """Generates cash flow projections — alerts on negative balance risk."""

    name = "Cash Flow Forecaster"
    agent_type = "cash-flow-forecaster"
    status = "idle"

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        self.status = "running"
        start = time.monotonic()

        try:
            # get_cash_flow_forecast() handles red-line dashboard alerts internally
            forecast = await get_cash_flow_forecast(30)

            # Update shared context
            await context.set("latest_forecast", forecast)

            # Push to dashboard
            await push_to_dashboard("forecast", forecast)

            # Publish to bus
            risk_flags = forecast.get("risk_flags", [])
            await bus.publish(AgentMessage(
                source=self.name,
                event="forecast_generated",
                payload={
                    "forecast_days": forecast.get("forecast_days", 30),
                    "risk_flag_count": len(risk_flags),
                    "confidence": forecast.get("confidence", 0.0),
                },
            ))

            self.status = "completed"
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=True,
                data={
                    "forecast_days": 30,
                    "risk_flags": risk_flags,
                    "confidence": forecast.get("confidence", 0.0),
                },
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            self.status = "error"
            logger.error("Cash flow forecaster failed: %s", exc)
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
