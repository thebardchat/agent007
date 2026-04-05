"""Agent007 financial tools package.

Contains modules for Chase bank access, bill tracking, 401K fund monitoring,
cash flow forecasting, and alert dispatch within the ShaneBrain ecosystem.

Also provides cross-cutting Weaviate storage tools used by all modules:
    - save_to_weaviate()  — persist financial records
    - query_weaviate()    — semantic search history
    - log_transaction()   — audit trail

Weaviate collections:
    - FinanceSnapshots  — dated full financial pictures
    - BillTracker       — 31 bills, status, history
    - CashFlowForecasts — 30/60/90 day projections
    - FundNAVHistory    — daily 401K NAV records
    - AlertLog          — all alerts sent with timestamps
    - AgentRegistry     — sub-agent specs and runtime state
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("agent007.tools")

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")

VALID_COLLECTIONS = {
    "FinanceSnapshots",
    "BillTracker",
    "CashFlowForecasts",
    "FundNAVHistory",
    "AlertLog",
    "AgentRegistry",
}

# --- Shared aiohttp session (one per process, pooled) ---

_session: aiohttp.ClientSession | None = None


async def _get_session() -> aiohttp.ClientSession:
    """Lazily create a single pooled aiohttp session for all tool modules."""
    global _session
    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(limit=5)
        _session = aiohttp.ClientSession(connector=connector)
    return _session


async def close_session() -> None:
    """Close the shared aiohttp session. Call on shutdown."""
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None


# --- Financial log masking ---

def mask_financial(value: float) -> str:
    """Mask a dollar amount into a range string for safe logging.

    Never log exact balances — CLAUDE.md security rule.
    """
    if value < 0:
        return "negative"
    if value < 500:
        return "< $500"
    if value < 1_000:
        return "$500–$1K"
    if value < 5_000:
        return "$1K–$5K"
    if value < 10_000:
        return "$5K–$10K"
    if value < 50_000:
        return "$10K–$50K"
    return "> $50K"


def _validate_collection(collection: str) -> None:
    """Raise ValueError if collection is not in the allowlist."""
    if collection not in VALID_COLLECTIONS:
        raise ValueError(
            f"Unknown collection '{collection}'. "
            f"Valid: {', '.join(sorted(VALID_COLLECTIONS))}"
        )


# --- Weaviate storage tools ---

async def save_to_weaviate(collection: str, data: dict[str, Any]) -> dict[str, Any]:
    """Persist a financial record to a Weaviate collection.

    Args:
        collection: Target Weaviate collection name.
        data: Record data to store.

    Returns:
        dict with keys: saved (bool), collection, object_id, timestamp.

    Raises:
        aiohttp.ClientError: If Weaviate is unreachable.
        ValueError: If collection name is not recognized.
    """
    _validate_collection(collection)

    timestamp = datetime.now(timezone.utc).isoformat()
    record = {**data, "timestamp": data.get("timestamp", timestamp)}
    object_id = str(uuid.uuid4())

    session = await _get_session()
    payload = {
        "class": collection,
        "id": object_id,
        "properties": record,
    }

    try:
        async with session.post(
            f"{WEAVIATE_URL}/v1/objects",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            logger.info("Saved to %s (id=%s)", collection, object_id[:8])
    except aiohttp.ClientError as exc:
        logger.error("Weaviate save failed for %s: %s", collection, exc)
        raise

    return {
        "saved": True,
        "collection": collection,
        "object_id": object_id,
        "timestamp": timestamp,
    }


async def query_weaviate(collection: str, query: str) -> list[dict[str, Any]]:
    """Perform a semantic search against a Weaviate collection.

    Args:
        collection: Weaviate collection to search.
        query: Natural language search query.

    Returns:
        List of matching records (max 10), each a dict with
        relevance score and full record data.

    Raises:
        aiohttp.ClientError: If Weaviate is unreachable.
        ValueError: If collection name is not recognized.
    """
    _validate_collection(collection)

    # Weaviate GraphQL nearText query — limit 10 to conserve Pi RAM
    graphql = {
        "query": (
            "{ Get { "
            f"{collection}("
            f'nearText: {{concepts: ["{query}"]}}, '
            "limit: 10"
            ") { _additional { id distance } } } }"
        )
    }

    session = await _get_session()
    try:
        async with session.post(
            f"{WEAVIATE_URL}/v1/graphql",
            json=graphql,
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
    except aiohttp.ClientError as exc:
        logger.error("Weaviate query failed for %s: %s", collection, exc)
        raise

    # Parse GraphQL response into flat list
    results = []
    raw = (
        body.get("data", {})
        .get("Get", {})
        .get(collection, [])
    )
    for item in raw:
        additional = item.pop("_additional", {})
        results.append({
            "score": additional.get("distance", 0.0),
            "id": additional.get("id", ""),
            **item,
        })

    logger.info("Queried %s: %d results for '%s'", collection, len(results), query[:40])
    return results


async def log_transaction(type: str, amount: float, description: str) -> dict[str, Any]:
    """Log a transaction to the Weaviate audit trail.

    Args:
        type: Transaction type (e.g. 'income', 'expense', 'transfer', 'bill_payment').
        amount: Transaction amount as float.
        description: Human-readable description of the transaction.

    Returns:
        dict with keys: logged (bool), transaction_id, timestamp.

    Raises:
        aiohttp.ClientError: If Weaviate is unreachable.
    """
    transaction_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    record = {
        "transaction_id": transaction_id,
        "type": type,
        "amount": amount,
        "description": description,
        "timestamp": timestamp,
    }

    # Mask amount in logs — never expose exact figures
    logger.info(
        "Transaction: type=%s amount=%s desc=%s",
        type, mask_financial(amount), description[:50],
    )

    await save_to_weaviate("AlertLog", record)

    return {
        "logged": True,
        "transaction_id": transaction_id,
        "timestamp": timestamp,
    }
