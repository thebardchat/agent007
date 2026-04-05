"""HaloFinance panel for the Mega Dashboard.

Manages the HaloFinance panel on the Mega Dashboard at
http://100.67.120.6:8300. Pushes real-time financial data including
Chase balances, bill status, 401K NAVs, cash flow forecasts, and
active alerts.

Network targets:
    - Mega Dashboard (MEGA_DASHBOARD_URL) at http://100.67.120.6:8300
    - Weaviate (WEAVIATE_URL) for reading latest financial data
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, query_weaviate

load_dotenv()

logger = logging.getLogger("agent007.dashboard")

MEGA_DASHBOARD_URL = os.getenv("MEGA_DASHBOARD_URL", "")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")


async def _push_panel(panel_name: str, data: Any) -> dict[str, Any]:
    """Shared helper to POST data to a dashboard sub-panel."""
    timestamp = datetime.now(timezone.utc).isoformat()
    url = f"{MEGA_DASHBOARD_URL}/api/panels/halofinance/{panel_name}"

    session = await _get_session()
    try:
        async with session.post(
            url,
            json={"panel": panel_name, "data": data, "updated_at": timestamp},
        ) as resp:
            resp.raise_for_status()
    except aiohttp.ClientError as exc:
        logger.error("Dashboard panel '%s' push failed: %s", panel_name, exc)
        raise

    logger.info("Dashboard panel updated: %s", panel_name)
    return {"updated": True, "panel": panel_name, "timestamp": timestamp}


async def update_halofinance_panel() -> dict[str, Any]:
    """Push a full refresh to the HaloFinance panel on Mega Dashboard.

    Pulls latest data from Weaviate (balances, bills, funds, forecasts)
    and pushes a consolidated update to the dashboard.

    Returns:
        dict with keys: updated (bool), panels_refreshed (list),
        timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard or Weaviate is unreachable.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    panels_refreshed = []

    # Pull latest from Weaviate and push each panel sequentially
    # Sequential to avoid overwhelming the dashboard with concurrent POSTs

    # Balances
    try:
        balances = await query_weaviate("FinanceSnapshots", "latest chase balance")
        if balances:
            await push_balance_panel(balances[0])
            panels_refreshed.append("balances")
    except aiohttp.ClientError:
        logger.warning("Skipped balances panel — data unavailable")

    # Bills
    try:
        bills = await query_weaviate("BillTracker", "all bills current status")
        if bills:
            await push_bills_panel(bills)
            panels_refreshed.append("bills")
    except aiohttp.ClientError:
        logger.warning("Skipped bills panel — data unavailable")

    # Funds
    try:
        funds = await query_weaviate("FundNAVHistory", "latest NAV all tickers")
        if funds:
            await push_funds_panel(funds)
            panels_refreshed.append("funds")
    except aiohttp.ClientError:
        logger.warning("Skipped funds panel — data unavailable")

    # Forecast
    try:
        forecasts = await query_weaviate("CashFlowForecasts", "latest forecast")
        if forecasts:
            await push_forecast_panel(forecasts[0])
            panels_refreshed.append("forecast")
    except aiohttp.ClientError:
        logger.warning("Skipped forecast panel — data unavailable")

    logger.info("Dashboard refresh: %d/%d panels updated", len(panels_refreshed), 4)

    return {
        "updated": True,
        "panels_refreshed": panels_refreshed,
        "timestamp": timestamp,
    }


async def push_balance_panel(data: dict[str, Any]) -> dict[str, Any]:
    """Update the balances sub-panel on the dashboard.

    Args:
        data: dict with checking and savings balance data.

    Returns:
        dict with keys: updated (bool), panel ('balances'), timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard is unreachable.
    """
    return await _push_panel("balances", data)


async def push_bills_panel(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Update the bills sub-panel on the dashboard.

    Args:
        data: List of bill status dicts from get_all_bills().

    Returns:
        dict with keys: updated (bool), panel ('bills'), timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard is unreachable.
    """
    return await _push_panel("bills", data)


async def push_funds_panel(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Update the 401K funds sub-panel on the dashboard.

    Args:
        data: List of fund NAV dicts from get_401k_nav().

    Returns:
        dict with keys: updated (bool), panel ('funds'), timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard is unreachable.
    """
    return await _push_panel("funds", data)


async def push_forecast_panel(data: dict[str, Any]) -> dict[str, Any]:
    """Update the cash flow forecast sub-panel on the dashboard.

    Args:
        data: Forecast data dict from get_cash_flow_forecast().

    Returns:
        dict with keys: updated (bool), panel ('forecast'), timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard is unreachable.
    """
    return await _push_panel("forecast", data)
