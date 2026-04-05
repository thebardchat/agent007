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

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, save_to_weaviate

load_dotenv()

logger = logging.getLogger("agent007.alerts")

GOOGLE_APPS_SCRIPT_SMS_URL = os.getenv("GOOGLE_APPS_SCRIPT_SMS_URL", "")
N8N_BASE_URL = os.getenv("N8N_BASE_URL", "")
MEGA_DASHBOARD_URL = os.getenv("MEGA_DASHBOARD_URL", "")


async def send_sms_alert(message: str) -> dict[str, Any]:
    """Send an SMS alert to Shane via Google Apps Script.

    Args:
        message: Alert message text. Truncated to 160 chars (SMS limit).

    Returns:
        dict with keys: sent (bool), timestamp, message_id.

    Raises:
        aiohttp.ClientError: If Google Apps Script endpoint is unreachable.
    """
    message_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    # SMS limit
    truncated = message[:160]

    session = await _get_session()
    try:
        async with session.post(
            GOOGLE_APPS_SCRIPT_SMS_URL,
            json={"message": truncated},
        ) as resp:
            resp.raise_for_status()
            logger.info("SMS sent (id=%s): %s", message_id[:8], truncated[:50])
    except aiohttp.ClientError as exc:
        logger.error("SMS dispatch failed: %s", exc)
        raise

    # Log to Weaviate AlertLog for audit trail
    await save_to_weaviate("AlertLog", {
        "alert_type": "sms",
        "message": truncated,
        "message_id": message_id,
        "sent": True,
        "timestamp": timestamp,
    })

    return {"sent": True, "timestamp": timestamp, "message_id": message_id}


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
    timestamp = datetime.now(timezone.utc).isoformat()
    webhook_url = f"{N8N_BASE_URL}/webhook/agent007-{event}"

    session = await _get_session()
    try:
        async with session.post(
            webhook_url,
            json={"event": event, "payload": payload, "timestamp": timestamp},
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
            workflow_id = body.get("workflowId", "unknown")
    except aiohttp.ClientError as exc:
        logger.error("N8N webhook failed for event '%s': %s", event, exc)
        raise

    logger.info("N8N triggered: event=%s workflow=%s", event, workflow_id)

    return {"triggered": True, "workflow_id": workflow_id, "timestamp": timestamp}


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
    timestamp = datetime.now(timezone.utc).isoformat()
    panel_url = f"{MEGA_DASHBOARD_URL}/api/panels/halofinance/{panel}"

    session = await _get_session()
    try:
        async with session.post(
            panel_url,
            json={"panel": panel, "data": data, "updated_at": timestamp},
        ) as resp:
            resp.raise_for_status()
    except aiohttp.ClientError as exc:
        logger.error("Dashboard push failed for panel '%s': %s", panel, exc)
        raise

    logger.info("Dashboard updated: panel=%s", panel)

    return {"updated": True, "panel": panel, "timestamp": timestamp}
