"""N8N webhook trigger integrations for Agent007.

Manages webhook registrations and event dispatching to N8N workflows
running on Pulsar0100 (100.81.70.117:5678). Handles both inbound
webhooks (N8N → Agent007) and outbound triggers (Agent007 → N8N).

N8N workflows triggered:
    - chase_pull — Chase balance refresh (every 30 min)
    - bill_escalation — Overdue bill alert chain
    - nav_update — 401K NAV daily pull
    - sms_dispatch — SMS alert relay
    - snapshot_gen — Full snapshot generation (monthly)

Network targets:
    - N8N (N8N_BASE_URL) at http://100.81.70.117:5678
    - Weaviate (WEAVIATE_URL) for logging webhook events
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, save_to_weaviate

load_dotenv()

logger = logging.getLogger("agent007.webhooks")

N8N_BASE_URL = os.getenv("N8N_BASE_URL", "")
WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")

KNOWN_WORKFLOWS = {
    "chase_pull",
    "bill_escalation",
    "nav_update",
    "sms_dispatch",
    "snapshot_gen",
    "bill_overdue",
    "low_balance",
    "fund_drop",
}

INBOUND_EVENTS = {
    "balance_update",
    "payment_confirmed",
    "nav_ready",
}

# Webhook paths registered with N8N
WEBHOOK_REGISTRY = {
    "balance_update": "/webhook/agent007-balance-update",
    "payment_confirmed": "/webhook/agent007-payment-confirmed",
    "nav_ready": "/webhook/agent007-nav-ready",
}


async def register_webhooks() -> dict[str, Any]:
    """Register all Agent007 webhook endpoints with N8N.

    Sets up inbound webhook listeners for N8N to push data to Agent007
    (e.g. Chase balance updates, bill payment confirmations).

    Returns:
        dict with keys: registered (list of webhook names),
        count (int), timestamp.

    Raises:
        aiohttp.ClientError: If N8N is unreachable.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    session = await _get_session()
    registered = []

    for name, path in WEBHOOK_REGISTRY.items():
        try:
            async with session.post(
                f"{N8N_BASE_URL}/webhook/agent007-register",
                json={"webhook_name": name, "path": path},
            ) as resp:
                resp.raise_for_status()
                registered.append(name)
        except aiohttp.ClientError as exc:
            logger.warning("Failed to register webhook '%s': %s", name, exc)

    logger.info("Registered %d/%d webhooks with N8N", len(registered), len(WEBHOOK_REGISTRY))

    return {
        "registered": registered,
        "count": len(registered),
        "timestamp": timestamp,
    }


async def trigger_n8n_workflow(workflow_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Trigger a specific N8N workflow by name.

    Args:
        workflow_name: Name of the N8N workflow to trigger.
        payload: Data payload to pass to the workflow.

    Returns:
        dict with keys: triggered (bool), workflow_name,
        execution_id, timestamp.

    Raises:
        aiohttp.ClientError: If N8N webhook endpoint is unreachable.
        ValueError: If workflow_name is not recognized.
    """
    if workflow_name not in KNOWN_WORKFLOWS:
        raise ValueError(
            f"Unknown workflow '{workflow_name}'. "
            f"Known: {', '.join(sorted(KNOWN_WORKFLOWS))}"
        )

    timestamp = datetime.now(timezone.utc).isoformat()
    webhook_url = f"{N8N_BASE_URL}/webhook/agent007-{workflow_name}"

    session = await _get_session()
    try:
        async with session.post(
            webhook_url,
            json={"workflow": workflow_name, "payload": payload, "timestamp": timestamp},
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
            execution_id = body.get("executionId", "unknown")
    except aiohttp.ClientError as exc:
        logger.error("N8N workflow trigger failed for '%s': %s", workflow_name, exc)
        raise

    logger.info("Triggered N8N workflow: %s (exec=%s)", workflow_name, execution_id)

    return {
        "triggered": True,
        "workflow_name": workflow_name,
        "execution_id": execution_id,
        "timestamp": timestamp,
    }


async def handle_inbound_webhook(event: str, data: dict[str, Any]) -> dict[str, Any]:
    """Process an inbound webhook event from N8N.

    Routes events to the appropriate handler — updates Weaviate,
    triggers downstream tools, or fires alerts.

    Args:
        event: Event type received from N8N.
        data: Payload data from the N8N webhook.

    Returns:
        dict with keys: processed (bool), event, actions_taken (list).

    Raises:
        ValueError: If event type is not recognized.
    """
    if event not in INBOUND_EVENTS:
        raise ValueError(
            f"Unknown inbound event '{event}'. "
            f"Known: {', '.join(sorted(INBOUND_EVENTS))}"
        )

    actions: list[str] = []

    if event == "balance_update":
        # N8N pushed fresh Chase data — save to Weaviate
        await save_to_weaviate("FinanceSnapshots", {
            "source": "n8n_balance_update",
            **data,
        })
        actions.append("saved_balance_snapshot")

        # Check red lines inline
        checking = data.get("checking", 0)
        if isinstance(checking, (int, float)) and checking < 500:
            from tools.alerts import send_sms_alert
            await send_sms_alert("LOW BALANCE ALERT: Checking below $500 (via N8N).")
            actions.append("sms_low_balance")

    elif event == "payment_confirmed":
        # Mark bill as paid in Weaviate
        bill_name = data.get("bill_name", "")
        await save_to_weaviate("BillTracker", {
            "name": bill_name,
            "paid": True,
            "last_payment_date": data.get("payment_date", ""),
            **data,
        })
        actions.append(f"marked_paid:{bill_name}")

    elif event == "nav_ready":
        # Trigger NAV pull for all tickers
        from tools.funds import get_401k_nav, FUND_TICKERS
        for ticker in FUND_TICKERS:
            await get_401k_nav(ticker)
            actions.append(f"nav_pulled:{ticker}")

    logger.info("Inbound webhook processed: event=%s actions=%s", event, actions)

    return {"processed": True, "event": event, "actions_taken": actions}
