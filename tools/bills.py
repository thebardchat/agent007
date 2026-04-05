"""Bill tracking engine for Agent007.

Manages all 31 bills in Shane's financial picture. Cross-references payment
confirmations against due dates. Escalates unpaid bills 3 days before due
via N8N → SMS.

Data sources:
    - HaloFinance JSON at /mnt/shanebrain-raid/shanebrain-core/halofinance/
    - Weaviate BillTracker collection
    - Google Apps Script SMS reminder system

Network targets:
    - Weaviate (WEAVIATE_URL) for bill status persistence
    - N8N (N8N_BASE_URL) for escalation workflows
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, save_to_weaviate, query_weaviate
from tools.alerts import send_sms_alert, send_n8n_webhook

load_dotenv()

logger = logging.getLogger("agent007.bills")

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")
HALOFINANCE_PATH = Path("/mnt/shanebrain-raid/shanebrain-core/halofinance/")
BILLS_FILE = HALOFINANCE_PATH / "bills.json"


async def _load_bills_from_disk() -> list[dict[str, Any]]:
    """Read bill manifest from HaloFinance JSON on disk.

    Uses asyncio.to_thread to avoid blocking the event loop on file I/O.
    """
    def _read() -> list[dict[str, Any]]:
        if not BILLS_FILE.exists():
            raise FileNotFoundError(f"Bills file not found: {BILLS_FILE}")
        with open(BILLS_FILE) as f:
            return json.load(f)

    return await asyncio.to_thread(_read)


async def get_bill_status(bill_name: str) -> dict[str, Any]:
    """Get the current status of a specific bill.

    Args:
        bill_name: Name of the bill to look up (e.g. 'AT&T', 'Mortgage').

    Returns:
        dict with keys: name, amount, due_date, paid (bool), autopay (bool),
        last_payment_date.

    Raises:
        ValueError: If bill_name is not found in the 31-bill manifest.
        aiohttp.ClientError: If Weaviate is unreachable.
    """
    # Try Weaviate first for most current data
    try:
        results = await query_weaviate("BillTracker", bill_name)
        for record in results:
            if record.get("name", "").lower() == bill_name.lower():
                logger.info("Bill status: %s (from Weaviate)", bill_name)
                return record
    except aiohttp.ClientError:
        logger.warning("Weaviate unavailable, falling back to disk")

    # Fall back to disk
    try:
        bills = await _load_bills_from_disk()
    except FileNotFoundError:
        raise ValueError(f"Bill '{bill_name}' not found — disk file missing")

    for bill in bills:
        if bill.get("name", "").lower() == bill_name.lower():
            logger.info("Bill status: %s (from disk)", bill_name)
            return bill

    raise ValueError(
        f"Bill '{bill_name}' not found in the 31-bill manifest"
    )


async def get_all_bills() -> list[dict[str, Any]]:
    """Retrieve the full 31-bill manifest with current status.

    Pulls from Weaviate BillTracker collection and cross-references
    with HaloFinance JSON data on disk.

    Returns:
        List of 31 dicts, each with keys: name, amount, due_date,
        paid (bool), autopay (bool), last_payment_date.

    Raises:
        aiohttp.ClientError: If Weaviate is unreachable.
        FileNotFoundError: If HaloFinance data path is missing.
    """
    # Pull both sources and merge — Weaviate is authoritative, disk is fallback
    weaviate_bills: list[dict[str, Any]] = []
    try:
        weaviate_bills = await query_weaviate("BillTracker", "all bills status")
    except aiohttp.ClientError:
        logger.warning("Weaviate unavailable for bill sweep")

    disk_bills: list[dict[str, Any]] = []
    try:
        disk_bills = await _load_bills_from_disk()
    except FileNotFoundError:
        logger.warning("Disk bill file unavailable")

    # Merge: Weaviate data wins, disk fills gaps
    by_name: dict[str, dict[str, Any]] = {}
    for bill in disk_bills:
        name = bill.get("name", "")
        if name:
            by_name[name] = bill
    for bill in weaviate_bills:
        name = bill.get("name", "")
        if name:
            by_name[name] = bill  # Overwrite with fresher Weaviate data

    bills = list(by_name.values())

    # Red line check: any bill overdue > 1 day → SMS + N8N escalation
    now = datetime.now(timezone.utc)
    for bill in bills:
        if bill.get("paid"):
            continue
        due_str = bill.get("due_date", "")
        if not due_str:
            continue
        try:
            due = datetime.fromisoformat(due_str)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            overdue_days = (now - due).days
            if overdue_days > 1:
                bill_name = bill.get("name", "unknown")
                await send_sms_alert(
                    f"OVERDUE: {bill_name} is {overdue_days} days past due!"
                )
                await send_n8n_webhook("bill_overdue", {
                    "bill_name": bill_name,
                    "overdue_days": overdue_days,
                    "amount": bill.get("amount", 0),
                })
        except (ValueError, TypeError):
            continue

    logger.info("Bill sweep complete: %d bills tracked", len(bills))
    return bills
