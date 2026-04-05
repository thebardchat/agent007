"""Agent007 — HaloFinance Personal Finance Intelligence Agent.

Core orchestrator for the ShaneBrain financial intelligence system.
Runs on Pi 5 (100.67.120.6), coordinates Chase bank pulls, bill tracking,
401K monitoring, cash flow forecasting, and alert dispatch across the
ShaneBrain ecosystem.

Three concurrent async loops:
    1. monitoring_loop — schedule-based data pulls (30min/daily/weekly/monthly)
    2. agent_spawn_loop — Ollama-driven sub-agent spawning every 5 min
    3. bus_processor — inter-agent message routing and cascading triggers

Components:
    - tools/       — Financial data tools (Chase, bills, funds, forecast, alerts)
    - agents/      — Sub-agent framework (registry, bus, brain, implementations)
    - webhooks/    — N8N webhook integrations
    - dashboard/   — Mega Dashboard panel updates
"""

import asyncio
import logging
import os
import signal
from datetime import datetime, timezone

from dotenv import load_dotenv

from tools import close_session
from tools.chase import get_account_balances
from tools.bills import get_all_bills
from tools.funds import get_401k_nav, FUND_TICKERS
from tools.forecast import get_financial_snapshot
from tools.alerts import push_to_dashboard
from webhooks.n8n_triggers import register_webhooks
from dashboard.halofinance_panel import update_halofinance_panel
from agents.bus import AgentMessageBus, SharedContext
from agents.registry import SubAgentRegistry
from agents.ollama_brain import OllamaBrain

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Agent007] %(levelname)s %(message)s",
)
logger = logging.getLogger("agent007")

# Intervals (seconds)
MONITOR_INTERVAL = 60        # Check schedule every 60s
BALANCE_INTERVAL = 1800      # 30 minutes
SPAWN_INTERVAL = 300         # 5 minutes
BUS_DRAIN_INTERVAL = 10      # 10 seconds


async def monitoring_loop(
    context: SharedContext,
    bus: AgentMessageBus,
    registry: SubAgentRegistry,
) -> None:
    """Schedule-based monitoring loop.

    Checks time-based triggers every 60 seconds and spawns
    the appropriate sub-agents.

    Schedule:
        - Every 30 min → balance-monitor
        - Daily 8AM CT (13:00 UTC) → bill-tracker
        - Daily 4:30PM ET (21:30 UTC) → fund-watcher
        - Weekly Sunday → cash-flow-forecaster
        - Monthly 1st → full financial snapshot
    """
    last_balance_check = 0.0
    last_bill_sweep_day = -1
    last_nav_pull_day = -1
    last_forecast_weekday = -1
    last_snapshot_month = -1

    while True:
        try:
            now = datetime.now(timezone.utc)
            loop_time = asyncio.get_event_loop().time()

            # Every 30 min → balance-monitor
            if loop_time - last_balance_check >= BALANCE_INTERVAL:
                await registry.spawn("balance-monitor", context, bus)
                last_balance_check = loop_time

            # Daily 8AM CT = 13:00 UTC → bill-tracker
            if now.hour == 13 and now.day != last_bill_sweep_day:
                await registry.spawn("bill-tracker", context, bus)
                last_bill_sweep_day = now.day

            # Daily 4:30PM ET = ~21:30 UTC → fund-watcher
            if now.hour == 21 and now.minute >= 30 and now.day != last_nav_pull_day:
                await registry.spawn("fund-watcher", context, bus)
                last_nav_pull_day = now.day

            # Weekly Sunday → cash-flow-forecaster
            if now.weekday() == 6 and now.weekday() != last_forecast_weekday:
                await registry.spawn("cash-flow-forecaster", context, bus)
                last_forecast_weekday = now.weekday()

            # Monthly 1st → full financial snapshot
            if now.day == 1 and now.month != last_snapshot_month:
                logger.info("Monthly snapshot — generating full financial picture")
                try:
                    snapshot = await get_financial_snapshot()
                    await context.set("latest_snapshot", snapshot)
                except Exception as exc:
                    logger.error("Monthly snapshot failed: %s", exc)
                last_snapshot_month = now.month

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Monitoring loop error: %s", exc)

        await asyncio.sleep(MONITOR_INTERVAL)


async def agent_spawn_loop(
    brain: OllamaBrain,
    registry: SubAgentRegistry,
    context: SharedContext,
    bus: AgentMessageBus,
) -> None:
    """Ollama-driven sub-agent spawning loop.

    Every 5 minutes, asks the Ollama brain which agents should run
    based on current financial state. Spawns any that aren't already active.
    """
    while True:
        try:
            recommended = await brain.evaluate(context)

            for agent_type in recommended:
                if not registry.is_active(agent_type):
                    spawned = await registry.spawn(agent_type, context, bus)
                    if spawned:
                        logger.info("Brain spawned: %s", spawned)

            active = registry.list_active()
            if active:
                logger.info("Active agents: %s", active)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Spawn loop error: %s", exc)

        await asyncio.sleep(SPAWN_INTERVAL)


async def bus_processor(
    bus: AgentMessageBus,
    context: SharedContext,
) -> None:
    """Drains the message bus and routes agent results.

    Handles inter-agent coordination — e.g. anomaly-detector results
    may trigger cash-flow-forecaster, balance updates push to dashboard.
    """
    while True:
        try:
            messages = await bus.drain()

            for msg in messages:
                logger.info(
                    "Bus: %s → %s (event=%s)",
                    msg.source, msg.target or "broadcast", msg.event,
                )

                # Route based on event type
                if msg.event == "balances_updated":
                    try:
                        await update_halofinance_panel()
                    except Exception as exc:
                        logger.warning("Dashboard update failed: %s", exc)

                elif msg.event == "bills_updated":
                    unpaid = msg.payload.get("unpaid", 0)
                    if unpaid > 0:
                        await push_to_dashboard("bills", msg.payload)

                elif msg.event == "anomalies_detected":
                    count = msg.payload.get("count", 0)
                    if count > 0:
                        logger.warning("Anomalies detected: %d", count)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Bus processor error: %s", exc)

        await asyncio.sleep(BUS_DRAIN_INTERVAL)


async def seed_context(context: SharedContext) -> None:
    """Pull initial data to seed shared context on startup."""
    logger.info("Seeding initial context...")

    try:
        balances = await get_account_balances()
        await context.set("latest_balances", balances)
    except Exception as exc:
        logger.warning("Initial balance pull failed: %s", exc)

    try:
        bills = await get_all_bills()
        await context.set("latest_bills", bills)
    except Exception as exc:
        logger.warning("Initial bill sweep failed: %s", exc)

    try:
        navs = {}
        for ticker in FUND_TICKERS:
            navs[ticker] = await get_401k_nav(ticker)
        await context.set("latest_navs", navs)
    except Exception as exc:
        logger.warning("Initial NAV pull failed: %s", exc)

    logger.info("Context seeded")


async def main() -> None:
    """Main entry point for Agent007.

    Initializes all subsystems, seeds context, and runs three
    concurrent loops: monitoring, agent spawning, and bus processing.
    Handles SIGINT/SIGTERM for graceful shutdown.
    """
    logger.info("Agent007 starting — HaloFinance Personal Finance Agent")
    logger.info(
        "Pi 5: %s | N8N: %s | Ollama: %s",
        os.getenv("WEAVIATE_URL"),
        os.getenv("N8N_BASE_URL"),
        os.getenv("OLLAMA_URL"),
    )

    # Initialize subsystems
    bus = AgentMessageBus()
    context = SharedContext()
    registry = SubAgentRegistry()
    brain = OllamaBrain()

    # Load agent specs
    await registry.load_specs()

    # Register N8N webhooks
    try:
        result = await register_webhooks()
        logger.info("Webhooks registered: %d", result.get("count", 0))
    except Exception as exc:
        logger.warning("Webhook registration failed: %s", exc)

    # Seed initial context from live data
    await seed_context(context)

    # Start concurrent loops
    tasks = [
        asyncio.create_task(monitoring_loop(context, bus, registry)),
        asyncio.create_task(agent_spawn_loop(brain, registry, context, bus)),
        asyncio.create_task(bus_processor(bus, context)),
    ]

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal() -> None:
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    # Wait for shutdown signal
    await shutdown_event.wait()

    # Cancel all tasks
    logger.info("Shutting down Agent007...")
    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    await close_session()
    logger.info("Agent007 stopped")


if __name__ == "__main__":
    asyncio.run(main())
