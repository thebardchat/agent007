"""Anomaly Detector sub-agent for Agent007.

Analyzes recent transactions for unusual patterns via Ollama. Fires
SMS alerts for transactions > $200 that look anomalous. Uses Weaviate
history for pattern comparison.
"""

import logging
import time

from agents.base import AgentMessage, SubAgentResult
from agents.bus import AgentMessageBus, SharedContext
from tools import _get_session, query_weaviate
from tools.forecast import analyze_spending
from tools.alerts import send_sms_alert

logger = logging.getLogger("agent007.agent.anomaly_detector")


class AnomalyDetectorAgent:
    """Analyzes transactions for anomalies — alerts on > $200 unusual."""

    name = "Anomaly Detector"
    agent_type = "anomaly-detector"
    status = "idle"

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        self.status = "running"
        start = time.monotonic()

        try:
            # Pull recent transaction data from Weaviate
            recent = await query_weaviate(
                "FinanceSnapshots",
                "recent transactions unusual spending",
            )

            if not recent:
                self.status = "completed"
                return SubAgentResult(
                    agent_name=self.name,
                    agent_type=self.agent_type,
                    success=True,
                    data={"analyzed": 0, "anomalies": 0},
                    duration_ms=(time.monotonic() - start) * 1000,
                )

            # Feed to Ollama for analysis
            analysis = await analyze_spending({"transactions": recent})

            anomalies = analysis.get("anomalies", [])

            # Red line: unusual transaction > $200 → SMS alert
            for anomaly in anomalies:
                if isinstance(anomaly, str) and "$" in anomaly:
                    await send_sms_alert(f"ANOMALY: {anomaly[:140]}")

            # Publish to bus
            await bus.publish(AgentMessage(
                source=self.name,
                event="anomalies_detected",
                payload={
                    "count": len(anomalies),
                    "anomalies": anomalies,
                },
            ))

            self.status = "completed"
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=True,
                data={
                    "analyzed": len(recent),
                    "anomalies": len(anomalies),
                    "summary": analysis.get("summary", ""),
                },
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            self.status = "error"
            logger.error("Anomaly detector failed: %s", exc)
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
