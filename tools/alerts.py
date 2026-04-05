"""Alert dispatch system for Agent007.

Handles SMS alerts via Google Apps Script, N8N webhook triggers, and
Mega Dashboard panel updates. Alerts fire automatically based on red line
rules — no confirmation needed.

Red line triggers:
    - Balance < $500 → SMS immediately
    - Bill overdue > 1 day → SMS + N8N escalation
    - 401K drops > 5% in one day → SMS alert
    - Unusual transaction > $200 → SMS alert
    - Cash flow forecast negative in 14 days → Dashboard alert

Network targets:
    - Google Apps Script (GOOGLE_APPS_SCRIPT_SMS_URL) for SMS
    - N8N (N8N_BASE_URL) for workflow triggers
    - Mega Dashboard (MEGA_DASHBOARD_URL) for panel updates
    - Weaviate (WEAVIATE_URL) for AlertLog persistence
"""

import os
from typing import Any

import aiohttp
from dotenv import load_dotenv

load_dotenv()

GOOGLE_APPS_SCRIPT_SMS_URL = os.getenv("GOOGLE_APPS_SCRIPT_SMS_URL", "")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "")
MEGA_DASHBOARD_URL = os.getenv("MEGA_DASHBOARD_URL", "")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")


async def send_sms_alert(message: str) -> dict[str, Any]:
    """Send an SMS alert to Shane via Google Apps Script.

    Args:
        message: Alert message text. Keep concise — ADHD-friendly.

    Returns:
        dict with keys: sent (bool), timestamp, message_id.
        Also logged to Weaviate AlertLog collection.

    Raises:
        aiohttp.ClientError: If Google Apps Script endpoint is unreachable.
    """
    pass


async def send_n8n_webhook(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Trigger an N8N workflow via webhook.

    Args:
        event: Event name that maps to an N8N workflow
            (e.g. 'bill_overdue', 'low_balance', 'fund_drop').
        payload: Data payload to send with the webhook trigger.

    Returns:
        dict with keys: triggered (bool), workflow_id, timestamp.

    Raises:
        aiohttp.ClientError: If N8N webhook endpoint is unreachable.
    """
    pass


async def push_to_dashboard(panel: str, data: dict[str, Any]) -> dict[str, Any]:
    """Push data to a Mega Dashboard HaloFinance panel.

    Args:
        panel: Panel identifier on the dashboard
            (e.g. 'balances', 'bills', 'funds', 'forecast').
        data: Data payload to display on the panel.

    Returns:
        dict with keys: updated (bool), panel, timestamp.

    Raises:
        aiohttp.ClientError: If Mega Dashboard is unreachable.
    """
    pass
