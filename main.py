"""Agent007 — HaloFinance Personal Finance Intelligence Agent.

Core orchestrator for the ShaneBrain financial intelligence system.
Runs on Pi 5 (100.67.120.6), coordinates Chase bank pulls, bill tracking,
401K monitoring, cash flow forecasting, and alert dispatch across the
ShaneBrain ecosystem.

Components:
    - tools/chase.py      — Chase bank account balance retrieval
    - tools/bills.py      — 31-bill tracker and status engine
    - tools/funds.py      — 401K NAV pulls (RFNGX, RICAX, RGAGX)
    - tools/forecast.py   — Cash flow forecasting via Ollama
    - tools/alerts.py     — SMS and N8N alert dispatch
    - webhooks/n8n_triggers.py    — N8N webhook integrations
    - dashboard/halofinance_panel.py — Mega Dashboard panel updates
"""

import asyncio
import logging
import os

from dotenv import load_dotenv

from tools.chase import get_account_balances
from tools.bills import get_bill_status, get_all_bills
from tools.funds import get_401k_nav
from tools.forecast import get_cash_flow_forecast, get_financial_snapshot
from tools.alerts import send_sms_alert, send_n8n_webhook, push_to_dashboard
from webhooks.n8n_triggers import register_webhooks
from dashboard.halofinance_panel import update_halofinance_panel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Agent007] %(levelname)s %(message)s",
)
logger = logging.getLogger("agent007")


async def main() -> None:
    """Main entry point for Agent007.

    Initializes all subsystems and starts the monitoring loop.
    """
    logger.info("Agent007 starting — HaloFinance Personal Finance Agent")
    logger.info("Pi 5: %s | N8N: %s", os.getenv("WEAVIATE_URL"), os.getenv("N8N_BASE_URL"))
    pass


if __name__ == "__main__":
    asyncio.run(main())
