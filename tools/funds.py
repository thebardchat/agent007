"""401K fund NAV tracker for Agent007.

Monitors RFNGX, RICAX, and RGAGX via Yahoo Finance. Pulls daily after
4PM ET when NAV updates. Stores history to Weaviate FundNAVHistory
collection. Triggers SMS alert if any fund drops > 5% in one day.

Network targets:
    - Yahoo Finance (https://query2.finance.yahoo.com/v7/finance/quote)
    - Weaviate (WEAVIATE_URL) for NAV history persistence
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, save_to_weaviate
from tools.alerts import send_sms_alert

load_dotenv()

logger = logging.getLogger("agent007.funds")

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")
YAHOO_FINANCE_ENDPOINT = "https://query2.finance.yahoo.com/v7/finance/quote"
FUND_TICKERS = ["RFNGX", "RICAX", "RGAGX"]

# Red line: > 5% single-day drop
DROP_ALERT_THRESHOLD = -5.0


async def get_401k_nav(ticker: str) -> dict[str, Any]:
    """Fetch the current NAV for a 401K fund ticker.

    Args:
        ticker: Fund ticker symbol. Must be one of RFNGX, RICAX, RGAGX.

    Returns:
        dict with keys: ticker, nav (float), previous_close (float),
        change_percent (float), timestamp.

    Raises:
        ValueError: If ticker is not in the allowed list.
        aiohttp.ClientError: If Yahoo Finance endpoint is unreachable.
    """
    if ticker not in FUND_TICKERS:
        raise ValueError(
            f"Invalid ticker '{ticker}'. Must be one of: {', '.join(FUND_TICKERS)}"
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    session = await _get_session()

    # Server-side Pi call — no corsproxy needed
    try:
        async with session.get(
            YAHOO_FINANCE_ENDPOINT,
            params={"symbols": ticker},
            headers={"User-Agent": "Agent007/1.0"},
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
    except aiohttp.ClientError as exc:
        logger.error("Yahoo Finance pull failed for %s: %s", ticker, exc)
        raise

    # Parse quote data
    quotes = body.get("quoteResponse", {}).get("result", [])
    if not quotes:
        logger.warning("No quote data returned for %s", ticker)
        return {
            "ticker": ticker,
            "nav": 0.0,
            "previous_close": 0.0,
            "change_percent": 0.0,
            "timestamp": timestamp,
        }

    quote = quotes[0]
    nav = float(quote.get("regularMarketPrice", 0.0))
    previous_close = float(quote.get("regularMarketPreviousClose", 0.0))

    # Calculate change percentage
    if previous_close > 0:
        change_percent = ((nav - previous_close) / previous_close) * 100
    else:
        change_percent = 0.0

    result = {
        "ticker": ticker,
        "nav": nav,
        "previous_close": previous_close,
        "change_percent": round(change_percent, 2),
        "timestamp": timestamp,
    }

    logger.info("NAV update: %s change=%.2f%%", ticker, change_percent)

    # Red line: > 5% drop in one day → SMS alert
    if change_percent <= DROP_ALERT_THRESHOLD:
        await send_sms_alert(
            f"401K ALERT: {ticker} dropped {change_percent:.1f}% today! "
            f"NAV: ${nav:.2f}"
        )

    # Persist to Weaviate
    await save_to_weaviate("FundNAVHistory", result)

    return result
