"""Fund Watcher sub-agent for Agent007.

Pulls NAV for all three 401K funds (RFNGX, RICAX, RGAGX) from Yahoo
Finance. Fires SMS alert on > 5% single-day drops. Pushes to dashboard
and shared context.
"""

import logging
import time

from agents.base import AgentMessage, SubAgentResult
from agents.bus import AgentMessageBus, SharedContext
from tools import _get_session
from tools.funds import get_401k_nav, FUND_TICKERS
from tools.alerts import push_to_dashboard

logger = logging.getLogger("agent007.agent.fund_watcher")


class FundWatcherAgent:
    """Monitors 401K fund NAVs — alerts on > 5% daily drops."""

    name = "Fund Watcher"
    agent_type = "fund-watcher"
    status = "idle"

    async def run(
        self,
        context: SharedContext,
        bus: AgentMessageBus,
    ) -> SubAgentResult:
        self.status = "running"
        start = time.monotonic()

        try:
            navs = {}
            errors = []

            for ticker in FUND_TICKERS:
                try:
                    # get_401k_nav() handles red-line alerts internally
                    nav_data = await get_401k_nav(ticker)
                    navs[ticker] = nav_data
                except Exception as exc:
                    errors.append(f"{ticker}: {exc}")
                    logger.warning("NAV pull failed for %s: %s", ticker, exc)

            # Update shared context
            await context.set("latest_navs", navs)

            # Push to dashboard
            await push_to_dashboard("funds", list(navs.values()))

            # Publish to bus
            await bus.publish(AgentMessage(
                source=self.name,
                event="navs_updated",
                payload={
                    "tickers_pulled": list(navs.keys()),
                    "errors": errors,
                },
            ))

            self.status = "completed"
            return SubAgentResult(
                agent_name=self.name,
                agent_type=self.agent_type,
                success=len(errors) == 0,
                data={
                    "tickers_pulled": len(navs),
                    "navs": {t: n.get("nav", 0) for t, n in navs.items()},
                },
                errors=errors,
                duration_ms=(time.monotonic() - start) * 1000,
            )
        except Exception as exc:
            self.status = "error"
            logger.error("Fund watcher failed: %s", exc)
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
