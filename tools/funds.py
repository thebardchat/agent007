"""401K fund NAV tracker for Agent007.

Monitors RFNGX, RICAX, and RGAGX via Yahoo Finance. Pulls daily after
4PM ET when NAV updates. Stores history to Weaviate FundNAVHistory
collection. Triggers SMS alert if any fund drops > 5% in one day.

Network targets:
    - Yahoo Finance via corsproxy.io (https://query2.finance.yahoo.com/v7/finance/quote)
    - Weaviate (WEAVIATE_URL) for NAV history persistence
"""

import os
from typing import Any

import aiohttp
from dotenv import load_dotenv

load_dotenv()

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")
YAHOO_FINANCE_ENDPOINT = "https://query2.finance.yahoo.com/v7/finance/quote"
FUND_TICKERS = ["RFNGX", "RICAX", "RGAGX"]


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
    pass
