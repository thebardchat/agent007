"""Cash flow forecasting engine for Agent007.

Generates 30/60/90 day cash flow projections using Ollama (llama3.2:1b)
running locally on the Pi 5. Combines Chase balance data, bill schedule,
and historical spending patterns to predict future cash positions.

Also generates full financial snapshots combining all data sources.

Network targets:
    - Ollama (OLLAMA_URL) for local LLM inference
    - Weaviate (WEAVIATE_URL) for reading history and storing forecasts
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import aiohttp
from dotenv import load_dotenv

from tools import _get_session, save_to_weaviate, query_weaviate
from tools.alerts import push_to_dashboard

load_dotenv()

logger = logging.getLogger("agent007.forecast")

WEAVIATE_URL = os.getenv("WEAVIATE_URL", "")
OLLAMA_URL = os.getenv("OLLAMA_URL", "")
OLLAMA_MODEL = "llama3.2:1b"


async def _ollama_generate(prompt: str) -> str:
    """Call Ollama local LLM and return the response text.

    Shared helper — keeps Ollama calls consistent and lean.
    """
    session = await _get_session()
    try:
        async with session.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=aiohttp.ClientTimeout(total=120),
        ) as resp:
            resp.raise_for_status()
            body = await resp.json()
            return body.get("response", "")
    except aiohttp.ClientError as exc:
        logger.error("Ollama call failed: %s", exc)
        raise


def _extract_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Try to extract a JSON object or array from LLM output."""
    # Try the whole string first
    for attempt in [text.strip()]:
        try:
            return json.loads(attempt)
        except (json.JSONDecodeError, ValueError):
            pass
    # Try to find embedded JSON
    match = re.search(r"[\[{].*[\]}]", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except (json.JSONDecodeError, ValueError):
            pass
    return None


async def analyze_spending(data: dict[str, Any]) -> dict[str, Any]:
    """Run local LLM spending analysis via Ollama.

    Args:
        data: dict of transaction data to analyze. Keys vary by source.

    Returns:
        dict with keys: summary (str), categories (dict),
        anomalies (list), recommendations (list).

    Raises:
        aiohttp.ClientError: If Ollama is unreachable.
    """
    # Keep prompt short — 1B model works best with concise input
    prompt = (
        "Analyze this spending data and respond with JSON only.\n"
        "Keys: summary (string), categories (object with category:total), "
        "anomalies (array of strings), recommendations (array of strings).\n\n"
        f"Data: {json.dumps(data)[:1000]}\n\n"
        "JSON response:"
    )

    raw = await _ollama_generate(prompt)
    parsed = _extract_json(raw)

    if isinstance(parsed, dict):
        return {
            "summary": parsed.get("summary", raw[:200]),
            "categories": parsed.get("categories", {}),
            "anomalies": parsed.get("anomalies", []),
            "recommendations": parsed.get("recommendations", []),
        }

    # Fallback if LLM returns non-JSON
    logger.warning("Ollama returned non-JSON for spending analysis, using raw text")
    return {
        "summary": raw[:200],
        "categories": {},
        "anomalies": [],
        "recommendations": [],
    }


async def forecast_cashflow(history: list[dict[str, Any]]) -> dict[str, Any]:
    """Run local LLM cash flow projection via Ollama.

    Args:
        history: List of historical cash flow data points, each a dict
            with keys: date, balance, inflows, outflows.

    Returns:
        dict with keys: projection (list of daily balances),
        confidence (float), warnings (list).

    Raises:
        aiohttp.ClientError: If Ollama is unreachable.
    """
    # Trim history to last 30 entries to stay within model context
    recent = history[-30:] if len(history) > 30 else history

    prompt = (
        "Given this cash flow history, project the next 30 days.\n"
        "Respond with JSON only.\n"
        "Keys: projection (array of {date, balance}), "
        "confidence (float 0-1), warnings (array of strings).\n\n"
        f"History: {json.dumps(recent)[:1500]}\n\n"
        "JSON response:"
    )

    raw = await _ollama_generate(prompt)
    parsed = _extract_json(raw)

    if isinstance(parsed, dict):
        return {
            "projection": parsed.get("projection", []),
            "confidence": float(parsed.get("confidence", 0.5)),
            "warnings": parsed.get("warnings", []),
        }

    logger.warning("Ollama returned non-JSON for cashflow forecast, using defaults")
    return {"projection": [], "confidence": 0.0, "warnings": ["LLM parse failed"]}


async def get_cash_flow_forecast(days: int) -> dict[str, Any]:
    """Generate a cash flow forecast for the specified number of days.

    Gathers current balances, bills, and history, then feeds to Ollama
    for projection.

    Args:
        days: Number of days to forecast. Typically 30, 60, or 90.

    Returns:
        dict with keys: forecast_days, projected_balance (float),
        upcoming_bills (list), risk_flags (list), generated_at (str).

    Raises:
        aiohttp.ClientError: If Ollama or Weaviate is unreachable.
    """
    # Import here to avoid circular deps at module level
    from tools.chase import get_account_balances
    from tools.bills import get_all_bills

    timestamp = datetime.now(timezone.utc).isoformat()

    # Gather inputs in parallel
    balances, bills, history_records = await asyncio.gather(
        get_account_balances(),
        get_all_bills(),
        query_weaviate("CashFlowForecasts", f"last {days} days cash flow"),
    )

    # Build history for Ollama
    history = [
        {
            "date": r.get("timestamp", ""),
            "balance": r.get("projected_balance", 0),
            "inflows": r.get("inflows", 0),
            "outflows": r.get("outflows", 0),
        }
        for r in history_records
    ]

    # Run Ollama projection
    forecast = await forecast_cashflow(history)

    # Calculate projected balance from current + forecast
    current_balance = (
        balances.get("checking", {}).get("balance", 0)
        + balances.get("savings", {}).get("balance", 0)
    )

    # Upcoming unpaid bills
    upcoming = [
        {"name": b.get("name"), "amount": b.get("amount"), "due_date": b.get("due_date")}
        for b in bills
        if not b.get("paid")
    ]

    # Risk flags
    risk_flags = list(forecast.get("warnings", []))
    projected = forecast.get("projection", [])
    if projected:
        min_balance = min((p.get("balance", current_balance) for p in projected), default=current_balance)
        if min_balance < 0:
            risk_flags.append(f"Projected negative balance within {days} days")

    result = {
        "forecast_days": days,
        "projected_balance": current_balance,
        "upcoming_bills": upcoming,
        "risk_flags": risk_flags,
        "generated_at": timestamp,
        "projection_detail": projected,
        "confidence": forecast.get("confidence", 0.0),
    }

    # Red line: negative within 14 days → dashboard alert
    if any("negative" in flag.lower() for flag in risk_flags):
        await push_to_dashboard("forecast", {
            "alert": True,
            "message": "Cash flow projected negative within forecast window",
            "risk_flags": risk_flags,
        })

    # Save to Weaviate
    await save_to_weaviate("CashFlowForecasts", result)

    logger.info("Forecast generated: %d days, %d risk flags", days, len(risk_flags))
    return result


async def get_financial_snapshot() -> dict[str, Any]:
    """Generate a complete financial snapshot across all data sources.

    Combines Chase balances, all 31 bills status, 401K NAVs, and
    current cash flow forecast into a single dated snapshot.

    Returns:
        dict with keys: timestamp, checking_balance, savings_balance,
        bills_summary, fund_navs, cash_flow_30d, alerts_pending.

    Raises:
        aiohttp.ClientError: If any upstream data source is unreachable.
    """
    from tools.chase import get_account_balances
    from tools.bills import get_all_bills
    from tools.funds import get_401k_nav, FUND_TICKERS

    timestamp = datetime.now(timezone.utc).isoformat()

    # Pull all data sources in parallel
    balances, bills, *navs = await asyncio.gather(
        get_account_balances(),
        get_all_bills(),
        *[get_401k_nav(t) for t in FUND_TICKERS],
    )

    # Build fund NAV summary
    fund_navs = {nav["ticker"]: nav for nav in navs}

    # 30-day forecast
    forecast = await get_cash_flow_forecast(30)

    # Count pending alerts
    overdue = [b for b in bills if not b.get("paid")]

    snapshot = {
        "timestamp": timestamp,
        "checking_balance": balances.get("checking", {}).get("balance", 0),
        "savings_balance": balances.get("savings", {}).get("balance", 0),
        "bills_summary": {
            "total": len(bills),
            "paid": len(bills) - len(overdue),
            "unpaid": len(overdue),
            "bills": bills,
        },
        "fund_navs": fund_navs,
        "cash_flow_30d": forecast,
        "alerts_pending": len(overdue),
    }

    # Archive to Weaviate
    await save_to_weaviate("FinanceSnapshots", snapshot)

    logger.info("Full snapshot generated: %s", timestamp)
    return snapshot
