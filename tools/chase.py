"""Chase bank account integration for Agent007.

Pulls checking and savings balances from Chase via Google Apps Script → N8N
webhook pipeline. Data is stored to Weaviate FinanceSnapshots collection.

Pull frequency: Every 30 minutes via N8N.
Alert threshold: Balance drops below $500 triggers immediate SMS.

Network targets:
    - Google Apps Script (CHASE_SCRIPT_URL)
    - N8N (N8N_BASE_URL)
    - Weaviate (WEAVIATE_URL) for persistence
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, mask_financial, save_to_weaviate
from tools.alerts import send_sms_alert

load_dotenv()

logger = logging.getLogger("agent007.chase")

CHASE_SCRIPT_URL = os.getenv("CHASE_SCRIPT_URL", "")

# Red line threshold — auto-alert, no confirmation needed
BALANCE_ALERT_THRESHOLD = 500.0


async def get_account_balances() -> dict[str, Any]:
    """Retrieve current Chase checking and savings balances.

    Calls the Google Apps Script endpoint that provides Chase data,
    forwarded through the N8N webhook pipeline.

    Returns:
        dict with keys 'checking' and 'savings', each containing
        current balance as float and last_updated timestamp.

    Raises:
        aiohttp.ClientError: If the Chase script endpoint is unreachable.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    session = await _get_session()

    try:
        async with session.get(CHASE_SCRIPT_URL) as resp:
            resp.raise_for_status()
            raw = await resp.json()
    except aiohttp.ClientError as exc:
        logger.error("Chase balance pull failed: %s", exc)
        raise

    checking = float(raw.get("checking", 0.0))
    savings = float(raw.get("savings", 0.0))

    result = {
        "checking": {"balance": checking, "last_updated": timestamp},
        "savings": {"balance": savings, "last_updated": timestamp},
    }

    # Log masked — never expose exact balances
    logger.info(
        "Balance check: checking=%s savings=%s",
        mask_financial(checking), mask_financial(savings),
    )

    # Red line: balance < $500 → SMS immediately
    if checking < BALANCE_ALERT_THRESHOLD:
        await send_sms_alert(
            f"LOW BALANCE ALERT: Checking below ${int(BALANCE_ALERT_THRESHOLD)}. Act now."
        )
    if savings < BALANCE_ALERT_THRESHOLD:
        await send_sms_alert(
            f"LOW BALANCE ALERT: Savings below ${int(BALANCE_ALERT_THRESHOLD)}. Act now."
        )

    # Persist snapshot to Weaviate
    await save_to_weaviate("FinanceSnapshots", {
        "source": "chase",
        "checking": checking,
        "savings": savings,
        "timestamp": timestamp,
    })

    return result
