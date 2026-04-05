"""Sub-agent implementations for Agent007.

Maps agent type strings to their implementation classes for
dynamic import by the SubAgentRegistry.
"""

from agents.implementations.bill_tracker import BillTrackerAgent
from agents.implementations.balance_monitor import BalanceMonitorAgent
from agents.implementations.fund_watcher import FundWatcherAgent
from agents.implementations.cash_flow_forecaster import CashFlowForecasterAgent
from agents.implementations.anomaly_detector import AnomalyDetectorAgent

AGENT_IMPLEMENTATIONS = {
    "bill-tracker": BillTrackerAgent,
    "balance-monitor": BalanceMonitorAgent,
    "fund-watcher": FundWatcherAgent,
    "cash-flow-forecaster": CashFlowForecasterAgent,
    "anomaly-detector": AnomalyDetectorAgent,
}

__all__ = [
    "BillTrackerAgent",
    "BalanceMonitorAgent",
    "FundWatcherAgent",
    "CashFlowForecasterAgent",
    "AnomalyDetectorAgent",
    "AGENT_IMPLEMENTATIONS",
]
